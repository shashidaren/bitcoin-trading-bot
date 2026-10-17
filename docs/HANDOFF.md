# HANDOFF — read this first in a new session

Paste this file at the start of a new session:
> "I'm working on my Bitcoin trading bot. Here is the handoff: [paste docs/HANDOFF.md]. I want to work on [X]."

This is the **executive summary** of the whole project — the BTC twin of
`gold-trading-bot/docs/HANDOFF.md`. It carries *conclusions and pointers*; the
analysis behind them lives in `docs/REVIEW-*.md`. Keep it current: every session
that changes code, params, or conclusions must update the snapshot block, §1,
§4/§5 and §7 before it ends (§10 — "How to keep this file honest"). §10 also
carries the **Session & Push Protocol**: push every commit immediately and keep
the session PR open until the user signs off.

**Numbers convention (read this before quoting anything below).** Every P/L in
this file is **net of the measured $0.40 round trip** unless the word **gross**
is right next to it. The ledger itself models no cost at all, so a number copied
out of `trades.csv` is always gross. Never quote a pooled R total or a breakeven
win rate across the 2026-09-06 17:49 UTC geometry change (§9).

<!-- HANDOFF-SNAPSHOT machine-checked by tools/handoff_check.py; refresh with --update -->
| key | value |
|---|---|
| as_of_utc | 2026-10-17 15:35 |
| data_collection | 3531 |
| closed_trades | 166 |
| wins_losses | 69W/97L |
| win_rate_pct | 41.6 |
| engine_ledger_usd | 274.49 |
| true_equity_usd | -122.39 |
| live_era_trades | 112 |
| live_era_net_usd | +24.64 |
| log_covered_trades | 112 |
| log_bars | 11254 |
| log_last_bar_utc | 2026-10-17 15:35 |
| skip_rows | 190 |
| open_trade | SELL #165 @ 81506.35 |
| spread_usd_per_trade | 0.40 |
<!-- /HANDOFF-SNAPSHOT -->

The block above is the only part of this file that is **machine-checked**:
`python3 tools/handoff_check.py` recomputes every key from the live CSVs and
says `HANDOFF FRESH` or `HANDOFF STALE`; `--update` rewrites the block in place.
`tools/autosync.sh` prints the verdict in its Telegram digest, so a drifting
handoff announces itself instead of being discovered three sessions later.
Everything below the block is prose and is only as honest as the last person who
edited it — that is what §10's ritual is for.

---

## 1. Where things stand (local data through 2026-10-17 15:35 UTC; **166 closed trades, open SELL #165; readiness re-read 2026-10-17**)

> **RESOLVED 2026-10-05 — simulated BUY #125 reconciled from the OHLC path (NOT a guessed fill).** #125 (BUY, entry 2026-10-01 07:10:10 @ $84,177.15, SL $84,008.74, TP $84,513.98) had been force-closed in `trades.csv` as a *guessed* TP at the target with a wall-clock `Exit_Time` (2026-10-05 03:50:10, +$3.37) — exactly the "append a guessed close" the 2026-10-05 review forbids. It is now **explicitly reconciled from the ordered closed-candle OHLC path** under the same conservative convention as the MT5 forward-test fix (`engine.check_position_on_closed_candle`): the 07:15:11 candle touched neither barrier (low $84,035.75 > SL), and the 07:20:11 candle's low $83,838.25 ≤ SL with high $84,076.35 < TP, so the **first recorded barrier is the stop**; that bar opened at $84,034.75 (not through the stop), so it fills at the stop level. Reconciled exit: `Exit_Time` 2026-10-01 07:20:11, `Exit_Reason` SL, `Exit_Price` 84008.74, `Profit` −1.68, `Balance_After` 257.13. The entry candle's own range was not applied. Applied with `tools/reconcile_stale_trade.py` (report-only by default; `--apply` backs up `trades.csv`/`status.json` first). `status.json` now reads 126 closed, 54W/72L (42.9%), equity $257.13, `trade_active=false`, `next_trade_num=126`. This supersedes the "active #125" state in the 2026-10-05 review; that review's historical investigation stands, its exit-state finding does not.

- Repo: `shashidaren/bitcoin-trading-bot`, default branch `main`. Work happens on
  the **session branch** (`arena/<session>-bitcoin-trading-bot`) — read it with
  `git branch --show-current`; do not trust a branch name written into this file,
  because a new session gets a new one. Data flows **up** `main` (autosync commits
  it every 15 min); code flows **down** `main` only, so a session's work reaches
  the live box only when its PR merges.
- **The gold→BTC port is live** (deployed 2026-09-10, `docs/PORT-2026-09-10.md`):
  SELL funnel, EMA-slope + near-EMA regime gates, escalating SL cooldowns,
  daily-loss breaker, UTC everywhere, self-healing 16-field ledger, stale-feed
  guard, MT5 sidecar option, `tools/` suite.
- **Reviews:** `docs/REVIEW-2026-10-09.md` is the latest — the 141-trade
  win-rate re-read and the go-live timing check. `docs/REVIEW-2026-10-05.md` is the exit-state recheck (125 closed ledger rows plus the then-active #125, which has since been reconciled — see the RESOLVED note below). `docs/REVIEW-2026-10-01.md`
  remains the full live-readiness review and staged path; its detailed data
  snapshot is historical. `docs/REVIEW-2026-09-15.md` §13 is the 99-trade
  historical re-cut (§12 the 78-trade one).
- **Current session (2026-10-17):** added a display-only BTC tape-pressure read
  and previous-20-bar location card to `dashboard.py`, with the read-only
  `pressure.py` library, `tools/pressure_report.py`, regression Scenario N and
  `docs/ANALYSIS-2026-10-17-dashboard-pressure.md` (§8). It changes no engine
  parameters, entry/risk gates, state, or LIVE-readiness conclusion. The handoff
  snapshot/prose were refreshed to 166 closed rows / 11,254 bars; the readiness
  re-read is 108 post-gate trades, 2/6 data gates, still NOT READY. The score is
  explicitly contextual: EMA trend/slope repeat existing side gates, and flow
  uses tick-count proxy rather than exchange volume. **Outstanding decision for
  the user remains:** approve starting Stage A (order-path PR) and installing the
  XM logger sidecar — those are the calendar levers for any future micro-live (§7).
- **Continuation session (2026-10-13, PR #20):** docs-only again — added
  **`docs/START-LEVER1.md`**, the ready-to-run runbook for exactly that decision
  (Part A: logger pre-checks → dry `--spec` → scratch-dir cycle → install as
  `mt5quotes-btc` → the ≥14-day/2-weekend clock + the Oct-25 DST note; Part B:
  the Stage A findings table with current `engine.py` line refs + kill
  switches; Part B.1: the Wine order-executor intent/result/positions
  contract, idempotency, guards, reconcile-on-start), linked from §7. No code,
  params, gates, or conclusions changed. Re-verified on this checkout:
  `history_to_log.py --selfcheck` FAITHFUL at 10,081 bars; `backtest.py` at
  100% reproduction corroborates the 36-day read (entry-stream WR 34.6%,
  takeable-book cost cover 1.00×, EDGE/COST FAIL); `live_path_probe.py` still
  1/9 (4 BLOCKER / 3 HIGH / 1 ADVISORY). **To continue Stage A or the logger
  install, start from `docs/START-LEVER1.md`** (on `main` once PR #20 merges;
  runbook improvements belong in new PRs against it).

**LIVE verdict (2026-10-17 readiness re-read): still not ready.** Strictly
post-gate sample is **108 trades** (44W/64L, 40.7%), net +$0.22/trade after
$0.40 cost, t = +0.78 and a 76% day-block bootstrap probability of positive
mean. Best 5 trades are **130% of net** (net is negative without them); last 25
are net −$3.23. Estimated break-even round trip is about **$0.62 vs $0.40
assumed (1.5×)** — cost gate still FAIL. **2/6** data-readiness gates pass
(sample and feed). LIVE order-path probe remains 1/9 clean (4 BLOCKER, 3 HIGH,
1 ADVISORY); **Stage A has not started and the XM logger has not been installed
(0/14 days)**. The prior early-to-mid December micro-live estimate was based on
older data and is not revalidated here. Keep `TRADING_MODE = FORWARD_TEST`; do
not enable real-money orders.

### The book in one table (net of $0.40/trade; gross in brackets; refreshed 2026-10-17)

| Slice | n | W/L | WR | net | gross | net/trade |
|---|---:|---:|---:|---:|---:|---:|
| from 09-05 (exclude the 09-03 sizing outliers) | 164 | 69/95 | 42.1% | **+6.85** | [+72.45] | +0.04 |
| live geometry (≥09-06 17:49, RR 1:2) | 129 | 54/75 | 41.9% | +19.63 | [+71.23] | +0.15 |
| "new regime" (≥09-09 02:25, tool boundary) | 112 | 46/66 | 41.1% | **+24.64** | [+69.44] | +0.22 |
| **strictly post-gate (≥09-10)** | 108 | 44/64 | 40.7% | **+23.48** | [+66.68] | +0.22 |
| last 25 closed | 25 | 9/16 | 36.0% | -3.23 | [+6.77] | -0.13 |
| last 10 | 10 | 4/6 | 40.0% | +2.76 | [+6.76] | +0.28 |

The slices overlap. The 112-trade post-port slice includes four 09-09 rows before
the gates actually went live; use the 108-trade ≥09-10 slice when judging today's
gates. Do not use a pooled R total or one pooled breakeven rate across the 09-06 17:49 geometry change. Re-run `tools/win_rate_report.py --spread 0.40` for exact refreshed slices.

The raw Profit column sums to **−$322.39 gross** across all 166 closed rows, giving a ledger reconstruction of **−$122.39 from the $200 start before spread costs**. The engine ledger reads **$274.49**; the gap remains the known 09-03 sizing monsters plus pre-port balance resets and residual reconciliation artifacts. Exclude the two outliers from every strategy P/L statistic. The clean 09-05-on book (164 trades) is **+$72.45 gross / +$6.85 net** at the measured $0.40 round trip.

### What changed since the 2026-10-13 snapshot (157 → 166 closed rows; 10,081 → 11,254 M5 rows, +1,173)

1. **Nine additional closes; the current open position is SELL #165.** The strictly post-gate sample grew 99 → **108**, clearing the sample-count gate.
2. **The edge remains unproven.** Post-gate n=108: 44W/64L, 40.7%, +$66.68 gross / +$23.48 net, t=+0.78, day-block bootstrap 76% positive. Cost cover is ~1.5× ($0.62 break-even vs $0.40 assumed); best five trades are 130% of net, and the last 25 are net-negative (−$3.23). `live_readiness.py` now passes 2/6 data gates (sample and feed), not enough for LIVE.
3. **Ledger gap persists** (engine $274.49 vs reconstructed true equity −$122.39). `check_data.py` reports 0 failures plus expected warnings: duplicate Trade_Num/reset breaks, five feed gaps, and stale `status.json` counters (restart resyncs it). No history rewrite is indicated by this dashboard task.
4. **Data integrity:** local log has 11,254 rows through 10-17 15:35 UTC; feature reconstruction still matches logged floor/ATR/RSI at ~100% in the win-rate report. The latest 35-minute gap is below the 60-minute readiness threshold.
5. **Blocked signals:** skips remain 190. Current phantom replay's sequential view is +$20.00 gross / −$12.40 net across 81 takeable blocked candidates; it is cascade-ignorant and is not a reason to loosen gates.
6. **LIVE path and logger: no movement.** `live_path_probe.py` remains 1/9 clean. Stage A not started; XM logger not installed (0/14 days). Do not quote the prior December estimate as revalidated; readiness timing has not been re-estimated.
7. **Dashboard-only pressure read added:** 60 closed M5 bars (~5 h), transparent weighted components and a previous-20-bar location card. BTC ledger comparison shows pressure ranges largely split by BUY vs SELL, as expected from the existing EMA gates; it is labeled context-only and makes no performance claim (`docs/ANALYSIS-2026-10-17-dashboard-pressure.md`).

### Operations

- Live bot runs from `/opt/bitcoin/` (paths hardcoded in `engine.py` /
  `trade_filter.py`). Deploy = merge PR → autosync pulls → engine restarts.
  Restarts are safe mid-trade **in FORWARD_TEST** (open trade restores from
  `status.json`, stats reload from `trades.csv`, slope gate re-seeds from the
  log). **That does not hold in LIVE mode**: a restart with a broker position
  open orphans it (probe 2) — and every deploy restarts the engine.
- `tools/autosync.sh` (cron, root, every 15 min) commits live data, deploys only
  if `smoke_test.py` passes (rolls back otherwise), runs the integrity gate and
  the handoff freshness check, and notifies Telegram per its `NOTIFY` policy —
  **`alerts` by default since 2026-09-17** (deploys, incident/state changes,
  and one `(daily)` summary digest per UTC day, replacing the old digest-every-
  15-min flood; `off` = silent, `always`/`quiet` = old behaviour). It
  auto-detects the engine/dashboard units by scanning systemd for units
  referencing `/opt/bitcoin`, and **it only ever pulls `origin/main`**. Install
  checklist + digest legend: `docs/AUTOSYNC.md`.
- **XM quote + contract-spec logger (review §7 Stage B-i) — built, not yet running.**
  `tools/mt5_quotes.py` + `deploy/mt5quotes.service` (install as
  `mt5quotes-btc`) is a read-only Wine sidecar: XM BTCUSD bid/ask/spread every
  30 s (+ a 5 s min/max spike envelope), an allow-listed contract-spec snapshot
  (execution/filling modes, stops level, volume step, swap, demo-vs-real) and
  shadow XM M5 candles **back-filled from the terminal's history** (so feed parity
  is measurable on install day, with no era split) into `xm_data/`, which
  `tools/autosync.sh` commits with the other live data; `tools/xm_quote_report.py`
  reads it (the digest gains a `xm logger` line and one deduplicated alert if
  it goes STALE). **Tested only against a fake terminal** (smoke Scenarios K, L):
  the install + validation checklist in `docs/XM-LOGGER.md` §3 is the real test,
  and the ≥14-day clock (incl. two weekends) starts at the first real `OK` row,
  not at merge. It never touches `engine.py`, `DATA_SOURCE` or the forward-test
  sample.
- **MT5 feed timestamp fix — implemented, deployment status per host.**
  `tools/mt5_feed.py` learns XM's whole-hour offset from a fresh tick and
  publishes UTC `ts` values, retaining `server_ts` and `server_offset_s`; smoke
  Scenario H covers fresh/stale offset estimation. The Bitcoin sidecar must be
  restarted after deployment, and `DATA_SOURCE=MT5` must wait until the first
  post-deploy JSON is verified.
- Feed health at this snapshot: **11,254 local M5 rows** through 2026-10-17 15:35 UTC. Five gaps >15 min are recorded (885 min 09-28/29, 35 min 10-03, 20 min 10-04, 35 min 10-10, 35 min 10-17); the three most recent are inside the rolling 14-day window, with a 35-minute worst gap (below the 60-minute readiness limit).
- **Next milestones:** (a) the logger's exit — ≥14 complete UTC days incl. 2 complete weekends, read with `python3 tools/xm_quote_report.py` — and (b) the remaining live-readiness gates; the 100-trade sample gate is now met. Stage A (order-path + Wine executor) is the critical path for any micro-live. Keep collecting. Session spread profile and stronger per-signal skip logging remain open.

## 2. Bot in one paragraph

Simulated BTC/USD swing-scalper on **M5** candles. BUY at the 20-bar floor /
SELL at the 20-bar ceiling after a ≥15% wick rejection, trend-gated by
EMA50 vs EMA200 (+30-bar EMA50 slope, entry within 0.3·ATR **on the adverse
side** of EMA50), RSI 40–70 for BUY / 30–60 for SELL, ATR bounds enforced as a
**% of price** (0.01%–0.60%) in the filter. Exits: SL = entry ∓ 2·ATR,
TP = entry ± 4·ATR (**RR 1:2**, breakeven WR ≈ 33% before cost). `engine.py` =
signals + execution/state; `trade_filter.py` = portfolio risk gates;
`dashboard.py` = Flask page on port 6001. Trading is FORWARD-TEST simulated (no
real orders) at `LOT_SIZE = 0.01` from a `STARTING_BALANCE` of $200. A
`TRADING_MODE=LIVE` path exists but **must not be switched on**: it has never
been exercised, fails 8 of 9 offline probes (`tools/live_path_probe.py`), and
cannot import `MetaTrader5` on the Linux box — see `docs/REVIEW-2026-10-01.md`
§6 and the staged path in §7 below.

**Difference from the gold bot, in one line:** BTC is M5 (gold M1), RR 1:2
(gold 1:1.5), wick 0.15 (gold 0.38), %-based ATR bounds (gold absolute $),
24/7 with no rollover blackout and no quiet hours, and **no breakeven (BE)
ratchet** — gold's BE stop is *not* ported (`docs/REVIEW-2026-09-15.md` §5
re-tested it; §5 below has the prior re-read).

## 3. Data feed: Twelve Data (default) / MT5 sidecar (option)

`DATA_SOURCE` env var in `/opt/bitcoin/.env` picks the feed; code default is
`TWELVEDATA` (WebSocket, `TWELVE_DATA_API_KEY`).

- **Twelve Data caveat**: the free plan's WebSocket is a *trial* allotment.
  When it expires the endpoint accepts the handshake and immediately closes —
  the log silently stops growing and a zombie socket never raises. This is
  exactly what killed the gold feed. If `forward_test_log.csv` stops growing,
  check the plan/WS status at api.twelvedata.com first. The freshness check in
  `tools/handoff_check.py` also reports the newest bar's timestamp, so a dead
  feed shows up as a snapshot that stops ageing.
- **Stale-feed guard (both sources)**: `STALE_FEED_SECONDS = 600` without a
  price event → force reconnect / re-poll + Telegram alert, rate-limited to
  `STALE_ALERT_COOLDOWN_SECONDS = 1800`. **BTC has no quiet hours** —
  `is_market_quiet()` always returns `False`, so every silence is treated as a
  stale feed.
- **MT5 sidecar**: optional Wine + MetaTrader5 process that polls the terminal
  and writes JSON candles the engine can consume. Timestamp fix (whole-hour
  server offset) is in `tools/mt5_feed.py`. Prefer Twelve Data unless the
  operator has verified the sidecar after a restart.

## 4. Risk gates and filters (current)

| Gate | Setting | Notes |
|---|---|---|
| Daily loss breaker | 3 consecutive SL or -$10 day → halt rest of UTC day | Protective on phantoms |
| SL cooldown | escalating 30/60/120 min after 1/2/3 consecutive SL | Costly-looking on small sample; cascade-ignorant — do not loosen |
| Blackouts | none (24/7) | — |
| ATR % bounds | 0.01% – 0.60% of price | Rejects dead and explosive regimes |
| RSI | 40–70 BUY / 30–60 SELL | — |
| Wick | ≥0.15 of range | — |
| EMA slope + near-EMA | 30-bar EMA50 slope + entry within 0.3·ATR adverse of EMA50 | Regime gate |
| Max open | 1 | — |
| Lot | 0.01 fixed | Forward-test only |

## 5. What the data says (2026-10-17)

- **Edge is positive but unproven.** Strict post-gate n=108, +$0.22/trade after $0.40 cost, t=+0.78, day-block bootstrap 76%. Best 5 trades = 130% of net (net negative without them); last 25 are −$3.23 net. Do not treat the point estimate as a live expectation.
- **Buy side currently outperforms Sell, but the sample remains limited.** Post-gate BUY: 56 trades, +$25.76 net; SELL: 52, −$2.28 net. Do not disable SELL without a pre-specified regime study.
- **Cost is still binding.** Measured round-trip $0.40; estimated break-even ~$0.62 (1.5×). The readiness gate requires 2.0×.
- **Sample gate passed (108/100); only 2/6 data-readiness gates pass.** Edge significance, cost cover, fragility and recent form remain failed.
- **Phantoms (blocked signals):** current sequential replay is +$20.00 gross / −$12.40 net, but cascade-ignorant and not grounds to change risk gates.
- **Dashboard pressure is contextual only.** It does not inform readiness or trading decisions; see `docs/ANALYSIS-2026-10-17-dashboard-pressure.md`.
- **No parameter changes recommended.** Keep collecting and pursue the XM logger (real spread + contract specs), not a retune.

## 6. Known issues / debt

- LIVE order path: 1/9 probes clean. Stage A (fixes + Wine executor) not started. Do not flip `TRADING_MODE`.
- Engine ledger vs reconstructed equity gap (~$397) is known and explained (09-03 monsters + resets + residual). Do not "fix" the ledger by rewriting history.
- #125 reconciliation residue is closed history; status resyncs on restart.
- XM logger built but not installed on the host. 0/14 days.
- Session-specific spread profile and richer skip logging still open.

## 7. Staged path to micro-live (status refreshed 2026-10-17; still blocked)

| Stage | What | Status | Gate |
|---|---|---|---|
| A | Order-path fixes + Wine executor PR | **Not started** | Probe ≥8/9 clean |
| B-i | XM logger installed + ≥14 days (2 weekends) | **Not started** (built) | `xm_quote_report.py` OK |
| B-ii | 100 strictly post-gate trades | **108/100** (sample gate passed) | Sample |
| C | Remaining readiness gates (edge, cost, fragility, form) | **2/6 pass** | All 6 |
| D | Micro-live (tiny size, kill switches) | Blocked on A–C | User sign-off |

The early-to-mid December 2026 estimate in `docs/REVIEW-2026-10-09.md` is historical and has **not** been recalculated against the 2026-10-17 state. No micro-live date is promised. Stage A and the logger's ≥14-day/two-weekend clock remain the calendar levers; readiness gates and user sign-off still block any LIVE transition.

**Accelerating the statistical gates (added 2026-10-13, no params/gates/conclusions changed):** Stage C's binding gates (edge, cost cover, fragility) are statistical and are what make the forward test feel endless. `tools/backtest.py` + `tools/history_to_log.py` now cross-check them on a long M5 history in seconds (`docs/ACCELERATE-TESTING.md`). This does **not** move any gate or change the verdict — it only makes the trade-off visible sooner, and it does not replace the now-passed ≥100-post-gate forward sample or the logger clock. The two calendar levers that *do* move the date remain starting the logger (14-day clock) and Stage A now. **`docs/START-LEVER1.md`** is the ready-to-run runbook for both (logger install/validation + the Stage A findings table + the Wine order-executor design).

## 8. Tools

- `tools/win_rate_report.py --spread 0.40` — slices, t-stats, bootstrap, cost cover.
- `tools/live_readiness.py --spread 0.40` — the 6 data gates.
- `tools/handoff_check.py` / `--update` — snapshot freshness.
- `tools/check_data.py` — ledger integrity.
- `tools/live_path_probe.py` — LIVE order-path probes.
- `tools/xm_quote_report.py` — logger health (once installed).
- `tools/pressure_report.py` — dashboard-equivalent, read-only BTC buy/sell tape context + per-side pre-entry score ranges; no trade gate or predictive bucket claim (`docs/ANALYSIS-2026-10-17-dashboard-pressure.md`).
- `tools/autosync.sh` — 15-min data commit + deploy gate + Telegram.
- `tools/history_to_log.py` / `tools/backtest.py` — **fast path for the statistical
  gates**: replay the frozen gates over a long M5 history (raw OHLC → engine-faithful
  log → net/trade, t-stat, day-block bootstrap, cost cover, per-side, fragility) in
  seconds, reusing `replay_lib` + `live_readiness`. A cross-check, not a go-live
  substitute — see `docs/ACCELERATE-TESTING.md`. (`history_to_log.py --selfcheck`
  proves the converter reproduces the engine.)

## 9. Geometry change (do not pool)

2026-09-06 17:49 UTC: SL/TP geometry changed to the current 2·ATR / 4·ATR (RR 1:2). Pre-change trades have a different breakeven WR. Never quote a single pooled R-multiple or breakeven rate across this boundary. All "post-gate" and "live geometry" slices start after it.

## 10. How to keep this file honest

1. Run `python3 tools/handoff_check.py --update` (rewrites the snapshot block from live CSVs).
2. Update the prose in §1 (header, LIVE verdict, book table, "What changed"), §5, and §7 to match.
3. Commit and push immediately (Session & Push Protocol). Keep the session PR open until the user signs off.
4. Do not invent numbers. If a tool did not produce it, do not write it.
5. Re-run `tools/win_rate_report.py` and `tools/check_data.py` before drawing any conclusion from the CSVs.
