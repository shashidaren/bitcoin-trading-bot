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
| as_of_utc | 2026-10-13 09:05 |
| data_collection | unknown |
| closed_trades | 157 |
| wins_losses | 66W/91L |
| win_rate_pct | 42.0 |
| engine_ledger_usd | 270.37 |
| true_equity_usd | -126.48 |
| live_era_trades | 103 |
| live_era_net_usd | +24.15 |
| log_covered_trades | 103 |
| log_bars | 10030 |
| log_last_bar_utc | 2026-10-13 09:05 |
| skip_rows | 190 |
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

## 1. Where things stand (local data through 2026-10-13 09:05:09 UTC; **157 closed trades, no open trade; win-rate re-read 2026-10-13**)

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
- **Current session (2026-10-13):** docs-only refresh of the handoff snapshot and
  prose to the 157-trade / 10,030-bar mark, **plus** a code addition that changes
  no params, gates, or conclusions: `tools/history_to_log.py` +
  `tools/backtest.py` (§8, §7) — a large-N historical cross-check for the
  statistical gates, added because "the forward test takes too long"
  (`docs/ACCELERATE-TESTING.md`).
  Post-gate sample is now **99 trades** (was 83 on 10-09). **Outstanding decision
  for the user:** approve starting Stage A (order-path PR) and installing the XM
  logger sidecar — those two starts are what move the micro-live date (see §7).

**LIVE verdict (2026-10-13 win-rate re-read): still not ready.** Strictly
post-gate sample is now **99 trades** (42W/57L, 42.4%), with t = +0.80 and a
~75% day-block bootstrap probability of positive mean. Best 5 trades are
**133% of net** (net negative without them); second half of the slice is
net-negative. Estimated break-even round trip ~**$0.63 vs $0.40 assumed
(1.6×)** — cost gate still FAIL. Only **1/6** data-readiness gates pass.
Confirming even the observed ~$0.23/trade edge needs ~700+ post-gate trades
(~30 more weeks at ~20/week). LIVE order-path probe remains 1/9 clean
(4 BLOCKER, 3 HIGH, 1 ADVISORY); **Stage A has not started and the XM logger
has not been installed (0/14 days)**. Earliest realistic micro-live remains
**early-to-mid December 2026**, conditional on starting Stage A now. Keep
`TRADING_MODE = FORWARD_TEST`; do not enable real-money orders.

### The book in one table (net of $0.40/trade; gross in brackets; refreshed 2026-10-13)

| Slice | n | W/L | WR | net | gross | net/trade |
|---|---:|---:|---:|---:|---:|---:|
| from 09-05 (exclude the 09-03 sizing outliers) | 155 | 66/89 | 42.6% | **+8.32** | [+70.32] | +0.05 |
| live geometry (≥09-06 17:49, RR 1:2) | 120 | 51/69 | 42.5% | +21.10 | [+69.10] | +0.18 |
| "new regime" (≥09-09 02:25, tool boundary) | 103 | 43/60 | 41.7% | **+24.15** | [+65.35] | +0.23 |
| **strictly post-gate (≥09-10)** | 99 | 42/57 | 42.4% | **+23.00** | [+62.60] | +0.23 |
| last 25 closed | 25 | 10/15 | 40.0% | +1.40 | [+11.40] | +0.06 |
| last 10 | 10 | 4/6 | 40.0% | -1.20 | — | -0.12 |

The slices overlap. The 103-trade post-port slice includes four 09-09 rows before
the gates actually went live; use the 99-trade ≥09-10 slice when judging today's
gates. Do not use a pooled R total or one pooled breakeven rate across the 09-06 17:49 geometry change. Re-run `tools/win_rate_report.py --spread 0.40` for exact refreshed slices.

The raw Profit column sums to **−$326.48 gross** across all 157 closed rows, giving a ledger reconstruction of **−$126.48 from the $200 start before spread costs**. The engine ledger reads **$270.37**; the gap is the known 09-03 sizing monsters plus pre-port balance resets plus residual reconciliation artifacts. Exclude the two outliers from every strategy P/L statistic. The clean 09-05-on book (155 trades) is **+$70.32 gross / +$8.32 net** at the measured $0.40 round trip.

### What changed since the 2026-10-09 snapshot (141 → 157 closed rows; 8,930 → 10,030 M5 rows, +1,100)

1. **Sixteen new closes (6W/10L, roughly flat to slightly negative net), no open trade.** Post-gate sample grew 83 → **99**. Sample-size gate (100 post-gate) is now essentially met; the remaining gates are the binding constraints.
2. **The point estimate softened further; the edge remains unproven.** Strictly post-gate n=99: 42W/57L, 42.4%, ~+$62.60 gross / +$23.00 net, t=+0.80, day-block bootstrap ~75% positive. Cost-adjusted cover ~1.6× (still below the 2.0× gate). Best 5 trades are ~133% of net; second half net-negative. Confirming the observed edge still needs ~700 post-gate trades.
3. **Ledger gap persists** (engine $270.37 vs reconstructed true equity ~−$126.48). Same known causes (09-03 monsters + pre-port resets + residual #125-era artifacts). No new unexplained breaks reported by `check_data.py` beyond the expected warnings.
4. **Data integrity:** `check_data.py` reports only expected warnings (duplicate Trade_Num, Balance_After breaks from ledger resets, feed gaps). Local log 10,030 rows through 10-13 09:05. Indicator reconstruction remains high; pathwalk agrees with log-covered trades.
5. **Blocked signals:** skips grew (136 → 190). Phantoms still show daily halt protective, blackouts neutral, cooldown costly-looking but too small/cascade-ignorant to loosen.
6. **LIVE path and logger: no movement.** `live_path_probe.py` still 1/9 clean. Stage A not started; XM logger not installed (0/14 days). Data-readiness gates: **1/6 pass**. Go-live timing unchanged: not now; earliest realistic micro-live early-to-mid December 2026 if Stage A + logger start immediately.

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
- Feed health at this snapshot: **10,030 local M5 rows** through 2026-10-13 09:05 UTC. Prior gaps (885 min 09-28/29, 35 min 10-03, 20 min 10-04) still present; the 885-min gap has aged out of a rolling 14-day window. No new large gaps reported in the latest check.
- **Next milestones:** (a) the logger's exit — ≥14 complete UTC days incl. 2 complete weekends, read with `python3 tools/xm_quote_report.py` — and (b) the remaining live-readiness gates beyond the now-nearly-met 100 post-gate sample. Stage A (order-path + Wine executor) is the critical path for any micro-live. Keep collecting. Session spread profile and stronger per-signal skip logging remain open.

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

## 5. What the data says (2026-10-13)

- **Edge is positive but unproven.** Post-gate n=99, net ~+$0.23/trade after $0.40 cost, t=+0.80, bootstrap ~75%. Fragility high (best 5 = 133% of net). Second half of the sample is net-negative. Do not treat the point estimate as a live expectation.
- **Buy side carries the edge; Sell is weaker.** Consistent with prior cuts. Do not disable SELL without a proper regime study — sample still thin.
- **Cost is the binding constraint.** Measured round-trip $0.40; break-even ~$0.63 (1.6×). Gate wants 2.0×. Any live spread wider than ~$0.50 will erase the edge.
- **Sample gate nearly met.** 99/100 post-gate. Remaining failures: edge significance, cost cover, fragility, recent form.
- **Phantoms (blocked signals):** daily halt still protective; blackouts neutral; cooldown positive-looking but too small and cascade-ignorant to change. Keep gates.
- **No parameter changes recommended.** Collect more data. The next useful experiment is the XM logger (real spread + contract specs), not a retune.

## 6. Known issues / debt

- LIVE order path: 1/9 probes clean. Stage A (fixes + Wine executor) not started. Do not flip `TRADING_MODE`.
- Engine ledger vs reconstructed equity gap (~$397) is known and explained (09-03 monsters + resets + residual). Do not "fix" the ledger by rewriting history.
- #125 reconciliation residue is closed history; status resyncs on restart.
- XM logger built but not installed on the host. 0/14 days.
- Session-specific spread profile and richer skip logging still open.

## 7. Staged path to micro-live (unchanged)

| Stage | What | Status | Gate |
|---|---|---|---|
| A | Order-path fixes + Wine executor PR | **Not started** | Probe ≥8/9 clean |
| B-i | XM logger installed + ≥14 days (2 weekends) | **Not started** (built) | `xm_quote_report.py` OK |
| B-ii | 100 strictly post-gate trades | **99/100** (met ~today) | Sample |
| C | Remaining readiness gates (edge, cost, fragility, form) | 1/6 pass | All 6 |
| D | Micro-live (tiny size, kill switches) | Blocked on A–C | User sign-off |

Earliest realistic micro-live: **early-to-mid December 2026** if Stage A and the logger start immediately. Otherwise later. See `docs/REVIEW-2026-10-09.md` §7 for the dated table; the 2026-10-13 numbers do not move the critical path.

**Accelerating the statistical gates (added 2026-10-13, no params/gates/conclusions changed):** Stage C's binding gates (edge, cost cover, fragility) are statistical and are what make the forward test feel endless. `tools/backtest.py` + `tools/history_to_log.py` now cross-check them on a long M5 history in seconds (`docs/ACCELERATE-TESTING.md`). This does **not** move any gate or change the verdict — it only makes the trade-off visible sooner, and it does not replace the ≥100-post-gate forward sample or the logger clock. The two calendar levers that *do* move the date remain starting the logger (14-day clock) and Stage A now.

## 8. Tools

- `tools/win_rate_report.py --spread 0.40` — slices, t-stats, bootstrap, cost cover.
- `tools/live_readiness.py --spread 0.40` — the 6 data gates.
- `tools/handoff_check.py` / `--update` — snapshot freshness.
- `tools/check_data.py` — ledger integrity.
- `tools/live_path_probe.py` — LIVE order-path probes.
- `tools/xm_quote_report.py` — logger health (once installed).
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
