#!/usr/bin/env python3
"""MT5 -> file sidecar for the Nasdaq-100 (US100Cash) M15 engine.

The Linux engine cannot import MetaTrader5 (no Linux wheels on PyPI), so this
daemon runs under Wine Python in the SAME prefix as the XM MT5 terminal and
publishes:
  1) Z:/opt/nasdaq/mt5_warmup_candles.json  (250 closed M15 bars on startup and
     refreshed periodically so engine.py warms EMA200/EMA50/RSI/ATR immediately
     on Day 0 instead of waiting 50 trading hours!)
  2) Z:/opt/nasdaq/mt5_last_candle.json     (latest closed M15 candle every 5s,
     with broker-server time converted to UTC via a fresh tick offset)

Run (manual test):
  export WINEPREFIX=~/.mt5 && xvfb-run --auto-servernum \\
      wine C:/Python312/python.exe Z:/opt/nasdaq/tools/mt5_feed.py

Or as a service (see deploy/mt5feed.service):
  sudo systemctl enable --now mt5feed-nasdaq

Imports cleanly on Linux without MetaTrader5 so tools/smoke_test.py can import
pure helpers (estimate_server_offset, build_warmup_payload) directly.
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

SYMBOL = os.environ.get("MT5_FEED_SYMBOL", "US100Cash")
OUT = os.environ.get("MT5_FEED_FILE", "Z:/opt/nasdaq/mt5_last_candle.json")
WARMUP_OUT = os.environ.get("MT5_WARMUP_FILE", "Z:/opt/nasdaq/mt5_warmup_candles.json")
WARMUP_BARS = int(os.environ.get("MT5_WARMUP_BARS", "250"))
WARMUP_REFRESH_S = 6 * 3600
POLL = float(os.environ.get("MT5_FEED_POLL", "5"))
TIMEFRAME_NAME = os.environ.get("MT5_FEED_TIMEFRAME", "M15").strip().upper()


def _resolve_timeframe(mt5_mod, tf_name: str):
    if mt5_mod is None:
        return {"M1": 1, "M5": 5, "M15": 15, "H1": 16385}.get(tf_name, 15)
    tfs = {
        "M1": getattr(mt5_mod, "TIMEFRAME_M1", 1),
        "M5": getattr(mt5_mod, "TIMEFRAME_M5", 5),
        "M15": getattr(mt5_mod, "TIMEFRAME_M15", 15),
        "H1": getattr(mt5_mod, "TIMEFRAME_H1", 16385),
    }
    return tfs.get(tf_name, getattr(mt5_mod, "TIMEFRAME_M15", 15))


def utc_now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def atomic_write_json(path: str, payload: dict) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    os.replace(tmp, path)


def estimate_server_offset(server_ts: int, now_epoch: float = None):
    """Return the broker-server offset from UTC for a fresh tick, or None if stale."""
    if not server_ts:
        return None
    now = time.time() if now_epoch is None else float(now_epoch)
    delta = float(server_ts) - now
    candidate = int(round(delta / 3600.0) * 3600)
    if abs(candidate) > 14 * 3600 or abs(delta - candidate) > 300:
        return None
    return candidate


def build_warmup_payload(rates, server_offset: int, symbol: str = SYMBOL, timeframe: str = TIMEFRAME_NAME) -> dict:
    """Convert historical MT5 rate rows into UTC warm-up candles for engine.py."""
    candles = []
    for r in rates or ():
        srv_ts = int(r["time"])
        candles.append({
            "ts": srv_ts - int(server_offset),
            "server_ts": srv_ts,
            "open": float(r["open"]),
            "high": float(r["high"]),
            "low": float(r["low"]),
            "close": float(r["close"]),
            "tick_volume": int(r["tick_volume"]),
        })
    candles.sort(key=lambda c: c["ts"])
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "server_offset_s": int(server_offset),
        "updated_at": utc_now_str(),
        "candles": candles,
    }


def main(mt5_mod=None) -> int:
    m = mt5 if mt5_mod is None else mt5_mod
    if m is None:
        print("mt5_feed: MetaTrader5 package missing - install it in the WINE python:")
        print("  wine C:/Python312/python.exe -m pip install MetaTrader5")
        sys.exit(1)

    timeframe = _resolve_timeframe(m, TIMEFRAME_NAME)
    if not m.initialize():
        print(f"mt5_feed: MT5 initialize failed: {m.last_error()} "
              f"(is the terminal running and logged in in this prefix?)", flush=True)
        sys.exit(1)
    if not m.symbol_select(SYMBOL, True):
        print(f"mt5_feed: symbol_select({SYMBOL}) failed: {m.last_error()} "
              f"(check exact symbol name in XM Market Watch, e.g. US100Cash)", flush=True)
        sys.exit(1)
    account = m.account_info()
    acct = f" | account {account.login}" if account else ""
    print(f"mt5_feed: publishing closed {TIMEFRAME_NAME} {SYMBOL} candles -> {OUT}{acct}", flush=True)
    server_offset = None
    prev_tick_ts = None
    last_warmup_write = 0.0

    while True:
        try:
            tick = m.symbol_info_tick(SYMBOL)
            tick_ts = int(getattr(tick, "time", 0) or 0) if tick else 0
            if tick_ts and (prev_tick_ts is None or tick_ts != prev_tick_ts):
                learned = estimate_server_offset(tick_ts)
                if learned is not None:
                    server_offset = learned
            if tick_ts:
                prev_tick_ts = tick_ts

            now_mono = time.monotonic()
            if server_offset is not None and WARMUP_BARS > 0 and (
                last_warmup_write == 0.0 or (now_mono - last_warmup_write) >= WARMUP_REFRESH_S
            ):
                hist = m.copy_rates_from_pos(SYMBOL, timeframe, 1, WARMUP_BARS)
                if hist is not None and len(hist) > 0:
                    warm_payload = build_warmup_payload(hist, server_offset, SYMBOL, TIMEFRAME_NAME)
                    atomic_write_json(WARMUP_OUT, warm_payload)
                    last_warmup_write = now_mono
                    print(f"mt5_feed: wrote {len(warm_payload['candles'])} {TIMEFRAME_NAME} warm-up bars -> {WARMUP_OUT}",
                          flush=True)

            rates = m.copy_rates_from_pos(SYMBOL, timeframe, 1, 1)
            if rates is not None and len(rates) > 0 and server_offset is not None:
                r = rates[0]
                server_ts = int(r["time"])
                payload = {
                    "ts": server_ts - server_offset,
                    "server_ts": server_ts,
                    "server_offset_s": server_offset,
                    "open": float(r["open"]),
                    "high": float(r["high"]),
                    "low": float(r["low"]),
                    "close": float(r["close"]),
                    "tick_volume": int(r["tick_volume"]),
                    "updated_at": utc_now_str(),
                }
                atomic_write_json(OUT, payload)
            elif server_offset is None:
                print(f"mt5_feed: waiting for a fresh {SYMBOL} tick to learn broker UTC offset...", flush=True)
            else:
                print(f"mt5_feed: no {TIMEFRAME_NAME} data for {SYMBOL}: {m.last_error()}", flush=True)
            time.sleep(POLL)
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"mt5_feed: error: {e} (retrying)", flush=True)
            time.sleep(POLL)
    m.shutdown()
    print("mt5_feed: stopped", flush=True)
    return 0


if __name__ == "__main__":
    main()
