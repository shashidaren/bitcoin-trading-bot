"I'm working on my Bitcoin trading bot. Here is my project log: [paste the contents of PROJECT_LOG.md]. Currently, I want to work on [X]."

> **New sessions should start from `docs/HANDOFF.md`** (the executive summary:
> current state, gates, evidence base, next steps, data gotchas). This file is
> the long-form history behind it.

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
- **[2026-09-15] First data review + tooling cycle** (`docs/REVIEW-2026-09-15.md`).
  Written after reading gold's 2026-09-15 review (BE ratchet 0.30→0.75R) and
  re-testing every gold-derived queued item on BTC data. Findings: (1) the gross
  forward-test edge is **+$11.74 over 71 trades ≈ +$0.17/trade — inside the
  published XM BTCUSD spread of $0.225–0.60/trade at 0.01 lot**, i.e. the cost is
  the dominant term and must be measured before any cost-sensitive tuning;
  (2) the ATR%≥0.06 filter is a **calendar proxy** (own-day control collapses to
  n=4 and flips sign) and the ATR%<0.02 churn bucket is pre-era only → reject
  ATR-floor-by-win-rate, keep the cost-ratio form; (3) gold's **RSI≥45 does not
  transfer** (own-day 22.0% −$28.32 vs skip 29.4%); (4) **BE ratchet stays
  unadopted** — tight triggers lose in both views, best row +1.0R is ~2 trades of
  noise, and gold's adopted 0.75R is the *worst* row on BTC; (5) the
  09-11→09-14 collapse is **regime** (09-12: 15×ATR range, ATR $29, all 21
  census signals stopped; 09-14: 26×ATR whipsaw); (6) the 3-SL daily halt is
  **protective** (phantom −$4.93) while the **cooldown's cost is still
  unmeasured** (4 of 37 blocks scorable). New tooling: shared `tools/replay_lib.py`
  walk core (validated 19/19 against the engine) + `win_rate_report.py`,
  `pathwalk_sims.py`, `analyze_losers.py`, rewritten `phantom_trades.py`,
  geometry-era + bar-census checks in `check_data.py`, `smoke_test.py`
  Scenario I (walk-direction lock), and a `DAY_WINDOW=400` fix so the
  daily-loss breaker can see busy days.
- **[2026-09-10] `docs/HANDOFF.md` added** — executive-summary handoff doc ported from `gold-trading-bot/docs/HANDOFF.md`, rewritten against actual BTC state (61 trades, 7 post-port). Records the evidence base (RSI/ATR%/gate-replay/phantom findings), the queued gold changes that are deliberately NOT adopted yet (BE ratchet, direction-aware London, RSI<45 filter), and the data gotchas (09-03 sizing outliers, Trade_Num resets, log starting 09-07 20:20 UTC). §10 defines the per-session update ritual so changes stay tracked.
- **[2026-09-10] Gold-lessons port** (see `docs/PORT-2026-09-10.md`): bidirectional SELL funnel; EMA-slope + near-EMA regime gates; daily-loss circuit breaker + escalating cooldowns; expanded blackouts; UTC timestamps everywhere (fixes local-time/cooldown mismatch); trade-stats reload + open-trade restore on restart; 16-field `trades.csv` with `Trade_Type` + self-healing migration + drift tripwire; plain (non-comma) price formatting for new rows; stale-feed guard with Telegram alerts (no quiet hours - BTC is 24/7); `DATA_SOURCE=MT5` broker-feed option (M5 sidecar); LIVE mode dedups MT5 candles + supports SELL orders; dual-funnel dashboard with daily-loss tracking; new `tools/` suite (`check_data`, `validate_gates`, `phantom_trades`, `smoke_test`, `mt5_feed`, `autosync`); data files now tracked in git for reviews; retired `generate_trades.py` to `archive/` (stale params, overwrote the ledger).
- **[2026-09-07] Pre-port state**: BUY-only M5 engine, flat 30-min SL cooldown, narrow blackouts, %-based ATR filter, basic dashboard on port 6001. Strategy params (wick 0.15, RSI 40-70, RR 1:2) unchanged by the port.

## Forward Test Observations
- **73 closed trades total (30W/43L); ledger $208.74, true equity -$183.10.** The two 2026-09-03 trades (-197.63, -197.21) ran under a broken pre-port sizing setup - exclude them from every statistic. From 09-05 on: 71 trades, 30W/41L, **+$11.74 gross**; the ledger has **no cost model**, so every figure is gross.
- **Ledger geometry changed 09-06 17:49 UTC** (1.5x/2.5x -> 2x/4x ATR). Pre: n=37, 40.5%, -$393.62 (-199.6R). Post: n=36, 41.7%, +$10.52 (+8.3R). Never pool R totals or breakeven WRs across that line.
- **Live-era sample = 19 trades (from 09-09 02:25 UTC): 7W/12L, +$8.73 gross.** Last 10: 1W/9L, -$9.98. R-multiples clean (+2R / -1R; the two -1.38R rows are fast-move tick timing). Far below the n>=30 bar - do not retune on it.
- **Cost is the dominant term**: +$0.17/trade gross (n=71) vs published XM BTCUSD spread $0.225-0.60/trade at 0.01 lot = 0.13-0.35R at live ATR. Reducing cost (tighter-spread account) or trading only large-ATR signals beats any filter found so far. See `win_rate_report.py` §8.
- **Filters tested and closed**: ATR%>=0.06 rejected (calendar proxy; own-day control n=4, sign flips; churn bucket is pre-era only). RSI>=45 rejected (own-day 22.0% vs 29.4%). Two candidates survive the own-day control but need n>=30: wick <=0.40 (own-day keep 37.0% +$13.40 vs skip 20.0% -$17.23) and near-EMA <=0.15 ATR (own-day keep 62.5% +$13.18, n=8).
- **BE ratchet not adopted**: tight triggers lose; best row +1.0R beats "off" by $2.71 on 29 cascade trades. Gold's 0.75R is BTC's worst row. Re-open at 30+ live trades.
- Cooldown blocks 37 of 70 skipped signals but its cost is **still unmeasured** (only 4 scorable; the log starts 09-07 20:20 UTC). Daily-halt phantoms (18, all scorable) are 3W/15L = -$4.93 -> the breaker is protective. Biggest open question unchanged.
- No reviewed trade data yet under the new stack. First `docs/REVIEW-*.md` after real trades land.
- `archive/forward_test_log_m1.csv` (8,537 rows, Sep 1) is M1-cadence data from an earlier setup - NOT comparable to the current M5 log. Do not mix the two in analysis.

## Future Tweaks / To-Do
- [x] First data review (73 trades) -> `docs/REVIEW-2026-09-15.md`.
- [ ] **Measure the real XM BTCUSD spread** (MT5 spec + tick sample) - blocks every cost-sensitive decision.
- [ ] Log the wick/near-EMA feature per signal (monitor-only) and re-read at 30+ live-era trades.
- [ ] Validate regime-gate + SELL-mirror parameters against BTC data (currently inherited from gold's review, unproven on BTC).
- [ ] Revisit `WICK_RATIO_TARGET` 0.15 (loose vs gold's 0.38) once the funnel counters show signal quality.
- [ ] Confirm `SYMBOL_MT5` (`BTCUSD` vs `BTCUSDm`) and contract size on the XM terminal before any LIVE test.
- [ ] Multi-Timeframe (15m/1h) higher-timeframe trend integration.
- [ ] Live spread filter check before order dispatch.
