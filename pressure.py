#!/usr/bin/env python3
"""Read-only BTC tape-pressure context for the dashboard.

This module describes the last 60 closed M5 candles. It is deliberately not
imported by engine.py or trade_filter.py: pressure is not an entry/exit gate.
The composite includes EMA trend and slope, which are already strategy gates,
so a high/low reading may simply restate the side the engine is allowed to take.
The flow input is the feed's tick-count volume proxy, not exchange BTC volume.

The calculations are transparent and return each component as well as the
combined buy/sell shares. Strategy constants below are mirrored from engine.py;
tools/smoke_test.py checks that they do not drift.
"""
from __future__ import annotations

import csv
import math
import os
from datetime import datetime

# Mirrored strategy constants (source of truth: engine.py).
PRESSURE_WINDOW = 60                # 60 closed M5 candles = five hours
LOOKBACK_PERIOD = 20
WICK_RATIO_TARGET = 0.15
FLOOR_BUFFER_PCT = 0.0015
EMA_SLOPE_LOOKBACK = 30             # 30 M5 bars = 150 minutes
MAX_BELOW_EMA_ATR = 0.30
RSI_MIN = 40.0
RSI_MAX = 70.0
ATR_SL_MULT = 2.0
ATR_TP_MULT = 4.0

PRESSURE_WEIGHTS = {
    "flow": 0.30,
    "momentum": 0.20,
    "trend": 0.20,
    "slope": 0.15,
    "rsi": 0.15,
}

DATA_DIR = os.getenv("BTC_DATA_DIR", "/opt/bitcoin")
LOG_FILE_PATH = os.getenv("BTC_LOG_FILE", os.path.join(DATA_DIR, "forward_test_log.csv"))
TRADES_FILE_PATH = os.getenv("BTC_TRADES_FILE", os.path.join(DATA_DIR, "trades.csv"))


def parse_float(value):
    """Parse numeric CSV cells, tolerating blanks, commas and Calculating."""
    try:
        return float(str(value).strip().replace(",", ""))
    except (TypeError, ValueError):
        return None


def parse_ts(value):
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    return None


def read_rows(path):
    """Read a CSV as dictionaries; return [] for absent or temporarily bad files."""
    if not path or not os.path.isfile(path):
        return []
    try:
        with open(path, newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))
    except (OSError, csv.Error, UnicodeError):
        return []


def _sigmoid(x):
    return 1.0 / (1.0 + math.exp(-max(-60.0, min(60.0, x))))


def _clip01(x):
    return max(0.0, min(1.0, x))


def pressure(rows, window=PRESSURE_WINDOW):
    """Build a weighted, descriptive buy/sell pressure reading.

    Returns None until all required price/indicator history is present. Each
    component exposes its raw value, buy-share, weight and weighted contribution
    so the combined percentage is auditable. `Volume` is tick count in this repo.
    """
    if window < 2 or len(rows) < max(window + 1, EMA_SLOPE_LOOKBACK + 1):
        return None

    def col(name):
        return [parse_float(row.get(name)) for row in rows]

    opens, highs, lows, closes = (col(key) for key in ("Open", "High", "Low", "Close"))
    volumes = [parse_float(row.get("Volume")) or 0.0 for row in rows]
    ema50, ema200, rsis, atrs = (col(key) for key in ("EMA_50", "EMA_200", "RSI", "ATR"))
    i = len(rows) - 1
    atr, close = atrs[i], closes[i]
    slope_i = i - EMA_SLOPE_LOOKBACK
    # Do not manufacture neutral component values during indicator warm-up.
    if (atr is None or atr <= 0 or close is None or ema50[i] is None
            or ema200[i] is None or slope_i < 0 or ema50[slope_i] is None
            or rsis[i] is None):
        return None

    # Tick-count-weighted signed candle body (bounded by -1 and +1).
    flow_num = flow_den = 0.0
    for j in range(i - window + 1, i + 1):
        o, h, l, c = opens[j], highs[j], lows[j], closes[j]
        if None in (o, h, l, c) or h <= l:
            continue
        volume = volumes[j]
        if volume <= 0:
            continue
        flow_num += ((c - o) / (h - l)) * volume
        flow_den += volume
    if flow_den <= 0:
        return None
    flow = flow_num / flow_den

    start_close = closes[i - window]
    if start_close is None:
        return None
    momentum = (close - start_close) / atr
    trend = (ema50[i] - ema200[i]) / atr
    slope = (ema50[i] - ema50[slope_i]) / atr
    rsi = rsis[i]

    shares = {
        "flow": _clip01((flow + 1.0) / 2.0),
        "momentum": _sigmoid(momentum / 1.5),
        "trend": _sigmoid(trend / 0.5),
        "slope": _sigmoid(slope / 0.5),
        "rsi": _clip01((rsi - 30.0) / 40.0),
    }
    component_defs = [
        ("flow", "Tick-weighted candle flow", flow, f"{flow:+.2f}", "signed body (−1 to +1)"),
        ("momentum", f"{window}-bar momentum", momentum, f"{momentum:+.2f}", "ATR"),
        ("trend", "EMA50 vs EMA200", trend, f"{trend:+.2f}", "ATR"),
        ("slope", f"EMA50 {EMA_SLOPE_LOOKBACK}-bar slope", slope, f"{slope:+.2f}", "ATR"),
        ("rsi", "RSI posture", rsi, f"{rsi:.1f}", "RSI points"),
    ]
    components = []
    for key, label, raw_value, raw, unit in component_defs:
        share = shares[key]
        weight = PRESSURE_WEIGHTS[key]
        components.append({
            "key": key,
            "label": label,
            "raw": raw,
            "unit": unit,
            "buy_share": share,
            "buy_pct": share * 100.0,
            "weight": weight,
            "contribution": share * weight * 100.0,
        })
    buy_pct = sum(item["contribution"] for item in components)
    if buy_pct >= 70:
        label = "Tape leaning strongly up"
    elif buy_pct >= 58:
        label = "Tape leaning up"
    elif buy_pct > 42:
        label = "Tape balanced"
    elif buy_pct > 30:
        label = "Tape leaning down"
    else:
        label = "Tape leaning strongly down"
    return {
        "window": window,
        "buy_pct": buy_pct,
        "sell_pct": 100.0 - buy_pct,
        "label": label,
        "components": components,
        "as_of": rows[i].get("Timestamp"),
    }


def location(rows):
    """Report current close relative to the engine's previous-20-bar levels."""
    if len(rows) < LOOKBACK_PERIOD + 1:
        return None
    current = rows[-1]
    prior = rows[-LOOKBACK_PERIOD - 1:-1]
    lows = [parse_float(row.get("Low")) for row in prior]
    highs = [parse_float(row.get("High")) for row in prior]
    lows = [value for value in lows if value is not None]
    highs = [value for value in highs if value is not None]
    close = parse_float(current.get("Close"))
    atr = parse_float(current.get("ATR"))
    floor, ceiling = (min(lows), max(highs)) if lows and highs else (None, None)
    if close is None or floor is None or ceiling is None:
        return None
    return {
        "close": close,
        "floor": floor,
        "ceiling": ceiling,
        "atr": atr,
        "floor_atr": (close - floor) / atr if atr and atr > 0 else None,
        "ceiling_atr": (ceiling - close) / atr if atr and atr > 0 else None,
        "floor_logged": parse_float(current.get("Dynamic_Floor")),
        "as_of": current.get("Timestamp"),
    }


def calibrate(log_rows, trades):
    """Descriptive per-side pressure readings at the last logged bar pre-entry.

    This makes no threshold/bucket claim. We deliberately use only a log bar
    strictly earlier than the trade's entry timestamp, avoiding the entry bar.
    P/L here is the ledger's gross Profit (the ledger does not subtract costs).
    """
    parsed_log = [(parse_ts(row.get("Timestamp")), row) for row in log_rows]
    parsed_log = [(ts, row) for ts, row in parsed_log if ts is not None]
    output = {"BUY": [], "SELL": []}
    for trade in trades:
        side = (trade.get("Trade_Type") or "BUY").strip().upper()
        entry_ts = parse_ts(trade.get("Entry_Time"))
        if side not in output or entry_ts is None:
            continue
        eligible = [index for index, (ts, _) in enumerate(parsed_log) if ts < entry_ts]
        if not eligible:
            continue
        index = eligible[-1]
        start = max(0, index - PRESSURE_WINDOW)
        reading = pressure([row for _, row in parsed_log[start:index + 1]])
        if reading is None:
            continue
        profit = parse_float(trade.get("Profit"))
        output[side].append({"score": reading["buy_pct"], "profit": profit})

    summary = {}
    for side, items in output.items():
        scores = [item["score"] for item in items]
        profits = [item["profit"] for item in items if item["profit"] is not None]
        wins = sum(1 for value in profits if value > 0)
        losses = sum(1 for value in profits if value < 0)
        summary[side] = {
            "n": len(items),
            "score_min": min(scores) if scores else None,
            "score_median": sorted(scores)[len(scores) // 2] if scores else None,
            "score_max": max(scores) if scores else None,
            "wins": wins,
            "losses": losses,
            "gross_profit": sum(profits) if profits else 0.0,
        }
    return summary
