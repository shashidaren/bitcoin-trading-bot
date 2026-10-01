#!/usr/bin/env python3
"""
live_readiness - "is the BTC book ready for real money?", in numbers.

The other tools answer "what did the book do?". This one answers the question
the handoff keeps deferring: does the forward-test evidence justify risking
money, and how much of that evidence is noise?  It is the reproducible source
of every number in docs/REVIEW-2026-10-01.md (same loaders and era constants as
the rest of the suite - tools/replay_lib.py).

Sections
  1. EDGE        t-stat, bootstrap P(net/trade > 0) iid and by calendar day,
                 net R/trade, and how many trades it takes to confirm the edge
  2. COST        break-even round-trip spread and net P/L across spreads
  3. FRAGILITY   how much of the net P/L is the best few trades / best days
  4. WHERE       exploratory post-hoc cuts (ATR bucket, side, weekday/weekend):
                 HYPOTHESES for prospective logging, never parameters
  5. STABILITY   halves, last-N, per-week, drawdown, and a Monte Carlo of what a
                 0.01-lot account would see if the edge is real vs if it is zero,
                 incl. how often a candidate kill-switch floor would be touched
  6. LATENCY     M5 re-walk with the fill 1/2.5/5 minutes after the signal bar
                 (the simulator fills at the signal-bar close; a live order cannot)
  7. OPERATIONS  price-log coverage and gaps (a dead feed is a live-money risk)
  8. GATES       proposed go/no-go evidence gates + the non-data checklist

Everything is the strictly post-gate slice (entries >= replay_lib.GATES_DEPLOY,
the date today's entry gates actually went live) because earlier rows ran other
rules (docs/HANDOFF.md §9). P/L is NET of --spread per trade; the ledger itself
is gross. Unlike the other tools this one DEFAULTS to the measured $0.40 (a
go/no-go on gross numbers would be misleading); --spread 0 gives gross. Deterministic:
the bootstrap/Monte Carlo use a seeded RNG, so the same data gives the same output.

The gate thresholds below are PROPOSALS, not facts about the market - they are
constants at the top of this file on purpose, so the user can change them in one
place. Passing every data gate is NECESSARY, not sufficient: the non-data
checklist (live order path, spread profile, demo parity, kill switches) decides
the rest.

Usage:
  python3 tools/live_readiness.py --spread 0.40            # the handoff's measured cost (also the default)
  python3 tools/live_readiness.py --spread 0.40 --horizon 200 --boot 20000

Exit code: 0 = every data gate passes, 1 = at least one fails (so a script can
branch on it). Read-only: nothing is written to disk and no network is used.
Pure stdlib.
"""
import argparse
import bisect
import math
import os
import random
import statistics as st
import sys
from collections import defaultdict
from datetime import timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import replay_lib as R  # noqa: E402

ROOT = os.path.dirname(HERE)

# ---- proposed gate thresholds (edit here, not in the logic) -----------------
MIN_TRADES = 100          # strictly post-gate closed trades
MIN_P_EDGE = 0.90         # day-block bootstrap P(net/trade > 0)
MIN_SPREAD_COVER = 2.0    # break-even spread must be >= this x the assumed spread
TOP_FRAC = 0.05           # best 5% of trades (>= 3) are removed in the fragility gate
RECENT_N = 25             # most recent closed trades that must not be net-negative
MAX_GAP_MIN = 60          # longest tolerated price-log gap ...
GAP_WINDOW_DAYS = 14      # ... inside this trailing window of the log
FEED_GAP_FLAG_MIN = 15    # check_data's gap threshold (M5)
Z_ALPHA = 1.96            # two-sided 5%
Z_POWER = 0.8416          # 80% power
MC_PATHS = 6000           # Monte Carlo paths per scenario
KILL_FLOORS = (20, 30, 40, 50)   # $ drawdown floors whose touch probability is reported


# --------------------------------------------------------------------------- #
# small statistics helpers
# --------------------------------------------------------------------------- #
def norm_cdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def pct(sorted_xs, q):
    return sorted_xs[min(len(sorted_xs) - 1, max(0, int(q * len(sorted_xs))))]


def boot_iid(xs, B, rng):
    m = len(xs)
    out = sorted(sum(xs[rng.randrange(m)] for _ in range(m)) / m for _ in range(B))
    return out


def boot_days(groups, B, rng):
    """Resample whole calendar days (trades cluster by day), mean per trade."""
    keys = list(groups)
    nd = len(keys)
    out = []
    for _ in range(B):
        tot = cnt = 0
        for _ in range(nd):
            g = groups[keys[rng.randrange(nd)]]
            tot += sum(g)
            cnt += len(g)
        out.append(tot / cnt)
    out.sort()
    return out


def fisher_two_sided(a, b, c, d):
    """Fisher exact p for [[a,b],[c,d]] (wins/losses of two groups)."""
    n = a + b + c + d

    def hyp(x, y, z, w):
        return math.comb(x + y, x) * math.comb(z + w, z) / math.comb(n, x + z)

    p_obs = hyp(a, b, c, d)
    tot = 0.0
    for x in range(0, min(a + b, a + c) + 1):
        y, z = (a + b) - x, (a + c) - x
        w = (c + d) - z
        if min(y, z, w) < 0:
            continue
        p = hyp(x, y, z, w)
        if p <= p_obs + 1e-12:
            tot += p
    return min(1.0, tot)


def equity_stats(seq):
    """seq = [(exit_dt, net)] chronological -> (final, maxdd, loss_streak, underwater_trades, underwater_days)."""
    eq = peak = mdd = 0.0
    streak = best_streak = 0
    peak_i, peak_t = 0, seq[0][0]
    uw_trades, uw_days = 0, 0.0
    for i, (xt, x) in enumerate(seq):
        eq += x
        if x <= 0:
            streak += 1
            best_streak = max(best_streak, streak)
        else:
            streak = 0
        if eq > peak:
            peak, peak_i, peak_t = eq, i, xt
        else:
            uw_trades = max(uw_trades, i - peak_i)
            uw_days = max(uw_days, (xt - peak_t).total_seconds() / 86400)
        mdd = max(mdd, peak - eq)
    return eq, mdd, best_streak, uw_trades, uw_days


def monte_carlo(xs, horizon, B, rng, floors=()):
    """Bootstrap paths of `horizon` trades. Returns (sorted finals, sorted max drawdowns,
    {floor: P(equity touches -floor at any point)})."""
    m = len(xs)
    finals, dds = [], []
    touched = {f: 0 for f in floors}
    for _ in range(B):
        eq = peak = mdd = lowest = 0.0
        for _ in range(horizon):
            eq += xs[rng.randrange(m)]
            if eq > peak:
                peak = eq
            elif peak - eq > mdd:
                mdd = peak - eq
            if eq < lowest:
                lowest = eq
        finals.append(eq)
        dds.append(mdd)
        for f in floors:
            if lowest <= -f:
                touched[f] += 1
    finals.sort()
    dds.sort()
    return finals, dds, {f: touched[f] / B for f in floors}


def latency_stress(pg, bars, spread):
    """Re-walk the post-gate trades on the M5 log with the fill a fraction of the NEXT bar
    after the signal bar (0 = the simulator's fill at the signal-bar close, 1 = the next bar's
    close). SL/TP keep their ATR distances from the delayed fill price, as the live order
    would. An M5 walk is coarse (SL-first on ambiguous bars, TIME marked at 240 min), so read
    the rows RELATIVE to each other, not against the ledger."""
    dts = [b["dt"] for b in bars]
    rows = []
    for frac in (0.0, 0.2, 0.5, 1.0):
        tot, n, w, l = 0.0, 0, 0, 0
        for t in pg:
            j = bisect.bisect_left(dts, t["et"] - timedelta(seconds=150))
            if j >= len(dts) or abs((dts[j] - t["et"]).total_seconds()) > 150 or j + 2 >= len(bars):
                continue
            atr = abs(t["entry"] - t["sl"]) / R.ATR_SL_MULT
            c0, c1 = t["entry"], bars[j + 1]["c"]
            if frac >= 1.0:
                e, seg = c1, bars[j + 2:]
            else:
                e, seg = c0 + frac * (c1 - c0), bars[j + 1:]
            out, r, _, _ = R.walk(e, t["side"], atr, seg, horizon_min=240)
            tot += r * R.r_money(atr) - spread
            n += 1
            w += out == "TP"
            l += out == "SL"
        rows.append((frac, n, w, l, tot))
    return rows


def line(label, ts, spread):
    n = len(ts)
    if not n:
        return f"  {label:30s} n=  0"
    w = sum(1 for t in ts if t["profit"] > 0)
    g = sum(t["profit"] for t in ts)
    net = g - spread * n
    lo, hi = R.wilson(w, n)
    return (f"  {label:30s} n={n:3d} {w:2d}W/{n - w:2d}L WR {100 * w / n:5.1f}% [{lo:4.1f},{hi:4.1f}]"
            f"  gross {g:+7.2f}  net {net:+7.2f}  net/trade {net / n:+6.2f}")


# --------------------------------------------------------------------------- #
def feed_report(bars):
    """Gaps > FEED_GAP_FLAG_MIN between consecutive logged M5 bars + slot coverage.

    Slots are counted exactly like tools/check_data.py: rows are stamped at the bar
    close (a :01/:02 second offset is normal), so group by minute; repeated minutes
    are one slot, not extra coverage."""
    gaps = []
    for a, b in zip(bars, bars[1:]):
        m = (b["dt"] - a["dt"]).total_seconds() / 60
        if m > FEED_GAP_FLAG_MIN:
            gaps.append((a["dt"], b["dt"], m))
    have = {b["dt"].replace(second=0) for b in bars}
    t, end = bars[0]["dt"].replace(second=0), bars[-1]["dt"]
    expected = missing = 0
    while t <= end:
        expected += 1
        missing += t not in have
        t += timedelta(minutes=5)
    return gaps, expected - missing, expected, missing


def main():
    ap = argparse.ArgumentParser(description="BTC live-readiness evidence + gates")
    ap.add_argument("--spread", type=float, default=0.40,
                    help="round-trip $/trade at 0.01 lot. Default 0.40 = the handoff's measured cost "
                         "(unlike the other tools, which default to gross: a readiness verdict on "
                         "gross numbers would be misleading). 0 = gross.")
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--boot", type=int, default=5000, help="bootstrap iterations")
    ap.add_argument("--horizon", type=int, default=100, help="Monte Carlo trades per path")
    ap.add_argument("--root", default=ROOT)
    a = ap.parse_args()
    sp = a.spread
    rng = random.Random(a.seed)

    trades = R.load_trades(os.path.join(a.root, "trades.csv"))
    bars = R.load_bars(os.path.join(a.root, "forward_test_log.csv"))
    pg = [t for t in trades if t["et"] >= R.GATES_DEPLOY]
    n = len(pg)
    if n < 10:
        print(f"live_readiness: only {n} post-gate trades - nothing meaningful to say yet")
        return 1

    nets = [t["profit"] - sp for t in pg]
    gross = [t["profit"] for t in pg]
    oneR = [abs(t["entry"] - t["sl"]) * R.LOT_SIZE for t in pg]
    span_days = (pg[-1]["xt"] - pg[0]["et"]).total_seconds() / 86400
    per_week = n / span_days * 7
    wins = sum(1 for t in pg if t["profit"] > 0)
    mu, sd = st.mean(nets), st.stdev(nets)
    se = sd / math.sqrt(n)
    tstat = mu / se if se else 0.0

    print(f"live_readiness - {n} post-gate trades (entries >= {R.GATES_DEPLOY:%Y-%m-%d}) of {len(trades)} total, "
          f"{len(bars)} M5 bars, spread ${sp:.2f}/trade, seed {a.seed}")
    print(f"  span {span_days:.1f} days, {n / span_days:.1f} trades/day ({per_week:.1f}/week); "
          f"P/L below is {'NET of the spread' if sp else 'GROSS'}")
    if not sp:
        print("  WARNING: --spread 0 is GROSS. Every figure below ignores trading cost, so the gates are")
        print("           not meaningful. Use --spread 0.40 (the default) for any live-readiness conclusion.")

    # ---- 1. EDGE -----------------------------------------------------------
    print("\n== 1. EDGE: is it distinguishable from zero? ==")
    print(line("post-gate", pg, sp))
    print(f"  net/trade {mu:+.3f}  sd {sd:.2f}  se {se:.3f}  t {tstat:+.2f}  "
          f"one-sided p~{1 - norm_cdf(tstat):.2f}  95% CI [{mu - 1.997 * se:+.2f}, {mu + 1.997 * se:+.2f}]")
    b_iid = boot_iid(nets, a.boot, rng)
    by_day = defaultdict(list)
    for t, x in zip(pg, nets):
        by_day[t["xt"].date()].append(x)
    b_day = boot_days(by_day, a.boot, rng)
    p_iid = sum(1 for x in b_iid if x > 0) / len(b_iid)
    p_day = sum(1 for x in b_day if x > 0) / len(b_day)
    print(f"  bootstrap P(net/trade > 0): iid {100 * p_iid:.0f}% | by calendar day ({len(by_day)} days) {100 * p_day:.0f}%"
          f"   95% band by day [{pct(b_day, .025):+.2f}, {pct(b_day, .975):+.2f}]")
    r_g = [g / o for g, o in zip(gross, oneR)]
    r_n = [x / o for x, o in zip(nets, oneR)]
    cost_share = [sp / o for o in oneR]
    print(f"  per-trade R: gross {st.mean(r_g):+.2f}  net {st.mean(r_n):+.2f}   "
          f"median 1R ${st.median(oneR):.2f}; spread = {100 * st.median(cost_share):.0f}% of median 1R "
          f"(worst trade {100 * max(cost_share):.0f}%)")
    if mu > 0:
        n_obs = ((Z_ALPHA + Z_POWER) * sd / mu) ** 2
        n_half = ((Z_ALPHA + Z_POWER) * sd / (mu / 2)) ** 2
        print(f"  trades needed to confirm (80% power, 5% two-sided): {n_obs:,.0f} if the true edge is the observed "
              f"${mu:.2f}/trade (~{max(0, n_obs - n) / per_week:.0f} more weeks); {n_half:,.0f} if it is half that "
              f"(~{max(0, n_half - n) / per_week:.0f} more weeks)")
    else:
        print("  observed net/trade is not positive - nothing to confirm")

    # ---- 2. COST -----------------------------------------------------------
    print("\n== 2. COST: how much room is there? ==")
    g_mean = st.mean(gross)
    print(f"  gross/trade {g_mean:+.3f} => break-even round trip ${g_mean:.2f}/trade (${100 * g_mean:.0f}/BTC at 0.01 lot);"
          f" assumed ${sp:.2f} => cover {g_mean / sp:.1f}x" if sp else f"  gross/trade {g_mean:+.3f}")
    row = "  net P/L at spread $/trade:  "
    for s in (0.25, 0.40, 0.60, 0.80, 1.00, 1.50):
        row += f"{s:.2f}: {sum(gross) - s * n:+7.2f}   "
    print(row)
    be_wr = (1 + sp / st.median(oneR)) / 3 if sp else 1 / 3
    lo, hi = R.wilson(wins, n)
    print(f"  cost-adjusted break-even WR at median 1R ${st.median(oneR):.2f}: {100 * be_wr:.1f}%   "
          f"observed {100 * wins / n:.1f}% (Wilson {lo:.1f}-{hi:.1f})")

    # ---- 3. FRAGILITY ------------------------------------------------------
    print("\n== 3. FRAGILITY: how many trades carry the result? ==")
    total = sum(nets)
    ranked = sorted(nets, reverse=True)
    for k in (1, 3, 5, 10):
        s = sum(ranked[:k])
        print(f"  best {k:2d} trades = {s:+7.2f} ({100 * s / total if total else 0:4.0f}% of net);"
              f" net without them {total - s:+7.2f}")
    days_sorted = sorted(((sum(v), d) for d, v in by_day.items()), reverse=True)
    top3 = sum(v for v, _ in days_sorted[:3])
    print(f"  best 3 days {[str(d) for _, d in days_sorted[:3]]} = {top3:+.2f} "
          f"({100 * top3 / total if total else 0:.0f}% of net); net without them {total - top3:+.2f}")
    up = [v for v in (sum(g) for g in by_day.values()) if v > 0]
    dn = [v for v in (sum(g) for g in by_day.values()) if v <= 0]
    print(f"  days up {len(up)} (avg {st.mean(up) if up else 0:+.2f}) / down {len(dn)} (avg {st.mean(dn) if dn else 0:+.2f})")

    # ---- 4. WHERE ----------------------------------------------------------
    print("\n== 4. WHERE THE EDGE LIVES (post-hoc cuts of one regime - hypotheses, not parameters) ==")
    for lo_a, hi_a in ((0, 60), (60, 90), (90, 130), (130, 1e9)):
        ts = [t for t in pg if lo_a <= t["atr"] < hi_a]
        if not ts:
            continue
        r1 = st.median([abs(t["entry"] - t["sl"]) * R.LOT_SIZE for t in ts])
        be = (1 + sp / r1) / 3
        hi_lbl = "inf" if hi_a > 1e8 else str(int(hi_a))
        print(line(f"entry ATR ${int(lo_a)}-{hi_lbl}", ts, sp) + f"   [cost {100 * sp / r1:.0f}% of 1R, BE WR {100 * be:.0f}%]")
    if sp:
        cs = [(sp / (abs(t["entry"] - t["sl"]) * R.LOT_SIZE), t) for t in pg]
        for lo_c, hi_c in ((0, .20), (.20, .30), (.30, .40), (.40, 99)):
            ts = [t for c, t in cs if lo_c <= c < hi_c]
            if ts:
                hi_lbl = "inf" if hi_c > 1 else f"{int(100 * hi_c)}"
                print(line(f"spread = {int(100 * lo_c)}-{hi_lbl}% of 1R", ts, sp))
        print("  a spread guard that blocked cost-share > X would have (in-sample, retrospective):")
        for x in (.25, .30, .40):
            keep = sum(t["profit"] - sp for c, t in cs if c <= x)
            blk = [t for c, t in cs if c > x]
            print(f"    X={x:.2f}: keeps {len(cs) - len(blk):2d} trades net {keep:+7.2f}   "
                  f"blocks {len(blk):2d} trades net {sum(t['profit'] - sp for t in blk):+7.2f}")
    for side in ("BUY", "SELL"):
        print(line(f"side {side}", [t for t in pg if t["side"] == side], sp))
    wk = [t for t in pg if t["et"].weekday() < 5]
    we = [t for t in pg if t["et"].weekday() >= 5]
    print(line("weekday entries", wk, sp))
    print(line("weekend entries (Sat/Sun)", we, sp))
    if we and wk:
        ww, wl = sum(1 for t in we if t["profit"] > 0), sum(1 for t in we if t["profit"] <= 0)
        kw, kl = sum(1 for t in wk if t["profit"] > 0), sum(1 for t in wk if t["profit"] <= 0)
        wk_days = sorted({t["et"].date() for t in we})
        print(f"  weekend vs weekday win rate: Fisher exact p = {fisher_two_sided(ww, wl, kw, kl):.3f}; "
              f"{len(wk_days)} weekend dates. This is one of ~10 slices looked at - a Bonferroni bar is ~0.005.")

    # ---- 5. STABILITY AND RISK --------------------------------------------
    print("\n== 5. STABILITY AND RISK ==")
    half = n // 2
    print(line("first half (older)", pg[:half], sp))
    print(line("second half (newer)", pg[half:], sp))
    print(line(f"last {RECENT_N} closed", sorted(pg, key=lambda t: t["xt"])[-RECENT_N:], sp))
    weekly = defaultdict(list)
    for t in pg:
        weekly[t["et"].isocalendar()[:2]].append(t)
    for k in sorted(weekly):
        ts = weekly[k]
        print(line(f"ISO week {k[0]}-W{k[1]:02d}", ts, sp) + f"   median ATR ${st.median([t['atr'] for t in ts]):.0f}")
    seq = sorted(zip([t["xt"] for t in pg], nets), key=lambda x: x[0])
    final, mdd, streak, uw_t, uw_d = equity_stats(seq)
    print(f"  equity {final:+.2f}; max drawdown ${mdd:.2f}; longest losing streak {streak}; "
          f"longest stretch below a prior equity high {uw_t} trades / {uw_d:.1f} days")
    print(f"\n  Monte Carlo, {a.horizon} trades at 0.01 lot (~{a.horizon / (n / span_days):.0f} days), "
          f"bootstrap of the {n} post-gate net trades, {MC_PATHS} paths each:")
    print(f"  {'scenario':34s} {'P(net<0)':>8s} {'5th pct':>8s} {'median':>8s} {'95th pct':>9s}"
          f" {'median maxDD':>13s} {'95th maxDD':>11s}")
    demeaned = [x - mu for x in nets]
    scenarios = (("edge as observed", nets),
                 ("ZERO edge (same dispersion)", demeaned),
                 (f"spread doubles (+${sp:.2f}/trade)" if sp else "extra $0.40/trade", [x - (sp or 0.40) for x in nets]))
    touch_rows = []
    for label, xs in scenarios:
        f, d, tch = monte_carlo(xs, a.horizon, MC_PATHS, rng, KILL_FLOORS)
        pn = sum(1 for x in f if x < 0) / len(f)
        print(f"  {label:34s} {100 * pn:7.0f}% {pct(f, .05):+8.1f} {pct(f, .5):+8.1f} {pct(f, .95):+9.1f}"
              f" {pct(d, .5):13.1f} {pct(d, .95):11.1f}")
        touch_rows.append((label, tch))
    print(f"\n  P(equity touches -$X at any point within {a.horizon} trades) - how informative a kill-switch floor is:")
    print(f"  {'scenario':34s} " + " ".join(f"{'-$' + str(f):>7s}" for f in KILL_FLOORS))
    for label, tch in touch_rows:
        print(f"  {label:34s} " + " ".join(f"{100 * tch[f]:6.0f}%" for f in KILL_FLOORS))

    # ---- 6. LATENCY --------------------------------------------------------
    print("\n== 6. LATENCY STRESS: does a late fill kill the edge? (M5 re-walk, coarse - compare rows) ==")
    for frac, nn, w_, l_, tot_ in latency_stress(pg, bars, sp):
        lab = {0.0: "fill at signal-bar close (simulator)", 0.2: "fill ~1 min later",
               0.5: "fill ~2.5 min later", 1.0: "fill 5 min later (next bar close)"}[frac]
        print(f"  {lab:38s} n={nn} {w_}W/{l_}L/{nn - w_ - l_}T  net {tot_:+7.2f}  net/trade {tot_ / nn:+.3f}")

    # ---- 7. OPERATIONS -----------------------------------------------------
    print("\n== 7. OPERATIONS: price-log health ==")
    gaps, have, expected, missing = feed_report(bars)
    print(f"  {have} of {expected} expected M5 slots present ({100 * have / expected:.1f}%), {missing} missing "
          f"(same count as check_data), {bars[0]['dt']:%m-%d %H:%M} -> {bars[-1]['dt']:%m-%d %H:%M}")
    if gaps:
        for s, e, m in gaps:
            print(f"  gap > {FEED_GAP_FLAG_MIN} min: {s:%m-%d %H:%M} -> {e:%m-%d %H:%M}  ({m:.0f} min = {m / 60:.1f} h)")
    else:
        print(f"  no gap > {FEED_GAP_FLAG_MIN} min")
    cutoff = bars[-1]["dt"] - timedelta(days=GAP_WINDOW_DAYS)
    recent_gaps = [g for g in gaps if g[1] >= cutoff]
    worst = max((g[2] for g in recent_gaps), default=0.0)

    # ---- 8. GATES ----------------------------------------------------------
    print("\n== 8. GATES (proposed thresholds - constants at the top of this file) ==")
    k_drop = max(3, math.ceil(TOP_FRAC * n))
    without_top = total - sum(ranked[:k_drop])
    recent = sorted(pg, key=lambda t: t["xt"])[-RECENT_N:]
    recent_net = sum(t["profit"] for t in recent) - sp * len(recent)
    cover = (g_mean / sp) if sp else 0.0      # no cost assumed => the cost gate cannot pass
    gates = [
        (f"sample: >= {MIN_TRADES} post-gate trades", n >= MIN_TRADES, f"{n}"),
        (f"edge: by-day bootstrap P(net/trade>0) >= {MIN_P_EDGE:.0%}", p_day >= MIN_P_EDGE, f"{p_day:.0%}"),
        (f"cost: break-even spread >= {MIN_SPREAD_COVER:.1f}x assumed", cover >= MIN_SPREAD_COVER,
         f"{cover:.1f}x (${g_mean:.2f} vs ${sp:.2f})" if sp else "cannot pass: gross mode"),
        (f"fragility: net > 0 without the best {k_drop} trades", without_top > 0, f"{without_top:+.2f}"),
        (f"recent form: last {RECENT_N} closed trades net >= 0", recent_net >= 0, f"{recent_net:+.2f}"),
        (f"feed: no gap > {MAX_GAP_MIN} min in the last {GAP_WINDOW_DAYS} days of the log", worst <= MAX_GAP_MIN,
         f"worst {worst:.0f} min"),
    ]
    for label, ok, val in gates:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label:62s} {val}")
    npass = sum(1 for _, ok, _ in gates if ok)
    print(f"\n  DATA GATES: {npass}/{len(gates)} pass.", end=" ")
    if npass < len(gates):
        print("NOT READY - keep forward-testing; see the failing gates above.")
    else:
        print("Data gates pass; this is necessary, not sufficient (checklist below).")

    print("\n  NON-DATA GATES (cannot be computed from the CSVs - sign each off by hand;")
    print("  details and evidence in docs/REVIEW-2026-10-01.md sections 6-7;\n    python3 tools/live_path_probe.py reproduces the order-path findings):")
    for item in (
        "LIVE order path fixed + smoke-tested (close detection by position id, restart reconciliation,"
        " spread guard, filling mode, None-result handling)",
        "an order executor that can run where MT5 runs (the Linux engine cannot import MetaTrader5)",
        "XM spread profile measured (Asia/London/NY/weekend) + commission/swap confirmed -> new --spread",
        "demo-account run through the real order path; sim-vs-demo trade parity reviewed",
        "same-feed parity: a forward run on DATA_SOURCE=MT5 shows comparable signal flow",
        "kill switches: equity floor, max spread, stale-feed alarm, manual halt - all tested",
        "micro-live caps agreed in writing (size, max loss, weekday-only or not)",
    ):
        print(f"    [ ] {item}")
    return 0 if npass == len(gates) else 1


if __name__ == "__main__":
    sys.exit(main())
