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
| as_of_utc | 2026-10-23 13:20 |
| data_collection | 4098 |
| closed_trades | 183 |
| wins_losses | 72W/111L |
| win_rate_pct | 39.3 |
| engine_ledger_usd | 258.86 |
| true_equity_usd | -138.02 |
| live_era_trades | 129 |
| live_era_net_usd | +2.21 |
| log_covered_trades | 129 |
| log_bars | 12955 |
| log_last_bar_utc | 2026-10-23 13:20 |
| skip_rows | 227 |
| open_trade | none |
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

## 1. Where things stand (local data through 2026-10-23 13:20 UTC; **183 closed trades, no open trade; readiness re-read 2026-10-23**)

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
- **Reviews:** `docs/REVIEW-2026-10-18-dashboard-engine.md` is the latest —
  dashboard pressure/status and forward-test engine audit after PR #21.
  `docs/REVIEW-2026-10-09.md` is the 141-trade win-rate re-read and go-live
  timing check. `docs/REVIEW-2026-10-05.md` is the exit-state recheck (125
  closed ledger rows plus the then-active #125, since reconciled — see the
  RESOLVED note below). `docs/REVIEW-2026-10-01.md` remains the full
  live-readiness review and staged path; its detailed snapshot is historical.
  `docs/REVIEW-2026-09-15.md` §13 is the 99-trade historical re-cut (§12 the
  78-trade one).
- **Previous merge (PR #21, 2026-10-17):** added the display-only BTC tape-
  pressure read and previous-20-bar location card to `dashboard.py`, with the
  read-only `pressure.py` library, `tools/pressure_report.py`, regression
  Scenario N, and `docs/ANALYSIS-2026-10-17-dashboard-pressure.md`. It made no
  engine parameters, entry/risk gates, state, or LIVE-readiness changes. The
  score remains contextual: EMA trend/slope repeat existing side gates, and
  flow uses a tick-count proxy rather than exchange volume.
- **Current session (2026-10-18):** audited the PR #21 dashboard/pressure path
  and the trading engine. Fixed two optional-MT5 forward-test defects: stale
  feed alerts were bypassed on missing/unchanged candles, and restart dedup
  compared bar-open timestamps with log close timestamps (could skip the next
  M5 bar). MT5 bars now use a close-time watermark and the watchdog checks stale
  sidecar data. The dashboard now sources closed-trade cards from `trades.csv`,
  flags stale `status.json` counters without mutating state, and labels the
  retained engine balance as internal/not all-time P/L; pressure calibration now
  reports a conventional median for even samples. No strategy
  parameters, gates, sizing, or readiness conclusions changed. Added
  `docs/REVIEW-2026-10-18-dashboard-engine.md`; the current data snapshot is
  169 closed rows / 11,554 bars, with 111 strictly post-gate trades and 2/6
  data gates (still NOT READY). The default remains
  `TRADING_MODE = FORWARD_TEST`; the optional MT5 path changes are covered by
  offline tests only and must be verified against the real sidecar after deploy.
  **Outstanding decision remains:** approve Stage A (order-path work) and install
  the XM logger sidecar — the calendar levers for any future micro-live (§7).
- **This session (2026-10-23): Telegram silenced, events journaled.** The per-trade Telegram noise
  (setups, skips, exits, stale-feed alerts) was too distracting, so it is stopped: `engine.py` no
  longer sends Telegram messages at all — every event (trade entry, exit, skip, stale-feed alert)
  is appended to `journal.csv` (`BTC_JOURNAL_FILE`, default `/opt/bitcoin/journal.csv`) via
  `Engine.journal()`, and `tools/autosync.sh` now defaults `NOTIFY=off` (no digest). The dashboard
  gained a **Journal** tab (new nav tab next to Dashboard) showing the most recent 100 journal
  entries, newest first — that panel is the replacement feed. Nothing trading-related goes to
  Telegram anymore. The snapshot block was refreshed from the live files: data now runs through
  2026-10-23 13:20 UTC (183 closed rows / 12,955 bars / 227 skips). No strategy parameters,
  gates, sizing, or readiness conclusions changed.
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

**LIVE verdict (2026-10-23 readiness re-read): still not ready.** Strictly
post-gate sample is **125 trades** (47W/78L, 37.6%), net +$0.01/trade after
$0.40 cost (gross +$51.05, net +$1.05), t = +0.03 and a 49% calendar-day
bootstrap probability of positive mean. Best 5 trades are **2,908% of net** (net
is −$29.48 without them); last 25 are net −$19.58. Estimated break-even round
trip is about **$0.41 vs $0.40 assumed (1.0×)** — cost gate still FAIL (gate
requires 2.0×). **2/6** data-readiness gates pass (sample and feed). LIVE order-path probe remains 1/9 clean (4 BLOCKER, 3 HIGH,
1 ADVISORY); **Stage A has not started and the XM logger has not been installed
(0/14 days)**. The prior early-to-mid December micro-live estimate was based on
older data and is not revalidated here. Keep `TRADING_MODE = FORWARD_TEST`; do
not enable real-money orders.

### The book in one table (net of $0.40/trade; gross in brackets; refreshed 2026-10-23)

| Slice | n | W/L | WR | net | gross | net/trade |
|---|---:|---:|---:|---:|---:|---:|
| from 09-05 (exclude the 09-03 sizing outliers) | 181 | 72/109 | 39.8% | **-15.58** | [+56.82] | -0.09 |
| live geometry (≥09-06 17:49, RR 1:2) | 146 | 57/89 | 39.0% | -2.80 | [+55.60] | -0.02 |
| "new regime" (≥09-09 02:25, tool boundary) | 129 | 49/80 | 38.0% | **+2.21** | [+53.81] | +0.02 |
| **strictly post-gate (≥09-10)** | 125 | 47/78 | 37.6% | **+1.05** | [+51.05] | +0.01 |
| last 25 closed | 25 | 6/19 | 24.0% | -19.58 | [-9.58] | -0.78 |
| last 10 | 10 | 3/7 | 30.0% | -4.89 | [-0.89] | -0.49 |

The slices overlap. The post-port slice includes four 09-09 rows before
the gates actually went live; use the 125-trade ≥09-10 slice when judging today's
gates. Do not use a pooled R total or one pooled breakeven rate across the 09-06 17:49 geometry change. Re-run `tools/win_rate_report.py --spread 0.40` for exact refreshed slices.

The raw Profit column sums to **−$338.02 gross** across all 183 closed rows, giving a ledger reconstruction of **−$138.02 from the $200 start before spread costs**. The engine ledger reads **$258.86**; the gap is **$396.88**, the known 09-03 sizing monsters plus pre-port balance resets and residual reconciliation artifacts. Exclude the two outliers from every strategy P/L statistic. The clean 09-05-on book (181 trades) is **+$56.82 gross / −$15.58 net** at the measured $0.40 round trip.

### What changed since the 2026-10-17 snapshot (166 → 169 closed rows; 11,254 → 11,554 M5 rows, +300)

1. **Three additional closes; no trade is currently open.** The strictly post-gate sample grew 108 → **111**, clearing the sample-count gate.
2. **The edge remains unproven and has softened.** Post-gate n=111: 44W/67L, 39.6%, +$60.74 gross / +$16.34 net, t=+0.54, calendar-day bootstrap 68% positive. Cost cover is ~1.4× ($0.55 break-even vs $0.40 assumed); best five trades are 187% of net, and the last 25 are net-negative (−$7.82). `live_readiness.py` still passes only 2/6 data gates (sample and feed), not enough for LIVE.
3. **Ledger gap persists** (engine $268.54 vs reconstructed true equity −$128.33). `check_data.py` reports 0 failures / 66 warnings: duplicate Trade_Num/reset breaks, five feed gaps, and stale `status.json` counters (70W/99L vs ledger 69W/100L). The dashboard now shows ledger counts with a mismatch warning; it does not rewrite state or history. Today's ledger has 3 SLs; the daily breaker confirms 3/3 and halts entries for the remainder of this UTC day as designed.
4. **Data integrity:** local log has 11,554 rows through 2026-10-18 16:35 UTC; feature reconstruction remains approximately 100% for the logged pre-update floor/ATR/RSI. The worst gap in the rolling 14-day readiness window is 35 minutes (below the 60-minute limit).
5. **Blocked signals:** skips rose 190 → 196. Current sequential phantom replay is +$18.08 gross / −$15.92 net across 85 takeable blocked candidates; it is cascade-ignorant and is not a reason to loosen gates.
6. **Engine audit fixes (no strategy changes):** the optional MT5 runner now checks stale feed on missing/unchanged bars and compares source bar-close timestamps consistently across restart. These are offline-tested; the host sidecar has not been verified. `live_path_probe.py` remains 1/9 clean; Stage A not started; XM logger not installed (0/14 days).
7. **Dashboard pressure remains context-only:** as of 2026-10-18 16:35:14, BUY 18.9% / SELL 81.1%; last-pre-entry score ranges remain separated by side (expected from existing EMA gates). Tick-count proxy is not exchange volume and no predictive claim is made (`docs/ANALYSIS-2026-10-17-dashboard-pressure.md`, updated audit in `docs/REVIEW-2026-10-18-dashboard-engine.md`).

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
  **`off` by default since 2026-10-23** (Telegram was too noisy; engine events
  now live in `journal.csv` and on the dashboard's Journal tab; `alerts` =
  deploys/incidents + one `(daily)` digest per UTC day, replacing the old
  digest-every-15-min flood; `always`/`quiet` = old behaviour). It
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
  Scenario H covers fresh/stale offset estimation. The current session also
  aligns MT5 restart dedup on exact UTC bar-close timestamps. The Bitcoin
  sidecar must be restarted after deployment, and `DATA_SOURCE=MT5` must wait
  until the first post-deploy JSON is verified. Neither change has been verified
  against the real host terminal.
- Feed health at this snapshot: **11,554 local M5 rows** through 2026-10-18 16:35 UTC. Five gaps >15 min are recorded (885 min 09-28/29, 35 min 10-03, 20 min 10-04, 35 min 10-10, 35 min 10-17); the worst in the rolling 14-day readiness window is 35 minutes (below the 60-minute limit).
- **Next milestones:** (a) the logger's exit — ≥14 complete UTC days incl. 2 complete weekends, read with `python3 tools/xm_quote_report.py` — and (b) the remaining live-readiness gates; the 111-trade sample gate is met. Stage A (order-path + Wine executor) is the critical path for any micro-live. Keep collecting. Session spread profile and stronger per-signal skip logging remain open.

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
- **Stale-feed guard (both sources)**: `STALE_FEED_SECONDS = 600` without
  fresh source data → rate-limited Telegram alert (`STALE_ALERT_COOLDOWN_SECONDS
  = 1800`). Twelve Data forces a WebSocket reconnect; the MT5 runner checks
  every loop, including missing/unchanged files, and rejects stale closed
  candles. The MT5 fix is on the current session branch and still needs host
  verification. **BTC has no quiet hours** — `is_market_quiet()` always returns
  `False`, so every silence is treated as a stale feed.
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

## 5. What the data says (2026-10-23)

- **Edge is positive but unproven and has softened.** Strict post-gate n=125 (47W/78L, 37.6%), +$0.01/trade after $0.40 cost (gross +$51.05, net +$1.05), t=+0.03, calendar-day bootstrap 49%. Best 5 trades = 2,908% of net (net −$29.48 without them); last 25 are −$19.58 net. Do not treat the point estimate as a live expectation.
- **BUY still outperforms SELL in the post-gate sample, but this is not enough to disable a side.** BUY: 67 trades, +$18.05 net; SELL: 62 trades, −$15.84 net (new-regime slice ≥09-09). Keep both sides pending a pre-specified, out-of-sample regime study.
- **Cost is still binding.** Measured round-trip $0.40; estimated break-even ~$0.41 (1.0×). The readiness gate requires 2.0×.
- **Sample gate passed (125/100); only 2/6 data-readiness gates pass.** Edge significance, cost cover, fragility, and recent form remain failed.
- **Phantoms (blocked signals):** latest sequential replay is +$45.10 gross / +$7.50 net across 94 takeable candidates, but is cascade-ignorant and not grounds to change risk gates.
- **Dashboard pressure is contextual only.** Current snapshot is BUY 18.9% / SELL 81.1%; no readiness or trading decision consumes it. See `docs/ANALYSIS-2026-10-17-dashboard-pressure.md` and `docs/REVIEW-2026-10-18-dashboard-engine.md`.
- **No parameter changes recommended.** Keep collecting and pursue the XM logger (real spread + contract specs), not a retune.

## 6. Known issues / debt

- LIVE order path: 1/9 probes clean. Stage A (fixes + Wine executor) not started. Do not flip `TRADING_MODE`.
- Engine ledger vs reconstructed equity gap (+$396.87; engine $268.54 vs reconstructed −$128.33) is known and explained (09-03 monsters + resets + residual). Do not "fix" the ledger by rewriting history.
- `status.json` currently says 70W/99L while `trades.csv` says 69W/100L. The dashboard now displays the ledger counts and an amber mismatch notice; status/in-memory counters still need the normal safe FORWARD_TEST restart to resync. Risk gates read the ledger. Do not edit live state to make the dashboard look fresh.
- #125 reconciliation residue is closed history; status resyncs on restart.
- XM logger built but not installed on the host. 0/14 days.
- Optional MT5 runner stale-feed and restart-watermark fixes are implemented and smoke-tested on this branch only; host deployment and the real sidecar remain unverified.
- Telegram is silenced: `engine.py` journals events to `journal.csv` instead of sending Telegram messages, `autosync.sh` defaults `NOTIFY=off`, and the dashboard's Journal tab shows the log. To restore the digest, set `NOTIFY=alerts` in the autosync environment. Session-specific spread profile and richer skip logging still open.

## 7. Staged path to micro-live (status refreshed 2026-10-18; still blocked)

| Stage | What | Status | Gate |
|---|---|---|---|
| A | Order-path fixes + Wine executor PR | **Not started** | Probe ≥8/9 clean |
| B-i | XM logger installed + ≥14 days (2 weekends) | **Not started** (built) | `xm_quote_report.py` OK |
| B-ii | 100 strictly post-gate trades | **125/100** (sample gate passed) | Sample |
| C | Remaining readiness gates (edge, cost, fragility, form) | **2/6 pass** | All 6 |
| D | Micro-live (tiny size, kill switches) | Blocked on A–C | User sign-off |

The early-to-mid December 2026 estimate in `docs/REVIEW-2026-10-09.md` is historical and has **not** been recalculated against the 2026-10-18 state. No micro-live date is promised. Stage A and the logger's ≥14-day/two-weekend clock remain the calendar levers; readiness gates and user sign-off still block any LIVE transition.

**Accelerating the statistical gates (added 2026-10-13, no params/gates/conclusions changed):** Stage C's binding gates (edge, cost cover, fragility) are statistical and are what make the forward test feel endless. `tools/backtest.py` + `tools/history_to_log.py` now cross-check them on a long M5 history in seconds (`docs/ACCELERATE-TESTING.md`). This does **not** move any gate or change the verdict — it only makes the trade-off visible sooner, and it does not replace the now-passed ≥100-post-gate forward sample or the logger clock. The two calendar levers that *do* move the date remain starting the logger (14-day clock) and Stage A now. **`docs/START-LEVER1.md`** is the ready-to-run runbook for both (logger install/validation + the Stage A findings table + the Wine order-executor design).

## 8. Tools

- `tools/win_rate_report.py --spread 0.40` — slices, t-stats, bootstrap, cost cover.
- `tools/live_readiness.py --spread 0.40` — the 6 data gates.
- `tools/handoff_check.py` / `--update` — snapshot freshness.
- `tools/check_data.py` — ledger integrity.
- `tools/live_path_probe.py` — LIVE order-path probes.
- `tools/xm_quote_report.py` — logger health (once installed).
- `tools/pressure_report.py` — dashboard-equivalent, read-only BTC buy/sell tape context + per-side pre-entry score ranges; no trade gate or predictive bucket claim (`docs/ANALYSIS-2026-10-17-dashboard-pressure.md`).
- `docs/REVIEW-2026-10-18-dashboard-engine.md` — post-PR #21 audit findings, offline fixes, current readiness/data read, and verification.
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
