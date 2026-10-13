#!/usr/bin/env python3
"""
Large-N historical BACK-TEST of the FROZEN BTC gates - the fast path around the
~30-week forward test for the STATISTICAL go-live gates.

The forward test is slow because it is real time (~4 trades/day, ~700 post-gate
trades needed). The binding gates are statistical - EDGE (t-stat, day-block
bootstrap P(net/trade>0) >= 0.90) and COST (break-even spread / assumed spread
>= 2.0x) - and those can be cross-checked far faster by replaying a long history
through the SAME signal/walk/risk code. Feed it months of M5 bars and it reports
the gate metrics at N in the hundreds/thousands in seconds.

This tool changes NO strategy logic: it reuses
  - replay_lib      for signals (all_signals), the walk, and the cascade
                    (one position at a time + escalating SL cooldown + 3-SL
                    daily halt = the live risk gates), and
  - live_readiness  for the exact gate statistics (norm_cdf, boot_iid, boot_days).
It prepares raw OHLC with history_to_log (validated to reproduce the engine's
indicators).

INPUT is either an existing forward_test_log.csv (has an EMA_50 column) or a raw
OHLC csv (Timestamp,Open,High,Low,C[,Volume]) - detected automatically. Raw input
is converted with history_to_log; pass --save-log to keep the prepared log.

HONESTY (this is a back-test, not a go-live substitute - read before quoting):
  * It measures the strategy LOGIC on an M5 reconstruction. The live engine
    resolves entries/exits on ticks, so an M5 walk cannot reproduce it exactly
    (the same <100% agreement pathwalk_sims reports). Read rows RELATIVELY.
  * It is OUT-OF-SAMPLE only for history the gates were NOT tuned on. Do not read
    a point estimate as a live expectation; the handoff forbids treating a pooled
    back-test number as one.
  * Every trade uses the CURRENT geometry (SL 2xATR / TP 4xATR), so there is no
    geometry-change pooling inside one run. Use --min-date to align a slice.
  * If the reconstruction quality (printed first) is not ~100% for floor/ATR/RSI,
    distrust every number below it.

Usage:
  python3 tools/backtest.py long_history.csv --spread 0.40 --save-log bt_log.csv
  python3 tools/backtest.py forward_test_log.csv --spread 0.40 --horizon 240
  python3 tools/backtest.py history.csv --side sell --tp 5.0 --be 0.75
"""
import argparse
import csv
import math
import os
import random
import statistics as st
import sys
import tempfile
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
import replay_lib as R              # noqa: E402
import live_readiness as LR         # noqa: E402  (reuse the exact gate stats)
import trade_filter as TF           # noqa: E402  (live risk gates)
import history_to_log as H          # noqa: E402  (raw OHLC -> engine-faithful log)

TS_FMT = "%Y-%m-%d %H:%M:%S"


def is_log_file(path):
    with open(path, newline="") as f:
        header = f.readline()
    return "EMA_50" in header and "EMA_200" in header


def prepare_raw(path, save_log):
    """Raw OHLC -> engine-faithful log file. Returns the log path."""
    bars = H.read_ohlc(path)
    if not bars:
        raise SystemExit(f"error: no usable OHLC rows in {path}")
    out = save_log or os.path.join(tempfile.mkdtemp(prefix="btc_bt_"), "prepared_log.csv")
    with open(out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=H.LOG_FIELDS)
        w.writeheader()
        for row in H.build_log(bars):
            w.writerow(row)
    print(f"prepared {len(bars)} raw bars -> {out} (EMA200 ready from bar {H.EMA_SLOW})")
    return out


def book_stats(results, spread, B, rng):
    """Gate metrics for a list of walk/cascade results. None if empty."""
    if not results:
        return None
    nets, gross, days = [], [], {}
    for r in results:
        g = r["r"] * R.r_money(r["atr"])          # $ gross (price distance x lot)
        net = g - spread
        gross.append(g)
        nets.append(net)
        d = (r.get("exit_dt") or r["entry_dt"]).date()
        days.setdefault(d, []).append(net)
    n = len(results)
    mu = st.mean(nets)
    sd = st.stdev(nets) if n > 1 else 0.0
    se = sd / math.sqrt(n) if n else 0.0
    t = mu / se if se else 0.0
    p_iid = sum(1 for x in LR.boot_iid(nets, B, rng) if x > 0) / B
    p_day = sum(1 for x in LR.boot_days(days, B, rng) if x > 0) / B
    gm = st.mean(gross)
    cover = gm / spread if spread else float("inf")
    w = sum(1 for r in results if r["outcome"] == "TP")
    l = sum(1 for r in results if r["outcome"] == "SL")
    srt = sorted(nets, reverse=True)
    tot = sum(nets)
    second_half = sum(nets[n // 2:])
    top5_d = sum(srt[:5])
    top5_share = (top5_d / tot) if tot > 0.01 else None   # only meaningful when net > 0
    return dict(n=n, w=w, l=l, wr=(100 * w / (w + l) if (w + l) else 0.0),
                mu=mu, sd=sd, se=se, t=t, p_iid=p_iid, p_day=p_day, gm=gm,
                cover=cover, tot=tot, top5=top5_share, top5_d=top5_d,
                second=second_half, ndays=len(days))


def show(label, s, spread):
    if s is None:
        print(f"    {label:22s} (no trades)")
        return
    cover = f"{s['cover']:.2f}x" if spread else "  n/a"
    print(f"    {label:22s} n={s['n']:4d}  {s['w']:4d}W/{s['l']:4d}L  WR {s['wr']:4.1f}%  "
          f"net/trade {s['mu']:+.3f}  t {s['t']:+5.2f}  P_day {100*s['p_day']:3.0f}%  "
          f"cover {cover}")
    frag = (f"top5={100*s['top5']:3.0f}% of net" if s['top5'] is not None
            else f"best5 ${s['top5_d']:+.2f} (net<=0, share n/m)")
    print(f"    {'':22s} net {s['tot']:+8.2f}  gross/trade {s['gm']:+.3f}  "
          f"{frag}  2nd-half net {s['second']:+.2f}  ({s['ndays']} days)")


def walk_stream(sigs, bars, tp, be, horizon):
    from datetime import timedelta
    out = []
    for s in sigs:
        seg = [b for b in bars if s["dt"] < b["dt"] <= s["dt"] + timedelta(minutes=horizon)]
        o, r, held, xdt = R.walk(s["entry"], s["side"], s["atr"], seg,
                                 tp_mult=tp, be_trigger=be, horizon_min=horizon, start_dt=s["dt"])
        out.append(dict(outcome=o, r=r, atr=s["atr"], entry_dt=s["dt"], exit_dt=xdt, side=s["side"]))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", help="forward_test_log.csv OR raw OHLC csv (auto-detected)")
    ap.add_argument("--spread", type=float, default=0.40,
                    help="assumed round-trip $/trade at 0.01 lot (default 0.40; 0 = gross)")
    ap.add_argument("--boot", type=int, default=5000, help="bootstrap iterations (default 5000)")
    ap.add_argument("--seed", type=int, default=20260910, help="RNG seed (deterministic)")
    ap.add_argument("--horizon", type=int, default=240, help="walk horizon minutes (default 240)")
    ap.add_argument("--tp", type=float, default=R.ATR_TP_MULT, help="TP multiple of ATR (default 4.0)")
    ap.add_argument("--be", type=float, default=None, help="hypothetical breakeven ratchet at +R")
    ap.add_argument("--side", choices=["both", "buy", "sell"], default="both")
    ap.add_argument("--min-date", default=None, help="only bars/signals on/after YYYY-MM-DD")
    ap.add_argument("--max-date", default=None, help="only bars/signals on/before YYYY-MM-DD")
    ap.add_argument("--save-log", default=None, help="where to write the prepared log (raw input)")
    args = ap.parse_args(argv)

    if not os.path.isfile(args.input):
        raise SystemExit(f"error: no such file {args.input}")
    rng = random.Random(args.seed)

    src = args.input
    if not is_log_file(args.input):
        src = prepare_raw(args.input, args.save_log)

    bars = R.load_bars(src, with_indicators=True)
    if args.min_date:
        lo = datetime.strptime(args.min_date, "%Y-%m-%d")
        bars = [b for b in bars if b["dt"] >= lo]
    if args.max_date:
        hi = datetime.strptime(args.max_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
        bars = [b for b in bars if b["dt"] <= hi]
    if len(bars) < R.EMA_SLOPE_LOOKBACK + 5:
        raise SystemExit(f"error: only {len(bars)} bars after filtering - need a warm-up")

    # ---- validation first: reconstruction quality --------------------------
    quality = R.enrich_log(bars)
    print(f"\nbacktest: {len(bars)} M5 bars ({bars[0]['dt']} -> {bars[-1]['dt']}), "
          f"TP {args.tp}xATR, BE {'off' if args.be is None else '+%.2fR' % args.be}, "
          f"horizon {args.horizon}m, spread ${args.spread:.2f}/trade, seed {args.seed}")
    print("reconstruction quality (should be ~100%; if not, distrust everything below):")
    for name, (ok, bad) in quality.items():
        tot = ok + bad
        print(f"    {name:10s} {ok}/{tot} = {100*ok/tot:.1f}%" if tot else f"    {name}: n/a")

    sigs = R.all_signals(bars)
    if args.side != "both":
        want = "BUY" if args.side == "buy" else "SELL"
        sigs = [s for s in sigs if s["side"] == want]
    nb = sum(1 for s in sigs if s["side"] == "BUY")
    ns = len(sigs) - nb
    print(f"\nreconstructed signal stream: {len(sigs)} signals ({nb} BUY / {ns} SELL)")

    # ---- book 1: entry stream (cascade-ignorant) ---------------------------
    stream = walk_stream(sigs, bars, args.tp, args.be, args.horizon)
    print("\n== ENTRY STREAM (every signal, one position ignored - optimistic) ==")
    show("all", book_stats(stream, args.spread, args.boot, rng), args.spread)
    show("BUY", book_stats([r for r in stream if r["side"] == "BUY"], args.spread, args.boot, rng), args.spread)
    show("SELL", book_stats([r for r in stream if r["side"] == "SELL"], args.spread, args.boot, rng), args.spread)

    # ---- book 2: takeable book (cascade = the live risk gates) -------------
    taken, skipped, book = R.cascade(sigs, bars, tp_mult=args.tp, be_trigger=args.be,
                                     horizon_min=args.horizon, daily_halt=TF.MAX_DAILY_LOSSES)
    print(f"\n== TAKEABLE BOOK (one position + escalating SL cooldown + {TF.MAX_DAILY_LOSSES}-SL "
          f"daily halt; taken {taken}, skipped {skipped}) ==")
    show("all", book_stats(book, args.spread, args.boot, rng), args.spread)
    show("BUY", book_stats([r for r in book if r["side"] == "BUY"], args.spread, args.boot, rng), args.spread)
    show("SELL", book_stats([r for r in book if r["side"] == "SELL"], args.spread, args.boot, rng), args.spread)

    # ---- gate read ---------------------------------------------------------
    s = book_stats(book, args.spread, args.boot, rng)
    print("\n== GATE READ (takeable book, net of spread) ==")
    if s is None or s["n"] < 30:
        print("    too few trades to judge - feed a longer history")
    else:
        print(f"    EDGE  day-block bootstrap P(net/trade>0) = {100*s['p_day']:.0f}% "
              f"(gate >= 90%)  -> {'PASS' if s['p_day'] >= LR.MIN_P_EDGE else 'FAIL'}")
        if args.spread:
            print(f"    COST  break-even/assumed cover = {s['cover']:.2f}x "
                  f"(gate >= {LR.MIN_SPREAD_COVER:.1f}x)  -> "
                  f"{'PASS' if s['cover'] >= LR.MIN_SPREAD_COVER else 'FAIL'}")
        frag = (f"top-5 trades = {100*s['top5']:.0f}% of net"
                if s['top5'] is not None else f"best-5 trades ${s['top5_d']:+.2f} (net<=0)")
        print(f"    FRAGILITY {frag}; "
              f"second-half net {s['second']:+.2f} (negative = recent-form concern)")
    print("\nREMINDER: M5 reconstruction, not tick-resolved; a back-test cross-check, "
          "NOT a live expectation or a go-live substitute.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
