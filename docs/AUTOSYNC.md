# AUTOSYNC — Unattended Data Sync & Smoke-Gated Auto-Deploy (`/opt/nasdaq`)

`tools/autosync.sh` runs from root's crontab every 15 minutes on the server hosting `/opt/nasdaq`.

## What Every Run Does

1. **Commits live data** (`trades.csv`, `forward_test_log.csv`, `skipped_trades.csv`, `status.json`, `xm_data/`) as `"data collection N"`.
2. **Fetches `origin/main`:** If `origin/main` advanced (e.g. a merged PR) and `/opt/nasdaq` has no hand-edited code:
   - Stops `nasdaq-engine` if `engine.py` or `trade_filter.py` changed.
   - Merges `origin/main` (`--ours` on live data files, `--theirs` on code/docs).
   - Runs `python3 tools/smoke_test.py` (`SMOKE_GATE=1`) — **automatically rolls back** to `PRE_MERGE` if `smoke_test.py` fails.
   - Restarts `nasdaq-engine` / `nasdaq-dashboard` as needed and checks `status.json` freshness.
3. **Pushes** the commit to `origin/main`.
4. **Runs advisory & integrity gates:**
   - `python3 tools/check_data.py` (ledger + M15 bar census + gate conformance)
   - `python3 tools/handoff_check.py --quiet` (`docs/HANDOFF.md` freshness)
   - `python3 tools/xm_quote_report.py --quiet` (`mt5quotes-nasdaq` liveness, market-hours aware)
5. **Optional Telegram Digest** (`NOTIFY=off|quiet|alerts|always`; static alert text on `STALE` so `alert_once` deduplicates cleanly).

## Cron Setup

```bash
*/15 * * * * /opt/nasdaq/tools/autosync.sh >> /var/log/nasdaq-autosync.log 2>&1
```

## Rules for Operators & Agents

- **Never hand-edit `.py` files in `/opt/nasdaq`** — `autosync.sh` skips deploys when local code is dirty.
- **Never force-push `main`** — live data commits advance `origin/main` every 15 minutes; always merge PRs cleanly.
