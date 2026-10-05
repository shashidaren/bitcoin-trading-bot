#!/usr/bin/env python3
"""One-off reconciler for a STALE simulated trade (recreated; cf. local commit ba6d0bf).

Why this exists
---------------
docs/REVIEW-2026-10-05.md documents simulated BUY #125 as an open trade whose
saved stop was already breached on the M5 path, and it explicitly warns:

    "Do not hand-edit status.json or append a guessed close to trades.csv ...
     reconcile from ordered price/tick history rather than guessing."

Some later run force-closed #125 as a *guessed* TP at the take-profit level with
a wall-clock Exit_Time (e.g. 2026-10-05 03:50:10). That is exactly the guessed
fill the review forbids. This tool re-derives the true exit from the ordered
closed-candle OHLC path in forward_test_log.csv, under the SAME conservative
convention the MT5 forward-test fix uses (PR #14 / commit 0ea8d67), and rewrites
the ledger row + status.json to match.

Conservative closed-candle OHLC convention (mirrors engine.check_position_on_closed_candle)
-------------------------------------------------------------------------------------------
  - BUY : stop if low  <= stop ; target if high >= target
  - SELL: stop if high >= stop ; target if low  <= target
  - both barriers inside one candle  -> STOP wins (checked first)
  - a stop gap fills at the candle OPEN only if the open is already through the
    stop; otherwise it fills at the stop level
  - a target touch fills at the target level (no credit for favourable overshoot)
  - the entry candle's earlier OHLC range is NOT applied to the trade opened at
    that candle's close (the walk starts on the NEXT candle)

Safety model
------------
  - report-only by default: it computes and prints, writes NOTHING
  - opt-in --apply: writes changes
  - --apply ALWAYS backs up trades.csv and status.json first (into backups/)
  - --apply refuses if the exit cannot be derived from the logged path (it will
    never fabricate a fill)

Usage
-----
  python3 tools/reconcile_stale_trade.py                 # report-only, trade #125
  python3 tools/reconcile_stale_trade.py --trade-num 125 # report-only, explicit
  python3 tools/reconcile_stale_trade.py --apply         # reconcile + write (backs up first)
"""
import argparse
import csv
import io
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def read_lot_size():
    """Read LOT_SIZE straight from engine.py so the reconciler cannot drift from
    the engine's own PnL scaling. Falls back to 0.01 if engine.py is unreadable."""
    try:
        txt = open(os.path.join(ROOT, "engine.py"), encoding="utf-8").read()
        m = re.search(r"^LOT_SIZE\s*=\s*([0-9]*\.?[0-9]+)", txt, re.M)
        if m:
            return float(m.group(1))
    except Exception:
        pass
    return 0.01


LOT_SIZE = read_lot_size()


def fnum(x):
    if x is None:
        return None
    try:
        return float(str(x).replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def parse_dt(s):
    s = (s or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(s[:19], fmt)
        except ValueError:
            continue
    return None


def barrier_hit(trade_type, o, h, l, c, sl, tp):
    """(reason, exit_price) for the FIRST barrier this candle proves, else None.

    Mirrors engine.check_position_on_closed_candle: the stop is evaluated before
    the target, so a tie-bar resolves conservatively to the stop.
    """
    if trade_type == "BUY":
        if l <= sl:                                   # stop first (conservative)
            return ("SL", o if o <= sl else sl)       # gap-through fills at open
        if h >= tp:
            return ("TP", tp)                          # target fills at the target
    elif trade_type == "SELL":
        if h >= sl:
            return ("SL", o if o >= sl else sl)
        if l <= tp:
            return ("TP", tp)
    return None


def load_log(path):
    rows = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            dt = parse_dt(r.get("Timestamp"))
            o, h, l, c = fnum(r.get("Open")), fnum(r.get("High")), fnum(r.get("Low")), fnum(r.get("Close"))
            if dt is None or None in (o, h, l, c):
                continue
            rows.append({"ts": (r.get("Timestamp") or "").strip(), "dt": dt, "o": o, "h": h, "l": l, "c": c})
    return rows


def find_entry_index(log_rows, entry_dt):
    for i, r in enumerate(log_rows):
        if r["dt"] == entry_dt:
            return i, None
    best = None
    for i, r in enumerate(log_rows):
        d = abs((r["dt"] - entry_dt).total_seconds())
        if d <= 360 and (best is None or d < best[1]):
            best = (i, d)
    if best:
        return best[0], f"entry matched by nearest bar (+{best[1]:.0f}s); exact stamp absent from log"
    return None, "entry candle not found in price log"


def reconcile(trade, log_rows):
    """Walk candles AFTER the entry candle and return the derived exit (or why it can't)."""
    ttype = (trade.get("Trade_Type") or "").strip().upper()
    entry_dt = parse_dt(trade.get("Entry_Time"))
    entry, sl, tp = fnum(trade.get("Entry_Price")), fnum(trade.get("Stop_Loss")), fnum(trade.get("Take_Profit"))
    if ttype not in ("BUY", "SELL") or entry_dt is None or None in (entry, sl, tp):
        return {"ok": False, "error": "trade row missing/invalid type, times or barriers"}
    idx, note = find_entry_index(log_rows, entry_dt)
    if idx is None:
        return {"ok": False, "error": note or "entry candle not found in price log"}
    entry_candle = log_rows[idx]
    walk = []
    for r in log_rows[idx + 1:]:
        hit = barrier_hit(ttype, r["o"], r["h"], r["l"], r["c"], sl, tp)
        walk.append((r, hit))
        if hit:
            reason, price = hit
            return {"ok": True, "ttype": ttype, "entry": entry, "sl": sl, "tp": tp,
                    "entry_index": idx, "entry_candle": entry_candle, "walk": walk, "note": note,
                    "exit_time": r["ts"], "reason": reason, "exit_price": price, "exit_candle": r}
    return {"ok": False, "ttype": ttype, "entry": entry, "sl": sl, "tp": tp,
            "entry_index": idx, "entry_candle": entry_candle, "walk": walk, "note": note,
            "error": "no barrier touched anywhere in the logged path after entry - refusing to fabricate a fill"}


def compute_money(ttype, entry, exit_price, prev_bal):
    """profit and balance_after exactly as the engine would accumulate them
    (unrounded profit added to the running balance, then formatted to 2dp)."""
    if ttype == "BUY":
        profit = (exit_price - entry) * LOT_SIZE
    else:
        profit = (entry - exit_price) * LOT_SIZE
    base = prev_bal if prev_bal is not None else 0.0
    balance = base + profit
    return profit, balance


def load_trades(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def recompute_status(trades_rows):
    """Reproduce engine.load_trade_stats() accounting from the (reconciled) ledger."""
    wins = sum(1 for r in trades_rows if (r.get("Exit_Reason") or "").strip().upper() == "TP")
    losses = sum(1 for r in trades_rows if (r.get("Exit_Reason") or "").strip().upper() == "SL")
    total = wins + losses
    win_rate = round(wins / total * 100, 1) if total else 0.0
    max_num, last_bal = 0, None
    for r in trades_rows:
        n = int(fnum(r.get("Trade_Num")) or 0)
        if n > max_num:
            max_num = n
        b = fnum(r.get("Balance_After"))
        if b is not None and b > 0:
            last_bal = b
    return {
        "wins": wins, "losses": losses, "total_trades": total, "win_rate": win_rate,
        "next_trade_num": max_num + 1,
        "equity": round(last_bal, 2) if last_bal is not None else None,
    }


def rewrite_trades_row(path, num, entry_time, new_fields):
    """Replace exactly one raw CSV line (matched on Trade_Num + Entry_Time) while
    preserving every other byte, including CRLF endings and legacy quoting."""
    with open(path, "rb") as f:
        raw = f.read()
    lines = raw.split(b"\n")
    replaced = 0
    for i, ln in enumerate(lines):
        s = ln.rstrip(b"\r")
        if not s.strip():
            continue
        try:
            fields = next(csv.reader([s.decode("utf-8")]))
        except Exception:
            continue
        if len(fields) >= 3 and fields[0] == str(num) and fields[2] == entry_time:
            buf = io.StringIO()
            csv.writer(buf, lineterminator="").writerow(new_fields)
            cr = b"\r" if ln.endswith(b"\r") else b""
            lines[i] = buf.getvalue().encode("utf-8") + cr
            replaced += 1
    if replaced != 1:
        raise SystemExit(f"ABORT: expected exactly 1 row for #{num} @ {entry_time}, found {replaced}")
    with open(path, "wb") as f:
        f.write(b"\n".join(lines))


def backup(paths, dest_dir):
    os.makedirs(dest_dir, exist_ok=True)
    made = []
    for p in paths:
        if os.path.isfile(p):
            shutil.copy2(p, os.path.join(dest_dir, os.path.basename(p)))
            made.append(os.path.join(dest_dir, os.path.basename(p)))
    return made


def main():
    ap = argparse.ArgumentParser(description="Reconcile one stale simulated trade from the OHLC path (report-only unless --apply).")
    ap.add_argument("--trade-num", type=int, default=125, help="Trade_Num to reconcile (default 125)")
    ap.add_argument("--apply", action="store_true", help="Write the reconciliation (backs up first). Omit for report-only.")
    ap.add_argument("--root", default=ROOT, help="Repo root (default: this checkout)")
    ap.add_argument("--trades", default=None, help="Override trades.csv path")
    ap.add_argument("--log", default=None, help="Override forward_test_log.csv path")
    ap.add_argument("--status", default=None, help="Override status.json path")
    args = ap.parse_args()

    trades_path = args.trades or os.path.join(args.root, "trades.csv")
    log_path = args.log or os.path.join(args.root, "forward_test_log.csv")
    status_path = args.status or os.path.join(args.root, "status.json")

    trades = load_trades(trades_path)
    log_rows = load_log(log_path)

    # locate the target row (Trade_Num + Entry_Time disambiguates the legacy dup/gap numbering)
    tgt = None
    tgt_i = None
    for i, r in enumerate(trades):
        if int(fnum(r.get("Trade_Num")) or -1) == args.trade_num:
            tgt, tgt_i = r, i
            break
    if tgt is None:
        raise SystemExit(f"trade #{args.trade_num} not found in {trades_path}")

    prev_bal = fnum(trades[tgt_i - 1].get("Balance_After")) if tgt_i > 0 else None
    entry_time = (tgt.get("Entry_Time") or "").strip()

    rec = reconcile(tgt, log_rows)

    print("=" * 78)
    print(f"STALE-TRADE RECONCILER  |  trade #{args.trade_num}  |  LOT_SIZE={LOT_SIZE}")
    print(f"  trades: {trades_path}")
    print(f"  log   : {log_path}")
    print(f"  mode  : {'APPLY (will write, backup first)' if args.apply else 'REPORT-ONLY (no writes)'}")
    print("=" * 78)

    print("\nRecorded ledger row (current):")
    print(f"  #{tgt.get('Trade_Num')} {tgt.get('Trade_Type')} entry {entry_time} @ {tgt.get('Entry_Price')}")
    print(f"    SL={tgt.get('Stop_Loss')}  TP={tgt.get('Take_Profit')}")
    print(f"    Exit_Time   = {tgt.get('Exit_Time')}")
    print(f"    Exit_Reason = {tgt.get('Exit_Reason')}")
    print(f"    Exit_Price  = {tgt.get('Exit_Price')}")
    print(f"    Profit      = {tgt.get('Profit')}")
    print(f"    Balance_After = {tgt.get('Balance_After')}")

    if not rec["ok"]:
        print(f"\nCANNOT RECONCILE: {rec['error']}")
        print("Refusing to write a guessed fill. Investigate the price path first.")
        return 2

    profit, balance = compute_money(rec["ttype"], rec["entry"], rec["exit_price"], prev_bal)
    profit_str = f"{profit:.2f}"
    balance_str = f"{balance:.2f}"
    exit_price_str = f"{rec['exit_price']:.2f}"

    print("\nEntry candle (its earlier range is NOT applied to the trade):")
    ec = rec["entry_candle"]
    print(f"  {ec['ts']}  O={ec['o']:.2f} H={ec['h']:.2f} L={ec['l']:.2f} C={ec['c']:.2f}   (entry at close)")
    if rec.get("note"):
        print(f"  note: {rec['note']}")

    print("\nWalk forward (candles after entry, until the first proven barrier):")
    for r, hit in rec["walk"]:
        if hit:
            reason, price = hit
            print(f"  {r['ts']}  O={r['o']:.2f} H={r['h']:.2f} L={r['l']:.2f} C={r['c']:.2f}  ->  {reason} @ {price:.2f}  <== EXIT")
        else:
            print(f"  {r['ts']}  O={r['o']:.2f} H={r['h']:.2f} L={r['l']:.2f} C={r['c']:.2f}  ->  no barrier")

    print("\nReconciled exit (conservative OHLC convention):")
    print(f"  Exit_Time   = {rec['exit_time']}")
    print(f"  Exit_Reason = {rec['reason']}")
    print(f"  Exit_Price  = {exit_price_str}")
    print(f"  Profit      = {profit_str}")
    print(f"  Balance_After = {balance_str}   (prev {prev_bal} + {profit:+.4f})")

    changed = (str(tgt.get("Exit_Reason")) != rec["reason"]
               or str(tgt.get("Exit_Price")) != exit_price_str
               or str(tgt.get("Profit")) != profit_str
               or str(tgt.get("Balance_After")) != balance_str
               or str(tgt.get("Exit_Time")) != rec["exit_time"])
    print("\n  => " + ("LEDGER ROW WILL CHANGE" if changed else "ledger row already matches the reconciled exit"))

    # Proposed status.json accounting (what the engine would load from the fixed ledger)
    proposed = recompute_status(trades)
    # reflect the pending row change on the target
    tmp = [dict(r) for r in trades]
    tmp[tgt_i]["Exit_Reason"] = rec["reason"]
    tmp[tgt_i]["Exit_Price"] = exit_price_str
    tmp[tgt_i]["Profit"] = profit_str
    tmp[tgt_i]["Balance_After"] = balance_str
    tmp[tgt_i]["Exit_Time"] = rec["exit_time"]
    proposed = recompute_status(tmp)

    cur_status = {}
    if os.path.isfile(status_path):
        try:
            cur_status = json.load(open(status_path))
        except Exception as e:
            print(f"\n(warning: could not read status.json: {e})")

    print("\nstatus.json accounting -> target:")
    for k in ("total_trades", "wins", "losses", "win_rate", "equity", "trade_active", "next_trade_num"):
        print(f"  {k:14s}: {cur_status.get(k)!r:>12}  ->  "
              f"{False if k == 'trade_active' else proposed.get(k)!r}")

    if not args.apply:
        print("\nREPORT-ONLY: nothing written. Re-run with --apply to reconcile (backs up first).")
        return 0

    # ---- APPLY ----
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    dest = os.path.join(args.root, "backups", f"reconcile_{ts}")
    made = backup([trades_path, status_path], dest)
    print(f"\nBackup written: {', '.join(os.path.relpath(m, args.root) for m in made)}")

    new_fields = list(tgt.values())  # keep every field, incl. RSI/ATR/EMA-at-entry
    order = list(tgt.keys())
    new_fields[order.index("Exit_Time")] = rec["exit_time"]
    new_fields[order.index("Exit_Price")] = exit_price_str
    new_fields[order.index("Exit_Reason")] = rec["reason"]
    new_fields[order.index("Profit")] = profit_str
    new_fields[order.index("Balance_After")] = balance_str
    rewrite_trades_row(trades_path, args.trade_num, entry_time, new_fields)
    print(f"Reconciled trades.csv row #{args.trade_num}.")

    # rebuild status accounting from the now-fixed ledger (engine load semantics)
    fixed = load_trades(trades_path)
    acct = recompute_status(fixed)
    if os.path.isfile(status_path):
        st = json.load(open(status_path))
    else:
        st = {}
    st["equity"] = acct["equity"]
    st["total_trades"] = acct["total_trades"]
    st["next_trade_num"] = acct["next_trade_num"]
    st["wins"] = acct["wins"]
    st["losses"] = acct["losses"]
    st["win_rate"] = acct["win_rate"]
    st["trade_active"] = False
    for k in ("trade_type", "entry_price", "stop_loss", "take_profit", "entry_time",
              "current_trade_num", "entry_rsi", "entry_atr", "entry_wick_ratio",
              "entry_ema_fast", "entry_ema_slow"):
        st[k] = None
    st["last_update"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    with open(status_path, "w") as f:
        json.dump(st, f, indent=2)
        f.write("\n")
    print(f"Rewrote {os.path.relpath(status_path, args.root)} accounting to match the ledger.")
    print("\nDone. Verify with: python3 tools/check_data.py && python3 tools/handoff_check.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
