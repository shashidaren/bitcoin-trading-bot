# MT5 order executor — Wine sidecar (Stage A, Part B)

**Status (2026-10-13):** offline implementation + fake-terminal tests only. The
worker is **not installed or running**, has not been tested against XM/Wine, and
is **not wired into `engine.py`**. The engine still defaults to
`TRADING_MODE = "FORWARD_TEST"`; keep it there. This work does not authorize a
demo order or a real-money order. Real accounts are refused by the worker.

The Linux host cannot import the MetaTrader5 Python package. This sidecar uses
the existing Wine/MT5 prefix pattern, while the engine-facing protocol remains
plain JSON files on the shared `/opt/bitcoin` filesystem:

- `tools/mt5_order_protocol.py` — stdlib-only atomic intent writer/result reader
  for the future Linux engine adapter.
- `tools/mt5_order_executor.py` — Wine worker, demo-account guard, order checks,
  spread/risk guards, one-shot dispatch and persistent broker reconciliation.
- `deploy/mt5order.service` — dormant-by-default systemd unit, installed as
  `mt5order-btc.service` (distinct from the read-only feed and quote services).
- `tools/mt5_order_executor_test.py` — deterministic fake-terminal tests; no
  terminal, broker, credentials, network or production data are touched.

## 1. Boundary and current non-goals

This implements the **executor boundary**, not the complete LIVE path. The
following remain separate Stage A work before a demo run:

1. Refactor `engine.py` to stay Linux-native in trading mode, write one intent
   for an accepted signal, and consume the executor's entry/close results.
2. Reconcile the engine's restart/open-trade state and `trades.csv` ledger from
   those results; keep the existing forward-test path unchanged.
3. Update/promote the engine LIVE-path probes, then make
   `tools/live_path_probe.py` exit 0 and `tools/smoke_test.py` pass.
4. Install and exercise this worker against an XM **demo** account using the
   actual Wine prefix, symbol contract, fill mode, costs and restart/outage
   checklist. The fake cannot verify XM server behavior.

The worker currently accepts only `OPEN` intents; it does not place a manual
close, move stops, or liquidate an open position. An order is sent with the
initial SL/TP attached, so a broker-side stop/target remains server-side. A
manual halt blocks **new entries**; it does not close an existing position.

## 2. File protocol

All paths are local/shared files; there is no HTTP server, localhost call, or
credential in the protocol. The Linux engine and Wine Python must resolve the
same underlying directory.

```text
/opt/bitcoin/mt5_order_bridge/
├── inbox/<intent_id>.json       # engine writes atomically
├── outbox/<intent_id>.json      # executor's latest status; safe to poll/re-read
├── processed/<intent_id>.json   # consumed intent archive
├── quarantine/                  # malformed files, never dispatched
└── state.json                   # durable idempotency/risk/reconciliation state
```

`mt5_order_bridge/` and `/opt/bitcoin/MT5_ORDER_HALT` are ignored by Git and
must never be added to autosync data commits. The worker should be the **only**
executor process watching this queue. Atomic file replacement is used so neither
process observes a partial JSON document.

Version-1 open intent:

```json
{
  "schema_version": 1,
  "intent_id": "0123456789abcdef0123456789abcdef",
  "action": "OPEN",
  "created_at": "2026-10-13T09:05:00Z",
  "signal_ts": "2026-10-13 09:00:00",
  "symbol": "BTCUSD",
  "direction": "BUY",
  "volume": 0.01,
  "atr": 100.0
}
```

Use `OrderBridge(root).submit_open(direction, atr, signal_ts=...)` to write an
intent from Linux. A successful write only means **queued**, not accepted or
filled. The executor re-validates the exact symbol, fixed lot, direction, finite
ATR, timestamp/queue age and schema. It derives stops from the frozen strategy
geometry (SL `2 × ATR`, TP `4 × ATR`); callers cannot supply arbitrary SL/TP or
magic numbers.

The outbox result uses the same `intent_id` and reports `REJECTED`, `UNKNOWN`,
`OPEN`, or `CLOSED`, with fill/position ids, entry/exit prices and, on close,
`gross_profit`, `commission`, `swap`, `fee` and their net sum. The result is
idempotent and is not deleted when read. An unresolved `UNKNOWN` intent blocks
all later entries. A result must be reconciled by the engine before it can be
represented as a ledger trade.

## 3. Guard and dispatch sequence

For each intent the worker:

1. Requires `MT5_ORDER_ENABLED=1`, explicit `MT5_ORDER_ACCOUNT_KIND=demo`, an
   actual MT5 `ACCOUNT_TRADE_MODE_DEMO` account, and an explicit starting-equity
   baseline. The first boot also requires account equity to match that baseline
   within `$1`; changing the baseline or persisted risk policy later fails
   closed. Account login/name/server are not written to logs or result files.
2. Checks the manual halt marker, latched drawdown/orphan state, terminal and
   account `trade_allowed`, daily MT5 history, symbol trading mode/lot limits,
   one-position/one-pending-order-per-magic, and any unresolved prior order. Missing broker state
   or history is not treated as flat/zero risk.
3. Normalizes the tick timestamp using the observed whole-hour broker-server
   offset and rejects stale/invalid quotes. It requires the strategy's ATR
   percentage bounds (`0.01%–0.60%`), and rejects if spread exceeds **either**
   `$60/BTC` **or** `70% of 1R` (`1R = 2 × ATR`). These caps are conservative
   Stage A proposals, not an XM measurement; revisit only after the quote logger
   has produced a real session profile.
4. Decodes `symbol_info().filling_mode` as the broker's
   `SYMBOL_FILLING_FOK`/`SYMBOL_FILLING_IOC` bit flags, selects a valid
   `ORDER_FILLING_*` enum for the execution mode, and requires `order_check()`
   to pass before dispatch.
5. Persists `SENDING` **before** the non-idempotent `order_send()` call. A
   definite broker reject is reported; a missing/timeout/ambiguous response is
   `UNKNOWN`, never automatically resent. On each poll/restart, the worker
   matches positions by magic/comment/stable position id and searches deal
   history. It confirms the broker-reported position has valid server-side
   SL/TP before publishing `OPEN`; if not, it latches `UNPROTECTED_POSITION` and
   reports `UNKNOWN` (no automatic close is attempted). It detects a server-side
   close by querying `history_deals_get` with `position=<position_id>` (not the
   entry order ticket), waits until the position is absent, then sums
   `profit + commission + swap + fee` across that position's deals.

Kill switches for new entries:

- `touch /opt/bitcoin/MT5_ORDER_HALT` — manual stop; remove only after review.
- Three stop-loss closes in the UTC day **or** realized net MT5 P/L `≤ -$10`.
  Deal timestamps are normalized with the fresh tick's whole-hour broker-server
  offset before applying the UTC-day boundary; a missing offset/history blocks entry.
- Account equity `≤ starting_equity - $30`; this is monitored each poll and
  latches in `state.json` across restarts. A terminal switched away from DEMO
  while running also latches a halt. Neither is cleared automatically by
  deposits, equity recovery, switching back to demo, or a service restart.
- Any untracked broker position or pending order with the bot magic, a missing
  server-side SL/TP, or an unresolved send result blocks new entries. The
  sidecar does not auto-close orphans.

## 4. Configuration and dormant service

`deploy/mt5order.service` is deliberately shipped with
`MT5_ORDER_ENABLED=0`; a disabled invocation exits without importing
MetaTrader5 or calling a trading API. No service was installed/enabled in this
session. The example baseline (`200`) is not a recommended default for another
account; it must be deliberately replaced with that demo account's equity
before any approved demo trial. Risk-policy changes after the first boot need
manual state reconciliation rather than a quiet environment edit.

| Variable | Default | Meaning |
|---|---:|---|
| `MT5_ORDER_ENABLED` | `0` | Must be explicitly `1` to run; no default arming |
| `MT5_ORDER_ACCOUNT_KIND` | `disabled` | Only `demo` is accepted |
| `MT5_ORDER_STARTING_EQUITY` | unset | Required, must match first-start demo equity within `$1` |
| `MT5_ORDER_SYMBOL` | `BTCUSD` | Exact Market Watch symbol |
| `MT5_ORDER_MAGIC` | `987655` | Bot position/order tag |
| `MT5_ORDER_VOLUME` | `0.01` | Fixed lot; intent must match |
| `MT5_ORDER_DIR` | `/opt/bitcoin/mt5_order_bridge` | Shared queue/state root |
| `MT5_ORDER_HALT_FILE` | `/opt/bitcoin/MT5_ORDER_HALT` | Manual new-entry kill switch |
| `MT5_ORDER_MAX_SPREAD_USD` | `60` | Hard spread cap per BTC |
| `MT5_ORDER_MAX_SPREAD_TO_1R` | `0.70` | Second spread cap, relative to 1R |
| `MT5_ORDER_MAX_DRAWDOWN_USD` | `30` | Persistent equity drawdown limit |
| `MT5_ORDER_MAX_DAILY_SL` | `3` | UTC-day SL-close limit |
| `MT5_ORDER_MAX_DAILY_LOSS_USD` | `10` | UTC-day realized net-loss limit |
| `MT5_ORDER_QUOTE_MAX_AGE_SECONDS` | `60` | Maximum normalized quote age |

Install/configure only after the engine adapter and a separate operator review:

```bash
sudo cp deploy/mt5order.service /etc/systemd/system/mt5order-btc.service
sudo systemctl daemon-reload
# Do not enable/start it during installation. For a later, specifically
# approved demo run, first set the validated baseline and MT5_ORDER_ENABLED=1.
```

The service uses the existing `WINEPREFIX=/root/.mt5` pattern and expects the MT5
terminal already running/logged in to a demo account in that prefix. It contains
no broker login/password. Do not test this unit against a real account. Do not
run a manual worker at the same time as the systemd worker.

To stop new orders during an approved demo test, create the halt file first and
then stop the service. The sidecar continues to rely on broker-attached SL/TP
for already-open positions; manual handling is still needed if the terminal or
broker loses that protection.

## 5. Offline test and remaining gates

```bash
python3 tools/mt5_order_executor_test.py
python3 tools/smoke_test.py
```

The fake tests cover demo-only arming, baseline/risk policy, quote age, both
spread caps, filling-mode flags, `order_check`, duplicate exposure, manual/daily/
equity stops, no-retry on ambiguous sends, and close reconciliation including
all cost fields. They do **not** verify the XM terminal, MT5 server semantics,
contract specs, spread distribution, demo fill rates, or restart behavior on the
host. Those require the real Wine/demo validation checklist before Stage C.

At this commit the existing `tools/live_path_probe.py` still exercises the old
engine LIVE path (not this worker) and is still expected to fail; this is a
component build, not the Stage A exit. `TRADING_MODE` remains
`FORWARD_TEST`; no order intent is produced by the engine yet, so the queue is
inert unless a separately enabled demo-only producer writes to it.
