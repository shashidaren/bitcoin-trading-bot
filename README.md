# bitcoin-trading-bot

Forward-testing engine for a Bitcoin (BTC/USD) price-action strategy on **M5
(medium-term)** candles. All trades are simulated (paper) until the strategy
proves an edge. See `archive/PROJECT_LOG.md` for the full architecture,
strategy rules, and changelog.

Ported 2026-09-10 from the lessons in `gold-trading-bot` (see
`docs/PORT-2026-09-10.md` for exactly what was carried over and what was
deliberately adapted for BTC).

## 📁 Where everything lives

| Path | What it is |
|---|---|
| `engine.py` | Data ingestion, indicators (EMA/RSI/ATR), the Buy/Sell signal funnel, trade execution. Includes `migrate_trades_csv()` — self-healing schema fix. |
| `trade_filter.py` | Risk gatekeeper: session blackouts, escalating SL cooldowns, daily-loss circuit breaker, %-based ATR bounds. |
| `dashboard.py` | Web dashboard (port 6001): funnel telemetry, equity, active trade. |
| `trades.csv` | **The ledger** — one row per closed trade (16-field schema with `Trade_Type`). |
| `forward_test_log.csv` | M5 candle log with all indicator values per bar. |
| `skipped_trades.csv` | Every full signal the risk layer blocked, with reason. |
| `status.json` | Live engine state (equity, funnel counters, daily losses). |
| `docs/HANDOFF.md` | **Start here** — executive summary: current state, gates, evidence base, next steps, data gotchas. Paste it into a new session. |
| `archive/PROJECT_LOG.md` | Living changelog, current strategy rules, parameters, to-do list. |
| `docs/PORT-2026-09-10.md` | What was ported from gold-trading-bot and the BTC-specific adaptations. |
| `docs/REVIEW-2026-09-15.md` | The first full data review (73 trades). **§12 is the 2026-09-16 re-cut at 78 trades** — read that first; the body is the provenance behind it. |
| `docs/AUTOSYNC.md` | The unattended sync/deploy loop: cron assumptions, branch rule, Telegram digest legend, what a deploy does to a running trade. |
| `tools/handoff_check.py` | Freshness gate for `docs/HANDOFF.md`: recomputes its snapshot block from the live CSVs, says `HANDOFF FRESH`/`STALE`, and rewrites the block with `--update`. |
| `archive/` | Historical backups, old engine versions, retired helpers (`generate_trades.py`). |

## 🧰 Tools (run in this order on every new data drop)

```bash
python3 tools/handoff_check.py                        # 0. is docs/HANDOFF.md still true?
python3 tools/check_data.py                           # 1. integrity gate — FIRST, trust nothing before it passes
python3 tools/win_rate_report.py --spread 0.40        # 2. baseline/eras/slices/filter candidates/cost
python3 tools/pathwalk_sims.py --spread 0.40 --census # 3. exit-rule replay (prints its agreement rate first)
python3 tools/analyze_losers.py --spread 0.40         # 4. winner/loser feature drift, MAE/MFE, stop grid
python3 tools/validate_gates.py                       # 5. replay entry gates vs all historical trades (gross)
python3 tools/phantom_trades.py --spread 0.40         # 6. what did the blocked (skipped) signals actually do?
python3 tools/smoke_test.py                           # 7. engine regression tests (scenarios A–I)
```

`--spread 0.40` is the measured XM BTCUSD round trip at `LOT_SIZE = 0.01`; the tools default to
`--spread 0` (gross), so a command copied without the flag prints numbers $0.40/trade more
optimistic than the docs. `tools/handoff_check.py` fails the handoff if its command blocks disagree
with its own cost assumption. All tools are read-only except the engine's self-healing migration and
`handoff_check.py --update` (which rewrites only the marked snapshot block in `docs/HANDOFF.md`).
Every walk comes from one implementation, `tools/replay_lib.py` — never hand-roll a bar walk.

## 🚀 Deploying to production

Production files live at `/opt/bitcoin/` (paths hardcoded in `engine.py` /
`trade_filter.py`). Deploy = `git pull` on the server + restart the engine.
On restart the engine auto-migrates `trades.csv` if needed (keeps a
`.bak-pre-migration` backup), resyncs `status.json`, and restores any
open trade.

`tools/autosync.sh` (cron, root) automates this: commits live data, deploys
merged PRs only if the smoke test passes (rolls back otherwise), runs the
integrity gate, and sends a Telegram digest.

## 📡 Forward-test data source

Default is the **Twelve Data WebSocket** (`TWELVE_DATA_API_KEY`). The free plan's
WebSocket access is a *trial* allotment — when it expires the endpoint accepts
the handshake and immediately closes the connection, so the log silently stops.
Check the plan/WS status at [api.twelvedata.com](https://api.twelvedata.com) if
`forward_test_log.csv` stops growing. The engine force-reconnects stale feeds
(10-min silence threshold) and alerts on Telegram — BTC is 24/7, so every
silence is treated as an incident (no quiet hours).

Alternative: `DATA_SOURCE=MT5` in `.env` sources closed M5 BTCUSD candles from the
local Wine MT5 terminal (broker feed, no plan limits). Architecture: the Linux
engine never imports `MetaTrader5` (the package has no Linux wheels) — instead a
small sidecar `tools/mt5_feed.py` runs under the Wine Python in the same prefix
as the terminal and publishes the latest closed candle to
`/opt/bitcoin/mt5_last_candle.json`, which the engine reads. Run the sidecar as
a service: `sudo cp deploy/mt5feed.service /etc/systemd/system/mt5feed-btc.service
&& sudo systemctl daemon-reload && sudo systemctl enable --now mt5feed-btc`
(note the `-btc` suffix — the gold bot owns `mt5feed.service`).
Trading stays simulated either way.

## 🆕 Starting a new session / handing off to a new agent

Read, in this order:
1. **`docs/HANDOFF.md`** — the executive summary; paste it into the new session
2. `archive/PROJECT_LOG.md` — changelog + current strategy state
3. `docs/PORT-2026-09-10.md` — what the gold port changed and why
4. the latest `docs/REVIEW-*.md` (once they exist) — most recent data findings
5. `git log --oneline` — what changed recently

Then run `python3 tools/handoff_check.py` and `python3 tools/check_data.py`
before drawing any conclusion from the CSVs. Document each review cycle in
`docs/REVIEW-YYYY-MM-DD.md` (or re-cut the current one if the question did not
change), add a changelog line to `archive/PROJECT_LOG.md`, and **update
`docs/HANDOFF.md`** — snapshot block via `python3 tools/handoff_check.py
--update`, then the prose per its §10 ritual. `tools/autosync.sh` reports the
handoff verdict in its Telegram digest, so a drifting doc announces itself.
