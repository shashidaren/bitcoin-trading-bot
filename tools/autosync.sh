#!/usr/bin/env bash
# ==============================================================================
# tools/autosync.sh — unattended data sync + safe auto-deploy for /opt/bitcoin
# Runs from cron (root). Full documentation: docs/AUTOSYNC.md
#
# Every run:
#   1. Commits the live data files and pushes them to origin/main
#   2. If origin/main advanced (e.g. a merged PR):
#        stops the engine -> merges (conflicts: data files = server wins,
#        everything else = remote wins) -> runs the smoke test -> rolls back
#        on failure -> restarts the engine -> verifies status.json is fresh
#   3. Runs tools/check_data.py (integrity gate)
#   4. Sends a one-message digest to the Telegram chat configured in .env
#
# Safety model:
#   - flock: never two runs at once
#   - data is committed BEFORE any merge, so a rollback never loses data
#   - refuses to deploy if someone hand-edited code files on the server
#   - smoke-test gate with automatic rollback to pre-merge code
#   - .env (secrets) is read but never committed
# ==============================================================================
set -uo pipefail

BTC_DIR="${BTC_DIR:-/opt/bitcoin}"
LOCK_FILE="${LOCK_FILE:-/var/lock/bitcoin-autosync.lock}"
REMOTE="${REMOTE:-origin}"
BRANCH="${BRANCH:-main}"
AUTO_DEPLOY="${AUTO_DEPLOY:-1}"       # 0 = data-only mode (never pull/restart)
SMOKE_GATE="${SMOKE_GATE:-1}"         # 0 = deploy without the smoke test
ENGINE_SERVICE="${ENGINE_SERVICE:-}" # empty = auto-detect the unit running engine.py
DASHBOARD_SERVICE="${DASHBOARD_SERVICE:-}" # empty = auto-detect the unit running dashboard.py
NOTIFY="${NOTIFY:-always}"            # always | quiet (quiet = only on events)
DATA_FILES=(trades.csv forward_test_log.csv skipped_trades.csv status.json)

log() { echo "[$(date -u '+%Y-%m-%d %H:%M:%S')] $*"; }

TG_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
TG_CHAT="${TELEGRAM_CHAT_ID:-}"
if [ -z "$TG_TOKEN" ] && [ -f "$BTC_DIR/.env" ]; then
    TG_TOKEN=$(sed -n 's/^TELEGRAM_BOT_TOKEN=//p' "$BTC_DIR/.env" | head -n1 | tr -d "\"'")
    TG_CHAT=$(sed -n 's/^TELEGRAM_CHAT_ID=//p' "$BTC_DIR/.env" | head -n1 | tr -d "\"'")
fi

tg() {
    if [ -z "$TG_TOKEN" ] || [ -z "$TG_CHAT" ]; then return 0; fi
    curl -s -m 10 -X POST "https://api.telegram.org/bot${TG_TOKEN}/sendMessage" \
        --data-urlencode "chat_id=${TG_CHAT}" \
        --data-urlencode "text=${1}" >/dev/null 2>&1 || true
}

detect_service() {
    # $1 = marker to look for in the unit definition (e.g. 'engine\.py')
    # $2 = optional explicit unit name override (skips detection)
    # Detection is scoped to units that ALSO reference $BTC_DIR, so services
    # belonging to other repos on the same box (e.g. a gold bot with its
    # own engine.py) are never picked up by mistake.
    if [ -n "${2:-}" ]; then echo "$2"; return 0; fi
    local unit def
    while IFS= read -r unit; do
        [ -z "$unit" ] && continue
        def=$(systemctl cat "$unit" 2>/dev/null) || continue
        if printf '%s' "$def" | grep -q "$1" && printf '%s' "$def" | grep -qF "$BTC_DIR"; then
            echo "$unit"; return 0
        fi
    done < <(systemctl list-units --type=service --no-legend --plain 2>/dev/null | awk '{print $1}')
    return 1
}

# --- lock ---------------------------------------------------------------------
exec 9>"$LOCK_FILE" || { log "FATAL: cannot open lock file"; exit 1; }
if ! flock -n 9; then log "another autosync run is active - skipping"; exit 0; fi

cd "$BTC_DIR" || { log "FATAL: cannot cd to $BTC_DIR"; tg "bitcoin autosync: FATAL - cannot cd to $BTC_DIR"; exit 1; }

if [ -d .git/rebase-merge ] || [ -d .git/rebase-apply ] || [ -f .git/MERGE_HEAD ]; then
    log "repo is mid rebase/merge - manual attention required"
    tg "bitcoin autosync: /opt/bitcoin is mid rebase/merge. Fix manually; autosync paused."
    exit 1
fi

git config user.email >/dev/null 2>&1 || git config user.email "autosync@$(hostname)"
git config user.name  >/dev/null 2>&1 || git config user.name  "bitcoin-autosync"
export GIT_TERMINAL_PROMPT=0

DATA_MSG="no new data"
DEPLOY_MSG="none"
EXTRA=""

# --- phase 1: commit live data -------------------------------------------------
for f in "${DATA_FILES[@]}"; do git add -- "$f" 2>/dev/null || true; done
if ! git diff --cached --quiet 2>/dev/null; then
    NEW_TRADES=$(git diff --cached -- trades.csv | grep -c '^+[^+]' || true)
    LAST_N=$(git log --format=%s | sed -n 's/^data collection \([0-9][0-9]*\)$/\1/p' | sort -n | tail -n1)
    N=$(( ${LAST_N:-0} + 1 ))
    if git commit -q -m "data collection $N"; then
        DATA_MSG="committed ${NEW_TRADES} new trade rows -> 'data collection $N'"
        log "data: $DATA_MSG"
    else
        DATA_MSG="COMMIT FAILED (will retry next run)"
        log "data commit failed"
    fi
else
    log "no data changes"
fi

# --- phase 2: fetch & (maybe) deploy ------------------------------------------
git fetch "$REMOTE" "$BRANCH" >/dev/null 2>&1 || log "WARN: git fetch failed (offline/credentials?)"

LOCAL_SHA=$(git rev-parse HEAD 2>/dev/null || echo "")
REMOTE_SHA=$(git rev-parse "$REMOTE/$BRANCH" 2>/dev/null || echo "")

NEED_MERGE=0
if [ -n "$REMOTE_SHA" ] && [ "$LOCAL_SHA" != "$REMOTE_SHA" ]; then
    if git merge-base --is-ancestor "$REMOTE_SHA" HEAD 2>/dev/null; then
        : # local ahead (data commit) - phase 3 will push
    else
        NEED_MERGE=1
    fi
fi

if [ "$NEED_MERGE" = "1" ]; then
    if ! git diff --quiet -- engine.py trade_filter.py dashboard.py tools/ 2>/dev/null; then
        DEPLOY_MSG="SKIPPED - local code edits detected on server (hand-edits are not supported); manual pull needed"
        log "$DEPLOY_MSG"
    elif [ "$AUTO_DEPLOY" != "1" ]; then
        DEPLOY_MSG="SKIPPED (AUTO_DEPLOY=0) - origin/main is ahead; manual pull needed"
        log "$DEPLOY_MSG"
    else
        CODE_CHANGED=$(git diff --name-only HEAD "$REMOTE_SHA" -- '*.py' | grep -c . || true)
        CORE_CHANGED=$(git diff --name-only HEAD "$REMOTE_SHA" -- engine.py trade_filter.py | grep -c . || true)
        DASH_CHANGED=$(git diff --name-only HEAD "$REMOTE_SHA" -- dashboard.py | grep -c . || true)
        SVC=$(detect_service 'engine\.py' "$ENGINE_SERVICE" || true)
        PRE_MERGE=$(git rev-parse HEAD)

        if [ -n "$SVC" ] && [ "$CORE_CHANGED" -gt 0 ]; then
            log "stopping engine ($SVC)"
            systemctl stop "$SVC" >/dev/null 2>&1 || log "WARN: stop $SVC failed"
        fi

        MERGE_RC=0
        if ! git merge "$REMOTE/$BRANCH" -m "autosync: merge upstream (live data kept local)" >/dev/null 2>&1; then
            log "merge conflict - resolving: data files=ours, everything else=theirs"
            for f in $(git diff --name-only --diff-filter=U); do
                case "$f" in
                    trades.csv|forward_test_log.csv|skipped_trades.csv|status.json)
                        git checkout --ours -- "$f" ;;
                    *) git checkout --theirs -- "$f" ;;
                esac
                git add -- "$f" >/dev/null 2>&1 || true
            done
            git commit -q -m "autosync: merge upstream (live data kept local)" >/dev/null 2>&1 || MERGE_RC=1
        fi

        SMOKE="not run (no code change)"
        if [ "$MERGE_RC" = "0" ] && [ "$SMOKE_GATE" = "1" ] && [ "$CODE_CHANGED" -gt 0 ]; then
            if python3 tools/smoke_test.py >/tmp/autosync_smoke.log 2>&1; then
                SMOKE="ok"
            else
                SMOKE="FAIL"
            fi
        fi

        if [ "$MERGE_RC" != "0" ] || [ "$SMOKE" = "FAIL" ]; then
            log "deploy failed (merge_rc=$MERGE_RC smoke=$SMOKE) - rolling back to $PRE_MERGE"
            [ -f .git/MERGE_HEAD ] && git merge --abort >/dev/null 2>&1
            git reset --hard "$PRE_MERGE" >/dev/null 2>&1
            DEPLOY_MSG="ROLLED BACK (smoke=$SMOKE) - needs a manual look"
            EXTRA="$EXTRA
🚨 deploy rolled back - start a review session"
        else
            DEPLOY_MSG="deployed $(git rev-parse --short HEAD) (code files: $CODE_CHANGED, smoke: $SMOKE)"
        fi

        if [ "$CORE_CHANGED" -gt 0 ]; then
            if [ -n "$SVC" ]; then
                log "starting engine ($SVC)"
                systemctl start "$SVC" >/dev/null 2>&1 || DEPLOY_MSG="$DEPLOY_MSG; FAILED to start $SVC"
                sleep 20
                if systemctl is-active --quiet "$SVC" 2>/dev/null; then
                    if [ -z "$(find status.json -mmin -3 2>/dev/null)" ]; then
                        DEPLOY_MSG="$DEPLOY_MSG; engine active but status.json looks STALE"
                    fi
                else
                    DEPLOY_MSG="$DEPLOY_MSG; ENGINE SERVICE NOT ACTIVE"
                fi
            else
                DEPLOY_MSG="$DEPLOY_MSG; engine service NOT FOUND - restart engine manually"
                EXTRA="$EXTRA
⚠️ engine service not detected - manual restart needed"
            fi
        fi
        if [ "$DASH_CHANGED" -gt 0 ]; then
            DSVC=$(detect_service 'dashboard\.py' "$DASHBOARD_SERVICE" || true)
            if [ -n "$DSVC" ]; then
                log "restarting dashboard ($DSVC)"
                systemctl restart "$DSVC" >/dev/null 2>&1 \
                    || DEPLOY_MSG="$DEPLOY_MSG; FAILED to restart $DSVC"
            else
                DEPLOY_MSG="$DEPLOY_MSG; dashboard service NOT FOUND - restart dashboard manually"
            fi
        fi
    fi
fi

# --- phase 3: push -------------------------------------------------------------
PUSH_MSG="ok"
if ! git push "$REMOTE" "$BRANCH" >/dev/null 2>&1; then
    PUSH_MSG="FAILED (data is safe in a local commit; retries next run)"
    EXTRA="$EXTRA
⚠️ push to $REMOTE failed"
fi
log "push: $PUSH_MSG"

# --- phase 4: integrity + stats --------------------------------------------------
CHECK_MSG="not run"
python3 tools/check_data.py >/tmp/autosync_check.log 2>&1
CHECK_RC=$?
CHECK_MSG=$(grep -E '^== result' /tmp/autosync_check.log | tail -n1 | sed 's/^== result: //')
if [ -z "$CHECK_MSG" ]; then
    CHECK_MSG="check_data FAILED to run (rc=$CHECK_RC)"
fi
if [ "$CHECK_RC" != "0" ]; then
    EXTRA="$EXTRA
🚨 check_data: $CHECK_MSG - start a review session"
fi

STATS=$(python3 - <<'PYEOF' 2>/dev/null
import json
try:
    s = json.load(open("status.json"))
    print("equity {eq} | {w}W/{l}L | daily SLs {d}/{m} | open trade: {a} | updated {u} UTC".format(
        eq=s.get("equity"), w=s.get("wins"), l=s.get("losses"),
        d=s.get("daily_losses"), m=s.get("max_daily_losses"),
        a="yes" if s.get("trade_active") else "no", u=s.get("last_update")))
except Exception as e:
    print("status.json unreadable: %s" % e)
PYEOF
)

log "done. data=[$DATA_MSG] deploy=[$DEPLOY_MSG] check=[$CHECK_MSG]"

QUIET_SKIP=0
if [ "$NOTIFY" = "quiet" ] && [ "$DATA_MSG" = "no new data" ] && [ "$DEPLOY_MSG" = "none" ] \
   && [ "$PUSH_MSG" = "ok" ] && [ -z "$EXTRA" ]; then
    QUIET_SKIP=1
fi
if [ "$QUIET_SKIP" = "0" ]; then
    tg "🤖 bitcoin autosync — $(date -u '+%m-%d %H:%M') UTC
📦 data: $DATA_MSG (push: $PUSH_MSG)
🚀 deploy: $DEPLOY_MSG
🩺 integrity: $CHECK_MSG
💰 $STATS$EXTRA"
fi
