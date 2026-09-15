# HANDOFF — read this first in a new session

Paste this file at the start of a new session:
> "I'm working on my Bitcoin trading bot. Here is the handoff: [paste docs/HANDOFF.md]. I want to work on [X]."

This is the **executive summary** of the whole project. It is the BTC twin of
`gold-trading-bot/docs/HANDOFF.md`. Gold's 2026-09-15 review (BE ratchet
0.30→0.75, RSI≥45) was read and re-tested against BTC data this cycle — see
`docs/REVIEW-2026-09-15.md` for the verdict on each gold-derived item. Keep it current: every session that changes
code, params, or conclusions must update §1, §4/§5 and §7 before it ends
(see §10 "How to keep this file honest").

---

## 1. Where things stand (as of 2026-09-15, 73 closed trades — first review written)

- Repo: `shashidaren/bitcoin-trading-bot`, default branch `main`.
  Current work branch: `arena/01a0a313-bitcoin-trading-bot`.
- **The gold→BTC port is live** (2026-09-10, see `docs/PORT-2026-09-10.md`):
  SELL funnel, EMA-slope + near-EMA regime gates, escalating SL cooldowns,
  daily-loss breaker, UTC everywhere, self-healing 16-field ledger, stale-feed
  guard, MT5 sidecar option, `tools/` suite.
- **The first data review is written: `docs/REVIEW-2026-09-15.md`.** Headline:
  the whole forward test has made **+$11.74 gross** in 71 trades (from 09-05,
  excluding the two 09-03 outliers) — about **+$0.17/trade, which is inside the
  published XM BTCUSD spread ($0.225–0.60/trade at 0.01 lot)**. The gross edge
  is thinner than the broker spread; measuring the real spread is step 1.
  The review also rejects the ATR-floor and RSI≥45 filters (day-proxy /
  within-day reversal), keeps the BE ratchet unadopted, and finds the recent
  09-11→09-14 collapse is regime, not parameters.
- **Live-era sample = 19 trades** (from 2026-09-09 02:25 UTC, RR 1:2):
  **7W/12L, +$8.73 gross**; last 10: 1W/9L, −$9.98. Open SELL #74.
  Still far below the n≥30 bar — **do not retune on it**.
- Live bot runs from `/opt/bitcoin/` (paths hardcoded in `engine.py` /
  `trade_filter.py`). Deploy = merge PR → `git pull` on the box → restart the
  engine. Restarts are safe mid-trade (open trade restores from `status.json`,
  stats reload from `trades.csv`, slope gate re-seeds from the log).
- `tools/autosync.sh` (cron, root) does this automatically: commits live data,
  deploys only if `smoke_test.py` passes (rolls back otherwise), runs the
  integrity gate, sends a Telegram digest. It auto-detects the engine/dashboard
  units by scanning systemd for units referencing `/opt/bitcoin`.
- `docs/REVIEW-2026-09-15.md` is the first review (73 trades). Next milestone:
  re-cut it at 30+ live-era trades with the measured spread in hand.

## 2. Bot in one paragraph

Simulated BTC/USD swing-scalper on **M5** candles. BUY at the 20-bar floor /
SELL at the 20-bar ceiling after a ≥15% wick rejection, trend-gated by
EMA50 vs EMA200 (+30-bar EMA50 slope, entry within 0.3·ATR of EMA50),
RSI 40–70 for BUY / 30–60 for SELL, ATR bounds enforced as a **% of price**
(0.01%–0.60%) in the filter. Exits: SL = entry ∓ 2·ATR, TP = entry ± 4·ATR
(**RR 1:2**, breakeven WR ≈ 33%). `engine.py` = signals + execution/state;
`trade_filter.py` = portfolio risk gates; `dashboard.py` = Flask page on port
6001. Trading is FORWARD-TEST simulated (no real orders) at `LOT_SIZE = 0.01`
from a `STARTING_BALANCE` of $200. A `TRADING_MODE=LIVE` path exists but
**must not be switched on** until the MT5 symbol/contract size is verified (§8).

**Difference from the gold bot, in one line:** BTC is M5 (gold M1), RR 1:2
(gold 1:1.5), wick 0.15 (gold 0.38), %-based ATR bounds (gold absolute $),
24/7 with no rollover blackout and no quiet hours, and **no breakeven (BE)
ratchet** — the gold bot's BE stop is *not* ported (`docs/REVIEW-2026-09-15.md`
§5 re-tested it: tight triggers still lose on BTC).

## 3. Data feed: Twelve Data (default) / MT5 sidecar (option)

`DATA_SOURCE` env var in `/opt/bitcoin/.env` picks the feed; code default is
`TWELVEDATA` (WebSocket, `TWELVE_DATA_API_KEY`).

- **Twelve Data caveat**: the free plan's WebSocket is a *trial* allotment.
  When it expires the endpoint accepts the handshake and immediately closes —
  the log silently stops growing and a zombie socket never raises. This is
  exactly what killed the gold feed. If `forward_test_log.csv` stops growing,
  check the plan/WS status at api.twelvedata.com first.
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
  Env overrides: `MT5_FEED_FILE`, `MT5_FEED_SYMBOL` (default `BTCUSD`; XM may
  list `BTCUSDm`), `MT5_FEED_TIMEFRAME` (default `M5`), `MT5_FEED_POLL`.
  Ops check: `jq .updated_at /opt/bitcoin/mt5_last_candle.json` (≤2 min old).
  Smoke Scenario H covers the read/normalize/dedup path.
- Deploy note (gold lesson): put `Environment=PYTHONUNBUFFERED=1` in the
  engine's systemd unit or prints are block-buffered out of `journalctl`.

## 4. Current risk gates (trade_filter.py)

- **SL cooldown**: 30 min after 1 SL, escalating to **60 min after 2
  consecutive SLs**. This is by far the most-triggered gate (37 of 70 logged
  skips) and its cost is still unmeasured (`docs/REVIEW-2026-09-15.md` §6).
- **Daily breaker**: `MAX_DAILY_LOSSES = 3` SLs per UTC day → hard halt for the
  rest of the day. (Gold uses 10 + a trend-side-only mode; BTC keeps the hard
  halt.) The pre-port days (09-05/06/07, 13/10/6 SLs) are before the breaker
  existed. Under the current stack it has engaged 18 times and the phantom
  replay of those 18 blocked signals is **−$4.93 (3W/15L) → the halt is
  protective, keep it**. The counter reads a **400-row window** (`DAY_WINDOW`)
  because a 30-row window silently under-counts busy days.
- **Blackouts (UTC)**: London 07:55–09:00, NY pre-market 12:25–12:45,
  NY open & US macro 13:25–15:15. All block **both** directions
  (gold's direction-aware London carve-out is *not* ported — no BTC evidence).
  **No rollover blackout** (BTC has no rollover) and no weekend pause.
- **ATR bounds (% of price)**: `MIN_ATR_PERCENT = 0.0001` (0.01%),
  `MAX_ATR_PERCENT = 0.0060` (0.60%). Observed live ATR% at entry runs
  0.006%–0.275%, so the **upper bound has never bound** and the lower bound has
  fired 6 times (all of them pre-log, none scorable). The floor is **not** a
  cost control: at 0.01% ($7.70 at $77k) it sits ~10× below the level implied by
  the spread (see `docs/REVIEW-2026-09-15.md` §1: keep the round trip at ≤15% of
  1R ⇒ `ATR ≥ 333 × spread$`).

Engine-side there is **no BE ratchet and no time stop** — a BTC trade only ends
at SL or TP. Exit-reason domain is therefore `{SL, TP}` only; every tool
assumes that.

## 5. Evidence base (73 trades, 2026-09-03 → 09-15) — don't re-derive

Headline: **30W/43L (41.1%), engine ledger $208.74, true equity −$183.10.**
The raw Profit column sums to −$383.10, dominated by **two pre-port trades on
09-03 that ran with a broken lot/size setup (−$197.63 and −$197.21)**.
Excluding them (trades from 09-05 on): **71 trades, 30W/41L, 42.3%, +$11.74
gross** (+$0.165/trade). Always state which figure you are quoting, and always
say **gross** — no cost is modeled anywhere in the ledger.

**Ledger geometry changed on 09-06 17:49 UTC** (SL 1.5×ATR / TP 2.5×ATR
→ 2×/4×, i.e. RR 1:1.67 → 1:2). Pooled R totals across that line are invalid;
`check_data.py` and `replay_lib` now enforce the era split. Era-correct:
pre-09-06 17:49 n=37 40.5% −$393.62 (realized −199.6R) · from 09-06 17:49 n=36
41.7% +$10.52 (realized +8.3R).

- `check_data.py` reports **0 fail, 61 warn**, all known: duplicate `Trade_Num`
  values, `Balance_After` continuity breaks (pre-port ledger resets), a
  ledger-vs-sum drift of +$391.84 (that drift **is** the two 09-03 monsters plus
  the resets, not a live accounting bug), one missing M5 slot in the log
  (09-14 08:45) and the geometry-era warnings above.
- **New-regime slice (n=19, from 09-09): 7W/12L, +$8.73 gross.** R-multiples
  are clean on live-era rows (winners ≈ +2R, losers ≈ −1R; the only two
  overshoots, #40/#52 at −1.38R, are tick timing at fast moves, not sizing
  drift). Last 10: 1W/9L, −$9.98.
- **SELLs (post-port) are the better side so far**: 10 trades, 4W/6L, +$4.91
  vs BUYs 9 trades, 3W/6L, −$0.93. n is far too small to act on, and the
  signal census disagrees (see the review §4).
- **Cost is the dominant term**: gross edge +$0.17/trade (n=71) vs published
  XM BTCUSD spread $0.225–0.60/trade at 0.01 lot = 0.13–0.35R at live ATR.
  Breakeven-WR-vs-cost table: `win_rate_report.py` §8.
- **Gate replay** (`validate_gates.py`, all trades): every adopted gate is
  positive on the sample it can score —
  `SLOPE30` 4W/2L +$11.09 · `ABV50s` 4W/1L +$15.68 · `RISE120` 4W/2L +$12.76 ·
  `PROX1.0` 5W/1L +$17.20 · adopted combo (SLOPE30+ABV50s+NOH8) 4W/1L +$15.68.
  Caveat: gates can only be replayed where the price log covers the entry, so
  these all score the **recent** trades (the log starts 09-07 20:20 UTC).
- **Phantom (blocked) signals** (`phantom_trades.py`, rewritten onto
  `replay_lib`; 70 skips, 24h horizon + TIME mark-to-market, `--spread`):
  daily-halt 18 blocked all scorable → **3W/15L, −$4.93 gross / −$9.43 net (the
  halt is protective)** · blackout 6 scorable → +$8.27 gross / +$6.77 net ·
  cooldown only **4 of 37 scorable** → +$0.84 gross / −$0.16 net · ATR floor 0
  scorable. Totals: +$4.18 gross, **−$2.82 net** at $0.25. Sequential view
  (in-trade + cooldown dedup): 16 taken, 8W/8L, +$16.82 gross / +$12.82 net —
  an estimate, not a fact.
  → **The cooldown's cost is still unmeasured on BTC** (33 of 37 blocks predate
  the 09-07 20:20 log start). Unchanged from the last handoff.
- **RSI ≥ 45 (gold's adopted filter) does NOT transfer — and reverses
  within-day**: pooled keep 30.5% +$0.76 vs skip 29.4% −$1.31; own-day keep
  22.0% −$28.32 vs skip 29.4% −$1.31. Do not port it.
- **ATR% ≥ 0.06 is a calendar proxy — rejected on win-rate grounds**: pooled
  keep 44.0% +$22.09 vs skip 3.8% −$22.63, but the own-day control collapses to
  n=4 (67 signals sit on days where the split selects everything or nothing) and
  the sign flips. The ATR%<0.02 churn bucket is **pre-era only** (all 33 trades
  on 09-05/06, when the floor was still 0.04%). Only the **cost-ratio** version
  of an ATR floor survives (review §1).
- **Two filter candidates survive the own-day control but need n≥30**: wick
  ratio ≤ 0.40 (own-day keep 37.0% +$13.40 vs skip 20.0% −$17.23, drops 2) and
  entry within 0.15 ATR of EMA50 (own-day keep 62.5% +$13.18, n=8 vs skip 32.6%
  +$9.23). `analyze_losers.py` agrees in direction: winners entered 0.78 ATR
  from EMA50 vs 1.40 for losers; wick quality 62.5% (W) vs 48.5% (L).
  **Monitor/log-only — do not gate on them yet.**
- **BE ratchet: still not adopted** (review §5). Tight triggers lose (0.5R and
  0.75R both below "off" in both views; gold's adopted 0.75R is the *worst* row
  here). Best row is +1.0R (cascade takeable census, net of $0.25 spread:
  +$8.69 vs +$5.98 off) — a $2.71 edge on 29 trades, i.e. noise. All tools are
  BE-aware, so a future adoption can be measured; use +1.0R if ever armed.
- **The 09-11→09-14 collapse is regime, not parameters** (review §7): 09-12 was
  a 15×ATR range day with median ATR $29 where all 21 census signals stopped;
  09-14 was a 26×ATR day that went 7 TP/7 SL on 14 BUY signals while the
  cascade/halt let only 4 through. Nothing to retune on 19 trades.
- **Hour-of-day** is noise at this n. Do not build session filters on it yet.

## 6. Tooling (run in this order on every data drop)

```bash
python3 tools/check_data.py                        # 1. integrity gate — FIRST ("0 fail")
python3 tools/win_rate_report.py --spread 0.25     # 2. baseline/eras/slices/filters/cost
python3 tools/pathwalk_sims.py --spread 0.25 --census   # 3. exit-rule replay (validates itself first)
python3 tools/analyze_losers.py --spread 0.25      # 4. winner/loser feature drift + stop grid
python3 tools/validate_gates.py                    # 5. replay entry gates vs all historical trades
python3 tools/phantom_trades.py --spread 0.25      # 6. what did the blocked signals actually do?
python3 tools/smoke_test.py                        # 7. engine regression tests (scenarios A–I)
```

All read-only except the engine's own self-healing migration. **The analysis
core is `tools/replay_lib.py`** — one walk implementation (direction-safe,
SL-first tie-break, BE-aware, horizon + TIME mark, cascade replay) that every
tool imports. **Never hand-roll a bar walk**: gold's equivalent tool shipped
with a SELL excursion inversion that made it validate itself against its own
bug. `pathwalk_sims.py` prints its agreement rate with the engine *first*
(19/19 for the log-covered trades) and `smoke_test.py` Scenario I locks the
direction/ratchet/horizon rules.

## 7. Next steps (in order)

1. **Measure the real XM BTCUSD spread** (MT5 symbol spec + a tick-log sample).
   Published XM BTCUSD spreads run $22.50–60 per BTC ⇒ $0.225–0.60 per round
   trip at 0.01 lot, against a gross measured edge of $0.17/trade. Nothing
   cost-sensitive should be tuned before this number exists. If it is wide,
   the options are a tighter-spread account, a cost-ratio ATR floor
   (`ATR ≥ 333 × spread$` for ≤15% of 1R), or fewer/larger-ATR trades.
2. **Collect to 30 live-era trades** (19 today). Then re-run §6's suite and
   re-cut `docs/REVIEW-2026-09-15.md`; only then decide: the +1.0R BE ratchet
   (currently ~2 trades of noise), the wick ≤0.40 and near-EMA ≤0.15 candidates
   (own-day control holds, n too small), and whether the SELL/BUY conflict
   resolves.
3. **Instrument, don't gate**: log the wick/near-EMA feature per signal so the
   candidates can be re-read at 30+ samples without another archaeology pass.
4. **Let the log cover the cooldown blocks.** 33 of 37 cooldown skips still
   predate the 09-07 20:20 log start, so `phantom_trades.py` cannot score them.
   No cooldown change before that — and note the sequential estimate (+$16.82 on
   16 reconstructed trades) is an upper bound, not evidence.
5. **Keep the daily halt** (phantom replay: −$4.93, protective) and the current
   geometry (1:2). Do not raise `MIN_ATR_PERCENT` on win-rate grounds — that
   evidence is a day proxy (review §2).
6. **Before any LIVE test**: confirm `SYMBOL_MT5` (`BTCUSD` vs `BTCUSDm`) and
   XM's BTC contract size, add a live spread check before order dispatch, and
   re-check that `MIN_ATR_PERCENT` is consistent with the measured spread.
7. Longer-term: higher-timeframe (15m/1h) trend confirmation.

### Explicitly NOT queued (with the evidence that closed them)

- **BE ratchet adoption** — tight triggers lose on BTC in both views; +1.0R
  edge is 2 trades. Re-open only at 30+ live trades with a measured spread.
- **RSI ≥ 45** — reverses within-day (review §3).
- **ATR floor by win rate** — calendar proxy (review §2).
- **Direction-aware London blackout / cooldown softening / trend-side breaker** —
  still no BTC evidence (review §6); the hard halt is protective.

## 8. How to verify code changes (always)

```bash
python3 tools/smoke_test.py                      # must print "SMOKE TEST PASSED" (A–I)
python3 -m py_compile engine.py trade_filter.py dashboard.py
python3 tools/check_data.py                      # expect "0 fail" (warnings are normal)
```

Never enable `TRADING_MODE=LIVE` as part of an unrelated change.

## 9. Data gotchas (hard-won — read before analyzing)

- **The two 09-03 trades (−$197.63, −$197.21) are not comparable to anything
  else** — pre-port sizing. Exclude them from every P&L statistic and say so.
- `trades.csv` has multiple batches: `Trade_Num` **restarts** (duplicates at 20
  rows, resets after rows 2/13/14/20) because of pre-port balance resets.
  **Dedupe by timestamp, never by Trade_Num.** `Balance_After` has 9 continuity
  breaks for the same reason.
- **Legacy rows are comma-formatted** (`"80,832.88"`) — 58 of 61 rows. Naive
  `float()` breaks. Every loader must strip commas (all `tools/` do).
  New rows are written plain `%.2f`.
- Schema is **16 fields with `Trade_Type`**; `engine.migrate_trades_csv()`
  self-heals drift on start and before every append (keeps a
  `.bak-pre-migration` backup) and `trade_filter.load_recent_trades()` has a
  loud drift tripwire.
- **The price log only starts 2026-09-07 20:20 UTC** (904 M5 rows). 57 of 61
  trades therefore have no log row within ±6 min — that is the source of every
  `check_data.py` cross-file warning, and the reason `validate_gates.py` and
  `phantom_trades.py` can only score the tail. **Any conclusion drawn from
  log-joined analysis is a statement about the last ~7 trades only.**
- Per-trade replay must use **±6 min** windows (M5 cadence); gold uses ±2 min
  on M1. Gap threshold is >15 min (gold: >5).
- `archive/forward_test_log_m1.csv` (8,537 rows, Sep 1) is **M1** data from the
  pre-M5 design. Never mix it with the M5 log in any analysis.
- Exit reasons are `{SL, TP}` only — no `BE` rows on BTC (unlike gold). If you
  ever add BE, R-multiple math must reconstruct the original 2×/4×ATR geometry
  from `ATR_At_Entry` (1R$ ≈ 2×ATR×lot), as gold's tools do.
- Simulated P&L is scaled by `LOT_SIZE = 0.01`, no spread/slippage modelled.
  Phantom P&L uses the same scaling — it is an upper bound.
- `status.json` equity ($215.39) is the **engine ledger**, not the sum of the
  Profit column. `check_data.py` reports the drift by design.

## 10. How to keep this file honest (do this every session)

1. Update **§1** (date, trade count, new-regime count, branch/PR state).
2. Update **§4/§5** if params changed or a review produced new numbers —
   replace stale figures, don't append.
3. Move anything you shipped out of **§7** and into `archive/PROJECT_LOG.md`'s
   changelog; add whatever the session queued.
4. Write the analysis itself in `docs/REVIEW-YYYY-MM-DD.md`; this file only
   carries the *conclusion* and a pointer. The current one is
   `docs/REVIEW-2026-09-15.md` (73 trades) — re-cut it rather than starting a
   new file unless the question changed.
4b. Never quote a pooled R total or a breakeven WR across the 09-06 17:49
   geometry change, and never quote a P/L without saying whether it is gross
   (the ledger has no cost in it). Both traps have bitten this project twice.
5. Commit with a message that names the doc, so `git log --oneline` stays a
   usable index of decisions.

## 11. File map (short)

`engine.py` signals/execution · `trade_filter.py` risk gates ·
`dashboard.py` port 6001 · `trades.csv` ledger (16 fields) ·
`forward_test_log.csv` M5 bars + indicators · `skipped_trades.csv` blocked
signals (+reason) · `status.json` live state · `tools/replay_lib.py` shared
bar-walk core · `tools/` analysis + tests · `deploy/mt5feed.service` sidecar
unit · `docs/PORT-2026-09-10.md` what came from gold and why ·
`docs/REVIEW-2026-09-15.md` first data review ·
`archive/PROJECT_LOG.md` full history · **this file** = executive summary.

## 12. Reading order for a brand-new agent

1. **`docs/HANDOFF.md`** (this file)
2. `archive/PROJECT_LOG.md` — changelog + current strategy state
3. `docs/PORT-2026-09-10.md` — what the gold port changed and why
4. `docs/REVIEW-2026-09-15.md` — most recent data findings (and what is queued)
5. `git log --oneline` — what changed recently

Then run `python3 tools/check_data.py` before drawing any conclusion from the CSVs.
