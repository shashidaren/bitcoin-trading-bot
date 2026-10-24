# BTC dashboard tape-pressure read — 2026-10-17

## Purpose and boundary

This is a **display-only** read layer, adapted from the gold bot's
`pressure.py` / `docs/ANALYSIS-2026-10-16-dashboard-pressure.md`. It adds a
BTC Buy/Sell Tape Pressure panel and a 20-bar price-location panel to
`dashboard.py`, plus the CLI mirror `tools/pressure_report.py`.

Nothing in this change imports `pressure.py` from `engine.py` or
`trade_filter.py`; no signal, gate, execution, sizing, or risk parameter changed.
The gauge is not a probability, entry/exit signal, or evidence of edge. EMA50
trend and slope are already part of the BTC entry funnel, so a high BUY / low
BUY-pressure reading may simply restate the side the strategy permits. Do not
use this panel to veto or size trades.

## Definition of the composite

Window: the latest **60 logged closed M5 bars** (about five hours). The
components and weights are fixed in `pressure.py` and displayed individually so
the score is reproducible:

| Component | Raw value | Buy-share transform | Weight |
|---|---|---|---:|
| Candle flow | `Σ ((close−open)/(high−low)) × tick_count / Σ tick_count` | `(flow + 1) / 2` | 0.30 |
| Momentum | `(close_now − close_60_bars_ago) / ATR` | `logistic(momentum / 1.5)` | 0.20 |
| Trend | `(EMA50 − EMA200) / ATR` | `logistic(trend / 0.5)` | 0.20 |
| EMA50 slope | `(EMA50_now − EMA50_30_bars_ago) / ATR` | `logistic(slope / 0.5)` | 0.15 |
| RSI posture | RSI(14) | `clip((RSI − 30) / 40, 0, 1)` | 0.15 |

`BUY pressure = 100 × weighted sum(buy-shares)`; `SELL pressure = 100 − BUY`.
The first input is the log's **tick-count volume proxy**, not exchange-traded BTC
volume. The dashboard retains the raw component values, the component buy-share
bars, and the weights; the total is just a weighted descriptive index.

The location card reconstructs the floor and ceiling from the **previous 20
bars**, excluding the current candle in the same manner as `engine.py`. It also
shows distance in ATR and warns if the reconstructed floor differs from the
logged floor. It does not claim the complete setup would pass: the log does not
persist all post-update indicator values or every SELL-side funnel flag.

## BTC ledger cross-check (descriptive, no chosen buckets)

`tools/pressure_report.py` uses the last logged row **strictly before** each
entry timestamp, then reports the per-side observed score range. This avoids
using an entry-minute candle as a pre-entry feature. On the local snapshot
through 2026-10-17 15:35 UTC (112 log-covered live-geometry trades):

| Side | Joined trades | Buy-pressure min / median / max |
|---|---:|---:|
| BUY | 60 | 49.7 / 73.8 / 84.8 |
| SELL | 52 | 15.7 / 27.9 / 44.9 |

The score is strongly separated by trade side in this sample, which is expected
because the strategy itself gates side by EMA trend and slope. This is **not** a
within-side outcome calibration: no thresholds were selected, no buckets are
claimed, and no causal or predictive interpretation is warranted. A proper
predictive claim would need a pre-specified BTC-specific analysis and out-of-
sample validation. The join is also limited by the existing M5 log cadence and
the engine's logged indicator timing.

## Operations and verification

- Dashboard: existing Flask page at port 6001; deploy/restart the dashboard only.
  The engine and live state are not touched.
- Local paths can be selected with `BTC_DATA_DIR`, `BTC_LOG_FILE`, and
  `BTC_STATUS_FILE` (defaults remain `/opt/bitcoin/*` in production).
- CLI: `python3 tools/pressure_report.py` (or pass `--log` and `--trades`).
- Regression coverage: smoke Scenario N checks mirrored BTC constants, score
  bounds/complement, level lookback, strict pre-entry calibration, and that the
  module remains stdlib-only/read-only.
- No engine parameters, gates, data, or LIVE readiness verdict were changed by
  this feature. Keep `TRADING_MODE = FORWARD_TEST` as before.
