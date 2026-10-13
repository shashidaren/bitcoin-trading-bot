#!/usr/bin/env python3
"""Demo-only Wine sidecar that executes/reconciles Linux-engine order intents.

The Linux engine cannot import the MetaTrader5 package.  This worker runs with
Wine Python in the same prefix as the MT5 terminal, reads atomic JSON intents
from `inbox/`, and publishes durable result JSON files in `outbox/`.

Safety properties:
  * OFF by default; the only permitted account kind is an MT5 DEMO account.
  * The configured starting equity must match the demo account on first start;
    the baseline and risk policy are persisted and must not silently change.
  * A manual halt file, a $30 drawdown, 3 daily SL closes, or -$10 daily net P/L
    blocks new orders.  A drawdown/orphan kill remains latched in state.json.
  * Quote freshness, ATR, a $60 hard spread cap AND a 70%-of-1R spread cap are
    checked before every entry. `order_check` precedes `order_send`.
  * The symbol's filling flags are decoded (SYMBOL_FILLING_* bitmask), not
    confused with ORDER_FILLING_* enum values.
  * State is durably marked SENDING before `order_send`. A None/timeout/unknown
    response is never retried automatically; the intent remains quarantined as
    UNKNOWN until broker state/history resolves it or an operator reconciles it.
  * Positions are reconciled by position id. Close deals use the position filter
    and net P/L sums profit + commission + swap + fee.

This is a Stage A component only.  It is not wired into engine.py, the LIVE path
is still unavailable on Linux, and it must not be used with a real account.
See docs/MT5-ORDER-EXECUTOR.md before installation or configuration.
"""
import json
import math
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

try:
    from mt5_order_protocol import (DEFAULT_ROOT, SCHEMA_VERSION,
                                    atomic_write_json, read_json, utc_iso)
except ImportError:  # imported as tools.mt5_order_executor from a repository root
    from tools.mt5_order_protocol import (DEFAULT_ROOT, SCHEMA_VERSION,
                                          atomic_write_json, read_json, utc_iso)

_INTENT_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_MAX_INTENT_BYTES = 16 * 1024
_ACTIVE_STATES = {"SENDING", "UNKNOWN", "OPEN"}
_FINAL_STATES = {"REJECTED", "CLOSED"}


class SafetyError(RuntimeError):
    """An operator/configuration state that must fail closed."""


class IntentError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def _finite_positive(value, name):
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("%s must be numeric" % name)
    if not math.isfinite(result) or result <= 0:
        raise ValueError("%s must be finite and positive" % name)
    return result


def _optional_float(obj, name, default=0.0):
    try:
        value = float(getattr(obj, name, default) or 0.0)
        return value if math.isfinite(value) else default
    except (TypeError, ValueError, OverflowError):
        return default


def _utc_now():
    return datetime.now(timezone.utc)


def _safe_text(value, limit=160):
    """Keep broker-supplied comments bounded and single-line in local results."""
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    return text[:limit]


@dataclass
class ExecutorConfig:
    root: str = DEFAULT_ROOT
    enabled: bool = False
    account_kind: str = "disabled"
    starting_equity: float = None
    symbol: str = "BTCUSD"
    magic: int = 987655
    volume: float = 0.01
    halt_file: str = "/opt/bitcoin/MT5_ORDER_HALT"
    poll_seconds: float = 1.0
    max_spread_usd: float = 60.0
    max_spread_to_1r: float = 0.70
    quote_max_age_seconds: float = 60.0
    intent_max_age_seconds: float = 120.0
    max_daily_stop_losses: int = 3
    max_daily_loss_usd: float = 10.0
    max_drawdown_usd: float = 30.0
    baseline_tolerance_usd: float = 1.0
    sl_atr_multiplier: float = 2.0
    tp_atr_multiplier: float = 4.0
    deviation_points: int = 50
    min_atr_percent: float = 0.0001
    max_atr_percent: float = 0.0060

    def __post_init__(self):
        self.root = os.path.abspath(str(self.root))
        self.account_kind = str(self.account_kind or "").strip().lower()
        self.symbol = str(self.symbol or "").strip()
        if not self.symbol:
            raise ValueError("symbol must not be empty")
        if self.starting_equity is not None:
            self.starting_equity = _finite_positive(self.starting_equity, "starting_equity")
        self.volume = _finite_positive(self.volume, "volume")
        self.poll_seconds = _finite_positive(self.poll_seconds, "poll_seconds")
        self.max_spread_usd = _finite_positive(self.max_spread_usd, "max_spread_usd")
        self.max_spread_to_1r = _finite_positive(self.max_spread_to_1r, "max_spread_to_1r")
        self.quote_max_age_seconds = _finite_positive(self.quote_max_age_seconds, "quote_max_age_seconds")
        self.intent_max_age_seconds = _finite_positive(self.intent_max_age_seconds, "intent_max_age_seconds")
        self.max_daily_loss_usd = _finite_positive(self.max_daily_loss_usd, "max_daily_loss_usd")
        self.max_drawdown_usd = _finite_positive(self.max_drawdown_usd, "max_drawdown_usd")
        self.baseline_tolerance_usd = _finite_positive(self.baseline_tolerance_usd, "baseline_tolerance_usd")
        self.sl_atr_multiplier = _finite_positive(self.sl_atr_multiplier, "sl_atr_multiplier")
        self.tp_atr_multiplier = _finite_positive(self.tp_atr_multiplier, "tp_atr_multiplier")
        if self.max_daily_stop_losses < 1:
            raise ValueError("max_daily_stop_losses must be >= 1")
        if self.magic <= 0:
            raise ValueError("magic must be positive")
        if self.deviation_points < 0:
            raise ValueError("deviation_points must be >= 0")
        if not (0 < self.min_atr_percent < self.max_atr_percent):
            raise ValueError("ATR percentage bounds are invalid")

    @classmethod
    def from_env(cls):
        def get_float(name, default):
            raw = os.environ.get(name)
            return default if raw is None or raw.strip() == "" else float(raw)

        def get_int(name, default):
            raw = os.environ.get(name)
            return default if raw is None or raw.strip() == "" else int(raw)

        return cls(
            root=os.environ.get("MT5_ORDER_DIR", DEFAULT_ROOT),
            enabled=os.environ.get("MT5_ORDER_ENABLED", "0").strip().lower() in ("1", "true", "yes"),
            account_kind=os.environ.get("MT5_ORDER_ACCOUNT_KIND", "disabled"),
            starting_equity=get_float("MT5_ORDER_STARTING_EQUITY", None),
            symbol=os.environ.get("MT5_ORDER_SYMBOL", "BTCUSD"),
            magic=get_int("MT5_ORDER_MAGIC", 987655),
            volume=get_float("MT5_ORDER_VOLUME", 0.01),
            halt_file=os.environ.get("MT5_ORDER_HALT_FILE", "/opt/bitcoin/MT5_ORDER_HALT"),
            poll_seconds=get_float("MT5_ORDER_POLL_SECONDS", 1.0),
            max_spread_usd=get_float("MT5_ORDER_MAX_SPREAD_USD", 60.0),
            max_spread_to_1r=get_float("MT5_ORDER_MAX_SPREAD_TO_1R", 0.70),
            quote_max_age_seconds=get_float("MT5_ORDER_QUOTE_MAX_AGE_SECONDS", 60.0),
            intent_max_age_seconds=get_float("MT5_ORDER_INTENT_MAX_AGE_SECONDS", 120.0),
            max_daily_stop_losses=get_int("MT5_ORDER_MAX_DAILY_SL", 3),
            max_daily_loss_usd=get_float("MT5_ORDER_MAX_DAILY_LOSS_USD", 10.0),
            max_drawdown_usd=get_float("MT5_ORDER_MAX_DRAWDOWN_USD", 30.0),
            baseline_tolerance_usd=get_float("MT5_ORDER_BASELINE_TOLERANCE_USD", 1.0),
            sl_atr_multiplier=get_float("MT5_ORDER_SL_ATR_MULTIPLIER", 2.0),
            tp_atr_multiplier=get_float("MT5_ORDER_TP_ATR_MULTIPLIER", 4.0),
            deviation_points=get_int("MT5_ORDER_DEVIATION_POINTS", 50),
            min_atr_percent=get_float("MT5_ORDER_MIN_ATR_PERCENT", 0.0001),
            max_atr_percent=get_float("MT5_ORDER_MAX_ATR_PERCENT", 0.0060),
        )

    @property
    def inbox(self):
        return os.path.join(self.root, "inbox")

    @property
    def outbox(self):
        return os.path.join(self.root, "outbox")

    @property
    def archive(self):
        return os.path.join(self.root, "processed")

    @property
    def quarantine(self):
        return os.path.join(self.root, "quarantine")

    @property
    def state_path(self):
        return os.path.join(self.root, "state.json")


class MT5OrderExecutor:
    """File-queue worker. Pass an MT5-like module to test safely with a fake."""

    def __init__(self, mt5, config=None, clock=None, logger=None):
        self.mt5 = mt5
        self.config = config or ExecutorConfig.from_env()
        self.clock = clock or _utc_now
        self.logger = logger or (lambda message: print("mt5_order_executor: " + str(message), flush=True))
        self.connected = False
        self._state_error = None
        self.state = self._load_state()
        for directory in (self.config.inbox, self.config.outbox, self.config.archive,
                          self.config.quarantine):
            os.makedirs(directory, exist_ok=True)

    def _new_state(self):
        return {
            "schema_version": SCHEMA_VERSION,
            "baseline_equity": None,
            "risk_policy": None,
            "halted_reason": None,
            "halted_at": None,
            "intents": {},
            "orphan_positions": {},
        }

    def _load_state(self):
        if not os.path.isfile(self.config.state_path):
            return self._new_state()
        try:
            state = read_json(self.config.state_path)
            if not isinstance(state, dict) or state.get("schema_version") != SCHEMA_VERSION:
                raise ValueError("unsupported state schema")
            if not isinstance(state.get("intents"), dict):
                raise ValueError("invalid intents state")
            if not isinstance(state.get("orphan_positions", {}), dict):
                raise ValueError("invalid orphan position state")
            state.setdefault("baseline_equity", None)
            state.setdefault("risk_policy", None)
            state.setdefault("halted_reason", None)
            state.setdefault("halted_at", None)
            state.setdefault("orphan_positions", {})
            return state
        except Exception as exc:
            self._state_error = "state file unreadable or invalid (%s)" % type(exc).__name__
            return self._new_state()

    def _save_state(self):
        if self._state_error:
            raise SafetyError(self._state_error)
        atomic_write_json(self.config.state_path, self.state)

    def _now(self):
        now = self.clock()
        if now.tzinfo is None:
            raise SafetyError("local clock must return timezone-aware UTC")
        return now.astimezone(timezone.utc)

    def _risk_policy(self):
        return {
            "max_drawdown_usd": round(self.config.max_drawdown_usd, 4),
            "max_daily_loss_usd": round(self.config.max_daily_loss_usd, 4),
            "max_daily_stop_losses": int(self.config.max_daily_stop_losses),
            "max_spread_usd": round(self.config.max_spread_usd, 4),
            "max_spread_to_1r": round(self.config.max_spread_to_1r, 4),
            "quote_max_age_seconds": round(self.config.quote_max_age_seconds, 4),
            "intent_max_age_seconds": round(self.config.intent_max_age_seconds, 4),
            "min_atr_percent": round(self.config.min_atr_percent, 8),
            "max_atr_percent": round(self.config.max_atr_percent, 8),
            "deviation_points": int(self.config.deviation_points),
            "halt_file": os.path.abspath(self.config.halt_file),
            "sl_atr_multiplier": round(self.config.sl_atr_multiplier, 4),
            "tp_atr_multiplier": round(self.config.tp_atr_multiplier, 4),
            "symbol": self.config.symbol,
            "magic": int(self.config.magic),
            "volume": round(self.config.volume, 8),
        }

    def connect(self):
        """Connect only if explicitly armed for the configured demo account."""
        if self._state_error:
            self.logger("REFUSED: " + self._state_error)
            return False
        if not self.config.enabled:
            self.logger("disabled by MT5_ORDER_ENABLED; no terminal or order API called")
            return False
        if self.config.account_kind != "demo":
            self.logger("REFUSED: MT5_ORDER_ACCOUNT_KIND must be exactly 'demo'")
            return False
        if self.config.starting_equity is None:
            self.logger("REFUSED: MT5_ORDER_STARTING_EQUITY must be set explicitly")
            return False
        if not self.mt5.initialize():
            self.logger("MT5 initialize failed: " + _safe_text(self.mt5.last_error()))
            return False
        self.connected = True
        try:
            account = self.mt5.account_info()
            terminal = self.mt5.terminal_info()
            if account is None or terminal is None:
                raise SafetyError("account or terminal info unavailable")
            demo_code = getattr(self.mt5, "ACCOUNT_TRADE_MODE_DEMO", None)
            if demo_code is None or getattr(account, "trade_mode", None) != demo_code:
                raise SafetyError("connected terminal is not on an MT5 demo account")

            current_equity = _optional_float(account, "equity", float("nan"))
            if not math.isfinite(current_equity) or current_equity <= 0:
                raise SafetyError("account equity is unavailable or invalid")
            expected_policy = self._risk_policy()
            baseline = self.state.get("baseline_equity")
            stored_policy = self.state.get("risk_policy")
            if baseline is None:
                if abs(current_equity - self.config.starting_equity) > self.config.baseline_tolerance_usd:
                    raise SafetyError("current demo equity does not match the configured starting-equity baseline")
                self.state["baseline_equity"] = round(self.config.starting_equity, 2)
                self.state["risk_policy"] = expected_policy
                self._save_state()
            else:
                try:
                    baseline = float(baseline)
                except (TypeError, ValueError):
                    raise SafetyError("persisted baseline equity is invalid")
                if abs(baseline - self.config.starting_equity) > 0.01:
                    raise SafetyError("configured starting-equity baseline differs from persisted state")
                if stored_policy != expected_policy:
                    raise SafetyError("risk policy differs from persisted state; manual reconciliation required")

            if current_equity <= self.config.starting_equity - self.config.max_drawdown_usd:
                self._latch_halt("MAX_DRAWDOWN", "account equity is at/below the configured drawdown floor")
            self.logger("connected; account verified as DEMO (account identifiers are not logged)")
            return True
        except Exception as exc:
            self.logger("REFUSED: " + _safe_text(exc))
            try:
                self.mt5.shutdown()
            except Exception:
                pass
            self.connected = False
            return False

    def shutdown(self):
        if self.connected:
            try:
                self.mt5.shutdown()
            finally:
                self.connected = False

    def _latch_halt(self, code, message):
        if not self.state.get("halted_reason"):
            self.state["halted_reason"] = str(code)
            self.state["halted_at"] = utc_iso(self._now())
            self.state["halt_message"] = _safe_text(message)
            self._save_state()
            self.logger("KILL SWITCH LATCHED: %s (%s)" % (code, _safe_text(message)))

    def _result_for(self, record):
        intent = record.get("intent") or {}
        result = {
            "schema_version": SCHEMA_VERSION,
            "intent_id": record.get("intent_id"),
            "action": "OPEN",
            "status": record.get("status"),
            "reason_code": record.get("reason_code"),
            "message": _safe_text(record.get("message"), 240),
            "created_at": intent.get("created_at"),
            "updated_at": record.get("updated_at"),
            "symbol": record.get("symbol") or intent.get("symbol"),
            "direction": record.get("direction") or intent.get("direction"),
            "volume": record.get("volume") or intent.get("volume"),
            "atr": record.get("atr") or intent.get("atr"),
        }
        fields = (
            "order_ticket", "deal_ticket", "position_id", "entry_price", "stop_loss",
            "take_profit", "exit_price", "exit_reason", "gross_profit", "commission",
            "swap", "fee", "net_profit", "spread_usd", "quote_age_seconds",
            "comment_tag", "signal_ts", "filled_at_utc", "closed_at_utc",
        )
        for field in fields:
            if field in record:
                result[field] = record[field]
        return result

    def _publish(self, record):
        intent_id = record.get("intent_id")
        if not intent_id or not _INTENT_ID_RE.fullmatch(str(intent_id)):
            self._save_state()
            return
        path = os.path.join(self.config.outbox, str(intent_id) + ".json")
        current = self._result_for(record)
        try:
            if os.path.isfile(path) and read_json(path) == current:
                return  # steady OPEN/UNKNOWN poll: avoid rewriting files every second
        except Exception:
            pass
        record["updated_at"] = utc_iso(self._now())
        self._save_state()
        atomic_write_json(path, self._result_for(record))

    def _set_status(self, record, status, reason_code=None, message=None, **fields):
        record["status"] = status
        record["reason_code"] = reason_code
        record["message"] = _safe_text(message, 240)
        record.update(fields)
        self._publish(record)

    def _quarantine(self, path, suffix="bad"):
        try:
            os.makedirs(self.config.quarantine, exist_ok=True)
            stamp = self._now().strftime("%Y%m%dT%H%M%SZ")
            target = os.path.join(self.config.quarantine,
                                  os.path.basename(path) + "." + stamp + "." + suffix)
            os.replace(path, target)
        except OSError as exc:
            self.logger("could not quarantine malformed intent (%s)" % type(exc).__name__)

    def _archive(self, path, intent_id):
        if not os.path.isfile(path):
            return
        try:
            os.makedirs(self.config.archive, exist_ok=True)
            target = os.path.join(self.config.archive, intent_id + ".json")
            if os.path.exists(target):
                os.unlink(path)
            else:
                os.replace(path, target)
        except OSError as exc:
            self.logger("could not archive processed intent (%s)" % type(exc).__name__)

    def _validate_intent(self, payload):
        if not isinstance(payload, dict):
            raise IntentError("BAD_SCHEMA", "intent must be a JSON object")
        if payload.get("schema_version") != SCHEMA_VERSION:
            raise IntentError("BAD_SCHEMA", "unsupported schema_version")
        if payload.get("action") != "OPEN":
            raise IntentError("BAD_ACTION", "only OPEN intents are supported")
        direction = str(payload.get("direction", "")).strip().upper()
        if direction not in ("BUY", "SELL"):
            raise IntentError("BAD_DIRECTION", "direction must be BUY or SELL")
        if payload.get("symbol") != self.config.symbol:
            raise IntentError("BAD_SYMBOL", "intent symbol does not match the configured instrument")
        try:
            volume = _finite_positive(payload.get("volume"), "volume")
            atr = _finite_positive(payload.get("atr"), "atr")
        except ValueError as exc:
            raise IntentError("BAD_SIZE_OR_ATR", str(exc))
        if abs(volume - self.config.volume) > 1e-8:
            raise IntentError("BAD_VOLUME", "intent volume must equal the configured fixed lot")
        raw_created = payload.get("created_at")
        if not isinstance(raw_created, str) or not raw_created.strip():
            raise IntentError("BAD_TIMESTAMP", "created_at must be an ISO-8601 UTC timestamp")
        try:
            created = datetime.fromisoformat(raw_created.strip().replace("Z", "+00:00"))
            if created.tzinfo is None:
                raise ValueError("timezone missing")
            created = created.astimezone(timezone.utc)
        except Exception:
            raise IntentError("BAD_TIMESTAMP", "created_at must be an ISO-8601 UTC timestamp")
        age = (self._now() - created).total_seconds()
        if age < -30:
            raise IntentError("FUTURE_INTENT", "created_at is too far in the future")
        if age > self.config.intent_max_age_seconds:
            raise IntentError("STALE_INTENT", "intent exceeded the maximum queue age")
        signal_ts = payload.get("signal_ts")
        if signal_ts is not None and (not isinstance(signal_ts, str) or len(signal_ts) > 64):
            raise IntentError("BAD_SIGNAL_TIMESTAMP", "signal_ts must be a short string or null")
        return {
            "intent_id": payload["intent_id"],
            "symbol": self.config.symbol,
            "direction": direction,
            "volume": volume,
            "atr": atr,
            "created_at": raw_created,
            "signal_ts": signal_ts,
        }

    def _monitor_equity_kill(self):
        """Latch account-mode/drawdown changes even when no new signal arrives."""
        try:
            account = self.mt5.account_info()
        except Exception:
            account = None
        if account is None:
            return
        demo_code = getattr(self.mt5, "ACCOUNT_TRADE_MODE_DEMO", None)
        if demo_code is None or getattr(account, "trade_mode", None) != demo_code:
            self._latch_halt("ACCOUNT_MODE_CHANGED", "connected account is no longer DEMO")
            return
        equity = _optional_float(account, "equity", float("nan"))
        if math.isfinite(equity) and equity <= self.config.starting_equity - self.config.max_drawdown_usd:
            self._latch_halt("MAX_DRAWDOWN", "account equity is at/below the configured drawdown floor")

    def poll_once(self):
        """Reconcile broker state, then consume queued intents once."""
        if not self.connected:
            raise SafetyError("executor is not connected")
        self._monitor_equity_kill()
        if not self._reconcile():
            # An unreadable broker position set is not equivalent to flat.
            self.logger("position query unavailable; leaving queued intents untouched")
            return False
        for name in sorted(os.listdir(self.config.inbox)):
            if not name.endswith(".json") or name.startswith("."):
                continue
            path = os.path.join(self.config.inbox, name)
            self._process_file(path)
        self._reconcile()
        return True

    def _process_file(self, path):
        stem = os.path.basename(path)[:-5]
        if not _INTENT_ID_RE.fullmatch(stem):
            self._quarantine(path, "bad-id")
            return
        try:
            if os.path.getsize(path) > _MAX_INTENT_BYTES:
                self._quarantine(path, "oversize")
                return
            payload = read_json(path)
        except Exception as exc:
            self.logger("invalid intent file quarantined (%s)" % type(exc).__name__)
            self._quarantine(path, "bad-json")
            return
        if not isinstance(payload, dict) or payload.get("intent_id") != stem:
            self._quarantine(path, "id-mismatch")
            return

        record = self.state["intents"].get(stem)
        if record is not None:
            if record.get("status") != "RECEIVED":
                # The durable SENDING marker is the idempotency barrier. Never
                # resend an id that has crossed it, even around a worker crash.
                self._publish(record)
                self._archive(path, stem)
                return
            if record.get("intent") != payload:
                self._quarantine(path, "intent-id-reuse")
                return
            # RECEIVED is written before validation/order_check. Those operations
            # are read-only, so an interrupted RECEIVED intent is safe to resume.
        else:
            record = {
                "intent_id": stem,
                "intent": payload,
                "status": "RECEIVED",
                "reason_code": None,
                "message": "",
                "created_at_utc": utc_iso(self._now()),
                "comment_tag": "BTC:" + stem[:24],
            }
            self.state["intents"][stem] = record
            self._save_state()
        try:
            normalized = self._validate_intent(payload)
            record.update(normalized)
            self._entry_guard(record)
            request, quote = self._build_request(record)
        except IntentError as exc:
            self._set_status(record, "REJECTED", exc.code, exc.message)
            self._archive(path, stem)
            self.logger("intent %s rejected (%s)" % (stem[:8], exc.code))
            return
        except SafetyError as exc:
            code = getattr(exc, "code", "SAFETY_GUARD")
            self._set_status(record, "REJECTED", code, str(exc))
            self._archive(path, stem)
            self.logger("intent %s rejected (%s)" % (stem[:8], code))
            return
        except Exception as exc:
            # The request has not yet reached order_send, so this is a definite
            # local rejection, not an unknown broker outcome.
            self._set_status(record, "REJECTED", "LOCAL_VALIDATION_ERROR",
                             "local order validation failed (%s)" % type(exc).__name__)
            self._archive(path, stem)
            self.logger("intent %s rejected (local validation error)" % stem[:8])
            return

        record.update({
            "spread_usd": round(quote["spread"], 8),
            "quote_age_seconds": round(quote["age"], 3),
            "requested_price": request["price"],
            "stop_loss": request["sl"],
            "take_profit": request["tp"],
        })
        try:
            checked = self.mt5.order_check(request)
        except Exception as exc:
            checked = None
            check_error = type(exc).__name__
        else:
            check_error = ""
        if checked is None:
            self._set_status(record, "REJECTED", "ORDER_CHECK_FAILED",
                             "order_check returned no result%s" % (" (" + check_error + ")" if check_error else ""))
            self._archive(path, stem)
            return
        check_retcode = getattr(checked, "retcode", None)
        done_code = getattr(self.mt5, "TRADE_RETCODE_DONE", 10009)
        if check_retcode not in (0, done_code):
            self._set_status(record, "REJECTED", "ORDER_CHECK_REJECTED",
                             "order_check retcode %s: %s" %
                             (check_retcode, _safe_text(getattr(checked, "comment", ""))))
            self._archive(path, stem)
            return

        # order_check can take time and a Market Execution request may ignore
        # its quoted price. Re-run gates against the latest quote/positions just
        # before dispatch, rebuilding levels and rechecking if the request moved.
        try:
            self._entry_guard(record)
            final_request, final_quote = self._build_request(record)
        except IntentError as exc:
            self._set_status(record, "REJECTED", exc.code, exc.message)
            self._archive(path, stem)
            return
        except SafetyError as exc:
            self._set_status(record, "REJECTED", getattr(exc, "code", "SAFETY_GUARD"), str(exc))
            self._archive(path, stem)
            return
        except Exception as exc:
            self._set_status(record, "REJECTED", "FINAL_VALIDATION_ERROR",
                             "final pre-send validation failed (%s)" % type(exc).__name__)
            self._archive(path, stem)
            return
        if final_request != request:
            try:
                final_check = self.mt5.order_check(final_request)
            except Exception:
                final_check = None
            if final_check is None or getattr(final_check, "retcode", None) not in (0, done_code):
                self._set_status(record, "REJECTED", "FINAL_ORDER_CHECK_REJECTED",
                                 "refreshed request failed its final order_check")
                self._archive(path, stem)
                return
        request, quote = final_request, final_quote
        record.update({
            "spread_usd": round(quote["spread"], 8),
            "quote_age_seconds": round(quote["age"], 3),
            "requested_price": request["price"],
            "stop_loss": request["sl"],
            "take_profit": request["tp"],
        })

        # Persist before the non-idempotent call. If the worker dies before or
        # after the server receives it, restart reconciliation never resends it.
        record["order_request"] = {
            key: (value if isinstance(value, (str, int, float, bool)) or value is None else str(value))
            for key, value in request.items()
        }
        self._set_status(record, "SENDING", None, "order_send in progress")
        # Explicit second flush documents/enforces the idempotency barrier even
        # if a future result-writer optimization short-circuits an unchanged file.
        self._save_state()
        try:
            result = self.mt5.order_send(request)
        except Exception as exc:
            result = None
            send_error = type(exc).__name__
        else:
            send_error = ""
        if result is None:
            self._set_status(record, "UNKNOWN", "SEND_RESULT_UNKNOWN",
                             "order_send gave no definitive result%s; automatic retry is disabled" %
                             (" (" + send_error + ")" if send_error else ""))
            self._archive(path, stem)
            self._reconcile()
            return

        retcode = getattr(result, "retcode", None)
        order_ticket = int(getattr(result, "order", 0) or 0)
        deal_ticket = int(getattr(result, "deal", 0) or 0)
        record["order_ticket"] = order_ticket or None
        record["deal_ticket"] = deal_ticket or None
        success_codes = {
            done_code,
            getattr(self.mt5, "TRADE_RETCODE_DONE_PARTIAL", 10010),
        }
        ambiguous_codes = {
            getattr(self.mt5, "TRADE_RETCODE_PLACED", 10008),
            getattr(self.mt5, "TRADE_RETCODE_TIMEOUT", 10012),
            getattr(self.mt5, "TRADE_RETCODE_CONNECTION", 10031),
            getattr(self.mt5, "TRADE_RETCODE_ERROR", 10011),
        }
        if retcode in success_codes:
            self._set_status(record, "UNKNOWN", "AWAITING_RECONCILIATION",
                             "server accepted the request; reconciling the position and fill")
        elif retcode is None or retcode in ambiguous_codes:
            self._set_status(record, "UNKNOWN", "SEND_RESULT_AMBIGUOUS",
                             "retcode %s is ambiguous; automatic retry is disabled" % retcode)
        else:
            self._set_status(record, "REJECTED", "BROKER_REJECTED",
                             "broker retcode %s: %s" %
                             (retcode, _safe_text(getattr(result, "comment", ""))))
        self._archive(path, stem)
        self._reconcile()

    def _entry_guard(self, record):
        config = self.config
        if not self.connected or config.account_kind != "demo" or not config.enabled:
            raise SafetyError("executor is not armed for a demo account")
        if self._state_error:
            raise SafetyError(self._state_error)
        if self.state.get("halted_reason"):
            raise SafetyError("latched kill switch: " + str(self.state["halted_reason"]))
        if os.path.exists(config.halt_file):
            raise SafetyError("manual halt file exists")
        if self.state.get("orphan_positions"):
            open_orphans = [v for v in self.state["orphan_positions"].values()
                            if v.get("status") != "CLOSED_UNRECONCILED"]
            if open_orphans:
                raise SafetyError("an untracked broker position is present")

        active = [r for r in self.state["intents"].values()
                  if r.get("intent_id") != record.get("intent_id")
                  and r.get("status") in _ACTIVE_STATES]
        if active:
            raise SafetyError("another broker order is open or unresolved")

        terminal = self.mt5.terminal_info()
        account = self.mt5.account_info()
        if terminal is None or account is None:
            raise SafetyError("terminal/account status unavailable")
        if getattr(terminal, "connected", True) is False:
            raise SafetyError("MT5 terminal is disconnected")
        if getattr(terminal, "trade_allowed", False) is not True:
            raise SafetyError("MT5 terminal auto-trading is disabled")
        if getattr(account, "trade_allowed", False) is not True:
            raise SafetyError("account trading is disabled")
        demo_code = getattr(self.mt5, "ACCOUNT_TRADE_MODE_DEMO", None)
        if demo_code is None or getattr(account, "trade_mode", None) != demo_code:
            raise SafetyError("account is no longer verified as DEMO")
        equity = _optional_float(account, "equity", float("nan"))
        if not math.isfinite(equity):
            raise SafetyError("account equity unavailable")
        if equity <= config.starting_equity - config.max_drawdown_usd:
            self._latch_halt("MAX_DRAWDOWN", "account equity is at/below the configured drawdown floor")
            raise SafetyError("equity drawdown floor reached")

        daily_ok, daily_code, daily_message = self._daily_risk()
        if not daily_ok:
            raise _CodedSafetyError(daily_code, daily_message)

        try:
            selected = self.mt5.symbol_select(config.symbol, True)
        except Exception:
            selected = False
        if not selected:
            raise SafetyError("symbol_select failed for configured symbol")
        symbol_info = self.mt5.symbol_info(config.symbol)
        if symbol_info is None:
            raise SafetyError("symbol contract specification unavailable")
        disabled = getattr(self.mt5, "SYMBOL_TRADE_MODE_DISABLED", 0)
        if getattr(symbol_info, "trade_mode", None) == disabled:
            raise SafetyError("broker reports trading disabled for the configured symbol")
        min_volume = _optional_float(symbol_info, "volume_min", float("nan"))
        max_volume = _optional_float(symbol_info, "volume_max", float("nan"))
        volume_step = _optional_float(symbol_info, "volume_step", float("nan"))
        if not all(math.isfinite(v) and v > 0 for v in (min_volume, max_volume, volume_step)):
            raise SafetyError("symbol volume limits/step unavailable")
        volume = record["volume"]
        steps = (volume - min_volume) / volume_step
        if volume < min_volume - 1e-9 or volume > max_volume + 1e-9 or abs(steps - round(steps)) > 1e-7:
            raise SafetyError("configured lot does not match the symbol's min/max/step")

        positions = self._get_positions()
        if positions is None:
            raise SafetyError("positions_get failed; broker exposure is unknown")
        ours = [p for p in positions if int(getattr(p, "magic", 0) or 0) == config.magic]
        if ours:
            raise SafetyError("a position with this bot's magic number is already open")
        try:
            pending_orders = self.mt5.orders_get()
        except Exception:
            pending_orders = None
        if pending_orders is None:
            raise SafetyError("orders_get failed; pending broker exposure is unknown")
        if any(int(getattr(order, "magic", 0) or 0) == config.magic for order in pending_orders):
            self._latch_halt("ORPHAN_ORDER", "untracked pending order with this bot's magic was found")
            raise SafetyError("a pending order with this bot's magic number exists")

    def _daily_risk(self):
        now = self._now()
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        try:
            tick = self.mt5.symbol_info_tick(self.config.symbol)
        except Exception:
            tick = None
        if tick is None:
            return False, "QUOTE_UNAVAILABLE", "cannot normalize broker deal times without a tick"
        _tick_utc, quote_age, server_offset = self._tick_utc_age_offset(tick)
        if server_offset is None or quote_age > self.config.quote_max_age_seconds:
            return False, "QUOTE_STALE", "fresh broker-server offset unavailable for daily risk check"
        # Pull a wide range because MT5 brokers may encode deal timestamps in
        # server time. The server offset is then applied below and only UTC-day
        # deals are counted; a boundary deal cannot silently fall outside the
        # history query due to XM's UTC+2/+3 clock.
        try:
            deals = self.mt5.history_deals_get(start - timedelta(hours=14), now + timedelta(hours=14))
        except Exception:
            deals = None
        if deals is None:
            return False, "DAILY_HISTORY_UNAVAILABLE", "daily deal history unavailable; fail closed"
        magic = self.config.magic
        net = 0.0
        sl_positions = set()
        close_entries = {
            getattr(self.mt5, "DEAL_ENTRY_OUT", 1),
            getattr(self.mt5, "DEAL_ENTRY_OUT_BY", 3),
            getattr(self.mt5, "DEAL_ENTRY_INOUT", 2),
        }
        sl_reason = getattr(self.mt5, "DEAL_REASON_SL", 4)
        now_epoch = now.timestamp()
        start_epoch = start.timestamp()
        for deal in deals:
            if int(getattr(deal, "magic", 0) or 0) != magic:
                continue
            if getattr(deal, "symbol", self.config.symbol) != self.config.symbol:
                continue
            raw_time = _optional_float(deal, "time_msc", 0.0) / 1000.0
            if raw_time <= 0:
                raw_time = _optional_float(deal, "time", 0.0)
            if raw_time <= 0:
                return False, "DAILY_HISTORY_UNAVAILABLE", "a bot deal has no usable timestamp"
            deal_utc = raw_time - server_offset
            if not (start_epoch <= deal_utc <= now_epoch + 5):
                continue
            net += sum(_optional_float(deal, name, 0.0)
                       for name in ("profit", "commission", "swap", "fee"))
            if (getattr(deal, "entry", None) in close_entries
                    and getattr(deal, "reason", None) == sl_reason):
                sl_positions.add(int(getattr(deal, "position_id", 0) or getattr(deal, "ticket", 0) or 0))
        sl_positions.discard(0)
        if len(sl_positions) >= self.config.max_daily_stop_losses:
            return False, "DAILY_SL_LIMIT", "%d stop-loss closes today" % len(sl_positions)
        if net <= -self.config.max_daily_loss_usd:
            return False, "DAILY_LOSS_LIMIT", "realized net P/L today is at/below the configured loss floor"
        return True, "", ""

    def _tick_utc_age_offset(self, tick):
        raw = _optional_float(tick, "time_msc", 0.0) / 1000.0
        if raw <= 0:
            raw = _optional_float(tick, "time", 0.0)
        if raw <= 0:
            return None, float("inf"), None
        now_epoch = self._now().timestamp()
        delta = raw - now_epoch
        offset = int(round(delta / 3600.0) * 3600)
        if abs(offset) > 14 * 3600 or abs(delta - offset) > 300:
            return None, float("inf"), None
        tick_epoch_utc = raw - offset
        age = now_epoch - tick_epoch_utc
        if age < -5:
            return None, age, None
        return tick_epoch_utc, max(0.0, age), offset

    def _tick_utc_and_age(self, tick):
        tick_utc, age, _offset = self._tick_utc_age_offset(tick)
        return tick_utc, age

    def _normalize_price(self, value, symbol_info):
        point = _optional_float(symbol_info, "point", 0.0)
        tick_size = _optional_float(symbol_info, "trade_tick_size", point)
        if tick_size <= 0:
            tick_size = point
        if tick_size <= 0:
            raise SafetyError("symbol point/tick size unavailable")
        digits = int(getattr(symbol_info, "digits", 2))
        return round(round(float(value) / tick_size) * tick_size, digits)

    def _choose_filling_mode(self, symbol_info):
        raw = int(getattr(symbol_info, "filling_mode", -1))
        execution = int(getattr(symbol_info, "trade_exemode", -1))
        market = getattr(self.mt5, "SYMBOL_TRADE_EXECUTION_MARKET", 2)
        flag_fok = getattr(self.mt5, "SYMBOL_FILLING_FOK", 1)
        flag_ioc = getattr(self.mt5, "SYMBOL_FILLING_IOC", 2)
        if raw < 0:
            raise SafetyError("symbol filling flags unavailable")
        if raw & flag_fok:
            return getattr(self.mt5, "ORDER_FILLING_FOK", 0)
        if raw & flag_ioc:
            return getattr(self.mt5, "ORDER_FILLING_IOC", 1)
        if execution != market:
            return getattr(self.mt5, "ORDER_FILLING_RETURN", 2)
        raise SafetyError("symbol permits no supported market-order filling mode")

    def _build_request(self, record):
        config = self.config
        info = self.mt5.symbol_info(config.symbol)
        tick = self.mt5.symbol_info_tick(config.symbol)
        if info is None or tick is None:
            raise SafetyError("symbol info or tick unavailable")
        _, age = self._tick_utc_and_age(tick)
        if not math.isfinite(age) or age > config.quote_max_age_seconds:
            raise SafetyError("quote is stale or its server-time offset is unknown")
        bid = _optional_float(tick, "bid", 0.0)
        ask = _optional_float(tick, "ask", 0.0)
        if bid <= 0 or ask <= bid:
            raise SafetyError("quote bid/ask is invalid")
        spread = ask - bid
        entry = ask if record["direction"] == "BUY" else bid
        atr = record["atr"]
        mid = (bid + ask) / 2.0
        atr_pct = atr / mid
        if not (config.min_atr_percent <= atr_pct <= config.max_atr_percent):
            raise IntentError("ATR_OUT_OF_RANGE", "ATR is outside the frozen percentage bounds")
        one_r = atr * config.sl_atr_multiplier
        if spread > config.max_spread_usd:
            raise IntentError("SPREAD_HARD_CAP", "spread exceeds the configured hard USD cap")
        if spread > one_r * config.max_spread_to_1r:
            raise IntentError("SPREAD_TO_1R", "spread exceeds the configured share of 1R")

        point = _optional_float(info, "point", 0.0)
        if point <= 0:
            raise SafetyError("symbol point is unavailable")
        stop_level = _optional_float(info, "trade_stops_level", 0.0)
        minimum_stop_distance = max(0.0, stop_level * point)
        target_distance = one_r * (config.tp_atr_multiplier / config.sl_atr_multiplier)
        if one_r < minimum_stop_distance or target_distance < minimum_stop_distance:
            raise SafetyError("ATR stop/target is inside the broker's minimum stop distance")

        if record["direction"] == "BUY":
            order_type = self.mt5.ORDER_TYPE_BUY
            sl = entry - one_r
            tp = entry + atr * config.tp_atr_multiplier
        else:
            order_type = self.mt5.ORDER_TYPE_SELL
            sl = entry + one_r
            tp = entry - atr * config.tp_atr_multiplier
        sl = self._normalize_price(sl, info)
        tp = self._normalize_price(tp, info)
        request = {
            "action": self.mt5.TRADE_ACTION_DEAL,
            "symbol": config.symbol,
            "volume": config.volume,
            "type": order_type,
            "price": self._normalize_price(entry, info),
            "sl": sl,
            "tp": tp,
            "deviation": int(config.deviation_points),
            "magic": int(config.magic),
            "comment": record["comment_tag"],
            "type_time": self.mt5.ORDER_TIME_GTC,
            "type_filling": self._choose_filling_mode(info),
        }
        return request, {"spread": spread, "age": age}

    def _get_positions(self):
        try:
            positions = self.mt5.positions_get()
        except Exception:
            return None
        if positions is None:
            return None
        return tuple(positions)

    def _position_key(self, position):
        value = getattr(position, "identifier", None)
        if value is None or int(value or 0) == 0:
            value = getattr(position, "ticket", 0)
        return int(value or 0)

    def _position_for_record(self, record, positions):
        key = int(record.get("position_id") or 0)
        tag = record.get("comment_tag")
        order_ticket = int(record.get("order_ticket") or 0)
        for position in positions:
            if int(getattr(position, "magic", 0) or 0) != self.config.magic:
                continue
            if getattr(position, "symbol", None) != self.config.symbol:
                continue
            position_key = self._position_key(position)
            comment = str(getattr(position, "comment", "") or "")
            if (key and position_key == key) or (tag and tag in comment) or (order_ticket and
                    int(getattr(position, "ticket", 0) or 0) == order_ticket):
                return position
        return None

    def _history_by_order(self, order_ticket):
        if not order_ticket:
            return None
        try:
            result = self.mt5.history_deals_get(ticket=int(order_ticket))
        except Exception:
            return None
        return None if result is None else tuple(result)

    def _history_by_position(self, position_id):
        if not position_id:
            return None
        try:
            result = self.mt5.history_deals_get(position=int(position_id))
        except Exception:
            return None
        return None if result is None else tuple(result)

    def _history_by_comment(self, record):
        now = self._now()
        from_time = now - timedelta(days=7)
        try:
            deals = self.mt5.history_deals_get(from_time, now)
        except Exception:
            return None
        if deals is None:
            return None
        tag = record.get("comment_tag", "")
        result = []
        for deal in deals:
            if int(getattr(deal, "magic", 0) or 0) != self.config.magic:
                continue
            if tag and tag in str(getattr(deal, "comment", "") or ""):
                result.append(deal)
        return tuple(result)

    def _entry_deals(self, deals):
        entries = {
            getattr(self.mt5, "DEAL_ENTRY_IN", 0),
            getattr(self.mt5, "DEAL_ENTRY_INOUT", 2),
        }
        return [d for d in (deals or ()) if getattr(d, "entry", None) in entries]

    def _close_deals(self, deals):
        closes = {
            getattr(self.mt5, "DEAL_ENTRY_OUT", 1),
            getattr(self.mt5, "DEAL_ENTRY_OUT_BY", 3),
            getattr(self.mt5, "DEAL_ENTRY_INOUT", 2),
        }
        return [d for d in (deals or ()) if getattr(d, "entry", None) in closes]

    def _weighted_price(self, deals):
        weighted = 0.0
        volume = 0.0
        for deal in deals:
            price = _optional_float(deal, "price", 0.0)
            amount = _optional_float(deal, "volume", 0.0)
            if price > 0 and amount > 0:
                weighted += price * amount
                volume += amount
        return (weighted / volume) if volume > 0 else None

    def _position_deals(self, record, position_id):
        deals = self._history_by_position(position_id)
        if deals is not None:
            return deals
        return self._history_by_order(record.get("order_ticket"))

    def _sync_open(self, record, position, deals=None):
        if deals is None:
            position_id = self._position_key(position)
            deals = self._position_deals(record, position_id)
        entry_deals = self._entry_deals(deals or ())
        entry_price = self._weighted_price(entry_deals)
        if entry_price is None:
            entry_price = _optional_float(position, "price_open", 0.0)
        position_id = self._position_key(position)
        if not position_id:
            self._set_status(record, "UNKNOWN", "POSITION_ID_UNAVAILABLE",
                             "broker position exists but its stable id is unavailable")
            return
        record["position_id"] = position_id
        record["entry_price"] = round(entry_price, int(getattr(self.mt5.symbol_info(self.config.symbol), "digits", 2)))
        record["volume"] = _optional_float(position, "volume", record.get("volume", self.config.volume))
        record["stop_loss"] = _optional_float(position, "sl", record.get("stop_loss", 0.0))
        record["take_profit"] = _optional_float(position, "tp", record.get("take_profit", 0.0))
        if entry_deals:
            record["deal_ticket"] = int(getattr(entry_deals[0], "ticket", 0) or record.get("deal_ticket") or 0) or None
            record["order_ticket"] = int(
                getattr(entry_deals[0], "order", 0) or record.get("order_ticket") or 0
            ) or None
        record["filled_at_utc"] = record.get("filled_at_utc") or utc_iso(self._now())
        if record["direction"] == "BUY":
            protected = 0 < record["stop_loss"] < record["entry_price"] < record["take_profit"]
        else:
            protected = 0 < record["take_profit"] < record["entry_price"] < record["stop_loss"]
        if not protected:
            self._latch_halt("UNPROTECTED_POSITION", "broker position is missing valid server-side SL/TP")
            self._set_status(record, "UNKNOWN", "MISSING_OR_INVALID_STOPS",
                             "position exists but valid server-side SL/TP are not confirmed")
            return
        self._set_status(record, "OPEN", None, "broker position is open and reconciled")

    def _sync_closed(self, record, position_id, deals):
        if deals is None:
            self._set_status(record, "UNKNOWN", "HISTORY_UNAVAILABLE",
                             "broker position is absent but position history is unavailable")
            return
        entries = self._entry_deals(deals)
        closes = self._close_deals(deals)
        if not entries or not closes:
            self._set_status(record, "UNKNOWN", "CLOSE_NOT_CONFIRMED",
                             "no matching entry and exit history; automatic retry is disabled")
            return
        entry_price = self._weighted_price(entries)
        exit_price = self._weighted_price(closes)
        gross = sum(_optional_float(d, "profit", 0.0) for d in deals)
        commission = sum(_optional_float(d, "commission", 0.0) for d in deals)
        swap = sum(_optional_float(d, "swap", 0.0) for d in deals)
        fee = sum(_optional_float(d, "fee", 0.0) for d in deals)
        sl_reason = getattr(self.mt5, "DEAL_REASON_SL", 4)
        tp_reason = getattr(self.mt5, "DEAL_REASON_TP", 5)
        reasons = [getattr(d, "reason", None) for d in closes]
        if sl_reason in reasons:
            exit_reason = "SL"
        elif tp_reason in reasons:
            exit_reason = "TP"
        else:
            exit_reason = "CLOSED"
        digits = int(getattr(self.mt5.symbol_info(self.config.symbol), "digits", 2))
        if entry_price is not None:
            record["entry_price"] = round(entry_price, digits)
        if exit_price is not None:
            record["exit_price"] = round(exit_price, digits)
        record["gross_profit"] = round(gross, 8)
        record["commission"] = round(commission, 8)
        record["swap"] = round(swap, 8)
        record["fee"] = round(fee, 8)
        record["net_profit"] = round(gross + commission + swap + fee, 8)
        record["position_id"] = int(position_id)
        record["exit_reason"] = exit_reason
        record["closed_at_utc"] = utc_iso(self._now())
        self._set_status(record, "CLOSED", None, "broker close reconciled from position history")

    def _reconcile(self):
        positions = self._get_positions()
        if positions is None:
            return False
        bot_positions = [p for p in positions if int(getattr(p, "magic", 0) or 0) == self.config.magic]
        matched_position_keys = set()

        # Recover all tracked in-flight/open orders by comment or stable position id.
        for record in self.state["intents"].values():
            if record.get("status") not in _ACTIVE_STATES:
                continue
            position = self._position_for_record(record, positions)
            if position is not None:
                position_key = self._position_key(position)
                matched_position_keys.add(position_key)
                deals = self._position_deals(record, position_key)
                self._sync_open(record, position, deals)
                continue

            position_id = int(record.get("position_id") or 0)
            deals = self._position_deals(record, position_id) if position_id else None
            if deals is not None and not position_id:
                entries = self._entry_deals(deals)
                if entries:
                    position_id = int(getattr(entries[0], "position_id", 0) or 0)
                    record["position_id"] = position_id or None
                    deals = self._history_by_position(position_id) if position_id else deals
            if deals is None or not self._entry_deals(deals):
                tagged = self._history_by_comment(record)
                if tagged:
                    entries = self._entry_deals(tagged)
                    if entries:
                        position_id = int(getattr(entries[0], "position_id", 0) or 0)
                        record["position_id"] = position_id or None
                        deals = self._history_by_position(position_id) if position_id else tagged
            if position_id and deals is not None and self._close_deals(deals):
                self._sync_closed(record, position_id, deals)
            else:
                self._set_status(record, "UNKNOWN", "POSITION_UNRESOLVED",
                                 "no open position or confirmed close found; automatic retry is disabled")

        # Any position with this magic number that cannot be matched is orphaned.
        for position in bot_positions:
            key = self._position_key(position)
            if key in matched_position_keys:
                continue
            matched = any(self._position_for_record(record, (position,)) is not None
                          for record in self.state["intents"].values()
                          if record.get("status") in _ACTIVE_STATES or record.get("status") == "CLOSED")
            if matched:
                continue
            key_str = str(key or getattr(position, "ticket", "unknown"))
            orphan = self.state["orphan_positions"].get(key_str)
            if orphan is None:
                orphan = {
                    "position_id": key,
                    "symbol": _safe_text(getattr(position, "symbol", ""), 64),
                    "comment": _safe_text(getattr(position, "comment", ""), 64),
                    "status": "OPEN_ORPHAN",
                    "detected_at_utc": utc_iso(self._now()),
                }
                self.state["orphan_positions"][key_str] = orphan
                self._latch_halt("ORPHAN_POSITION", "untracked position with this bot's magic was found")
                atomic_write_json(os.path.join(self.config.outbox, "orphan-" + key_str + ".json"), {
                    "schema_version": SCHEMA_VERSION,
                    "status": "ORPHAN",
                    "position_id": key,
                    "symbol": orphan["symbol"],
                    "message": "untracked broker position; no automatic close or new entry is permitted",
                    "detected_at_utc": orphan["detected_at_utc"],
                })
        return True

    def run_forever(self):
        if not self.connected:
            raise SafetyError("call connect() before run_forever()")
        self.logger("watching the order queue; no account identifiers are logged")
        while True:
            try:
                self.poll_once()
                time.sleep(self.config.poll_seconds)
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                # Any uncertainty is logged and retried as a read-only poll. The
                # durable intent state prevents a repeated order_send.
                self.logger("poll error (%s); no automatic order retry" % type(exc).__name__)
                time.sleep(self.config.poll_seconds)


def _CodedSafetyError(code, message):
    error = SafetyError(message)
    error.code = code
    return error


def main():
    config = ExecutorConfig.from_env()
    if not config.enabled:
        print("mt5_order_executor: disabled (MT5_ORDER_ENABLED=0); no terminal or order API called", flush=True)
        return 0
    if config.account_kind != "demo":
        print("mt5_order_executor: refused; only MT5_ORDER_ACCOUNT_KIND=demo is supported", flush=True)
        return 2
    if config.starting_equity is None:
        print("mt5_order_executor: refused; set MT5_ORDER_STARTING_EQUITY explicitly", flush=True)
        return 2
    try:
        import MetaTrader5 as mt5
    except ImportError:
        print("mt5_order_executor: MetaTrader5 package missing - run this under the configured Wine Python",
              flush=True)
        return 2
    executor = MT5OrderExecutor(mt5, config=config)
    if not executor.connect():
        return 2
    try:
        executor.run_forever()
    except KeyboardInterrupt:
        print("\nmt5_order_executor: stopped", flush=True)
    finally:
        executor.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
