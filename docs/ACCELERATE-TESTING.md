# ACCELERATE-TESTING — Fast Large-N `US100Cash` M15 Backtesting

Waiting in real time for hundreds of closed `M15` forward-test trades takes months. Two mechanisms in the `US100Cash` stack remove that wait without loosening any statistical gate:

## 1. Zero-Wait Live Indicator Warm-Up (`mt5_warmup_candles.json`)

200 `M15` candles equal **50 trading hours** (~2.2 trading days). Instead of sitting cold after a fresh deploy:
- `tools/mt5_feed.py` exports the latest **250 closed `M15` bars** to `/opt/nasdaq/mt5_warmup_candles.json` on startup (and refreshes every 6 hours).
- `engine.py` (`load_warmup_from_mt5()`) ingests those bars on boot whenever `forward_test_log.csv` has fewer than 200 rows, warming `EMA200`, `EMA50`, `EMA50` 12-bar slope, `RSI(14)`, `ATR(14)`, and the 20-bar floor/ceiling **on minute zero**.

## 2. 12,000-Bar (~6-Month) XM M15 Historical Backtest

On its very first cycle, `tools/mt5_quotes.py` (`mt5quotes-nasdaq.service`) backfills up to **12,000 closed `US100Cash` `M15` bars** (~180 trading days / ~6 months) directly from the XM terminal into `xm_data/candles_m15.csv`.

Run the exact frozen engine gates + live risk cascade (`1` position at a time, `30m/60m` escalating SL cooldown, `3`-SL daily halt) across that entire 6-month history in seconds:

```bash
# Direct one-step backtest on xm_data/candles_m15.csv at $0.25/trade (0.10 lot):
python3 tools/backtest.py xm_data/candles_m15.csv --spread 0.25 --save-log bt_us100_m15.csv

# Verify indicator reconstruction faithfulness (should report ~100% agreement):
python3 tools/history_to_log.py forward_test_log.csv --selfcheck
```

Remember (`docs/HANDOFF.md` §7): `tools/backtest.py` accelerates the **statistical edge & spread-cover cross-check** on M15 OHLC; Stage B live demo execution soak (`docs/START-LEVER1.md`) is still mandatory to validate broker fills before real-money cutover.
