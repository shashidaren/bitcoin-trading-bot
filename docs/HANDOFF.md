# HANDOFF — read this first in a new session

Paste this file at the start of a new session:
> "I'm working on my Bitcoin trading bot. Here is the handoff: [paste docs/HANDOFF.md]. I want to work on [X]."

This is the **executive summary** of the whole project. It is the BTC twin of
`gold-trading-bot/docs/HANDOFF.md`. Keep it current: every session that changes
code, params, or conclusions must update §1, §4/§5 and §7 before it ends
(see §10 "How to keep this file honest").

---

## 1. Where things stand (as of 2026-09-10, 61 closed trades)

- Repo: `shashidaren/bitcoin-trading-bot`, default branch `main`.
  Current work branch: `arena/01a08db2-bitcoin-trading-bot`.
- **The gold→BTC port is live** (2026-09-10, see `docs/PORT-2026-09-10.md`):
  SELL funnel, EMA-slope + near-EMA regime gates, escalating SL cooldowns,
  daily-loss breaker, UTC everywhere, self-healing 16-field ledger, stale-feed
  guard, MT5 sidecar option, `tools/` suite.
- **Post-port ("new-regime") sample = 7 trades** (from 2026-09-09 02:25 UTC):
  **5W/2L, +$15.38**, including the first three SELLs (3W/0L, +$12.62).
  Encouraging but far below the n≥30 bar — **do not retune on it**.
- Live bot runs from `/opt/bitcoin/` (paths hardcoded in `engine.py` /
  `trade_filter.py`). Deploy = merge PR → `git pull` on the box → restart the
  engine. Restarts are safe mid-trade (open trade restores from `status.json`,
  stats reload from `trades.csv`, slope gate re-seeds from the log).
- `tools/autosync.sh` (cron, root) does this automatically: commits live data,
  deploys only if `smoke_test.py` passes (rolls back otherwise), runs the
  integrity gate, sends a Telegram digest. It auto-detects the engine/dashboard
  units by scanning systemd for units referencing `/opt/bitcoin`.
- No `docs/REVIEW-*.md` exists yet. **The first review is the next milestone**
  (target: ~20–30 new-regime trades).

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
ratchet** — the gold bot's BE stop is *not* ported (see §7 item 2a).

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
  consecutive SLs**. This is by far the most-triggered gate (33 of 43 logged
  skips).
- **Daily breaker**: `MAX_DAILY_LOSSES = 3` SLs per UTC day → hard halt for the
  rest of the day. (Gold uses 10 + a trend-side-only mode; BTC keeps the hard
  halt.) Note: 09-05/09-06/09-07 show 13/10/6 SLs in a day — those are
  **pre-port** days, before the breaker existed. It has not yet engaged under
  the current stack.
- **Blackouts (UTC)**: London 07:55–09:00, NY pre-market 12:25–12:45,
  NY open & US macro 13:25–15:15. All block **both** directions
  (gold's direction-aware London carve-out is *not* ported — see §7 item 2b).
  **No rollover blackout** (BTC has no rollover) and no weekend pause.
- **ATR bounds (% of price)**: `MIN_ATR_PERCENT = 0.0001` (0.01%),
  `MAX_ATR_PERCENT = 0.0060` (0.60%). Observed live ATR% at entry runs
  0.006%–0.275%, so the **upper bound has never bound** and the lower bound has
  fired 6 times.

Engine-side there is **no BE ratchet and no time stop** — a BTC trade only ends
at SL or TP. Exit-reason domain is therefore `{SL, TP}` only; every tool
assumes that.

## 5. Evidence base (61 trades, 2026-09-03 → 09-10) — don't re-derive

Headline: **28W/33L (45.9%), engine ledger $215.39.** Raw sum of the Profit
column is −$376.45, but that is dominated by **two pre-port trades on 09-03
that ran with a broken lot/size setup (−$197.63 and −$197.21)**. Excluding
them (trades from 09-05 on): **59 trades, 28W/31L, +$18.39.** Always state
which of these two figures you are quoting.

- `check_data.py` reports **0 fail**, plus known warnings: 20 duplicate
  `Trade_Num` values and 9 `Balance_After` continuity breaks (ledger resets
  during the pre-port era) and a ledger-vs-sum drift of +$391.84 — that drift
  **is** the two 09-03 monsters plus the resets, not a live accounting bug.
- **New-regime slice (n=7, from 09-09): 5W/2L, +$15.38.** R-multiples are
  clean: winners +2.0R, losers −1.06R — exactly the 1:2 geometry, so execution
  and the ledger agree with the intended risk model.
- **SELLs work so far**: 3W/0L, +$12.62 on the first three shorts. Small n, but
  the ported mirror is not obviously broken.
- **Gate replay** (`validate_gates.py`, all trades): every adopted gate is
  positive on the sample it can score —
  `SLOPE30` 4W/2L +$11.09 · `ABV50s` 4W/1L +$15.68 · `RISE120` 4W/2L +$12.76 ·
  `PROX1.0` 5W/1L +$17.20 · adopted combo (SLOPE30+ABV50s+NOH8) 4W/1L +$15.68.
  Caveat: gates can only be replayed where the price log covers the entry, so
  these all score the **recent** trades (the log starts 09-07 20:20 UTC).
- **Phantom (blocked) signals** (`phantom_trades.py`, 43 skips): only **1** is
  reproducible against the log — a 09-10 15:10 SELL blocked by the NY macro
  blackout that would have hit TP for **+$5.88**. The other 42 (33 cooldown,
  6 ATR-too-low, 3 blackout) predate the log window and cannot be scored.
  → Conclusion: **the cooldown's cost is currently unmeasured on BTC.** That is
  the single biggest open question, mirroring gold's finding that blocked
  signals outperformed taken ones.
- **RSI buckets** (all 61): RSI<45 n=18 −$1.95 · 45–50 n=7 +$6.18 ·
  50–55 n=11 −$389.94 (both 09-03 monsters live here — ignore) ·
  ≥55 n=25 +$9.26. **No BTC support for gold's "skip RSI<45" filter.** Do not
  port it blind.
- **ATR% buckets** (09-05 on): ATR%<0.02 → 33 trades, −$0.24 (churn, no edge);
  ATR%≥0.10 → 6 trades, **+$12.76**. Weak evidence that **higher volatility is
  where BTC's edge is** — the opposite of gold, where high ATR was toxic.
  Candidate: raise `MIN_ATR_PERCENT`. Needs n≥30 before adopting.
- **Hour-of-day** is noise at this n; the only readable cells are 11:00 (+$7.91)
  and 15:00 (+$5.76, one trade). Do not build session filters on it yet.

## 6. Tooling (run in this order on every data drop)

```bash
python3 tools/check_data.py       # 1. integrity gate — FIRST. Trust nothing before "0 fail"
python3 tools/validate_gates.py   # 2. replay entry gates against all historical trades
python3 tools/phantom_trades.py   # 3. what did the blocked (skipped) signals actually do?
python3 tools/smoke_test.py       # 4. engine regression tests (scenarios A–H)
```

All read-only except the engine's own self-healing migration. **Gold has two
tools BTC does not**: `pathwalk_sims.py` (exit-rule replay) and
`analyze_losers.py` (winner/loser feature drift). Porting them is queued (§7).

## 7. Next steps (in order)

1. **Collect data — 30 new-regime trades.** At 7/30 as of 09-10. After each
   data-collection commit run §6 and compare against §5. Write the findings up
   as `docs/REVIEW-YYYY-MM-DD.md` and add a changelog line to
   `archive/PROJECT_LOG.md`.
2. **Queued changes from the gold bot, in evidence order** (nothing below is
   adopted; each needs BTC evidence at n≥30):
   - (a) **BE (breakeven) stop ratchet** — gold arms SL→entry at +0.30R and it
     cut its bleed 65%. BTC's win rate is 45.9% against a 33% breakeven bar,
     so BE would *convert* winners to scratches: **only adopt if BTC's
     new-regime WR falls below ~35%**, and if adopted, all tools must become
     BE-aware (extra `BE` exit reason + `be_exits` counter) first.
   - (b) **Direction-aware London blackout** (block BUYs only, 07:55–09:00) —
     gold's phantom evidence was 5W/1L. BTC has zero blocked-London samples in
     the log window; wait for phantom evidence.
   - (c) **Cooldown softening / de-escalation** — the cooldown blocks 77% of
     all skipped signals and its cost is unmeasured (§5). First step is
     *measurement*, not a change: keep collecting until the log covers enough
     skips for `phantom_trades.py` to score them.
   - (d) **Raise `MIN_ATR_PERCENT`** (e.g. 0.01% → 0.03–0.05%) — kills the
     ATR%<0.02 churn bucket (33 trades, −$0.24, pure fee/variance drag).
     Cheapest change with real BTC evidence behind it; still wants n≥30.
   - (e) **Trend-side-only daily breaker** (gold's soft breaker) instead of the
     hard 3-SL halt — only if the hard halt starts costing trend days.
3. **Port `pathwalk_sims.py` + `analyze_losers.py`** from gold, adapted to M5,
   RR 1:2 and BTC's `{SL, TP}` exit domain. Do this *before* the first review —
   the review is much weaker without exit-rule replay.
4. **Re-validate the inherited hypotheses.** The regime gates (SLOPE30,
   ABV50s), the SELL mirror windows and the blackout set were all derived on
   *gold* data. §5 gives them early BTC support; the first review must confirm
   or drop them rather than assume.
5. **Revisit `WICK_RATIO_TARGET = 0.15`** (gold uses 0.38 — BTC's is loose) once
   the funnel counters show whether rejection quality separates W from L.
6. **Before any LIVE test**: confirm `SYMBOL_MT5` (`BTCUSD` vs `BTCUSDm`) and
   XM's BTC contract size, and add a live spread check before order dispatch.
7. Longer-term: higher-timeframe (15m/1h) trend confirmation.

## 8. How to verify code changes (always)

```bash
python3 tools/smoke_test.py                      # must print "SMOKE TEST PASSED" (A–H)
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
   carries the *conclusion* and a pointer.
5. Commit with a message that names the doc, so `git log --oneline` stays a
   usable index of decisions.

## 11. File map (short)

`engine.py` signals/execution · `trade_filter.py` risk gates ·
`dashboard.py` port 6001 · `trades.csv` ledger (16 fields) ·
`forward_test_log.csv` M5 bars + indicators · `skipped_trades.csv` blocked
signals (+reason) · `status.json` live state · `tools/` analysis + tests ·
`deploy/mt5feed.service` sidecar unit · `docs/PORT-2026-09-10.md` what came
from gold and why · `docs/REVIEW-*.md` data reviews (none yet) ·
`archive/PROJECT_LOG.md` full history · **this file** = executive summary.

## 12. Reading order for a brand-new agent

1. **`docs/HANDOFF.md`** (this file)
2. `archive/PROJECT_LOG.md` — changelog + current strategy state
3. `docs/PORT-2026-09-10.md` — what the gold port changed and why
4. latest `docs/REVIEW-*.md` — most recent data findings (none yet)
5. `git log --oneline` — what changed recently

Then run `python3 tools/check_data.py` before drawing any conclusion from the CSVs.
