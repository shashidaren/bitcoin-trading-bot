"I'm working on my Bitcoin trading bot. Here is my project log: [paste the contents of PROJECT_LOG.md]. Currently, I want to work on [X]."

# Bitcoin Engine - Development & Strategy Log

## Architecture Overview
The bot is split into two distinct files to separate signal generation from risk management:
1. **`engine.py`**: Handles data ingestion (Twelve Data / MT5), indicator calculation (EMA, RSI, ATR), and price-action signal generation (The "Funnel", long + short).
2. **`trade_filter.py`**: Acts as the final portfolio-level gatekeeper. Checks session blackouts, escalating SL cooldowns, the daily-loss circuit breaker, and %-based ATR bounds before allowing execution.

Medium-term design: ticks are aggregated into **M5 (5-minute)** candles. All indicator lookbacks, the slope gate, and the log cadence are in M5 bars.

## Current Strategy Rules (The Funnel)
For a BUY signal to trigger, ALL of the following must be true:
1. **Tested Floor**: Price drops to the 20-candle low (with 0.15% buffer).
2. **Valid Rejection**: Lower wick is >= 15% of the total candle range.
3. **Held Support**: Candle closes *above* the dynamic floor.
4. **Trend Confirmed**: EMA 50 > EMA 200 (Uptrend only).
5. **Slope Confirmed**: EMA 50 rising vs 30 M5 bars ago (regime gate).
6. **Near Mean**: Close >= EMA50 - 0.3 x ATR (regime gate).
7. **RSI Filter**: RSI is between 40.0 and 70.0.
8. **ATR Filter**: ATR > 0 (engine floor disabled; %-based bounds enforced in `trade_filter.py`).
9. **Trade Filter**: Passes `trade_filter.py` checks (no blackouts, no SL cooldown, daily-loss breaker not tripped).

SELL is the mirror: 20-bar ceiling test, upper-wick rejection >= 15%, close below ceiling, EMA50 < EMA200, EMA50 falling, close <= EMA50 + 0.3 x ATR, RSI between 30.0 and 60.0.

Risk geometry: SL = entry -/+ 2.0 x ATR, TP = entry +/- 4.0 x ATR (RR 1:2, breakeven WR ~33%). Simulated PnL is scaled by LOT_SIZE (0.01).

## Current Parameters
### engine.py
- `LOOKBACK_PERIOD` = 20
- `WICK_RATIO_TARGET` = 0.15
- `EMA_FAST` = 50, `EMA_SLOW` = 200
- `FLOOR_BUFFER_PCT` = 0.0015
- `ATR_SL_MULT` = 2.0, `ATR_TP_MULT` = 4.0
- `REQUIRE_VOLUME_CONFIRM` = False
- `REQUIRE_TREND_CONFIRM` = True
- `REQUIRE_EMA_SLOPE` = True, `EMA_SLOPE_LOOKBACK` = 30, `MAX_BELOW_EMA_ATR` = 0.30
- `RSI_MIN` = 40.0, `RSI_MAX` = 70.0 (SELL mirrors to 30.0-60.0)
- `MIN_ATR` = 0.0 (filter-level %-bounds apply instead)
- `CANDLE_SECONDS` = 300 (M5)
- `STARTING_BALANCE` = 200.00, `LOT_SIZE` = 0.01, `MAGIC_NUMBER` = 987655
- `STALE_FEED_SECONDS` = 600, `STALE_ALERT_COOLDOWN_SECONDS` = 1800

### trade_filter.py
- `SL_COOLDOWN_BASE_MINUTES` = 30, `SL_COOLDOWN_ESCALATED_MINUTES` = 60 (after 2 consecutive SLs)
- `MAX_DAILY_LOSSES` = 3 (UTC day)
- `MIN_ATR_PERCENT` = 0.0001 (0.01%), `MAX_ATR_PERCENT` = 0.0060 (0.60%)
- **Blackouts (UTC)**: London Open (07:55-09:00), NY Pre-Market (12:25-12:45), NY Open & US Macro (13:25-15:15). No rollover window - BTC trades 24/7.

## Changelog & Recent Fixes
- **[2026-09-10] Gold-lessons port** (see `docs/PORT-2026-09-10.md`): bidirectional SELL funnel; EMA-slope + near-EMA regime gates; daily-loss circuit breaker + escalating cooldowns; expanded blackouts; UTC timestamps everywhere (fixes local-time/cooldown mismatch); trade-stats reload + open-trade restore on restart; 16-field `trades.csv` with `Trade_Type` + self-healing migration + drift tripwire; plain (non-comma) price formatting for new rows; stale-feed guard with Telegram alerts (no quiet hours - BTC is 24/7); `DATA_SOURCE=MT5` broker-feed option (M5 sidecar); LIVE mode dedups MT5 candles + supports SELL orders; dual-funnel dashboard with daily-loss tracking; new `tools/` suite (`check_data`, `validate_gates`, `phantom_trades`, `smoke_test`, `mt5_feed`, `autosync`); data files now tracked in git for reviews; retired `generate_trades.py` to `archive/` (stale params, overwrote the ledger).
- **[2026-09-07] Pre-port state**: BUY-only M5 engine, flat 30-min SL cooldown, narrow blackouts, %-based ATR filter, basic dashboard on port 6001. Strategy params (wick 0.15, RSI 40-70, RR 1:2) unchanged by the port.

## Forward Test Observations
- No reviewed trade data yet under the new stack. First `docs/REVIEW-*.md` after real trades land.
- `archive/forward_test_log_m1.csv` (8,537 rows, Sep 1) is M1-cadence data from an earlier setup - NOT comparable to the current M5 log. Do not mix the two in analysis.

## Future Tweaks / To-Do
- [ ] First data review once ~20+ trades close under the new stack (write `docs/REVIEW-YYYY-MM-DD.md`).
- [ ] Validate regime-gate + SELL-mirror parameters against BTC data (currently inherited from gold's review, unproven on BTC).
- [ ] Revisit `WICK_RATIO_TARGET` 0.15 (loose vs gold's 0.38) once the funnel counters show signal quality.
- [ ] Confirm `SYMBOL_MT5` (`BTCUSD` vs `BTCUSDm`) and contract size on the XM terminal before any LIVE test.
- [ ] Multi-Timeframe (15m/1h) higher-timeframe trend integration.
- [ ] Live spread filter check before order dispatch.
