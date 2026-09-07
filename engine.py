#!/usr/bin/env python3
import os
import csv
import json
import time
import sys
import requests
from collections import deque
from dotenv import load_dotenv
from trade_filter import should_take_trade

# ==========================================
# 🎛️ CONFIGURATION SWITCH
# Set to "FORWARD_TEST" to use Twelve Data and simulated balance
# Set to "LIVE" to use MetaTrader 5 and real execution
# ==========================================
TRADING_MODE = "FORWARD_TEST"

load_dotenv(dotenv_path="/opt/bitcoin/.env")

TWELVE_DATA_KEY = os.getenv("TWELVE_DATA_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# --- INSTRUMENT ---
SYMBOL_TD = "BTC/USD"
SYMBOL_MT5 = "BTCUSD"  # Verify this in MT5! Might be "BTCUSDm" for micro lots.

# --- STRATEGY PARAMETERS ---
LOOKBACK_PERIOD = 20
WICK_RATIO_TARGET = 0.15
EMA_FAST = 50
EMA_SLOW = 200
RSI_PERIOD = 14
ATR_PERIOD = 14
FLOOR_BUFFER_PCT = 0.0015

# Optimized Risk Management
ATR_SL_MULT = 2.0
ATR_TP_MULT = 4.0

# Filters
REQUIRE_VOLUME_CONFIRM = False
VOLUME_SPIKE_MULTIPLIER = 0.9
REQUIRE_TREND_CONFIRM = True
RSI_MIN = 40.0          # NEW: Prevent catching falling knives
RSI_MAX = 70.0          # NEW: Prevent buying overbought tops
MIN_ATR = 0.0         # NEW: Prevent trading in low volatility chop (BTC moves fast)

# Live Trading Parameters (Only used if TRADING_MODE == "LIVE")
# ⚠️ WARNING: Verify XM's BTC contract size before going live!
LOT_SIZE = 0.01
MAGIC_NUMBER = 987655  # Different from Gold's 987654

STATS_EVERY_N_CANDLES = 30
STARTING_BALANCE = 200.00  # UPDATED: Matches your real $200 account

LOG_FILE_PATH = "/opt/bitcoin/forward_test_log.csv"
TRADES_LOG_PATH = "/opt/bitcoin/trades.csv"
STATUS_FILE_PATH = "/opt/bitcoin/status.json"

# Conditional Imports
if TRADING_MODE == "LIVE":
    import MetaTrader5 as mt5
else:
    from twelvedata import TDClient


class BitcoinEngine:
    def __init__(self):
        self.lows = deque(maxlen=EMA_SLOW)
        self.highs = deque(maxlen=EMA_SLOW)
        self.closes = deque(maxlen=EMA_SLOW)
        self.volumes = deque(maxlen=EMA_SLOW)
        self.tr_list = deque(maxlen=ATR_PERIOD)
        self.rsi_gains = deque(maxlen=RSI_PERIOD)
        self.rsi_losses = deque(maxlen=RSI_PERIOD)

        self.prev_close = None
        self.rsi = None
        self.ema_fast = None
        self.ema_slow = None
        self.atr = None

        self.k_fast = 2 / (EMA_FAST + 1)
        self.k_slow = 2 / (EMA_SLOW + 1)

        self.current_minute = None
        self.tick_pool = []

        self.balance = STARTING_BALANCE
        self.trade_active = False
        self.entry_price = 0.0
        self.stop_loss = 0.0
        self.take_profit = 0.0
        self.total_trades = 0
        # Load previous trade count from CSV to prevent resetting to 1
        if os.path.isfile(TRADES_LOG_PATH):
            try:
                with open(TRADES_LOG_PATH, "r") as f:
                    self.total_trades = sum(1 for row in csv.reader(f)) - 1  # Subtract 1 for header
            except Exception: pass
        self.wins = 0
        self.losses = 0

        self.entry_time = None
        self.entry_rsi = None
        self.entry_atr = None
        self.entry_wick_ratio = None
        self.entry_ema_fast = None
        self.entry_ema_slow = None

        # Live mode specific
        self.active_ticket = None
        self.trade_active_live = False

        self.warmup_logged = False
        self.candles_evaluated = 0
        self.candles_warm = 0
        self.hit_tested_floor = 0
        self.hit_valid_rejection = 0
        self.hit_held_support = 0
        self.hit_volume_confirmed = 0
        self.hit_trend_confirmed = 0
        self.hit_all = 0

        if TRADING_MODE == "LIVE":
            if not mt5.initialize():
                print(f"❌ MT5 Initialize failed: {mt5.last_error()}")
                sys.exit(1)
            account = mt5.account_info()
            print(f"✅ Connected to MT5 | Account: {account.login} | Balance: {account.balance} {account.currency}")
            mt5.symbol_select(SYMBOL_MT5, True)
        else:
            self.load_history_from_csv()
            self.save_status()

    def load_history_from_csv(self):
        if not os.path.isfile(LOG_FILE_PATH):
            print("ℹ️ No existing log found. Starting fresh.")
            return
        print(f"📂 Loading history from {LOG_FILE_PATH}...")
        try:
            rows = []
            with open(LOG_FILE_PATH, mode="r") as f:
                reader = csv.DictReader(f)
                for row in reader: rows.append(row)
            if not rows: return
            recent = rows[-EMA_SLOW:] if len(rows) > EMA_SLOW else rows
            print(f"📊 Found {len(rows)} total rows → using last {len(recent)}")
            for row in recent:
                try:
                    low = float(row["Low"])
                    high = float(row.get("High", low))
                    close = float(row["Close"])
                    vol_str = row.get("Volume", "1")
                    volume = float(vol_str) if vol_str not in ("Calculating", "", None) else 1.0
                    self.lows.append(low); self.highs.append(high); self.closes.append(close); self.volumes.append(volume)
                    if self.prev_close is not None:
                        change = close - self.prev_close
                        self.rsi_gains.append(max(change, 0)); self.rsi_losses.append(max(-change, 0))
                        tr = max(high - low, abs(high - self.prev_close), abs(low - self.prev_close))
                        self.tr_list.append(tr)
                    self.prev_close = close
                except Exception: continue
            closes_list = list(self.closes)
            if len(closes_list) >= EMA_FAST:
                self.ema_fast = sum(closes_list[:EMA_FAST]) / EMA_FAST
                for price in closes_list[EMA_FAST:]: self.ema_fast = (price * self.k_fast) + (self.ema_fast * (1 - self.k_fast))
            if len(closes_list) >= EMA_SLOW:
                self.ema_slow = sum(closes_list[:EMA_SLOW]) / EMA_SLOW
                for price in closes_list[EMA_SLOW:]: self.ema_slow = (price * self.k_slow) + (self.ema_slow * (1 - self.k_slow))
            self.calculate_rsi(); self.calculate_atr()
            print(f"✅ Loaded {len(self.closes)} candles")
        except Exception as e: print(f"❌ Failed to load history: {e}")

    def calculate_rsi(self):
        if len(self.rsi_gains) < RSI_PERIOD: self.rsi = None; return
        avg_gain = sum(self.rsi_gains) / RSI_PERIOD
        avg_loss = sum(self.rsi_losses) / RSI_PERIOD
        self.rsi = 100.0 if avg_loss == 0 else 100 - (100 / (1 + (avg_gain / avg_loss)))

    def calculate_atr(self):
        if len(self.tr_list) < ATR_PERIOD: self.atr = None; return
        self.atr = sum(self.tr_list) / ATR_PERIOD

    def update_indicators(self, high, low, close):
        if self.ema_fast is None:
            if len(self.closes) >= EMA_FAST: self.ema_fast = sum(list(self.closes)[-EMA_FAST:]) / EMA_FAST
        else: self.ema_fast = (close * self.k_fast) + (self.ema_fast * (1 - self.k_fast))
        if self.ema_slow is None:
            if len(self.closes) >= EMA_SLOW: self.ema_slow = sum(list(self.closes)[-EMA_SLOW:]) / EMA_SLOW
        else: self.ema_slow = (close * self.k_slow) + (self.ema_slow * (1 - self.k_slow))
        if self.prev_close is not None:
            change = close - self.prev_close
            self.rsi_gains.append(max(change, 0)); self.rsi_losses.append(max(-change, 0)); self.calculate_rsi()
            tr = max(high - low, abs(high - self.prev_close), abs(low - self.prev_close))
            self.tr_list.append(tr); self.calculate_atr()
        self.prev_close = close

    def save_status(self):
        win_rate = (self.wins / self.total_trades * 100) if self.total_trades > 0 else 0.0
        # Always include trade fields, even when no active trade
        active_trade = self.trade_active or self.trade_active_live
        data = {"symbol": SYMBOL_MT5 if TRADING_MODE == "LIVE" else SYMBOL_TD,
                "equity": round(self.balance, 2), "total_trades": self.total_trades, "wins": self.wins, "losses": self.losses,
                "win_rate": round(win_rate, 1), "trade_active": active_trade, 
                "last_update": time.strftime("%Y-%m-%d %H:%M:%S"),
                "rsi": round(self.rsi, 1) if self.rsi else None, "ema_fast": round(self.ema_fast, 2) if self.ema_fast else None,
                "ema_slow": round(self.ema_slow, 2) if self.ema_slow else None, "atr": round(self.atr, 2) if self.atr else None,
                "entry_price": round(self.entry_price, 2) if active_trade and self.entry_price else None,
                "stop_loss": round(self.stop_loss, 2) if active_trade and self.stop_loss else None,
                "take_profit": round(self.take_profit, 2) if active_trade and self.take_profit else None,
                "funnel": {"candles_evaluated": self.candles_evaluated, "tested_floor": self.hit_tested_floor,
                           "valid_rejection": self.hit_valid_rejection, "held_support": self.hit_held_support,
                           "volume_confirmed": self.hit_volume_confirmed, "trend_confirmed": self.hit_trend_confirmed, "all_confirmed": self.hit_all}}
        try:
            with open(STATUS_FILE_PATH, "w") as f: json.dump(data, f, indent=2)
        except Exception as e: print(f"⚠️ Failed to write status.json: {e}")

    def send_telegram(self, text: str):
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID: return
        try: requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", json={"chat_id": str(TELEGRAM_CHAT_ID), "text": text, "parse_mode": "Markdown"}, timeout=4)
        except Exception as e: print(f"\n⚠️ Telegram failed: {e}")

    def log_candle(self, timestamp, o, h, l, c, ratio, tick_count, vol_ma, dynamic_floor, ema_f, ema_s, tested, rejected, held, vol_conf, trend_conf, rsi_val, atr_val):
        file_exists = os.path.isfile(LOG_FILE_PATH)
        with open(LOG_FILE_PATH, mode="a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["Timestamp", "Open", "High", "Low", "Close", "Wick_Ratio", "Volume", "Vol_MA", "Vol_Confirmed", "Dynamic_Floor", "EMA_50", "EMA_200", "Trend_Confirmed", "Tested_Floor", "Valid_Rejection", "Held_Floor", "RSI", "ATR"])
            if not file_exists: writer.writeheader()
            writer.writerow({"Timestamp": timestamp, "Open": f"{o:.2f}", "High": f"{h:.2f}", "Low": f"{l:.2f}", "Close": f"{c:.2f}",
                             "Wick_Ratio": f"{ratio:.1%}", "Volume": f"{tick_count:.0f}", "Vol_MA": f"{vol_ma:.1f}" if vol_ma else "Calculating",
                             "Vol_Confirmed": str(vol_conf), "Dynamic_Floor": f"{dynamic_floor:.2f}" if dynamic_floor else "Calculating",
                             "EMA_50": f"{ema_f:.2f}" if ema_f else "Calculating", "EMA_200": f"{ema_s:.2f}" if ema_s else "Calculating",
                             "Trend_Confirmed": str(trend_conf), "Tested_Floor": str(tested), "Valid_Rejection": str(rejected),
                             "Held_Floor": str(held), "RSI": f"{rsi_val:.1f}" if rsi_val else "Calculating", "ATR": f"{atr_val:.2f}" if atr_val else "Calculating"})

    def log_trade(self, exit_price, exit_reason, profit):
        file_exists = os.path.isfile(TRADES_LOG_PATH)
        with open(TRADES_LOG_PATH, mode="a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["Trade_Num", "Entry_Time", "Exit_Time", "Entry_Price", "Stop_Loss", "Take_Profit", "Exit_Price", "Exit_Reason", "Profit", "Balance_After", "RSI_At_Entry", "ATR_At_Entry", "Wick_Ratio_At_Entry", "EMA50_At_Entry", "EMA200_At_Entry"])
            if not file_exists: writer.writeheader()
            writer.writerow({"Trade_Num": self.total_trades, "Entry_Time": self.entry_time, "Exit_Time": time.strftime("%Y-%m-%d %H:%M:%S"),
                             "Entry_Price": f"{self.entry_price:,.2f}", "Stop_Loss": f"{self.stop_loss:,.2f}", "Take_Profit": f"{self.take_profit:,.2f}",
                             "Exit_Price": f"{exit_price:,.2f}", "Exit_Reason": exit_reason, "Profit": f"{profit:,.2f}", "Balance_After": f"{self.balance:,.2f}",
                             "RSI_At_Entry": f"{self.entry_rsi:.1f}" if self.entry_rsi else "", "ATR_At_Entry": f"{self.entry_atr:,.2f}" if self.entry_atr else "",
                             "Wick_Ratio_At_Entry": f"{self.entry_wick_ratio:.1%}" if self.entry_wick_ratio else "", "EMA50_At_Entry": f"{self.entry_ema_fast:,.2f}" if self.entry_ema_fast else "", "EMA200_At_Entry": f"{self.entry_ema_slow:,.2f}" if self.entry_ema_slow else ""})

    def evaluate_candle(self, o, h, l, c, tick_count):
        candle_range = h - l
        if candle_range <= 0: return
        body_bottom = min(o, c)
        lower_wick = body_bottom - l
        wick_ratio = lower_wick / candle_range
        valid_rejection = wick_ratio >= WICK_RATIO_TARGET

        dynamic_floor, volume_ma, tested_floor, held_support, volume_confirmed, trend_confirmed = None, None, False, False, False, False
        self.candles_evaluated += 1

        if len(self.closes) >= LOOKBACK_PERIOD:
            dynamic_floor = min(list(self.lows)[-LOOKBACK_PERIOD:])
            volume_ma = sum(list(self.volumes)[-LOOKBACK_PERIOD:]) / LOOKBACK_PERIOD
            tested_floor = l <= (dynamic_floor * (1 + FLOOR_BUFFER_PCT))
            held_support = c > dynamic_floor
            volume_confirmed = tick_count >= (volume_ma * VOLUME_SPIKE_MULTIPLIER) if volume_ma else True

        if self.ema_fast is not None and self.ema_slow is not None: trend_confirmed = self.ema_fast > self.ema_slow
        elif self.ema_fast is not None: trend_confirmed = c > self.ema_fast
        else: trend_confirmed = False

        if len(self.closes) < EMA_SLOW:
            if not self.warmup_logged or len(self.closes) % 30 == 0: print(f"⏳ Warming up... {len(self.closes)}/{EMA_SLOW}"); self.warmup_logged = True
        else:
            print(f"📊 Floor:${dynamic_floor:,.2f} | EMA50:${self.ema_fast:,.2f} EMA200:${self.ema_slow:,.2f} | RSI:{self.rsi} ATR:{self.atr:,.2f} | C:${c:,.2f}")
            print(f"   Tested:{tested_floor} | Rej:{valid_rejection} ({wick_ratio:.0%}) | Held:{held_support} | Vol:{volume_confirmed} | Trend:{trend_confirmed}")

        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        self.log_candle(ts, o, h, l, c, wick_ratio, tick_count, volume_ma, dynamic_floor, self.ema_fast, self.ema_slow, tested_floor, valid_rejection, held_support, volume_confirmed, trend_confirmed, self.rsi, self.atr)
        self.lows.append(l); self.highs.append(h); self.volumes.append(tick_count); self.closes.append(c)
        self.update_indicators(h, l, c); self.save_status()

        vol_ok = volume_confirmed if REQUIRE_VOLUME_CONFIRM else True
        trend_ok = trend_confirmed if REQUIRE_TREND_CONFIRM else True
        rsi_ok = (self.rsi is not None and RSI_MIN < self.rsi < RSI_MAX)
        atr_ok = (self.atr is not None and self.atr > MIN_ATR)


        #vol_ok = True
        #trend_ok = True
        #rsi_ok = True
        #atr_ok = True


        in_trade = self.trade_active or self.trade_active_live

        # --- DIAGNOSTIC: Increment funnel stats ---
        if dynamic_floor is not None:
            if tested_floor: self.hit_tested_floor += 1
            if valid_rejection: self.hit_valid_rejection += 1
            if held_support: self.hit_held_support += 1
            if volume_confirmed: self.hit_volume_confirmed += 1
            if trend_confirmed: self.hit_trend_confirmed += 1

        if (dynamic_floor is not None and self.ema_slow is not None and self.atr is not None and
                tested_floor and valid_rejection and held_support and vol_ok and trend_ok and rsi_ok and atr_ok and not in_trade):
            
            self.hit_all += 1

            # --- Pre-trade filter (Gatekeeper) ---
            allow, reason = should_take_trade(
                current_atr=self.atr,
                current_price=c,
                ema_fast=self.ema_fast,
                ema_slow=self.ema_slow
            )

            if not allow:
                msg = f"⛔ *BTC TRADE SKIPPED*\nReason: `{reason}`\nPrice: `${c:,.2f}` | RSI: `{self.rsi:.1f}` | ATR: `{self.atr:,.2f}`"
                self.send_telegram(msg)
                print(f"\n⛔ BTC Trade skipped → {reason}\n")
                return

            # --- Proceed with trade ---
            if TRADING_MODE == "LIVE":
                self.execute_live_trade(c, wick_ratio, ts, dynamic_floor)
            else:
                self.execute_simulated_trade(c, wick_ratio, ts, dynamic_floor)

    def execute_live_trade(self, c, wick_ratio, ts, dynamic_floor):
        print("\n🚨 ALL CONDITIONS MET! PREPARING LIVE ORDER...")
        sl_price = c - (self.atr * ATR_SL_MULT)
        tp_price = c + (self.atr * ATR_TP_MULT)
        symbol_info = mt5.symbol_info(SYMBOL_MT5)
        point = symbol_info.point
        sl_price = round(sl_price / point) * point
        tp_price = round(tp_price / point) * point
        tick = mt5.symbol_info_tick(SYMBOL_MT5)
        if tick is None: print("⚠️ Failed to get tick data"); return

        request = {"action": mt5.TRADE_ACTION_DEAL, "symbol": SYMBOL_MT5, "volume": LOT_SIZE, "type": mt5.ORDER_TYPE_BUY, "price": tick.ask,
                   "sl": sl_price, "tp": tp_price, "deviation": 50, "magic": MAGIC_NUMBER, "comment": "BTC Engine Live",
                   "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_FOK}
        print(f"   ➡️ Sending: BUY {LOT_SIZE} {SYMBOL_MT5} @ {tick.ask:,.2f} | SL: {sl_price:,.2f} | TP: {tp_price:,.2f}")
        
        result = mt5.order_send(request)
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            print(f"❌ Order failed: {result.retcode} - {result.comment}")
            self.send_telegram(f"❌ *BTC ORDER FAILED*\nCode: {result.retcode}\nMsg: {result.comment}")
        else:
            self.total_trades += 1
            self.active_ticket = result.order
            self.trade_active_live = True
            self.entry_price = tick.ask; self.stop_loss = sl_price; self.take_profit = tp_price
            self.entry_time = ts; self.entry_rsi = self.rsi; self.entry_atr = self.atr; self.entry_wick_ratio = wick_ratio
            self.entry_ema_fast = self.ema_fast; self.entry_ema_slow = self.ema_slow
            
            # Log entry to trades.csv immediately
            #self.log_trade(tick.ask, "OPEN", 0.0) 
            
            print(f"✅ ORDER SUCCESS! Ticket: {self.active_ticket}")
            self.send_telegram(f"🚨 *LIVE BTC BUY EXECUTED*\n🎫 Ticket: `{self.active_ticket}`\n💰 Entry: `${tick.ask:,.2f}`\n🛑 SL: `${sl_price:,.2f}`\n🎯 TP: `${tp_price:,.2f}`")

    def execute_simulated_trade(self, c, wick_ratio, ts, dynamic_floor):
        self.trade_active = True; self.total_trades += 1
        self.entry_price = c; self.stop_loss = c - (self.atr * ATR_SL_MULT); self.take_profit = c + (self.atr * ATR_TP_MULT)
        self.entry_time = ts; self.entry_rsi = self.rsi; self.entry_atr = self.atr; self.entry_wick_ratio = wick_ratio
        self.entry_ema_fast = self.ema_fast; self.entry_ema_slow = self.ema_slow
        msg = f"🚨 *BTC BUY SETUP #{self.total_trades}*\n💰 Entry: `${self.entry_price:,.2f}`\n📊 RSI: `{self.rsi:.1f}` | ATR: `${self.atr:,.2f}`\n🛑 SL: `${self.stop_loss:,.2f}`\n🎯 TP: `${self.take_profit:,.2f}`"
        self.send_telegram(msg); print(f"\n🤖 Alert sent → Trade #{self.total_trades}\n"); self.save_status()

    def check_position(self, price: float):
        if not self.trade_active: return
        
        # Calculate raw price difference
        raw_profit = price - self.entry_price
        raw_loss = self.entry_price - price
        
        # Apply the 0.01 lot size to get actual dollar PnL
        actual_profit = raw_profit * LOT_SIZE
        actual_loss = raw_loss * LOT_SIZE

        if price >= self.take_profit:
            self.balance += actual_profit
            self.wins += 1
            self.trade_active = False
            self.log_trade(exit_price=price, exit_reason="TP", profit=actual_profit)
            self.send_telegram(f"✅ *BTC TP HIT*\nExit: `${price:,.2f}` (+${actual_profit:,.2f})\nEquity: `${self.balance:,.2f}`")
            self.save_status()
        elif price <= self.stop_loss:
            self.balance -= actual_loss
            self.losses += 1
            self.trade_active = False
            self.log_trade(exit_price=price, exit_reason="SL", profit=-actual_loss)
            self.send_telegram(f"❌ *BTC SL HIT*\nExit: `${price:,.2f}` (-${actual_loss:,.2f})\nEquity: `${self.balance:,.2f}`")
            self.save_status()

    def check_live_exits(self):
        """Checks MT5 history to see if our active live trade has closed."""
        if not self.trade_active_live or not self.active_ticket:
            return
        
        history = mt5.history_deals_get(ticket=self.active_ticket)
        if history:
            for deal in history:
                if deal.entry == mt5.DEAL_ENTRY_OUT: # 1 = entry out (close)
                    profit = deal.profit
                    exit_price = deal.price
                    reason = "TP" if profit > 0 else "SL"
                    
                    if profit > 0: self.wins += 1
                    else: self.losses += 1
                    
                    self.trade_active_live = False
                    self.active_ticket = None
                    
                    self.log_trade(exit_price=exit_price, exit_reason=reason, profit=profit)
                    self.send_telegram(f"{'✅' if profit > 0 else '❌'} *BTC {reason} HIT*\nExit: `${exit_price:,.2f}`\nProfit: `${profit:,.2f}`")
                    self.save_status()
                    break

    def aggregate_tick(self, price: float):
        minute_now = int(time.time() // 60)
        if self.current_minute is None: self.current_minute = minute_now
        if minute_now != self.current_minute:
            if self.tick_pool:
                o, h, l, c = self.tick_pool[0], max(self.tick_pool), min(self.tick_pool), self.tick_pool[-1]
                self.evaluate_candle(o, h, l, c, len(self.tick_pool))
            self.tick_pool.clear(); self.current_minute = minute_now
        self.tick_pool.append(price)

    def on_event(self, event):
        if event.get("event") != "price": return
        try:
            price = float(event["price"])
            self.check_position(price); self.aggregate_tick(price)
            print(f"⏱️ ${price:,.2f} | ticks: {len(self.tick_pool)}   ", end="\r"); sys.stdout.flush()
        except Exception: return

    def run_live(self):
        print(f"🚀 Bitcoin Engine LIVE starting for {SYMBOL_MT5}...")
        candles_fetched = 0
        while True:
            try:
                rates = mt5.copy_rates_from_pos(SYMBOL_MT5, mt5.TIMEFRAME_M1, 0, 250)
                if rates is None or len(rates) == 0: time.sleep(5); continue
                last_candle = rates[-2]
                o, h, l, c, vol = float(last_candle['open']), float(last_candle['high']), float(last_candle['low']), float(last_candle['close']), int(last_candle['tick_volume'])
                self.evaluate_candle(o, h, l, c, vol)
                self.check_live_exits() # Check if MT5 closed our trade
                if candles_fetched % 10 == 0: print(f"💓 Heartbeat: Processed candle @ {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(last_candle['time']))} | Close: {c:,.2f}")
                candles_fetched += 1
                for _ in range(12): time.sleep(5)
            except KeyboardInterrupt: print("\n⚙️ Shutting down..."); mt5.shutdown(); break
            except Exception as e: print(f"\n❌ Error: {e}"); time.sleep(10)

    def run_forward_test(self):
        print("🚀 Bitcoin Engine FORWARD TEST starting...")
        if not TWELVE_DATA_KEY: print("❌ TWELVE_DATA_API_KEY missing"); sys.exit(1)
        while True:
            try:
                td = TDClient(apikey=TWELVE_DATA_KEY)
                ws = td.websocket(on_event=self.on_event)
                ws.subscribe([SYMBOL_TD]); ws.connect(); print(f"📡 Connected to Twelve Data ({SYMBOL_TD})\n")
                while True:
                    try: ws.heartbeat(); time.sleep(15)
                    except Exception as e: print(f"\n⚠️ Connection issue: {e}"); print("🔄 Reconnecting in 10s..."); time.sleep(10); break
            except KeyboardInterrupt: print("\n⚙️ Shutting down..."); break
            except Exception as e: print(f"\n❌ Error: {e}"); print("🔄 Restarting in 15s..."); time.sleep(15)

    def run(self):
        if TRADING_MODE == "LIVE": self.run_live()
        else: self.run_forward_test()

if __name__ == "__main__":
    engine = BitcoinEngine()
    engine.run()
