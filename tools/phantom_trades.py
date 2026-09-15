#!/usr/bin/env python3
"""
Phantom-trade replay - what did the blocked signals actually do?

Every row in skipped_trades.csv is a FULL strategy signal (all engine gates
passed) that the risk layer (trade_filter.py) refused: cooldown, blackout,
daily-loss halt, or the %-based ATR bounds. Those skips have no trade record,
so their value/cost is invisible in trades.csv.

This tool reconstructs each blocked signal from forward_test_log.csv and
simulates the trade it WOULD have been (SL 2xATR / TP 4xATR, LOT_SIZE 0.01),
then walks the log forward to see whether it would have hit TP or SL. That
turns the skip log into measurable evidence: did the cooldowns / blackouts /
halts save money or burn it?

Since 2026-09-15 the walk comes from tools/replay_lib.py (ONE copy of the
direction-safe excursion logic for every analysis tool - gold's 09-15 review
found its own duplicated walks had SELL extremes inverted, so shorts silently
"fell back to their actual outcome" and the tool looked self-validating).
Signals the log cannot resolve within the 24 h horizon are marked to market at
the last available bar and reported separately as TIME instead of vanishing
into an "open" column.

Output is a per-skip table + summary by skip reason. P&L is in $ at 0.01 lot
(price distance x LOT_SIZE), raw distances without spread/slippage.

Usage: python3 tools/phantom_trades.py [--root DIR] [--log LOG] [--skips SKIPS]
                                       [--since "YYYY-MM-DD HH:MM"]
Read-only - no files are modified.
"""
import argparse
import os
import sys
from bisect import bisect_left
from collections import defaultdict
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import replay_lib as R  # noqa: E402

MAX_HOLD_MIN = 24 * 60      # 24 h horizon (kept from the original tool)
MATCH_SECONDS = 360         # skip timestamp must land within +-6 min of a log row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.dirname(HERE))
    ap.add_argument("--log", default=None)
    ap.add_argument("--skips", default=None)
    ap.add_argument("--since", default=None, help='only show skips >= "YYYY-MM-DD HH:MM"')
    ap.add_argument("--spread", type=float, default=0.0,
                    help="assumed round-trip cost in $ per would-be trade at LOT_SIZE "
                         "(default 0). Applied to every SCORED phantom, like the other "
                         "tools - the ledger itself has no cost model.")
    args = ap.parse_args()

    log_path = args.log or os.path.join(args.root, "forward_test_log.csv")
    skip_path = args.skips or os.path.join(args.root, "skipped_trades.csv")

    log = R.load_bars(log_path, with_indicators=True)
    stats = R.enrich_log(log)
    print("=== reconstruction quality vs logged values (pre-update) ===")
    for name, (ok, bad) in stats.items():
        pct = ok / (ok + bad) * 100 if (ok + bad) else 0
        print(f"  {name:<10} {ok}/{ok+bad} match ({pct:.1f}%)")

    stamps = [r["dt"] for r in log]
    sig_cache = {}
    since = datetime.strptime(args.since, "%Y-%m-%d %H:%M") if args.since else None

    skips = []
    with open(skip_path, newline="") as f:
        import csv
        for r in csv.DictReader(f):
            try:
                dt = datetime.strptime((r.get("Timestamp") or "").strip(), R.TS_FMT)
            except (KeyError, ValueError):
                continue
            reason = r.get("Reason", "")
            kind = ("daily-halt" if reason.startswith("Daily Loss")
                    else "cooldown" if reason.startswith("SL Cooldown")
                    else "blackout" if reason.startswith("Blackout")
                    else "atr")
            skips.append({"dt": dt, "reason": reason, "kind": kind})

    print(f"\n=== blocked signals -> phantom outcome ({len(skips)} skips) ===")
    print(f"{'skip time':<17} {'kind':<11} {'side':<5} {'result':<12} {'pnl':>7}  reason")
    rows_out = []
    for s in skips:
        if since and s["dt"] < since:
            continue
        i = bisect_left(stamps, s["dt"])
        best = None
        for j in (i, i - 1, i + 1, i - 2):
            if 0 <= j < len(log) and abs((log[j]["dt"] - s["dt"]).total_seconds()) <= MATCH_SECONDS:
                best = j
                break
        if best is None:
            rows_out.append((s, None, "-", "no log row", 0.0))
            continue
        if best not in sig_cache:
            buy, sell = R.signal_at(log, best)
            sig_cache[best] = ("BUY" if buy else "SELL") if (buy or sell) else None
        side = sig_cache[best]
        if side is None:
            rows_out.append((s, log[best], "-", "not reproducible", 0.0))
            continue
        row = log[best]
        atr, entry = row["post_atr"], row["c"]
        seg = [b for b in log if b["dt"] > row["dt"]]
        out, r_mult, held, _exit = R.walk(entry, side, atr, seg, horizon_min=MAX_HOLD_MIN,
                                          start_dt=row["dt"])
        pnl = r_mult * R.r_money(atr)
        rows_out.append((s, row, side, out, pnl))

    for s, row, side, res, pnl in rows_out:
        print(f"{s['dt'].strftime('%m-%d %H:%M:%S'):<17} {s['kind']:<11} {side:<5} {res:<12} "
              f"{pnl:>+7.2f}  {s['reason'][:48]}")

    print("\n=== summary by skip kind (phantom P&L, $ at 0.01 lot) ===")
    agg = defaultdict(lambda: [0, 0, 0, 0, 0])  # n, W, L, TIME, unscored
    pnls = defaultdict(float)
    for s, row, side, res, pnl in rows_out:
        a = agg[s["kind"]]
        a[0] += 1
        a[1] += res == "TP"
        a[2] += res == "SL"
        a[3] += res == "TIME"
        a[4] += res in ("no log row", "not reproducible")
        pnls[s["kind"]] += pnl
    grand = [0, 0, 0, 0, 0]
    gpnl = gnet = 0.0
    for kind in sorted(agg):
        n, w, l, t, u = agg[kind]
        scored = n - u
        net = pnls[kind] - args.spread * scored
        print(f"  {kind:<11} {n:>3} blocked -> {w}W/{l}L/{t}T  ({u} unscorable: no log row / "
              f"gates changed)   phantom {pnls[kind]:+8.2f} gross"
              + (f"  {net:+8.2f} net of ${args.spread:.2f}" if args.spread else ""))
        for x in range(5):
            grand[x] += (n, w, l, t, u)[x]
        gpnl += pnls[kind]
        gnet += net
    print(f"  {'TOTAL':<11} {grand[0]:>3} blocked -> {grand[1]}W/{grand[2]}L/{grand[3]}T "
          f"({grand[4]} unscorable)   phantom {gpnl:+8.2f} gross"
          + (f"  {gnet:+8.2f} net" if args.spread else ""))

    # ---- sequential view -------------------------------------------------
    # Consecutive skips minutes apart are usually the SAME setup re-firing:
    # had the first been taken, the engine would have been in_trade (and on
    # SL, in cooldown) for the rest. This view keeps only the phantoms the
    # engine could actually have taken one after another.
    print("\n=== sequential view (dedup: in-trade + 30/60m post-SL cooldown) ===")
    busy_until = None
    consec_sl = 0
    seq = []
    for s, row, side, res, pnl in rows_out:
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
    agg2 = defaultdict(lambda: [0, 0, 0, 0, 0.0])
    for s, side, res, pnl in seq:
        a = agg2[s["kind"]]
        a[0] += 1
        a[1] += res == "TP"
        a[2] += res == "SL"
        a[3] += res == "TIME"
        a[4] += pnl
    g2 = [0, 0, 0, 0, 0.0]
    for kind in sorted(agg2):
        n, w, l, t, p = agg2[kind]
        print(f"  {kind:<11} {n:>3} taken  -> {w}W/{l}L/{t}T   phantom {p:+8.2f} gross"
              + (f"  {p - args.spread * n:+8.2f} net" if args.spread else ""))
        for x in range(5):
            g2[x] += (n, w, l, t, p)[x]
    dec = g2[1] + g2[2]
    wr = g2[1] / dec * 100 if dec else 0
    print(f"  {'TOTAL':<11} {g2[0]:>3} taken  -> {g2[1]}W/{g2[2]}L/{g2[3]}T "
          f"({wr:.0f}% WR over decisive) phantom {g2[4]:+8.2f} gross"
          + (f"  {g2[4] - args.spread * g2[0]:+8.2f} net" if args.spread else ""))
    print("\n  compare: the traded book is "
          f"{len(R.load_trades(os.path.join(args.root, 'trades.csv')))} rows at 41% decisive")

    print("\nNote: raw ATR-geometry distances x 0.01 lot"
          + (f", net of ${args.spread:.2f}/trade round trip" if args.spread else
             " - pass --spread to see the cost haircut, no slippage modeled"))
    print("      'not reproducible' = signal fired under gates/params that no longer match the log.")
    print("      SL-first tie-break on bars that touch both levels (conservative).")
    print("      TIME rows are marked to market at the 24 h cap (or at the end of the log for")
    print("      recent skips) - they are not a claim the trade would have been closed there.")
    print("      The sequential view ignores cascades - treat it as an estimate, not a fact.")


if __name__ == "__main__":
    main()
