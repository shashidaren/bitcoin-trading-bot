#!/usr/bin/env python3
"""
Losing-trade analysis for BTC (port of gold's analyze_losers.py, M5 / RR 1:2).

What it answers:
  1. How much heat do winners take, and how far do losers get before dying?
     (MAE / MFE in R, re-walked on M5 bars.)
  2. "Losers that were winners first" - the share of losses that reached +xR
     before reversing. This is the mechanism behind the BE-ratchet question.
  3. Entry-feature drift: what do winners look like vs losers vs the whole book.
  4. Realized-R sanity: an SL must cost 1R and a TP must pay 2R at LOT_SIZE
     0.01; rows that do not are sizing/schema drift (this is the class of bug
     that produced the two -$197 pre-port trades).
  5. Stop-width grid: is the 2xATR stop too tight? (complement of the target
     grid in tools/pathwalk_sims.py)

Counterfactual EXIT questions are deliberately NOT answered here: scoring a
trade inside the window its actual exit left open cannot see a looser exit
(gold's 2026-09-15 review §6.3 - its naive table printed "TP 1.5R -> 0.6% win
rate" against a real 19.4%). Use tools/pathwalk_sims.py or the grids in
tools/win_rate_report.py, which walk with an explicit horizon.

Usage: python3 tools/analyze_losers.py [--root DIR] [--spread 0.25]
Read-only - writes nothing.
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

MIN_DECISIVE = 5          # buckets smaller than this print a warning, not a verdict


def q(values, p):
    if not values:
        return float("nan")
    v = sorted(values)
    return v[min(len(v) - 1, int(len(v) * p))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.dirname(HERE))
    ap.add_argument("--spread", type=float, default=0.0)
    ap.add_argument("--horizon", type=int, default=240)
    args = ap.parse_args()

    trades = R.load_trades(os.path.join(args.root, "trades.csv"))
    bars = R.load_bars(os.path.join(args.root, "forward_test_log.csv"))
    clean = [t for t in trades if t["et"] >= datetime(2026, 9, 5)]
    covered, _ = R.coverage(clean, bars)

    print(f"analyze_losers - {len(trades)} trades ({len(clean)} from 09-05), "
          f"{len(covered)} log-covered, {len(bars)} M5 bars\n")

    # ------------------------------------------------------------- 1. baseline
    print("== 1. BASELINE (from 09-05) ==")
    w = [t for t in clean if t["reason"] == "TP"]
    l = [t for t in clean if t["reason"] == "SL"]
    pnl = sum(t["profit"] for t in clean) - args.spread * len(clean)
    print(f"  {len(clean)} trades: {len(w)}W/{len(l)}L = "
          f"{len(w)/len(clean)*100:.1f}% all-in, decisive WR "
          f"{len(w)/(len(w)+len(l))*100:.1f}% (breakeven {1/(1+R.ATR_TP_MULT/R.ATR_SL_MULT)*100:.1f}%)")
    print(f"  net P/L {pnl:+.2f} (spread ${args.spread:.2f}/trade) | "
          f"R total {2*len(w)-len(l):+d}R | avg 1R "
          f"${statistics.mean(R.r_money(t['atr']) for t in clean):.2f}")
    print(f"  median ATR at entry ${statistics.median(t['atr'] for t in clean):.2f} "
          f"({statistics.median(t['atr']/t['entry'] for t in clean)*100:.3f}% of price)\n")

    # ------------------------------------------------------- 2. MFE / MAE walk
    print(f"== 2. HEAT AND RUN-UP (MAE/MFE in R, {len(covered)} covered trades) ==")
    print("   window = entry -> actual exit +5 min; horizon = 240 min from entry")
    rows = []
    for t in covered:
        seg = [b for b in bars if t["et"] < b["dt"] <= t["xt"] + timedelta(minutes=5)]
        seg_h = [b for b in bars if t["et"] < b["dt"] <= t["et"] + timedelta(minutes=args.horizon)]
        risk = abs(t["entry"] - t["sl"]) or R.ATR_SL_MULT * t["atr"]
        d = 1 if t["side"] == "BUY" else -1
        def exc(seg_):
            if not seg_:
                return None, None
            fav = max(d * (b["h"] - t["entry"]) for b in seg_)
            fav2 = max(d * (b["l"] - t["entry"]) for b in seg_)
            adv = min(d * (b["h"] - t["entry"]) for b in seg_)
            adv2 = min(d * (b["l"] - t["entry"]) for b in seg_)
            return max(fav, fav2) / risk, min(adv, adv2) / risk
        mfe, mae = exc(seg)
        mfe_h, _ = exc(seg_h)
        rows.append(dict(t=t, mfe=mfe, mae=mae, mfe_h=mfe_h))
        if mfe is None:
            continue
    for reason in ("TP", "SL"):
        sel = [r for r in rows if r["t"]["reason"] == reason and r["mfe"] is not None]
        if not sel:
            continue
        print(f"  {reason}: n={len(sel):2d}  MFE median {statistics.median(r['mfe'] for r in sel):+.2f}R "
              f"| MAE median {statistics.median(r['mae'] for r in sel):+.2f}R "
              f"| MFE p90 {q([r['mfe'] for r in sel], 0.9):+.2f}R")
    print()

    # --------------------------------------- 3. losers that were winners first
    print("== 3. LOSERS THAT WERE IN PROFIT FIRST ==")
    los = [r for r in rows if r["t"]["reason"] == "SL" and r["mfe"] is not None]
    win = [r for r in rows if r["t"]["reason"] == "TP" and r["mfe"] is not None]
    if los:
        for th in (0.25, 0.5, 0.75, 1.0, 1.5):
            n = sum(1 for r in los if r["mfe"] >= th)
            print(f"  losers that reached +{th:.2f}R before dying: {n:2d}/{len(los)} "
                  f"({n/len(los)*100:4.0f}%)")
        n_arm = sum(1 for r in los if r["mfe"] >= 0.5)
        n_win_arm = sum(1 for r in win if r["mfe"] >= 0.5)
        print(f"  -> a BE ratchet at +0.50R would arm on {n_arm}/{len(los)} eventual losers "
              f"AND on {n_win_arm}/{len(win)} eventual winners")
        print("     (that trade-off is exactly why its net effect needs a horizon walk)")
    print("  (net effect of a ratchet is measured with a horizon in tools/pathwalk_sims.py §B)\n")

    # ------------------------------------------------------ 4. feature drift
    print("== 4. ENTRY FEATURES: winners vs losers (all trades from 09-05) ==")
    def feat(name, fn):
        wv = [fn(t) for t in w if fn(t) is not None]
        lv = [fn(t) for t in l if fn(t) is not None]
        if not wv or not lv:
            return
        d = statistics.median(wv) - statistics.median(lv)
        print(f"  {name:30s} W median {statistics.median(wv):9.3f}   L median "
              f"{statistics.median(lv):9.3f}   diff {d:+9.3f}")
    feat("RSI at entry", lambda t: t["rsi"])
    feat("ATR at entry ($)", lambda t: t["atr"])
    feat("ATR % of price", lambda t: t["atr"] / t["entry"] * 100)
    feat("wick ratio (%)", lambda t: t["wick"])
    feat("|EMA50-EMA200| ($)", lambda t: abs(t["ema50"] - t["ema200"]))
    feat("|EMA50-EMA200| % price", lambda t: abs(t["ema50"] - t["ema200"]) / t["entry"] * 100)
    feat("entry-EMA50 signed ($)", lambda t: (t["entry"] - t["ema50"]) * (1 if t["side"] == "BUY" else -1))
    feat("entry-EMA50 in ATR", lambda t: (t["entry"] - t["ema50"]) * (1 if t["side"] == "BUY" else -1) / t["atr"])
    feat("1R risk ($)", lambda t: R.r_money(t["atr"]))
    feat("hold (min)", lambda t: (t["xt"] - t["et"]).total_seconds() / 60)
    print()

    # --------------------------------------------------------- 5. realized-R
    print("== 5. REALIZED-R SANITY (catches lot/size or schema drift) ==")
    print("  Checked only on rows from 09-06 17:49 UTC (the live SL 2xATR / TP 4xATR rule, RR 1:2).")
    print("  Older rows ran SL 1.5xATR / TP 2.5xATR with candle-era fills that overshoot the")
    print("  logged stop, so they cannot be R-validated - and the two 09-03 rows were sized")
    print("  100x too large (-100R).")
    bad = checked = 0
    old_rows = 0
    devs = {"SL": [], "TP": []}
    for t in trades:
        risk = abs(t["entry"] - t["sl"])
        rr = R.planned_rr(t)
        if risk <= 0 or not rr:
            continue
        if t["et"] < R.GEOM2_DEPLOY:
            old_rows += 1
            continue
        checked += 1
        r = R.realized_r(t)
        exp = -1.0 if t["reason"] == "SL" else rr
        dev = (r - exp) / abs(exp) * 100
        devs[t["reason"]].append(dev)
        # simulated exits fill on ticks; a fast move between price events can overshoot
        if abs(dev) > 20:
            bad += 1
            print(f"    [WARN] #{t['num']} {t['side']} {t['et']:%m-%d %H:%M} {t['reason']} "
                  f"realized {r:+.2f}R vs planned {exp:+.2f}R ({dev:+.0f}%) "
                  f"profit {t['profit']:+.2f}, risk ${risk:.2f}")
    for reason, vals in devs.items():
        if vals:
            print(f"    {reason} rows: n={len(vals):2d}  median slippage {statistics.median(vals):+5.1f}%  "
                  f"worst {min(vals) if reason == 'SL' else max(vals):+6.1f}%")
    if not bad:
        print(f"    all {checked} live-geometry rows inside +-20% "
              f"({old_rows} pre-change rows skipped by design)")
    print()

    # ------------------------------------------------------- 6. stop-width grid
    print(f"== 6. STOP-WIDTH GRID (SL multiple; TP fixed at {R.ATR_TP_MULT:.0f}xATR, "
          f"{args.horizon}-min horizon) ==")
    for sl in (1.0, 1.5, 2.0, 2.5, 3.0):
        w_ = l_ = tm = 0
        pnl = 0.0
        for t in covered:
            seg = [b for b in bars if t["et"] < b["dt"] <= t["et"] + timedelta(minutes=args.horizon)]
            out, r, held, _ = R.walk(t["entry"], t["side"], t["atr"], seg, sl_mult=sl)
            w_ += out == "TP"
            l_ += out == "SL"
            tm += out == "TIME"
            pnl += r * R.r_money(t["atr"]) - args.spread
        dec = w_ + l_
        print(f"  SL {sl:.1f}xATR: {w_}W/{l_}L/{tm}T  WR {w_/dec*100 if dec else 0:5.1f}%  "
              f"P/L {pnl:+7.2f}" + ("   <- LIVE" if sl == R.ATR_SL_MULT else ""))
    print("  (n=19 covered trades - read the direction, not the digits)\n")

    print("Reminder: for exit-rule counterfactuals use tools/pathwalk_sims.py - it walks")
    print("with an explicit horizon and prints its agreement with the live engine first.")


if __name__ == "__main__":
    main()
