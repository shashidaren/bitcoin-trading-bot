#!/usr/bin/env python3
"""
Lightweight pre-trade filter - Bitcoin Medium-term version
Acts as the final gatekeeper for portfolio/state-level rules.
(Strategy-level rules like RSI, Wick, and Trend are handled in engine.py)
"""

import csv
import os
from datetime import datetime, time, timedelta, timezone

# === FIXED: Paths now point to Bitcoin directory ===
TRADES_LOG = "/opt/bitcoin/trades.csv"
SKIP_LOG   = "/opt/bitcoin/skipped_trades.csv"
LOOKBACK   = 15

# === Settings (Medium-term) ===
SL_COOLDOWN_MINUTES = 30          # Block new trades for 30 min after any SL

# === OPTION 2: Percentage-based ATR (Adaptive to BTC price) ===
# At $80,000: MIN is 0.04% ($32) | MAX is 0.60% ($480)
MIN_ATR_PERCENT = 0.0001  
MAX_ATR_PERCENT = 0.0060  

# === Simple time-based blackout (UTC) ===
BLACKOUT_WINDOWS = [
    (7, 55, 8, 15, "London Open"),
    (12, 25, 12, 45, "NY Open"),
    (13, 55, 14, 15, "NY Open volatility"),
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


def load_recent_trades(n=LOOKBACK):
    if not os.path.isfile(TRADES_LOG):
        return []
    rows = []
    try:
        with open(TRADES_LOG, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)
    except Exception:
        return []
    return rows[-n:] if rows else []


def check_sl_cooldown(trades: list) -> tuple[bool, str]:
    if not trades:
        return False, ""

    last = trades[-1]
    if last.get("Exit_Reason") != "SL":
        return False, ""

    try:
        exit_time = datetime.strptime(last["Exit_Time"], "%Y-%m-%d %H:%M:%S")
        exit_time = exit_time.replace(tzinfo=timezone.utc)
        cooldown_end = exit_time + timedelta(minutes=SL_COOLDOWN_MINUTES)
        now = datetime.now(timezone.utc)

        if now < cooldown_end:
            remaining = int((cooldown_end - now).total_seconds() / 60) + 1
            return True, f"SL Cooldown: {remaining} min remaining"
    except Exception:
        pass

    return False, ""


def analyze_recent(trades: list) -> tuple[bool, str]:
    if len(trades) < 5:
        return False, ""

    recent = trades[-10:]
    sl_trades = [t for t in recent if t.get("Exit_Reason") == "SL"]

    # Circuit breaker: Recent SLs in elevated ATR
    # Note: Changed from 1.6 (Gold value) to 0.005 (0.5% for BTC)
    try:
        high_atr_sl = 0
        for t in sl_trades[-3:]:  
            # Strip commas to prevent ValueError (e.g., "80,000.00" -> "80000.00")
            atr_str = str(t.get("ATR_At_Entry", "0")).replace(",", "")
            price_str = str(t.get("Entry_Price", "0")).replace(",", "")
            
            atr = float(atr_str or 0)
            price = float(price_str or 0)
            
            if price > 0:
                atr_pct = atr / price
                if atr_pct >= 0.005: # 0.5%
                    high_atr_sl += 1
        
        if high_atr_sl >= 2:
            return True, "Recent SLs occurred in elevated ATR (≥0.5%)"
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
        print(f"️ Failed to log skip: {e}")


def should_take_trade(current_atr=None, current_price=None, ema_fast=None, ema_slow=None) -> tuple[bool, str]:
    """
    Final gatekeeper for portfolio/state-level rules.
    """

    # 1. Time blackout
    in_bo, bo_reason = is_in_blackout()
    if in_bo:
        log_skip(bo_reason, current_price, current_atr)
        return False, bo_reason

    trades = load_recent_trades()

    # 2. SL Cooldown
    skip, reason = check_sl_cooldown(trades)
    if skip:
        log_skip(reason, current_price, current_atr)
        return False, reason

    # 3. Percentage-based ATR Filter (Adaptive to BTC price)
    if current_atr is not None and current_price is not None and current_price > 0:
        atr_percent = current_atr / current_price
        
        # Minimum ATR
        if atr_percent < MIN_ATR_PERCENT:
            reason = f"ATR too low ({atr_percent*100:.3f}% < {MIN_ATR_PERCENT*100:.3f}%)"
            log_skip(reason, current_price, current_atr)
            return False, reason

        # Maximum ATR (Block extreme news volatility)
        if atr_percent > MAX_ATR_PERCENT:
            reason = f"ATR too high - News volatility ({atr_percent*100:.3f}% > {MAX_ATR_PERCENT*100:.3f}%)"
            log_skip(reason, current_price, current_atr)
            return False, reason

    # 4. Recent SL pattern (Circuit breaker)
    #skip, reason = analyze_recent(trades)
    #if skip:
    #    log_skip(reason, current_price, current_atr)
    #    return False, reason

    # All filters passed
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
