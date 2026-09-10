#!/usr/bin/env python3
"""
Lightweight pre-trade filter & Portfolio Risk Gatekeeper - Bitcoin version.

Acts as the final gatekeeper for portfolio/state-level rules.
(Strategy-level rules like RSI, Wick, Floor/Ceiling, and Trend are handled
in engine.py.)

Ported from gold-trading-bot (2026-09-10): escalating SL cooldowns, daily-loss
circuit breaker, expanded session blackouts, schema-drift tripwire. ATR bounds
stay percentage-based (adaptive to BTC price) instead of gold's absolute $.

Timestamps: engine.py writes Entry_Time / Exit_Time in UTC.
This module also uses UTC for blackouts, cooldowns, daily limits, and skip logs.
"""

import csv
import os
from datetime import datetime, time, timedelta, timezone

TRADES_LOG = "/opt/bitcoin/trades.csv"
SKIP_LOG   = "/opt/bitcoin/skipped_trades.csv"
LOOKBACK   = 30

# === Settings (Risk & Volatility Controls) ===
SL_COOLDOWN_BASE_MINUTES      = 30    # Base cooldown after 1 SL
SL_COOLDOWN_ESCALATED_MINUTES = 60    # Escalated cooldown after 2 consecutive SLs
MAX_DAILY_LOSSES              = 3     # Halt trading for the rest of the UTC day after 3 SLs

# === Percentage-based ATR bounds (adaptive to BTC price) ===
# At $80,000: MIN is 0.01% ($8) | MAX is 0.60% ($480)
MIN_ATR_PERCENT = 0.0001
MAX_ATR_PERCENT = 0.0060

# === Session Blackout Windows (UTC) ===
# Equity-session volatility that whipsaws BTC too (ported from gold 2026-09-10).
# NOTE: gold also blacks out 21:45-22:30 UTC (forex daily rollover spread spike).
# BTC trades 24/7 with no rollover, so that window is intentionally NOT ported.
BLACKOUT_WINDOWS = [
    (7, 55, 9, 0, "London Open & Early Session Kill-Zone"),
    (12, 25, 12, 45, "NY Early Pre-Market"),
    (13, 25, 15, 15, "NY Open & US High-Impact Macro Releases"),
]


def is_in_blackout(now: datetime = None) -> tuple[bool, str]:
    if now is None:
        now = datetime.now(timezone.utc)
    t = now.time()
    for sh, sm, eh, em, label in BLACKOUT_WINDOWS:
        start = time(sh, sm)
        end = time(eh, em)
        if start <= t <= end:
            return True, f"Blackout: {label}"
    return False, ""


def load_recent_trades(n=LOOKBACK) -> list:
    if not os.path.isfile(TRADES_LOG):
        return []
    rows = []
    try:
        with open(TRADES_LOG, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Schema-drift tripwire (gold 2026-09-10 incident): if a row was
                # written with a Trade_Type column but the header lacks it,
                # Entry_Time parses as "BUY"/"SELL" and every later field is
                # shifted - Exit_Reason becomes a price, so SL counting,
                # cooldowns and the daily-loss breaker silently stop working.
                if (row.get("Entry_Time") or "").strip().upper() in ("BUY", "SELL"):
                    print("WARNING: trades.csv schema drift detected (Entry_Time == BUY/SELL). "
                          "Risk-gate counts are UNRELIABLE until the file is migrated - "
                          "restart the engine (it auto-migrates) or run engine.migrate_trades_csv().")
                rows.append(row)
    except Exception:
        return []
    return rows[-n:] if rows else []


def get_daily_sl_count(trades: list, now: datetime = None) -> int:
    """Counts number of Stop Loss trades that exited today in UTC."""
    if not trades:
        return 0
    if now is None:
        now = datetime.now(timezone.utc)
    today_str = now.strftime("%Y-%m-%d")
    count = 0
    for t in trades:
        ext = t.get("Exit_Time") or t.get("Entry_Time") or ""
        if ext.startswith(today_str) and (t.get("Exit_Reason") or "").strip().upper() == "SL":
            count += 1
    return count


def get_consecutive_sl_count(trades: list) -> int:
    """Counts uninterrupted trailing Stop Loss trades."""
    if not trades:
        return 0
    count = 0
    for t in reversed(trades):
        reason = (t.get("Exit_Reason") or "").strip().upper()
        if reason == "SL":
            count += 1
        elif reason == "TP":
            break
    return count


def check_daily_loss_limit(trades: list, now: datetime = None) -> tuple[bool, str]:
    """Circuit breaker: halts trading if daily loss limit is hit."""
    daily_sls = get_daily_sl_count(trades, now)
    if daily_sls >= MAX_DAILY_LOSSES:
        return True, f"Daily Loss Limit Reached ({daily_sls}/{MAX_DAILY_LOSSES} SLs today) - Trading Halted"
    return False, ""


def check_sl_cooldown(trades: list, now: datetime = None) -> tuple[bool, str]:
    """Escalating cooldown based on consecutive losses."""
    if not trades:
        return False, ""

    last = trades[-1]
    if (last.get("Exit_Reason") or "").strip().upper() != "SL":
        return False, ""

    consecutive_sls = get_consecutive_sl_count(trades)
    cooldown_minutes = (
        SL_COOLDOWN_ESCALATED_MINUTES if consecutive_sls >= 2 else SL_COOLDOWN_BASE_MINUTES
    )

    try:
        # Exit_Time is written by engine.py in UTC
        exit_time = datetime.strptime(last["Exit_Time"], "%Y-%m-%d %H:%M:%S")
        exit_time = exit_time.replace(tzinfo=timezone.utc)
        cooldown_end = exit_time + timedelta(minutes=cooldown_minutes)
        if now is None:
            now = datetime.now(timezone.utc)

        if now < cooldown_end:
            remaining = int((cooldown_end - now).total_seconds() / 60) + 1
            streak_info = f" ({consecutive_sls} consecutive SLs -> {cooldown_minutes}m cooldown)" if consecutive_sls >= 2 else ""
            return True, f"SL Cooldown: {remaining} min remaining{streak_info}"
    except Exception:
        pass

    return False, ""


def analyze_recent(trades: list) -> tuple[bool, str]:
    """Legacy circuit breaker: recent SLs in elevated ATR (>=0.5%).

    Kept for reference but DISABLED - superseded by the daily-loss circuit
    breaker + escalating cooldowns (gold 2026-09-10). Left here so the old
    rule stays visible in history rather than silently vanishing.
    """
    if len(trades) < 5:
        return False, ""

    recent = trades[-10:]
    sl_trades = [t for t in recent if (t.get("Exit_Reason") or "").strip().upper() == "SL"]

    try:
        high_atr_sl = 0
        for t in sl_trades[-3:]:
            # Strip commas to tolerate legacy comma-formatted rows
            # (e.g. "80,000.00" -> "80000.00")
            atr_str = str(t.get("ATR_At_Entry", "0")).replace(",", "")
            price_str = str(t.get("Entry_Price", "0")).replace(",", "")

            atr = float(atr_str or 0)
            price = float(price_str or 0)

            if price > 0:
                atr_pct = atr / price
                if atr_pct >= 0.005:  # 0.5%
                    high_atr_sl += 1

        if high_atr_sl >= 2:
            return True, "Recent SLs occurred in elevated ATR (>=0.5%)"
    except Exception:
        pass

    return False, ""


def log_skip(reason: str, price=None, atr=None):
    file_exists = os.path.isfile(SKIP_LOG)
    try:
        with open(SKIP_LOG, mode="a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "Timestamp", "Reason", "Price", "ATR"
            ])
            if not file_exists:
                writer.writeheader()
            writer.writerow({
                "Timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                "Reason": reason,
                "Price": f"{price:.2f}" if price is not None else "",
                "ATR": f"{atr:.2f}" if atr is not None else "",
            })
    except Exception as e:
        print(f"WARNING: Failed to log skip: {e}")


def should_take_trade(current_atr=None, current_price=None, ema_fast=None, ema_slow=None, now: datetime = None) -> tuple[bool, str]:
    """
    Final gatekeeper for portfolio/state-level rules.
    Note: RSI, Wick, Floor/Ceiling, and Trend direction are validated in engine.py.
    """

    # 1. Time blackout
    in_bo, bo_reason = is_in_blackout(now)
    if in_bo:
        log_skip(bo_reason, current_price, current_atr)
        return False, bo_reason

    trades = load_recent_trades()

    # 2. Daily Loss Circuit Breaker
    halted, halt_reason = check_daily_loss_limit(trades, now)
    if halted:
        log_skip(halt_reason, current_price, current_atr)
        return False, halt_reason

    # 3. Escalating SL Cooldown
    skip, reason = check_sl_cooldown(trades, now)
    if skip:
        log_skip(reason, current_price, current_atr)
        return False, reason

    # 4. Percentage-based ATR Filter (adaptive to BTC price)
    if current_atr is not None and current_price is not None and current_price > 0:
        atr_percent = current_atr / current_price

        # Minimum ATR (skip dead chop)
        if atr_percent < MIN_ATR_PERCENT:
            reason = f"ATR too low ({atr_percent*100:.3f}% < {MIN_ATR_PERCENT*100:.3f}%)"
            log_skip(reason, current_price, current_atr)
            return False, reason

        # Maximum ATR (block extreme news volatility)
        if atr_percent > MAX_ATR_PERCENT:
            reason = f"ATR too high - News volatility ({atr_percent*100:.3f}% > {MAX_ATR_PERCENT*100:.3f}%)"
            log_skip(reason, current_price, current_atr)
            return False, reason

    # 5. Recent SL pattern (legacy circuit breaker) - DISABLED, superseded by
    #    the daily-loss breaker + escalating cooldowns above.
    # skip, reason = analyze_recent(trades)
    # if skip:
    #     log_skip(reason, current_price, current_atr)
    #     return False, reason

    # All portfolio filters passed
    return True, "OK"


if __name__ == "__main__":
    # Test run with realistic Bitcoin dummy data
    allow, reason = should_take_trade(
        current_atr=35.00,
        current_price=80000.00,
        ema_fast=80005.00,
        ema_slow=79995.00
    )
    print(f"Allow: {allow} | Reason: {reason}")
