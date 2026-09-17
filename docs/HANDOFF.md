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
| as_of_utc | 2026-09-17 04:05 |
| data_collection | 665 |
| closed_trades | 80 |
| wins_losses | 33W/47L |
| win_rate_pct | 41.2 |
| engine_ledger_usd | 211.84 |
| true_equity_usd | -180.00 |
| live_era_trades | 26 |
| live_era_net_usd | +1.43 |
| log_covered_trades | 26 |
| log_bars | 2685 |
| log_last_bar_utc | 2026-09-17 04:05 |
| skip_rows | 74 |
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

## 1. Where things stand (snapshot above, refreshed 2026-09-17; data prose last re-cut 2026-09-16 at 78 trades — the snapshot has since moved to 80, unreviewed, next re-cut at the 30-live-era-trade milestone)

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
- **Reviews:** `docs/REVIEW-2026-09-15.md` is the full first review (written at
  73 trades) — **its §12 is the 2026-09-16 re-cut at 78 trades** and is the
  provenance for every number in §5 below. Where the two disagree, read §12.

### The book in one table (net of $0.40/trade; gross in brackets)

| Slice | n | W/L | WR | net | gross | net/trade |
|---|---|---|---|---|---|---|
| all rows incl. the 09-03 outliers | 78 | 33/45 | 42.3% | −405.59 | [−374.39] | −5.20 |
| **from 09-05 (exclude the outliers)** | 76 | 33/43 | 43.4% | **−9.95** | [+20.45] | −0.13 |
| live geometry (≥09-06 17:49, RR 1:2) | 41 | 18/23 | 43.9% | +2.83 | [+19.23] | +0.07 |
| **"new regime" as the tools slice it (≥09-09 02:25)** | 24 | 10/14 | 41.7% | **+7.84** | [+17.44] | +0.33 |
| strictly post-gate (≥09-10, first SELL 09-10 09:05) | 20 | 8/12 | 40.0% | +6.68 | [+14.68] | +0.33 |
| last 10 | 10 | 4/6 | 40.0% | +2.26 | [+6.26] | +0.23 |

True equity from the $200 start is **−$174.39**; the engine ledger reads
**$217.45**. The $391.84 gap is the two 2026-09-03 pre-port sizing monsters
(−$394.84) plus pre-port balance resets — not a live accounting bug (§9).

### What changed since the 2026-09-15 review (73 → 78 trades)

1. **The cost-adjusted breakeven line was crossed — barely.** At the live-era
   median entry ATR ($87.85 ⇒ 1R = $1.757) the $0.40 round trip is **22.8% of 1R**,
   which needs a **40.9%** decisive win rate; the live era is now at **41.7%**
   (Wilson 24.5–61.2). On 09-15 the same comparison read 41.3% required vs 36.8%
   actual. **This is n=24 inside a ±19-point confidence interval — it says "still
   alive", not "solved".** The timeframe question in §7.1 is unchanged.
2. **The last-10 collapse reversed**: 1W/9L (−$11.48 net) on 09-15 → **4W/6L
   (+$2.26 net)** now, on a 3W/1L 09-15 and a 1-trade 09-16. Reinforces the
   review's verdict that 09-11→09-14 was regime, not parameters.
3. **The cooldown's measured sign flipped.** It now has 7 scorable blocks
   (was 4) reading **+$6.72 gross / +$3.92 net** — i.e. on the slice the log can
   finally score, the cooldown is *throwing away winners*. 33 of 40 blocks still
   predate the log, so this is a first reading, not a verdict (§4, §7.5).
4. **Two queued candidates were re-graded.** The wick-ratio candidate now has
   **opposite signs in the two views** (demoted to unresolved), and the
   "entry near EMA50" candidate turned out to be **mislabeled**: the live gate is
   one-sided and *tightening it hurts*, while the edge belongs to a **two-sided**
   band that is not implemented (§5). This is the most consequential correction
   in this update — it removes a change that would have cost money.
5. **A third stop-overshoot row appeared** (#65, −1.22R) and the era boundary
   moved: `check_data.py` now re-applies today's entry gates to every post-09-10
   row and all 20 pass, while two 09-09 rows violate the near-EMA gate — the
   fingerprint of the gates going live on 09-10, not 09-09 (§9).

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
- Feed health: 2494 M5 bars since 09-07 20:20 UTC, **no gap >15 min anywhere**
  (`check_data.py`'s stale-feed proxy) and only three single-bar holes (09-14
  08:45, 09-15 03:45, 09-15 13:00) — the feed has been continuous. At the
  snapshot there is **no open trade** and the daily-loss counter reads 1/3.
- Next milestone: **30 live-era trades**, then re-run §6 and re-cut the review.
  At 24 (or 20 strictly post-gate) nothing below may be retuned.

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
re-tested it; §5 below has the 78-trade re-read).

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
  consecutive SLs**. Still the most-triggered gate — **40 of 73 logged skips** —
  and its cost is *finally* measurable on a slice: 7 scorable blocks read
  **+$6.72 gross / +$3.92 net**, i.e. the blocked signals were net winners.
  Do not act on 7; 33 of the 40 still predate the log (§7.5).
- **Daily breaker**: `MAX_DAILY_LOSSES = 3` SLs per UTC day → hard halt for the
  rest of the day. (Gold uses 10 + a trend-side-only mode; BTC keeps the hard
  halt.) It has engaged on 18 blocked signals, all scorable: **3W/15L,
  −$4.93 gross / −$12.13 net → the halt is protective, keep it.** The counter
  reads a **400-row window** (`DAY_WINDOW`) because a 30-row window silently
  under-counts busy days. The pre-port days (09-05/06/07, 13/10/6 SLs) are
  before the breaker existed.
- **Blackouts (UTC)**: London 07:55–09:00, NY pre-market 12:25–12:45,
  NY open & US macro 13:25–15:15. All block **both** directions (gold's
  direction-aware London carve-out is *not* ported — no BTC evidence). 9 skips
  logged, 6 scorable: **3W/3L, +$8.27 gross / +$5.87 net** — the blocked
  signals were net winners, so the blackouts currently read as *costly*, on n=6.
  **No rollover blackout** (BTC has none) and no weekend pause.
- **ATR bounds (% of price)**: `MIN_ATR_PERCENT = 0.0001` (0.01%),
  `MAX_ATR_PERCENT = 0.0060` (0.60%). 6 skips logged, **none scorable** (all
  pre-log). Observed ATR% at entry runs 0.006%–0.275% across the 76 post-outlier
  trades (live era only: 0.030%–0.275%), so the **upper bound has never
  bound**. The floor is **not** a cost control: 0.01% is $7.70 at $77k,
  ~10× below the level the spread implies (keep the round trip ≤15% of 1R ⇒
  `ATR ≥ 333 × spread$`, review §1).
- **Near-EMA gate is ONE-SIDED**: `MAX_BELOW_EMA_ATR = 0.30` caps how far the
  entry may sit on the *adverse* side of EMA50 (below for BUY, above for SELL).
  It does **not** cap distance on the favourable side, so it is not a "band".
  Tightening it makes both measured views worse; the candidate that looks
  interesting is a two-sided band, which is a **new** gate (§5, §7.4).
- **Slope gate**: EMA50 vs 30 bars ago, both directions; `ema50_history`
  re-seeds from the log on restart so the gate is live immediately.

Engine-side there is **no BE ratchet and no time stop** — a BTC trade only ends
at SL or TP. Exit-reason domain is therefore `{SL, TP}` only; every tool assumes
that.

## 5. Evidence base (78 trades, 2026-09-03 → 09-16) — don't re-derive

Headline: **33W/45L (42.3%), engine ledger $217.45, true equity −$174.39.**
The raw Profit column sums to −$374.39, dominated by **two pre-port trades on
09-03 that ran with a broken lot/size setup (−$197.63 and −$197.21)**. Excluding
them (09-05 on): **76 trades, 33W/43L, 43.4%, +$20.45 gross / −$9.95 net.**
Always say which slice and whether it is gross or net.

**Ledger geometry changed on 09-06 17:49 UTC** (SL 1.5×ATR / TP 2.5×ATR →
2×/4×, i.e. RR 1:1.67 → 1:2). Pooled R totals across that line are invalid;
`check_data.py` and `replay_lib` enforce the era split. Era-correct:
pre-09-06 17:49 n=37 40.5% −$393.62 gross (−199.6R) · from 09-06 17:49 n=41
43.9% +$19.23 gross (+12.3R).

- `check_data.py` reports **0 fail, 61 warn**, all known: 21 duplicate
  `Trade_Num` values, 9 `Balance_After` continuity breaks (pre-port ledger
  resets), the +$391.84 ledger-vs-sum drift explained above, three missing M5
  slots, the geometry-era warnings, and two realized-R overshoot rows (#40/#52;
  `analyze_losers.py` flags a third, #65, at a tighter threshold — see below).
  Its new **entry-gate conformance** block re-applies today's trend / RSI /
  near-EMA rules to every post-09-10 row: **all 20 pass** (§9 on the boundary).
- **Cost is the dominant term, and it is now roughly break-even.** Live-era
  median entry ATR **$87.85** ⇒ 1R = **$1.757** ⇒ $0.40 = **22.8% of 1R** ⇒
  breakeven decisive WR **40.9%** vs actual **41.7%** (n=24). Timeframe re-cut
  from the review (cost as % of 1R): M5 24.0%, M15 11.9%, H1 5.4%, H4 2.6% —
  the bar timeframe, not BE/TP tuning, is still the dominant open decision.
- **Sides disagree between the book and the census — the biggest open tension.**
  Live era: SELL n=15 **7W/8L, +$16.12 gross / +$10.12 net** vs BUY n=9
  **3W/6L, +$1.32 gross / −$2.28 net**. The reconstructed signal census says the
  *opposite*: at the live geometry BUY 10W/15L (40.0%) **+$3.55 net** vs SELL
  22W/51L (30.1%) **−$12.20 net**, and the reconstructed census contains 75 SELL
  vs 25 BUY signals. The book is gated and cascade-limited, the census is
  neither — but nobody has reconciled them (§7.3).
- **Regime, not parameters**: since the last restart the funnel has evaluated 382
  candles with **BUY `trend_confirmed` = 0** (EMA50 below EMA200 the whole time)
  and 7 full SELL signals — the engine has been short-only, which is why the
  recent ledger is all SELL. The review's 09-11→09-14 diagnosis stands: 09-12 was
  a 15×ATR range day with median ATR $29 where all 21 census signals stopped;
  09-14 was a 26×ATR day that went 7 TP/7 SL on 14 BUY signals while the
  cascade/halt let only 4 through.
- **Gate replay** (`validate_gates.py`, gross, log-covered trades only — the log
  starts 09-07 20:20, so these all score the recent tail):
  `SLOPE30` 23 kept 9W/14L +$13.15 · `ABV50s` 22 kept 9W/13L +$17.74 ·
  `RISE120` 19 kept 8W/11L +$14.73 · `PROX1.0` 17 kept 10W/7L +$24.82 ·
  `PROX0.5` 7 kept 5W/2L +$13.75 · adopted combo (SLOPE30+ABV50s+NOH8) 22 kept
  9W/13L +$17.74. Every adopted gate is still positive on the sample it can
  score; none of these n's is large enough to tighten anything.
- **Phantom (blocked) signals** (`phantom_trades.py --spread 0.40`, 73 skips,
  24 h horizon + TIME mark-to-market): daily-halt 18/18 scorable → **3W/15L,
  −$4.93 gross / −$12.13 net (protective)** · blackout 6/9 → **+$8.27 / +$5.87
  (costly)** · cooldown 7/40 → **+$6.72 / +$3.92 (costly)** · ATR floor 0/6.
  Totals: 31 scorable, 10W/21L, **+$10.06 gross / −$2.34 net**. Sequential view
  (in-trade + cooldown dedup): 17 taken, 8W/9L, +$14.94 gross / +$8.14 net — an
  estimate, not a fact. **Net read: the halt pays for the blackouts and the
  cooldown; the gate stack as a whole is cost-neutral-to-negative on the slice
  that can be scored, and 42 of 73 blocks still cannot be scored at all.**
- **Exit geometry** (`pathwalk_sims.py --spread 0.40 --census`, 24 log-covered
  trades, replay agreement **24/24** vs the engine's actual outcomes):

  | Rule | 24 real trades (net) | cascade census, 92 takeable (net) | all 100 signals, cascade-ignorant (net) |
  |---|---|---|---|
  | TP 3×ATR | +6.79 (12W/12L) | +2.89 | −9.59 |
  | **TP 4×ATR (live)** | **+3.97** (9W/14L/1T) | **+7.26** (11W/18L) | −8.65 |
  | TP 5×ATR | +12.50 | +12.65 | −1.05 |
  | TP 6×ATR | +16.60 | +19.43 | — |
  | BE off (live) | +3.97 | +7.26 | −8.65 |
  | BE +0.50R | +10.90 (8W/8L/8BE) | +4.09 | −7.94 |
  | BE +0.75R | +4.49 | +4.11 | −3.77 |
  | **BE +1.00R** | +7.10 | **+11.46** | **+6.00** |
  | BE +1.25R | +6.36 | +9.63 | — |

  ("BE off" is the same rule as TP 4×ATR — it is repeated so every BE row sits
  next to its own baseline; the three columns are not additive, they are three
  different samples of the same rule.)

  Two honest readings: **(a)** *wider TP (5–6×ATR) now beats the live 4×ATR in
  both the real-trade and cascade-census views* — a direction that did not exist
  at 73 trades, still worth a few dollars on n≈24–30, and not adoption-grade;
  **(b)** **+1.0R is the only BE row positive in all three views** (gold's
  adopted +0.75R is the *worst or near-worst* row here, and +0.50R wins the
  24-trade view but loses the cascade census). If a ratchet is ever armed, arm
  +1.0R — and measure it first, all tools are BE-aware.
- **Excursion profile** (`analyze_losers.py`, 24 covered): winners MFE median
  **+2.32R** / MAE median **−0.31R**; losers MFE median **+0.38R** / MAE
  **−1.14R**. 6 of 14 eventual losers (43%) were **+0.50R** in profit first, and
  a +0.50R ratchet would arm on those 6 **and on 10/10 eventual winners** — that
  trade-off is exactly why the grid above, not this stat, decides it.
- **Fills**: on live-geometry rows, SL slips median **−5.0%** of 1R (worst
  −37.9%) and TP overshoots median **+2.2%** (worst +12.2%). Three rows exceed
  the planned −1.00R: **#40 and #52 at −1.38R** (tick timing in fast moves) and
  **#65 at −1.22R**. The two tools use different thresholds, which is why the
  counts differ: `check_data.py` warns past **0.25R** of deviation (#40/#52,
  inside its 61 warnings), `analyze_losers.py` past **20%** (#40/#52/#65).
  Not sizing drift — but they are why a replay must use the SL-first tie-break.
- **Filter candidates, re-graded at 78 trades** (`win_rate_report.py` §7 prints
  each with its within-day control):

  | Candidate | Verdict now | Numbers (net @$0.40) |
  |---|---|---|
  | ATR% ≥ 0.06 | **rejected — day proxy** (unchanged) | pooled keep 66 43.9% +17.87 vs skip 26 3.8% −26.53, but own-day collapses to n=4 (0.0%, −7.48) and flips sign |
  | RSI ≥ 45 (gold's filter) | **rejected — reverses within-day** (unchanged) | pooled keep 75 33.3% −4.80 vs skip 17 29.4% −3.86; own-day keep 50 22.0% **−35.82** |
  | momentum-aligned (5 h) | **rejected** | own-day keep 41 19.5% −27.26 vs skip 5 40.0% +3.47 |
  | wick ratio ≤ 0.40 | **demoted → unresolved (sign conflict)** | census keep 56 35.7% **+2.46** vs skip 36 27.8% −11.11 (own-day identical, drops 0) **but** ledger keep 26 42.3% **−6.42** vs skip 50 44.0% −3.53, and winners' wick median is 62.1% vs losers' 47.4% — two views, opposite signs |
  | side = SELL | **unresolved** (book vs census, above) | census keep 71 31.0% −12.06 vs skip 21 38.1% +3.40 |
  | **two-sided EMA50 band ≤ 0.50 ATR** (NEW gate) | **strongest survivor — monitor/log-only** | census keep 25 44.0% **+10.46** vs skip 67 28.4% −19.11, own-day **drops 0** (cleanest control in the list); post-gate ledger keep 5 **80.0% +11.97** vs skip 15 26.7% −5.29; live era keep 6 5W/1L **+16.45** vs skip 18 −8.61. Tiny n's — three views agreeing is the reason to instrument it, not to gate on it |
  | tighten `MAX_BELOW_EMA_ATR` 0.30 → 0.15 / 0.00 | **rejected — hurts** | census −8.66 → **−11.20** → **−18.23**; post-gate ledger +6.68 → +5.49 (blocks 2 winners worth +1.19); live era would have blocked 5 trades worth **+$4.57 net** |
- **Hour-of-day** is noise at this n (00:00 1W/5L, 01:00 3W/0L, 05:00 2W/8L).
  Do not build session filters on it yet.

### Four things this data has not settled

| Tension | The two numbers | What would settle it |
|---|---|---|
| Bar timeframe | M5 cost = 22.8% of 1R; M15/H1/H4 = 11.9/5.4/2.6% | an M15 or H1 replay of the same rules, or a lower-spread account (§7.1) |
| SELL vs BUY | book: SELL +10.12 / BUY −2.28 · census: SELL −12.20 / BUY +3.55 | 30+ live-era trades *and* a gated cascade replay per side (§7.3) |
| Cooldown & blackouts | cooldown +3.92, blackouts +5.87 (both = blocked winners) on 7 and 6 scorable blocks | log coverage of the remaining 33 + 3 blocks (§7.5) |
| Wider TP / BE +1.0R | TP 5–6×ATR beats live in 2 views; BE +1.0R positive in 3 views | n≥30 live-era trades, then `pathwalk_sims.py --census` re-cut (§7.3) |

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
win_rate_report - 78 trades, 2494 M5 bars (2026-09-07 20:20:00 -> 2026-09-16 12:10:01), spread $0.40/trade
pathwalk_sims  - 78 trades, 2494 M5 bars (...), horizon 240 min, spread $0.40/trade
analyze_losers - 78 trades (76 from 09-05), 24 log-covered, 2494 M5 bars
== result: 0 fail, 61 warn ==
```

All read-only except the engine's own self-healing migration and
`handoff_check.py --update` (which touches this file's snapshot block only).
**The analysis core is `tools/replay_lib.py`** — one walk implementation
(direction-safe, SL-first tie-break, BE-aware, horizon + TIME mark, cascade
replay) that every tool imports. **Never hand-roll a bar walk**: gold's
equivalent tool shipped with a SELL excursion inversion that made it validate
itself against its own bug. `pathwalk_sims.py` prints its agreement rate with the
engine *first* (24/24 for the log-covered trades) and `smoke_test.py` Scenario I
locks the direction/ratchet/horizon rules.

## 7. Next steps (in order)

1. **Bar timeframe decision (M5 vs M15 vs H1 vs H4) — the primary blocker.**
   Cost is 22.8% of 1R on M5 at the measured $40.00/BTC spread ($0.40/trade at
   0.01 lot), vs 11.9% on M15, 5.4% on H1, 2.6% on H4. The live era now sits
   *at* its cost-adjusted breakeven (41.7% actual vs 40.9% required) on n=24,
   which is an argument for measuring the higher timeframes, not for relaxing.
   Nothing else should be tuned before this is settled — every parameter below
   is a function of what 1R is worth.
2. **Confirm the spread profile across sessions.** The $40.00 figure was sampled
   at 04:06 UTC (Asian session). London/NY may be narrower or wider; if the
   round trip is materially lower in some sessions, a session-aware cost model
   beats a global timeframe change.
3. **Collect to 30 live-era trades, then re-cut.** Re-run §6 and update
   `docs/REVIEW-2026-09-15.md` §12 (or start a new review if the question
   changed). Only then decide: wider TP (5–6×ATR), the +1.0R BE ratchet, the
   two-sided EMA50 band, and whether the SELL/BUY conflict resolves.
4. **Instrument the two-sided EMA50 distance, don't gate on it.** The band is
   the only candidate that survives every control in three views, and it is
   *already* reconstructable from the ledger (`EMA50_At_Entry`, `ATR_At_Entry`,
   `Entry_Price`) — `win_rate_report.py` §7 prints it. Add it to the per-signal
   log/skip rows so future blocks are scorable, and **do not** touch
   `MAX_BELOW_EMA_ATR`: tightening the live one-sided gate is measured-negative.
5. **Let the log cover the cooldown and blackout blocks.** 33 of 40 cooldown
   skips and 3 of 9 blackout skips still predate the 09-07 20:20 log start, and
   both currently read as *costly* (+$3.92 and +$5.87 net on 7 and 6 scorable
   blocks). No cooldown or blackout change before those n's are meaningful — and
   note the sequential estimate (+$8.14 net on 17 reconstructed trades) is an
   upper bound, not evidence.
6. **Keep the daily halt** (18/18 scorable, −$12.13 net → protective) and the
   current geometry (1:2). Do not raise `MIN_ATR_PERCENT` on win-rate grounds —
   that evidence is a day proxy (review §2). Fix `replay_lib.PORT_DEPLOY` vs
   `GATES_DEPLOY` only with a review re-cut in the same PR (§9).
7. **Before any LIVE test**: symbol `BTCUSD` with contract 1.0 / min lot 0.01 is
   confirmed (`BTCUSDm` absent); add a live spread check before order dispatch,
   re-check that `MIN_ATR_PERCENT` is consistent with the measured spread, and
   confirm the account's commission/swap so the $0.40 model is not optimistic.

### Explicitly NOT queued (with the evidence that closed them)

- **Tightening `MAX_BELOW_EMA_ATR` (0.30 → 0.15 / 0.00)** — measured-negative in
  both views; it would have blocked +$4.57 net of live-era winners (§5). This
  replaces the previous handoff's "entry within 0.15 ATR of EMA50 (candidate:
  tighten `MAX_BELOW_EMA_ATR`)", which conflated a two-sided band with the
  one-sided live gate.
- **RSI ≥ 45** — reverses within-day (review §3; unchanged at 78 trades).
- **ATR floor by win rate** — calendar proxy (review §2; own-day n=4).
- **Wick-ratio gate (either direction)** — census and ledger disagree on the
  *sign*; monitor only (§5).
- **BE/TP parameter changes on M5** — deferred until the timeframe decision.
  The evidence moved (wider TP and BE +1.0R both read better than at 73 trades)
  but n=24 and the grids are a few dollars apart.
- **Direction-aware London blackout / cooldown softening / trend-side breaker** —
  still no BTC evidence (review §6); the hard halt is protective.

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
  else** — pre-port sizing (~100× lot). Exclude them from every P&L statistic
  and say so.
- **There are THREE era boundaries, not one.** (a) 09-05: the outliers stop.
  (b) 09-06 17:49: geometry 1.5×/2.5× → 2×/4×. (c) **the gates went live
  09-10, not 09-09**: `replay_lib.PORT_DEPLOY` (09-09 02:25) is the first trade
  of the "new regime" slice every existing review quotes, but the ledger's first
  SELL is 09-10 09:05 and two 09-09 BUY rows (#57 at 3.11 ATR, #58 at 0.57 ATR
  on the adverse side) violate the near-EMA gate — so `replay_lib.GATES_DEPLOY`
  (09-10 00:00, mirrored by `check_data.GATES_LIVE`) is the boundary to use when
  re-applying entry rules. Quoting the ≥09-09 slice is fine; *judging a gate* on
  it is not.
- `trades.csv` has multiple batches: `Trade_Num` **restarts** (21 duplicate
  values — including a duplicated **#74** in the live era, 09-15 02:15 and
  09-15 06:00) because of pre-port balance resets. **Dedupe/join by timestamp,
  never by Trade_Num.** `Balance_After` has 9 continuity breaks for the same reason.
- **Legacy rows are comma-formatted** (`"80,832.88"`) — 58 of 78 rows. Naive
  `float()` breaks. Every loader must strip commas (all `tools/` do). New rows
  are written plain `%.2f`.
- Schema is **16 fields with `Trade_Type`**; `engine.migrate_trades_csv()`
  self-heals drift on start and before every append (keeps a
  `.bak-pre-migration` backup) and `trade_filter.load_recent_trades()` has a
  loud drift tripwire.
- **The price log starts 2026-09-07 20:20 UTC** (2494 M5 bars at the snapshot,
  three single-bar holes). **Only 24 of 78 trades are log-covered** — 54 predate
  the log, which is the source of every `check_data.py` cross-file warning and
  the reason `validate_gates.py` and `phantom_trades.py` can only score the tail.
  **Any conclusion drawn from log-joined analysis is a statement about the last
  ~24 trades.** Ledger-feature analysis (RSI/ATR/wick/EMA columns) covers all 76
  post-09-05 rows — prefer it where possible.
- **The log's `EMA_50`/`RSI`/`ATR` are PRE-update for that bar; the ledger's
  `*_At_Entry` are POST-update** (the engine gates on post-update values).
  `replay_lib.enrich_log()` reconstructs the post-update values and prints its
  match rate (2474/2474 floor, 2479/2479 ATR and RSI at the snapshot) — if that
  is not ~100%, every census number is suspect. Never compare a log column
  against a ledger column directly.
- **The dashboard's funnel counters are since-restart, not lifetime** (they are
  in-memory and never restored): at the snapshot `candles_evaluated` = 382
  (≈32 h) with BUY `trend_confirmed` = 0 and `sell_all_confirmed` = 7. Use them
  to read the *current regime*; use `win_rate_report.py` §6 for a census.
- Per-trade replay must use **±6 min** windows (M5 cadence); gold uses ±2 min on
  M1. Gap threshold is >15 min (gold: >5).
- `archive/forward_test_log_m1.csv` (8,537 rows, Sep 1) is **M1** data from the
  pre-M5 design. Never mix it with the M5 log in any analysis.
- Exit reasons are `{SL, TP}` only — no `BE` rows on BTC (unlike gold). If BE is
  ever added, R-multiple math must reconstruct the original 2×/4×ATR geometry
  from `ATR_At_Entry` (1R$ ≈ 2×ATR×lot), as gold's tools do — `replay_lib`
  already keys on geometry, not on `Exit_Reason`.
- **Cost haircut**: the live terminal spread is measured at **$40.00/BTC =
  $0.40/trade at 0.01 lot** (XM, 2026-09-15 04:06 UTC, Asian session — one
  sample, §7.2). The tools default to `--spread 0`, so always pass `--spread
  0.40`: gross +$20.45 is net −$9.95 across the 76 post-outlier trades.
  Phantom P&L uses the same scaling and is an upper bound.
- **Symbol / contract**: `BTCUSD` exists on XM MT5 with contract 1.0 / min lot
  0.01; `BTCUSDm` does not exist (`SYMBOL_MT5=BTCUSD`).
- `status.json` equity ($217.45) is the **engine ledger**, not the sum of the
  Profit column (−$374.39 raw, −$174.39 true equity from $200). `check_data.py`
  reports the +$391.84 drift by design.

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
   `docs/REVIEW-2026-09-15.md` — **re-cut it (add a dated delta section) rather
   than starting a new file unless the question changed.**
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
came from gold and why · `docs/REVIEW-2026-09-15.md` first data review (**§12 =
the 2026-09-16 re-cut**) · `docs/AUTOSYNC.md` the unattended deploy loop +
digest guide · `archive/PROJECT_LOG.md` full history · **this file** =
executive summary.

## 12. Reading order for a brand-new agent

1. **`docs/HANDOFF.md`** (this file) — snapshot block, §1, then §5's tables
2. `docs/REVIEW-2026-09-15.md` §12 — the newest numbers and their provenance
3. `archive/PROJECT_LOG.md` — changelog + current strategy state
4. `docs/PORT-2026-09-10.md` — what the gold port changed and why
5. `docs/REVIEW-2026-09-15.md` §1–§11 — the full first review (73 trades)
6. `git log --oneline` — what changed recently

Then run `python3 tools/handoff_check.py` and `python3 tools/check_data.py`
before drawing any conclusion from the CSVs.
