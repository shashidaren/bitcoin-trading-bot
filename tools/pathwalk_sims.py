#!/usr/bin/env python3
"""
Sequence-aware exit-rule replay for BTC (port of gold's pathwalk_sims.py).

Answers the "what if the exit were different?" question honestly:
  - every trade/signal is re-walked bar-by-bar through forward_test_log.csv in
    TRUE TIME ORDER with its own stop/target levels,
  - a bar that spans both levels resolves to the STOP (conservative),
  - the walk never sees the future beyond its horizon, and
  - rows that end flat at the horizon are marked to market and reported as
    TIME, never silently replaced by the actual outcome (that fallback is what
    made gold's pre-review exit table "self-validating" - see its
    docs/REVIEW-2026-09-15.md §6).

VALIDATION FIRST: the tool walks the trades the engine actually made, inside
their real exit windows, with the live geometry (SL 2xATR / TP 4xATR) and
prints the agreement rate. If that row does not reproduce the engine, no other
row in this file is worth reading.

BTC notes: M5 bars (log rows are stamped at bar close, so the walk starts at
the next row), exit domain {SL, TP}, no BE ratchet live (the BE grid is a
candidate measurement only), LOT_SIZE 0.01 => money = price distance x 0.01.
Legacy ledger rows are comma-grouped and are parsed comma-tolerantly.

Usage:
  python3 tools/pathwalk_sims.py [--root DIR] [--spread 0.25] [--horizon 240]
                                 [--census]

Grids:  A) real trades, TP multiple sweep      B) real trades, BE ratchet sweep
        C) cascade-aware real trades           D) raw signal census (entry stream)
        E) takeable census through cascade + blackout/daily gates (the honest D)
Read-only - no files are modified.
"""
import argparse
import os
import sys
from collections import Counter
from datetime import timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
import replay_lib as R  # noqa: E402
import trade_filter as TF  # noqa: E402  (blackout windows, single source of truth)


def money(r_mult, atr, spread=0.0):
    """$ for an R-multiple, net of a per-trade round-trip cost."""
    return r_mult * R.r_money(atr) - spread


def grid_row(label, rows, spread, note=""):
    w, l, be, tm, pnl, rtot = R.summarize(rows)
    dec = w + l
    wr = w / dec * 100 if dec else float("nan")
    pnl -= spread * len(rows)
    print(f"    {label:26s} {w:3d}W/{l:3d}L/{be:2d}BE/{tm:2d}T  "
          f"WR {wr:5.1f}%  sumR {rtot:+7.1f}  P/L {pnl:+8.2f}  /trade {pnl/len(rows):+.3f}"
          + (f"   {note}" if note else ""))
    return pnl


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.dirname(HERE))
    ap.add_argument("--spread", type=float, default=0.0,
                    help="assumed round-trip cost in $ per trade at LOT_SIZE (default 0)")
    ap.add_argument("--horizon", type=int, default=240,
                    help="walk horizon in minutes from entry (default 240 = 4h)")
    ap.add_argument("--census", action="store_true",
                    help="also replay the reconstructed signal stream (all signals in the log)")
    args = ap.parse_args()

    trades_path = os.path.join(args.root, "trades.csv")
    log_path = os.path.join(args.root, "forward_test_log.csv")
    trades = R.load_trades(trades_path)
    bars = R.load_bars(log_path)
    covered, uncovered = R.coverage(trades, bars)

    print(f"pathwalk_sims - {len(trades)} trades, {len(bars)} M5 bars "
          f"({bars[0]['dt']} -> {bars[-1]['dt']}), horizon {args.horizon} min, "
          f"spread ${args.spread:.2f}/trade")
    print(f"log-covered trades: {len(covered)} (entry >= first bar); "
          f"{len(uncovered)} predate the log and cannot be re-walked\n")

    # ---------------- validation: does the walk reproduce the engine? ---------
    print("== 0. VALIDATION - live geometry inside the ACTUAL exit window ==")
    ok = diff = 0
    mismatches = []
    for t in covered:
        seg = [b for b in bars if t["et"] < b["dt"] <= t["xt"] + timedelta(minutes=5)]
        out, r, held, _ = R.walk(t["entry"], t["side"], t["atr"], seg)
        if out == t["reason"]:
            ok += 1
        else:
            diff += 1
            mismatches.append((t, out))
    print(f"    agreement with actual outcomes: {ok}/{len(covered)}")
    for t, out in mismatches[:10]:
        print(f"      MISMATCH #{t['num']} {t['side']} {t['et']:%m-%d %H:%M} "
              f"actual {t['reason']} walk {out}")
    print("    (the walk resolves ties to the stop and the live engine resolves them on")
    print("     ticks, so <100% is expected; read every grid below with that error bar)\n")

    # ---------------- A. real trades: TP multiple grid ------------------------
    print(f"== A. REAL TRADES - TP multiple grid (SL fixed at {R.ATR_SL_MULT:.0f}xATR, "
          f"{args.horizon}-min horizon, cascade-ignorant) ==")
    for tp in (2.0, 3.0, 4.0, 5.0, 6.0, 8.0):
        rows = []
        for t in covered:
            seg = [b for b in bars if t["et"] < b["dt"] <= t["et"] + timedelta(minutes=args.horizon)]
            out, r, held, _ = R.walk(t["entry"], t["side"], t["atr"], seg, tp_mult=tp)
            rows.append(dict(outcome=out, r=r, atr=t["atr"]))
        tag = "  <- LIVE (RR 1:2)" if tp == R.ATR_TP_MULT else ""
        grid_row(f"TP {tp:.0f}xATR ({tp/2:.2f}R)", rows, args.spread, tag)

    # ---------------- B. real trades: BE ratchet grid ------------------------
    print(f"\n== B. REAL TRADES - breakeven-ratchet grid (TP {R.ATR_TP_MULT:.0f}xATR, "
          f"{args.horizon}-min horizon) ==")
    print("    BTC has NO BE ratchet live; this measures gold's candidate on BTC data.")
    for be in (None, 0.5, 0.75, 1.0, 1.25):
        rows = []
        for t in covered:
            seg = [b for b in bars if t["et"] < b["dt"] <= t["et"] + timedelta(minutes=args.horizon)]
            out, r, held, _ = R.walk(t["entry"], t["side"], t["atr"], seg, be_trigger=be)
            rows.append(dict(outcome=out, r=r, atr=t["atr"]))
        grid_row("BE " + ("off (live)" if be is None else f"at +{be:.2f}R"), rows, args.spread)

    # ---------------- C. cascade-aware book ----------------------------------
    print(f"\n== C. CASCADE-AWARE (one position at a time + escalating SL cooldown) ==")
    print("    Grid A/B are optimistic: a position held for hours blocks new entries.")
    for tp in (3.0, 4.0, 5.0):
        taken, skipped, rows = R.cascade(covered, bars, tp_mult=tp, horizon_min=args.horizon)
        w, l, be, tm, pnl, rtot = R.summarize(rows)
        pnl -= args.spread * taken
        dec = w + l
        print(f"    TP {tp:.0f}xATR: taken {taken:3d} (skip {skipped:3d})  "
              f"{w:3d}W/{l:3d}L/{be}BE/{tm}T  WR {w/dec*100 if dec else 0:5.1f}%  "
              f"P/L {pnl:+8.2f}  /trade {pnl/taken if taken else 0:+.3f}")
    for be in (0.5, 0.75, 1.0):
        taken, skipped, rows = R.cascade(covered, bars, be_trigger=be, horizon_min=args.horizon)
        w, l, be_n, tm, pnl, rtot = R.summarize(rows)
        pnl -= args.spread * taken
        dec = w + l
        print(f"    BE +{be:.2f}R (TP 4x): taken {taken:3d} (skip {skipped:3d})  "
              f"{w:3d}W/{l:3d}L/{be_n}BE/{tm}T  WR {w/dec*100 if dec else 0:5.1f}%  "
              f"P/L {pnl:+8.2f}  /trade {pnl/taken if taken else 0:+.3f}")

    # ---------------- E. cascade-aware takeable census ----------------------
    if args.census:
        bars_full = R.load_bars(log_path, with_indicators=True)
        R.enrich_log(bars_full)
        sigs = R.all_signals(bars_full)
        takeable = [s for s in sigs if not TF.is_in_blackout(s["dt"])[0]]
        blocked = len(sigs) - len(takeable)
        print(f"\n== E. TAKEABLE CENSUS - cascade + risk gates ({len(takeable)} of {len(sigs)} "
              f"signals; {blocked} in session blackouts) ==")
        print("    One position at a time, escalating SL cooldown, 3-SL daily halt. This is")
        print("    the honest version of grid D: the live book cannot take every signal.")
        for tp in (2.0, 3.0, 4.0, 5.0, 6.0):
            taken, skipped, rows = R.cascade(takeable, bars_full, tp_mult=tp,
                                             horizon_min=args.horizon, daily_halt=TF.MAX_DAILY_LOSSES)
            w, l, be_n, tm, pnl, rtot = R.summarize(rows)
            pnl -= args.spread * taken
            dec = w + l
            tag = "  <- LIVE (RR 1:2)" if tp == R.ATR_TP_MULT else ""
            print(f"    TP {tp:.0f}xATR BE off: taken {taken:3d} (skip {skipped:3d})  "
                  f"{w:3d}W/{l:3d}L/{be_n}BE/{tm}T  WR {w/dec*100 if dec else 0:5.1f}%  "
                  f"P/L {pnl:+8.2f}{tag}")
        for be in (0.5, 0.75, 1.0, 1.25):
            taken, skipped, rows = R.cascade(takeable, bars_full, be_trigger=be,
                                             horizon_min=args.horizon, daily_halt=TF.MAX_DAILY_LOSSES)
            w, l, be_n, tm, pnl, rtot = R.summarize(rows)
            pnl -= args.spread * taken
            dec = w + l
            print(f"    BE +{be:.2f}R (TP 4x): taken {taken:3d} (skip {skipped:3d})  "
                  f"{w:3d}W/{l:3d}L/{be_n}BE/{tm}T  WR {w/dec*100 if dec else 0:5.1f}%  "
                  f"P/L {pnl:+8.2f}")
        print("    NOTE: cascade trade counts are small (skip-dedup removes most of the")
        print("    stream), so differences of a few $ are inside the noise - see")
        print("    docs/REVIEW-2026-09-15.md before acting on any row here.")

    # ---------------- D. signal census --------------------------------------
    if args.census:
        bars_full = R.load_bars(log_path, with_indicators=True)
        R.enrich_log(bars_full)
        sigs = R.all_signals(bars_full)
        print(f"\n== D. SIGNAL CENSUS - all {len(sigs)} reconstructed signals in the log "
              f"({Counter(s['side'] for s in sigs)}) ==")
        print("    Cascade-ignorant and includes signals the risk gates would block; it")
        print("    measures the ENTRY STREAM, not the traded book.")
        for tp in (2.0, 3.0, 4.0, 5.0):
            rows = []
            for s in sigs:
                seg = [b for b in bars_full if s["dt"] < b["dt"] <= s["dt"] + timedelta(minutes=args.horizon)]
                out, r, held, _ = R.walk(s["entry"], s["side"], s["atr"], seg, tp_mult=tp)
                rows.append(dict(outcome=out, r=r, atr=s["atr"]))
            grid_row(f"TP {tp:.0f}xATR", rows, args.spread,
                     "<- live geometry" if tp == R.ATR_TP_MULT else "")
        print("    per side (live geometry):")
        for side in ("BUY", "SELL"):
            rows = []
            for s in sigs:
                if s["side"] != side:
                    continue
                seg = [b for b in bars_full if s["dt"] < b["dt"] <= s["dt"] + timedelta(minutes=args.horizon)]
                out, r, held, _ = R.walk(s["entry"], s["side"], s["atr"], seg)
                rows.append(dict(outcome=out, r=r, atr=s["atr"]))
            grid_row(side, rows, args.spread)
        for be in (0.5, 0.75, 1.0):
            rows = []
            for s in sigs:
                seg = [b for b in bars_full if s["dt"] < b["dt"] <= s["dt"] + timedelta(minutes=args.horizon)]
                out, r, held, _ = R.walk(s["entry"], s["side"], s["atr"], seg, be_trigger=be)
                rows.append(dict(outcome=out, r=r, atr=s["atr"]))
            grid_row(f"BE +{be:.2f}R", rows, args.spread)

    print("\nReading notes:")
    print("  * TIME rows are marked to market at the horizon close - they are not a")
    print("    fallback to the actual result; a longer horizon would resolve most of them.")
    print("  * Rows are not comparable by trade COUNT across TP levels: a tighter target")
    print("    finishes sooner, so the same signals resolve differently in a cascade.")
    print("  * '$ spread' is a flat round-trip haircut at LOT_SIZE 0.01 - measure the real")
    print("    XM BTCUSD spread before any LIVE decision (docs/HANDOFF.md §7).")


if __name__ == "__main__":
    main()
