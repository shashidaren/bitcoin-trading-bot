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
| `docs/REVIEW-*.md` | Per-cycle data reviews (none yet — first one after real trade data lands). |
| `archive/` | Historical backups, old engine versions, retired helpers (`generate_trades.py`). |

## 🧰 Tools (run in this order on every new data drop)

```bash
python3 tools/check_data.py       # 1. integrity gate — run FIRST, trust nothing before it passes
python3 tools/validate_gates.py   # 2. replay entry gates against all historical trades
python3 tools/phantom_trades.py   # 3. what did the blocked (skipped) signals actually do?
python3 tools/smoke_test.py       # 4. engine regression tests (gates, SELL, drift auto-fix, stale feed)
```

All tools are read-only except the engine's own self-healing migration.

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

Then run `python3 tools/check_data.py` before drawing any conclusion from the
CSVs. Document each review cycle as a new `docs/REVIEW-YYYY-MM-DD.md`, add a
changelog line to `archive/PROJECT_LOG.md`, and **update `docs/HANDOFF.md`**
(see its §10 — that's how changes stay tracked between sessions).
