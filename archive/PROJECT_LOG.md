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
6. **Near Mean**: Close >= EMA50 - 0.3 x ATR (regime gate). NOTE this is a **one-sided** cap on
   adverse-side distance only (`MAX_BELOW_EMA_ATR`): a BUY may sit any distance *above* EMA50. It is
   not a two-sided band, and the two quantities measure differently - see the 2026-09-16 entries.
7. **RSI Filter**: RSI is between 40.0 and 70.0.
8. **ATR Filter**: ATR > 0 (engine floor disabled; %-based bounds enforced in `trade_filter.py`).
9. **Trade Filter**: Passes `trade_filter.py` checks (no blackouts, no SL cooldown, daily-loss breaker not tripped).

SELL is the mirror: 20-bar ceiling test, upper-wick rejection >= 15%, close below ceiling, EMA50 < EMA200, EMA50 falling, close <= EMA50 + 0.3 x ATR (same one-sided cap), RSI between 30.0 and 60.0.

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
- **[2026-10-05] BUY #125 exit-state verification — documentation only; no production change.**
  Refreshed `docs/HANDOFF.md` and `docs/REVIEW-2026-10-05.md` from the current
  checkout (7,668 M5 rows through 03:00:03 UTC; status snapshot 03:02:16) and
  operator-pasted host output. The host reports `DATA_SOURCE=MT5`, an active
  `bitcoin-engine.service` with a FORWARD_TEST (MT5 feed) startup, and a restart
  that restored #125 as open after loading 125 closed rows. The 10-01 07:20:11
  M5 OHLC crossed the saved SL, while the supplied journal excerpt has no close
  event. Checked-in `run_mt5_test()` lacks a position/bar exit check, making MT5
  a plausible code-level explanation **if** it was active on the deployed
  revision at the time; the Oct 1 source and deployed SHA remain unknown. Current
  MT5 mode is not evidence of a broker position, and OHLC is not an exact fill.
  The review includes read-only host checks for the deployed SHA, direct
  `mt5feed-btc.service` state, safe candle timestamps and Oct 1 startup/feed-mode
  journal lines. Do not edit the status/ledger, deploy a fix or enable LIVE while
  those checks are pending. This documentation-only change is in open draft PR #13;
  do not merge until the host output is reviewed and the user approves.
- **[2026-10-01] XM quote + contract-spec logger (review §7 Stage B-i) — new read-only Wine sidecar; no engine,
  strategy, parameter or `DATA_SOURCE` change** (`docs/XM-LOGGER.md`, `tools/mt5_quotes.py`,
  `tools/xm_quote_report.py`, `deploy/mt5quotes.service`). Built because the whole edge rests on an
  unmeasured cost: break-even round trip $0.87 vs $0.40 assumed, and the $0.40 is one Asian-session sample.
  The sidecar logs XM BTCUSD bid/ask/spread every 30 s (+ a 5 s min/max spike envelope), snapshots the
  allow-listed contract spec (execution/filling modes, stops level, volume step, swap, demo-vs-real; changes
  are history-logged) and records shadow XM M5 candles **back-filled from the terminal's own history**
  (so feed parity is measurable on install day, with no era split) into `xm_data/`, which `tools/autosync.sh`
  now commits and whose liveness rides in the digest (`📈 xm logger`; one deduplicated alert if STALE).
  `tools/xm_quote_report.py` reads it: progress vs the ≥14-day / 2-weekend exit, spread by
  session/weekend/blackout/hour against the $87 break-even and the $60 cap proposal, the measured cost at the
  ledger's real entry/exit times, candle parity with a ±3 h time-shift scan, the spec. **Not yet validated on
  the real terminal** (no Wine/MT5 in the build sandbox): smoke Scenarios K (70 checks, fake terminal + fake
  clock, mutation-checked) and L (36 checks, report) lock the behaviour; `docs/XM-LOGGER.md` §3 is the on-box
  validation checklist and the 14-day clock starts at the first real `OK` row. Traps found and designed
  around: MT5 `time` is **broker server time** (XM GMT+2/+3, EU DST rule, next change **Sun 25 Oct 2026**), so
  the offset is learned only from *fresh* ticks (a tick exactly N hours old looks like a fresh tick on a
  server N hours behind) and bars are converted with the current-or-previous offset inside a plausible
  window (otherwise the bar straddling a DST change is dated an hour into the future and an hour of candles
  is dropped); `account_info()`/`terminal_info()` contain the login, balance, server and Windows user paths
  and the repo is public, so only explicit allow-lists are copied (a planted fake secret must never reach a
  file); the Wine Python writes CRLF in text mode. **Finding, not fixed (needs an `engine.py` change):**
  `mt5_feed.py` publishes the raw server-time `ts` while `engine.run_mt5_test` seeds its dedup from the
  UTC log stamp, so with XM's +2/+3 h server each restart in `DATA_SOURCE=MT5` mode re-logs the last bar once
  (the default Twelve Data path is unaffected); queued with Stage A. Verified with a throwaway bare remote:
  the data commit includes `xm_data/` (no `.tmp` junk), a conflicting `xm_data` edit resolves server-wins
  while upstream code lands, the STALE alert fires once, dedupes and re-arms.
- **[2026-10-01] Live-readiness review; documentation + two read-only tools — no engine, strategy or parameter change**
  (`docs/REVIEW-2026-10-01.md`, `docs/HANDOFF.md`). Autosync snapshot `data collection 1937` is through
  2026-10-01 02:05 UTC: 124 closed rows (54W/70L), 70 post-port / 66 strictly post-gate, open simulated
  SELL #124. Verdict: **not ready for real money**. Strictly post-gate is 29W/37L (43.9%, Wilson
  32.6–55.9), +$57.44 gross / +$31.04 net, t = +1.22 (day-block bootstrap 85% positive; ~350 trades to
  confirm); the 25 trades since the 09-24 snapshot are 10W/15L, +$0.78 net (21 at 6W/15L, then four straight
  wins); break-even round trip is $0.87 vs $0.40 assumed; the best 5 trades are 98% of net. Post-hoc
  hypotheses (not parameters): BUY +$31.36 vs SELL −$0.32 net, entry ATR < $60 → 2W/11L, weekends 3W/13L.
  The LIVE order path fails 8 of 9 offline probes (SL/TP closes never detected — `ticket=` vs `position=`;
  a restart orphans the position; no spread guard; FOK hard-coded; `None` result crashes; no
  duplicate-position check) and the Linux engine cannot import `MetaTrader5`. Also found: an
  **885-minute feed outage 09-28 17:50 → 09-29 08:35** (the handoff had said no gap > 15 min). New tools:
  `tools/live_readiness.py` (edge/cost/fragility/Monte Carlo/latency stress/gates, seeded, default
  `--spread 0.40`) and `tools/live_path_probe.py` (fake-MT5 probe of engine.py's LIVE path). `TRADING_MODE`
  untouched. Staged path (fix → measure → XM demo → micro-live → scale) in review §7.
  Also fixed (same PR): `tools/handoff_check.py` cried wolf — four moving keys (`log_last_bar_utc`,
  `open_trade`, `wins_losses`, `win_rate_pct`) were exact-match and the log tolerance was 60 rows (5 h),
  so the autosync digest read `STALE` within one bar of any refresh and a doc one trade behind was
  already STALE, contradicting the "5 trades / 48 h, must not cry wolf" design. Each key is now judged
  by what moves it; `BAR_TOLERANCE` 60 → 576 rows (= `MAX_AGE_HOURS`, tunable). Still STALE: > 5 trades
  behind, > 48 h of log, outcomes changed without a new trade (ledger edited), a snapshot *newer* than the
  data (lost data), a changed `--spread`. Locked by smoke Scenario J (13 checks; 6 fail on the old code).
- **[2026-09-24] 99-trade forward-test re-cut; documentation only**
  (`docs/REVIEW-2026-09-15.md` §13, `docs/HANDOFF.md`). Autosync snapshot
  `data collection 1301` is through 2026-09-23 20:35 UTC: 99 closed rows,
  44W/55L, 45 post-port / 41 strictly post-gate, and an open simulated SELL #99.
  Clean 09-05-on results are +$52.43 gross / +$13.63 net at the measured $0.40
  cost; strict post-gate is 19W/22L, +$30.26 net, still too uncertain to
  establish an edge. The 30-trade review milestone is met. TP5/TP6 replay
  results are stronger but counterfactual; no code, strategy, or parameters
  changed. `check_data.py` reports 0 fail / 62 warn; daily halt phantoms remain
  protective, while cooldown/blackout reads are small and incomplete.
- **[2026-09-17] autosync Telegram flood fixed: `NOTIFY=alerts` (new default) + `off`, one daily summary digest.**
  At the 15-min cron the old default (`always`) sent ~96 digests/day, and `quiet` did not help on
  BTC: a new M5 bar lands every 5 minutes, so "data changed" is the normal case and quiet still
  fired almost every run. `tools/autosync.sh` phase 5 now has four policies — `alerts` (default:
  deploys, incident/state *changes*, and ONE `(daily)` summary digest per UTC day), `off` (never
  message, including the early FATAL paths), `always`/`quiet` (unchanged old behaviour). Repeat
  suppression: a persistent failure (dead push credentials, wedged merge, missing dir) messages
  once via `alert_once`/`ALERT_STAMP` until the state changes — a clean run re-arms it — so a
  stuck incident cannot re-flood every 15 min but stays visible in the daily summary. Stamps live
  in `/tmp` (`DAILY_STAMP`/`ALERT_STAMP`), so a reboot can repeat one digest at worst. The 15-min
  sync cadence itself was kept deliberately: 24/7 M5 feed → 3-bar data-loss window (vs 36 bars at
  the gold bot's 3-hour cadence) and ≤15-min deploy latency after a merge. Decision log + tuning
  table: `docs/AUTOSYNC.md` §5; HANDOFF §1 Operations updated, snapshot refreshed to 80 trades.

- **[2026-09-16] `docs/HANDOFF.md` reviewed, re-cut at 78 trades, and made machine-checkable.**
  The handoff had drifted a day behind the box (autosync had taken it from 73 to 78 closed trades)
  and carried four defects that would have misled the next session:
  (1) every headline number was the 09-15 one; (2) §1 hard-coded a *previous* session's branch name
  (`arena/01a0a350-…`) as "current work branch"; (3) §6's copy-paste command block still said
  `--spread 0.25` while §1/§9 said the measured cost is $0.40, so following the doc reproduced
  numbers that did not match the doc; (4) §5/§7 queued "entry within 0.15 ATR of EMA50
  (candidate: tighten `MAX_BELOW_EMA_ATR`)" — a **two-sided** measurement labelled as a change to a
  **one-sided** gate (see the next entry: acting on it would have cost money).
  Structure changes: a machine-checked **snapshot block** at the top (the only part parsed by code),
  a "what changed since the last review" delta list, a single slice table with gross **and** net
  columns, an explicit numbers convention (everything is net of $0.40 unless marked gross), a
  "four things this data has not settled" tension table, expected tool first-lines in §6 so a stale
  doc is visible at a glance, and the era-boundary/pre-vs-post-update-EMA/funnel-counter gotchas in
  §9. Section numbering (§1–§12) is unchanged because `check_data.py`, `win_rate_report.py` and
  `pathwalk_sims.py` cite §7/§9 in their output.
- **[2026-09-16] New `tools/handoff_check.py` + handoff line in the autosync digest** — the
  mechanism behind "always update the handoff". It recomputes every snapshot key from
  `status.json` / `trades.csv` / `forward_test_log.csv` / `skipped_trades.csv` (via `replay_lib`, so
  it cannot disagree with the analysis suite), reports `HANDOFF FRESH` / `HANDOFF STALE` with
  per-key deltas, refuses a doc whose command blocks quote a different `--spread` than the snapshot's
  cost assumption, verifies that every referenced `docs/`/`tools/`/`archive/` path exists, and
  rewrites the block in place with `--update` (prose is never touched). Tolerances: 5 trades /
  60 log rows / 48 h, so a doc that is one trade behind does not cry wolf. Exit 0/1/2.
  `tools/autosync.sh` gained phase 4b, which runs it `--quiet` and adds `📝 handoff: …` to the
  Telegram digest — **advisory only**: it never blocks a deploy, never rolls back, and never touches
  the 🚨/⚠️ paths (a doc 6 trades behind is not an incident, and nagging 4×/h would get the digest
  muted). Documented in `docs/AUTOSYNC.md` §1–§3. §8/§10 of the handoff now require
  `HANDOFF FRESH` before a push.
- **[2026-09-16] Data re-cut at 78 trades → `docs/REVIEW-2026-09-15.md` §12** (the question did not
  change, so the review was re-cut in place per the §10 ritual). Findings: from-09-05 slice is now
  **+$20.45 gross / −$9.95 net** (was +$11.74 / −$16.66) and the live era **+$17.44 gross /
  +$7.84 net** (n=24, was +$1.13 net at n=19); at the live-era median ATR of **$87.85** the $0.40
  round trip is **22.8% of 1R**, so breakeven decisive WR is **40.9%** vs an actual **41.7%** — the
  book has crossed from below its cost-adjusted breakeven to *at* it (still n=24, Wilson 24.5–61.2,
  and the M5-vs-higher-timeframe decision is unchanged). The last-10 collapse reversed (1W/9L →
  4W/6L). The **cooldown's measured sign flipped**: 7 of 40 blocks are now scorable and read
  **+$3.92 net**, i.e. it is throwing away winners on the slice the log can finally see (33 still
  predate the log; no change). Blackouts likewise read costly (+$5.87 net on 6 scorable) while the
  daily halt stays protective (−$12.13 net on 18/18). Exits moved: **wider TP (5–6×ATR) now beats
  the live 4×ATR in both cascade-aware views**, and **BE +1.0R is still the only ratchet row positive
  in all three views** (+0.50R wins the 24-trade view but loses the cascade census → noise); both
  stay deferred behind the timeframe decision. The **wick ≤0.40 candidate was demoted to unresolved**
  (census and ledger now disagree on the *sign*). A **third** stop-overshoot row appeared (#65,
  −1.22R, alongside #40/#52 at −1.38R).
- **[2026-09-16] Era-boundary fix + entry-gate conformance check.** Evidence that the ported regime
  gates went live on **09-10**, not 09-09: the ledger's first SELL is 09-10 09:05, and two of the
  four 09-09 BUY rows sit on the adverse side of the near-EMA gate (#57 at **3.11 ATR**, #58 at
  **0.57 ATR** vs `MAX_BELOW_EMA_ATR = 0.30`). Added `replay_lib.GATES_DEPLOY` (09-10 00:00) for
  anything that **re-applies an entry rule** to ledger rows, keeping `PORT_DEPLOY` (09-09 02:25) for
  era *slices* so already-published numbers stay comparable; the strictly-post-gate slice is n=20,
  8W/12L, +$14.68 gross / +$6.68 net. `tools/check_data.py` gained an **entry-gate conformance**
  block (trend / RSI window / near-EMA, from ledger fields alone, rows ≥ `GATES_LIVE`): **all 20
  pass, 0 fail, 61 warn unchanged**. That is the check that catches an unrecorded parameter change or
  a silently-skipped gate — neither was visible before.
- **[2026-09-16] `win_rate_report.py` §7: the two EMA50-distance quantities are no longer
  conflated.** The old row measured a **two-sided** band |entry−EMA50| ≤ 0.15 ATR under a label that
  said "tighten `MAX_BELOW_EMA_ATR`", which is **one-sided** (it caps only adverse-side distance).
  Both are now printed separately, on the census *and* on the post-gate ledger rows. Measured:
  **tightening the live gate hurts in both views** (census −8.66 → −11.20 at 0.15 → −18.23 at 0.00;
  post-gate ledger +6.68 → +5.49, blocking 2 winners worth +$1.19; in the live era a 0.15 gate would
  have blocked 5 trades worth **+$4.57 net**) — so it moved to the handoff's "Explicitly NOT queued".
  The **two-sided band ≤ 0.50 ATR** is the strongest surviving candidate: census keep 25 at 44.0%
  **+10.46 net** vs skip 67 at 28.4% −19.11 with a within-day control that drops **zero** signals
  (the only candidate in the lab that cannot be a calendar proxy), post-gate ledger keep 5 at 80.0%
  **+11.97 net**, live era keep 6 (5W/1L) **+16.45 net** vs skip 18 −8.61. n is far too small to
  gate on, and it needs no engine change to keep scoring (`EMA50_At_Entry`/`ATR_At_Entry`/
  `Entry_Price` are already in every row) → instrument-and-watch. Also: the one-sided rows suppress
  the within-day control (a near-universal gate makes it pure composition noise — it printed a
  +22.81 "own-day keep" for a split whose pooled keep was −11.20), and the hard-coded
  "the same candidates on the 71 real trades" label is now computed.
- **[2026-09-15] Session & Push Protocol added to `docs/HANDOFF.md` §10** — the four permanent
  workflow rules, so they no longer need to be restated at the start of every session:
  (1) one session = one scope = one PR, merged only at the end;
  (2) push after every logical step — zero local-only state, because the sandbox filesystem is
  ephemeral and unpushed commits are unrecoverable;
  (3) the PR stays open (draft) until tests pass and the user gives the green light;
  (4) hand off via `HANDOFF.md` + this changelog, not chat.
  Also fixed §10's duplicated item numbering (4/4b) and pointed §1 at the current work branch
  (`arena/01a0a350-bitcoin-trading-bot`). Docs-only change — no code, params, or strategy touched.
- **[2026-09-15] Deploy Record & Live Spread Measurement ($40.00/BTC)**.
  Measured from the live XM MT5 terminal (04:06 UTC, Asian session):
  `BTCUSD` exists with contract `1.0` / min lot `0.01` (`BTCUSDm` does not exist, so `SYMBOL_MT5=BTCUSD`).
  Spread = **$40.00/BTC flat = $0.40 round-trip at 0.01 lot**.
  Netting this cost turns the 71-trade test (09-05 on) from **+$11.74 gross to −$16.66 net**.
  Live era (n=19) is **+$1.13 net**, but **+$12.62** of that is 09-10 alone (without 09-10 it is **−$10.29 net**).
  Cause: M5 ATR ($84) is too small for a $40 spread (cost is **23.9% of 1R**, requiring 41.3% WR vs 36.8% actual).
  Timeframe re-cut: M5 24.0% of 1R, M15 11.9%, H1 5.4%, H4 2.6%.
  The dominant decision is **bar timeframe**, not BE/TP tuning (BE/TP tuning deferred).
  Deploy path documented in `docs/AUTOSYNC.md` and verified live via `autosync.sh`.
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

Current local snapshot/review: CSV data through **2026-10-05 03:00:03 UTC**
(7,668 M5 rows), with `status.json` updated at 03:02:16; see `docs/HANDOFF.md`
and the 2026-10-05 data/exit-state delta `docs/REVIEW-2026-10-05.md`.
`docs/REVIEW-2026-10-01.md` remains the full live-readiness review and staged
LIVE path. These are paper-forward-test results, not realized brokerage P/L.
The checkout does not contain `/opt/bitcoin/.env`, systemd state or journals;
the operator has pasted a limited host snapshot (current MT5 forward-test mode
and restart state), which cannot establish the Oct 1 feed or deployed revision.

- **Important operations finding — simulated BUY #125 remains open after a logged
  stop breach.** Local `status.json` at 2026-10-05 03:02:16 and the operator's
  host snapshot both show BUY #125 active (entry 2026-10-01 07:10:10 at
  $84,177.15; SL $84,008.74; TP $84,513.98), with no close row. The 07:15 M5
  low ($84,035.75) stayed above the stop; the 07:20:11 candle low was $83,838.25
  and close $83,841.65, below the stop. This establishes a recorded OHLC breach,
  not an executable fill. Host output sampled `DATA_SOURCE=MT5` on Oct 5 and
  reported an active engine started in FORWARD_TEST (MT5 feed); after restart it
  loaded 125 closed rows and restored #125 open. That is simulator state, not a
  broker position, and does not prove MT5 was the feed on Oct 1. The checked-in
  `run_mt5_test()` evaluates candles without `check_position()`, a plausible
  explanation only if the deployed revision and historical feed match; the
  deployed Git SHA and source-switch date remain unknown. The Twelve Data path
  checks ticks but silently catches callback exceptions. The supplied journal
  excerpt has no close/SL event at the breach. Run the read-only checks in
  `docs/REVIEW-2026-10-05.md`; do not guess a fill or edit status/ledger. Keep
  `TRADING_MODE=FORWARD_TEST`; no broker position is evidenced.
- **Current ledger:** 125 closed rows, 54W/71L (43.2%). Raw Profit totals
  −$333.01 gross, or −$133.01 from the $200 start before spread costs; engine
  equity $258.81, a +$391.82 history/reset gap. Exclude the two 09-03 sizing
  outliers (−$197.63 and −$197.21) from strategy statistics. From 09-05 onward:
  123 trades, 54W/69L, +$61.83 gross / **+$12.63 net** at $0.40/trade.
- **Current gates have 67 strictly post-gate trades** (entries ≥09-10):
  29W/38L, 43.3%, +$56.06 gross / **+$29.26 net**. Wilson 95% interval
  32.1–55.2%; t=+1.14; day-block bootstrap 83% positive; estimated
  cost-adjusted break-even is 41.4% WR / $0.84 round trip. The best five trades
  are 104% of net (−$1.27 without them). This is a positive but **unproven**
  point estimate. The 100-trade sample gate and 90% bootstrap gate still fail.
- **Recent performance:** last 25 closed trades 10W/15L, +$12.82 gross / +$2.82
  net; last 10 are 6W/4L, +$17.85 gross / +$13.85 net. The best-five result
  still makes the evidence fragile; keep collecting rather than retuning.
- **Accounting is history-split:** raw Profit and engine ledger still differ by
  $391.82; do not use the engine balance as cumulative true P/L. Current
  geometry slice from 09-06 17:49 is n=88, 39W/49L, +$60.61 gross / +$25.41
  net; never pool R totals or breakeven WR across geometry eras.
- **Integrity:** `check_data.py` reports 0 fail / 64 warnings. The local M5
  log has 7,668 rows through 10-05 03:00:03, 197 missing slots in 14 runs,
  including gaps of 885 min (09-28/29), 35 min (10-03) and 20 min (10-04); two
  repeated minutes remain. Status updated at 03:02:16, 2 min 13 s after the last
  bar; status/ledger counts agree. 71/125 closed rows are log-covered and replay
  agrees 71/71 on those closed outcomes. This replay does not resolve #125.
- **Risk gates:** all 117 skip rows remain; daily-halt phantoms are 3W/36L/3T,
  −$65.29 net; blackouts −$4.38 net on 21 scorable; cooldown +$18.84 on 11
  scorable; 43 skips remain unscorable. Do not relax gates on these small
  samples.
- **LIVE readiness:** `tools/live_readiness.py` passes 3/6 data gates;
  `tools/live_path_probe.py` passes 1/9 (4 BLOCKER, 3 HIGH, 1 ADVISORY), and the
  Linux engine cannot import `MetaTrader5`. Not ready; do not switch to LIVE.
  The readiness failures still include inadequate sample/bootstrap evidence
  and the historic 885-minute feed gap.
- **XM quote logger:** built, but there are no `xm_data/` files in this checkout;
  `tools/xm_quote_report.py --quiet` says “not collecting yet”. The ≥14-day
  logger clock has not started here.
- **Freshness gate:** `tools/handoff_check.py` uses ≤5 closed trades / ≤48 h
  tolerances. The snapshot was refreshed to 2026-10-05 03:02 / latest bar 03:00;
  it reports `HANDOFF FRESH` with 0 advisory drift after the prose update. Smoke
  Scenario J continues to lock the tolerance behavior.

## Future Tweaks / To-Do
- [x] First data review (73 trades) -> `docs/REVIEW-2026-09-15.md`.
- [x] 30-trade review milestone; re-cut at 99 closed rows -> `docs/REVIEW-2026-09-15.md` §13 (2026-09-24).
- [x] **Measure real XM BTCUSD spread**: $40.00/BTC ($0.40/trade) measured 2026-09-15 live MT5 terminal.
- [x] Confirm `SYMBOL_MT5` (`BTCUSD` vs `BTCUSDm`) and contract size: confirmed `BTCUSD` contract 1.0, min lot 0.01.
- [ ] **Bar timeframe decision (M5 vs M15 vs H1 vs H4)** — primary blocker before tuning parameters.
- [ ] Confirm spread profile across London and NY sessions (superseded by the logger items below, which also cover weekends).
- [ ] Log the wick/near-EMA feature per signal (monitor-only) and re-read on a larger post-gate sample.
- [ ] Validate regime-gate + SELL-mirror parameters against BTC data (currently inherited from gold's review, unproven on BTC).
- [ ] Revisit `WICK_RATIO_TARGET` 0.15 (loose vs gold's 0.38) once the funnel counters show signal quality.
- [ ] Multi-Timeframe (15m/1h) higher-timeframe trend integration.
- [x] Live-readiness review at 124 closed rows -> `docs/REVIEW-2026-10-01.md` (verdict: not ready; staged path in §7).
- [x] 2026-10-05 data/exit-state recheck at 125 closed rows -> `docs/REVIEW-2026-10-05.md`; documented the stop breach, operator-pasted Oct 5 MT5 simulator/restart evidence, and unverified Oct 1 feed/revision. Read-only host checks remain pending; no engine, status, ledger or production change.
- [ ] **LIVE order-path fixes** (review §6): close detection by `position=`, restart reconciliation via `positions_get`/`MAGIC_NUMBER`, filling mode from `symbol_info()`, `None`-result handling, one position per magic; promote `tools/live_path_probe.py` checks into smoke scenarios. Exit: the probe exits 0.
- [ ] Live spread guard before order dispatch (share of 1R + hard $ cap, e.g. <= $60/BTC) and kill switches (equity floor −$30 at 0.01 lot, `trade_allowed`/demo-vs-real check, manual halt file, position-aware dead-man alarm).
- [ ] Wine order-executor sidecar (the Linux engine cannot import `MetaTrader5`); make `TRADING_MODE` an env var (default `FORWARD_TEST`).
- [x] **Built (this PR):** read-only XM quote + contract-spec logger as a Wine sidecar (`tools/mt5_quotes.py`, `deploy/mt5quotes.service`, `docs/XM-LOGGER.md`) with shadow XM M5 candles, `tools/xm_quote_report.py` and the autosync wiring.
- [ ] **Install and validate the logger on the box** (`docs/XM-LOGGER.md` §3: `--spec`, `--once`, install `mt5quotes-btc`; first confirm which `DATA_SOURCE` the box runs and that the Wine terminal + `mt5feed-btc` exist). The ≥14-day clock (incl. two weekends) starts at the first real `OK` row; exit = `python3 tools/xm_quote_report.py` prints `Stage B-i exit: MET` -> session-aware `--spread`, weekend rule, and the real filling mode / stops level for Stage A.
- [ ] Signal parity with the Twelve Data era: the logger now records (and back-fills) shadow XM M5 candles beside the current feed (no era split), so **candle-level** parity is readable on install day; still to build: **signal-level** parity (feed `engine.evaluate_candle` the shadow candles). The alternative — forward test on `DATA_SOURCE=MT5` for >= 14 days — is a new era boundary.
- [ ] **Fix the MT5-mode server-time dedup** (`engine.run_mt5_test` compares a server-time candle `ts` with a UTC log stamp, so a restart re-logs the last bar once; `docs/XM-LOGGER.md` §6). Only matters if `DATA_SOURCE=MT5`; do it in a PR that may restart the engine (Stage A or the data-source decision) and add a smoke scenario with a non-zero offset.
- [ ] Multi-regime offline backtest of the frozen rules on public BTC history (M5 vs M15/H1, %-based costs).
- [ ] XM demo run through the real order path: >= 30 closed trades and >= 2 weekends, parity/cost criteria in review §7 Stage C.
- [ ] Agree micro-live terms in writing (0.01 lot, −$30 hard stop, weekdays only, >= 50 trades) before any real-money order.
- [ ] Investigate the 09-28/29 885-minute outage cause (`journalctl` on the box) and add a position-aware stale-feed alarm.
- [x] `tools/handoff_check.py` judges each key by what moves it (≤ 5 trades / ≤ 48 h, no more exact-match on moving keys); smoke Scenario J (2026-10-01).
