#!/usr/bin/env python3
"""
Shared replay core for the BTC analysis tools - ONE copy of every walk rule.

Why this module exists: gold's 2026-09-15 review found that its sequence-aware
replay had the bar extremes inverted for SELLs, so shorts "fell back to their
actual outcome" and the tool silently validated itself. Duplicated walk logic
in three tools is what allowed the bug to survive. New BTC tools must import
the walk from here instead of re-implementing it, and `tools/smoke_test.py`
Scenario I locks the SELL direction with a synthetic bar path.

Conventions (all BTC):
  - M5 bars, log rows are stamped at the bar's CLOSE (row T covers [T-5m, T)).
    A signal at row i enters at row i's close, so the walk starts at row i+1.
  - Geometry: SL = entry -/+ ATR_SL_MULT*ATR, TP = entry +/- ATR_TP_MULT*ATR
    (RR 1:2, breakeven decisive WR = 33.3%). Money = price distance * LOT_SIZE.
  - 1R in price units = ATR_SL_MULT*ATR; in dollars = 1R * LOT_SIZE.
  - Exit domain on BTC is {SL, TP}: no BE ratchet, no time stop. The walk
    supports a hypothetical BE trigger (RB) so the gold candidate can be
    measured on BTC data before anyone implements it.
  - Within one bar that touches both levels, the STOP is assumed first
    (conservative). The live engine resolves exits on ticks, so an M5 walk
    cannot reproduce it exactly - `validate_against_actual()` measures how far
    off it is, and every tool prints that number before its grids.

Read-only helpers: nothing in this module writes to disk.
"""
import csv
import math
from datetime import datetime, timedelta

# --- engine/trade_filter constants (keep in sync with engine.py) -------------
LOOKBACK_PERIOD = 20
FLOOR_BUFFER_PCT = 0.0015
WICK_RATIO_TARGET = 0.15
RSI_MIN, RSI_MAX = 40.0, 70.0
MAX_BELOW_EMA_ATR = 0.30
EMA_SLOPE_LOOKBACK = 30
ATR_SL_MULT = 2.0
ATR_TP_MULT = 4.0
LOT_SIZE = 0.01
CANDLE_SECONDS = 300
MIN_ATR_PERCENT = 0.0001      # trade_filter.MIN_ATR_PERCENT
MAX_ATR_PERCENT = 0.0060      # trade_filter.MAX_ATR_PERCENT
SL_COOLDOWN_BASE_MINUTES = 30
SL_COOLDOWN_ESCALATED_MINUTES = 60
MAX_DAILY_LOSSES = 3

# The port that installed the regime gates / SELL funnel (first post-port trade).
# Era slices ("new regime") start here so that historical numbers stay
# comparable with every review already written.
PORT_DEPLOY = datetime(2026, 9, 9, 2, 25)

# When those gates were ACTUALLY taking trades - use this, not PORT_DEPLOY, for
# anything that re-applies an entry gate to ledger rows. Evidence that the gated
# code went live a day after PORT_DEPLOY: the ledger's first SELL is 09-10 09:05
# (the SELL funnel arrived with the port), and two of the four 09-09 BUY rows sit
# on the adverse side of the near-EMA gate (0.57 and 3.11 ATR) that would have
# blocked them. tools/check_data.py's entry-gate conformance block polices the
# boundary and carries a copy of this date (keep the two in sync).
GATES_DEPLOY = datetime(2026, 9, 10, 0, 0)

# The ledger's second geometry change: rows before this ran SL 1.5xATR / TP
# 2.5xATR (RR 1:1.67) with candle-era fills that overshoot the logged stop; rows
# from here ran the live 2x/4x rule. The two 09-03 rows coincidentally show
# 1.5/2.5 multiples because their lot size was 100x too large.
GEOM2_DEPLOY = datetime(2026, 9, 6, 17, 49)

TS_FMT = "%Y-%m-%d %H:%M:%S"


def wilson(w, n, z=1.96):
    """95% CI on a proportion. n must be the DECISIVE count (no scratches here)."""
    if n <= 0:
        return 0.0, 0.0
    p = w / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (centre - half) / denom * 100), min(100.0, (centre + half) / denom * 100)


def fnum(x):
    """Comma-tolerant float (58 of the first 61 ledger rows are comma-grouped)."""
    try:
        return float(str(x).replace(",", "").replace("%", ""))
    except (TypeError, ValueError):
        return None


def r_money(atr, sl_mult=ATR_SL_MULT, lot=LOT_SIZE):
    """Dollar value of 1R for a trade with this ATR at this lot size."""
    return sl_mult * atr * lot


def planned_rr(t):
    """Reward:risk the row was opened with, from its own logged SL/TP levels.

    The ledger is NOT single-geometry: every row logged before 2026-09-06 17:49
    UTC ran SL 1.5xATR / TP 2.5xATR (RR 1:1.67), the 2x/4x geometry starts with
    row 09-06 17:49. Never assume 2R per win across a mixed sample.
    """
    d = 1 if t["side"] == "BUY" else -1
    risk = d * (t["entry"] - t["sl"])
    reward = d * (t["tp"] - t["entry"])
    return reward / risk if risk else None


def geometry(t):
    """(SL multiple, TP multiple) in ATR units, as logged on the row."""
    if not t.get("atr"):
        return None
    return (round(abs(t["entry"] - t["sl"]) / t["atr"], 2),
            round(abs(t["tp"] - t["entry"]) / t["atr"], 2))


def realized_r(t):
    """What the row actually did, in R, at LOT_SIZE - the honest per-trade unit."""
    risk = abs(t["entry"] - t["sl"])
    if risk <= 0 or t.get("profit") is None:
        return None
    return t["profit"] / (risk * LOT_SIZE)


def parse_ts(s):
    try:
        return datetime.strptime(str(s).strip(), TS_FMT)
    except (TypeError, ValueError):
        return None


def load_trades(path, since=None):
    """Ledger rows -> dicts with direction-aware geometry.

    Defensive ratchet handling: if |Entry_Price - Stop_Loss| ~ 0 the row logs a
    stop that was moved to entry (gold's BE ratchet). BTC has no BE yet, so this
    only matters if one is ever adopted - but every R-multiple would divide by
    zero then, and `Exit_Reason` is not a reliable marker (gold's engine logs the
    LIVE stop, so armed winners look like scratches too). Key on geometry.
    """
    out = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            side = (r.get("Trade_Type") or "").strip().upper()
            if side not in ("BUY", "SELL"):
                continue
            et, xt = parse_ts(r.get("Entry_Time")), parse_ts(r.get("Exit_Time"))
            entry, sl, tp = fnum(r.get("Entry_Price")), fnum(r.get("Stop_Loss")), fnum(r.get("Take_Profit"))
            atr = fnum(r.get("ATR_At_Entry"))
            if None in (et, xt, entry, sl, tp, atr):
                continue
            ratcheted = abs(entry - sl) < 1e-9
            if ratcheted:  # rebuild the original geometry from ATR
                d = 1 if side == "BUY" else -1
                sl, tp = entry - d * ATR_SL_MULT * atr, entry + d * ATR_TP_MULT * atr
            out.append(dict(
                num=r.get("Trade_Num"), side=side, et=et, xt=xt,
                entry=entry, sl=sl, tp=tp, atr=atr, ratcheted=ratcheted,
                reason=(r.get("Exit_Reason") or "").strip().upper(),
                exit_price=fnum(r.get("Exit_Price")), profit=fnum(r.get("Profit")),
                rsi=fnum(r.get("RSI_At_Entry")), wick=fnum(r.get("Wick_Ratio_At_Entry")),
                ema50=fnum(r.get("EMA50_At_Entry")), ema200=fnum(r.get("EMA200_At_Entry")),
            ))
    out.sort(key=lambda t: t["et"])
    if since:
        out = [t for t in out if t["et"] >= since]
    return out


def load_bars(path, with_indicators=False):
    """Price-log rows -> [{dt,o,h,l,c}] sorted by timestamp.

    with_indicators=True also loads the logged (pre-update) indicator columns
    needed by enrich_log()/signal_at() for the signal census.
    """
    bars = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            dt = parse_ts(r.get("Timestamp"))
            o, h, l, c = (fnum(r.get(k)) for k in ("Open", "High", "Low", "Close"))
            if dt is None or None in (o, h, l, c):
                continue
            bar = dict(dt=dt, o=o, h=h, l=l, c=c)
            if with_indicators:
                bar.update(ema50=fnum(r.get("EMA_50")), ema200=fnum(r.get("EMA_200")),
                           floor=fnum(r.get("Dynamic_Floor")), rsi=fnum(r.get("RSI")),
                           atr=fnum(r.get("ATR")))
            bars.append(bar)
    bars.sort(key=lambda b: b["dt"])
    return bars


def enrich_log(rows):
    """Reconstruct post-update EMA50/ATR/RSI + floor/ceiling per log row.

    The logged EMA_50/ATR/RSI are PRE-update for that row; the engine gates on
    the post-update values, so signals cannot be re-derived without this step.
    Returns the reconstruction-quality stats (should be ~100% - if it is not,
    every signal-census number in the reports is suspect).
    """
    n = len(rows)
    for i, row in enumerate(rows):
        prior = rows[max(0, i - LOOKBACK_PERIOD):i]
        if len(prior) == LOOKBACK_PERIOD:
            row["r_floor"] = min(x["l"] for x in prior)
            row["r_ceiling"] = max(x["h"] for x in prior)
        if row["ema50"] is not None and row["c"] is not None:
            k = 2 / (50 + 1)
            row["post_ema50"] = row["c"] * k + row["ema50"] * (1 - k)
        if i > 0 and None not in (row["h"], row["l"], rows[i - 1]["c"]):
            pc = rows[i - 1]["c"]
            row["tr"] = max(row["h"] - row["l"], abs(row["h"] - pc), abs(row["l"] - pc))
            trs = [rows[j]["tr"] for j in range(max(0, i - 13), i + 1) if "tr" in rows[j]]
            if len(trs) == 14:
                row["post_atr"] = sum(trs) / 14
            trs_pre = [rows[j]["tr"] for j in range(max(0, i - 14), i) if "tr" in rows[j]]
            if len(trs_pre) == 14:
                row["pre_atr"] = sum(trs_pre) / 14
        if i >= 14:
            chgs = [rows[j]["c"] - rows[j - 1]["c"] for j in range(i - 13, i + 1)]
            g = sum(max(x, 0) for x in chgs) / 14
            d = sum(max(-x, 0) for x in chgs) / 14
            row["post_rsi"] = 100.0 if d == 0 else 100 - 100 / (1 + g / d)
            chgs_pre = [rows[j]["c"] - rows[j - 1]["c"] for j in range(i - 14, i)]
            g = sum(max(x, 0) for x in chgs_pre) / 14
            d = sum(max(-x, 0) for x in chgs_pre) / 14
            row["pre_rsi"] = 100.0 if d == 0 else 100 - 100 / (1 + g / d)

    stats = {}
    for name, rec_key, log_key, tol in (("floor", "r_floor", "floor", 0.5),
                                        ("ATR(pre)", "pre_atr", "atr", 0.5),
                                        ("RSI(pre)", "pre_rsi", "rsi", 0.2)):
        ok = bad = 0
        for row in rows:
            rec, lg = row.get(rec_key), row.get(log_key)
            if rec is None or lg is None:
                continue
            ok += abs(rec - lg) <= tol
            bad += abs(rec - lg) > tol
        stats[name] = (ok, bad)
    return stats


def signal_at(rows, i):
    """Full-signal flags (buy, sell) for log row i under the CURRENT gate stack.

    Mirrors engine.evaluate_candle: floor/ceiling from the prior 20 bars,
    pre-update trend columns from the row itself, post-update slope/near-EMA/
    RSI/ATR gates, and trade_filter's %-based ATR floor.
    """
    row = rows[i]
    if any(row.get(k) is None for k in ("o", "h", "l", "c", "r_floor", "r_ceiling",
                                        "post_ema50", "post_atr", "post_rsi")):
        return False, False
    rng = row["h"] - row["l"]
    if rng <= 0:
        return False, False
    body_bot, body_top = min(row["o"], row["c"]), max(row["o"], row["c"])
    low_wick = (body_bot - row["l"]) / rng
    up_wick = (row["h"] - body_top) / rng

    rsi, atr = row["post_rsi"], row["post_atr"]
    atr_ok = atr / row["c"] > MIN_ATR_PERCENT if row["c"] else False
    trend_buy = None not in (row["ema50"], row["ema200"]) and row["ema50"] > row["ema200"]
    trend_sell = None not in (row["ema50"], row["ema200"]) and row["ema50"] < row["ema200"]
    slope_buy = slope_sell = near_buy = near_sell = False
    if i >= EMA_SLOPE_LOOKBACK and rows[i - EMA_SLOPE_LOOKBACK].get("post_ema50") is not None:
        slope_buy = row["post_ema50"] > rows[i - EMA_SLOPE_LOOKBACK]["post_ema50"]
        slope_sell = row["post_ema50"] < rows[i - EMA_SLOPE_LOOKBACK]["post_ema50"]
        near_buy = row["c"] >= row["post_ema50"] - MAX_BELOW_EMA_ATR * atr
        near_sell = row["c"] <= row["post_ema50"] + MAX_BELOW_EMA_ATR * atr

    buy = (row["l"] <= row["r_floor"] * (1 + FLOOR_BUFFER_PCT) and low_wick >= WICK_RATIO_TARGET
           and row["c"] > row["r_floor"] and trend_buy and slope_buy and near_buy
           and RSI_MIN < rsi < RSI_MAX and atr_ok)
    sell = (row["h"] >= row["r_ceiling"] * (1 - FLOOR_BUFFER_PCT) and up_wick >= WICK_RATIO_TARGET
            and row["c"] < row["r_ceiling"] and trend_sell and slope_sell and near_sell
            and (100 - RSI_MAX) < rsi < (100 - RSI_MIN) and atr_ok)
    return buy, sell


def all_signals(rows, include_pre_port=False):
    """Every full signal in the price log (cascade-ignorant: one per row, max).

    Returns dicts with i (row index), dt, side, atr, entry, rsi, wick.
    """
    out = []
    for i in range(len(rows)):
        if not include_pre_port and rows[i]["dt"] < PORT_DEPLOY:
            continue
        buy, sell = signal_at(rows, i)
        for side, ok in (("BUY", buy), ("SELL", sell)):
            if not ok:
                continue
            row = rows[i]
            rng = row["h"] - row["l"]
            body_bot, body_top = min(row["o"], row["c"]), max(row["o"], row["c"])
            wick = (body_bot - row["l"]) / rng if side == "BUY" else (row["h"] - body_top) / rng
            out.append(dict(i=i, dt=row["dt"], side=side, atr=row["post_atr"],
                            entry=row["c"], rsi=row["post_rsi"], wick=wick,
                            sl_dist=ATR_SL_MULT * row["post_atr"]))
    return out


def walk(entry, side, atr, bars, sl_mult=ATR_SL_MULT, tp_mult=ATR_TP_MULT,
         be_trigger=None, horizon_min=None, start_dt=None):
    """Walk one trade bar-by-bar under a hypothetical exit rule.

    Direction-aware excursions (the gold 09-15 SELL fix): a bar's MOST FAVOURABLE
    move is max(high-entry, low-entry) for a BUY and the same expression is
    correct for a SELL only because of the sign flip inside max() - so use
    hi = max(d*(h-e), d*(l-e)) and lo = min(d*(h-e), d*(l-e)) with d = +-1,
    never `d*(h-e)` alone (that is the favourable side for BUYs only).

    Returns (outcome, r_multiple, bars_held, exit_dt) with outcome in
    {TP, SL, BE, TIME}:
      - TP/SL: level touched (SL first when one bar spans both - conservative);
      - BE:    hypothetical breakeven ratchet armed at +be_trigger R and the
               price came back to entry;
      - TIME:  horizon ended flat -> marked to market at the last close.
    `be_trigger=None` => no ratchet. `horizon_min=None` => walk to the last bar.
    """
    d = 1 if side.upper() == "BUY" else -1
    risk = sl_mult * atr
    if risk <= 0:
        return "TIME", 0.0, 0, start_dt
    tp_r = tp_mult * atr / risk
    stop_r = -1.0                      # in R units; 0.0 once the ratchet arms
    armed = False
    # horizon is measured from start_dt when given, else from the first bar
    anchor = start_dt if start_dt is not None else (bars[0]["dt"] if bars else None)
    end = (anchor + timedelta(minutes=horizon_min)) if (horizon_min is not None and anchor) else None
    held = 0
    last_close = entry
    for b in bars:
        if start_dt is not None and b["dt"] <= start_dt:
            continue
        if end is not None and b["dt"] > end:
            break
        held += 1
        last_close = b["c"]
        hi_r = max(d * (b["h"] - entry), d * (b["l"] - entry)) / risk
        lo_r = min(d * (b["h"] - entry), d * (b["l"] - entry)) / risk
        # ratchet arms on the favourable excursion, then the stop sits at entry
        if be_trigger is not None and not armed and hi_r >= be_trigger - 1e-9:
            armed = True
            stop_r = 0.0
        if lo_r <= stop_r - 1e-9:
            return ("BE" if armed else "SL"), stop_r, held, b["dt"]
        if hi_r >= tp_r - 1e-9:
            return "TP", tp_r, held, b["dt"]
    if held == 0:
        return "TIME", 0.0, 0, start_dt
    return "TIME", d * (last_close - entry) / risk, held, bars[-1]["dt"] if end is None else end


def walk_trade(t, bars, **kw):
    """Walk a ledger trade with the LIVE geometry (logged SL/TP levels).

    The logged levels are used for the baseline row of any grid so it can be
    compared against what the engine actually did.
    """
    d = 1 if t["side"] == "BUY" else -1
    risk = abs(t["entry"] - t["sl"])
    seg = [b for b in bars if b["dt"] > t["et"]]
    if kw.get("horizon_min") is not None:
        seg = [b for b in seg if b["dt"] <= t["et"] + timedelta(minutes=kw["horizon_min"])]
    return walk(t["entry"], t["side"], risk / ATR_SL_MULT, seg,
                sl_mult=ATR_SL_MULT, tp_mult=ATR_TP_MULT, **kw)


def cascade(items, bars, sl_mult=ATR_SL_MULT, tp_mult=ATR_TP_MULT, be_trigger=None,
            horizon_min=240, cooldown_min=SL_COOLDOWN_BASE_MINUTES,
            escalated_min=SL_COOLDOWN_ESCALATED_MINUTES, daily_halt=None):
    """Sequence-aware replay: the simulated book can only hold one trade.

    An item is taken only if the simulated book is free and the SL cooldown
    (30 min, escalating to 60 after 2 consecutive simulated SLs) has elapsed.
    Without this, a looser exit looks better than it is: held positions block
    the later signals that the live book actually kept trading.

    `items` must be dicts with dt/side/atr/entry (signals) or trades (walk_trade
    style: et/side/atr/entry). Returns (taken, skipped, results) where results
    carry outcome/r/exit_dt/entry_dt.
    """
    taken, skipped, results = 0, 0, []
    busy_until = None
    streak = 0
    day_sls = {}
    for it in sorted(items, key=lambda x: x.get("dt") or x["et"]):
        dt = it.get("dt") or it["et"]
        if daily_halt:
            key = dt.date()
            if day_sls.get(key, 0) >= daily_halt:
                skipped += 1
                continue
        if busy_until is not None:
            cd = escalated_min if streak >= 2 else (cooldown_min if streak else 0)
            if dt < busy_until + timedelta(minutes=cd):
                skipped += 1
                continue
        seg = [b for b in bars if b["dt"] > dt]
        out, r, held, exit_dt = walk(it["entry"], it["side"], it["atr"], seg,
                                     sl_mult=sl_mult, tp_mult=tp_mult,
                                     be_trigger=be_trigger, horizon_min=horizon_min,
                                     start_dt=dt)
        taken += 1
        results.append(dict(outcome=out, r=r, entry_dt=dt, exit_dt=exit_dt,
                            side=it["side"], atr=it["atr"], entry=it["entry"], held_bars=held))
        if out == "SL":
            streak += 1
            day_sls[dt.date()] = day_sls.get(dt.date(), 0) + 1
        elif out == "TP":
            streak = 0
        busy_until = exit_dt or dt
    return taken, skipped, results


def summarize(results, atr_key="atr"):
    """(W, L, BE, TIME, pnl$, sum_r) for a list of cascade/walk results."""
    w = l = be = tm = 0
    pnl = 0.0
    rtot = 0.0
    for r in results:
        money = r_money(r[atr_key])
        pnl += r["r"] * money
        rtot += r["r"]
        if r["outcome"] == "TP":
            w += 1
        elif r["outcome"] == "SL":
            l += 1
        elif r["outcome"] == "BE":
            be += 1
        else:
            tm += 1
    return w, l, be, tm, pnl, rtot


def coverage(trades, bars):
    """Split trades into log-covered / not, by 'is there a bar at/after entry'."""
    if not bars:
        return [], trades
    first = bars[0]["dt"]
    covered = [t for t in trades if t["et"] >= first]
    return covered, [t for t in trades if t["et"] < first]
