#!/usr/bin/env python3
import csv
import os
from collections import deque

# --- STRATEGY PARAMETERS (Must match engine.py exactly) ---
LOOKBACK_PERIOD = 20
WICK_RATIO_TARGET = 0.35
EMA_FAST = 50
EMA_SLOW = 200
RSI_PERIOD = 14
ATR_PERIOD = 14
FLOOR_BUFFER_PCT = 0.0015
ATR_SL_MULT = 1.5
ATR_TP_MULT = 2.5
RSI_MIN = 40.0
RSI_MAX = 70.0
MIN_ATR = 100.0

LOG_FILE = "/opt/bitcoin/forward_test_log.csv"
TRADES_FILE = "/opt/bitcoin/trades.csv"

def main():
    if not os.path.isfile(LOG_FILE):
        print(f"❌ Cannot find {LOG_FILE}")
        return

    print(f"📂 Reading {LOG_FILE} to generate trades...")
    
    # Read all candles
    candles = []
    with open(LOG_FILE, mode="r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            candles.append({
                "time": row["Timestamp"],
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": float(row["Volume"]) if row["Volume"] != "Calculating" else 1.0
            })

    if len(candles) < EMA_SLOW:
        print("⚠️ Not enough data to calculate EMA 200. Need at least 200 candles.")
        return

    # Indicator buffers
    lows = deque(maxlen=EMA_SLOW)
    highs = deque(maxlen=EMA_SLOW)
    closes = deque(maxlen=EMA_SLOW)
    volumes = deque(maxlen=EMA_SLOW)
    tr_list = deque(maxlen=ATR_PERIOD)
    rsi_gains = deque(maxlen=RSI_PERIOD)
    rsi_losses = deque(maxlen=RSI_PERIOD)

    ema_fast = None
    ema_slow = None
    rsi = None
    atr = None
    prev_close = None

    k_fast = 2 / (EMA_FAST + 1)
    k_slow = 2 / (EMA_SLOW + 1)

    trade_active = False
    entry_price = 0.0
    stop_loss = 0.0
    take_profit = 0.0
    entry_time = ""
    entry_rsi = 0.0
    entry_atr = 0.0
    entry_wick = 0.0
    entry_ema_f = 0.0
    entry_ema_s = 0.0
    trade_num = 0
    wins = 0
    losses = 0
    balance = 500.00

    trades = []

    print("🔄 Simulating trades...")
    for i, candle in enumerate(candles):
        o, h, l, c, v = candle["open"], candle["high"], candle["low"], candle["close"], candle["volume"]
        lows.append(l); highs.append(h); closes.append(c); volumes.append(v)

        # Calculate Indicators
        if prev_close is not None:
            change = c - prev_close
            rsi_gains.append(max(change, 0))
            rsi_losses.append(max(-change, 0))
            tr = max(h - l, abs(h - prev_close), abs(l - prev_close))
            tr_list.append(tr)

        prev_close = c

        if len(closes) >= EMA_FAST:
            if ema_fast is None:
                ema_fast = sum(list(closes)[-EMA_FAST:]) / EMA_FAST
            else:
                ema_fast = (c * k_fast) + (ema_fast * (1 - k_fast))

        if len(closes) >= EMA_SLOW:
            if ema_slow is None:
                ema_slow = sum(list(closes)[-EMA_SLOW:]) / EMA_SLOW
            else:
                ema_slow = (c * k_slow) + (ema_slow * (1 - k_slow))

        if len(rsi_gains) >= RSI_PERIOD:
            avg_gain = sum(rsi_gains) / RSI_PERIOD
            avg_loss = sum(rsi_losses) / RSI_PERIOD
            rsi = 100.0 if avg_loss == 0 else 100 - (100 / (1 + (avg_gain / avg_loss)))

        if len(tr_list) >= ATR_PERIOD:
            atr = sum(tr_list) / ATR_PERIOD

        # Skip evaluation until warm
        if len(closes) < EMA_SLOW or atr is None or rsi is None or ema_slow is None:
            continue

        # Check Exits First (if in a trade)
        if trade_active:
            # For a BUY, check if Low hit SL first, else if High hit TP
            if l <= stop_loss:
                # SL Hit
                exit_price = stop_loss
                profit = exit_price - entry_price
                balance += profit
                losses += 1
                trade_active = False
                trades.append({
                    "Trade_Num": trade_num, "Entry_Time": entry_time, "Exit_Time": candle["time"],
                    "Entry_Price": f"{entry_price:,.2f}", "Stop_Loss": f"{stop_loss:,.2f}",
                    "Take_Profit": f"{take_profit:,.2f}", "Exit_Price": f"{exit_price:,.2f}",
                    "Exit_Reason": "SL", "Profit": f"{profit:,.2f}", "Balance_After": f"{balance:,.2f}",
                    "RSI_At_Entry": f"{entry_rsi:.1f}", "ATR_At_Entry": f"{entry_atr:,.2f}",
                    "Wick_Ratio_At_Entry": f"{entry_wick:.1%}", "EMA50_At_Entry": f"{entry_ema_f:,.2f}",
                    "EMA200_At_Entry": f"{entry_ema_s:,.2f}"
                })
                print(f"  ❌ Trade {trade_num} SL Hit @ {exit_price:,.2f} (Profit: {profit:,.2f})")
                continue
            elif h >= take_profit:
                # TP Hit
                exit_price = take_profit
                profit = exit_price - entry_price
                balance += profit
                wins += 1
                trade_active = False
                trades.append({
                    "Trade_Num": trade_num, "Entry_Time": entry_time, "Exit_Time": candle["time"],
                    "Entry_Price": f"{entry_price:,.2f}", "Stop_Loss": f"{stop_loss:,.2f}",
                    "Take_Profit": f"{take_profit:,.2f}", "Exit_Price": f"{exit_price:,.2f}",
                    "Exit_Reason": "TP", "Profit": f"{profit:,.2f}", "Balance_After": f"{balance:,.2f}",
                    "RSI_At_Entry": f"{entry_rsi:.1f}", "ATR_At_Entry": f"{entry_atr:,.2f}",
                    "Wick_Ratio_At_Entry": f"{entry_wick:.1%}", "EMA50_At_Entry": f"{entry_ema_f:,.2f}",
                    "EMA200_At_Entry": f"{entry_ema_s:,.2f}"
                })
                print(f"  ✅ Trade {trade_num} TP Hit @ {exit_price:,.2f} (Profit: {profit:,.2f})")
                continue

        # Check Entries (if not in a trade)
        body_bottom = min(o, c)
        lower_wick = body_bottom - l
        candle_range = h - l
        wick_ratio = lower_wick / candle_range if candle_range > 0 else 0
        valid_rejection = wick_ratio >= WICK_RATIO_TARGET

        dynamic_floor = min(list(lows)[-LOOKBACK_PERIOD:])
        volume_ma = sum(list(volumes)[-LOOKBACK_PERIOD:]) / LOOKBACK_PERIOD
        
        tested_floor = l <= (dynamic_floor * (1 + FLOOR_BUFFER_PCT))
        held_support = c > dynamic_floor
        volume_confirmed = v >= (volume_ma * 0.9) # Defaulting to 0.9 multiplier
        
        trend_confirmed = ema_fast > ema_slow
        
        rsi_ok = (RSI_MIN < rsi < RSI_MAX)
        atr_ok = (atr > MIN_ATR)

        if (tested_floor and valid_rejection and held_support and volume_confirmed and 
            trend_confirmed and rsi_ok and atr_ok):
            
            trade_active = True
            trade_num += 1
            entry_price = c
            stop_loss = c - (atr * ATR_SL_MULT)
            take_profit = c + (atr * ATR_TP_MULT)
            entry_time = candle["time"]
            entry_rsi = rsi
            entry_atr = atr
            entry_wick = wick_ratio
            entry_ema_f = ema_fast
            entry_ema_s = ema_slow
            
            print(f"  🚀 Trade {trade_num} ENTERED @ {entry_price:,.2f} (RSI: {rsi:.1f}, ATR: {atr:,.2f})")

    # Write to trades.csv
    if trades:
        fieldnames = ["Trade_Num", "Entry_Time", "Exit_Time", "Entry_Price", "Stop_Loss", "Take_Profit", 
                      "Exit_Price", "Exit_Reason", "Profit", "Balance_After", "RSI_At_Entry", "ATR_At_Entry", 
                      "Wick_Ratio_At_Entry", "EMA50_At_Entry", "EMA200_At_Entry"]
        with open(TRADES_FILE, mode="w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(trades)
        
        final_wr = (wins / trade_num * 100) if trade_num > 0 else 0.0
        print("\n" + "="*50)
        print(f"✅ SUCCESS! Generated {TRADES_FILE}")
        print(f"📊 Total Trades: {trade_num} | Wins: {wins} | Losses: {losses}")
        print(f"📈 Win Rate: {final_wr:.1f}% | Final Simulated Balance: ${balance:,.2f}")
        print("="*50)
    else:
        print("\n⚠️ No trades were generated. The strategy conditions may not have been met in this dataset, or the MIN_ATR/RSI filters filtered everything out.")

if __name__ == "__main__":
    main()
