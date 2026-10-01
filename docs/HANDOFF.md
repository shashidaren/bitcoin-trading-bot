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
| as_of_utc | 2026-10-01 02:05 |
| data_collection | 1937 |
| closed_trades | 124 |
| wins_losses | 54W/70L |
| win_rate_pct | 43.5 |
| engine_ledger_usd | 260.19 |
| true_equity_usd | -131.63 |
| live_era_trades | 70 |
| live_era_net_usd | +32.20 |
| log_covered_trades | 70 |
| log_bars | 6518 |
| log_last_bar_utc | 2026-10-01 02:05 |
| skip_rows | 117 |
| open_trade | SELL #124 @ 83602.0 |
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

## 1. Where things stand (data as of 2026-10-01 02:05 UTC; review re-cut 2026-10-01 at 124 closed trades)

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
- **Reviews:** `docs/REVIEW-2026-10-01.md` is the 2026-10-01 **live-readiness**
  review at 124 closed trades; it is the provenance for the evidence in §5 below
  and for the LIVE verdict. `docs/REVIEW-2026-09-15.md` §13 is the historical
  99-trade re-cut (§12 the 78-trade one).

**LIVE verdict (2026-10-01): not ready for real money.** The forward test is
promising but unproven (strictly post-gate t = +1.22 at n = 66; the best 5 trades
are 98 % of net), the margin over the measured cost is thin (break-even round
trip $0.87 vs $0.40 assumed), and the LIVE order path fails 8 of 9 offline probes
and cannot even import `MetaTrader5` on the Linux box. The staged path to a
capped micro-live pilot (fix → measure → XM demo → micro-live, ~5–6 weeks at the
soonest) is in `docs/REVIEW-2026-10-01.md` §7 and §7 below. `tools/live_readiness.py`
re-scores the evidence gates on any data drop (3/6 pass today).

### The book in one table (net of $0.40/trade; gross in brackets)

| Slice | n | W/L | WR | net | gross | net/trade |
|---|---:|---:|---:|---:|---:|---:|
| from 09-05 (exclude the 09-03 sizing outliers) | 122 | 54/68 | 44.3% | **+14.41** | [+63.21] | +0.12 |
| live geometry (≥09-06 17:49, RR 1:2) | 87 | 39/48 | 44.8% | +27.19 | [+61.99] | +0.31 |
| "new regime" (≥09-09 02:25, tool boundary) | 70 | 31/39 | 44.3% | **+32.20** | [+60.20] | +0.46 |
| **strictly post-gate (≥09-10)** | 66 | 29/37 | 43.9% | **+31.04** | [+57.44] | +0.47 |
| 25 closed since the 09-24 snapshot (exits after 09-23 20:35) | 25 | 10/15 | 40.0% | +0.78 | [+10.78] | +0.03 |
| last 10 | 10 | 6/4 | 60.0% | +14.03 | [+18.03] | +1.40 |

The slices overlap. The 70-trade post-port slice includes four 09-09 rows before
the gates actually went live; use the 66-trade ≥09-10 slice when judging today's
gates. Do not use a pooled R total or one pooled breakeven rate across the
09-06 17:49 geometry change.

The raw Profit column sums to **−$331.63 gross** across all 124 rows, giving a
ledger reconstruction of **−$131.63 from the $200 start before spread costs**.
The engine ledger reads **$260.19**; the **$391.82** gap is the known 09-03
sizing monsters (−$197.63 and −$197.21) plus pre-port balance resets, not a new
live accounting failure. Exclude the two outliers from every strategy P/L
statistic. The ledger models no cost; the clean 09-05-on book is +$63.21 gross /
**+$14.41 net** at the measured $0.40 round trip.

### What changed since the 2026-09-24 re-cut (99 → 124 trades)

1. **The promising run flattened.** The 25 trades closed since the snapshot are
   10W/15L, **+$0.78 net** (+$10.78 gross): the first 21 are 6W/15L (−$13.59),
   then four straight wins on 09-30 (+$14.37). The previous "last 10 = 7W/3L,
   +$24.45" has rolled off; the last 10 are now 6W/4L, +$14.03. The "very
   promising" feeling is the four-win tail, which is n = 4.
2. **The edge is still not distinguishable from zero.** Strictly post-gate n = 66:
   29W/37L, **43.9 % (Wilson 32.6–55.9), +$31.04 net**, t = +1.22, 95 % CI on
   net/trade [−0.30, +1.24]; the average trade is positive in 85 % of day-block
   resamples (a 90 % bar is not met). Confirming an edge this size takes ~350
   trades (≈ 13 more weeks at 22 trades/week).
3. **The cost margin is thin and thinning.** At the post-gate median ATR, 1R is
   **$1.67**; $0.40 is **24.0 % of 1R** (was 22.3 %), approximate cost-adjusted
   breakeven decisive WR **41.3 %** vs 43.9 % observed. Gross edge is +$0.87/trade,
   so the **break-even round trip is $0.87 ($87/BTC)**; at $0.80 the 66-trade net
   is +$4.64. $0.40 is still one Asian-session sample (§5).
4. **Hypotheses from post-hoc cuts (not parameters).** Best 5 trades = 98 % of
   net (+$0.51 without them). BUY +$31.36 (n = 32) vs **SELL −$0.32 (n = 34)**.
   Entry ATR < $60 → 2W/11L; cost share of 1R > 40 % → 1W/9L. Weekends 3W/13L
   (Fisher p = 0.023, one of ~10 looks). Details and caveats: review §3.
5. **Wider TP remains a counterfactual, not a change.** On the 70 log-covered
   trade paths and in the risk-gated census, 5×–6×ATR outscore the live 4×ATR by
   a wider margin than at 99 trades; BE ratchets disagree between views. The
   240-minute horizon and single regime keep these below adoption grade (§5).
6. **Risk-gate evidence moved.** The daily halt's blocked signals remain strongly
   losing (42 → 3W/36L/3T, −$65.29 net). Blackouts flipped from costly-looking to
   neutral-protective (21 scorable: 8W/13L, **−$4.38** net); the scorable cooldown
   slice is still a net winner (11: 8W/3L, +$18.84) but 43 of 117 skips remain
   unscorable; do not relax gates on these small slices.
7. **Data has one real incident.** `check_data.py` reports 0 failures / 64
   warnings, but the log has **one 885-minute (14.8 h) outage, 09-28 17:50 →
   09-29 08:35**, 183 missing M5 slots in 7 runs (was 6 in 5), and two repeated
   minutes (09-23 10:50, 09-25 10:10). The cause is not recorded here (check
   `journalctl` on the box). All 66 post-gate ledger rows pass current
   trend/RSI/near-EMA conformance.
8. **The LIVE path was audited for the first time.** `tools/live_path_probe.py`
   (fake MT5, documented semantics): 4 BLOCKER + 3 HIGH + 1 ADVISORY — SL/TP
   closes are never detected (`ticket=` vs `position=`), a restart orphans the
   position, no spread guard, FOK hard-coded, `None` result crashes, no
   duplicate-position check. The Linux engine cannot import `MetaTrader5` and
   the smoke test has no LIVE scenario (review §6).

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
- Feed health at this snapshot: 6518 M5 rows since 09-07 20:20 UTC, **one
  885-minute outage (09-28 17:50 → 09-29 08:35)**, 183 missing M5 slots in seven
  runs, and the two repeated minutes noted above. `status.json` is updated
  through 02:05 UTC. The forward-test simulator has an open SELL #124 at 83602.0
  (entered 01:15 UTC; SL 83735.78, TP 83334.43); the daily-loss counter reads
  0/3. The open trade is not in the closed-trade statistics.
- **The next milestone is 100 strictly-post-gate trades (66 today) and the
  staged gates in review §7 — not a retune.** Keep collecting. The timeframe
  decision, session spread profile, and stronger per-signal skip logging remain
  open.

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
re-tested it; §5 below has the 124-trade re-read).

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
  candle timestamp (a restart never re-logs the boundary candle).
  Install: `sudo cp deploy/mt5feed.service /etc/systemd/system/mt5feed-btc.service
  && sudo systemctl daemon-reload && sudo systemctl enable --now mt5feed-btc`
  — **note the `-btc` suffix; the gold bot owns plain `mt5feed.service`.**
  Env overrides: `MT5_FEED_FILE`, `MT5_FEED_SYMBOL` (default `BTCUSD`; XM has no
  `BTCUSDm` — verified 2026-09-15), `MT5_FEED_TIMEFRAME` (default `M5`),
  `MT5_FEED_POLL`. Ops check: `jq .updated_at /opt/bitcoin/mt5_last_candle.json`
  (≤2 min old). Smoke Scenario H covers the read/normalize/dedup path.
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

## 5. Evidence base (124 closed trades, 2026-09-03 → 10-01) — see review 2026-10-01

Headline: **124 rows, 54W/70L (43.5%)** including two 09-03 pre-port sizing
monsters. The raw ledger sums to **−$331.63 gross** (−$131.63 from the $200
start before costs) while `status.json` shows $260.19; the $391.82 discrepancy
is the known sizing/reset history, not a current engine accounting failure.
Exclude the 09-03 pair from every strategy statistic. From 09-05 on: **122 rows,
54W/68L, +$63.21 gross / +$14.41 net** at the measured $0.40 round trip.
Always name the slice and say gross or net.

**Do not pool across geometry.** On 09-06 17:49 UTC the ledger moved from SL
1.5×ATR / TP 2.5×ATR to 2×/4× (RR 1:1.67 → 1:2). The pre-change slice is
n=37, 15W/22L, −$393.62 gross; from the change onward it is n=87, 39W/48L,
+$61.99 gross (+$27.19 net). These are separate rule eras; never quote pooled
R totals or breakeven rates across the boundary.

- **Integrity:** `check_data.py` reports 0 fail / 64 warn. Warnings include 21
  duplicate `Trade_Num` values, 9 `Balance_After` continuity breaks, the known
  +$391.82 engine-ledger/raw-profit drift, **183 missing M5 slots in 7 runs
  including one 885-minute outage (09-28 17:50 → 09-29 08:35)**, the geometry
  boundary, two duplicate-minute re-evaluations (09-23 10:50, 09-25 10:10), and
  the fill warnings: SL overshoots #40/#52 (−1.38R), #65/#101 (−1.22R) and TP
  overshoot #122 (+3.05R vs +2.00R planned). Every ledger row from the actual
  gate boundary (09-10) passes today's trend, RSI and near-EMA checks: **66/66**.
- **Edge and cost.** The strict post-gate slice (≥09-10) is n=66, 29W/37L, 43.9%
  (Wilson 32.6–55.9), **+$57.44 gross / +$31.04 net**; t = +1.22, 95% CI on
  net/trade [−0.30, +1.24], day-block bootstrap 85% positive (iid 90%); in R:
  +0.33 gross, +0.06 net per trade. Median entry ATR gives median 1R ≈ $1.67 ⇒
  $0.40 is **24.0% of 1R** ⇒ approximate cost-adjusted breakeven decisive WR
  **41.3%**; the **break-even round trip is $0.87 ($87/BTC)**. The best 5 trades
  are 98% of net (+$0.51 without them). Stability: first 33 trades +$7.12, last
  33 +$23.92; the last 25 closed +$0.78. M5/M15/H1/H4 timeframe comparison is
  still the dominant unresolved economics question.
- **Book by direction (strictly post-gate):** BUY n=32, 16W/16L, +$44.16 gross /
  +$31.36 net (Wilson 33.6–66.4); SELL n=34, 13W/21L, +$13.28 gross / **−$0.32
  net** (Wilson 23.9–55.0). SELL has not paid for its cost yet, but 34 trades do
  not justify switching it off. The unfiltered 4× signal census (all 320 signals,
  live geometry) also favours BUY: −$3.31 net vs SELL −$49.25; it ignores
  cascade/risk gates.
- **Signal census and cascade:** 6518 logged M5 bars reconstruct 320 full
  signals (133 BUY, 187 SELL); 35 occur in blackouts, leaving 285 takeable. At
  live geometry the unfiltered, cascade-ignorant stream is 101W/189L/30T,
  −$52.57 net (−$52.24 for the 285 takeable). With one-position-at-a-time,
  cooldown, daily halt and blackout replay, the takeable census selects 77
  trades at TP 4×: 28W/42L/7T, **+$16.17 net**. This is a modelled stream, not 77
  additional real trades. Indicator reconstruction matches logged values: floor
  6498/6498; ATR and RSI 6503/6503.
- **Exit geometry** (`pathwalk_sims.py --spread 0.40 --census`): actual-outcome
  replay agrees **70/70** for the log-covered trades. In the 240-minute
  counterfactual walk and the risk-gated cascade census (all net of $0.40):

  | Rule | 70 trade paths | gated census |
  |---|---:|---:|
  | TP 4×ATR (live) | +$15.43 | +$16.17 (77 taken) |
  | TP 5×ATR | +$30.00 | +$25.21 (72 taken) |
  | TP 6×ATR | +$36.20 | +$36.27 (71 taken) |
  | BE +0.50R | +$6.01 | −$10.04 (98 taken) |
  | BE +0.75R | +$4.79 | +$0.25 (92 taken) |
  | BE +1.00R | +$16.18 | +$18.43 (84 taken) |

  `TIME` is marked to market at 240 minutes; target changes also alter holding
  time and the cascade. Wider TP keeps beating live 4× in both views, by more than
  at 99 trades — but it is a counterfactual on one regime, and TP6 means a ~33%
  hit rate and bigger drawdowns. +1.0R beats live only slightly; +0.50R/+0.75R do
  not agree across views. **Keep live 4× TP and no BE ratchet for now** (and
  change nothing before the demo stage: one variable at a time).
- **Excursions and fills:** on the 70 covered trades, TP winners have median MFE
  +2.21R / MAE −0.38R; SL losers median MFE +0.49R / MAE −1.17R. A +0.50R
  ratchet would arm on 19/39 eventual losers and all 31/31 winners. On 2×/4×
  geometry, SL slippage median is −3.6% of 1R (worst −37.9%); TP overshoot median
  +2.7% (worst +52.7%, #122). Four SLs exceed 20% of planned risk (#40/#52 at
  −1.38R, #65/#101 at −1.22R) — consistent with fast-move fills, not a sizing drift.
- **Filter candidates (net at $0.40) — all monitor-only:** ATR% ≥0.06 remains a
  day-confounded split (census own-day keep n=37 −$39.59 vs skip n=36 −$32.20,
  while the 122-trade ledger split keeps +$39.82 vs −$25.41). RSI ≥45 remains
  unsupported (census keep −$33.73 vs skip −$18.52; ledger +$8.16 vs +$6.25).
  **Wick ratio ≤0.40 now agrees in sign across views** (census keep 153 +$3.07 vs
  skip 132 −$55.32; ledger keep 47 +$12.48 vs skip 75 +$1.93; they conflicted at
  99 trades) — still one regime, log it, don't gate. The two-sided EMA50 band
  stays monitor-only (census ≤0.15 ATR keep 37 +$2.44 vs skip 248 −$54.68;
  post-gate ledger ≤0.50 ATR keep 25 at 52.0% WR +$23.02 vs skip 41 at 39.0%
  +$8.02). Tightening the live one-sided `MAX_BELOW_EMA_ATR` 0.30→0.15 is
  unresolved (ledger: would block 4 losing rows, −$2.52; census: skips +$1.14).
  Cut-dependent, small samples; do not conflate these tests. A **cost-share-of-1R**
  cut is monotone on the post-gate ledger (≤20% → 54% WR, +$1.26/trade; >40% →
  10% WR, −$0.92/trade) and is the one cut with a first-principles reason — it
  belongs in the live spread guard (review §3.1), not in a win-rate filter.
- **Blocked-signal phantoms** (`phantom_trades.py --spread 0.40`, 117 skips):
  daily halt 42 scorable → 3W/36L/3T, −$48.49 gross / −$65.29 net (protective);
  blackout 21/25 scorable → 8W/13L, +$4.02 / −$4.38 net (neutral-protective now);
  cooldown 11/44 scorable → 8W/3L, +$23.24 / +$18.84 net (costly-looking, small);
  ATR 0/6 scorable. Overall 74 scorable, 19W/52L/3T, −$21.23 gross / −$50.83
  net; **43/117 remain unscorable**. Sequential dedup is 45 estimated trades,
  +$3.71 gross / −$14.29 net — not a factual counterfactual. Keep the halt and
  do not loosen cooldown/blackouts on these samples.
- **Cost and real-world constraints:** $0.40 is one XM Asian-session sample
  (09-15 04:06 UTC), not a London/NY/weekend profile; third-party guides
  (unverified) quote $100–300 in high volatility and $100–200 at weekends against
  an $87 break-even. The forward test fills at the feed's last tick with a flat
  haircut; XM executes on its own quotes (the paper feed looks like a ~1 Hz
  spot-style stream — confirm `DATA_SOURCE`). Entry latency is *not* a problem:
  a fill 1–5 minutes late leaves the M5 re-walk flat within noise (review §5.3).
  BTC remains forward-test simulated; do not enable `TRADING_MODE=LIVE` (§7).

### What this data has not settled

| Question | Current evidence | What would settle it |
|---|---|---|
| **Live readiness** | edge t = +1.22 at n = 66; best 5 trades = 98% of net; break-even spread $0.87; order path fails 8/9 probes; no Linux MT5 | Stages A–E in review 2026-10-01 §7 (fix → measure → XM demo → micro-live → scale) |
| Bar timeframe / execution cost | M5 cost ≈ 24.0% of median post-gate 1R; $0.40 is one Asian-session sample | spread logger across sessions + a multi-regime M5/M15/H1 backtest on older BTC history |
| BUY vs SELL | post-gate BUY +$31.36 / SELL −$0.32 net; raw census BUY −$3.31 / SELL −$49.25 | per-side data from the demo stage; do not use the unfiltered census alone |
| Cooldown and blackouts | cooldown +$18.84 on 11 scorable; blackout −$4.38 on 21; 43 of 117 skips unscorable | more log coverage before changing either gate |
| TP / BE | TP 5–6× beats live in both replay views (+$30.00/+$36.20 vs +$15.43; census +$25.21/+$36.27 vs +$16.17); BE views disagree | prospective collection and a multi-regime re-cut |
| EMA50 band / wick | wick ≤0.40 now agrees in sign; band results vary by cutoff/view | continue monitor-only logging; no gate change |

## 6. Tooling (run in this order on every data drop)

```bash
python3 tools/handoff_check.py                     # 0. is this file still true? ("HANDOFF FRESH")
python3 tools/check_data.py                        # 1. integrity gate — FIRST ("0 fail")
python3 tools/win_rate_report.py --spread 0.40     # 2. baseline/eras/slices/filters/cost
python3 tools/pathwalk_sims.py --spread 0.40 --census  # 3. exit-rule replay (validates itself first)
python3 tools/analyze_losers.py --spread 0.40      # 4. winner/loser feature drift + stop grid
python3 tools/validate_gates.py                    # 5. replay entry gates vs all historical trades (gross)
python3 tools/phantom_trades.py --spread 0.40      # 6. what did the blocked signals actually do?
python3 tools/smoke_test.py                        # 7. engine regression tests (scenarios A–I)
python3 tools/live_readiness.py --spread 0.40      # 8. evidence + go/no-go gates for LIVE (seeded, ~1 s)
python3 tools/live_path_probe.py                   # 9. LIVE order-path probe vs a fake MT5 (exit 1 until fixed)
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
win_rate_report - 124 trades, 6518 M5 bars (2026-09-07 20:20:00 -> 2026-10-01 02:05:00), spread $0.40/trade
pathwalk_sims  - 124 trades, 6518 M5 bars (...), horizon 240 min, spread $0.40/trade
analyze_losers - 124 trades (122 from 09-05), 70 log-covered, 6518 M5 bars
live_readiness - 66 post-gate trades (entries >= 2026-09-10) of 124 total, 6518 M5 bars, spread $0.40/trade, seed 2026
== result: 0 fail, 64 warn ==
```

All read-only except the engine's own self-healing migration and
`handoff_check.py --update` (which touches this file's snapshot block only).
**The analysis core is `tools/replay_lib.py`** — one walk implementation
(direction-safe, SL-first tie-break, BE-aware, horizon + TIME mark, cascade
replay) that every tool imports. **Never hand-roll a bar walk**: gold's
equivalent tool shipped with a SELL excursion inversion that made it validate
itself against its own bug. `pathwalk_sims.py` prints its agreement rate with the
engine *first* (70/70 for the log-covered trades) and `smoke_test.py` Scenario I
locks the direction/ratchet/horizon rules.

## 7. Next steps (in order)

> **Awaiting the user — answer these before any code change starts**
> (raised in the 2026-10-01 review; delete this block once answered):
> (a) accept or modify the staged path and its **proposed** thresholds (review
> §7, Stages A–E);
> (b) go-ahead for **Stage A** — LIVE order-path fixes, Wine order-executor
> sidecar, spread guard, kill switches, and `TRADING_MODE` as an env var
> defaulting to `FORWARD_TEST`. Stage A never enables LIVE;
> (c) which `DATA_SOURCE` the live box runs (`/opt/bitcoin/.env` is not in the
> repo and the code default is `TWELVEDATA`, so the feed is *assumed*, not
> recorded) — it decides whether Stage B's MT5 forward run starts a new era or
> is already the baseline.

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
2. **Stage B — measure, zero risk, start now:** (i) spread logger in the Wine
   sidecar — XM bid/ask every minute for ≥14 days incl. two weekends and the
   blackout windows, then a session-aware `--spread` and weekend rule;
   (ii) run the forward test on `DATA_SOURCE=MT5` for ≥14 days (new era
   boundary — record it in §9) to test signal parity with the Twelve Data era;
   (iii) a multi-regime offline backtest of the frozen rules on public BTC
   history (M5 vs M15/H1, %-based costs — no network in the last session's
   sandbox); (iv) log spread-to-1R, weekend flag and side on every
   signal/skip row (monitor-only).
3. **Bar timeframe decision (M5 vs M15 vs H1 vs H4) — still the primary
   economics blocker.** On the 66-trade post-gate slice, the $0.40 round trip is
   24.0% of median 1R (about $1.67), with a 41.3% approximate cost-adjusted
   breakeven rate versus 43.9% observed (Wilson 32.6–55.9); the break-even
   round trip is $0.87. That interval is not proof of an edge. Item 2(iii) is
   the way to settle it; do not tune M5 first.
4. **Confirm swap/commission and the full contract spec on the XM terminal**
   (Specification tab: swap, commission, stops level, execution mode, filling
   modes, weekend maintenance). Sources disagree on crypto swap; the $0.40 model
   assumes spread-only.
5. **Keep collecting rather than retuning.** The next milestone is 100 strictly
   post-gate trades (66 today, ~22/week): re-run `python3 tools/live_readiness.py
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
9. **Make the handoff freshness gate honour its own tolerances**
   (`tools/handoff_check.py`; advisory only, so not urgent). Measured on a
   scratch copy on 2026-10-01: straight after `--update` it reads FRESH; **one new
   M5 bar later it reads STALE** (`log_last_bar_utc` is compared exactly); and a
   doc exactly **one closed trade** behind goes STALE via `wins_losses` /
   `win_rate_pct` even though `closed_trades` is inside the 5-trade tolerance.
   Four keys that move with the data (`log_last_bar_utc`, `open_trade`,
   `wins_losses`, `win_rate_pct`) are exact-match, so the "5 trades / 48 h — must
   not cry wolf" design in the script header and `docs/AUTOSYNC.md` never reaches
   them, and `BAR_TOLERANCE` (60 rows = 5 h) trips long before `MAX_AGE_HOURS`
   (48 h) can. Result: the digest's `📝 handoff:` line flips to `STALE` within
   about five minutes of every refresh, so as a *freshness* signal it carries
   nothing between sessions (it still catches a missing doc or a `--spread`
   mismatch). It is a policy choice, not a typo: decide the intended tolerances
   first, then judge those four keys by the same gaps as their numeric
   neighbours (and flag a snapshot *newer* than the data); re-run the three
   scenarios above as the test.

### Explicitly NOT queued (with the evidence that closed them)

- **Tightening `MAX_BELOW_EMA_ATR` (0.30 → 0.15 / 0.00)** — unresolved and not
  worth acting on: the post-gate ledger would block four losing rows (−$2.52 net)
  but the census view says the same cut skips +$1.14 (0.15) / +$5.23 (0.00).
  The two-sided band is a different monitor-only hypothesis.
- **RSI ≥45** — still unsupported by the census/within-day control (census keep
  −$33.73 vs skip −$18.52); no transfer from gold.
- **ATR floor by win rate** — still day-confounded; do not treat it as spread
  control. (The cost-share-of-1R guard in item 1 is a different, first-principles
  mechanism and *is* queued — as a live safeguard, validated prospectively.)
- **Wick-ratio gate (either direction)** — census and ledger now agree in sign
  (keep better) but on one regime; monitor only.
- **TP/BE changes on M5** — wider TP and BE +1.0R look better in counterfactual
  paths, but are not adoption-grade; live remains TP4 with no ratchet.
- **Switching SELL off, or a hard weekend pause** — SELL is −$0.32 on n = 34 and
  weekends are 3W/13L on n = 16, post-hoc cuts of one regime. Test both on the
  demo account (trade everything there); pause weekends only in the micro-live
  phase, as a risk limit rather than an optimisation.
- **Direction-aware London blackout / cooldown softening / trend-side breaker**
  — no sufficient BTC evidence. Keep current hard daily halt and schedules for
  now.

## 8. How to verify code changes (always)

```bash
python3 tools/smoke_test.py                      # must print "SMOKE TEST PASSED" (A–I)
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
  statistic and say so. The current 124-row raw Profit sum is −$331.63 gross;
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
- **The price log starts 2026-09-07 20:20 UTC** (6518 M5 rows through
  2026-10-01 02:05 UTC; 183 missing slots in 7 runs, **dominated by one
  885-minute outage, 09-28 17:50 → 09-29 08:35** — the only gap >15 minutes, cause
  unrecorded). **Only 70 of 124 closed trades are log-covered**; 54 predate the
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
  `replay_lib.enrich_log()` reconstruction matches floor 6498/6498 and ATR/RSI
  6503/6503. If the match rate is not ~100%, treat every census number as
  suspect. Never compare a raw log indicator column against a ledger entry
  column directly.
- **Dashboard funnel counters are since-restart, not lifetime.** Current
  `status.json` has `candles_evaluated = 413`, `all_confirmed = 2` BUY and
  `sell_all_confirmed = 5`; use them only for post-restart context, not a
  lifetime signal census. Use `win_rate_report.py` for the reconstructed census.
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
  From 09-05 on the current clean slice is +$63.21 gross / +$14.41 net at this
  assumed flat cost. `phantom_trades.py` uses the same scaling and its outcomes
  are upper-bound counterfactuals, not fills.
- **Symbol / contract:** `BTCUSD` exists on XM MT5 with contract 1.0 / min lot
  0.01; `BTCUSDm` does not exist (`SYMBOL_MT5=BTCUSD`).
- `status.json` equity ($260.19) is the **engine ledger**, not the raw sum of
  Profit (−$331.63 gross, −$131.63 from $200 before spread costs). `check_data.py`
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
   there means "start the next session with step 1". **Known quirk (§7 item 9):**
   until it is fixed that line reads `STALE` within about five minutes of any
   refresh (one new bar is enough), so run `python3 tools/handoff_check.py` for
   the real gap — `closed_trades` more than 5 behind is the case that matters.
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
   `docs/REVIEW-2026-10-01.md` (the **live-readiness** question) — keep adding
   dated deltas there unless the question changes again.
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
order-path probe (fake MT5) · `tools/` analysis + tests · `deploy/mt5feed.service`
sidecar unit · `docs/PORT-2026-09-10.md` what came from gold and why ·
`docs/REVIEW-2026-10-01.md` **live-readiness review (current)** ·
`docs/REVIEW-2026-09-15.md` first data review (**§13 = the 99-trade re-cut; §12
is historical**) · `docs/AUTOSYNC.md` the unattended deploy loop +
digest guide · `archive/PROJECT_LOG.md` full history · **this file** =
executive summary.

## 12. Reading order for a brand-new agent

1. **`docs/HANDOFF.md`** (this file) — snapshot block, §1, then §5's tables
2. `docs/REVIEW-2026-10-01.md` — the live-readiness review: newest numbers, the
   LIVE-path findings (§6) and the staged path to live (§7)
3. `archive/PROJECT_LOG.md` — changelog + current strategy state
4. `docs/PORT-2026-09-10.md` — what the gold port changed and why
5. `docs/REVIEW-2026-09-15.md` §13 (99-trade re-cut) and §1–§11 — the full first review (73 trades)
6. `git log --oneline` — what changed recently

Then run `python3 tools/handoff_check.py` and `python3 tools/check_data.py`
before drawing any conclusion from the CSVs.
