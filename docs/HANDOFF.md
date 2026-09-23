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
| as_of_utc | 2026-09-23 20:35 |
| data_collection | 1301 |
| closed_trades | 99 |
| wins_losses | 44W/55L |
| win_rate_pct | 44.4 |
| engine_ledger_usd | 249.43 |
| true_equity_usd | -142.41 |
| live_era_trades | 45 |
| live_era_net_usd | +31.42 |
| log_covered_trades | 45 |
| log_bars | 4611 |
| log_last_bar_utc | 2026-09-23 20:35 |
| skip_rows | 88 |
| open_trade | SELL #99 @ 84301.75 |
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

## 1. Where things stand (data as of 2026-09-23 20:35 UTC; review re-cut 2026-09-24 at 99 closed trades)

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
- **Reviews:** `docs/REVIEW-2026-09-15.md` §13 is the 2026-09-24 re-cut at 99
  closed trades and is the provenance for the current evidence in §5 below. §12
  remains the historical 78-trade re-cut.

### The book in one table (net of $0.40/trade; gross in brackets)

| Slice | n | W/L | WR | net | gross | net/trade |
|---|---:|---:|---:|---:|---:|---:|
| from 09-05 (exclude the 09-03 sizing outliers) | 97 | 44/53 | 45.4% | **+13.63** | [+52.43] | +0.14 |
| live geometry (≥09-06 17:49, RR 1:2) | 62 | 29/33 | 46.8% | +26.41 | [+51.21] | +0.43 |
| "new regime" (≥09-09 02:25, tool boundary) | 45 | 21/24 | 46.7% | **+31.42** | [+49.42] | +0.70 |
| **strictly post-gate (≥09-10)** | 41 | 19/22 | 46.3% | **+30.26** | [+46.66] | +0.74 |
| 19 entries since prior snapshot (≥09-17 04:05) | 19 | 11/8 | 57.9% | +29.99 | [+37.59] | +1.58 |
| last 10 | 10 | 7/3 | 70.0% | +24.45 | [+28.45] | +2.45 |

The slices overlap. The 45-trade post-port slice includes four 09-09 rows before
the gates actually went live; use the 41-trade ≥09-10 slice when judging today's
gates. Do not use a pooled R total or one pooled breakeven rate across the
09-06 17:49 geometry change.

The raw Profit column sums to **−$342.41 gross** across all 99 rows, giving a
ledger reconstruction of **−$142.41 from the $200 start before spread costs**.
The engine ledger reads **$249.43**; the **$391.84** gap is the known 09-03
sizing monsters (−$197.63 and −$197.21) plus pre-port balance resets, not a new
live accounting failure. Exclude the two outliers from every strategy P/L
statistic. The ledger models no cost; the clean 09-05-on book is +$52.43 gross /
**+$13.63 net** at the measured $0.40 round trip.

### What changed since the 2026-09-16 re-cut (78 → 99 trades)

1. **The 30-trade review milestone is past.** There are 45 rows in the tools'
   post-port slice and 41 strictly post-gate rows. The latter are 19W/22L,
   **46.3% (Wilson 32.1–61.3), +$30.26 net**. This is encouraging, not
   conclusive: its interval still includes the cost-adjusted breakeven line.
2. **The 19 newer closed rows account for +$29.99 net** (+$37.59 gross): 11W/8L
   since the previous snapshot timestamp. The last 10 are 7W/3L, +$24.45 net,
   but their median entry ATR ($131.80) is higher than the 41-trade post-gate
   median ($89.58), so larger dollar outcomes and a lower spread/R share
   contribute to the short-window result.
3. **The cost problem has not gone away.** At the post-gate median ATR of $89.58,
   1R is about $1.79; $0.40 is **22.3% of 1R**, implying an approximate
   cost-adjusted breakeven decisive WR of **40.8%**. The observed 46.3% is above
   it, but the 95% interval is wide. Timeframe and session-spread measurement
   remain ahead of parameter tuning (§7).
4. **The book now leans BUY, but don't switch off SELL.** Strict post-gate BUYs
   are 11W/10L, +$25.72 net (n=21); SELLs are 8W/12L, +$4.54 net (n=20).
   The unfiltered signal census also favours BUY, but is cascade-ignorant and
   includes signals the live stack cannot take (§5).
5. **Wider TP remains a counterfactual candidate, not a change.** On the
   45 log-covered trade paths and in the risk-gated cascade census, 5×–6×ATR
   outscore the live 4×ATR; a +1.0R ratchet is only slightly better than off.
   The 240-minute horizon, small sample and cascade effects keep these findings
   below adoption grade (§5).
6. **Risk-gate evidence is mixed.** The daily halt's blocked signals remain
   strongly losing. The scorable cooldown and blackout phantoms are net winners,
   but 42 of 88 skips remain unscorable; do not relax gates on these small slices.
7. **Data remains usable with visible anomalies.** `check_data.py` reports 0
   failures / 62 warnings, no M5 gap over 15 minutes, six missing M5 slots, and
   one repeated 10:50 minute (same OHLC, one second apart). All 41 post-gate
   ledger rows pass current trend/RSI/near-EMA conformance.

### Operations

- Live bot runs from `/opt/bitcoin/` (paths hardcoded in `engine.py` /
  `trade_filter.py`). Deploy = merge PR → autosync pulls → engine restarts.
  Restarts are safe mid-trade (open trade restores from `status.json`, stats
  reload from `trades.csv`, slope gate re-seeds from the log).
- `tools/autosync.sh` (cron, root, every 15 min) commits live data, deploys only
  if `smoke_test.py` passes (rolls back otherwise), runs the integrity gate and
  the handoff freshness check, and notifies Telegram per its `NOTIFY` policy —
  **`alerts` by default since 2026-09-17** (deploys, incident/state changes,
  and one `(daily)` summary digest per UTC day, replacing the old digest-every-
  15-min flood; `off` = silent, `always`/`quiet` = old behaviour). It
  auto-detects the engine/dashboard units by scanning systemd for units
  referencing `/opt/bitcoin`, and **it only ever pulls `origin/main`**. Install
  checklist + digest legend: `docs/AUTOSYNC.md`.
- Feed health at this snapshot: 4611 M5 bars since 09-07 20:20 UTC, **no gap
  >15 min**, six missing M5 slots in five runs, and the repeated 09-23 10:50 bar
  noted above. `status.json` is updated through 20:35 UTC. The forward-test
  simulator has an open SELL #99 at 84301.75 (entered 17:55 UTC; SL 84638.45,
  TP 83628.34); the daily-loss counter reads 1/3. The open trade is not in the
  closed-trade statistics.
- **The 30-trade milestone has been met and this review has been re-cut.** Keep
  collecting; it is not a signal to retune. The timeframe decision, session
  spread profile, and stronger per-signal skip logging remain open.

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
`TRADING_MODE=LIVE` path exists but **must not be switched on** until the live
spread check in §7.7 is in place.

**Difference from the gold bot, in one line:** BTC is M5 (gold M1), RR 1:2
(gold 1:1.5), wick 0.15 (gold 0.38), %-based ATR bounds (gold absolute $),
24/7 with no rollover blackout and no quiet hours, and **no breakeven (BE)
ratchet** — gold's BE stop is *not* ported (`docs/REVIEW-2026-09-15.md` §5
re-tested it; §5 below has the 99-trade re-read).

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
  consecutive SLs**. It is still the most-triggered gate: **41 of 88 skips**.
  The price log can score only 8 of them; those are 5W/3L, **+$12.23 gross /
  +$9.03 net**. The other 33 predate the log or cannot be reconstructed.
  This is a costly-looking small slice, not grounds to soften the cooldown.
- **Daily breaker**: `MAX_DAILY_LOSSES = 3` SLs per UTC day → hard halt for the
  rest of the day. It has 24 scorable blocked signals: **3W/21L, −$16.08 gross /
  −$25.68 net**. This remains protective; keep the hard halt. The counter reads
  a **400-row window** (`DAY_WINDOW`) because a 30-row window silently
  under-counts busy days. Pre-port loss days predate the breaker.
- **Blackouts (UTC)**: London 07:55–09:00, NY pre-market 12:25–12:45, NY open &
  US macro 13:25–15:15. They block both directions; there is no BTC evidence for
  gold's direction-aware carve-out. Of 17 logged blackout skips, 14 are
  scorable: **8W/6L, +$19.35 gross / +$13.75 net**; 3 remain unscorable. This
  currently looks costly on a small sample, so keep the schedule pending more
  coverage. No rollover blackout and no weekend pause.
- **ATR bounds (% of price)**: `MIN_ATR_PERCENT = 0.0001` (0.01%),
  `MAX_ATR_PERCENT = 0.0060` (0.60%). Six ATR skips are logged; none is
  scorable from the current price log. The floor is not a cost control: keep the
  measured-spread/timeframe decision separate from a win-rate filter.
- **Near-EMA gate is ONE-SIDED**: `MAX_BELOW_EMA_ATR = 0.30` caps how far the
  entry may sit on the *adverse* side of EMA50 (below for BUY, above for SELL).
  It does **not** cap favourable-side distance and is not a two-sided band.
  Tightening it remains measured-negative; the two-sided band is a separate,
  monitor-only candidate (§5, §7).
- **Slope gate**: EMA50 vs 30 bars ago, both directions; `ema50_history`
  re-seeds from the log on restart so the gate is live immediately.

Engine-side there is **no BE ratchet and no time stop** — a BTC trade only ends
at SL or TP. Exit-reason domain is therefore `{SL, TP}` only; every tool assumes
that. Phantom scores are horizon-marked counterfactuals, not realized trades.

## 5. Evidence base (99 closed trades, 2026-09-03 → 09-23) — see review §13

Headline: **99 rows, 44W/55L (44.4%)** including two 09-03 pre-port sizing
monsters. The raw ledger sums to **−$342.41 gross** (−$142.41 from the $200
start before costs) while `status.json` shows $249.43; the $391.84 discrepancy
is the known sizing/reset history, not a current engine accounting failure.
Exclude the 09-03 pair from every strategy statistic. From 09-05 on: **97 rows,
44W/53L, +$52.43 gross / +$13.63 net** at the measured $0.40 round trip.
Always name the slice and say gross or net.

**Do not pool across geometry.** On 09-06 17:49 UTC the ledger moved from SL
1.5×ATR / TP 2.5×ATR to 2×/4× (RR 1:1.67 → 1:2). The pre-change slice is
n=37, 15W/22L, −$393.62 gross; from the change onward it is n=62, 29W/33L,
+$51.21 gross (+$26.41 net). These are separate rule eras; never quote pooled
R totals or breakeven rates across the boundary.

- **Integrity:** `check_data.py` reports 0 fail / 62 warn. Warnings include 21
  duplicate `Trade_Num` values, 9 `Balance_After` continuity breaks, the known
  +$391.84 engine-ledger/raw-profit drift, six missing M5 slots, the geometry
  boundary, the 10:50 duplicate-minute re-evaluation, and the existing SL
  overshoots. Every ledger row from the actual gate boundary (09-10) passes
  today's trend, RSI and near-EMA checks: **41/41**.
- **Cost remains material.** The strict post-gate slice (≥09-10) is n=41,
  19W/22L, 46.3% (Wilson 32.1–61.3), **+$46.66 gross / +$30.26 net**. Median
  entry ATR is $89.58 ⇒ median 1R ≈ $1.79 ⇒ $0.40 is **22.3% of 1R** ⇒
  approximate cost-adjusted breakeven decisive WR **40.8%**. The observed rate is
  above the point threshold but its interval spans it. Last 10: 7W/3L,
  +$28.45 gross / +$24.45 net; median ATR $131.80, so do not read the dollar
  surge as a parameter effect. M5/M15/H1/H4 timeframe comparison is still the
  dominant unresolved economics question.
- **Book by direction (strictly post-gate):** BUY n=21, 11W/10L, +$34.12 gross /
  +$25.72 net (Wilson 32.4–71.7); SELL n=20, 8W/12L, +$12.54 gross /
  +$4.54 net (Wilson 21.9–61.3). The book favours BUY, but both samples are
  small. The reconstructed, unfiltered 4× signal census also favours BUY:
  +$22.00 net vs SELL −$37.60; it includes signals before cascade/risk gates,
  so it does not justify switching SELL off.
- **Signal census and cascade:** 4611 logged M5 bars reconstruct 216 full signals
  (100 BUY, 116 SELL); 26 occur in blackouts, leaving 190 takeable. At live
  geometry the unfiltered, cascade-ignorant 216-signal stream is 68W/126L/22T,
  −$15.60 net. With one-position-at-a-time, cooldown, daily halt and blackout
  replay, the takeable census selects 52 trades at TP 4×: 19W/28L/5T,
  +$16.69 net. This is a modelled stream, not 52 additional real trades.
  Indicator reconstruction matches logged values: floor 4591/4591; ATR and RSI
  4596/4596.
- **Exit geometry** (`pathwalk_sims.py --spread 0.40 --census`): actual-outcome
  replay agrees **45/45** for the log-covered trades. In the 240-minute
  counterfactual walk and the risk-gated cascade census (all net of $0.40):

  | Rule | 45 trade paths | gated census |
  |---|---:|---:|
  | TP 4×ATR (live) | +$17.05 | +$16.69 (52 taken) |
  | TP 5×ATR | +$34.73 | +$31.24 (49 taken) |
  | TP 6×ATR | +$38.62 | +$37.81 (48 taken) |
  | BE +0.50R | +$12.68 | −$2.98 (63 taken) |
  | BE +0.75R | +$5.84 | +$8.28 (59 taken) |
  | BE +1.00R | +$17.52 | +$18.23 (56 taken) |

  `TIME` is marked to market at 240 minutes; target changes also alter holding
  time and the cascade. Wider TP merits another review, but this is a
  counterfactual on 45 covered trades, not adoption evidence. +1.0R beats live
  only slightly; +0.50R/+0.75R do not agree across views. **Keep live 4× TP and
  no BE ratchet for now.**
- **Excursions and fills:** on the 45 covered trades, TP winners have median MFE
  +2.25R / MAE −0.40R; SL losers median MFE +0.23R / MAE −1.14R. A +0.50R
  ratchet would arm on 10/24 eventual losers and all 21/21 winners. On 2×/4×
  geometry, SL slippage median is −3.8% of 1R (worst −37.9%); TP overshoot
  median +2.4% (worst +12.2%). Three SLs exceed 20% of planned risk: #40/#52
  at −1.38R and #65 at −1.22R. This remains consistent with fast-move fills,
  not a new sizing drift.
- **Filter candidates (net at $0.40):** ATR% ≥0.06 remains a day-confounded
  split (census own-day keep −$23.82 vs skip −$14.50, despite the 97-trade
  ledger-feature split keeping +$36.67); RSI ≥45 remains unsupported by the census/within-day view. Wick
  ratio ≤0.40 is unresolved because census keep 108 is +$3.74 vs skip 82
  −$36.68, while ledger keep 39 is −$3.09 vs skip 58 +$16.72. The two-sided
  EMA50 band remains monitor-only: census ≤0.15 ATR keep 22 is +$15.41 vs skip
  168 −$48.35, while the post-gate ledger's ≤0.50 ATR split is 15 trades
  (10W/5L, +$27.88) vs 26 (9W/17L, +$2.38). Different cuts, small samples;
  log/monitor, do not gate. Tightening the live one-sided
  `MAX_BELOW_EMA_ATR` 0.30→0.15 blocks two positive post-gate rows (+$1.19 net)
  and lowers keep P/L; 0.00 is no better. Do not conflate these tests.
- **Blocked-signal phantoms** (`phantom_trades.py --spread 0.40`, 88 skips):
  daily halt 24 scorable → 3W/21L, −$16.08 gross / −$25.68 net (protective);
  blackout 14/17 scorable → 8W/6L, +$19.35 / +$13.75 net (costly-looking);
  cooldown 8/41 scorable → 5W/3L, +$12.23 / +$9.03 net (costly-looking);
  ATR 0/6 scorable. Overall 46 scorable, 16W/30L, +$15.50 gross / −$2.90
  net; **42/88 remain unscorable**. Sequential dedup is 28 estimated trades,
  +$17.88 gross / +$6.68 net—not a factual counterfactual. Keep the halt and
  do not loosen cooldown/blackouts on these samples.
- **Cost and real-world constraints:** $0.40 is one XM Asian-session sample
  (09-15 04:06 UTC), not a London/NY spread profile. The M5 cost burden is still
  large; measure session spreads and compare the same rules on M15/H1 before
  tuning exits or filters. BTC remains forward-test simulated; do not enable
  `TRADING_MODE=LIVE` without the spread/commission safeguards in §7.

### Four things this data has not settled

| Question | Current evidence | What would settle it |
|---|---|---|
| Bar timeframe / execution cost | M5 cost ≈22.3% of median post-gate 1R; $0.40 is one Asian-session sample | M15/H1 replay of the same rules and spread samples across sessions |
| BUY vs SELL | post-gate book BUY +$25.72 / SELL +$4.54 net; raw census BUY +$22.00 / SELL −$37.60 | Larger gated cascade sample per side; do not use unfiltered census alone |
| Cooldown and blackouts | +$9.03 / +$13.75 net on 8 / 14 scorable skips; 42 of 88 total skips unscorable | More log coverage before changing either gate |
| TP / BE | TP 5–6× beats live in two replay views; BE +1.0R is only slightly ahead | Prospective collection and re-cut beyond this 45-path counterfactual |
| EMA50 band / wick | band results vary by cutoff/view; wick signs conflict | Continue monitor-only logging; no gate change |

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
```

**`--spread 0.40` is the measured XM BTCUSD round trip at 0.01 lot** (§9). The
tools default to `--spread 0` (i.e. gross), so a command copied without the flag
silently produces numbers $0.40/trade more optimistic than this file's — that is
why `handoff_check.py` fails the doc if any command block disagrees with the
snapshot's `spread_usd_per_trade`. `validate_gates.py` takes no spread flag and
prints **gross** ledger sums.

Expected first lines at the snapshot (a mismatch means the data moved — refresh
the block, then re-read the prose):

```
win_rate_report - 99 trades, 4611 M5 bars (2026-09-07 20:20:00 -> 2026-09-23 20:35:00), spread $0.40/trade
pathwalk_sims  - 99 trades, 4611 M5 bars (...), horizon 240 min, spread $0.40/trade
analyze_losers - 99 trades (97 from 09-05), 45 log-covered, 4611 M5 bars
== result: 0 fail, 62 warn ==
```

All read-only except the engine's own self-healing migration and
`handoff_check.py --update` (which touches this file's snapshot block only).
**The analysis core is `tools/replay_lib.py`** — one walk implementation
(direction-safe, SL-first tie-break, BE-aware, horizon + TIME mark, cascade
replay) that every tool imports. **Never hand-roll a bar walk**: gold's
equivalent tool shipped with a SELL excursion inversion that made it validate
itself against its own bug. `pathwalk_sims.py` prints its agreement rate with the
engine *first* (45/45 for the log-covered trades) and `smoke_test.py` Scenario I
locks the direction/ratchet/horizon rules.

## 7. Next steps (in order)

1. **Bar timeframe decision (M5 vs M15 vs H1 vs H4) — still the primary
   blocker.** On the 41-trade post-gate slice, the $0.40 round trip is 22.3% of
   median 1R (about $1.79), with a 40.8% approximate cost-adjusted breakeven
   rate versus 46.3% observed (Wilson 32.1–61.3). That interval is not proof of
   an edge. Measure the same rules on a higher timeframe before tuning M5.
2. **Confirm spread profile across sessions.** The $40/BTC figure was sampled
   at 04:06 UTC in the Asian session. London/NY may differ; measure the actual
   spread and any commission/swap before using a session-aware cost model.
3. **The 30-trade milestone is met; keep collecting rather than retuning.** The
   review is re-cut at 99 total rows, 45 post-port and 41 strictly post-gate.
   The evidence improves the live-era reading but is still noisy; no exit or
   entry parameter change is justified by the current sample alone.
4. **Keep the two-sided EMA50 distance monitor-only.** It is reconstructable
   from the ledger and should be logged on signal/skip rows when a code change
   is next in scope. The old one-sided gate is different; do not tighten
   `MAX_BELOW_EMA_ATR`.
5. **Grow log coverage for blocked signals.** 33 of 41 cooldown skips and 3 of
   17 blackout skips remain unscorable; overall 42 of 88 skips cannot be scored.
   The currently scorable cooldown/blackout slices look costly, but are too
   small to justify changing their rules.
6. **Keep the daily halt and current 1:2 geometry.** The halt's 24/24 scorable
   phantoms are 3W/21L, −$25.68 net. Do not raise `MIN_ATR_PERCENT` on win-rate
   grounds; the evidence is confounded by day selection. Leave TP4 and BE off
   until the timeframe/cost question is better measured.
7. **Before any LIVE test:** symbol `BTCUSD` with contract 1.0 / min lot 0.01 is
   confirmed (`BTCUSDm` absent); add a live spread check before order dispatch,
   re-check `MIN_ATR_PERCENT` against measured costs, and confirm
   commission/swap so the $0.40 model is not optimistic.

### Explicitly NOT queued (with the evidence that closed them)

- **Tightening `MAX_BELOW_EMA_ATR` (0.30 → 0.15 / 0.00)** — one-sided and
  measured-negative. At 0.15 it blocks two positive post-gate trades worth
  +$1.19 net; the two-sided band is a different monitor-only hypothesis.
- **RSI ≥45** — still unsupported by the census/within-day control; no transfer
  from gold.
- **ATR floor by win rate** — still day-confounded; do not treat it as spread
  control.
- **Wick-ratio gate (either direction)** — census and ledger disagree on sign;
  monitor only.
- **TP/BE changes on M5** — wider TP and BE +1.0R look better in counterfactual
  paths, but are not adoption-grade; live remains TP4 with no ratchet.
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

Never enable `TRADING_MODE=LIVE` as part of an unrelated change. If a change
alters a number quoted in this file, update the file in the same commit —
`handoff_check.py` catches the snapshot block but not the prose, and the prose
is where stale numbers actually hide.

## 9. Data gotchas (hard-won — read before analyzing)

- **The two 09-03 trades (−$197.63, −$197.21) are not comparable to anything
  else** — pre-port sizing (~100× lot). Exclude them from every strategy P/L
  statistic and say so. The current 99-row raw Profit sum is −$342.41 gross;
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
- **The price log starts 2026-09-07 20:20 UTC** (4611 M5 bars through
  2026-09-23 20:35 UTC; six missing slots in five runs). **Only 45 of 99 closed
  trades are log-covered**; 54 predate the log, limiting any log-joined replay
  to the covered tail. There is no gap >15 minutes. One duplicated minute is
  present at 09-23 10:50: two same-OHLC rows at 10:50:00 and 10:50:01 with
  updated indicators; treat it as a restart/re-evaluation warning, not an extra
  price interval. `check_data.py` reports 0 fail / 62 warn.
- **Log indicators are PRE-update for that bar; ledger `*_At_Entry` values are
  POST-update** (the engine gates on post-update values). The current
  `replay_lib.enrich_log()` reconstruction matches floor 4591/4591 and ATR/RSI
  4596/4596. If the match rate is not ~100%, treat every census number as
  suspect. Never compare a raw log indicator column against a ledger entry
  column directly.
- **Dashboard funnel counters are since-restart, not lifetime.** Current
  `status.json` has `candles_evaluated = 2499`, `all_confirmed = 29` BUY and
  `sell_all_confirmed = 15`; use them only for post-restart context, not a
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
  From 09-05 on the current clean slice is +$52.43 gross / +$13.63 net at this
  assumed flat cost. `phantom_trades.py` uses the same scaling and its outcomes
  are upper-bound counterfactuals, not fills.
- **Symbol / contract:** `BTCUSD` exists on XM MT5 with contract 1.0 / min lot
  0.01; `BTCUSDm` does not exist (`SYMBOL_MT5=BTCUSD`).
- `status.json` equity ($249.43) is the **engine ledger**, not the raw sum of
  Profit (−$342.41 gross, −$142.41 from $200 before spread costs). `check_data.py`
  reports the +$391.84 drift by design; see the outlier/reset notes above.

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
   there means "start the next session with step 1".
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
   `docs/REVIEW-2026-09-15.md` — **§13 is the 2026-09-24 re-cut; keep adding a
   dated delta there rather than starting a new file unless the question changed.**
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
`tools/handoff_check.py` freshness gate for this file · `tools/` analysis +
tests · `deploy/mt5feed.service` sidecar unit · `docs/PORT-2026-09-10.md` what
came from gold and why · `docs/REVIEW-2026-09-15.md` first data review (**§13 =
the 2026-09-24 re-cut; §12 is historical**) · `docs/AUTOSYNC.md` the unattended deploy loop +
digest guide · `archive/PROJECT_LOG.md` full history · **this file** =
executive summary.

## 12. Reading order for a brand-new agent

1. **`docs/HANDOFF.md`** (this file) — snapshot block, §1, then §5's tables
2. `docs/REVIEW-2026-09-15.md` §13 — the newest numbers and their provenance
3. `archive/PROJECT_LOG.md` — changelog + current strategy state
4. `docs/PORT-2026-09-10.md` — what the gold port changed and why
5. `docs/REVIEW-2026-09-15.md` §1–§11 — the full first review (73 trades)
6. `git log --oneline` — what changed recently

Then run `python3 tools/handoff_check.py` and `python3 tools/check_data.py`
before drawing any conclusion from the CSVs.
