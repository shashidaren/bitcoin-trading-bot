#!/usr/bin/env python3
"""
Data-integrity checker for the forward-test CSVs.

Run this FIRST on every new data drop, before drawing any conclusions:
a misaligned row or silent ledger reset poisons every statistic derived
from it (see gold docs/REVIEW-2026-09-09.md and REVIEW-2026-09-10.md).

Checks:
  trades.csv        header/schema (16-field, Trade_Type column), row widths,
                    Trade_Type/Exit_Reason domains, numbering, time order,
                    Balance_After ledger continuity, true P&L from $200
  forward_test_log  header, timestamp ordering, gaps > 15 min (M5 cadence)
  skipped_trades    header/row width
  cross-file        every trade entry exists in the price log (+-6 min),
                    no open trade spans a price-log gap,
                    status.json totals agree with trades.csv

Exit code 0 = clean (warnings allowed), 1 = FAIL-level problems found.
Read-only - no files are modified.

Usage: python3 tools/check_data.py [repo_root]
"""
import csv
import json
import os
import sys
from datetime import datetime

ROOT = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRADES = os.path.join(ROOT, "trades.csv")
LOG = os.path.join(ROOT, "forward_test_log.csv")
SKIPS = os.path.join(ROOT, "skipped_trades.csv")
STATUS = os.path.join(ROOT, "status.json")

STARTING_BALANCE = 200.00
GAP_SECONDS = 15 * 60   # M5 log: normal spacing is 5 min, flag > 15 min
ENTRY_MATCH_SECONDS = 6 * 60  # trade entry must have a log row within +-6 min

TRADES_FIELDS = [
    "Trade_Num", "Trade_Type", "Entry_Time", "Exit_Time", "Entry_Price", "Stop_Loss", "Take_Profit",
    "Exit_Price", "Exit_Reason", "Profit", "Balance_After", "RSI_At_Entry",
    "ATR_At_Entry", "Wick_Ratio_At_Entry", "EMA50_At_Entry", "EMA200_At_Entry",
]
LOG_FIELDS = ["Timestamp", "Open", "High", "Low", "Close", "Wick_Ratio", "Volume", "Vol_MA",
              "Vol_Confirmed", "Dynamic_Floor", "EMA_50", "EMA_200", "Trend_Confirmed",
              "Tested_Floor", "Valid_Rejection", "Held_Floor", "RSI", "ATR"]
SKIP_FIELDS = ["Timestamp", "Reason", "Price", "ATR"]

FAILS, WARNS = [], []


def fail(msg):
    FAILS.append(msg)
    print(f"  [FAIL] {msg}")


def warn(msg):
    WARNS.append(msg)
    print(f"  [WARN] {msg}")


def ok(msg):
    print(f"  [ ok ] {msg}")


def parse_dt(s):
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return None


def fnum(x):
    """Comma-tolerant float (legacy rows were written as '80,000.00')."""
    try:
        return float(str(x).replace(",", ""))
    except (TypeError, ValueError):
        return None


def check_trades():
    print("\n== trades.csv ==")
    with open(TRADES, newline="") as f:
        rdr = csv.reader(f)
        header = next(rdr, None)
        rows = [r for r in rdr if r]
    if header is None:
        fail("empty file")
        return []
    if [h.strip() for h in header] != TRADES_FIELDS:
        fail(f"header mismatch (pre-SELL 15-field schema? expected Trade_Type column). "
             f"Run the engine once to auto-migrate, or see engine.migrate_trades_csv(). "
             f"Got: {header}")
    else:
        ok(f"header matches the 16-field schema ({len(rows)} rows)")

    odd = [r for r in rows if len(r) != len(TRADES_FIELDS)]
    if odd:
        fail(f"{len(odd)} rows with wrong field count (e.g. trade #{odd[0][0]}) - "
             f"misaligned rows blind the risk gates")
    else:
        ok("all rows have 16 fields")

    trades = []
    nums, bad_reason, bad_side, bad_time = [], 0, 0, 0
    for r in rows:
        if len(r) != len(TRADES_FIELDS):
            continue
        d = dict(zip(TRADES_FIELDS, r))
        try:
            d["num"] = int(str(d["Trade_Num"]).replace(",", ""))
            d["profit"] = fnum(d["Profit"])
            d["bal"] = fnum(d["Balance_After"])
            d["entry_dt"] = parse_dt(d["Entry_Time"])
            d["exit_dt"] = parse_dt(d["Exit_Time"])
            if d["profit"] is None or d["bal"] is None:
                raise ValueError
        except ValueError:
            bad_reason += 1
            continue
        nums.append(d["num"])
        if d["Trade_Type"] not in ("BUY", "SELL"):
            bad_side += 1
        if d["Exit_Reason"] not in ("TP", "SL"):
            bad_reason += 1
        if not d["entry_dt"] or not d["exit_dt"] or d["entry_dt"] >= d["exit_dt"]:
            bad_time += 1
        trades.append(d)
    if bad_reason:
        fail(f"{bad_reason} rows with unparsable numbers or Exit_Reason not in TP/SL")
    else:
        ok("Exit_Reason domain + numeric fields all parse")
    if bad_side:
        fail(f"{bad_side} rows with Trade_Type not in BUY/SELL")
    if bad_time:
        fail(f"{bad_time} rows with Entry_Time >= Exit_Time")
    else:
        ok("entry/exit times ordered")

    dup = len(nums) - len(set(nums))
    if dup:
        warn(f"{dup} duplicate Trade_Num values (ledger-reset history: numbering "
             f"restarted - see engine.load_trade_stats)")
    else:
        ok("trade numbering unique")

    breaks = 0
    for prev, cur in zip(trades, trades[1:]):
        if abs(cur["bal"] - (prev["bal"] + cur["profit"])) > 0.02:
            breaks += 1
    if breaks:
        warn(f"{breaks} Balance_After continuity breaks (silent ledger resets)")
    else:
        ok("Balance_After ledger continuous")

    true_pnl = sum(t["profit"] for t in trades)
    wins = sum(1 for t in trades if t["Exit_Reason"] == "TP")
    losses = len(trades) - wins
    drift = trades[-1]["bal"] - (STARTING_BALANCE + true_pnl) if trades else 0
    print(f"  [info] {wins}W/{losses}L over {len(trades)} trades | true P&L from ${STARTING_BALANCE:.0f}: "
          f"{true_pnl:+.2f} -> ${STARTING_BALANCE + true_pnl:.2f} | engine ledger: ${trades[-1]['bal']:.2f} "
          f"(drift {drift:+.2f})")
    if abs(drift) > 0.02:
        warn("engine ledger disagrees with sum of profits (reset gap)")
    return trades


def check_log():
    print("\n== forward_test_log.csv ==")
    with open(LOG, newline="") as f:
        rdr = csv.reader(f)
        header = next(rdr, None)
        raw = [r for r in rdr if r]
    if [h.strip() for h in (header or [])] != LOG_FIELDS:
        fail(f"header mismatch: {header}")
    else:
        ok(f"header ok ({len(raw)} rows)")

    dts, badnum = [], 0
    for r in raw:
        dt = parse_dt(r[0]) if r else None
        if dt is None:
            badnum += 1
            continue
        dts.append(dt)
        try:
            float(str(r[1]).replace(",", "")); float(str(r[2]).replace(",", ""))
            float(str(r[3]).replace(",", "")); float(str(r[4]).replace(",", ""))
        except (ValueError, IndexError):
            badnum += 1
    if badnum:
        warn(f"{badnum} rows with unparsable timestamp/OHLC (skipped)")
    else:
        ok("timestamps + OHLC all parse")
    regress = sum(1 for a, b in zip(dts, dts[1:]) if b <= a)
    if regress:
        fail(f"{regress} timestamp regressions (log must be strictly increasing)")
    else:
        ok("timestamps strictly increasing")
    gaps = [(a, b) for a, b in zip(dts, dts[1:]) if (b - a).total_seconds() > GAP_SECONDS]
    if gaps:
        warn(f"{len(gaps)} gaps > 15 min: "
             + ", ".join(f"{a:%m-%d %H:%M}->{b:%H:%M} ({(b-a).total_seconds()/60:.0f}m)"
                         for a, b in gaps[:8])
             + (" ..." if len(gaps) > 8 else ""))
    else:
        ok("no gaps > 15 min")
    return dts


def check_skips():
    print("\n== skipped_trades.csv ==")
    with open(SKIPS, newline="") as f:
        rdr = csv.reader(f)
        header = next(rdr, None)
        rows = [r for r in rdr if r]
    if [h.strip() for h in (header or [])] != SKIP_FIELDS:
        fail(f"header mismatch: {header}")
    else:
        ok(f"header ok ({len(rows)} skip rows)")
    return rows


def check_cross(trades, log_dts):
    print("\n== cross-file ==")
    for t in trades:
        if not t.get("entry_dt"):
            continue
        near = [d for d in log_dts if abs((d - t["entry_dt"]).total_seconds()) <= ENTRY_MATCH_SECONDS]
        if not near:
            warn(f"trade #{t['num']} entry {t['entry_dt']} has no price-log row within 6 min")
    ok("trade entries matched to price log" if not any("no price-log row" in w for w in WARNS)
       else "see warnings above")

    # no open trade spans a >15 min price-log gap
    spans = 0
    for t in trades:
        if not t.get("entry_dt") or not t.get("exit_dt"):
            continue
        for a, b in zip(log_dts, log_dts[1:]):
            if (b - a).total_seconds() > GAP_SECONDS and t["entry_dt"] < a and t["exit_dt"] > b:
                spans += 1
    if spans:
        warn(f"{spans} trades were open across a price-log gap (exit prices may be unreliable)")
    else:
        ok("no trade open across a price-log gap")

    if os.path.isfile(STATUS):
        try:
            st = json.load(open(STATUS))
        except Exception as e:
            warn(f"status.json unparsable: {e}")
            return
        mism = []
        if trades and st.get("total_trades") not in (None, len(trades)):
            mism.append(f"total_trades {st.get('total_trades')} != {len(trades)}")
        if trades:
            w = sum(1 for t in trades if t["Exit_Reason"] == "TP")
            if st.get("wins") not in (None, w):
                mism.append(f"wins {st.get('wins')} != {w}")
            if st.get("equity") not in (None, trades[-1]["bal"]):
                mism.append(f"equity {st.get('equity')} != ledger {trades[-1]['bal']}")
        if mism:
            warn("status.json stale vs trades.csv (engine restart will resync): " + "; ".join(mism))
        else:
            ok("status.json agrees with trades.csv")


def main():
    print(f"bitcoin-trading-bot data integrity check - {ROOT}")
    for path in (TRADES, LOG, SKIPS):
        if not os.path.isfile(path):
            print(f"MISSING: {path}")
            sys.exit(1)
    trades = check_trades()
    log_dts = check_log()
    check_skips()
    check_cross(trades, log_dts)
    print(f"\n== result: {len(FAILS)} fail, {len(WARNS)} warn ==")
    if FAILS:
        print("Fix FAIL items before analysing this data.")
        sys.exit(1)
    print("Data is analysis-ready (warnings are informational).")
    sys.exit(0)


if __name__ == "__main__":
    main()
