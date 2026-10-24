# START-LEVER1 — Wine MT5 Order Execution (`US100Cash` LIVE Path)

This runbook governs moving `engine.py` from `FORWARD_TEST` to real MetaTrader 5 order execution on XM's **`US100Cash`** (`0.10` lot = `$0.10`/index point) via the Wine sidecar `tools/mt5_executor.py`.

---

## Architecture on Linux (`/opt/nasdaq`)

Because `MetaTrader5` has no native Linux Python wheel, order execution uses the same battle-tested Wine IPC pattern as `tools/mt5_feed.py`:

```text
[ engine.py (Linux) ]  -- writes intent.json -->  /opt/nasdaq/mt5_bridge/
                       <-- reads result.json  --
                       <-- reads positions.json -- [ tools/mt5_executor.py (Wine) ] <-> [ XM MT5 Terminal ]
```

*(When `engine.py` runs natively on Windows or inside `tools/live_path_probe.py` with `MetaTrader5` importable, it also supports direct in-process `mt5.order_send` with identical safety guards.)*

---

## Built-In Safety Locks (`tools/mt5_executor.py` + `engine.py`)

1. **Dormant by default (`MT5_EXEC_ENABLED=0`):** Even if `mt5exec-nasdaq.service` is running, it only publishes read-only `positions.json` and rejects any order intent with `DISABLED` until `MT5_EXEC_ENABLED=1`.
2. **Real-money lock (`MT5_EXEC_ALLOW_REAL=0`):** Queries `mt5.account_info().trade_mode` before every order and refuses `ACCOUNT_TRADE_MODE_REAL` (`2`) unless `MT5_EXEC_ALLOW_REAL=1` is explicitly set.
3. **Kill-switch file (`/opt/nasdaq/HALT`):** Creating `/opt/nasdaq/HALT` (`touch /opt/nasdaq/HALT`) blocks all new entries immediately and flattens any open `MAGIC_NUMBER = 987656` positions when `MT5_EXEC_FLATTEN_ON_HALT=1`.
4. **Idempotent `intent_id`:** Durable `mt5_bridge/state.json` persists `SENDING` *before* `mt5.order_send()` is called; duplicate `intent_id`s never double-send.
5. **`None` / Timeout Quarantine:** If `order_send()` returns `None`, both `mt5_executor.py` and `engine.py` quarantine retries until `positions_get()` / deal history reconciles broker state.
6. **Broker Hygiene:** Decodes `symbol_info().filling_mode` bitmask (`1=FOK`, `2=IOC`) to `ORDER_FILLING_*` enum (`0=FOK`, `1=IOC`, `2=RETURN`), enforces `MAX_SPREAD_POINTS = 8.0` and `MAX_SPREAD_TO_1R = 0.35`, validates `volume_min`/`volume_max`/`volume_step` without silent lot upsizing, checks `trade_stops_level`, and reconciles exits by `position_id` (summing `profit + commission + swap + fee`).

---

## Stage Progression

### Stage A — Offline Verification (Completed)
```bash
python3 tools/live_path_probe.py
python3 tools/smoke_test.py
```

### Stage B — XM Demo Account Execution Soak
1. Ensure the Wine MT5 terminal is logged into an **XM Demo** account with **Algo Trading** enabled and `US100Cash` visible in Market Watch.
2. Install `deploy/mt5exec.service` as `/etc/systemd/system/mt5exec-nasdaq.service` with:
   - `MT5_EXEC_ENABLED=1`
   - `MT5_EXEC_ALLOW_REAL=0` (keeps real-money accounts hard-blocked!)
3. Set `TRADING_MODE=LIVE` in `/opt/nasdaq/.env` (or `nasdaq-engine.service`) and restart `nasdaq-engine`.
4. Observe **5–10 closed demo round-trips**, verifying:
   - Fill prices, SL/TP levels, and broker close P/L match `trades.csv` and `status.json`.
   - `touch /opt/nasdaq/HALT` flattens an open demo trade cleanly and `rm /opt/nasdaq/HALT` resumes normal operation.

### Stage C — Real Account Cutover
Only after all three gates in `docs/HANDOFF.md` §7 pass:
1. Log the Wine MT5 terminal into the funded XM account (`$200+` equity for `0.10` lot `US100Cash`).
2. Set `MT5_EXEC_ALLOW_REAL=1` and `MT5_EXEC_ENABLED=1` in `/etc/systemd/system/mt5exec-nasdaq.service`, reload systemd, and monitor the first session closely.
