#!/usr/bin/env python3
"""Wine MT5 order-executor sidecar for the Nasdaq (US100Cash) engine.

Why this exists:
  The Linux trading engine (`engine.py`) cannot `import MetaTrader5` natively
  (no Linux wheels on PyPI). Just like `tools/mt5_feed.py` bridges M15 candles
  from the Wine MT5 terminal to `/opt/nasdaq/mt5_last_candle.json`, this sidecar
  runs under Wine Python in the same `WINEPREFIX` and bridges live order intents
  and broker position/deal reconciliation via atomic JSON files under
  `/opt/nasdaq/mt5_bridge/` (`Z:/opt/nasdaq/mt5_bridge` in Wine).

Safety & idempotency guarantees (Stage A design, docs/START-LEVER1.md):
  1. DORMANT BY DEFAULT (`MT5_EXEC_ENABLED=0`) and DEMO-LOCKED BY DEFAULT
     (`MT5_EXEC_ALLOW_REAL=0` refuses `ACCOUNT_TRADE_MODE_REAL=2` unless the
     operator explicitly sets `MT5_EXEC_ALLOW_REAL=1`).
  2. Manual kill-switch: if `MT5_EXEC_HALT_FILE` (`/opt/nasdaq/HALT`) exists,
     refuses new entries (and flattens open magic positions when
     `MT5_EXEC_FLATTEN_ON_HALT=1`).
  3. Idempotency by `intent_id`: durable `state.json` records `SENDING` *before*
     calling `order_send()`. Duplicate `intent_id`s return the cached result and
     never call `order_send()` twice.
  4. `None` / unknown `order_send` handling: never raises and never retries
     blindly. Quarantines state as `UNKNOWN` until `positions_get()` or deal
     history resolves whether the broker opened the position.
  5. One-position-per-magic: checks `positions_get(symbol=SYMBOL)` filtered by
     `MAGIC` before every entry; refuses duplicate exposure (`NOOP`).
  6. Live spread guard: blocks entries when `ask - bid > MAX_SPREAD_POINTS` or
     when `ask - bid > MAX_SPREAD_TO_1R * sl_distance`.
  7. Broker hygiene: decodes `symbol_info().filling_mode` bitmask (`1=FOK`,
     `2=IOC`) to `ORDER_FILLING_*` enum (`0=FOK`, `1=IOC`, `2=RETURN`), checks
     `volume_min`/`volume_max`/`volume_step` (never silently upsizes lots!),
     enforces `trade_stops_level`, and runs `order_check()` when available.
  8. Position-ID exit reconciliation: publishes `positions.json` with open
     positions AND `closed_recent` deals keyed by `position_id` (summing
     `profit + commission + swap + fee`), fixing MT5's closing-order ticket trap.

Imports cleanly on Linux without `MetaTrader5` so `tools/smoke_test.py` can
exercise the full engine <-> executor contract offline against a fake terminal.
"""
import argparse
import json
import math
import os
import sys
import time
from datetime import datetime, timedelta, timezone

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

TS_FMT = "%Y-%m-%d %H:%M:%S"
DEFAULT_BRIDGE_DIR = "Z:/opt/nasdaq/mt5_bridge" if os.name == "nt" else "/opt/nasdaq/mt5_bridge"
DEFAULT_HALT_FILE = "Z:/opt/nasdaq/HALT" if os.name == "nt" else "/opt/nasdaq/HALT"

SYMBOL_FILLING_FOK = 1
SYMBOL_FILLING_IOC = 2
ACCOUNT_TRADE_MODE_DEMO = 0
ACCOUNT_TRADE_MODE_CONTEST = 1
ACCOUNT_TRADE_MODE_REAL = 2


def utc_str(epoch=None) -> str:
    t = time.time() if epoch is None else float(epoch)
    return datetime.fromtimestamp(t, tz=timezone.utc).strftime(TS_FMT)


def atomic_write_json(path: str, payload: dict) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = f"{path}.tmp-{os.getpid()}"
    with open(tmp, "w", newline="", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
        fh.write("\n")
        fh.flush()
        try:
            os.fsync(fh.fileno())
        except OSError:
            pass
    os.replace(tmp, path)


def read_json(path: str):
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError, TypeError):
        return None


def estimate_server_offset(tick_time_srv: int, now_epoch: float, max_age_s: float = 300.0):
    if not tick_time_srv:
        return None
    delta = float(tick_time_srv) - float(now_epoch)
    off = int(round(delta / 3600.0)) * 3600
    if abs(off) > 14 * 3600 or abs(delta - off) > max_age_s:
        return None
    return off


def select_filling_mode(symbol_info, mt5_mod) -> int:
    """Decode MT5's SYMBOL_FILLING_* bitmask (1=FOK, 2=IOC) into ORDER_FILLING_* enum."""
    fok_enum = getattr(mt5_mod, "ORDER_FILLING_FOK", 0)
    ioc_enum = getattr(mt5_mod, "ORDER_FILLING_IOC", 1)
    ret_enum = getattr(mt5_mod, "ORDER_FILLING_RETURN", 2)
    flags = int(getattr(symbol_info, "filling_mode", 0) or 0) if symbol_info is not None else 0
    if flags & SYMBOL_FILLING_IOC:
        return ioc_enum
    if flags & SYMBOL_FILLING_FOK:
        return fok_enum
    return ret_enum


def validate_volume(volume: float, symbol_info) -> tuple[bool, str]:
    """Verify volume satisfies symbol_info volume_min/max/step without silent upsizing."""
    if symbol_info is None:
        return False, "symbol_info unavailable"
    vmin = float(getattr(symbol_info, "volume_min", 0.01) or 0.01)
    vmax = float(getattr(symbol_info, "volume_max", 100.0) or 100.0)
    vstep = float(getattr(symbol_info, "volume_step", 0.01) or 0.01)
    if volume + 1e-9 < vmin:
        return False, f"volume {volume} < broker volume_min {vmin} (refusing silent upsize)"
    if volume - 1e-9 > vmax:
        return False, f"volume {volume} > broker volume_max {vmax}"
    if vstep > 0:
        steps = round((volume - vmin) / vstep)
        snapped = vmin + steps * vstep
        if abs(volume - snapped) > 1e-6:
            return False, f"volume {volume} not aligned to volume_step {vstep} (min {vmin})"
    return True, "ok"


def deal_net_profit(deal) -> float:
    total = 0.0
    for field in ("profit", "commission", "swap", "fee"):
        try:
            val = float(getattr(deal, field, 0.0) or 0.0)
            if math.isfinite(val):
                total += val
        except (TypeError, ValueError):
            continue
    return total


class Mt5Executor:
    """Stateful Wine MT5 order-executor worker."""

    def __init__(
        self,
        mt5_mod,
        bridge_dir: str = DEFAULT_BRIDGE_DIR,
        symbol: str = "US100Cash",
        magic: int = 987656,
        enabled: bool = False,
        allow_real: bool = False,
        halt_file: str = DEFAULT_HALT_FILE,
        flatten_on_halt: bool = True,
        max_spread_points: float = 8.0,
        max_spread_to_1r: float = 0.35,
        intent_max_age_s: float = 90.0,
        quote_max_age_s: float = 30.0,
        deviation_points: int = 500,
        poll_s: float = 1.0,
        clock=None,
        sleep=None,
        log=None,
    ):
        self.mt5 = mt5_mod
        self.bridge_dir = bridge_dir
        self.symbol = symbol
        self.magic = int(magic)
        self.enabled = bool(enabled)
        self.allow_real = bool(allow_real)
        self.halt_file = halt_file
        self.flatten_on_halt = bool(flatten_on_halt)
        self.max_spread_points = float(max_spread_points)
        self.max_spread_to_1r = float(max_spread_to_1r)
        self.intent_max_age_s = float(intent_max_age_s)
        self.quote_max_age_s = float(quote_max_age_s)
        self.deviation_points = int(deviation_points)
        self.poll_s = float(poll_s)
        self.clock = clock or time.time
        self.sleep = sleep or time.sleep
        self.log = log or (lambda msg: print(msg, flush=True))

        self.server_offset_s = None
        self._prev_tick_ts = None

        os.makedirs(self.bridge_dir, exist_ok=True)
        os.makedirs(self.processed_dir, exist_ok=True)
        self.state = self._load_state()

    @property
    def intent_path(self) -> str:
        return os.path.join(self.bridge_dir, "intent.json")

    @property
    def result_path(self) -> str:
        return os.path.join(self.bridge_dir, "result.json")

    @property
    def positions_path(self) -> str:
        return os.path.join(self.bridge_dir, "positions.json")

    @property
    def state_path(self) -> str:
        return os.path.join(self.bridge_dir, "state.json")

    @property
    def processed_dir(self) -> str:
        return os.path.join(self.bridge_dir, "processed")

    def _load_state(self) -> dict:
        st = read_json(self.state_path)
        if not isinstance(st, dict):
            st = {}
        st.setdefault("results", {})
        st.setdefault("unknown_intent", None)
        return st

    def _save_state(self) -> None:
        # Keep only the latest 200 intent results in state.json
        keys = list(self.state.get("results", {}).keys())
        if len(keys) > 200:
            for k in keys[:-200]:
                self.state["results"].pop(k, None)
        atomic_write_json(self.state_path, self.state)

    def _account_kind(self, acct) -> str:
        mode = getattr(acct, "trade_mode", None)
        if mode == ACCOUNT_TRADE_MODE_DEMO:
            return "DEMO"
        if mode == ACCOUNT_TRADE_MODE_CONTEST:
            return "CONTEST"
        if mode == ACCOUNT_TRADE_MODE_REAL:
            return "REAL"
        return "UNKNOWN"

    def _learn_offset(self, tick, now: float):
        if tick is None:
            return
        tt = int(getattr(tick, "time", 0) or 0)
        if not tt:
            return
        fresh = self._prev_tick_ts is None or tt != self._prev_tick_ts
        self._prev_tick_ts = tt
        if fresh or self.server_offset_s is None:
            est = estimate_server_offset(tt, now)
            if est is not None:
                self.server_offset_s = est

    def _to_utc_str(self, srv_ts: int, fallback_now: float) -> str:
        if srv_ts and self.server_offset_s is not None:
            return utc_str(int(srv_ts) - self.server_offset_s)
        return utc_str(fallback_now)

    def _magic_positions(self) -> list:
        try:
            raw = self.mt5.positions_get(symbol=self.symbol)
        except TypeError:
            raw = self.mt5.positions_get()
        if not raw:
            return []
        return [
            p for p in raw
            if int(getattr(p, "magic", 0) or 0) == self.magic
            and str(getattr(p, "symbol", self.symbol)) == self.symbol
        ]

    def _recent_closed(self, open_ids: set, now: float) -> list:
        """Build closed-position summaries keyed by position_id using history_deals_get."""
        deals = None
        try:
            dt_from = datetime.fromtimestamp(now - 7 * 86400, tz=timezone.utc)
            dt_to = datetime.fromtimestamp(now + 86400, tz=timezone.utc)
            deals = self.mt5.history_deals_get(dt_from, dt_to)
        except TypeError:
            try:
                deals = self.mt5.history_deals_get()
            except Exception:
                deals = ()
        except Exception:
            deals = ()
        if not deals:
            return []

        entry_out = getattr(self.mt5, "DEAL_ENTRY_OUT", 1)
        entry_inout = getattr(self.mt5, "DEAL_ENTRY_INOUT", 2)
        by_pos = {}
        for d in deals:
            pos_id = int(getattr(d, "position_id", 0) or 0)
            if not pos_id or pos_id in open_ids:
                continue
            sym = getattr(d, "symbol", None)
            if sym and sym != self.symbol:
                continue
            by_pos.setdefault(pos_id, []).append(d)

        closed = []
        for pos_id, pdeals in by_pos.items():
            # Keep if any deal on this position carries our magic (broker SL/TP close deals
            # sometimes have magic=0 on MT5 while the entry deal had magic=self.magic).
            has_magic = any(int(getattr(x, "magic", 0) or 0) == self.magic for x in pdeals)
            # Also allow when FakeMT5 Deal tuple omits magic attribute
            has_magic_attr = any(hasattr(x, "magic") for x in pdeals)
            if has_magic_attr and not has_magic:
                continue
            outs = [x for x in pdeals if int(getattr(x, "entry", -1)) in (entry_out, entry_inout)]
            if not outs:
                continue
            last_out = outs[-1]
            net = sum(deal_net_profit(x) for x in pdeals)
            exit_px = float(getattr(last_out, "price", 0.0) or 0.0)
            t_srv = int(getattr(last_out, "time", 0) or 0)
            closed.append({
                "position_id": pos_id,
                "deal": int(getattr(last_out, "ticket", 0) or 0),
                "order": int(getattr(last_out, "order", 0) or 0),
                "price": exit_px,
                "profit": round(net, 2),
                "exit_reason": "TP" if net > 0 else "SL",
                "time_utc": self._to_utc_str(t_srv, now),
            })
        closed.sort(key=lambda r: r["position_id"])
        return closed[-50:]

    def publish_positions(self, now: float = None) -> dict:
        now = self.clock() if now is None else float(now)
        tick = self.mt5.symbol_info_tick(self.symbol)
        self._learn_offset(tick, now)
        acct = self.mt5.account_info()
        open_pos = self._magic_positions()
        open_ids = {int(getattr(p, "ticket", 0) or getattr(p, "identifier", 0) or 0) for p in open_pos}

        # Resolve quarantined UNKNOWN intent if broker state now answers it
        unk = self.state.get("unknown_intent")
        if unk and open_pos:
            p0 = open_pos[0]
            pid = int(getattr(p0, "ticket", 0) or 0)
            resolved = {
                "intent_id": unk["intent_id"],
                "ts_utc": utc_str(now),
                "status": "FILLED",
                "retcode": getattr(self.mt5, "TRADE_RETCODE_DONE", 10009),
                "order": pid,
                "deal": pid,
                "position_id": pid,
                "side": "BUY" if int(getattr(p0, "type", 0) or 0) == 0 else "SELL",
                "volume": float(getattr(p0, "volume", unk.get("volume", 0.0))),
                "fill_price": float(getattr(p0, "price_open", 0.0) or 0.0),
                "sl": float(getattr(p0, "sl", 0.0) or 0.0),
                "tp": float(getattr(p0, "tp", 0.0) or 0.0),
                "spread": None,
                "message": "reconciled open position after None order_send",
            }
            self.state["results"][unk["intent_id"]] = resolved
            self.state["unknown_intent"] = None
            self._save_state()
            atomic_write_json(self.result_path, resolved)

        bid = float(getattr(tick, "bid", 0.0) or 0.0) if tick else None
        ask = float(getattr(tick, "ask", 0.0) or 0.0) if tick else None
        spread = round(ask - bid, 5) if (bid and ask and ask >= bid) else None

        pos_list = []
        for p in open_pos:
            pid = int(getattr(p, "ticket", 0) or getattr(p, "identifier", 0) or 0)
            ptype = int(getattr(p, "type", 0) or 0)
            pos_list.append({
                "position_id": pid,
                "magic": int(getattr(p, "magic", self.magic) or self.magic),
                "symbol": str(getattr(p, "symbol", self.symbol)),
                "side": "BUY" if ptype == 0 else "SELL",
                "volume": float(getattr(p, "volume", 0.0) or 0.0),
                "price_open": float(getattr(p, "price_open", 0.0) or 0.0),
                "sl": float(getattr(p, "sl", 0.0) or 0.0),
                "tp": float(getattr(p, "tp", 0.0) or 0.0),
                "profit": float(getattr(p, "profit", 0.0) or 0.0),
                "time_utc": self._to_utc_str(int(getattr(p, "time", 0) or 0), now),
            })

        snap = {
            "updated_utc": utc_str(now),
            "updated_epoch": now,
            "symbol": self.symbol,
            "magic": self.magic,
            "enabled": self.enabled,
            "halted": bool(self.halt_file and os.path.exists(self.halt_file)),
            "account_kind": self._account_kind(acct) if acct else "UNKNOWN",
            "trade_allowed": bool(getattr(acct, "trade_allowed", True)) if acct else False,
            "equity": float(getattr(acct, "equity", getattr(acct, "balance", 0.0)) or 0.0) if acct else None,
            "balance": float(getattr(acct, "balance", 0.0) or 0.0) if acct else None,
            "bid": bid,
            "ask": ask,
            "spread": spread,
            "positions": pos_list,
            "closed_recent": self._recent_closed(open_ids, now),
        }
        atomic_write_json(self.positions_path, snap)
        return snap

    def flatten_all(self, now: float, reason: str = "HALT") -> list:
        """Close every open position matching our symbol + magic."""
        closed_results = []
        si = self.mt5.symbol_info(self.symbol)
        tick = self.mt5.symbol_info_tick(self.symbol)
        if tick is None:
            return closed_results
        filling = select_filling_mode(si, self.mt5)
        for p in self._magic_positions():
            pid = int(getattr(p, "ticket", 0) or 0)
            ptype = int(getattr(p, "type", 0) or 0)
            vol = float(getattr(p, "volume", 0.0) or 0.0)
            is_buy = (ptype == 0)
            close_type = getattr(self.mt5, "ORDER_TYPE_SELL", 1) if is_buy else getattr(self.mt5, "ORDER_TYPE_BUY", 0)
            px = float(tick.bid if is_buy else tick.ask)
            req = {
                "action": getattr(self.mt5, "TRADE_ACTION_DEAL", 1),
                "symbol": self.symbol,
                "position": pid,
                "volume": vol,
                "type": close_type,
                "price": px,
                "deviation": self.deviation_points,
                "magic": self.magic,
                "comment": f"Nasdaq Flatten {reason}"[:31],
                "type_time": getattr(self.mt5, "ORDER_TIME_GTC", 0),
                "type_filling": filling,
            }
            res = self.mt5.order_send(req)
            closed_results.append((pid, getattr(res, "retcode", None)))
        return closed_results

    def _finish_intent(self, intent_id: str, result: dict, raw_intent: dict = None) -> dict:
        if intent_id:
            self.state["results"][intent_id] = result
            self._save_state()
        atomic_write_json(self.result_path, result)
        if os.path.isfile(self.intent_path):
            dest = os.path.join(self.processed_dir, f"{intent_id or int(self.clock())}.json")
            try:
                os.replace(self.intent_path, dest)
            except OSError:
                try:
                    os.remove(self.intent_path)
                except OSError:
                    pass
        return result

    def process_intent(self, now: float = None):
        now = self.clock() if now is None else float(now)
        if not os.path.isfile(self.intent_path):
            return None

        intent = read_json(self.intent_path)
        if not isinstance(intent, dict):
            return self._finish_intent("invalid", {
                "intent_id": None, "ts_utc": utc_str(now),
                "status": "REJECTED", "message": "unparseable intent.json",
            })

        iid = str(intent.get("intent_id") or "").strip()
        if not iid:
            return self._finish_intent("missing-id", {
                "intent_id": None, "ts_utc": utc_str(now),
                "status": "REJECTED", "message": "missing intent_id",
            })

        # 1. Idempotency: never execute the same intent_id twice
        cached = self.state["results"].get(iid)
        if cached and cached.get("status") != "SENDING":
            return self._finish_intent(iid, cached, intent)

        # 2. Quarantine guard after an earlier None response
        if self.state.get("unknown_intent"):
            return self._finish_intent(iid, {
                "intent_id": iid, "ts_utc": utc_str(now),
                "status": "NOOP",
                "message": "executor quarantined after earlier unknown order_send; reconcile first",
            }, intent)

        # 3. Armed & Halt checks
        if not self.enabled:
            return self._finish_intent(iid, {
                "intent_id": iid, "ts_utc": utc_str(now),
                "status": "REJECTED",
                "message": "executor disabled (set MT5_EXEC_ENABLED=1 to arm)",
            }, intent)

        if self.halt_file and os.path.exists(self.halt_file):
            return self._finish_intent(iid, {
                "intent_id": iid, "ts_utc": utc_str(now),
                "status": "NOOP", "message": f"manual HALT file active ({self.halt_file})",
            }, intent)

        action = str(intent.get("action") or "OPEN").upper()
        if action == "FLATTEN":
            closed = self.flatten_all(now, reason="INTENT")
            return self._finish_intent(iid, {
                "intent_id": iid, "ts_utc": utc_str(now),
                "status": "FILLED", "closed": closed, "message": "flattened",
            }, intent)

        # 4. Account mode & permissions check
        acct = self.mt5.account_info()
        if acct is None:
            return self._finish_intent(iid, {
                "intent_id": iid, "ts_utc": utc_str(now),
                "status": "ERROR", "message": "account_info() returned None",
            }, intent)
        kind = self._account_kind(acct)
        if kind == "REAL" and not self.allow_real:
            return self._finish_intent(iid, {
                "intent_id": iid, "ts_utc": utc_str(now),
                "status": "REJECTED",
                "message": "REAL account blocked by default (set MT5_EXEC_ALLOW_REAL=1 to allow live funds)",
            }, intent)
        if not getattr(acct, "trade_allowed", True):
            return self._finish_intent(iid, {
                "intent_id": iid, "ts_utc": utc_str(now),
                "status": "REJECTED", "message": "account trade_allowed is False",
            }, intent)

        # 5. Intent freshness & symbol match
        ts_epoch = intent.get("ts_epoch")
        if ts_epoch is not None and (now - float(ts_epoch)) > self.intent_max_age_s:
            return self._finish_intent(iid, {
                "intent_id": iid, "ts_utc": utc_str(now),
                "status": "NOOP", "message": "stale order intent expired",
            }, intent)

        sym = str(intent.get("symbol") or self.symbol)
        if sym != self.symbol:
            return self._finish_intent(iid, {
                "intent_id": iid, "ts_utc": utc_str(now),
                "status": "REJECTED", "message": f"symbol mismatch ({sym} != {self.symbol})",
            }, intent)

        # 6. One-position-per-magic guard
        existing = self._magic_positions()
        if existing:
            pid = int(getattr(existing[0], "ticket", 0) or 0)
            return self._finish_intent(iid, {
                "intent_id": iid, "ts_utc": utc_str(now),
                "status": "NOOP", "position_id": pid,
                "message": f"position #{pid} already open for magic {self.magic}",
            }, intent)

        # 7. Symbol info, volume, tick freshness & spread guard
        si = self.mt5.symbol_info(self.symbol)
        vol = float(intent.get("volume") or 0.0)
        vol_ok, vol_msg = validate_volume(vol, si)
        if not vol_ok:
            return self._finish_intent(iid, {
                "intent_id": iid, "ts_utc": utc_str(now),
                "status": "REJECTED", "message": vol_msg,
            }, intent)

        tick = self.mt5.symbol_info_tick(self.symbol)
        self._learn_offset(tick, now)
        if tick is None or float(getattr(tick, "bid", 0) or 0) <= 0 or float(getattr(tick, "ask", 0) or 0) < float(tick.bid):
            return self._finish_intent(iid, {
                "intent_id": iid, "ts_utc": utc_str(now),
                "status": "NOOP", "message": "invalid or missing tick quote",
            }, intent)

        tick_ts = int(getattr(tick, "time", 0) or 0)
        if tick_ts and self.server_offset_s is not None:
            age = now - (tick_ts - self.server_offset_s)
            if age > self.quote_max_age_s:
                return self._finish_intent(iid, {
                    "intent_id": iid, "ts_utc": utc_str(now),
                    "status": "NOOP", "message": f"stale quote ({age:.1f}s > {self.quote_max_age_s:.0f}s)",
                }, intent)

        spread = float(tick.ask) - float(tick.bid)
        if spread > self.max_spread_points:
            return self._finish_intent(iid, {
                "intent_id": iid, "ts_utc": utc_str(now),
                "status": "NOOP", "spread": round(spread, 4),
                "message": f"spread {spread:.2f} > max_spread_points {self.max_spread_points:.2f}",
            }, intent)

        side = str(intent.get("side") or "").upper()
        if side not in ("BUY", "SELL"):
            return self._finish_intent(iid, {
                "intent_id": iid, "ts_utc": utc_str(now),
                "status": "REJECTED", "message": f"invalid side {side!r}",
            }, intent)

        point = float(getattr(si, "point", 0.01) or 0.01)
        atr = float(intent.get("atr") or 0.0)
        price = float(tick.ask if side == "BUY" else tick.bid)
        if atr > 0:
            sl_dist = float(intent.get("sl_dist") or (2.0 * atr))
            tp_dist = float(intent.get("tp_dist") or (4.0 * atr))
            if sl_dist > 0 and spread > self.max_spread_to_1r * sl_dist:
                return self._finish_intent(iid, {
                    "intent_id": iid, "ts_utc": utc_str(now),
                    "status": "NOOP", "spread": round(spread, 4),
                    "message": f"spread {spread:.2f} > {self.max_spread_to_1r:.0%} of 1R ({sl_dist:.2f})",
                }, intent)
            sl_raw = (price - sl_dist) if side == "BUY" else (price + sl_dist)
            tp_raw = (price + tp_dist) if side == "BUY" else (price - tp_dist)
        else:
            sl_raw = float(intent["sl"])
            tp_raw = float(intent["tp"])

        sl_price = round(sl_raw / point) * point
        tp_price = round(tp_raw / point) * point

        # Stops-level distance check
        stops_pts = int(getattr(si, "trade_stops_level", 0) or 0)
        min_stop_dist = stops_pts * point
        if min_stop_dist > 0:
            ref_close_px = float(tick.bid if side == "BUY" else tick.ask)
            if abs(ref_close_px - sl_price) < min_stop_dist or abs(tp_price - ref_close_px) < min_stop_dist:
                return self._finish_intent(iid, {
                    "intent_id": iid, "ts_utc": utc_str(now),
                    "status": "REJECTED",
                    "message": f"SL/TP closer than broker trade_stops_level ({stops_pts} pts)",
                }, intent)

        filling = select_filling_mode(si, self.mt5)
        order_type = getattr(self.mt5, "ORDER_TYPE_BUY", 0) if side == "BUY" else getattr(self.mt5, "ORDER_TYPE_SELL", 1)
        req = {
            "action": getattr(self.mt5, "TRADE_ACTION_DEAL", 1),
            "symbol": self.symbol,
            "volume": vol,
            "type": order_type,
            "price": price,
            "sl": sl_price,
            "tp": tp_price,
            "deviation": self.deviation_points,
            "magic": self.magic,
            "comment": str(intent.get("comment") or f"Nasdaq Live {side}")[:31],
            "type_time": getattr(self.mt5, "ORDER_TIME_GTC", 0),
            "type_filling": filling,
        }

        order_check_fn = getattr(self.mt5, "order_check", None)
        if callable(order_check_fn):
            chk = order_check_fn(req)
            if chk is not None and int(getattr(chk, "retcode", 0) or 0) not in (0, getattr(self.mt5, "TRADE_RETCODE_DONE", 10009)):
                return self._finish_intent(iid, {
                    "intent_id": iid, "ts_utc": utc_str(now),
                    "status": "REJECTED",
                    "retcode": int(getattr(chk, "retcode", -1)),
                    "message": f"order_check failed: {getattr(chk, 'comment', '')}",
                }, intent)

        # Persist SENDING before calling order_send (crash safety)
        self.state["results"][iid] = {"intent_id": iid, "status": "SENDING", "ts_utc": utc_str(now)}
        self._save_state()

        res = self.mt5.order_send(req)
        if res is None:
            # Reconcile immediately once; if still not visible, quarantine rather than retry
            after_pos = self._magic_positions()
            if after_pos:
                pid = int(getattr(after_pos[0], "ticket", 0) or 0)
                out = {
                    "intent_id": iid, "ts_utc": utc_str(now),
                    "status": "FILLED",
                    "retcode": getattr(self.mt5, "TRADE_RETCODE_DONE", 10009),
                    "order": pid, "deal": pid, "position_id": pid,
                    "side": side, "volume": vol,
                    "fill_price": float(getattr(after_pos[0], "price_open", price) or price),
                    "sl": sl_price, "tp": tp_price, "spread": round(spread, 4),
                    "message": "order_send returned None; reconciled open position",
                }
                return self._finish_intent(iid, out, intent)

            self.state["unknown_intent"] = {"intent_id": iid, "side": side, "volume": vol, "ts_utc": utc_str(now)}
            self._save_state()
            return self._finish_intent(iid, {
                "intent_id": iid, "ts_utc": utc_str(now),
                "status": "UNKNOWN",
                "message": "order_send returned None; quarantined pending position reconciliation",
            }, intent)

        done_code = getattr(self.mt5, "TRADE_RETCODE_DONE", 10009)
        retcode = int(getattr(res, "retcode", -1))
        if retcode != done_code:
            return self._finish_intent(iid, {
                "intent_id": iid, "ts_utc": utc_str(now),
                "status": "REJECTED",
                "retcode": retcode,
                "message": f"order_send rejected ({retcode}): {getattr(res, 'comment', '')}",
            }, intent)

        order_id = int(getattr(res, "order", 0) or 0)
        deal_id = int(getattr(res, "deal", 0) or 0)
        pos_id = order_id
        after_pos = self._magic_positions()
        if after_pos:
            pos_id = int(getattr(after_pos[-1], "ticket", order_id) or order_id)
            fill_px = float(getattr(after_pos[-1], "price_open", 0.0) or getattr(res, "price", 0.0) or price)
        else:
            fill_px = float(getattr(res, "price", 0.0) or price)

        out = {
            "intent_id": iid,
            "ts_utc": utc_str(now),
            "status": "FILLED",
            "retcode": retcode,
            "order": order_id,
            "deal": deal_id,
            "position_id": pos_id,
            "side": side,
            "volume": vol,
            "fill_price": fill_px,
            "sl": sl_price,
            "tp": tp_price,
            "spread": round(spread, 4),
            "message": str(getattr(res, "comment", "done")),
        }
        return self._finish_intent(iid, out, intent)

    def step(self, now: float = None) -> dict:
        now = self.clock() if now is None else float(now)
        if self.enabled and self.flatten_on_halt and self.halt_file and os.path.exists(self.halt_file):
            if self._magic_positions():
                self.flatten_all(now, reason="HALT")
        res = self.process_intent(now)
        snap = self.publish_positions(now)
        return {"result": res, "positions": snap}

    def run_forever(self) -> None:
        self.log(f"mt5_executor: watching {self.bridge_dir} | symbol={self.symbol} magic={self.magic} "
                 f"enabled={self.enabled} allow_real={self.allow_real}")
        while True:
            try:
                self.step()
            except KeyboardInterrupt:
                break
            except Exception as exc:
                self.log(f"mt5_executor: error in step: {exc}")
            self.sleep(self.poll_s)


def from_env(mt5_mod=None, **overrides) -> Mt5Executor:
    def _b(name, default="0"):
        return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")

    kw = dict(
        mt5_mod=mt5 if mt5_mod is None else mt5_mod,
        bridge_dir=os.environ.get("MT5_ORDER_DIR", DEFAULT_BRIDGE_DIR),
        symbol=os.environ.get("MT5_EXEC_SYMBOL", os.environ.get("SYMBOL_MT5", "US100Cash")),
        magic=int(os.environ.get("MT5_EXEC_MAGIC", os.environ.get("MAGIC_NUMBER", "987656"))),
        enabled=_b("MT5_EXEC_ENABLED", "0"),
        allow_real=_b("MT5_EXEC_ALLOW_REAL", "0"),
        halt_file=os.environ.get("MT5_EXEC_HALT_FILE", DEFAULT_HALT_FILE),
        flatten_on_halt=_b("MT5_EXEC_FLATTEN_ON_HALT", "1"),
        max_spread_points=float(os.environ.get("MT5_EXEC_MAX_SPREAD_POINTS", "8.0")),
        max_spread_to_1r=float(os.environ.get("MT5_EXEC_MAX_SPREAD_TO_1R", "0.35")),
        intent_max_age_s=float(os.environ.get("MT5_EXEC_INTENT_MAX_AGE_S", "90.0")),
        quote_max_age_s=float(os.environ.get("MT5_EXEC_QUOTE_MAX_AGE_S", "30.0")),
        deviation_points=int(os.environ.get("MT5_EXEC_DEVIATION_POINTS", "500")),
        poll_s=float(os.environ.get("MT5_EXEC_POLL_S", "1.0")),
    )
    kw.update(overrides)
    return Mt5Executor(**kw)


def main(argv=None, mt5_mod=None) -> int:
    ap = argparse.ArgumentParser(description="Wine MT5 order-executor sidecar for US100Cash")
    ap.add_argument("--once", action="store_true", help="process one cycle, write positions.json, and exit")
    ap.add_argument("--status", action="store_true", help="print current broker/bridge snapshot and exit")
    args = ap.parse_args(argv)

    m = mt5 if mt5_mod is None else mt5_mod
    if m is None:
        print("mt5_executor: MetaTrader5 package missing - run under Wine Python:\n"
              "  wine C:/Python312/python.exe Z:/opt/nasdaq/tools/mt5_executor.py", flush=True)
        return 1

    ex = from_env(mt5_mod=m)
    if not m.initialize():
        print(f"mt5_executor: MT5 initialize failed: {m.last_error()}", flush=True)
        return 1
    if not m.symbol_select(ex.symbol, True):
        print(f"mt5_executor: symbol_select({ex.symbol}) failed: {m.last_error()}", flush=True)
        m.shutdown()
        return 1

    try:
        if args.status:
            snap = ex.publish_positions()
            print(json.dumps(snap, indent=2, sort_keys=True))
            return 0
        if args.once:
            out = ex.step()
            print(json.dumps(out["positions"], indent=2, sort_keys=True))
            return 0
        ex.run_forever()
        return 0
    finally:
        m.shutdown()


if __name__ == "__main__":
    sys.exit(main())
