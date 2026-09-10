#!/usr/bin/env python3
"""
Phantom-trade replay - what did the blocked signals actually do?

Every row in skipped_trades.csv is a FULL strategy signal (all engine gates
passed) that the risk layer (trade_filter.py) refused: cooldown, blackout,
daily-loss halt, or ATR bounds. Those skips have no trade record, so their
value/cost is invisible in trades.csv.

This tool reconstructs each blocked signal from forward_test_log.csv and
simulates the trade it WOULD have been (same ATR*2 SL / ATR*4 TP geometry
the engine uses, scaled by LOT_SIZE 0.01), then walks the log forward to see
whether it would have hit TP or SL. That turns the skip log into measurable
evidence: did the cooldowns/blackouts/halts save money or burn it?

Reconstruction details (must mirror engine.evaluate_candle exactly):
  - floor/ceiling: min/max of the PRIOR 20 bars (engine appends after eval)
  - trend: logged EMA_50 vs EMA_200 (both pre-update for the signal candle)
  - slope / near-EMA / RSI / ATR gates use POST-update indicator values:
      post_ema50[j]  = close[j]*k + EMA_50[j]*(1-k),  k = 2/51
      post_atr[j]    = mean(TR[j-13..j]),  TR = max(h-l, |h-pc|, |l-pc|)
      post_rsi[j]    = 100 - 100/(1+g/loss), g/loss = simple means of the
                       last 14 up/down close changes INCLUDING close[j]
  - pre-SELL era: signals were BUY-only with no slope/near-EMA gates. Both
    gate sets are tested; rows matching neither are "not reproducible".

Output is a per-skip table + summary by skip reason. P&L is in $ at 0.01 lot
(price distance x LOT_SIZE), raw distances without spread/slippage.

Usage: python3 tools/phantom_trades.py [--log LOG] [--skips SKIPS] [--since "YYYY-MM-DD HH:MM"]
Read-only - no files are modified.
"""
import argparse
import csv
import os
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

LOOKBACK = 20
FLOOR_BUFFER_PCT = 0.0015
K_FAST = 2 / (50 + 1)
WICK_TARGET = 0.15
RSI_MIN, RSI_MAX = 40.0, 70.0
MIN_ATR_PCT = 0.0001  # trade_filter MIN_ATR_PERCENT (engine MIN_ATR is 0.0)
LOT_SIZE = 0.01
SL_MULT, TP_MULT = 2.0, 4.0
MAX_HOLD_BARS = 288  # M5 bars (~24h)


def fnum(x):
    try:
        return float(str(x).replace(",", ""))
    except (TypeError, ValueError):
        return None


def load_log(path):
    rows = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            try:
                dt = datetime.strptime(r["Timestamp"], "%Y-%m-%d %H:%M:%S")
            except (KeyError, ValueError):
                continue
            rows.append({
                "dt": dt,
                "o": fnum(r["Open"]), "h": fnum(r["High"]),
                "l": fnum(r["Low"]), "c": fnum(r["Close"]),
                "floor": fnum(r["Dynamic_Floor"]),
                "ema50": fnum(r["EMA_50"]), "ema200": fnum(r["EMA_200"]),
                "atr": fnum(r["ATR"]), "rsi": fnum(r["RSI"]),
            })
    rows.sort(key=lambda x: x["dt"])
    return rows


def enrich(log):
    """Add reconstructed floor/ceiling and post-update EMA50/ATR/RSI per row,
    and validate the reconstruction against the logged pre-update values."""
    n = len(log)
    for i, row in enumerate(log):
        prior = log[max(0, i - LOOKBACK):i]
        if len(prior) == LOOKBACK:
            row["r_floor"] = min(x["l"] for x in prior)
            row["r_ceiling"] = max(x["h"] for x in prior)
        # post-update EMA50 (logged EMA_50 is pre-update for this row)
        if row["ema50"] is not None and row["c"] is not None:
            row["post_ema50"] = row["c"] * K_FAST + row["ema50"] * (1 - K_FAST)
        # true range + post/pre ATR (deque of 14, simple mean)
        if i > 0 and row["h"] is not None and row["l"] is not None and log[i - 1]["c"] is not None:
            pc = log[i - 1]["c"]
            row["tr"] = max(row["h"] - row["l"],
                            abs(row["h"] - pc), abs(row["l"] - pc))
            trs = [log[j]["tr"] for j in range(max(0, i - 13), i + 1) if "tr" in log[j]]
            if len(trs) == 14:
                row["post_atr"] = sum(trs) / 14
            trs_pre = [log[j]["tr"] for j in range(max(0, i - 14), i) if "tr" in log[j]]
            if len(trs_pre) == 14:
                row["pre_atr"] = sum(trs_pre) / 14
        # post/pre RSI (simple mean of last 14 close changes)
        if i >= 14:
            chgs = [log[j]["c"] - log[j - 1]["c"] for j in range(i - 13, i + 1)]
            g = sum(max(x, 0) for x in chgs) / 14
            d = sum(max(-x, 0) for x in chgs) / 14
            row["post_rsi"] = 100.0 if d == 0 else 100 - 100 / (1 + g / d)
            chgs_pre = [log[j]["c"] - log[j - 1]["c"] for j in range(i - 14, i)]
            g = sum(max(x, 0) for x in chgs_pre) / 14
            d = sum(max(-x, 0) for x in chgs_pre) / 14
            row["pre_rsi"] = 100.0 if d == 0 else 100 - 100 / (1 + g / d)

    # reconstruction quality: compare against logged pre-update values
    stats = {}
    for name, rec_key, log_key, tol in (
        ("floor", "r_floor", "floor", 0.5),
        ("ATR(pre)", "pre_atr", "atr", 0.5),
        ("RSI(pre)", "pre_rsi", "rsi", 0.2),
    ):
        ok = bad = 0
        for row in log:
            rec, lg = row.get(rec_key), row.get(log_key)
            if rec is None or lg is None:
                continue
            if abs(rec - lg) <= tol:
                ok += 1
            else:
                bad += 1
        stats[name] = (ok, bad)
    return stats


def signals_at(log, i):
    """Return (buy_old, buy_new, sell_new) full-signal flags for row i,
    mirroring engine.evaluate_candle gate order."""
    row = log[i]
    if any(row.get(k) is None for k in ("o", "h", "l", "c", "r_floor", "r_ceiling",
                                        "post_ema50", "post_atr", "post_rsi")):
        return False, False, False
    rng = row["h"] - row["l"]
    if rng <= 0:
        return False, False, False
    body_bot, body_top = min(row["o"], row["c"]), max(row["o"], row["c"])
    low_wick = (body_bot - row["l"]) / rng
    up_wick = (row["h"] - body_top) / rng

    tested_floor = row["l"] <= row["r_floor"] * (1 + FLOOR_BUFFER_PCT)
    held_support = row["c"] > row["r_floor"]
    tested_ceiling = row["h"] >= row["r_ceiling"] * (1 - FLOOR_BUFFER_PCT)
    held_resistance = row["c"] < row["r_ceiling"]
    rej_buy = low_wick >= WICK_TARGET
    rej_sell = up_wick >= WICK_TARGET
    trend_buy = row["ema50"] is not None and row["ema200"] is not None and row["ema50"] > row["ema200"]
    trend_sell = row["ema50"] is not None and row["ema200"] is not None and row["ema50"] < row["ema200"]

    rsi, atr = row["post_rsi"], row["post_atr"]
    rsi_buy = RSI_MIN < rsi < RSI_MAX
    rsi_sell = (100 - RSI_MAX) < rsi < (100 - RSI_MIN)
    atr_ok = row["c"] > 0 and (atr / row["c"]) > MIN_ATR_PCT

    slope_buy = slope_sell = near_buy = near_sell = None
    if i >= 30 and log[i - 30].get("post_ema50") is not None:
        slope_buy = row["post_ema50"] > log[i - 30]["post_ema50"]
        slope_sell = row["post_ema50"] < log[i - 30]["post_ema50"]
        near_buy = row["c"] >= row["post_ema50"] - 0.3 * atr
        near_sell = row["c"] <= row["post_ema50"] + 0.3 * atr

    base_buy = tested_floor and rej_buy and held_support and trend_buy and rsi_buy and atr_ok
    buy_old = base_buy
    buy_new = base_buy and slope_buy and near_buy
    sell_new = (tested_ceiling and rej_sell and held_resistance and trend_sell
                and rsi_sell and atr_ok and slope_sell and near_sell)
    return buy_old, buy_new, sell_new


def phantom(log, i, side):
    """Simulate the trade the engine would have taken at row i."""
    row = log[i]
    atr = row["post_atr"]
    e = row["c"]
    if side == "BUY":
        sl, tp = e - SL_MULT * atr, e + TP_MULT * atr
    else:
        sl, tp = e + SL_MULT * atr, e - TP_MULT * atr
    for j in range(i + 1, min(len(log), i + MAX_HOLD_BARS + 1)):
        r = log[j]
        if r["h"] is None:
            continue
        if side == "BUY":
            if r["l"] <= sl:            # SL-first on tie (conservative)
                return "SL", (sl - e) * LOT_SIZE, log[j]["dt"]
            if r["h"] >= tp:
                return "TP", (tp - e) * LOT_SIZE, log[j]["dt"]
        else:
            if r["h"] >= sl:
                return "SL", (e - sl) * LOT_SIZE, log[j]["dt"]
            if r["l"] <= tp:
                return "TP", (e - tp) * LOT_SIZE, log[j]["dt"]
    last = log[min(len(log) - 1, i + MAX_HOLD_BARS)]
    pnl = ((last["c"] - e) if side == "BUY" else (e - last["c"])) * LOT_SIZE
    return "OPEN/timeout", pnl, last["dt"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default=os.path.join(ROOT, "forward_test_log.csv"))
    ap.add_argument("--skips", default=os.path.join(ROOT, "skipped_trades.csv"))
    ap.add_argument("--since", default=None, help='only show skips >= "YYYY-MM-DD HH:MM"')
    args = ap.parse_args()

    log = load_log(args.log)
    stats = enrich(log)
    print("=== reconstruction quality vs logged values (pre-update) ===")
    for name, (ok, bad) in stats.items():
        pct = ok / (ok + bad) * 100 if (ok + bad) else 0
        print(f"  {name:<10} {ok}/{ok+bad} match ({pct:.1f}%)")

    stamps = [r["dt"] for r in log]
    import bisect
    since = datetime.strptime(args.since, "%Y-%m-%d %H:%M") if args.since else None

    skips = []
    with open(args.skips, newline="") as f:
        for r in csv.DictReader(f):
            try:
                dt = datetime.strptime(r["Timestamp"], "%Y-%m-%d %H:%M:%S")
            except (KeyError, ValueError):
                continue
            reason = r.get("Reason", "")
            kind = ("daily-halt" if reason.startswith("Daily Loss")
                    else "cooldown" if reason.startswith("SL Cooldown")
                    else "blackout" if reason.startswith("Blackout")
                    else "atr")
            skips.append({"dt": dt, "reason": reason, "kind": kind})

    print(f"\n=== blocked signals -> phantom outcome ({len(skips)} skips) ===")
    print(f"{'skip time':<17} {'kind':<11} {'side':<5} {'gates':<5} {'result':<12} {'pnl':>7}  reason")
    rows_out = []
    for s in skips:
        if since and s["dt"] < since:
            continue
        i = bisect.bisect_left(stamps, s["dt"])
        best = None
        for j in (i, i - 1, i + 1, i - 2):
            if 0 <= j < len(log) and abs((log[j]["dt"] - s["dt"]).total_seconds()) <= 360:
                best = j
                break
        if best is None:
            rows_out.append((s, None, "-", "-", "no log row", 0.0, None))
            continue
        buy_old, buy_new, sell_new = signals_at(log, best)
        if buy_old or buy_new:
            side, gates = "BUY", "new" if buy_new else "old"
        elif sell_new:
            side, gates = "SELL", "new"
        else:
            rows_out.append((s, log[best], "-", "-", "not reproducible", 0.0, None))
            continue
        res, pnl, exit_dt = phantom(log, best, side)
        rows_out.append((s, log[best], side, gates, res, pnl, exit_dt))

    for s, row, side, gates, res, pnl, _exit in rows_out:
        print(f"{s['dt'].strftime('%m-%d %H:%M:%S'):<17} {s['kind']:<11} {side:<5} {gates:<5} "
              f"{res:<12} {pnl:>+7.2f}  {s['reason'][:48]}")

    print("\n=== summary by skip kind (phantom P&L, $ at 0.01 lot) ===")
    from collections import defaultdict
    agg = defaultdict(lambda: [0, 0, 0, 0.0])  # n, wins, losses, pnl
    for s, row, side, gates, res, pnl, _exit in rows_out:
        a = agg[s["kind"]]
        a[0] += 1
        if res == "TP":
            a[1] += 1
        elif res == "SL":
            a[2] += 1
        a[3] += pnl
    grand = [0, 0, 0, 0.0]
    for kind in sorted(agg):
        n, w, l, p = agg[kind]
        print(f"  {kind:<11} {n:>3} blocked -> {w}W/{l}L/{n-w-l}open   phantom {p:+8.2f}")
        for x in range(4):
            grand[x] += (n, w, l, p)[x]
    print(f"  {'TOTAL':<11} {grand[0]:>3} blocked -> {grand[1]}W/{grand[2]}L/{grand[0]-grand[1]-grand[2]}open   phantom {grand[3]:+8.2f}")

    # ---- sequential view -------------------------------------------------
    # Consecutive skips minutes apart are usually the SAME setup re-firing:
    # had the first been taken, the engine would have been in_trade (and on
    # SL, in cooldown) for the rest. This view keeps only the phantoms the
    # engine could actually have taken one after another.
    print("\n=== sequential view (dedup: in-trade + 30m post-SL cooldown) ===")
    from datetime import timedelta
    busy_until = None
    consec_sl = 0
    seq = []
    for s, row, side, gates, res, pnl, _exit in rows_out:
        if side not in ("BUY", "SELL"):
            continue
        if busy_until is not None and s["dt"] < busy_until:
            continue
        seq.append((s, side, res, pnl))
        if res == "SL":
            consec_sl += 1
            busy_until = row["dt"] + timedelta(minutes=30 if consec_sl < 2 else 60)
        else:
            consec_sl = 0
            busy_until = row["dt"]
    agg2 = defaultdict(lambda: [0, 0, 0, 0.0])
    for s, side, res, pnl in seq:
        a = agg2[s["kind"]]
        a[0] += 1
        if res == "TP":
            a[1] += 1
        elif res == "SL":
            a[2] += 1
        a[3] += pnl
    g2 = [0, 0, 0, 0.0]
    for kind in sorted(agg2):
        n, w, l, p = agg2[kind]
        print(f"  {kind:<11} {n:>3} taken  -> {w}W/{l}L/{n-w-l}open   phantom {p:+8.2f}")
        for x in range(4):
            g2[x] += (n, w, l, p)[x]
    wr = g2[1] / g2[0] * 100 if g2[0] else 0
    print(f"  {'TOTAL':<11} {g2[0]:>3} taken  -> {g2[1]}W/{g2[2]}L/{g2[0]-g2[1]-g2[2]}open "
          f"({wr:.0f}% WR) phantom {g2[3]:+8.2f}")

    print("\nNote: raw ATR-geometry distances x 0.01 lot, no spread/slippage.")
    print("      'not reproducible' = signal fired under gates/params that no longer match the log.")
    print("      SL-first tie-break on candles that touch both levels (conservative).")
    print("      Sequential view ignores cascades (a taken phantom would have displaced")
    print("      later real trades) - treat it as an estimate, not a fact.")


if __name__ == "__main__":
    main()
