#!/usr/bin/env python3
"""xm_quote_report - read what the XM quote logger collected (xm_data/) and answer the
questions it was built for. Stdlib only, read-only, runs anywhere the repo is checked out.

  python3 tools/xm_quote_report.py              full report
  python3 tools/xm_quote_report.py --quiet      one advisory line (used by autosync's digest)
  python3 tools/xm_quote_report.py --days 14    only the newest 14 UTC days of quote rows
  python3 tools/xm_quote_report.py --dir xm_data --root .

Sections (docs/XM-LOGGER.md has the column dictionary and the decision rules):
  1. LOGGER   progress against the Stage B-i exit (>= 14 days incl. 2 weekends, outages,
              blackout coverage) - the clock the whole stage is waiting for
  2. SPREAD   what XM actually charged, by session / weekday vs weekend / blackout window /
              hour of day, in $/BTC and in $ per trade at 0.01 lot, against the break-even
              ($87/BTC) and the hard-cap proposal ($60/BTC)
  3. COST     the assumed $0.40 against the spread measured at the moments the ledger's
              trades actually entered and exited (only trades after the logger started)
  4. PARITY   XM M5 candles against forward_test_log.csv: coverage, OHLC and wick
              agreement, and a time-shift scan that exposes a server-time/DST mistake
  5. SPEC     the contract facts Stage A must not guess (execution/filling modes, stops
              level, swap, demo-vs-real) and a check of the $0.01-per-$1 lot arithmetic

Every number here is a measurement of the XM feed, not a trading rule. The thresholds are
the review's PROPOSALS (docs/REVIEW-2026-10-01.md section 7) and are decided by a human.
Spread-only costs are a LOWER bound on the all-in round trip (slippage, commission and swap
come from Stage C deals). No --spread flag on purpose: the docs' command blocks may only
carry `--spread 0.40` (tools/handoff_check.py), and this tool measures the spread instead.
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

try:                                    # the engine's own windows: never re-declare them here
    from trade_filter import BLACKOUT_WINDOWS  # noqa: E402
except Exception:                       # pragma: no cover - the report must not die on this
    BLACKOUT_WINDOWS = []

UTC = timezone.utc

# --- reference numbers from the docs (all PROPOSALS; kept here so the report quotes them) ---
ASSUMED_USD_PER_TRADE = 0.40            # the flat cost every P/L in the repo is netted with
HARD_CAP_USD_BTC = 60.0                 # review section 7 Stage A: hard cap, e.g. <= $60/BTC
SHARE_1R_CUTS = (0.20, 0.30, 0.40)      # review section 3.1: spread as a share of 1R
STAGE_C_MEDIAN_LIMIT = 0.60             # review section 7 Stage C: all-in median <= $0.60/trade
STAGE_C_BUCKET_LIMIT = 1.00             # ... and no session/weekend bucket median above $1.00
TARGET_DAYS, TARGET_WEEKENDS = 14, 2    # Stage B-i exit
DAY_COMPLETE_FRAC = 0.80                # a UTC day counts as logged with >= 80 % of its rows
GAP_MIN_S = 300                         # a hole between rows longer than this is an outage
STALE_AFTER_S = 15 * 60                 # --quiet: no new row for this long = STALE
SESSIONS = (("ASIA", 0, 8), ("LONDON", 8, 13), ("NY", 13, 21), ("LATE", 21, 24))   # UTC hours
BAD_FLAGS = frozenset({"STALE", "NOOFFSET", "NOQUOTE", "BADQUOTE"})
PARITY_MIN_PAIRS = 50
QUIET_WINDOW_DAYS = 45                  # --quiet reads only this much history: autosync runs it every 15 min

Sample = namedtuple("Sample", "t spread smin smax flags age n_ok n_bad off")


# =========================================================================================
# loading
# =========================================================================================
def _f(x):
    try:
        return float(x) if x not in ("", None) else None
    except ValueError:
        return None


def load_quotes(qdir, since=None):
    """-> (samples ascending, malformed line count, number of files). Torn or misaligned
    lines are skipped and counted, never fatal."""
    rows, bad = [], 0
    files = sorted(glob.glob(os.path.join(qdir, "quotes-????-??-??.csv")))
    for path in files:
        if since is not None:                   # day files are named by UTC date: skip the old ones unread
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
    """XM shadow candles -> dicts with close (naive UTC datetime, the log's convention)."""
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


# =========================================================================================
# statistics
# =========================================================================================
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
    """A row whose spread is a real, fresh point sample (not stale, not an outage row)."""
    return s.spread is not None and not (s.flags & BAD_FLAGS)


def share_above(vals, thr):
    return 100.0 * sum(1 for x in vals if x > thr) / len(vals) if vals else 0.0


def dt_of(t):
    return datetime.fromtimestamp(t, tz=UTC)


def is_weekend(t):
    return dt_of(t).weekday() >= 5          # UTC Saturday / Sunday


def session_of(t):
    h = dt_of(t).hour
    for name, a, b in SESSIONS:
        if a <= h < b:
            return name
    return "?"


def blackout_of(t):
    d = dt_of(t)
    m = d.hour * 60 + d.minute
    for sh, sm, eh, em, label in BLACKOUT_WINDOWS:
        if sh * 60 + sm <= m <= eh * 60 + em:
            return label
    return None


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
    """Runs of consecutive rows that carry NO usable quote (STALE / NOQUOTE / BADQUOTE / NOOFFSET).
    These are the outages a gap list cannot see because the logger kept writing rows through
    them - an exchange/broker maintenance window, a frozen feed, a closed market. XM's FAQ reports
    a weekly Saturday crypto-CFD maintenance window, which would appear here."""
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
    """(complete days, complete weekends, exit met?) - the Stage B-i clock."""
    d, w = len(cov["complete"]), len(cov["weekends"])
    return d, w, d >= TARGET_DAYS and w >= TARGET_WEEKENDS


def blackout_days(samples, interval):
    """Per blackout window: distinct UTC days with >= 80 % of the window's expected rows."""
    out = {}
    for sh, sm, eh, em, label in BLACKOUT_WINDOWS:
        need = DAY_COMPLETE_FRAC * ((eh * 60 + em) - (sh * 60 + sm)) * 60.0 / max(interval, 1)
        per = Counter(dt_of(s.t).date() for s in samples if blackout_of(s.t) == label)
        out[label] = sum(1 for n in per.values() if n >= need)
    return out


# =========================================================================================
# the analyses
# =========================================================================================
def nearest(ts, vals, t, tol):
    i = bisect.bisect_left(ts, t)
    best = None
    for j in (i - 1, i):
        if 0 <= j < len(ts) and abs(ts[j] - t) <= tol and (best is None or abs(ts[j] - t) < abs(ts[best] - t)):
            best = j
    return None if best is None else vals[best]


def trade_costs(trades, samples, contract):
    """Measured cost of each trade: a round trip pays half the spread in and half out, so
    cost = (spread at entry + spread at exit) / 2 x lot x contract. Only trades whose entry
    AND exit have a fresh quote sample within 75 s."""
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
    """Join XM candles to the forward-test log. Log rows are stamped at bar CLOSE, sometimes
    a second or two late, so the join key is the close rounded to the 5-minute grid."""
    by_key = {int(round(b["dt"].replace(tzinfo=UTC).timestamp() / 300.0)) * 300: b for b in bars}
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
    return (h - max(o, c)) / rng, (min(o, c) - l) / rng      # (upper, lower)


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
    """Median |close difference| when the XM candles are shifted by -3..+3 hours. The right
    answer is 0; anything else means the server-time conversion is wrong (or a DST change)."""
    res = {}
    for h in range(-3, 4):
        pairs = pair_candles(candles, bars, h)
        if len(pairs) >= PARITY_MIN_PAIRS:
            res[h] = st.median(abs(c["c"] - b["c"]) for c, b in pairs)
    return res


def shifted_days(candles, bars, min_pairs=60):
    """UTC days where a +-1 h shift matches the log far better than no shift (a DST change
    or a back-fill converted with the wrong offset)."""
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
        if best[0] != 0 and best[1] < 0.5 * m0 and m0 > 30:
            flagged.append((day, best[0], m0, best[1]))
    return flagged


def bar_spread_check(candles, samples, point):
    """Does the terminal's per-bar spread (points) agree with the live samples? For each XM
    candle compare it with the point samples inside that bar's 5 minutes."""
    pts = [s for s in samples if usable(s)]
    ts = [s.t for s in pts]
    inside_env = n = 0
    diffs = []
    for c in candles:
        if c["sp"] is None:
            continue
        end = c["close"].replace(tzinfo=UTC).timestamp()
        i, j = bisect.bisect_left(ts, end - 300), bisect.bisect_left(ts, end)
        win = pts[i:j]
        if len(win) < 5:
            continue
        usd = c["sp"] * point
        lo = min(min(s.spread, s.smin if s.smin is not None else s.spread) for s in win)
        hi = max(max(s.spread, s.smax if s.smax is not None else s.spread) for s in win)
        n += 1
        inside_env += lo - 1.0 <= usd <= hi + 1.0
        diffs.append(abs(usd - st.median(s.spread for s in win)))
    if n < PARITY_MIN_PAIRS:
        return dict(n=n, verdict="INSUFFICIENT")
    ok = inside_env / n >= 0.80 and st.median(diffs) <= 5.0
    return dict(n=n, inside=100.0 * inside_env / n, med_diff=st.median(diffs),
                verdict="AGREES" if ok else "DISAGREES")


# =========================================================================================
# rendering
# =========================================================================================
def money(x):
    return "     n/a" if x is None else "$%7.2f" % x


def row_line(label, s, unit):
    if not s.get("n"):
        return "  %-26s %7d" % (label, 0)
    return "  %-26s %7d %s %s %s %s %s   $%5.2f / $%5.2f" % (
        label, s["n"], money(s["med"]), money(s["p90"]), money(s["p95"]), money(s["p99"]), money(s["mx"]),
        s["med"] * unit, s["p95"] * unit)


TABLE_HEAD = "  %-26s %7s %8s %8s %8s %8s %8s   $/trade med / p95" % (
    "", "n", "median", "p90", "p95", "p99", "max")


def spread_tables(title, pts, unit):
    """pts = [(t, spread_usd_per_btc)]. Prints the session / weekend / blackout / hour views."""
    print(TABLE_HEAD)
    print(row_line(title, summarize([v for _, v in pts]), unit))
    print("  -- by UTC session (weekday | weekend) --")
    for name, _, _ in SESSIONS:
        for wk, lab in ((False, "weekday"), (True, "weekend")):
            v = [x for t, x in pts if session_of(t) == name and is_weekend(t) == wk]
            if v:
                print(row_line("%s %s" % (name, lab), summarize(v), unit))
    if BLACKOUT_WINDOWS:
        print("  -- blackout windows (the engine's own, UTC) --")
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
        print("  weekend / weekday median ratio: %.2fx   (third-party guides claim 2-4x; n=%d / %d)" % (
            we["med"] / wd["med"] if wd["med"] else float("nan"), we["n"], wd["n"]))


def hour_table(pts):
    print("  hour  weekday: n   med   p90   | weekend: n   med   p90   ($/BTC, UTC)")
    for h in range(24):
        a = summarize([x for t, x in pts if dt_of(t).hour == h and not is_weekend(t)])
        b = summarize([x for t, x in pts if dt_of(t).hour == h and is_weekend(t)])
        fa = "%6d %5.0f %5.0f" % (a["n"], a["med"], a["p90"]) if a.get("n") else "     -     -     -"
        fb = "%6d %5.0f %5.0f" % (b["n"], b["med"], b["p90"]) if b.get("n") else "     -     -     -"
        print("   %02d  %s   | %s" % (h, fa, fb))


def one_r_usd(trades):
    pg = [t for t in trades if t["et"] >= R.GATES_DEPLOY]
    if len(pg) < 10:
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
    unit = R.LOT_SIZE * contract                    # $ per trade per $1 of spread

    print("xm_quote_report - %s  (%d quote files, %d rows, %d candles%s)" % (
        qdir, nfiles, len(samples), len(candles), ", %d malformed lines skipped" % malformed if malformed else ""))
    if not samples:
        print("  no quote rows yet. Install the sidecar (docs/XM-LOGGER.md) and let it run.")
        return 1

    # ---- 1. LOGGER --------------------------------------------------------------------
    cov = coverage(samples)
    print("\n== 1. LOGGER: progress against the Stage B-i exit (>= %d days incl. %d weekends) ==" % (
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
        print("  no-usable-quote runs >= %d min (rows kept, quotes stale/absent): %d, %.1f h in total; longest: %s" % (
            GAP_MIN_S // 60, len(runs), sum(d for _, d in runs) / 3600.0,
            "; ".join("%s UTC (%s) %.0f min" % (Q.utc_str(t0), dt_of(t0).strftime("%a"), d / 60.0)
                      for t0, d in runs[:3])))
    fl = Counter(f for s in samples for f in s.flags)
    print("  flags: %s    offsets seen: %s" % (
        ", ".join("%s %d" % kv for kv in sorted(fl.items())) or "none",
        ", ".join("%+gh" % (o / 3600.0) for o in sorted({s.off for s in samples if s.off is not None})) or "unknown"))
    ages = sorted(s.age for s in samples if s.age is not None)
    if ages:
        print("  tick age median %.1f s, p99 %.1f s%s" % (pct(ages, .5), pct(ages, .99),
              "   <-- WARNING: large median age = box clock skew or a stale feed" if pct(ages, .5) > 30 else ""))
    if BLACKOUT_WINDOWS:
        bd = blackout_days(samples, cov["interval"])
        print("  blackout windows covered (days with >= 80%% of rows): %s" % (
            ", ".join("%s %d" % (" ".join(k.split()[:2]), v) for k, v in bd.items())))
    print("  Stage B-i exit: %s" % ("MET - decide the session-aware cost and the weekend rule from section 2"
                                    if met else "NOT YET (%d more complete days, %d more weekends)" % (
                                        max(0, TARGET_DAYS - ok_days), max(0, TARGET_WEEKENDS - ok_wk))))

    # ---- 2. SPREAD --------------------------------------------------------------------
    good = [s for s in samples if usable(s)]
    pts = [(s.t, s.spread) for s in good]
    print("\n== 2. SPREAD: what XM charged (usable %d of %d rows; $/BTC; x%.2f = $ per trade) ==" % (
        len(good), len(samples), unit))
    oneR, gross, n_pg = one_r_usd(R.load_trades(os.path.join(a.root, "trades.csv"))
                                  if os.path.exists(os.path.join(a.root, "trades.csv")) else [])
    spread_tables("all usable samples", pts, unit)
    bar = [(s.t, s.spread) for s in good if int(s.t) % 300 == 0 and "LATE" not in s.flags]
    print("  -- at the M5 bar close (the quote a bar-close signal fills at) --")
    print(row_line("bar-close samples", summarize([v for _, v in bar]), unit))
    env = [s.smax for s in good if s.smax is not None]
    print(row_line("5 s spike envelope (max)", summarize(env), unit))
    vals = [v for _, v in pts]
    print("\n  share of usable samples ABOVE (all | bar-close):")
    cuts = [("assumed cost $%.2f/trade = $%.0f/BTC" % (ASSUMED_USD_PER_TRADE, ASSUMED_USD_PER_TRADE / unit),
             ASSUMED_USD_PER_TRADE / unit),
            ("hard-cap proposal $%.0f/BTC" % HARD_CAP_USD_BTC, HARD_CAP_USD_BTC)]
    if gross and gross > 0:
        cuts.append(("break-even $%.0f/BTC (post-gate gross +$%.2f/trade, n=%d)" % (gross / unit, gross, n_pg),
                     gross / unit))
    if oneR:
        for c in SHARE_1R_CUTS:
            cuts.append(("%.0f%% of median 1R ($%.2f) = $%.0f/BTC" % (100 * c, oneR, c * oneR / unit), c * oneR / unit))
    for label, thr in sorted(cuts, key=lambda x: x[1]):
        print("    %5.1f%% | %5.1f%%   > %s" % (share_above(vals, thr), share_above([v for _, v in bar], thr), label))
    print("\n  hour-of-day profile (usable samples):")
    hour_table(pts)
    allin = summarize(vals)
    if allin.get("n"):
        print("\n  spread-only median $%.2f/trade vs Stage C limit $%.2f all-in (a lower bound: slippage, commission,"
              " swap come from Stage C deals)" % (allin["med"] * unit, STAGE_C_MEDIAN_LIMIT))

    # ---- 3. COST on the actual trades -------------------------------------------------
    print("\n== 3. COST: $%.2f assumed vs the spread measured when the ledger's trades entered/exited ==" % (
        ASSUMED_USD_PER_TRADE))
    trades_path = os.path.join(a.root, "trades.csv")
    if not os.path.exists(trades_path):
        print("  no trades.csv at %s" % a.root)
    else:
        trades = [t for t in R.load_trades(trades_path) if t["et"] >= R.GATES_DEPLOY]
        tc = trade_costs(trades, samples, contract)
        if not tc:
            print("  no closed post-gate trade overlaps the quote data yet (%d post-gate trades in the ledger)" % len(trades))
        else:
            costs = [c for _, c, _, _ in tc]
            gross_sum = sum(t["profit"] for t, _, _, _ in tc)
            print("  %d post-gate trades with fresh quotes at entry and exit" % len(tc))
            print("  measured round trip: mean $%.2f  median $%.2f  p90 $%.2f  max $%.2f   (assumed $%.2f)" % (
                st.mean(costs), st.median(costs), pct(sorted(costs), .9), max(costs), ASSUMED_USD_PER_TRADE))
            print("  same trades: gross %+.2f | net at $%.2f flat %+.2f | net at the MEASURED cost %+.2f" % (
                gross_sum, ASSUMED_USD_PER_TRADE, gross_sum - ASSUMED_USD_PER_TRADE * len(tc), gross_sum - sum(costs)))
            if len(tc) < 30:
                print("  (n=%d is far too small to conclude anything - this is a plumbing check until n >= ~30)" % len(tc))

    # ---- 4. PARITY --------------------------------------------------------------------
    print("\n== 4. PARITY: XM M5 candles vs forward_test_log.csv ==")
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
        print("  XM candles %d (%s -> %s UTC), log bars in that range %d, matched %d (%.1f%% of the log)" % (
            len(candles), lo, hi, len(in_range), len(pairs), 100.0 * len(pairs) / max(len(in_range), 1)))
        if len(pairs) < PARITY_MIN_PAIRS:
            print("  too few matched bars for statistics (< %d)" % PARITY_MIN_PAIRS)
        else:
            ps = parity_stats(pairs)
            print("  close - close (XM minus log): bias %+.2f, |diff| median $%.2f p95 $%.2f max $%.2f" % (
                ps["close_bias"], ps["close_abs"]["med"], ps["close_abs"]["p95"], ps["close_abs"]["mx"]))
            print("  |high diff| median $%.2f p95 $%.2f   |low diff| median $%.2f p95 $%.2f   |open diff| median $%.2f"
                  % (ps["high_abs"]["med"], ps["high_abs"]["p95"], ps["low_abs"]["med"], ps["low_abs"]["p95"],
                     ps["open_abs"]["med"]))
            print("  candle direction agrees on %.1f%% of bars; wick>=%.2f gate agrees: upper %.1f%%, lower %.1f%%;"
                  " wick-ratio |diff| median %.3f p95 %.3f" % (
                      ps["dir_agree"], R.WICK_RATIO_TARGET, ps["up_gate_agree"], ps["lo_gate_agree"],
                      ps["wick_diff"]["med"], ps["wick_diff"]["p95"]))
            sc = shift_scan(candles, bars)
            if sc:
                best = min(sc, key=sc.get)
                print("  time-shift scan (median |close diff| by shift): %s" % "  ".join(
                    "%+dh $%.1f" % (h, sc[h]) for h in sorted(sc)))
                if best != 0:
                    print("  WARNING: the XM candles match the log best at a %+d h shift - the server-time "
                          "conversion is WRONG (offset_s column, DST?)" % best)
                else:
                    print("  OK: no time shift - the server-time conversion is right")
            flagged = shifted_days(candles, bars)
            for h in sorted({f[1] for f in flagged}):
                days = [f for f in flagged if f[1] == h]
                print("  WARNING: %d UTC day(s) (%s .. %s) match the log at a %+d h shift (median |close diff| "
                      "$%.1f -> $%.1f): a server DST change inside a back-fill, or a wrong offset_s" % (
                          len(days), days[0][0], days[-1][0], h, st.median(f[2] for f in days),
                          st.median(f[3] for f in days)))
        bsc = bar_spread_check(candles, samples, point)
        if bsc["verdict"] == "INSUFFICIENT":
            print("  bar-spread check: not enough overlap with live samples yet (%d bars)" % bsc["n"])
        else:
            print("  bar-spread check: the terminal's per-bar spread %s the live samples (%d bars, %.0f%% inside the "
                  "sampled envelope, median |diff| $%.2f)" % (
                      "AGREES WITH" if bsc["verdict"] == "AGREES" else "DISAGREES WITH",
                      bsc["n"], bsc["inside"], bsc["med_diff"]))
            if bsc["verdict"] == "AGREES":
                hist = [(c["close"].replace(tzinfo=UTC).timestamp() - 150, c["sp"] * point)
                        for c in candles if c["sp"] is not None]
                print("\n  PROVISIONAL history from the back-filled bar spreads (the check above passed; "
                      "%d bars, %s -> %s):" % (len(hist), candles[0]["close"], candles[-1]["close"]))
                spread_tables("bar spreads", hist, unit)

    # ---- 5. SPEC ----------------------------------------------------------------------
    print("\n== 5. SPEC: contract facts for Stage A ==")
    if not spec:
        print("  no symbol_spec.json yet")
    else:
        si, dec, acct, term = spec.get("symbol_info") or {}, spec.get("decoded") or {}, spec.get("account") or {}, spec.get("terminal") or {}
        print("  captured %s UTC  label %r  history entries %d (a new one = XM changed something)" % (
            spec.get("captured_utc"), spec.get("label"), spec_changes(qdir)))
        print("  account: %s, %s, leverage 1:%s, %s | terminal build %s, maxbars %s" % (
            dec.get("account_kind"), dec.get("margin_mode"), acct.get("leverage"), acct.get("currency"),
            term.get("build"), term.get("maxbars")))
        print("  execution %s | filling flags %s | order types %s | symbol trade mode %s" % (
            dec.get("execution_mode"), dec.get("filling_allowed_flags"), dec.get("order_types_allowed"),
            dec.get("symbol_trade_mode")))
        print("  stops level %s pts, freeze level %s pts | volume min %s step %s max %s | contract %s | digits %s point %s" % (
            si.get("trade_stops_level"), si.get("trade_freeze_level"), si.get("volume_min"), si.get("volume_step"),
            si.get("volume_max"), si.get("trade_contract_size"), si.get("digits"), si.get("point")))
        print("  swap: %s long %s short %s, triple on %s | spread now %s pts (floating: %s)" % (
            dec.get("swap_mode"), si.get("swap_long"), si.get("swap_short"), dec.get("swap_triple_day"),
            spec.get("spread_points_now"), si.get("spread_float")))
        pr = (spec.get("probes") or {}).get("calc_profit_usd_0.01lot_plus_100usd")
        checks = [("contract size 1.0 (handoff)", si.get("trade_contract_size") == 1.0),
                  ("min lot 0.01 (handoff)", si.get("volume_min") == 0.01),
                  ("0.01 lot x $100 move = $1.00 (order_calc_profit)", pr == 1.0)]
        print("  assumption checks: " + "; ".join("%s %s" % (n, "OK" if ok else "MISMATCH (%s)" % (pr if "calc" in n else "see above"))
                                                  for n, ok in checks))
        if dec.get("account_kind") == "DEMO":
            print("  NOTE: these spreads come from a DEMO account. XM demo normally mirrors live pricing, but Stage C's cost "
                  "criteria must be confirmed on the account that will actually trade.")
        if spec.get("errors"):
            print("  spec probe errors: %s" % spec["errors"])
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
    status = "OK" if age_min * 60 <= STALE_AFTER_S else "STALE (newest row %.1f h old - is mt5quotes-btc running?)" % (age_min / 60.0)
    tail = ""
    if good:
        unit = R.LOT_SIZE * (((load_spec(qdir) or {}).get("symbol_info") or {}).get("trade_contract_size") or 1.0)
        tail = " | spread median $%.0f p95 $%.0f /BTC ($%.2f/trade median)" % (
            pct(good, .5), pct(good, .95), pct(good, .5) * unit)
    return "xm logger: %s | %d/%d complete days, %d/%d weekends | rows %d, outage %.1f h%s" % (
        status, len(cov["complete"]), TARGET_DAYS, len(cov["weekends"]), TARGET_WEEKENDS, cov["rows"],
        cov["outage_s"] / 3600.0, tail)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Report on the XM quote / candle / spec logger data")
    ap.add_argument("--root", default=ROOT, help="repo root (trades.csv, forward_test_log.csv live here)")
    ap.add_argument("--dir", default="xm_data", help="logger data directory (relative to --root)")
    ap.add_argument("--days", type=int, default=0, help="only the newest N UTC days of quote rows (0 = all)")
    ap.add_argument("--quiet", action="store_true", help="one advisory line; never fails")
    ap.add_argument("--now", type=float, default=None, help=argparse.SUPPRESS)   # tests
    a = ap.parse_args(argv)
    if a.quiet:
        try:
            print(quiet_line(a))
        except Exception as e:                      # advisory: must never break the autosync digest
            print("xm logger: report error (%s: %s)" % (type(e).__name__, e))
        return 0
    return report(a)


if __name__ == "__main__":
    sys.exit(main())
