#!/usr/bin/env python3
"""Atomic file protocol shared by the Linux engine and Wine MT5 order executor.

This module is deliberately stdlib-only so it imports under Linux Python and
under the Wine Python that can load MetaTrader5.  It does not import MetaTrader5
and does not place, check, modify, or close orders.

The order executor is fail-closed and demo-only; see docs/MT5-ORDER-EXECUTOR.md.
"""
import json
import math
import os
import tempfile
import uuid
from datetime import datetime, timezone

SCHEMA_VERSION = 1
DEFAULT_ROOT = "/opt/bitcoin/mt5_order_bridge"


def utc_iso(now=None):
    """Return an unambiguous UTC timestamp suitable for the on-disk protocol."""
    if now is None:
        now = datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("UTC timestamps must be timezone-aware")
    return now.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def atomic_write_json(path, payload):
    """Write one JSON document and atomically replace `path` on the same volume."""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix="." + os.path.basename(path) + ".",
                                    suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False)
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except OSError:
                # Some Wine/Windows filesystem combinations do not expose fsync.
                pass
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def read_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


class OrderBridge:
    """Linux-side writer/result reader for the order-executor file queue.

    `submit_open` writes a unique intent into `inbox/` atomically.  The executor
    copies its outcome into `outbox/<intent_id>.json`; results are not consumed
    by reading them, so callers may safely poll or restart.  This client is not
    wired into engine.py yet: Stage A still needs its separate engine/order-path
    integration before any demo run.
    """

    def __init__(self, root=None):
        self.root = os.path.abspath(root or os.environ.get("MT5_ORDER_DIR", DEFAULT_ROOT))
        self.inbox = os.path.join(self.root, "inbox")
        self.outbox = os.path.join(self.root, "outbox")

    def submit_open(self, direction, atr, signal_ts=None, symbol="BTCUSD", volume=0.01,
                    created_at=None, intent_id=None):
        """Queue one OPEN intent and return its 32-hex-character id.

        The executor re-validates every field (including size, symbol and age);
        callers must not treat a successful file write as an accepted order.
        """
        direction = str(direction).strip().upper()
        if direction not in ("BUY", "SELL"):
            raise ValueError("direction must be BUY or SELL")
        try:
            atr = float(atr)
            volume = float(volume)
        except (TypeError, ValueError):
            raise ValueError("atr and volume must be numeric")
        if not (math.isfinite(atr) and math.isfinite(volume) and atr > 0.0 and volume > 0.0):
            raise ValueError("atr and volume must be finite and positive")

        intent_id = str(intent_id or uuid.uuid4().hex)
        if len(intent_id) != 32 or any(c not in "0123456789abcdef" for c in intent_id):
            raise ValueError("intent_id must be 32 lowercase hexadecimal characters")
        if created_at is None:
            created_at = utc_iso()
        payload = {
            "schema_version": SCHEMA_VERSION,
            "intent_id": intent_id,
            "action": "OPEN",
            "created_at": created_at,
            "signal_ts": signal_ts,
            "symbol": str(symbol),
            "direction": direction,
            "volume": volume,
            "atr": atr,
        }
        path = os.path.join(self.inbox, intent_id + ".json")
        if os.path.exists(path):
            raise FileExistsError("an intent with this id is already queued")
        atomic_write_json(path, payload)
        return intent_id

    def get_result(self, intent_id):
        """Return the latest executor result, or None while it is not available."""
        if len(str(intent_id)) != 32 or any(c not in "0123456789abcdef" for c in str(intent_id)):
            raise ValueError("intent_id must be 32 lowercase hexadecimal characters")
        path = os.path.join(self.outbox, str(intent_id) + ".json")
        if not os.path.isfile(path):
            return None
        try:
            result = read_json(path)
        except (OSError, ValueError, json.JSONDecodeError):
            # Atomic replacement should prevent torn files; tolerate a transient
            # network-drive read error and let the caller poll again.
            return None
        if result.get("intent_id") != intent_id:
            return None
        return result
