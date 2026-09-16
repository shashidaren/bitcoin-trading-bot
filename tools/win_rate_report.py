#!/usr/bin/env python3
"""
Win-rate report for BTC - "why is the win rate what it is?" (port of gold's
win_rate_report.py, adapted to M5 / RR 1:2 / exit domain {SL, TP}).

Read-only. Run after every data drop, next to the other tools:

    python3 tools/win_rate_report.py [--root DIR] [--spread 0.40]

    --spread defaults to 0.0 (gross); the measured XM BTCUSD round trip is $0.40
    per trade at LOT_SIZE 0.01 (docs/HANDOFF.md §9). Every P/L column below is
    net of it, and docs/HANDOFF.md quotes these numbers net unless marked gross.

Sections
  1. Baseline: W/L, decisive win rate with a Wilson 95% CI, P&L, expectancy in
     $ and in R, and the breakeven WR implied by the live 1:2 geometry.
  2. Eras: pre-port (before the 2026-09-09 deploy) vs new regime vs last
     N trades - never average a regime change into "the" win rate.
  3. Side / day / hour breakdowns (BUY and SELL are different strategies).
  4. How long each outcome actually takes.
  5. Exit-geometry sanity grid (compact; full version in tools/pathwalk_sims.py).
  6. Signal census: every reconstructed signal in the price log, walked with the
     live geometry - the entry stream's own hit rate, independent of the gates.
  7. Queued filter candidates (MIN_ATR, RSI floor, wick, side, hours, ATR%-by-day)
     scored keep-vs-skip, WITH the day-confound control: on 7 days of data every
     feature split is partly a split on WHICH DAYS the feature selected.
  8. Cost sensitivity: the spread level at which the current book stops working.

Data gotchas handled (docs/HANDOFF.md §9): comma-grouped legacy rows, M5 bar
spacing, log coverage starting 2026-09-07 20:20 UTC, 09-03 sizing outliers,
Trade_Num resets (stats here are row-based, never keyed on Trade_Num).
"""
import argparse
import os
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import replay_lib as R  # noqa: E402

OUTLIER_ERA = datetime(2026, 9, 5)          # the two 09-03 sizing monsters
BLACKOUTS = [(7, 55, 9, 0), (12, 25, 12, 45), (13, 25, 15, 15)]


def in_blackout(dt):
    t = dt.time()
    for sh, sm, eh, em in BLACKOUTS:
        if datetime.strptime(f"{sh}:{sm}", "%H:%M").time() <= t <= datetime.strptime(f"{eh}:{em}", "%H:%M").time():
            return True
    return False


def stats_line(ts, label, width=30, spread=0.0):
    w = sum(1 for t in ts if t["reason"] == "TP")
    l = sum(1 for t in ts if t["reason"] == "SL")
    pnl = sum(t["profit"] for t in ts) - spread * len(ts)
    dec = w + l
    rate = w / dec * 100 if dec else float("nan")
    lo, hi = R.wilson(w, dec)
    one_r = statistics.mean(R.r_money(t["atr"]) for t in ts) if ts else 0
    rr = statistics.mean(x for x in (R.planned_rr(t) for t in ts) if x) if ts else 0
    lr = R.realized_r
    rtot = sum(x for x in (lr(t) for t in ts) if x is not None)
    ci = f"[{lo:4.1f},{hi:4.1f}]" if dec else ""
    print(f"  {label:{width}s} n={len(ts):3d}  {w:2d}W/{l:2d}L  WR {rate:5.1f}% {ci:14s} "
          f"P/L {pnl:+8.2f}  {rtot:+6.1f}R  /trade {pnl/len(ts) if ts else 0:+.3f}  "
          f"(1R ${one_r:.2f}, planned 1:{rr:.2f})")
    return w, l, pnl


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.dirname(HERE))
    ap.add_argument("--spread", type=float, default=0.0,
                    help="round-trip cost $/trade at LOT_SIZE for the P/L columns")
    ap.add_argument("--horizon", type=int, default=240)
    args = ap.parse_args()

    trades = R.load_trades(os.path.join(args.root, "trades.csv"))
    bars = R.load_bars(os.path.join(args.root, "forward_test_log.csv"))

    print(f"win_rate_report - {len(trades)} trades, {len(bars)} M5 bars "
          f"({bars[0]['dt']} -> {bars[-1]['dt']}), spread ${args.spread:.2f}/trade\n")

    # ---------------------------------------------------------------- baseline
    print("== 1. BASELINE ==")
    stats_line(trades, "all rows (incl 09-03)", spread=args.spread)
    clean = [t for t in trades if t["et"] >= OUTLIER_ERA]
    stats_line(clean, "from 09-05 (excl outliers)", spread=args.spread)
    new = [t for t in trades if t["et"] >= R.PORT_DEPLOY]
    stats_line(new, "new regime (post-port)", spread=args.spread)
    dec_all = sum(1 for t in clean if t["reason"] in ("TP", "SL"))
    w_all = sum(1 for t in clean if t["reason"] == "TP")
    be_wr = 1 / (1 + R.ATR_TP_MULT / R.ATR_SL_MULT) * 100
    edge = w_all / dec_all * 100 - be_wr
    print(f"  breakeven decisive WR at RR 1:{R.ATR_TP_MULT/R.ATR_SL_MULT:.0f} = {be_wr:.1f}% "
          f"-> the book sits {abs(edge):.1f} points {'above' if edge >= 0 else 'below'} it "
          f"(from 09-05, before any spread)")
    gross_w = sum(t["profit"] for t in clean if t["reason"] == "TP")
    gross_l = sum(t["profit"] for t in clean if t["reason"] == "SL")
    print(f"  gross +{gross_w:.2f} / {gross_l:.2f}  |  09-03 outlier pair excluded "
          f"(-$394.84, pre-port sizing)")

    # --- ledger geometry: the sample is NOT one strategy --------------------
    print("\n== 1b. LEDGER GEOMETRY (why pooled R statistics are a trap) ==")
    for label, ts in (("before 09-06 17:49 (RR 1:1.67 + candle fills)",
                       [t for t in trades if t["et"] < R.GEOM2_DEPLOY]),
                      ("from 09-06 17:49 (live RR 1:2)",
                       [t for t in trades if t["et"] >= R.GEOM2_DEPLOY])):
        if not ts:
            continue
        w = sum(1 for t in ts if t["reason"] == "TP")
        lo, hi = R.wilson(w, w + len(ts) - w)
        rrs = [R.planned_rr(t) for t in ts if R.planned_rr(t)]
        rr = statistics.median(rrs)
        # GROSS on purpose: a geometry census is about the ledger, not about cost.
        print(f"  {label:42s} n={len(ts):3d} {w}W/{len(ts)-w}L  WR {w/len(ts)*100:5.1f}% "
              f"[{lo:4.1f},{hi:4.1f}]  P/L {sum(t['profit'] for t in ts):+8.2f} (gross)  "
              f"planned 1:{rr:.2f} (breakeven {1/(1+rr)*100:.1f}%)  "
              f"realized {sum(x for x in (R.realized_r(t) for t in ts) if x is not None):+6.1f}R")
    print("  -> Rows here are GROSS (the --spread haircut does not apply); the R totals are")
    print("     why every other table is era-split.")
    print("  -> Pre-change rows fill on candles (stops overshoot the logged level) and hold")
    print("     a different geometry; R totals and breakeven WR are era-specific. Only rows")
    print("     from 09-06 17:49 on ran the live 2x/4x rule (docs/REVIEW-2026-09-15.md).\n")

    # -------------------------------------------------------------------- eras
    print("== 2. ERAS AND SLICES ==")
    for label, ts in (("pre-port (09-05..09-09)", [t for t in clean if t["et"] < R.PORT_DEPLOY]),
                      ("new regime (>= 09-09)", new),
                      ("last 30", clean[-30:]), ("last 20", clean[-20:]),
                      ("last 10", clean[-10:])):
        stats_line(ts, label, spread=args.spread)
    print()

    # -------------------------------------------------------------- side / day
    print("== 3a. SIDE ==")
    for side in ("BUY", "SELL"):
        stats_line([t for t in clean if t["side"] == side], f"{side} (from 09-05)", spread=args.spread)
    for side in ("BUY", "SELL"):
        stats_line([t for t in new if t["side"] == side], f"{side} (new regime)", spread=args.spread)
    print("\n== 3b. DAY ==")
    by_day = defaultdict(list)
    for t in clean:
        by_day[t["et"].date()].append(t)
    for d in sorted(by_day):
        stats_line(by_day[d], str(d), width=12, spread=args.spread)
    print("\n== 3c. HOUR (UTC entry, from 09-05) ==")
    by_hour = defaultdict(list)
    for t in clean:
        by_hour[t["et"].hour].append(t)
    for h in sorted(by_hour):
        stats_line(by_hour[h], f"{h:02d}:00", width=12, spread=args.spread)
    print()

    # --------------------------------------------------------------- durations
    print("== 4. HOW LONG EACH OUTCOME TAKES (min) ==")
    for reason in ("TP", "SL"):
        d = sorted((t["xt"] - t["et"]).total_seconds() / 60 for t in trades if t["reason"] == reason)
        if not d:
            continue
        print(f"  {reason}: n={len(d):3d} median {statistics.median(d):6.1f}  "
              f"p90 {d[int(len(d)*0.9)]:6.1f}  max {max(d):7.1f}")
    print("  (BTC has no time stop and no BE ratchet: every trade ends at SL or TP, so the")
    print("   exit-reason domain is exactly {SL, TP})")
    print()

    # ------------------------------------------------- exit grid (compact)
    covered, _ = R.coverage(trades, bars)
    print(f"== 5. EXIT GEOMETRY (compact; {len(covered)} log-covered trades, "
          f"{args.horizon}-min horizon, cascade-ignorant) ==")
    print("   full grids: python3 tools/pathwalk_sims.py --census")
    for tp in (3.0, 4.0, 5.0):
        w = l = tm = 0
        pnl = 0.0
        for t in covered:
            seg = [b for b in bars if t["et"] < b["dt"] <= t["et"] + timedelta(minutes=args.horizon)]
            out, r, held, _ = R.walk(t["entry"], t["side"], t["atr"], seg, tp_mult=tp)
            pnl += r * R.r_money(t["atr"]) - args.spread
            w += out == "TP"
            l += out == "SL"
            tm += out == "TIME"
        print(f"   TP {tp:.0f}xATR ({tp/2:.2f}R): {w}W/{l}L/{tm}T  WR {w/(w+l)*100 if w+l else 0:5.1f}%  "
              f"P/L {pnl:+7.2f}" + ("   <- LIVE" if tp == R.ATR_TP_MULT else ""))
    for be in (0.5, 1.0):
        w = l = b_ = tm = 0
        pnl = 0.0
        for t in covered:
            seg = [b for b in bars if t["et"] < b["dt"] <= t["et"] + timedelta(minutes=args.horizon)]
            out, r, held, _ = R.walk(t["entry"], t["side"], t["atr"], seg, be_trigger=be)
            pnl += r * R.r_money(t["atr"]) - args.spread
            w += out == "TP"
            l += out == "SL"
            b_ += out == "BE"
            tm += out == "TIME"
        print(f"   BE +{be:.2f}R (candidate, not live): {w}W/{l}L/{b_}BE/{tm}T  "
              f"WR {w/(w+l)*100 if w+l else 0:5.1f}%  P/L {pnl:+7.2f}")
    print()

    # ----------------------------------------------------------- signal census
    bars_full = R.load_bars(os.path.join(args.root, "forward_test_log.csv"), with_indicators=True)
    recon = R.enrich_log(bars_full)
    print("== 6. SIGNAL CENSUS (reconstructed from the price log) ==")
    print("   reconstruction quality vs logged pre-update values: "
          + ", ".join(f"{k} {ok}/{ok+bad}" for k, (ok, bad) in recon.items()))
    sigs = R.all_signals(bars_full)
    takeable = [s for s in sigs if not in_blackout(s["dt"])]
    print(f"   {len(sigs)} full signals (BUY {sum(s['side']=='BUY' for s in sigs)}, "
          f"SELL {sum(s['side']=='SELL' for s in sigs)}); {len(sigs)-len(takeable)} fire inside a")
    print(f"   blackout window and are never takeable live -> {len(takeable)} takeable")
    rows = []
    for s in takeable:
        seg = [b for b in bars_full if s["dt"] < b["dt"] <= s["dt"] + timedelta(minutes=args.horizon)]
        out, r, held, _ = R.walk(s["entry"], s["side"], s["atr"], seg)
        rows.append(dict(outcome=out, r=r, atr=s["atr"], side=s["side"]))
    w = sum(1 for x in rows if x["outcome"] == "TP")
    l = sum(1 for x in rows if x["outcome"] == "SL")
    tm = len(rows) - w - l
    pnl = sum(x["r"] * R.r_money(x["atr"]) for x in rows) - args.spread * len(rows)
    lo, hi = R.wilson(w, w + l)
    print(f"   entry stream at the LIVE geometry: {w}W/{l}L/{tm}T  "
          f"WR {w/(w+l)*100:5.1f}% [{lo:.1f},{hi:.1f}]  P/L {pnl:+7.2f}  "
          f"({pnl/len(rows):+.3f}/trade)")
    print("   -> this is the raw signal stream BEFORE the risk gates (cooldown, blackout,")
    print("      daily halt), and before exits are decided by tick order.")
    print()

    # ------------------------------------------------------------- filter lab
    print("== 7. QUEUED FILTER CANDIDATES (keep vs skip) ==")
    print("   WARNING: 7 days of data. Every split below is also a split on WHICH DAYS the")
    print("   feature selected, so each candidate is printed together with its within-day")
    print("   control - if the two disagree, the feature is a calendar proxy, not an edge.\n")

    def lab(label, keep_fn, control=True):
        kept = [x for x in rows if keep_fn(x["sig"])]
        skip = [x for x in rows if not keep_fn(x["sig"])]
        if not kept or not skip:
            return
        def cell(sel):
            w = sum(1 for x in sel if x["outcome"] == "TP")
            l = sum(1 for x in sel if x["outcome"] == "SL")
            p = sum(x["r"] * R.r_money(x["atr"]) for x in sel) - args.spread * len(sel)
            lo, hi = R.wilson(w, w + l) if w + l else (0, 0)
            return (f"n={len(sel):3d} WR {w/(w+l)*100 if w+l else float('nan'):5.1f}% "
                    f"[{lo:4.1f},{hi:4.1f}] P/L {p:+7.2f}")
        print(f"   {label}")
        print(f"      keep  {cell(kept)}")
        print(f"      skip  {cell(skip)}")
        if control:
            # WITHIN-DAY control: compare keep vs skip only inside days that contain
            # both. Pooled keep-vs-skip above can be pure calendar composition (a
            # feature that selects two quiet days looks decisive); this removes the
            # between-day component. Days where the feature takes everything or
            # nothing are dropped and reported.
            ck = [x for x in kept if any(not keep_fn(y["sig"]) for y in rows
                                         if y["sig"]["dt"].date() == x["sig"]["dt"].date())]
            cs = [x for x in skip if any(keep_fn(y["sig"]) for y in rows
                                         if y["sig"]["dt"].date() == x["sig"]["dt"].date())]
            dropped = len(rows) - len(ck) - len(cs)
            if ck and cs:
                print(f"      own-day keep {cell(ck)}   (drops {dropped} signals on "
                      f"all-keep/all-skip days)")
                print(f"      own-day skip {cell(cs)}   <- if this does not agree with the"
                      f" pooled rows, the feature is a day proxy")

    rows = []
    for s in takeable:
        seg = [b for b in bars_full if s["dt"] < b["dt"] <= s["dt"] + timedelta(minutes=args.horizon)]
        out, r, held, _ = R.walk(s["entry"], s["side"], s["atr"], seg)
        i = s["i"]
        s["mom5h"] = ((bars_full[i]["c"] - bars_full[i - 60]["c"]) / bars_full[i - 60]["c"] * 100
                      if i >= 60 else None)
        rows.append(dict(sig=s, outcome=out, r=r, atr=s["atr"]))

    lab("ATR% >= 0.06 (volatility floor -> kills the low-vol stream)",
        lambda s: s["atr"] / s["entry"] >= 0.0006)
    # within-day control: split each day's signals at that day's own ATR% median
    by_day_sig = defaultdict(list)
    for s in takeable:
        by_day_sig[s["dt"].date()].append(s)
    med = {d: sorted(x["atr"] / x["entry"] for x in v)[len(v) // 2] for d, v in by_day_sig.items()}
    lab("ATR% above its OWN day's median (the control)",
        lambda s: s["atr"] / s["entry"] >= med[s["dt"].date()], control=False)
    lab("RSI >= 45 (gold's adopted filter)", lambda s: s["rsi"] >= 45)
    lab("wick ratio <= 0.40 (deep rejection is worse, not better)",
        lambda s: s["wick"] <= 0.40)
    lab("side = SELL", lambda s: s["side"] == "SELL")
    lab("momentum-aligned (BUY 5h mom >= 0, SELL <= 0)",
        lambda s: s["mom5h"] is not None and
        ((s["side"] == "BUY" and s["mom5h"] >= 0) or (s["side"] == "SELL" and s["mom5h"] <= 0)))
    # --- EMA50 distance: TWO different quantities, do not confuse them --------
    # The live gate (engine.MAX_BELOW_EMA_ATR = 0.30) is ONE-SIDED: it only caps
    # how far the entry may sit on the ADVERSE side of EMA50 (below for a BUY,
    # above for a SELL). A two-sided |distance| band is a DIFFERENT, new gate.
    # This block used to print a two-sided 0.15 band under a label that said
    # "tighten MAX_BELOW_EMA_ATR", which reads as an instruction to change a
    # parameter that the numbers do not support - both are now printed, labelled
    # with the quantity they actually measure (docs/HANDOFF.md §5).
    def prox_two(s):
        """|entry - EMA50| in ATR (two-sided band; NOT what the engine gates)."""
        e = bars_full[s["i"]].get("post_ema50")
        return abs(s["entry"] - e) / s["atr"] if e else None

    def prox_adverse(s):
        """Adverse-side distance in ATR - the quantity MAX_BELOW_EMA_ATR caps."""
        e = bars_full[s["i"]].get("post_ema50")
        if not e:
            return None
        return ((e - s["entry"]) if s["side"] == "BUY" else (s["entry"] - e)) / s["atr"]

    for k in (0.15, 0.50, 1.00):
        lab(f"TWO-SIDED EMA50 band |entry-EMA50| <= {k:.2f} ATR (a NEW gate, not live)",
            lambda s, k=k: prox_two(s) is not None and prox_two(s) <= k)
    # control=False on purpose: a one-sided gate at 0.30 already keeps ~all of
    # the stream, so tightening it drops 7-12 signals and the within-day control
    # just re-slices which days are left (it printed a +22.81 "own-day keep" for
    # a split whose pooled keep is -11.20). Read the pooled row here and the
    # post-gate ledger rows below.
    for k in (0.15, 0.00):
        lab(f"ONE-SIDED tighten MAX_BELOW_EMA_ATR {R.MAX_BELOW_EMA_ATR:.2f} -> {k:.2f} (live gate)",
            lambda s, k=k: prox_adverse(s) is not None and prox_adverse(s) <= k,
            control=False)

    def cell2(sel):
        w = sum(1 for t in sel if t["reason"] == "TP")
        l = sum(1 for t in sel if t["reason"] == "SL")
        p = sum(t["profit"] for t in sel) - args.spread * len(sel)
        lo, hi = R.wilson(w, w + l) if w + l else (0, 0)
        return (f"n={len(sel):3d} WR {w/(w+l)*100 if w+l else float('nan'):5.1f}% "
                f"[{lo:4.1f},{hi:4.1f}] P/L {p:+7.2f}")

    def ledger_lab(label, pool, keep_fn):
        kept = [t for t in pool if keep_fn(t)]
        skip = [t for t in pool if not keep_fn(t)]
        if not kept and not skip:
            return
        if not skip:
            # a gate that every ledger row already satisfies says something real
            # (the engine enforced it) - print it instead of hiding the row.
            print(f"   {label:52s} keep {cell2(kept)}")
            print(f"   {'':52s} skip n=  0  (nothing in the ledger violates it)")
            return
        if not kept:
            print(f"   {label:52s} keep n=  0  (no ledger row satisfies it)")
            print(f"   {'':52s} skip {cell2(skip)}")
            return
        print(f"   {label:52s} keep {cell2(kept)}")
        print(f"   {'':52s} skip {cell2(skip)}")

    print(f"   --- the same candidates on the {len(clean)} real trades (from 09-05, ledger features) ---")
    for label, keep_fn in (
        ("ATR% >= 0.06", lambda t: t["atr"] / t["entry"] >= 0.0006),
        ("RSI >= 45", lambda t: t["rsi"] >= 45),
        ("wick <= 0.40", lambda t: t["wick"] <= 40.0),   # ledger stores the ratio in %
        ("side = SELL (trades)", lambda t: t["side"] == "SELL"),
    ):
        ledger_lab(label, clean, keep_fn)

    # The EMA50-distance candidates are re-read on POST-GATE trades only: the
    # near-EMA gate went live with the 09-10 deploy, so earlier rows were taken
    # by code that had no such gate and would only blur the split (two 09-09 BUY
    # rows sit 0.57 and 3.11 ATR on the adverse side - tools/check_data.py's
    # entry-gate conformance block reports exactly this).
    post = [t for t in clean if t["et"] >= R.GATES_DEPLOY]
    def t_two(t):
        return abs(t["entry"] - t["ema50"]) / t["atr"] if t.get("ema50") else None
    def t_adv(t):
        if not t.get("ema50"):
            return None
        return ((t["ema50"] - t["entry"]) if t["side"] == "BUY"
                else (t["entry"] - t["ema50"])) / t["atr"]
    print(f"   --- EMA50 distance on the {len(post)} post-gate trades (>= {R.GATES_DEPLOY:%m-%d}, ledger features) ---")
    for k in (0.50, 1.00):
        ledger_lab(f"TWO-SIDED band <= {k:.2f} ATR (a NEW gate, not live)", post,
                   lambda t, k=k: t_two(t) is not None and t_two(t) <= k)
    for k in (0.30, 0.15):
        ledger_lab(f"ONE-SIDED adverse <= {k:.2f} ATR" + ("  <- LIVE gate" if k == R.MAX_BELOW_EMA_ATR else "  (tighter)"),
                   post, lambda t, k=k: t_adv(t) is not None and t_adv(t) <= k)
    print()

    # ------------------------------------------------------- cost sensitivity
    print("== 8. COST SENSITIVITY - the spread at which the book stops working ==")
    print(f"   breakeven decisive WR = (1 + s/a)/3 where a = 1R in $ = "
          f"{R.ATR_SL_MULT:.0f}xATR x LOT_SIZE")
    print("   live book WR (from 09-05) = "
          f"{sum(t['reason']=='TP' for t in clean)/dec_all*100:.1f}%")
    grid = (0.10, 0.25, 0.40, 0.50)   # 0.40 = measured XM BTCUSD round trip
    header = "   " + "ATR$".rjust(7) + "".join(f"  s=${s:.2f}" for s in grid)
    print(header)
    for atr in (10, 15, 20, 30, 50, 70, 100, 150, 220):
        a = R.r_money(atr)
        cells = "".join(f"  {(1+s/a)/3*100:6.0f}%" for s in grid)
        mark = "  <- near the live-era median ATR" if atr == 100 else ""
        print(f"   {atr:7.0f}{cells}{mark}")
    print("   Read: s=$0.40 is the measured XM BTCUSD round trip at LOT_SIZE 0.01. At the")
    print("   live-era median entry ATR (~$88) it needs a 40.9% decisive win rate; a $15-ATR")
    print("   signal needs 75%.")
    print("   Trade flow that small is not a strategy, it is a fee stream - measure the real")
    print("   XM BTCUSD spread before LIVE (docs/HANDOFF.md §7).")
    print("\n   Legend: 'WR' is decisive (SL/TP only - BTC has no scratch outcome).")
    print("   Wilson CI covers sampling noise only; it is not a forecast.")


if __name__ == "__main__":
    main()
