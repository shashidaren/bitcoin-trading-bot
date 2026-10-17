#!/usr/bin/env python3
"""CLI view of the dashboard's read-only BTC tape-pressure composite."""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import pressure  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", default=pressure.LOG_FILE_PATH, help="forward_test_log.csv path")
    parser.add_argument("--trades", default=pressure.TRADES_FILE_PATH, help="trades.csv path")
    args = parser.parse_args()

    rows = pressure.read_rows(args.log)
    trades = pressure.read_rows(args.trades)
    read = pressure.pressure(rows[-500:])
    print("BTC M5 tape-pressure read (descriptive only; not a signal or probability)")
    if read is None:
        print(f"Not enough usable history in {args.log!r}; need at least {pressure.PRESSURE_WINDOW + 1} valid bars with indicators.")
    else:
        print(f"As of {read['as_of']} | {read['window']} closed bars (~{read['window'] * 5 / 60:g} hours)")
        print(f"BUY {read['buy_pct']:.1f}% | SELL {read['sell_pct']:.1f}% | {read['label']}")
        print("Components (raw input; buy-share; weight; weighted points):")
        for item in read["components"]:
            print(f"  {item['label']:<30} {item['raw']:>7} {item['unit']:<26} "
                  f"buy-share {item['buy_pct']:5.1f}% × {item['weight']:.2f} = {item['contribution']:5.1f}")

    print("\nHistorical readings at the last logged bar strictly before each entry")
    print("(gross ledger Profit; descriptive only, no calibrated buckets):")
    for side, item in pressure.calibrate(rows, trades).items():
        if not item["n"]:
            print(f"  {side}: no usable joined entries")
            continue
        print(f"  {side}: n={item['n']}, buy-pressure min/median/max="
              f"{item['score_min']:.1f}/{item['score_median']:.1f}/{item['score_max']:.1f}, "
              f"wins/losses={item['wins']}/{item['losses']}, gross Profit=${item['gross_profit']:+.2f}")
    print("\nCaution: EMA trend and slope are already strategy gates; the score can restate trade side. "
          "Volume is tick-count proxy, not exchange-traded BTC volume. Do not use it to gate or size trades.")


if __name__ == "__main__":
    main()
