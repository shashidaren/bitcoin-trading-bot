# Starting Lever 1 — the two things that actually move the micro-live date

Draft runbook, grounded in `docs/XM-LOGGER.md`, `docs/REVIEW-2026-10-01.md` §6–§7,
`tools/live_path_probe.py` and `deploy/mt5quotes.service`. **Today: 2026-10-13.**

These two items are what the handoff names as the critical path. They run **in
parallel** with ongoing forward-test collection — you do **not** wait for the
~700-trade sample. Neither touches the forward-test sample or `DATA_SOURCE`.

- **A. XM quote logger** → starts the ≥14-day clock (Stage B-i). Mostly
  install-and-watch; the build is done and fake-terminal-tested.
- **B. Stage A** → make the LIVE order path correct (engineering, **no money**).
  This is the real work: 7 findings + a Wine order-executor + kill switches.

Do **not** flip `TRADING_MODE` to `LIVE` at any point in this runbook.

---

## Part A — XM quote + contract-spec logger (start the ≥14-day clock)

**Why:** the paper P/L nets a flat **$0.40** round trip, but the estimated
break-even is ~**$0.63** (1.6× vs the 2.0× gate) and the $0.40 is one
Asian-session sample. The logger
measures XM's real BTCUSD spread + contract spec for 14 days so the cost model
stops being a guess. It is **read-only** — it never sends an order and never
touches `engine.py`/`DATA_SOURCE`.

### Pre-checks (two facts the repo can't know)
```bash
grep DATA_SOURCE /opt/bitcoin/.env            # expect TWELVEDATA (leave it)
systemctl list-units | grep -i mt5            # is the feed sidecar (mt5feed-btc) already installed?
```

### Optional — validate before merging (nothing on /opt/bitcoin changes)
Steps 1–2 can run from a throwaway clone of the branch while the PR is a draft:
```bash
git clone --depth 1 --branch <PR-branch> https://github.com/shashidaren/bitcoin-trading-bot /tmp/xmtest
export WINEPREFIX=/root/.mt5
PY="xvfb-run --auto-servernum wine C:/Python312/python.exe Z:/tmp/xmtest/tools/mt5_quotes.py"
$PY --spec                                   # step 1
MT5_QUOTES_DIR=Z:/tmp/xm_probe $PY --once    # step 2 into a scratch dir
python3 /tmp/xmtest/tools/xm_quote_report.py --root /opt/bitcoin --dir /tmp/xm_probe   # parity vs the LIVE log
```
(The tools are already on `main` as of the merged PR, so you can also just run
them from `/opt/bitcoin/tools/` after autosync pulls.)

### Install & start (on the box, terminal running + logged in, same WINEPREFIX)
```bash
export WINEPREFIX=/root/.mt5
PY="xvfb-run --auto-servernum wine C:/Python312/python.exe Z:/opt/bitcoin/tools/mt5_quotes.py"

# 1. Dry read of the contract spec (writes nothing). Read the JSON.
$PY --spec
```
Expect `account_kind` DEMO/REAL, `filling_allowed_flags`, `trade_stops_level`,
`volume_min 0.01`, `trade_contract_size 1.0`,
`calc_profit_usd_0.01lot_plus_100usd 1.0`, `terminal.maxbars`. **It must contain
no login/name/server/balance** — if it does, stop (allow-list bug).

```bash
# 2. One real cycle into a SCRATCH dir (does not touch xm_data/).
MT5_QUOTES_DIR=Z:/tmp/xm_probe $PY --once
```
Expect, in order: `contract spec recorded` → banner with `server offset +3h`
(summer) → `first run - back-filled N closed M5 bars` → a quote row →
`candles written this run N`. Then the three checks only the real terminal answers:

| Check | Pass | If it fails |
|---|---|---|
| offset a whole hour `+2h`/`+3h` | learned from a fresh tick | `NOOFFSET`: market closed or box clock off — `date -u`, `chronyc tracking` |
| back-filled N ≈ 12 000 | terminal served the history | N ≈ `maxbars` (e.g. 5 000): raise **Tools → Options → Charts → Max bars in chart**, then re-`--backfill 12000` with the service stopped |
| `xm_quote_report.py --dir /tmp/xm_probe` §4 PARITY | **`OK: no time shift`**, matches ≈ all log bars | ±1 h shift = server-time conversion wrong on this broker — **do not start the clock**, open a session |

```bash
# 3. Install & start (note the -btc suffix; the gold bot owns the plain names)
sudo cp /opt/bitcoin/deploy/mt5quotes.service /etc/systemd/system/mt5quotes-btc.service
sudo systemctl daemon-reload && sudo systemctl enable --now mt5quotes-btc
journalctl -u mt5quotes-btc -f      # contract spec recorded / first run - back-filled N / hourly heartbeat

# 4. After ~1 hour
cd /opt/bitcoin && python3 tools/xm_quote_report.py | head -60
```

### The clock + a timing note for starting now
**The ≥14-day clock starts when the first real `OK` row is written — not at
install/merge.** Within a day, confirm: (a) `mt5quotes-btc` and `mt5feed-btc` run
side by side; (b) the autosync digest shows `📈 xm logger: OK …` and `xm_data/`
lands on `main`; (c) the engine was **not** restarted by the deploy.

> **DST (matters because you're starting mid-October).** A run started ~Oct 13
> ends ~Oct 27, which **spans the broker's autumn switch to GMT+2 on Sunday
> 2026-10-25**. The logger is built for this (offset re-learned from fresh ticks;
> DST-straddle bar handled — `XM-LOGGER.md` §5), but on **Oct 25** watch
> `server offset changed` in `journalctl -u mt5quotes-btc` and the report's
> per-day shift flags. The two required complete weekends (Oct 17–18, Oct 24–25)
> both fall inside the window.

### Exit
`python3 tools/xm_quote_report.py` → the line **`Stage B-i exit: MET`** is the
only thing that ends the wait (≥14 complete UTC days incl. 2 complete weekends).
Then read §4 SPREAD/COST/PARITY to decide whether the flat `$0.40` holds — a
human decides, not the tool. Do **not** change `--spread` on anything but that
evidence.

---

## Part B — Stage A: make the LIVE order path correct (engineering, no money)

**Why:** `python3 tools/live_path_probe.py` is **1/9 clean** (4 BLOCKER, 3 HIGH,
1 ADVISORY) and the Linux engine cannot `import MetaTrader5` at all. Fix these,
keep the probe green, **then** go to demo (Stage C). Findings are from
`REVIEW-2026-10-01.md` §6; locations are `engine.py`.

| # | Sev | Where | Defect | Fix |
|---|---|---|---|---|
| 1 | BLOCKER | `check_live_exits` ~L1062 | `history_deals_get(ticket=<ENTRY order>)`; the SL/TP close runs under a **new** order, so it never matches → closes never logged, `trade_active_live` sticks, gates go blind | Query by `position=` (position id from the entry deal / `positions_get`); sum `profit+commission+swap+fee`; confirm closure with `positions_get` |
| 2 | BLOCKER | `restore_open_trade_from_status` L363, `run_live` L1112 | Restart restores the simulated flag but leaves `active_ticket=None`; `run_live` never calls `check_position` → every deploy orphans an open position | On LIVE start, reconcile with `positions_get(symbol=…)` filtered by `MAGIC_NUMBER` and re-attach **or flatten** |
| 3 | BLOCKER | `execute_live_trade` | No spread guard — an order is sent even at a $500 spread | Add a live spread check before dispatch (size from the logger's data once Stage B-i exits) |
| 4 | BLOCKER | `import MetaTrader5` L188–189 | No Linux wheel; `TRADING_MODE=LIVE` can't start on the box | **Wine order-executor sidecar** mirroring `mt5_feed.py`: engine writes an order *intent*; the executor owns spread guard, fill mode, reconciliation and kill-switch, and returns fills — keeps the engine Linux-native and testable |
| 5 | HIGH | ~L977 | `type_filling` hard-coded **FOK** → retcode 10030 `INVALID_FILL` | Pick from `symbol_info().filling_mode`; `order_check()` first |
| 6 | HIGH | ~L981 | `order_send` `None` result not handled → `AttributeError`; a second position can open | Handle `None`; reconcile via `positions_get` **before** any retry |
| 7 | HIGH | `execute_live_trade` | Never calls `positions_get`; `MAGIC_NUMBER` only tags orders → double exposure after a restart/None | One-position-per-magic check before sending |

**Kill switches to build in (Stage A, `REVIEW-2026-10-01.md` §7):** equity floor
(−$30 at 0.01 lot), the existing 3-SL daily halt, one position per magic,
`trade_allowed`/demo-vs-real check at start, a manual-halt file, a stale-quote
check, and a position-aware dead-man alert.

**Definition of done for Stage A:** findings 1–7 (+9) fixed; the executor
designed; `live_path_probe.py` returns 0 BLOCKER/HIGH; add a LIVE scenario to
`smoke_test.py`; **then** Stage C (XM demo through the real path). Stage A is
code changes — do them on a branch, and merge via PR **only** after the probe and
smoke gate are green. (Note: Stage A touches `engine.py`, so unlike the logger
its deploy **will** restart the engine — safe in FORWARD_TEST, but merge via PR,
not by editing the live box.)

---

## Part B.1 — Wine order-executor design (finding 4)

**The architectural fix.** `TRADING_MODE=LIVE` can't run on the Linux box at all
(`import MetaTrader5` has no Linux wheel). Keep the engine **Linux-native and
testable**; move every MT5 call into a **Wine sidecar** that mirrors
`tools/mt5_feed.py` (same `WINEPREFIX`, atomic `.tmp`+`os.replace` JSON,
`newline=""`, offset learned from fresh ticks). The engine emits an **order
intent**; the executor owns price, filling mode, the spread guard, reconciliation
and kill-switches, and returns **fills + positions**. `engine.py`'s current
`execute_live_trade` (builds the full MT5 request, `deviation:50`, hard-coded
`ORDER_FILLING_FOK`, calls `order_send` directly) is replaced by intent emission.

### File contract (all under `/opt/bitcoin/`, atomic writes)

Engine **writes** → `mt5_order_intent.json`; executor consumes (rename to `.done`).
Executor **writes** → `mt5_order_result.json` (latest) + `mt5_positions.json`.

**Intent (engine → executor):**
```json
{"intent_id": "uuid", "ts_utc": "2026-10-13 12:00:00",
 "action": "OPEN", "side": "BUY", "symbol": "BTCUSD", "volume": 0.01,
 "sl": 82840.0, "tp": 83440.0, "magic": 987655,
 "comment": "BTC Engine Live BUY", "client_ref": "trade#126"}
```
`action ∈ {OPEN, CLOSE, FLATTEN}`; `CLOSE`/`FLATTEN` carry `position_id`. The
engine decides *whether* and the SL/TP geometry (point-rounded as today); the
executor decides *price, filling mode, and whether it is safe to send*.

**Result (executor → engine):**
```json
{"intent_id": "uuid", "ts_utc": "...",
 "status": "FILLED", "retcode": 10009,
 "order": 1001, "deal": 2001, "position_id": 1001,
 "side": "BUY", "volume": 0.01, "fill_price": 83040.0, "fill_time_utc": "...",
 "sl": 82840.0, "tp": 83440.0, "profit": null, "error": ""}
```
`status ∈ {FILLED, REJECTED, PENDING, NOOP, ERROR}`. `intent_id` is the
**idempotency key** — the executor never sends twice for one id (finding 6's
double-exposure root cause).

**Positions snapshot (executor → engine) — this is the finding-1 fix:**
```json
{"ts_utc": "...",
 "positions":   [{"position_id":1, "magic":987655, "type":0, "volume":0.01,
                  "price_open":83040.0, "sl":82840.0, "tp":83440.0, "profit":0.0}],
 "closed_recent":[{"position_id":1, "deal":2001, "profit":-2.0, "price":82840.0,
                   "reason_guess":"SL", "time_utc":"..."}]}
```
The engine's `check_live_exits` stops calling `history_deals_get(ticket=<entry
order>)` (never matches the broker's close order) and instead reads
`closed_recent` keyed by **`position_id`** — and confirms via `positions`.

### Kill-switches the executor owns (Stage A §7)
| Guard | Rule | On trip |
|---|---|---|
| Spread | current `ask−bid` > cap (from logger data; hard-cap proposal **$60/BTC**) | `NOOP`, no order |
| Filling mode | pick from `symbol_info().filling_mode`; `order_check()` first (finding 5) | `REJECTED` |
| One-per-magic | any open position with `magic` → refuse new OPEN (finding 7) | `NOOP` |
| `None` result | `order_send` returned `None` → **no retry**, publish positions to reconcile (finding 6) | `ERROR` |
| Stops level | `sl`/`tp` distance ≥ `trade_stops_level`, else adjust/reject | adjust or `REJECTED` |
| Stale quote | refuse to act on a tick older than N s | `NOOP` |
| Trade allowed / demo-vs-real | `account_info().trade_allowed`; refuse real if policy is demo-only | `REJECTED` |
| Equity floor / 3-SL halt | breach → flatten (engine owns the count; executor enforces the flatten) | `FLATTEN` |
| Manual halt | `/opt/bitcoin/HALT` present → flatten + no new orders | `FLATTEN`/`NOOP` |
| Dead-man | engine heartbeat stops → position-aware flatten | `FLATTEN` |

### Reconcile-on-start (finding 2)
Executor on boot: `positions_get(symbol)` filtered by `magic`; publish whatever
it finds in `mt5_positions.json`. Engine on LIVE start reads it and **re-attaches**
(adopt `position_id`, entry/SL/TP from the position) **or flattens** per policy —
replacing today's `restore_open_trade_from_status` + `run_live` gap where
`active_ticket` stays `None`.

### Engine ↔ executor split
- **Engine (Linux, unit-tested):** signals, gates, cooldowns, daily-loss,
  ledger/`status.json`/Telegram, decision → intent; reads result + positions.
- **Executor (Wine):** every MT5 call (`symbol_info(_tick)`, `order_check`,
  `order_send`, `positions_get`, `history_deals_get(position=…)`,
  `account_info`) + all guards above; publishes fills + positions.

### Test plan (mirror the probe)
A `FakeMT5` drives the executor with the documented semantics; extend
`live_path_probe.py` to exercise the **contract**: intent→result round-trip,
`intent_id` idempotency, `None` handling, spread guard, one-per-magic,
reconcile-on-start. Add a `smoke_test.py` LIVE scenario. Definition of done is
unchanged: probe 0 BLOCKER/HIGH + a LIVE smoke scenario → then Stage C demo.

---

## Sequencing & safety

- **Run A and B concurrently with collection.** A is mostly watch-time; B is the
  engineering critical path. Neither waits for the ~700-trade sample.
- **A is read-only and safe to install today.** B changes `engine.py` — keep it
  on a branch behind a green probe + smoke test.
- **The 14-day clock and the sample-size clock are independent** — starting A now
  finishes B-i ~Oct 27 regardless of how many trades accumulate.
- This runbook moves **no** gate and changes **no** parameter. It only starts the
  two clocks the handoff already names as the critical path.

## Where every number/step comes from (don't invent)
Logger install/validation: `docs/XM-LOGGER.md` §3 (checklist) + §4 (report) +
§5 (DST/offset traps). Service unit: `deploy/mt5quotes.service`. Order-path
findings + Stage A scope + kill switches: `docs/REVIEW-2026-10-01.md` §6–§7.
Probe checks: `tools/live_path_probe.py`. Cost assumptions ($0.40 assumed /
~$0.63 break-even, 1.6×): `docs/HANDOFF.md` §5.
