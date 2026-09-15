# AUTOSYNC — unattended data sync + safe auto-deploy

`tools/autosync.sh` is the only thing that touches `/opt/bitcoin` unattended.
It is the reference for the questions "do I need to do anything else?" and
"what does the Telegram digest mean?". Referenced from the script header and
`docs/HANDOFF.md` §1.

---

## 1. What the cron line assumes

```cron
7-52/15 * * * * /opt/bitcoin/tools/autosync.sh >> /var/log/bitcoin_autosync.log 2>&1
```

Minutes 7/22/37/52 of every hour — offset from the top of the hour so it never
collides with the engine's candle handling. The line itself is fine, but it
assumes all of this is already true:

| Requirement | Why | Check |
|---|---|---|
| `/opt/bitcoin` is a git clone of this repo | the script `cd`s there and runs git | `cd /opt/bitcoin && git remote -v` |
| The clone is **on `main`** | `BRANCH=main`: it merges `origin/main` to deploy | `cd /opt/bitcoin && git rev-parse --abbrev-ref HEAD` |
| `tools/autosync.sh` is executable | cron needs the +x bit | `ls -l /opt/bitcoin/tools/autosync.sh` |
| git can **push** to `origin/main` unattended | data commits are pushed every run | `cd /opt/bitcoin && git push --dry-run origin main` |
| cron user is **root** | `systemctl stop/start` the engine | `crontab -l` (root's crontab) |
| `python3` works from that cwd | smoke gate + `check_data.py` | `cd /opt/bitcoin && python3 tools/check_data.py` |
| No **uncommitted hand-edits** in `engine.py` / `trade_filter.py` / `dashboard.py` / `tools/` | the script refuses to deploy over them | `cd /opt/bitcoin && git status --short` |

`.env` is read for the Telegram token/chat id but is never committed or
required — without it the script still runs, it just stays silent.

---

## 2. The branch rule (the one that bites)

**Data flows up `main`; code only comes down `main`.** Every run:

1. commits `trades.csv forward_test_log.csv skipped_trades.csv status.json`
   locally and pushes them to `origin/main`;
2. `git fetch origin main`; **if `origin/main` advanced**, it stops the engine,
   merges (data-file conflicts = server wins, everything else = remote wins),
   runs the smoke gate, rolls back on failure, restarts the engine and checks
   `status.json` is fresh;
3. runs `tools/check_data.py`;
4. sends one Telegram digest.

So a commit sitting on any other branch (e.g. an `arena/*` work branch) will
never reach the bot. **Merging to `main` is the deploy trigger** — that is the
only manual step in the loop, and it is why a review/tooling session ends with
a PR rather than a push.

### What the dates in the ledger mean

Commits named `data collection N` are the script's own data commits. Don't
rebase or squash them away — `tools/check_data.py` and the analysis tools read
the ledger as-is, and a force-push can drop a trading day's log.

---

## 3. Reading the Telegram digest

```
🤖 bitcoin autosync — 09-15 12:22 UTC
📦 data: committed 1 new trade rows -> 'data collection 467' (push: ok)
🚀 deploy: deployed 730bced (code files: 9, smoke: ok)
🩺 integrity: 0 fail, 61 warn
💰 equity 208.74 | 31W/43L | daily SLs 0/3 | open trade: no | updated 2026-09-15 12:20 UTC
```

- **📦 data** — `no new data` is the normal quiet case.
- **🚀 deploy** — `none` means `origin/main` did not move. If it moved, one of
  the states below appears.
- **🩺 integrity** — the `check_data.py` verdict. `0 fail` is required;
  warnings are informational.
- **💰 stats** — straight from `status.json`.

### Deploy states and what they mean

| Digest text | Meaning | Action |
|---|---|---|
| `deployed <sha> (code files: N, smoke: ok)` | merged, smoke test passed, engine restarted if core files changed | none |
| `none` | nothing to deploy | none |
| `SKIPPED (AUTO_DEPLOY=0)` | data-only mode | expected if you set it |
| `SKIPPED - local code edits detected on server` | someone hand-edited code on the box | `cd /opt/bitcoin && git status` → commit or `git checkout -- <file>` |
| `ROLLED BACK (smoke=FAIL)` + 🚨 | the smoke gate failed after merging; code was reset to the pre-merge SHA | read `/tmp/bitcoin_autosync_smoke.log`, fix, re-merge |
| `push FAILED` + ⚠️ | data is safe in a **local commit**, retried next run | fix git credentials on the box |
| `engine service NOT FOUND - restart engine manually` | `detect_service` could not find a systemd unit referencing `/opt/bitcoin` and `engine.py` | restart manually, or set `ENGINE_SERVICE=` in the crontab |
| `engine active but status.json looks STALE` | the service is up but has not written state for 3+ minutes | check the engine log |

Machine-readable history: `/var/log/bitcoin_autosync.log`. Per-run detail:
`/tmp/bitcoin_autosync_smoke.log` and `/tmp/bitcoin_autosync_check.log`.

---

## 4. What a deploy does to a running trade

Safe: the engine restores an open trade from `status.json` and re-seeds its
stats and slope history from `trades.csv` / `forward_test_log.csv` on start, so
a restart mid-trade resumes the same trade. The engine is only stopped and
restarted when `engine.py` or `trade_filter.py` changed (`CORE_CHANGED`); a
`dashboard.py` change only restarts the dashboard.

The smoke gate runs before the restart, so a broken commit is rolled back
*before* the engine ever loads it — this is why `tools/smoke_test.py` must be
kept at exit-code semantics (`SMOKE TEST PASSED` / `sys.exit(1)`). It is the
deploy gate, not just a dev tool: `autosync.sh` reads only the exit code.

---

## 5. Tuning (environment variables, set in the crontab line)

```cron
7-52/15 * * * * AUTO_DEPLOY=1 SMOKE_GATE=1 NOTIFY=quiet /opt/bitcoin/tools/autosync.sh >> /var/log/bitcoin_autosync.log 2>&1
```

| Var | Default | Effect |
|---|---|---|
| `BTC_DIR` | `/opt/bitcoin` | repo location |
| `REMOTE` / `BRANCH` | `origin` / `main` | what to sync against |
| `AUTO_DEPLOY` | `1` | `0` = commit/push data only, never pull or restart |
| `SMOKE_GATE` | `1` | `0` = deploy without the smoke test (**not recommended**) |
| `NOTIFY` | `always` | `quiet` = only message when something happened (data, deploy, failure) |
| `ENGINE_SERVICE` / `DASHBOARD_SERVICE` | auto-detect | pin the systemd unit names if detection fails |
| `LOCK_FILE` | `/var/lock/bitcoin-autosync.lock` | `flock` guard; overlapping runs exit 0 |

At four runs an hour, `NOTIFY=always` is ~96 messages/day. `NOTIFY=quiet` keeps
the digest for the runs that actually changed something.
