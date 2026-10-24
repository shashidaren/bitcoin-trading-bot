# REVIEW 2026-10-18 — BTC dashboard pressure and engine audit

## Scope and history

This follow-up reviews the dashboard pressure feature merged in PR #21 on
2026-10-17 (`Add BTC tape pressure dashboard read`), using
`docs/HANDOFF.md` and `docs/ANALYSIS-2026-10-17-dashboard-pressure.md` as the
baseline. The review covers the display-only pressure/location cards, the
forward-test engine paths, and current ledger/status consistency. It does not
retune or change any entry, exit, sizing, or portfolio-risk rule.

Current local data: 169 closed trade rows, 11,554 logged M5 bars through
2026-10-18 16:35:14 UTC, and 196 skip rows. The code still defaults to
`TRADING_MODE = FORWARD_TEST` and `DATA_SOURCE = TWELVEDATA`; no broker order was
sent. The optional MT5 sidecar path is reviewed with fakes/smoke tests only.

## Findings and actions

### 1. Pressure read is descriptive and bounded; keep it out of the trade funnel

The five weighted components sum to 100%, BUY and SELL are complementary, and
the 20-bar location calculation excludes the candle being evaluated. The
latest local reading is **BUY 18.9% / SELL 81.1%** as of 2026-10-18 16:35:14 UTC.
This is one snapshot, not a forecast or win probability. The momentum, EMA trend,
and EMA slope components are sharply bearish in this window; the flow input is
only the feed's tick-count proxy, not exchange BTC volume. The strategy's own
EMA gates can make the score restate which side is eligible.

The historical join still uses the last log bar strictly before each entry and
makes no threshold/bucket claim: BUY n=62, score min/median/max
49.7/73.8/84.8; SELL n=53, 15.7/27.8/44.9. A small reporting bug used the upper
middle element as the median for even sample sizes; it now uses the conventional
average of the two middle values. The displayed dashboard score is unchanged.

### 2. Dashboard closed-trade cards could disagree with the ledger

At this snapshot `status.json` says 70 wins / 99 losses while the 169 rows in
`trades.csv` contain 69 TP / 100 SL outcomes. The dashboard previously showed
the stale JSON counters without warning. It now derives closed-trade count,
wins, losses, and win rate from the read-only ledger on each render; when those
counters differ, it shows an amber notice. It does **not** write or repair
`status.json` and does not change the engine's in-memory balance or gates. The
current dashboard therefore displays 69/100 (40.8%) and flags the stale JSON.
The equity card is now labeled **Engine Ledger Balance** and explicitly says
that it is an internal balance, not all-time P/L; it still shows the existing
`status.json` value and does not silently reconstruct or rewrite it.

The daily-loss state is consistent: the ledger has **3 UTC-day SLs** on
2026-10-18, `status.json` reports 3/3, and the filter's pure breaker check
returns `Daily Loss Limit Reached (3/3 SLs today) - Trading Halted`. This is
expected behavior, not a dashboard or engine fault.

### 3. Optional MT5 forward-test stale-feed watchdog could be bypassed

In `run_mt5_test()`, both the missing-file and unchanged-candle paths slept and
`continue`d before reaching the stale-feed check. Consequently, a crashed
sidecar or frozen JSON candle could leave the MT5 runner retrying forever without
the promised stale-feed alert. The watchdog now runs on every loop, checks the
UTC age of a readable closed candle, falls back to a monotonic startup/last-bar
timer when the file is missing, and rate-limits the alert with an MT5-specific
recovery message. Stale candle data is not evaluated.

### 4. MT5 restart dedup compared bar-open time to a bar-close watermark

MT5 `rates[0]["time"]` is the candle's **open** timestamp, while the engine log
watermark was a processing/close timestamp. Reusing the log value directly as
an open-time watermark could reject the immediately following M5 candle after a
restart. MT5-accepted bars now log the exact UTC close boundary, and dedup
compares `open_ts + 300 seconds` with the last logged close. Regression coverage
checks that the just-processed candle is rejected but the next candle is not.

This is an offline code/test fix only. The optional MT5/XM sidecar has not been
verified on the host; deploy/restart and verify the first post-deploy JSON before
using `DATA_SOURCE=MT5` (per the operations checklist in HANDOFF §3 and
`docs/START-LEVER1.md`).

## Current trading-readiness read

`tools/live_readiness.py --spread 0.40` reports 111 strictly post-gate trades
(44W/67L, 39.6%), +$16.34 net (+$0.15/trade), t=+0.54, and a 68% calendar-day
bootstrap probability of positive mean. Break-even round-trip cost is about
$0.55 (1.4x the assumed $0.40), best-five removal leaves −$14.19, and the last
25 are −$7.82 net. Only **2/6** data gates pass (sample and feed); edge, cost,
fragility, and recent form still fail. The live order-path probe remains **1/9**
clean (4 BLOCKER, 3 HIGH, 1 ADVISORY). Keep `TRADING_MODE = FORWARD_TEST`; do
not enable real-money orders.

`tools/check_data.py` reports 0 failures / 66 warnings. The known ledger drift
remains: engine balance $268.54 vs reconstructed $−128.33 from the $200 start
before costs, a $396.87 gap from historical sizing outliers/resets/reconciliation
residue. No historical rows or `status.json` were rewritten for this review.

## Verification

- `python3 -m py_compile engine.py dashboard.py pressure.py tools/smoke_test.py` — pass.
- `python3 tools/smoke_test.py` — pass, including updated MT5 stale-feed / restart
  dedup checks and pressure-median / ledger-summary checks.
- Flask test client with local CSV/JSON paths — HTTP 200; both pressure/location
  panels render; pressure is 18.9/81.1; closed-trade cards use 69W/100L, the
  mismatch warning is present, and the balance card is labeled as internal.
- `python3 tools/check_data.py` — 0 failures, 66 expected/informational warnings.
- `python3 tools/live_readiness.py --spread 0.40` — 2/6 data gates; NOT READY.
- `python3 tools/live_path_probe.py` — 1/9 clean; LIVE PATH NOT READY (expected
  nonzero exit because blockers remain).
- `python3 tools/pressure_report.py --log forward_test_log.csv --trades trades.csv`
  — read-only report; pressure remains context-only.

No strategy or readiness conclusion changed. Full project state and current
numbers are in `docs/HANDOFF.md`.
