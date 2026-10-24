#!/usr/bin/env python3
"""xm_quote_report - read what the XM quote logger collected (xm_data/) for US100Cash
and answer the spread, cost, parity, and contract-spec questions.

  python3 tools/xm_quote_report.py              full report
  python3 tools/xm_quote_report.py --quiet      one advisory line (used by autosync's digest)
  python3 tools/xm_quote_report.py --days 14    only the newest 14 UTC days of quote rows
  python3 tools/xm_quote_report.py --dir xm_data --root .

No --spread flag on purpose: docs command blocks carry `--spread 0.25`
(checked by tools/handoff_check.py), whereas this tool measures XM's live spread.
"""
import argparse
import bisect
import csv
import glob
import json
import os
import statistics as st
import sys
import time
from collections import Counter, defaultdict, namedtuple
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

import replay_lib as R  # noqa: E402
import mt5_quotes as Q  # noqa: E402

try:
    from trade_filter import BLACKOUT_WINDOWS, blackout_label_for_utc, is_market_quiet  # noqa: E402
except Exception:  # pragma: no cover
    BLACKOUT_WINDOWS = []
    blackout_label_for_utc = lambda dt=None: None
    is_market_quiet = lambda dt=None: False

UTC = timezone.utc

# --- Nasdaq (US100Cash, M15, 0.10 lot) reference numbers ---
ASSUMED_USD_PER_TRADE = 0.25            # 2.5 pts index spread x 0.10 lot x 1.0 contract
HARD_CAP_PTS = 8.0                      # engine MAX_SPREAD_POINTS (8.0 index pts = $0.80 at 0.10 lot)
SHARE_1R_CUTS = (0.20, 0.30, 0.35)
STAGE_C_MEDIAN_LIMIT = 0.40             # Stage C all-in median <= $0.40/trade at 0.10 lot
STAGE_C_BUCKET_LIMIT = 0.80
TARGET_DAYS, TARGET_WEEKENDS = 10, 2    # 10 active trading days (~2 trading weeks)
DAY_COMPLETE_FRAC = 0.80
GAP_MIN_S = 300
STALE_AFTER_S = 20 * 60                 # > 1 M15 bar
SESSIONS = (("ASIA", 0, 8), ("LONDON", 8, 13), ("NY", 13, 21), ("LATE", 21, 24))
BAD_FLAGS = frozenset({"STALE", "NOOFFSET", "NOQUOTE", "BADQUOTE"})
PARITY_MIN_PAIRS = 40
QUIET_WINDOW_DAYS = 45
BAR_SECONDS = Q.M15_SECONDS             # 900s (M15)

Sample = namedtuple("Sample", "t spread smin smax flags age n_ok n_bad off")


def _f(x):
    try:
        return float(x) if x not in ("", None) else None
    except ValueError:
        return None


def load_quotes(qdir, since=None):
    """-> (samples ascending, malformed line count, number of files)."""
    rows, bad = [], 0
    files = sorted(glob.glob(os.path.join(qdir, "quotes-????-??-??.csv")))
    for path in files:
        if since is not None:
            try:
                day = datetime.strptime(os.path.basename(path)[7:17], "%Y-%m-%d").replace(tzinfo=UTC).timestamp()
                if day + 86400 <= since:
                    continue
            except ValueError:
                pass
        try:
            with open(path, newline="", encoding="utf-8", errors="replace") as fh:
                rd = csv.reader(fh)
                if next(rd, None) != Q.QUOTE_FIELDS:
                    bad += 1
                    continue
                for p in rd:
                    if len(p) != len(Q.QUOTE_FIELDS):
                        bad += 1
                        continue
                    d = dict(zip(Q.QUOTE_FIELDS, p))
                    try:
                        t = Q.parse_utc(d["ts_utc"])
                        off = int(d["srv_offset_s"]) if d["srv_offset_s"] else None
                        n_ok, n_bad = int(d["n_ok"] or 0), int(d["n_bad"] or 0)
                    except ValueError:
                        bad += 1
                        continue
                    if since is not None and t < since:
                        continue
                    rows.append(Sample(t, _f(d["spread"]), _f(d["spread_min"]), _f(d["spread_max"]),
                                       frozenset(x for x in d["flags"].split(";") if x),
                                       _f(d["tick_age_s"]), n_ok, n_bad, off))
        except OSError:
            bad += 1
    rows.sort(key=lambda s: s.t)
    return rows, bad, len(files)


def load_candles(qdir):
    """XM shadow M15 candles -> dicts with close (naive UTC datetime, the log's convention)."""
    out = []
    path = os.path.join(qdir, Q.CANDLES_FILE)
    for r in Q.read_csv_rows(path, Q.CANDLE_FIELDS):
        close = R.parse_ts(r["bar_close_utc"])
        o, h, l, c = (_f(r[k]) for k in ("open", "high", "low", "close"))
        if close is None or None in (o, h, l, c):
            continue
        out.append(dict(close=close, o=o, h=h, l=l, c=c, tv=_f(r["tick_volume"]),
                        sp=_f(r["spread_pts"]), off=_f(r["offset_s"])))
    out.sort(key=lambda x: x["close"])
    return out


def load_spec(qdir):
    try:
        with open(os.path.join(qdir, Q.SPEC_FILE), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def spec_changes(qdir):
    try:
        with open(os.path.join(qdir, Q.SPEC_HISTORY_FILE), encoding="utf-8") as fh:
            return sum(1 for ln in fh if ln.strip())
    except OSError:
        return 0


def pct(sorted_vals, q):
    if not sorted_vals:
        return None
    k = (len(sorted_vals) - 1) * q
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def summarize(vals):
    v = sorted(vals)
    if not v:
        return dict(n=0)
    return dict(n=len(v), mean=sum(v) / len(v), med=pct(v, .5), p90=pct(v, .9), p95=pct(v, .95),
                p99=pct(v, .99), mx=v[-1])


def usable(s):
    return s.spread is not None and not (s.flags & BAD_FLAGS)


def share_above(vals, thr):
    return 100.0 * sum(1 for x in vals if x > thr) / len(vals) if vals else 0.0


def dt_of(t):
    return datetime.fromtimestamp(t, tz=UTC)


def is_weekend(t):
    return dt_of(t).weekday() >= 5


def session_of(t):
    h = dt_of(t).hour
    for name, a, b in SESSIONS:
        if a <= h < b:
            return name
    return "?"


def blackout_of(t):
    return blackout_label_for_utc(dt_of(t))


def coverage(samples):
    """Rows per UTC day, complete days/weekends, outages."""
    if not samples:
        return None
    gaps_s = Counter(int(b.t - a.t) for a, b in zip(samples, samples[1:]) if 0 < b.t - a.t <= GAP_MIN_S)
    interval = gaps_s.most_common(1)[0][0] if gaps_s else 30
    per_day = 86400.0 / max(interval, 1)
    by_day = Counter(dt_of(s.t).date() for s in samples)
    complete = sorted(d for d, n in by_day.items() if n >= DAY_COMPLETE_FRAC * per_day)
    cset = set(complete)
    weekends = sorted(d for d in cset if d.weekday() == 5 and (d + timedelta(days=1)) in cset)
    outages = [(a.t, b.t - a.t) for a, b in zip(samples, samples[1:]) if b.t - a.t > GAP_MIN_S]
    span = samples[-1].t - samples[0].t
    expected = span / interval + 1
    return dict(interval=interval, by_day=by_day, complete=complete, weekends=weekends,
                outages=sorted(outages, key=lambda x: -x[1]), outage_s=sum(d for _, d in outages),
                expected=expected, rows=len(samples), span_days=span / 86400.0)


def unusable_runs(samples, interval, min_s=GAP_MIN_S):
    runs, start, last = [], None, None
    for sm in samples:
        if usable(sm):
            if start is not None and last - start + interval >= min_s:
                runs.append((start, last - start + interval))
            start = None
        else:
            if start is None:
                start = sm.t
            last = sm.t
    if start is not None and last - start + interval >= min_s:
        runs.append((start, last - start + interval))
    return sorted(runs, key=lambda r: -r[1])


def stage_b_progress(cov):
    d, w = len(cov["complete"]), len(cov["weekends"])
    return d, w, d >= TARGET_DAYS and w >= TARGET_WEEKENDS


def blackout_days(samples, interval):
    out = {}
    for sh, sm, eh, em, label in BLACKOUT_WINDOWS:
        need = DAY_COMPLETE_FRAC * ((eh * 60 + em) - (sh * 60 + sm)) * 60.0 / max(interval, 1)
        per = Counter(dt_of(s.t).date() for s in samples if blackout_of(s.t) == label)
        out[label] = sum(1 for n in per.values() if n >= need)
    return out


def nearest(ts, vals, t, tol):
    i = bisect.bisect_left(ts, t)
    best = None
    for j in (i - 1, i):
        if 0 <= j < len(ts) and abs(ts[j] - t) <= tol and (best is None or abs(ts[j] - t) < abs(ts[best] - t)):
            best = j
    return None if best is None else vals[best]


def trade_costs(trades, samples, contract):
    pts = [s for s in samples if usable(s)]
    ts, sp = [s.t for s in pts], [s.spread for s in pts]
    out = []
    for t in trades:
        se = nearest(ts, sp, t["et"].replace(tzinfo=UTC).timestamp(), 75)
        sx = nearest(ts, sp, t["xt"].replace(tzinfo=UTC).timestamp(), 75)
        if se is not None and sx is not None:
            out.append((t, (se + sx) / 2.0 * R.LOT_SIZE * contract, se, sx))
    return out


def pair_candles(candles, bars, shift_h=0):
    """Join XM M15 candles to forward_test_log.csv on the 15-minute bar-close grid."""
    by_key = {int(round(b["dt"].replace(tzinfo=UTC).timestamp() / float(BAR_SECONDS))) * BAR_SECONDS: b for b in bars}
    out = []
    for c in candles:
        key = int(c["close"].replace(tzinfo=UTC).timestamp()) + shift_h * 3600
        b = by_key.get(key)
        if b is not None:
            out.append((c, b))
    return out


def wick_ratios(o, h, l, c):
    rng = h - l
    if rng <= 0:
        return None
    return (h - max(o, c)) / rng, (min(o, c) - l) / rng


def parity_stats(pairs):
    dc = [c["c"] - b["c"] for c, b in pairs]
    dh = [c["h"] - b["h"] for c, b in pairs]
    dl = [c["l"] - b["l"] for c, b in pairs]
    do = [c["o"] - b["o"] for c, b in pairs]
    dir_ok = up_ok = lo_ok = n_w = 0
    wd = []
    for c, b in pairs:
        sa = (c["c"] > c["o"]) - (c["c"] < c["o"])
        sb = (b["c"] > b["o"]) - (b["c"] < b["o"])
        dir_ok += sa == sb
        wa, wb = wick_ratios(c["o"], c["h"], c["l"], c["c"]), wick_ratios(b["o"], b["h"], b["l"], b["c"])
        if wa and wb:
            n_w += 1
            up_ok += (wa[0] >= R.WICK_RATIO_TARGET) == (wb[0] >= R.WICK_RATIO_TARGET)
            lo_ok += (wa[1] >= R.WICK_RATIO_TARGET) == (wb[1] >= R.WICK_RATIO_TARGET)
            wd.append(max(abs(wa[0] - wb[0]), abs(wa[1] - wb[1])))
    n = len(pairs)
    return dict(n=n, close_bias=st.mean(dc), close_abs=summarize([abs(x) for x in dc]),
                high_abs=summarize([abs(x) for x in dh]), low_abs=summarize([abs(x) for x in dl]),
                open_abs=summarize([abs(x) for x in do]),
                dir_agree=100.0 * dir_ok / n, up_gate_agree=100.0 * up_ok / max(n_w, 1),
                lo_gate_agree=100.0 * lo_ok / max(n_w, 1), wick_diff=summarize(wd))


def shift_scan(candles, bars):
    res = {}
    for h in range(-3, 4):
        pairs = pair_candles(candles, bars, h)
        if len(pairs) >= PARITY_MIN_PAIRS:
            res[h] = st.median(abs(c["c"] - b["c"]) for c, b in pairs)
    return res


def shifted_days(candles, bars, min_pairs=30):
    by_day = defaultdict(list)
    for c in candles:
        by_day[c["close"].date()].append(c)
    flagged = []
    for day, cs in sorted(by_day.items()):
        p0 = pair_candles(cs, bars, 0)
        if len(p0) < min_pairs:
            continue
        m0 = st.median(abs(c["c"] - b["c"]) for c, b in p0)
        best = (0, m0)
        for h in (-1, 1):
            ph = pair_candles(cs, bars, h)
            if len(ph) >= min_pairs:
                mh = st.median(abs(c["c"] - b["c"]) for c, b in ph)
                if mh < best[1]:
                    best = (h, mh)
        if best[0] != 0 and best[1] < 0.5 * m0 and m0 > 8:
            flagged.append((day, best[0], m0, best[1]))
    return flagged


def bar_spread_check(candles, samples, point):
    pts = [s for s in samples if usable(s)]
    ts = [s.t for s in pts]
    inside_env = n = 0
    diffs = []
    for c in candles:
        if c["sp"] is None:
            continue
        end = c["close"].replace(tzinfo=UTC).timestamp()
        i, j = bisect.bisect_left(ts, end - BAR_SECONDS), bisect.bisect_left(ts, end)
        win = pts[i:j]
        if len(win) < 5:
            continue
        idx_pts = c["sp"] * point
        lo = min(min(s.spread, s.smin if s.smin is not None else s.spread) for s in win)
        hi = max(max(s.spread, s.smax if s.smax is not None else s.spread) for s in win)
        n += 1
        inside_env += lo - 0.5 <= idx_pts <= hi + 0.5
        diffs.append(abs(idx_pts - st.median(s.spread for s in win)))
    if n < PARITY_MIN_PAIRS:
        return dict(n=n, verdict="INSUFFICIENT")
    ok = inside_env / n >= 0.80 and st.median(diffs) <= 1.5
    return dict(n=n, inside=100.0 * inside_env / n, med_diff=st.median(diffs),
                verdict="AGREES" if ok else "DISAGREES")


def pts_fmt(x):
    return "     n/a" if x is None else "%7.2fp" % x


def row_line(label, s, unit):
    if not s.get("n"):
        return "  %-26s %7d" % (label, 0)
    return "  %-26s %7d %s %s %s %s %s   $%5.2f / $%5.2f" % (
        label, s["n"], pts_fmt(s["med"]), pts_fmt(s["p90"]), pts_fmt(s["p95"]), pts_fmt(s["p99"]), pts_fmt(s["mx"]),
        s["med"] * unit, s["p95"] * unit)


TABLE_HEAD = "  %-26s %7s %8s %8s %8s %8s %8s   $/trade med / p95" % (
    "", "n", "median", "p90", "p95", "p99", "max")


def spread_tables(title, pts, unit):
    print(TABLE_HEAD)
    print(row_line(title, summarize([v for _, v in pts]), unit))
    print("  -- by UTC session (weekday | weekend) --")
    for name, _, _ in SESSIONS:
        for wk, lab in ((False, "weekday"), (True, "weekend")):
            v = [x for t, x in pts if session_of(t) == name and is_weekend(t) == wk]
            if v:
                print(row_line("%s %s" % (name, lab), summarize(v), unit))
    if BLACKOUT_WINDOWS:
        print("  -- blackout windows (America/New_York DST-aware) --")
        for _, _, _, _, label in BLACKOUT_WINDOWS:
            v = [x for t, x in pts if blackout_of(t) == label]
            if v:
                print(row_line(label[:26], summarize(v), unit))
        v = [x for t, x in pts if blackout_of(t) is None]
        if v:
            print(row_line("outside every blackout", summarize(v), unit))
    wd = summarize([x for t, x in pts if not is_weekend(t)])
    we = summarize([x for t, x in pts if is_weekend(t)])
    if wd.get("n") and we.get("n"):
        print("  weekend / weekday median ratio: %.2fx   (n=%d / %d)" % (
            we["med"] / wd["med"] if wd["med"] else float("nan"), we["n"], wd["n"]))


def hour_table(pts):
    print("  hour  weekday: n   med   p90   | weekend: n   med   p90   (pts on US100Cash, UTC)")
    for h in range(24):
        a = summarize([x for t, x in pts if dt_of(t).hour == h and not is_weekend(t)])
        b = summarize([x for t, x in pts if dt_of(t).hour == h and is_weekend(t)])
        fa = "%6d %5.2f %5.2f" % (a["n"], a["med"], a["p90"]) if a.get("n") else "     -     -     -"
        fb = "%6d %5.2f %5.2f" % (b["n"], b["med"], b["p90"]) if b.get("n") else "     -     -     -"
        print("   %02d  %s   | %s" % (h, fa, fb))


def one_r_usd(trades):
    pg = [t for t in trades if t["et"] >= R.GATES_DEPLOY]
    if len(pg) < 5:
        return None, None, len(pg)
    return (st.median(abs(t["entry"] - t["sl"]) * R.LOT_SIZE for t in pg),
            st.mean(t["profit"] for t in pg), len(pg))


def report(a):
    qdir = a.dir if os.path.isabs(a.dir) else os.path.join(a.root, a.dir)
    now = a.now or time.time()
    since = now - a.days * 86400 if a.days else None
    samples, malformed, nfiles = load_quotes(qdir, since)
    candles = load_candles(qdir)
    spec = load_spec(qdir)
    contract = ((spec or {}).get("symbol_info") or {}).get("trade_contract_size") or 1.0
    point = ((spec or {}).get("symbol_info") or {}).get("point") or 0.01
    unit = R.LOT_SIZE * contract

    print("xm_quote_report (US100Cash M15) - %s  (%d quote files, %d rows, %d candles%s)" % (
        qdir, nfiles, len(samples), len(candles), ", %d malformed lines skipped" % malformed if malformed else ""))
    if not samples:
        print("  no quote rows yet. Install the sidecar (docs/XM-LOGGER.md) and let it run.")
        return 1

    # ---- 1. LOGGER --------------------------------------------------------------------
    cov = coverage(samples)
    print("\n== 1. LOGGER: progress against Stage B-i (>= %d days incl. %d weekends) ==" % (
        TARGET_DAYS, TARGET_WEEKENDS))
    print("  %s -> %s UTC  (%.1f days)   newest row %.0f min ago" % (
        Q.utc_str(samples[0].t), Q.utc_str(samples[-1].t), cov["span_days"], (now - samples[-1].t) / 60.0))
    ok_days, ok_wk, met = stage_b_progress(cov)
    print("  complete UTC days (>= %.0f%% of rows): %d / %d    complete weekends (Sat+Sun): %d / %d" % (
        100 * DAY_COMPLETE_FRAC, ok_days, TARGET_DAYS, ok_wk, TARGET_WEEKENDS))
    print("  rows %d of ~%.0f expected (%.1f%%), interval %ds; outage time %.1f h in %d gaps > %d min" % (
        cov["rows"], cov["expected"], 100.0 * cov["rows"] / max(cov["expected"], 1), cov["interval"],
        cov["outage_s"] / 3600.0, len(cov["outages"]), GAP_MIN_S // 60))
    for t0, d in cov["outages"][:3]:
        print("     longest gaps: %s UTC for %.0f min" % (Q.utc_str(t0), d / 60.0))
    runs = unusable_runs(samples, cov["interval"])
    if runs:
        print("  no-usable-quote runs >= %d min (market closed / maintenance / stale): %d, %.1f h total" % (
            GAP_MIN_S // 60, len(runs), sum(d for _, d in runs) / 3600.0))
    fl = Counter(f for s in samples for f in s.flags)
    print("  flags: %s    offsets seen: %s" % (
        ", ".join("%s %d" % kv for kv in sorted(fl.items())) or "none",
        ", ".join("%+gh" % (o / 3600.0) for o in sorted({s.off for s in samples if s.off is not None})) or "unknown"))
    if BLACKOUT_WINDOWS:
        bd = blackout_days(samples, cov["interval"])
        print("  blackout windows covered (days with >= 80%% of rows): %s" % (
            ", ".join("%s %d" % (" ".join(k.split()[:2]), v) for k, v in bd.items())))
    print("  Stage B-i exit: %s" % ("MET" if met else "NOT YET (%d more complete days, %d more weekends)" % (
        max(0, TARGET_DAYS - ok_days), max(0, TARGET_WEEKENDS - ok_wk))))

    # ---- 2. SPREAD --------------------------------------------------------------------
    good = [s for s in samples if usable(s)]
    pts = [(s.t, s.spread) for s in good]
    print("\n== 2. SPREAD: what XM charged on US100Cash (usable %d of %d rows; pts; x%.2f = $/trade) ==" % (
        len(good), len(samples), unit))
    oneR, gross, n_pg = one_r_usd(R.load_trades(os.path.join(a.root, "trades.csv"))
                                  if os.path.exists(os.path.join(a.root, "trades.csv")) else [])
    spread_tables("all usable samples", pts, unit)
    bar = [(s.t, s.spread) for s in good if int(s.t) % BAR_SECONDS == 0 and "LATE" not in s.flags]
    print("  -- at the M15 bar close (:00/:15/:30/:45) --")
    print(row_line("bar-close samples", summarize([v for _, v in bar]), unit))
    env = [s.smax for s in good if s.smax is not None]
    print(row_line("5 s spike envelope (max)", summarize(env), unit))
    vals = [v for _, v in pts]
    print("\n  share of usable samples ABOVE (all | bar-close):")
    cuts = [("assumed cost $%.2f/trade = %.2f pts" % (ASSUMED_USD_PER_TRADE, ASSUMED_USD_PER_TRADE / unit),
             ASSUMED_USD_PER_TRADE / unit),
            ("hard-cap guard %.1f pts/US100Cash" % HARD_CAP_PTS, HARD_CAP_PTS)]
    if gross and gross > 0:
        cuts.append(("break-even %.2f pts (post-gate gross +$%.2f/trade, n=%d)" % (gross / unit, gross, n_pg),
                     gross / unit))
    else:
        cuts.append(("break-even reference 15.00 pts ($1.50/trade)", 15.0))
    if oneR:
        for c in SHARE_1R_CUTS:
            cuts.append(("%.0f%% of median 1R ($%.2f) = %.2f pts" % (100 * c, oneR, c * oneR / unit), c * oneR / unit))
    else:
        cuts.append(("35% of reference 1R ($7.00) = 24.50 pts", 24.5))
    for label, thr in sorted(cuts, key=lambda x: x[1]):
        print("    %5.1f%% | %5.1f%%   > %s" % (share_above(vals, thr), share_above([v for _, v in bar], thr), label))
    print("\n  hour-of-day profile (usable samples):")
    hour_table(pts)
    allin = summarize(vals)
    if allin.get("n"):
        print("\n  spread-only median $%.2f/trade vs Stage C limit $%.2f all-in" % (
            allin["med"] * unit, STAGE_C_MEDIAN_LIMIT))

    # ---- 3. COST ----------------------------------------------------------------------
    print("\n== 3. COST: $%.2f assumed vs spread measured at entry/exit ==" % ASSUMED_USD_PER_TRADE)
    trades_path = os.path.join(a.root, "trades.csv")
    if not os.path.exists(trades_path):
        print("  no trades.csv at %s" % a.root)
    else:
        trades = [t for t in R.load_trades(trades_path) if t["et"] >= R.GATES_DEPLOY]
        tc = trade_costs(trades, samples, contract)
        if not tc:
            print("  no closed post-gate trade overlaps quote data yet (%d trades in ledger)" % len(trades))
        else:
            costs = [c for _, c, _, _ in tc]
            gross_sum = sum(t["profit"] for t, _, _, _ in tc)
            print("  %d trades with fresh quotes at entry and exit" % len(tc))
            print("  measured round trip: mean $%.2f  median $%.2f  p90 $%.2f  max $%.2f   (assumed $%.2f)" % (
                st.mean(costs), st.median(costs), pct(sorted(costs), .9), max(costs), ASSUMED_USD_PER_TRADE))
            print("  same trades: gross %+.2f | net at $%.2f flat %+.2f | net at MEASURED cost %+.2f" % (
                gross_sum, ASSUMED_USD_PER_TRADE, gross_sum - ASSUMED_USD_PER_TRADE * len(tc), gross_sum - sum(costs)))

    # ---- 4. PARITY --------------------------------------------------------------------
    print("\n== 4. PARITY: XM M15 candles vs forward_test_log.csv ==")
    log_path = os.path.join(a.root, "forward_test_log.csv")
    if not candles:
        print("  no candles logged yet")
    elif not os.path.exists(log_path):
        print("  no forward_test_log.csv at %s" % a.root)
    else:
        bars = R.load_bars(log_path)
        pairs = pair_candles(candles, bars, 0)
        lo, hi = candles[0]["close"], candles[-1]["close"]
        in_range = [b for b in bars if lo <= b["dt"] <= hi]
        print("  XM candles %d (%s -> %s UTC), log bars in range %d, matched %d (%.1f%%)" % (
            len(candles), lo, hi, len(in_range), len(pairs), 100.0 * len(pairs) / max(len(in_range), 1)))
        if len(pairs) < PARITY_MIN_PAIRS:
            print("  too few matched bars for statistics (< %d)" % PARITY_MIN_PAIRS)
        else:
            ps = parity_stats(pairs)
            print("  close - close (XM minus log): bias %+.2f, |diff| median %.2f p95 %.2f max %.2f" % (
                ps["close_bias"], ps["close_abs"]["med"], ps["close_abs"]["p95"], ps["close_abs"]["mx"]))
            sc = shift_scan(candles, bars)
            if sc:
                best = min(sc, key=sc.get)
                if best != 0:
                    print("  WARNING: XM candles match log best at %+d h shift - server-time conversion error!" % best)
                else:
                    print("  OK: no time shift - server-time conversion is accurate")
        bsc = bar_spread_check(candles, samples, point)
        if bsc["verdict"] == "INSUFFICIENT":
            print("  bar-spread check: not enough overlap with live samples yet (%d bars)" % bsc["n"])
        else:
            print("  bar-spread check: terminal per-bar spread %s live samples (%d bars, %.0f%% inside envelope)" % (
                "AGREES WITH" if bsc["verdict"] == "AGREES" else "DISAGREES WITH", bsc["n"], bsc["inside"]))

    # ---- 5. SPEC ----------------------------------------------------------------------
    print("\n== 5. SPEC: contract facts for US100Cash ==")
    if not spec:
        print("  no symbol_spec.json yet")
    else:
        si, dec, acct, term = (spec.get("symbol_info") or {}, spec.get("decoded") or {},
                               spec.get("account") or {}, spec.get("terminal") or {})
        print("  captured %s UTC  label %r  history entries %d" % (
            spec.get("captured_utc"), spec.get("label"), spec_changes(qdir)))
        print("  account: %s, %s, leverage 1:%s, %s | terminal build %s, maxbars %s" % (
            dec.get("account_kind"), dec.get("margin_mode"), acct.get("leverage"), acct.get("currency"),
            term.get("build"), term.get("maxbars")))
        print("  execution %s | filling flags %s | stops level %s pts | volume min %s step %s | contract %s" % (
            dec.get("execution_mode"), dec.get("filling_allowed_flags"), si.get("trade_stops_level"),
            si.get("volume_min"), si.get("volume_step"), si.get("trade_contract_size")))
        pr = (spec.get("probes") or {}).get("calc_profit_usd_0.10lot_plus_100pts")
        checks = [("contract size 1.0", si.get("trade_contract_size") == 1.0),
                  ("0.10 lot >= volume_min", (si.get("volume_min") or 0.01) <= 0.10),
                  ("0.10 lot x 100 pts = $10.00", pr == 10.0)]
        print("  assumption checks: " + "; ".join("%s %s" % (n, "OK" if ok else "MISMATCH") for n, ok in checks))
    return 0


def quiet_line(a):
    qdir = a.dir if os.path.isabs(a.dir) else os.path.join(a.root, a.dir)
    now = a.now or time.time()
    samples, malformed, nfiles = load_quotes(qdir, since=now - QUIET_WINDOW_DAYS * 86400)
    if not samples:
        return "xm logger: not collecting yet (no quote rows in %s)" % os.path.relpath(qdir, a.root)
    cov = coverage(samples)
    age_min = (now - samples[-1].t) / 60.0
    good = sorted(s.spread for s in samples if usable(s))
    now_dt = datetime.fromtimestamp(now, tz=UTC)
    if age_min * 60 <= STALE_AFTER_S:
        status = "OK"
    elif is_market_quiet(now_dt):
        status = "OK (market closed; newest row %.1f h old)" % (age_min / 60.0)
    else:
        status = "STALE (newest row %.1f h old - is mt5quotes-nasdaq running?)" % (age_min / 60.0)
    tail = ""
    if good:
        unit = R.LOT_SIZE * (((load_spec(qdir) or {}).get("symbol_info") or {}).get("trade_contract_size") or 1.0)
        tail = " | spread median %.2f p95 %.2f pts ($%.2f/trade median)" % (
            pct(good, .5), pct(good, .95), pct(good, .5) * unit)
    return "xm logger: %s | %d/%d complete days, %d/%d weekends | rows %d, outage %.1f h%s" % (
        status, len(cov["complete"]), TARGET_DAYS, len(cov["weekends"]), TARGET_WEEKENDS, cov["rows"],
        cov["outage_s"] / 3600.0, tail)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Report on XM US100Cash quote / M15 candle / spec logger data")
    ap.add_argument("--root", default=ROOT, help="repo root (trades.csv, forward_test_log.csv live here)")
    ap.add_argument("--dir", default="xm_data", help="logger data directory (relative to --root)")
    ap.add_argument("--days", type=int, default=0, help="only the newest N UTC days of quote rows (0 = all)")
    ap.add_argument("--quiet", action="store_true", help="one advisory line; never fails")
    ap.add_argument("--now", type=float, default=None, help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    if a.quiet:
        try:
            print(quiet_line(a))
        except Exception as e:
            print("xm logger: report error (%s: %s)" % (type(e).__name__, e))
        return 0
    return report(a)


if __name__ == "__main__":
    sys.exit(main())
