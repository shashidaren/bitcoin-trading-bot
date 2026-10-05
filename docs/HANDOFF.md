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
| as_of_utc | 2026-10-05 03:02 |
| data_collection | 2326 |
| closed_trades | 125 |
| wins_losses | 54W/71L |
| win_rate_pct | 43.2 |
| engine_ledger_usd | 258.81 |
| true_equity_usd | -133.01 |
| live_era_trades | 71 |
| live_era_net_usd | +30.42 |
| log_covered_trades | 71 |
| log_bars | 7668 |
| log_last_bar_utc | 2026-10-05 03:00 |
| skip_rows | 117 |
| open_trade | BUY #125 @ 84177.15 |
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

## 1. Where things stand (local data through 2026-10-05 03:00:03 UTC; host status through 03:02:16 UTC; delta review 2026-10-05 at 125 closed trades)

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
- **Reviews:** `docs/REVIEW-2026-10-05.md` is the latest data and exit-state
  recheck (125 closed ledger rows plus active #125). `docs/REVIEW-2026-10-01.md`
  remains the full live-readiness review and staged path; its detailed data
  snapshot is historical. `docs/REVIEW-2026-09-15.md` §13 is the 99-trade
  historical re-cut (§12 the 78-trade one).
- **Current session:** PR #13 (docs-only verification) is already merged and did
  **not** contain an engine exit fix. This session adds a narrowly scoped,
  unmerged MT5 forward-test exit fix for future simulated candles only: BUY/SELL
  SL/TP checks on each accepted closed M5 candle, conservative stop-first ties,
  stop gaps filled at the candle open, target touches filled at the target,
  exit-before-entry ordering on the same candle close, and smoke Scenario M.
  Do not merge/deploy until the user approves; merging restarts the engine via
  autosync.

**LIVE verdict (2026-10-05): not ready for real money.** The strictly post-gate
sample is 67 trades (29W/38L), with t = +1.14 and an 83% day-block bootstrap
probability of positive mean; the best 5 trades are 104% of net (net −$1.27
without them). Estimated break-even round trip is $0.84 vs $0.40 assumed, and
only 3/6 data-readiness gates pass. The LIVE order-path probe remains at 1/9
clean (4 BLOCKER, 3 HIGH, 1 ADVISORY), and the Linux engine cannot import
`MetaTrader5`. Keep `TRADING_MODE = FORWARD_TEST`; do not enable real-money
orders. Separately, the saved simulator state has an active BUY #125 despite an
earlier recorded stop breach; this is an exit-state incident, not evidence of a
live broker position (details below and in the 2026-10-05 review).

### The book in one table (net of $0.40/trade; gross in brackets)

| Slice | n | W/L | WR | net | gross | net/trade |
|---|---:|---:|---:|---:|---:|---:|
| from 09-05 (exclude the 09-03 sizing outliers) | 123 | 54/69 | 43.9% | **+12.63** | [+61.83] | +0.10 |
| live geometry (≥09-06 17:49, RR 1:2) | 88 | 39/49 | 44.3% | +25.41 | [+60.61] | +0.29 |
| "new regime" (≥09-09 02:25, tool boundary) | 71 | 31/40 | 43.7% | **+30.42** | [+58.82] | +0.43 |
| **strictly post-gate (≥09-10)** | 67 | 29/38 | 43.3% | **+29.26** | [+56.06] | +0.44 |
| last 25 closed | 25 | 10/15 | 40.0% | +2.82 | [+12.82] | +0.11 |
| last 10 | 10 | 6/4 | 60.0% | +13.85 | [+17.85] | +1.39 |

The slices overlap. The 71-trade post-port slice includes four 09-09 rows before
the gates actually went live; use the 67-trade ≥09-10 slice when judging today's
gates. Do not use a pooled R total or one pooled breakeven rate across the
09-06 17:49 geometry change.

The raw Profit column sums to **−$333.01 gross** across all 125 closed rows,
giving a ledger reconstruction of **−$133.01 from the $200 start before spread
costs**. The engine ledger reads **$258.81**; the **$391.82** gap is the known
09-03 sizing monsters (−$197.63 and −$197.21) plus pre-port balance resets, not
a new live accounting failure. Exclude the two outliers from every strategy P/L
statistic. The clean 09-05-on book is **+$61.83 gross / +$12.63 net** at the
measured $0.40 round trip.

### What changed since the 2026-10-01 snapshot (124 → 125 closed rows; 6,518 → 7,668 M5 rows, +1,150)

1. **One new close, one new open trade.** The newly closed ledger row is the
   SELL entered 10-01 01:15 at $83,602.00; it exited SL at 03:51 for −$1.38
   gross / −$1.78 net. The current open BUY #125 entered 10-01 07:10 at
   $84,177.15. Last 25 closed trades are +$2.82 net; last 10 are +$13.85 net.
2. **The edge remains unproven.** Strictly post-gate n=67: 29W/38L, 43.3%
   (Wilson 32.1–55.2), **+$56.06 gross / +$29.26 net**, t=+1.14, 95% CI on
   net/trade [−$0.33, +$1.20], day-block bootstrap 83% positive. Median 1R is
   $1.66; $0.40 is 24% of 1R; estimated cost-adjusted breakeven WR is 41.4% and
   break-even round trip is $0.84. The best five trades are 104% of net (−$1.27
   without them). See the 2026-10-05 review for the full cut.
3. **BUY #125 remains open in the simulator after a logged stop breach.** Entry
   $84,177.15, SL $84,008.74, TP $84,513.98. The 07:15 candle low was $84,035.75
   (no stop hit); the 07:20:11 candle low was $83,838.25 and close $83,841.65,
   with high only $84,076.35. The first recorded barrier is SL. Local
   `status.json` at 03:02:16 and the operator-pasted host status after restart
   both show #125 active, 91 h 52 min after entry, with no close row. The supplied
   engine excerpt has no close/SL event; later prices rise above TP, which cannot
   supersede the first stop. OHLC proves a breach, not an exact executable fill.
   The MT5 forward-test startup is a simulator, not evidence of a broker position.
4. **The best-supported explanation is the historical MT5 candle-exit omission.**
   The operator-supplied host evidence now points strongly at the MT5 forward-test
   path for #125: a Twelve Data startup at 04:43:08 UTC on Oct 1, then an MT5-feed
   startup at 04:53:24, no later engine stop/start in the supplied Oct 1–2 journal
   window, `mt5feed-btc.service` loaded/active/running, and the host's current
   deployed checkout at `aa506c025494acc9de008755393abe060948d5a8` (a docs-only
   merge of PR #13). The checked-in `run_mt5_test()` in that line of history
   evaluates closed candles without checking an already-open simulated trade
   against candle OHLC. This session fixes future MT5 forward-test exits with a
   conservative convention (SL first on ties; stop gaps fill at the candle open;
   target touches fill at the target; entry-candle range is ignored), but it does
   **not** retro-close #125 or mutate the host ledger/state. The exact engine SHA
   at the 07:20 breach was not supplied, so the MT5 attribution is still a strong
   inference rather than a byte-for-byte proof.
5. **Data integrity:** `check_data.py` reports 0 failures / 64 warnings. The local
   log has 7,668 rows through 10-05 03:00:03, 197 missing M5 slots in 14 runs,
   and three gaps >15 min (885 min on 09-28/29; 35 min on 10-03; 20 min on
   10-04). Two duplicated minutes remain (09-23 10:50 and 09-25 10:10). The
   status update at 03:02:16 is 2 min 13 s after the last bar; ledger counts
   agree, but timestamps do not match. The host also reported 7,668 rows. The
   sampled service was active then; this does not prove it is still alive later.
6. **Gates/readiness:** risk-gate skip evidence is unchanged (117 skips; 43
   unscorable). `live_readiness.py` passes 3/6 data gates; feed health still fails
   on the historical 885-minute outage. `pathwalk_sims.py` agrees with all 71
   log-covered **closed** trades; that agreement does not resolve open #125.
7. **LIVE path remains blocked.** `tools/live_path_probe.py` reports 4 BLOCKER,
   3 HIGH and 1 ADVISORY (1/9 clean); the Linux engine cannot import
   `MetaTrader5`. The smoke suite now passes **A–M**; new Scenario M covers MT5
   forward-test candle exits (BUY/SELL SL/TP touches, no-touch candles,
   stop-first both-barriers behaviour, gap fills, no entry-candle self-exit,
   exit-before-entry ordering, and restart/dedup without duplicate close rows).

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
  reads it (the digest gains a `📈 xm logger` line and one deduplicated alert if
  it goes STALE). **Tested only against a fake terminal** (smoke Scenarios K, L):
  the install + validation checklist in `docs/XM-LOGGER.md` §3 is the real test,
  and the ≥14-day clock (incl. two weekends) starts at the first real `OK` row,
  not at merge. It never touches `engine.py`, `DATA_SOURCE` or the forward-test
  sample.
- **MT5 feed timestamp fix — implemented in this PR, not yet deployed.**
  `tools/mt5_feed.py` now learns XM's whole-hour offset from a fresh tick and
  publishes UTC `ts` values, retaining `server_ts` and `server_offset_s`; smoke
  Scenario H covers fresh/stale offset estimation. The Bitcoin sidecar must be
  restarted after deployment, and `DATA_SOURCE=MT5` must wait until the first
  post-deploy JSON is verified.
- Feed health at this snapshot: **7,668 local M5 rows** since 09-07 20:20 UTC,
  through 2026-10-05 03:00:03; 197 missing M5 slots in 14 runs, with the
  885-minute 09-28/29 outage plus 35-minute (10-03) and 20-minute (10-04) gaps.
  Local status was updated at 03:02:16 (2 min 13 s after the last bar), and the
  operator reported the same 7,668-row host log. Host output says `/opt/bitcoin/.env`
  currently selects `DATA_SOURCE=MT5`; `bitcoin-engine.service` was active and
  started as `FORWARD TEST (MT5 feed)`. After restart the engine restored BUY
  #125 (entry $84,177.15 at 10-01 07:10:10; SL $84,008.74, TP $84,513.98;
  daily-loss counter 0/3) while still showing 125 closed trades. This confirms
  simulator state, not a broker position, and restart did not reconcile the
  10-01 07:20:11 stop breach. See `docs/REVIEW-2026-10-05.md` before relying on
  the dashboard state. The checked-in MT5 loop lacks a simulated exit check, but
  the Oct 1 feed mode and deployed SHA are still unknown. The unit scan was
  limited to units referencing `/opt/bitcoin`; query `mt5feed-btc.service`
  directly rather than infer that it is absent.
- **Next milestones:** first confirm/fix/reconcile the open paper trade and its
  feed path; then (a) the logger's exit — ≥14 complete UTC days incl. 2 complete
  weekends, read with `python3 tools/xm_quote_report.py` — and (b) 100
  strictly-post-gate trades (**67 today**) with the staged gates in review §7 —
  not a retune. The logger is built but no `xm_data/` output is present in this
  checkout. Keep collecting. The timeframe decision, session spread profile,
  and stronger per-signal skip logging remain open.

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
re-tested it; §5 below has the 125-trade re-read).

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
  `is_market_quiet()` always returns `False`, so every silence is an incident
  (deliberately different from gold).
- **MT5 option** (`DATA_SOURCE=MT5`, feed only — trading stays simulated):
  the Linux engine never imports `MetaTrader5` (no Linux wheels). Sidecar
  `tools/mt5_feed.py` runs under the **Wine** Python in the same prefix as the
  terminal and atomically publishes the latest **closed M5 BTCUSD** candle to
  `/opt/bitcoin/mt5_last_candle.json`; the engine reads and dedupes it by
  candle timestamp. The sidecar must include the UTC timestamp normalization
  described below; verify its deployed version before switching to MT5 mode.
  Install: `sudo cp deploy/mt5feed.service /etc/systemd/system/mt5feed-btc.service
  && sudo systemctl daemon-reload && sudo systemctl enable --now mt5feed-btc`
  — **note the `-btc` suffix; the gold bot owns plain `mt5feed.service`.**
  Env overrides: `MT5_FEED_FILE`, `MT5_FEED_SYMBOL` (default `BTCUSD`; XM has no
  `BTCUSDm` — verified 2026-09-15), `MT5_FEED_TIMEFRAME` (default `M5`),
  `MT5_FEED_POLL`. Ops check: `jq .updated_at /opt/bitcoin/mt5_last_candle.json`
  (≤2 min old). Smoke Scenario H covers the read/normalize/dedup path.
- **MT5 `time` is broker server time, not UTC** (XM: GMT+2 winter / GMT+3
  summer on the EU rule — next change **Sun 25 Oct 2026**; the Python docs say UTC,
  the integers are not). `tools/mt5_feed.py` now learns the whole-hour offset from
  a fresh tick and publishes a UTC `ts` (retaining `server_ts` and
  `server_offset_s` for diagnosis). `engine.run_mt5_test` and its restart dedup
  therefore compare like with like. The fix is covered by smoke Scenario H for
  fresh/stale +3 h ticks; the default `TWELVEDATA` path is unaffected. The service
  must be restarted after this PR deploys; do not switch `DATA_SOURCE=MT5` before
  verifying the first post-deploy JSON has a UTC `ts`. The logger's independent
  candle conversion remains the reference for DST behavior; see
  `docs/XM-LOGGER.md` §6.
- **XM quote + contract-spec logger** (`mt5quotes-btc`, read-only, writes
  `xm_data/`): see §1 Operations and `docs/XM-LOGGER.md` (file/column dictionary,
  on-box validation checklist, reading guide). Install: `sudo cp
  deploy/mt5quotes.service /etc/systemd/system/mt5quotes-btc.service && sudo
  systemctl daemon-reload && sudo systemctl enable --now mt5quotes-btc` — **run
  the `--spec` and `--once` dry runs first** (checklist §3). Env overrides:
  `MT5_QUOTES_SYMBOL`, `_DIR`, `_INTERVAL`, `_POLL`, `_BACKFILL_BARS`, `_LABEL`.
- Deploy note (gold lesson): put `Environment=PYTHONUNBUFFERED=1` in the
  engine's systemd unit or prints are block-buffered out of `journalctl`.

## 4. Current risk gates (trade_filter.py)

- **SL cooldown**: 30 min after 1 SL, escalating to **60 min after 2
  consecutive SLs**. It is still the most-triggered gate: **44 of 117 skips**.
  The price log can score only 11 of them; those are 8W/3L, **+$23.24 gross /
  +$18.84 net**. The other 33 predate the log or cannot be reconstructed.
  This is a costly-looking small slice, not grounds to soften the cooldown.
- **Daily breaker**: `MAX_DAILY_LOSSES = 3` SLs per UTC day → hard halt for the
  rest of the day. It has 42 scorable blocked signals: **3W/36L/3T, −$48.49
  gross / −$65.29 net**. This remains protective; keep the hard halt. The counter
  reads a **400-row window** (`DAY_WINDOW`) because a 30-row window silently
  under-counts busy days. Pre-port loss days predate the breaker.
- **Blackouts (UTC)**: London 07:55–09:00, NY pre-market 12:25–12:45, NY open &
  US macro 13:25–15:15. They block both directions; there is no BTC evidence for
  gold's direction-aware carve-out. Of 25 logged blackout skips, 21 are
  scorable: **8W/13L, +$4.02 gross / −$4.38 net**; 4 remain unscorable. That is
  now neutral-to-protective (at 99 trades it read +$13.75 net on 14), so keep
  the schedule. No rollover blackout and no weekend pause (a weekend pause is a
  *hypothesis*, not a rule — review 2026-10-01 §3).
- **ATR bounds (% of price)**: `MIN_ATR_PERCENT = 0.0001` (0.01%),
  `MAX_ATR_PERCENT = 0.0060` (0.60%). Six ATR skips are logged; none is
  scorable from the current price log. The floor is not a cost control (0.01 % ≈
  $8 of ATR, where $0.40 would be ~250 % of 1R). The cost control belongs in the
  live spread guard, defined as a **share of 1R** (review §3.1, §6) — keep it
  separate from any win-rate filter.
- **Near-EMA gate is ONE-SIDED**: `MAX_BELOW_EMA_ATR = 0.30` caps how far the
  entry may sit on the *adverse* side of EMA50 (below for BUY, above for SELL).
  It does **not** cap favourable-side distance and is not a two-sided band.
  Tightening it is **unresolved**, not measured-negative any more: the post-gate
  ledger view says 0.15 would have blocked four losing rows (25 % WR, −$2.52
  net), the census view says the same cut skips +$1.14 — the views disagree on
  n = 4, so no change. The two-sided band is a separate, monitor-only candidate
  (§5, §7).
- **Slope gate**: EMA50 vs 30 bars ago, both directions; `ema50_history`
  re-seeds from the log on restart so the gate is live immediately.

Engine-side there is **no BE ratchet and no time stop** — a BTC trade only ends
at SL or TP. Exit-reason domain is therefore `{SL, TP}` only; every tool assumes
that. Phantom scores are horizon-marked counterfactuals, not realized trades.

**Missing, and required before LIVE (review 2026-10-01 §6):** a spread guard
(share of 1R + hard $ cap), an equity/drawdown kill switch (only 3 SLs/day
exists), a one-position-per-magic check against the broker, and a position-aware
dead-man alarm.

## 5. Evidence base (125 closed trades through 2026-10-01; log through 10-05) — see 2026-10-05 delta

Headline: **125 closed rows, 54W/71L (43.2%)**, including the two 09-03
pre-port sizing monsters. The raw ledger sums to **−$333.01 gross** (−$133.01
from the $200 start before costs) while `status.json` shows $258.81; the $391.82
discrepancy is the known sizing/reset history. Exclude the 09-03 pair from every
strategy statistic. From 09-05 on: **123 rows, 54W/69L, +$61.83 gross /
+$12.63 net** at the measured $0.40 round trip. The active BUY #125 is not a
closed row and is excluded from every performance statistic. Its saved state
conflicts with the price path; see §1 and `docs/REVIEW-2026-10-05.md`.

**Do not pool across geometry.** On 09-06 17:49 UTC the ledger moved from SL
1.5×ATR / TP 2.5×ATR to 2×/4× (RR 1:1.67 → 1:2). The pre-change slice is
n=37, 15W/22L, −$393.62 gross; from the change onward it is n=88, 39W/49L,
+$60.61 gross (+$25.41 net). These are separate rule eras; never quote pooled
R totals or breakeven rates across the boundary.

- **Integrity:** `check_data.py` reports 0 fail / 64 warn. Warnings include 21
  duplicate `Trade_Num` values, 9 `Balance_After` continuity breaks, the known
  +$391.82 engine-ledger/raw-profit drift, **197 missing M5 slots in 14 runs**
  (one 885-minute outage on 09-28/29, plus 35 minutes on 10-03 and 20 minutes
  on 10-04), the geometry boundary, two duplicate-minute re-evaluations
  (09-23 10:50, 09-25 10:10), and the existing fill warnings (#40/#52 −1.38R,
  #65/#101 −1.22R, #122 TP +3.05R vs +2.00R planned). All 67 ledger rows from
  the actual gate boundary (09-10) pass today's trend, RSI and near-EMA checks.
  The checker does **not** detect an active trade whose saved price path already
  crossed SL/TP; it is a separate operational finding.
- **Edge and cost.** Strictly post-gate (entries ≥09-10): n=67, 29W/38L, 43.3%
  (Wilson 32.1–55.2), **+$56.06 gross / +$29.26 net**; t=+1.14, 95% CI on
  net/trade [−$0.33, +$1.20], day-block bootstrap 83% positive. Median 1R is
  $1.66, so $0.40 is **24% of 1R**; approximate cost-adjusted breakeven WR is
  **41.4%**, and the break-even round trip is **$0.84 ($84/BTC)**. Best 5 trades
  are 104% of net (net −$1.27 without them). Last 25 closed: +$2.82 net; last
  10: +$13.85 net. This remains a positive but unproven point estimate; the
  M5/M15/H1/H4 timeframe comparison is still a dominant economics question.
- **Book by direction (strictly post-gate):** BUY n=32, 16W/16L, +$44.16 gross /
  **+$31.36 net**; SELL n=35, 13W/22L, +$11.90 gross / **−$2.10 net**. SELL
  has not paid for its cost yet, but 35 trades do not justify switching it off.
  The unfiltered signal census is a separate, cascade-ignorant diagnostic; it
  is not the traded book.
- **Signal census and cascade:** 7,668 logged M5 rows reconstruct 419 full
  signals (205 BUY, 214 SELL); 50 occur in blackout windows, leaving 369
  takeable. At TP 4×, the raw takeable entry stream is 117W/219L/33T and
  −$83.55 net before the one-position/cooldown/daily-halt cascade. Applying
  those gates selects 96 modeled trades (36W/51L/9T, **+$13.70 net**). This is
  a replay estimate, not additional observed trades. Indicator reconstruction
  matches floor 7,648/7,648 and ATR/RSI 7,653/7,653.
- **Exit geometry** (`pathwalk_sims.py --spread 0.40 --census`): replay agrees
  **71/71** for the log-covered closed trades. On the 240-minute counterfactual
  paths (all net of $0.40), TP 4× (live) is +$13.69, TP 5× +$28.26 and TP 6×
  +$34.46. In the gated census, TP 4× is +$13.70 (96 taken), TP 5× +$24.49
  (90 taken), TP 6× +$34.98 (88 taken). Wider TP continues to look better in
  these limited views; horizon and regime dependence mean this is not
  adoption-grade. **Keep live 4× TP and no BE ratchet for now.**
- **Excursions and fills:** 71 covered closed trades: TP winners n=31 have median
  MFE +2.21R / MAE −0.38R; SL losers n=40 have median MFE +0.51R / MAE −1.16R.
  A +0.50R ratchet would arm on 20/40 eventual losers and all 31/31 winners.
  On 2×/4× geometry, median SL slippage is −3.5% of 1R (worst −37.9%); TP
  overshoot median +2.7% (worst +52.7%, #122). These are simulated-feed fills,
  not XM execution measurements.
- **Filter candidates — all monitor-only:** ATR% ≥0.06 remains day-confounded
  (within-day census keep/skip −$48.95/−$30.06; clean ledger keep/skip
  +$38.04/−$25.41). RSI ≥45 remains unsupported (clean ledger +$6.38 vs
  +$6.25). Wick ratio ≤0.40 leans toward keeping the trade in both views, but
  remains one-regime evidence (clean ledger +$10.70 vs +$1.93). The two-sided
  EMA50 band is still monitor-only (post-gate ≤0.50 ATR: n=25 +$23.02 vs n=42
  +$6.24). Tightening the one-sided `MAX_BELOW_EMA_ATR` 0.30→0.15 would block
  four losing ledger rows (−$2.52), but the signal-census view disagrees; no
  gate change. A **cost-share-of-1R** cap belongs in the LIVE spread guard, not
  in a win-rate filter.
- **Blocked-signal phantoms** (`phantom_trades.py --spread 0.40`, 117 skips):
  daily halt 42 scorable → 3W/36L/3T, −$48.49 gross / −$65.29 net (protective);
  blackout 21/25 scorable → 8W/13L, +$4.02 gross / −$4.38 net (neutral-to-
  protective); cooldown 11/44 scorable → 8W/3L, +$23.24 gross / +$18.84 net
  (costly-looking, small); ATR 0/6 scorable. Overall 74 scorable, 19W/52L/3T,
  −$21.23 gross / −$50.83 net; **43/117 remain unscorable**. Keep the halt and
  do not loosen cooldown/blackouts on these samples.
- **Cost and real-world constraints:** $0.40 is one XM Asian-session sample
  (09-15 04:06 UTC), not a London/NY/weekend profile. The forward test uses the
  feed's last tick with a flat haircut; XM executes on its own CFD quotes and
  signal parity is unproven. `xm_data/` is absent in this checkout, so the quote
  logger's ≥14-day / two-weekend measurement has not started here. Keep
  `TRADING_MODE=FORWARD_TEST`; the LIVE path is not ready (§7 and
  `docs/REVIEW-2026-10-01.md` §6–7).

### What this data has not settled

| Question | Current evidence | What would settle it |
|---|---|---|
| **Live readiness** | t=+1.14 at n=67; best 5 trades = 104% of net; break-even spread $0.84; LIVE path probe 1/9 clean | Stages A–E in review 2026-10-01 §7 (fix → measure → XM demo → micro-live → scale) |
| **Open paper-trade exit handling** | BUY #125 remains active after an OHLC stop breach and an Oct 5 restart; host sampled MT5 forward-test mode, but Oct 1 mode and deployed SHA are unknown | Read-only revision/feed-unit/candle-metadata/journal checks in review 2026-10-05; then test the confirmed exit path and reconcile from ordered history |
| Bar timeframe / execution cost | M5 cost ≈24% of median post-gate 1R; $0.40 is one Asian-session sample | XM quote logger (`docs/XM-LOGGER.md`; built, awaiting install) for ≥14 days incl. 2 weekends, plus multi-regime M5/M15/H1 backtest |
| BUY vs SELL | post-gate BUY +$31.36 / SELL −$2.10 net; raw census is cascade-ignorant | per-side data from the demo stage; do not use the unfiltered census alone |
| Cooldown and blackouts | cooldown +$18.84 on 11 scorable; blackout −$4.38 on 21; 43 of 117 skips unscorable | more log coverage before changing either gate |
| TP / BE | TP 5–6× beats live in both current replay views; BE views disagree | prospective collection and a multi-regime re-cut |
| EMA50 band / wick | modest ledger splits; views/cutoffs remain sensitive | continue monitor-only logging; no gate change |

## 6. Tooling (run in this order on every data drop)

```bash
python3 tools/handoff_check.py                     # 0. is this file still true? ("HANDOFF FRESH")
python3 tools/check_data.py                        # 1. integrity gate — FIRST ("0 fail")
python3 tools/win_rate_report.py --spread 0.40     # 2. baseline/eras/slices/filters/cost
python3 tools/pathwalk_sims.py --spread 0.40 --census  # 3. exit-rule replay (validates itself first)
python3 tools/analyze_losers.py --spread 0.40      # 4. winner/loser feature drift + stop grid
python3 tools/validate_gates.py                    # 5. replay entry gates vs all historical trades (gross)
python3 tools/phantom_trades.py --spread 0.40      # 6. what did the blocked signals actually do?
python3 tools/smoke_test.py                        # 7. engine + sidecar regression tests (scenarios A–M)
python3 tools/live_readiness.py --spread 0.40      # 8. evidence + go/no-go gates for LIVE (seeded, ~1 s)
python3 tools/live_path_probe.py                   # 9. LIVE order-path probe vs a fake MT5 (exit 1 until fixed)
python3 tools/xm_quote_report.py                   # 10. XM logger: spread by session, cost on real trades, feed parity (needs xm_data/)
```

**`--spread 0.40` is the measured XM BTCUSD round trip at 0.01 lot** (§9). The
tools default to `--spread 0` (i.e. gross), so a command copied without the flag
silently produces numbers $0.40/trade more optimistic than this file's — that is
why `handoff_check.py` fails the doc if any command block disagrees with the
snapshot's `spread_usd_per_trade`. `validate_gates.py` takes no spread flag and
prints **gross** ledger sums. `live_readiness.py` is the one exception: it
*defaults* to 0.40 (a go/no-go on gross numbers would be misleading) and prints a
warning if you pass `--spread 0`. `live_path_probe.py` never touches a real
terminal, the network, Telegram or `/opt/bitcoin` (fake MT5, temp dirs).

Expected first lines at the snapshot (a mismatch means the data moved — refresh
the block, then re-read the prose):

```
win_rate_report - 125 trades, 7668 M5 bars (2026-09-07 20:20:00 -> 2026-10-05 03:00:03), spread $0.40/trade
pathwalk_sims  - 125 trades, 7668 M5 bars (...), horizon 240 min, spread $0.40/trade
analyze_losers - 125 trades (123 from 09-05), 71 log-covered, 7668 M5 bars
live_readiness - 67 post-gate trades (entries >= 2026-09-10) of 125 total, 7668 M5 bars, spread $0.40/trade, seed 2026
== result: 0 fail, 64 warn ==
```

All read-only except the engine's own self-healing migration and
`handoff_check.py --update` (which touches this file's snapshot block only).
**The analysis core is `tools/replay_lib.py`** — one walk implementation
(direction-safe, SL-first tie-break, BE-aware, horizon + TIME mark, cascade
replay) that every tool imports. **Never hand-roll a bar walk**: gold's
equivalent tool shipped with a SELL excursion inversion that made it validate
itself against its own bug. `pathwalk_sims.py` prints its agreement rate with the
engine *first* (71/71 for the log-covered closed trades) and `smoke_test.py` Scenario I
locks the direction/ratchet/horizon rules.

## 7. Next steps (in order)

> **Status (re-checked 2026-10-05).**
> - **Immediate: leave historical #125 untouched, but prevent repeats.** The
>   saved M5 path records an SL breach on 10-01 07:20 while local and host status
>   still show #125 active at 10-05 03:02:16 after restart. Later host evidence
>   strongly supports MT5 forward-test mode for that trade (`mt5feed-btc.service`
>   active; Oct 1 journal showing Twelve Data startup then MT5-feed startup with
>   no later engine restart in the supplied window; current deployed checkout
>   `aa506c0...`, a docs-only merge). This session adds the future-simulation fix
>   only: on each accepted closed MT5 M5 candle, an already-open simulated trade
>   is checked against candle OHLC before signal evaluation; BUY uses low/high vs
>   SL/TP, SELL mirrors it, ties resolve to SL first, stop gaps fill at the candle
>   open, target touches fill at the target, and a candle opened at its own close
>   cannot self-exit. Do **not** hand-edit the ledger/status or invent a fill for
>   #125; see `docs/REVIEW-2026-10-05.md`.
> - **Stage B-i logger — built, awaiting on-box validation.** No `xm_data/` is
>   present in this checkout. The ≥14-day clock (including 2 weekends) starts
>   at the first real `OK` row (`docs/XM-LOGGER.md` §3).
> - **Stage A — next engine-changing PR after this one.** This session already
>   covers the MT5 forward-test exit path; keep the remaining MT5 server-time
>   dedup/restart work (item 9) and any LIVE-path changes in separately reviewed
>   steps. Every merge restarts the engine.
> - **No real-money order** before Stage A's LIVE probe exits 0 and Stage B has
>   ≥14 days. The staged-path thresholds in review §7 remain proposals until
>   the user says otherwise.
> - **Remaining evidence gap:** the exact engine SHA at the 10-01 07:20:11 stop
>   breach was not supplied. The current deployed SHA and journal context make the
>   MT5 omission the best-supported explanation, but they do not justify
>   retroactively writing a guessed close.

1. **Do not enable LIVE. Follow the staged path** (`docs/REVIEW-2026-10-01.md`
   §7; thresholds there are proposals the user has not yet accepted):
   **A** fix the order path (findings 1–7, 9 in review §6: close detection by
   `position=`, restart reconciliation against `positions_get`/`MAGIC_NUMBER`,
   spread guard as a share of 1R + hard $ cap, filling mode from
   `symbol_info()`, `None`-result handling, one position per magic) and design a
   Wine order-executor sidecar (the Linux engine cannot import `MetaTrader5`);
   add LIVE smoke scenarios and kill switches (equity floor −$30 at 0.01 lot,
   `trade_allowed`/demo-vs-real check, manual halt file, position-aware
   dead-man alarm); exit = `live_path_probe.py` exits 0. **B** measure (item 2).
   **C** XM demo account through the real order path: ≥30 closed trades and ≥2
   weekends, parity ≥90%, 0 orphaned/missed exits, median all-in cost ≤$0.60.
   **D** micro-live: 0.01 lot, hard stop −$30, weekdays only, ≥50 trades.
   **E** no scale-up before ≥100 live trades with a positive lower-80% bound.
   Earliest sensible micro-live: ~5–6 weeks. Make `TRADING_MODE` an env var
   (default `FORWARD_TEST`) so a demo/live run is configuration, not a code edit
   autosync would overwrite.
2. **Stage B — measure, zero risk:** (i) **spread logger — built (this PR),
   awaiting install**; exit = `xm_quote_report.py` prints `Stage B-i exit: MET`
   (≥14 complete UTC days incl. 2 complete weekends, blackout windows covered);
   then decide the session-aware `--spread` and the weekend rule **from its
   report** (`docs/XM-LOGGER.md` §4 reading guide), not from the proposals;
   (ii) test signal parity with the Twelve Data era — the logger already records
   shadow XM M5 candles beside the current feed (no era split) and back-fills
   them, so **candle-level parity (match rate, wick-gate agreement, time-shift
   scan) is readable on install day**; **signal-level parity — feed
   `engine.evaluate_candle` the shadow candles, as `smoke_test.py` does with
   synthetic ones — is still to build**; the alternative (forward test on
   `DATA_SOURCE=MT5` for ≥14 days) would be a new era boundary — record it in §9;
   (iii) a multi-regime offline backtest of the frozen rules on public BTC
   history (M5 vs M15/H1, %-based costs — no network in the last session's
   sandbox); (iv) log spread-to-1R, weekend flag and side on every
   signal/skip row (monitor-only).
3. **Bar timeframe decision (M5 vs M15 vs H1 vs H4) — still the primary
   economics blocker.** On the 67-trade post-gate slice, the $0.40 round trip is
   24% of median 1R (about $1.66), with a 41.4% approximate cost-adjusted
   breakeven rate versus 43.3% observed (Wilson 32.1–55.2); the break-even
   round trip is $0.84. That interval is not proof of an edge. Item 2(iii) is
   the way to settle it; do not tune M5 first.
4. **Confirm swap/commission and the full contract spec on the XM terminal.**
   Partly automated now: the logger's `symbol_spec.json` records execution and
   filling modes, stops/freeze level, volume step, swap and demo-vs-real once the
   sidecar runs. Still manual: **commission** (not in `symbol_info()`; Stage C
   deals) and realised swap/slippage. An XM FAQ reports a **Saturday 10:05–10:35
   server-time crypto maintenance window** (unverified — the report lists runs of
   stale quotes). Sources disagree on crypto swap; the $0.40 model assumes
   spread-only.
5. **Keep collecting rather than retuning.** The next milestone is 100 strictly
   post-gate trades (67 today, ~22/week): re-run `python3 tools/live_readiness.py
   --spread 0.40` and read the gates. No exit or entry parameter change is
   justified by the current sample.
6. **Keep the two-sided EMA50 distance and the wick ratio monitor-only.** Both
   are reconstructable from the ledger and should be logged on signal/skip rows
   when a code change is next in scope. The old one-sided gate is a different
   question; leave `MAX_BELOW_EMA_ATR` at 0.30 (views disagree on n = 4).
7. **Grow log coverage for blocked signals.** 33 of 44 cooldown skips and 4 of
   25 blackout skips remain unscorable; overall 43 of 117 skips cannot be scored.
   The scorable cooldown slice looks costly (+$18.84 on 11) and blackouts look
   protective (−$4.38 on 21), but both are too small to justify changing rules.
8. **Keep the daily halt and current 1:2 geometry.** The halt's 42/42 scorable
   phantoms are 3W/36L/3T, −$65.29 net. Do not raise `MIN_ATR_PERCENT` on
   win-rate grounds (day-confounded); the cost control is the live spread guard
   (item 1). Leave TP4 and BE off until the timeframe/cost question is better
   measured.

9. **MT5-mode server-time dedup — fixed in this PR, pending deployment.**
   `tools/mt5_feed.py` now publishes a UTC `ts` using a fresh-tick offset
   estimate and retains the raw server timestamp for diagnosis; `engine.py`
   compares like with like and Scenario H covers fresh/stale +3 h offsets. After
   merge, restart `mt5feed-btc`, verify the JSON, and only then consider
   `DATA_SOURCE=MT5`. The default `TWELVEDATA` path is unaffected.

### Explicitly NOT queued (with the evidence that closed them)

- **Tightening `MAX_BELOW_EMA_ATR` (0.30 → 0.15 / 0.00)** — unresolved and not
  worth acting on: the post-gate ledger would block four losing rows (−$2.52 net),
  while the current cascade-ignorant signal-census cuts skip +$1.52 (0.15) /
  +$3.93 (0.00). The two-sided band is a different monitor-only hypothesis.
- **RSI ≥45** — still unsupported: the current takeable-signal census split is
  negative on both sides (−$58.90 keep / −$24.25 skip), and the clean ledger is
  essentially flat (+$6.38 / +$6.25); no transfer from gold.
- **ATR floor by win rate** — still day-confounded; do not treat it as spread
  control. (The cost-share-of-1R guard in item 1 is a different, first-principles
  mechanism and *is* queued — as a live safeguard, validated prospectively.)
- **Wick-ratio gate (either direction)** — census and ledger now agree in sign
  (keep better) but on one regime; monitor only.
- **TP/BE changes on M5** — wider TP and BE +1.0R look better in counterfactual
  paths, but are not adoption-grade; live remains TP4 with no ratchet.
- **Switching SELL off, or a hard weekend pause** — SELL is −$2.10 on n = 35 and
  weekends are 3W/13L on n = 16, post-hoc cuts of one regime. Test both on the
  demo account (trade everything there); pause weekends only in the micro-live
  phase, as a risk limit rather than an optimisation.
- **Direction-aware London blackout / cooldown softening / trend-side breaker**
  — no sufficient BTC evidence. Keep current hard daily halt and schedules for
  now.

## 8. How to verify code changes (always)

```bash
python3 tools/smoke_test.py                      # must print "SMOKE TEST PASSED" (A–M)
python3 -m py_compile engine.py trade_filter.py dashboard.py tools/*.py
python3 tools/check_data.py                      # expect "0 fail" (warnings are normal)
python3 tools/handoff_check.py                   # expect "HANDOFF FRESH"; --update the block if not
```

Never enable `TRADING_MODE=LIVE` as part of an unrelated change. LIVE has its
own gate (review 2026-10-01 §7): `python3 tools/live_path_probe.py` must exit 0
and the XM-demo stage must pass before LIVE is even discussed. If a change
alters a number quoted in this file, update the file in the same commit —
`handoff_check.py` catches the snapshot block but not the prose, and the prose
is where stale numbers actually hide.

## 9. Data gotchas (hard-won — read before analyzing)

- **The two 09-03 trades (−$197.63, −$197.21) are not comparable to anything
  else** — pre-port sizing (~100× lot). Exclude them from every strategy P/L
  statistic and say so. The current 125-row raw Profit sum is −$333.01 gross;
  it is not the performance of the current strategy.
- **There are THREE era boundaries, not one.** (a) 09-05: the outliers stop.
  (b) 09-06 17:49: geometry 1.5×/2.5× → 2×/4×. (c) **the gates went live
  09-10, not 09-09**: `replay_lib.PORT_DEPLOY` (09-09 02:25) is the first trade
  of the tools' "new regime" slice, but the ledger's first SELL is 09-10 09:05
  and two 09-09 BUY rows (#57 at 3.11 ATR, #58 at 0.57 ATR on the adverse side)
  violate the near-EMA gate. Use `replay_lib.GATES_DEPLOY` (09-10 00:00,
  mirrored by `check_data.GATES_LIVE`) when re-applying entry rules. The ≥09-09
  slice is fine for comparable era reporting; **do not use it to judge gate
  conformance**.
- `trades.csv` has multiple batches: `Trade_Num` restarts (21 duplicate values)
  because of pre-port balance resets. **Dedupe/join by timestamp, never by
  `Trade_Num`.** `Balance_After` has 9 continuity breaks for the same reason.
- Legacy ledger prices are comma-formatted in older rows (for example
  `"80,832.88"`); naive `float()` breaks. Every loader must strip commas (the
  `tools/` loaders do). New rows are written plain `%.2f`.
- Schema is **16 fields with `Trade_Type`**; `engine.migrate_trades_csv()`
  self-heals drift on start and before every append (keeps a
  `.bak-pre-migration` backup) and `trade_filter.load_recent_trades()` has a
  loud drift tripwire.
- **The price log starts 2026-09-07 20:20 UTC** (7,668 M5 rows through
  2026-10-05 03:00 UTC; 197 missing slots in 14 runs, including the 885-minute
  09-28/29 outage plus 35-minute 10-03 and 20-minute 10-04 gaps; causes
  unrecorded). **Only 71 of 125 closed trades are log-covered**; 54 predate the
  log, limiting any log-joined replay to the covered tail. Two minutes are
  duplicated (09-23 10:50 and 09-25 10:10: two same-OHLC rows a second apart
  with updated indicators); treat them as restart/re-evaluation warnings, not
  extra price intervals. Log rows are stamped at bar close and may carry a
  :01/:02 second offset — match trades to bars by **nearest row within 150 s /
  ±6 min**, never by exact minute. `check_data.py` reports 0 fail / 64 warn.
- **Paper fills are not XM fills.** The forward test fills at the feed's last
  tick (a ~1 Hz spot-style stream: tick volume ≈240–280 per bar all month) with a
  flat $0.40 haircut; XM will fill on its own CFD quotes with its own spread,
  basis and weekend/news behaviour. Signal parity between the two feeds is
  unproven (review 2026-10-01 §5.2).
- **Log indicators are PRE-update for that bar; ledger `*_At_Entry` values are
  POST-update** (the engine gates on post-update values). The current
  `replay_lib.enrich_log()` reconstruction matches floor 7643/7643 and ATR/RSI
  7648/7648. If the match rate is not ~100%, treat every census number as
  suspect. Never compare a raw log indicator column against a ledger entry
  column directly.
- **Dashboard funnel counters are since-restart, not lifetime.** The latest
  `status.json` snapshot (03:02:16, after restart) has
  `candles_evaluated = 0`, `all_confirmed = 0` and `sell_all_confirmed = 0`;
  use them only for post-restart context, not a lifetime signal census. Use
  `win_rate_report.py` for the reconstructed census.
- Per-trade replay must use **±6 min** windows (M5 cadence); gold uses ±2 min on
  M1. Gap threshold is >15 min (gold: >5).
- `archive/forward_test_log_m1.csv` (8,537 rows, Sep 1) is **M1** data from the
  pre-M5 design. Never mix it with the M5 log in any analysis.
- Exit reasons are `{SL, TP}` only — no `BE` rows on BTC (unlike gold). If BE is
  ever added, R-multiple math must reconstruct the original 2×/4×ATR geometry
  from `ATR_At_Entry` (1R$ ≈ 2×ATR×lot), as gold's tools do — `replay_lib`
  already keys on geometry, not on `Exit_Reason`.
- **Cost haircut:** the live terminal spread is measured at **$40.00/BTC =
  $0.40/trade at 0.01 lot** (XM, 2026-09-15 04:06 UTC, Asian session — one
  sample). Always pass `--spread 0.40`; tools default to gross (`--spread 0`).
  From 09-05 on the current clean slice is +$61.83 gross / +$12.63 net at this
  assumed flat cost. `phantom_trades.py` uses the same scaling and its outcomes
  are upper-bound counterfactuals, not fills.
- **Symbol / contract:** `BTCUSD` exists on XM MT5 with contract 1.0 / min lot
  0.01; `BTCUSDm` does not exist (`SYMBOL_MT5=BTCUSD`). The logger's
  `symbol_spec.json` re-checks both (and `0.01 lot × $100 = $1.00`) on the box.
- **Never compare an MT5 `time` to a UTC stamp.** MT5 bar/tick times are broker
  *server* time (XM: GMT+2/+3). `xm_data/` carries both: `bar_close_utc` (the
  `forward_test_log.csv` convention, UTC) and the raw `time_srv` + `offset_s`; a
  server DST change (next: Sun 25 Oct 2026) can leave bars stamped one hour off
  — `xm_quote_report.py`'s time-shift scan flags the day. `xm_data/` rows are
  live-collected data: never hand-edit them.
- `status.json` equity ($258.81) is the **engine ledger**, not the raw sum of
  Profit (−$333.01 gross, −$133.01 from $200 before spread costs). `check_data.py`
  reports the +$391.82 drift by design; see the outlier/reset notes above.

## 10. How to keep this file honest (do this every session)

### Session & Push Protocol (CRITICAL — zero unpushed state)

The sandbox workspace is **ephemeral**: when a session ends, its filesystem is
destroyed, so **a commit that is not on GitHub does not exist**. These four
rules apply to every session, from the first commit:

1. **One session = one scope = one PR at the end.** Do all session work on the
   session branch and keep pushing to it; open at most one PR per session and
   merge it only when the entire session goal is complete. Merging is the last
   click, not a mid-session step — and here merge → `origin/main` →
   `tools/autosync.sh` **deploys to the live box**, a second reason it is final.
2. **Push after every logical step (zero local-only state).** After each code or
   doc modification:
   `git add <files> && git commit -m "..." && git push origin <branch>`.
   Keep GitHub perfectly synchronized with the workspace so nothing is lost if
   the connection drops or the browser closes. Never plan to cherry-pick or
   salvage commits from a previous session's local workspace — that workspace is
   gone; anything not pushed is unrecoverable.
3. **The PR stays open (draft / in-progress) until the user gives the green
   light.** If a PR is opened early, open it as a **draft** and push additional
   commits to the same branch — GitHub updates the PR automatically. Merge only
   after the agent reports "all tasks complete, `tools/smoke_test.py` and
   `tools/check_data.py` pass, ready for merge" **and** the user confirms.
4. **Hand off via this file + `archive/PROJECT_LOG.md`, not chat.** Before a
   session ends (and always before a PR merges), the snapshot block, §1/§4/§5/§7
   and the changelog must reflect the new state, so the next session boots from
   `main` with full context — no cherry-picking, no orphan commits, no lost work.

**Opening line for a new session (no need to re-explain this workflow):**
> "Read `docs/HANDOFF.md` and follow the Session & Push Protocol in §10.
> I want to work on [X]."

### Per-session update ritual

1. **Snapshot block first, and let the machine do it**:
   `python3 tools/handoff_check.py --update` recomputes every key from the live
   CSVs. Then run it again without `--update` and require **HANDOFF FRESH**
   before you push. `tools/autosync.sh` reports the same verdict in the Telegram
   digest, so a stale handoff is visible between sessions too — a `STALE` line
   there means "start the next session with step 1". The gate tolerates ordinary
   drift (≤ 5 closed trades, ≤ 48 h of log; per-key rules in the
   `tools/handoff_check.py` header, locked by smoke Scenario J), so between
   sessions the digest normally reads `fresh, N advisory drift` and a `STALE`
   line is a real signal.
2. Update **§1** prose (what changed since the last update, the slice table,
   branch/PR state, ops notes).
3. Update **§4/§5** if params changed or a review produced new numbers —
   **replace stale figures, don't append**, and keep the "Four things this data
   has not settled" table current: it is the fastest way back into the project.
4. Move anything you shipped out of **§7** into `archive/PROJECT_LOG.md`'s
   changelog; add whatever the session queued. If you close a question, move it
   to §7's "Explicitly NOT queued" *with the evidence that closed it*.
5. Write the analysis itself in `docs/REVIEW-YYYY-MM-DD.md`; this file only
   carries the *conclusion* and a pointer. The current one is
   `docs/REVIEW-2026-10-05.md` (the latest **data/exit-state delta**) and
   `docs/REVIEW-2026-10-01.md` (the full **live-readiness** review). Add future
   deltas to the dated data review unless the question changes again.
   `docs/REVIEW-2026-09-15.md` (§13 = the 99-trade re-cut) is the earlier
   "is there an edge / what do we tune" review.
6. Never quote a pooled R total or a breakeven WR across the era boundaries in
   §9, and never quote a P/L without saying whether it is gross or net. Both
   traps have bitten this project twice.
7. Commit with a message that names the doc, so `git log --oneline` stays a
   usable index of decisions — and push immediately (protocol above).

## 11. File map (short)

`engine.py` signals/execution · `trade_filter.py` risk gates ·
`dashboard.py` port 6001 · `trades.csv` ledger (16 fields) ·
`forward_test_log.csv` M5 bars + indicators (pre-update) · `skipped_trades.csv`
blocked signals (+reason) · `status.json` live state (funnel counters are
since-restart) · `tools/replay_lib.py` shared bar-walk core + era constants ·
`tools/handoff_check.py` freshness gate for this file · `tools/live_readiness.py`
edge/cost/risk evidence + LIVE go/no-go gates · `tools/live_path_probe.py` LIVE
order-path probe (fake MT5) · `tools/mt5_quotes.py` + `tools/xm_quote_report.py` XM
quote/spec logger sidecar and its reader (`xm_data/` = its output, `docs/XM-LOGGER.md`
= its runbook) · `tools/` analysis + tests · `deploy/mt5feed.service` +
`deploy/mt5quotes.service` sidecar units · `docs/PORT-2026-09-10.md` what came from gold and why ·
`docs/REVIEW-2026-10-05.md` **latest data/exit-state delta** ·
`docs/REVIEW-2026-10-01.md` **live-readiness review** ·
`docs/REVIEW-2026-09-15.md` first data review (**§13 = the 99-trade re-cut; §12
is historical**) · `docs/AUTOSYNC.md` the unattended deploy loop +
digest guide · `archive/PROJECT_LOG.md` full history · **this file** =
executive summary.

## 12. Reading order for a brand-new agent

1. **`docs/HANDOFF.md`** (this file) — snapshot block, §1, then §5's tables
2. `docs/REVIEW-2026-10-05.md` — latest data/exit-state delta and open-trade
   finding; `docs/REVIEW-2026-10-01.md` — full live-readiness review and staged path
3. `archive/PROJECT_LOG.md` — changelog + current strategy state
4. `docs/PORT-2026-09-10.md` — what the gold port changed and why
5. `docs/REVIEW-2026-09-15.md` §13 (99-trade re-cut) and §1–§11 — the full first review (73 trades)
6. `docs/XM-LOGGER.md` — only when touching the XM/MT5 side (logger, spread, parity)
7. `git log --oneline` — what changed recently

Then run `python3 tools/handoff_check.py` and `python3 tools/check_data.py`
before drawing any conclusion from the CSVs.
