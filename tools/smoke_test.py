#!/usr/bin/env python3
"""
Smoke test for the engine's regime gates, bidirectional (Buy/Sell) execution,
daily loss circuit breaker, and trades.csv schema migration.

Runs BitcoinEngine.evaluate_candle() over synthetic 5-minute candles in temp
directories (no /opt/bitcoin, no network, no Telegram, no real API keys needed).

Scenarios:
  A) Uptrend + rejection dip at 20-bar floor       -> BUY trade MUST trigger & close with TP
  B) Established decline + floor rejection dip     -> BUY trade MUST be blocked
  C) Downtrend + ceiling rejection dip             -> SELL trade MUST trigger & close with TP
  D) Daily loss circuit breaker                    -> MUST halt after MAX_DAILY_LOSSES (3)
  E) Restart from log                             -> EMA50 history seeds properly
  F) trades.csv schema drift (gold 2026-09-10 incident) -> engine MUST auto-migrate and
     restore correct risk-gate counting for SELL trades (incl. legacy comma rows)
  G) stale-feed guard (gold 2026-09-10 silent WebSocket stall) -> MUST detect a quiet
     feed and rate-limit Telegram alerts (BTC is 24/7: NO quiet hours)
  H) MT5 sidecar feed file (DATA_SOURCE=MT5) -> engine MUST read the sidecar's
     JSON file, evaluate each closed candle exactly once (no re-log after
     restart), and default to TWELVEDATA
  I) replay_lib walk direction -> SELL bar extremes MUST mirror BUY (gold's
     2026-09-15 review found its replay had them inverted, so shorts silently
     fell back to their actual outcome and the tool validated itself), the BE
     ratchet MUST arm only at/above its trigger, and a walk MUST NOT resolve to
     TP when only the stop was touched inside its horizon
  J) handoff_check tolerance policy -> the docs freshness gate MUST NOT cry wolf
     (one new bar, one closed trade or an open-trade change is normal drift) and
     MUST still go STALE when genuinely behind (> 5 trades, > 48 h), when
     outcomes change without a new trade, or when the snapshot is newer than
     the data
  K) XM quote + contract-spec logger (tools/mt5_quotes.py) -> MUST stay read-only
     (AST: no trading API named; the fake terminal records any trading call),
     leak nothing identifying (login/name/server/balance/Windows paths) into the
     public repo, learn the broker SERVER-time offset only from fresh ticks (a
     frozen tick must not move it), keep the candle series continuous in UTC across
     a server DST change, heal gaps and restarts without duplicates, write NOQUOTE/
     BADQUOTE/STALE rows instead of silent holes, never emit CRLF or misaligned rows,
     exit 2 (systemd restart) after 15 quiet minutes
  L) xm_quote_report (the logger's data) -> MUST parse the real writer's files and
     survive a torn line, count complete days/weekends against the Stage B-i exit,
     keep STALE/NOOFFSET/NOQUOTE rows out of every spread statistic, price a trade at
     (entry spread + exit spread) / 2, and CATCH candles stamped an hour off

Usage: python3 tools/smoke_test.py
"""
import os
import sys
import json
import csv
import shutil
import tempfile
import time
import types
from datetime import datetime, timezone, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)      # replay_lib lives next to this file

# Stub external dependencies
for name in ("requests", "dotenv", "twelvedata"):
    if name not in sys.modules:
        mod = types.ModuleType(name)
        if name == "requests":
            mod.post = lambda *a, **k: None
        if name == "dotenv":
            mod.load_dotenv = lambda *a, **k: None
        if name == "twelvedata":
            mod.TDClient = object
        sys.modules[name] = mod

import engine  # noqa: E402
import trade_filter  # noqa: E402

FAILURES = []


def check(label, cond, extra=""):
    print(f"  [{'OK' if cond else 'FAIL'}] {label}" + (f"  ({extra})" if extra else ""))
    if not cond:
        FAILURES.append(label)


def candles_uptrend(n, start=80000.0):
    """Oscillating uptrend: RSI ~62, ATR ~$95 (~0.12%), EMA50 rising."""
    out, p = [], start
    for i in range(n):
        d = (60.0, 60.0, -55.0, 60.0, -55.0)[i % 5]
        o = p
        c = p + d
        out.append((o, max(o, c) + 18.0, min(o, c) - 18.0, c))
        p = c
    return out


def candles_decline(n, start=84000.0):
    """Oscillating decline: RSI ~38, EMA50 falling."""
    out, p = [], start
    for i in range(n):
        d = (-60.0, -60.0, 55.0, -60.0, 55.0)[i % 5]
        o = p
        c = p + d
        out.append((o, max(o, c) + 18.0, min(o, c) - 18.0, c))
        p = c
    return out


def run_candles(eng, candles, ts_start):
    ts = ts_start
    for (o, h, l, c) in candles:
        eng.evaluate_candle(o, h, l, c, tick_count=300)
        eng.check_position(c)
        ts += timedelta(minutes=5)


def rejection_dip_buy(eng):
    """Under-cuts 20-bar floor, closes above it, long lower wick."""
    floor = min(list(eng.lows)[-engine.LOOKBACK_PERIOD:])
    p = list(eng.closes)[-1]
    o = p
    c = p - 24.0
    low = floor - 36.0
    high = p + 18.0
    return (o, high, low, c)


def rejection_dip_sell(eng):
    """Tests 20-bar ceiling, closes below it, long upper wick."""
    ceil = max(list(eng.highs)[-engine.LOOKBACK_PERIOD:])
    p = list(eng.closes)[-1]
    o = p
    c = p - 12.0
    high = ceil + 36.0
    low = p - 30.0
    return (o, high, low, c)


# --- Scenario A ---
print("Scenario A: uptrend + floor rejection -> expect BUY trade")
tmp_a = tempfile.mkdtemp(prefix="btc_smoke_a_")
engine.LOG_FILE_PATH = os.path.join(tmp_a, "forward_test_log.csv")
engine.STATUS_FILE_PATH = os.path.join(tmp_a, "status.json")
engine.TRADES_LOG_PATH = os.path.join(tmp_a, "trades.csv")
trade_filter.TRADES_LOG = engine.TRADES_LOG_PATH
trade_filter.SKIP_LOG = os.path.join(tmp_a, "skipped_trades.csv")
trade_filter.is_in_blackout = lambda now=None: (False, "")

eng_a = engine.BitcoinEngine()
run_candles(eng_a, candles_uptrend(240), datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc))
dip_a = rejection_dip_buy(eng_a)
run_candles(eng_a, [dip_a], datetime(2026, 1, 1, 4, 0, tzinfo=timezone.utc))
check("A: BUY trade triggered", eng_a.trade_active and eng_a.trade_type == "BUY",
      f"trade_active={eng_a.trade_active} type={eng_a.trade_type} num={eng_a.current_trade_num}")

# Drive to TP (TP = entry + 4*ATR, ATR ~$110 -> need ~$450+ rise)
p_now = list(eng_a.closes)[-1]
up = [(p_now + i * 60, p_now + i * 60 + 30, p_now + i * 60 - 12, p_now + i * 60 + 48) for i in range(1, 12)]
run_candles(eng_a, up, datetime(2026, 1, 1, 4, 5, tzinfo=timezone.utc))
check("A: BUY trade closed with TP", not eng_a.trade_active and eng_a.wins == 1, f"wins={eng_a.wins} losses={eng_a.losses}")
shutil.rmtree(tmp_a, ignore_errors=True)


# --- Scenario B ---
print("\nScenario B: decline + floor rejection dip -> expect NO buy trade")
tmp_b = tempfile.mkdtemp(prefix="btc_smoke_b_")
engine.LOG_FILE_PATH = os.path.join(tmp_b, "forward_test_log.csv")
engine.STATUS_FILE_PATH = os.path.join(tmp_b, "status.json")
engine.TRADES_LOG_PATH = os.path.join(tmp_b, "trades.csv")
trade_filter.TRADES_LOG = engine.TRADES_LOG_PATH
trade_filter.SKIP_LOG = os.path.join(tmp_b, "skipped_trades.csv")
trade_filter.is_in_blackout = lambda now=None: (False, "")

eng_b = engine.BitcoinEngine()
run_candles(eng_b, candles_decline(240), datetime(2026, 2, 1, 0, 0, tzinfo=timezone.utc))
dip_b = rejection_dip_buy(eng_b)
run_candles(eng_b, [dip_b], datetime(2026, 2, 1, 4, 0, tzinfo=timezone.utc))
check("B: no BUY trade in decline", not eng_b.trade_active,
      f"trend_gate=ema50>{'ema200' if eng_b.ema_fast > eng_b.ema_slow else 'CROSSED'}")
shutil.rmtree(tmp_b, ignore_errors=True)


# --- Scenario C ---
print("\nScenario C: downtrend + ceiling rejection -> expect SELL trade")
tmp_c = tempfile.mkdtemp(prefix="btc_smoke_c_")
engine.LOG_FILE_PATH = os.path.join(tmp_c, "forward_test_log.csv")
engine.STATUS_FILE_PATH = os.path.join(tmp_c, "status.json")
engine.TRADES_LOG_PATH = os.path.join(tmp_c, "trades.csv")
trade_filter.TRADES_LOG = engine.TRADES_LOG_PATH
trade_filter.SKIP_LOG = os.path.join(tmp_c, "skipped_trades.csv")
trade_filter.is_in_blackout = lambda now=None: (False, "")

eng_c = engine.BitcoinEngine()
run_candles(eng_c, candles_decline(240, 84000.0), datetime(2026, 3, 1, 0, 0, tzinfo=timezone.utc))
dip_c = rejection_dip_sell(eng_c)
run_candles(eng_c, [dip_c], datetime(2026, 3, 1, 4, 0, tzinfo=timezone.utc))
check("C: SELL trade triggered", eng_c.trade_active and eng_c.trade_type == "SELL",
      f"trade_active={eng_c.trade_active} type={eng_c.trade_type}")

# Drive to SELL TP (downward price)
p_now = list(eng_c.closes)[-1]
down = [(p_now - i * 60, p_now - i * 60 + 12, p_now - i * 60 - 48, p_now - i * 60 - 30) for i in range(1, 12)]
run_candles(eng_c, down, datetime(2026, 3, 1, 4, 5, tzinfo=timezone.utc))
check("C: SELL trade closed with TP", not eng_c.trade_active and eng_c.wins == 1, f"wins={eng_c.wins}")


# --- Scenario D ---
print("\nScenario D: daily loss circuit breaker -> halts trading after 3 SLs")
trades_sim = [
    {"Trade_Num": "1", "Trade_Type": "BUY", "Entry_Time": "2026-09-10 01:00:00", "Exit_Time": "2026-09-10 01:10:00", "Exit_Reason": "SL", "Profit": "-3.00"},
    {"Trade_Num": "2", "Trade_Type": "BUY", "Entry_Time": "2026-09-10 02:00:00", "Exit_Time": "2026-09-10 02:10:00", "Exit_Reason": "SL", "Profit": "-3.00"},
    {"Trade_Num": "3", "Trade_Type": "SELL", "Entry_Time": "2026-09-10 03:00:00", "Exit_Time": "2026-09-10 03:10:00", "Exit_Reason": "SL", "Profit": "-3.00"},
]
sl_count = trade_filter.get_daily_sl_count(trades_sim, datetime(2026, 9, 10, 5, 0, tzinfo=timezone.utc))
halted, halt_reason = trade_filter.check_daily_loss_limit(trades_sim, datetime(2026, 9, 10, 5, 0, tzinfo=timezone.utc))
check("D: daily SL count equals 3", sl_count == 3, f"count={sl_count}")
check("D: circuit breaker triggered", halted and "Daily Loss Limit Reached" in halt_reason, f"reason={halt_reason}")

# A busy UTC day must not fall out of the window the breaker reads: gold hit 62
# trades/day, and with a 30-row window the day's SLs become invisible.
busy_day = [{"Trade_Num": str(i), "Trade_Type": "BUY",
             "Entry_Time": f"2026-09-10 00:{i:02d}:00", "Exit_Time": f"2026-09-10 01:{i:02d}:00",
             "Exit_Reason": "SL", "Profit": "-1.00"}
            for i in range(1, 41)]
now_d = datetime(2026, 9, 10, 5, 0, tzinfo=timezone.utc)
check("D: busy-day window is wider than the streak lookback",
      trade_filter.DAY_WINDOW >= 100 and trade_filter.LOOKBACK == 30,
      f"DAY_WINDOW={trade_filter.DAY_WINDOW} LOOKBACK={trade_filter.LOOKBACK}")
check("D: a 40-SL day is fully visible to the breaker",
      trade_filter.get_daily_sl_count(busy_day, now_d) == 40
      and trade_filter.get_daily_sl_count(busy_day[-trade_filter.LOOKBACK:], now_d) >= 3,
      f"wide={trade_filter.get_daily_sl_count(busy_day, now_d)} "
      f"narrow={trade_filter.get_daily_sl_count(busy_day[-trade_filter.LOOKBACK:], now_d)}")


# --- Scenario E ---
print("\nScenario E: restart state persistence")
eng_e = engine.BitcoinEngine()
check("E: EMA50 history seeded from CSV", len(eng_e.ema50_history) >= engine.EMA_SLOPE_LOOKBACK, f"{len(eng_e.ema50_history)} loaded")
check("E: trade stats loaded from trades.csv", eng_e.wins == 1 and eng_e.losses == 0)

shutil.rmtree(tmp_c, ignore_errors=True)


# --- Scenario F ---
print("\nScenario F: trades.csv schema drift (pre-SELL header + SELL row) -> auto-migrate")
OLD_HEADER = ["Trade_Num", "Entry_Time", "Exit_Time", "Entry_Price", "Stop_Loss", "Take_Profit",
              "Exit_Price", "Exit_Reason", "Profit", "Balance_After", "RSI_At_Entry",
              "ATR_At_Entry", "Wick_Ratio_At_Entry", "EMA50_At_Entry", "EMA200_At_Entry"]
tmp_f = tempfile.mkdtemp(prefix="btc_smoke_f_")
engine.LOG_FILE_PATH = os.path.join(tmp_f, "forward_test_log.csv")
engine.STATUS_FILE_PATH = os.path.join(tmp_f, "status.json")
engine.TRADES_LOG_PATH = os.path.join(tmp_f, "trades.csv")
trade_filter.TRADES_LOG = engine.TRADES_LOG_PATH
trade_filter.SKIP_LOG = os.path.join(tmp_f, "skipped_trades.csv")

with open(engine.TRADES_LOG_PATH, "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(OLD_HEADER)
    # two old-schema BUY rows (15 fields, legacy comma-formatted prices)
    w.writerow(["1", "2026-09-09 01:00:00", "2026-09-09 01:05:00", "80,000.00", "79,900.00", "80,200.00",
                "80,200.00", "TP", "2.00", "202.00", "55.0", "35.00", "50.0%", "79,950.00", "79,900.00"])
    w.writerow(["2", "2026-09-09 02:00:00", "2026-09-09 02:05:00", "80,100.00", "80,000.00", "80,300.00",
                "80,000.00", "SL", "-1.00", "201.00", "50.0", "35.50", "45.0%", "80,050.00", "80,000.00"])
    # the incident: 16-field SELL row appended under the 15-field header
    w.writerow(["3", "SELL", "2026-09-10 00:09:00", "2026-09-10 00:11:04", "79900.00", "80000.00",
                "79700.00", "80005.00", "SL", "-1.05", "199.95", "45.0", "35.00", "55.6%", "79950.00", "80000.00"])

# 1) demonstrate the incident: with drift, the SELL SL is invisible to the risk gates
drifted = trade_filter.load_recent_trades()
cnt_before = trade_filter.get_daily_sl_count(drifted, datetime(2026, 9, 10, 1, 0, tzinfo=timezone.utc))
check("F: drifted file misses the SELL SL (bug reproduced)", cnt_before == 0, f"daily_sls={cnt_before}")

# 2) engine start must auto-migrate and resync stats
eng_f = engine.BitcoinEngine()
with open(engine.TRADES_LOG_PATH, newline="") as f:
    rdr = csv.DictReader(f)
    rows_f = list(rdr)
    hdr_f = rdr.fieldnames
check("F: header migrated to 16-field schema", hdr_f == engine.TRADES_FIELDNAMES, f"{hdr_f}")
check("F: old rows backfilled as BUY", all(r["Trade_Type"] == "BUY" for r in rows_f[:2]))
check("F: legacy comma prices survive migration byte-for-byte",
      rows_f[0]["Entry_Price"] == "80,000.00" and rows_f[1]["EMA50_At_Entry"] == "80,050.00")
check("F: SELL row aligned (Exit_Reason=SL, Profit=-1.05)",
      rows_f[2]["Trade_Type"] == "SELL" and rows_f[2]["Exit_Reason"] == "SL"
      and rows_f[2]["Profit"] == "-1.05" and rows_f[2]["Balance_After"] == "199.95")
check("F: engine stats resynced (1W/2L, next=#4)",
      eng_f.wins == 1 and eng_f.losses == 2 and eng_f.next_trade_num == 4 and abs(eng_f.balance - 199.95) < 0.01,
      f"{eng_f.wins}W/{eng_f.losses}L next=#{eng_f.next_trade_num} bal={eng_f.balance}")

# 3) risk gates see the SELL SL now
migrated = trade_filter.load_recent_trades()
cnt_after = trade_filter.get_daily_sl_count(migrated, datetime(2026, 9, 10, 1, 0, tzinfo=timezone.utc))
check("F: daily SL count sees the SELL SL after migration", cnt_after == 1, f"daily_sls={cnt_after}")

# 4) migration is idempotent and keeps a backup
check("F: re-migration is a no-op", engine.migrate_trades_csv(engine.TRADES_LOG_PATH) is False)
check("F: backup kept", os.path.exists(engine.TRADES_LOG_PATH + ".bak-pre-migration"))
shutil.rmtree(tmp_f, ignore_errors=True)


# --- Scenario G ---
print("\nScenario G: stale-feed guard (silent WebSocket stall, no quiet hours on BTC)")
tmp_g = tempfile.mkdtemp(prefix="btc_smoke_g_")
engine.LOG_FILE_PATH = os.path.join(tmp_g, "forward_test_log.csv")
engine.STATUS_FILE_PATH = os.path.join(tmp_g, "status.json")
engine.TRADES_LOG_PATH = os.path.join(tmp_g, "trades.csv")
trade_filter.TRADES_LOG = engine.TRADES_LOG_PATH
trade_filter.SKIP_LOG = os.path.join(tmp_g, "skipped_trades.csv")

eng_g = engine.BitcoinEngine()

# fresh feed -> not stale
eng_g._last_price_mono = time.monotonic()
check("G: fresh feed not stale", eng_g.feed_stale_seconds() < 1.0, f"{eng_g.feed_stale_seconds():.2f}s")

# 11 min without ticks -> stale
eng_g._last_price_mono = time.monotonic() - (engine.STALE_FEED_SECONDS + 60)
stale = eng_g.feed_stale_seconds()
check("G: 11-min gap detected as stale", stale > engine.STALE_FEED_SECONDS, f"{stale:.0f}s")

# BTC trades 24/7: NOTHING is a quiet hour (gold's weekend/break suppression
# must never apply here - a silent BTC feed is always an incident)
check("G: Saturday 12:00 UTC is NOT quiet (BTC trades weekends)",
      not engine.is_market_quiet(datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)))
check("G: Friday 23:00 UTC is NOT quiet (no daily break on BTC)",
      not engine.is_market_quiet(datetime(2026, 9, 11, 23, 0, tzinfo=timezone.utc)))
check("G: Thursday 01:30 UTC is NOT quiet",
      not engine.is_market_quiet(datetime(2026, 9, 10, 1, 30, tzinfo=timezone.utc)))
check("G: Thursday 12:00 UTC is NOT quiet",
      not engine.is_market_quiet(datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)))

# alert rate-limit: first alert fires, immediate second is suppressed
first = eng_g.maybe_alert_stale_feed(stale)
second = eng_g.maybe_alert_stale_feed(stale)
check("G: stale alert fires once, then rate-limited", first is True and second is False)
shutil.rmtree(tmp_g, ignore_errors=True)


# --- Scenario H ---
print("\nScenario H: MT5 sidecar feed file (DATA_SOURCE=MT5)")
tmp_h = tempfile.mkdtemp(prefix="btc_smoke_h_")
engine.LOG_FILE_PATH = os.path.join(tmp_h, "forward_test_log.csv")
engine.STATUS_FILE_PATH = os.path.join(tmp_h, "status.json")
engine.TRADES_LOG_PATH = os.path.join(tmp_h, "trades.csv")
engine.MT5_FEED_FILE = os.path.join(tmp_h, "mt5_last_candle.json")
trade_filter.TRADES_LOG = engine.TRADES_LOG_PATH
trade_filter.SKIP_LOG = os.path.join(tmp_h, "skipped_trades.csv")

check("H: default data source stays TWELVEDATA", engine.DATA_SOURCE == "TWELVEDATA",
      f"DATA_SOURCE={engine.DATA_SOURCE}")

eng_h = engine.BitcoinEngine()
check("H: missing feed file -> None", eng_h.read_mt5_feed() is None)

# The sidecar must convert broker-server timestamps to UTC using a fresh tick.
# Import its pure helper with a stub MT5 module (Linux has no MT5 package).
import importlib.util
fake_mt5 = types.ModuleType("MetaTrader5")
fake_mt5.TIMEFRAME_M1 = 1
fake_mt5.TIMEFRAME_M5 = 5
fake_mt5.TIMEFRAME_M15 = 15
sys.modules["MetaTrader5"] = fake_mt5
feed_spec = importlib.util.spec_from_file_location("mt5_feed_under_test", os.path.join(HERE, "mt5_feed.py"))
feed_mod = importlib.util.module_from_spec(feed_spec)
feed_spec.loader.exec_module(feed_mod)
check("H: fresh +3h tick estimates UTC offset", feed_mod.estimate_server_offset(100000 + 10800 - 1, 100000) == 10800)
check("H: stale tick cannot estimate offset", feed_mod.estimate_server_offset(100000 + 10800 - 1200, 100000) is None)

# sidecar publishes the latest closed candle with a UTC ts; engine reads + normalizes it
feed1 = {"ts": 2000, "server_ts": 12800, "server_offset_s": 10800, "open": 80000.0, "high": 80010.0, "low": 79990.0,
         "close": 80005.0, "tick_volume": 120, "updated_at": "2026-09-10 05:01:03"}
with open(engine.MT5_FEED_FILE, "w") as f:
    json.dump(feed1, f)
r1 = eng_h.read_mt5_feed()
check("H: feed file normalized to rate shape",
      r1 is not None and r1[0]["time"] == 2000 and r1[0]["open"] == 80000.0 and r1[0]["tick_volume"] == 120)
check("H: first closed candle accepted",
      (lambda c: c is not None and c[0] == 2000 and c[1] == 80000.0 and c[5] == 120)(eng_h.mt5_next_candle(r1, 0)))
check("H: same candle NOT re-evaluated (restart dedup)", eng_h.mt5_next_candle(r1, 2000) is None)

with open(engine.MT5_FEED_FILE, "w") as f:
    json.dump({"ts": 2300, "open": 80005.0, "high": 80020.0, "low": 80000.0,
               "close": 80015.0, "tick_volume": 340, "updated_at": "2026-09-10 05:06:03"}, f)
c2 = eng_h.mt5_next_candle(eng_h.read_mt5_feed(), 2000)
check("H: next bar's candle accepted", c2 is not None and c2[0] == 2300 and c2[5] == 340)

with open(engine.MT5_FEED_FILE, "w") as f:
    f.write("corrupted")
check("H: corrupt feed file -> None (no crash)", eng_h.read_mt5_feed() is None)
check("H: no rates -> None", engine.latest_closed_candle_ts(None) is None)
check("H: empty rates -> None", engine.latest_closed_candle_ts([]) is None)
shutil.rmtree(tmp_h, ignore_errors=True)

# --- Scenario I ---
print("\nScenario I: replay_lib walk direction, ratchet trigger and horizon")
import replay_lib as R  # noqa: E402

side_dt = datetime(2026, 9, 8, 0, 0)
ENTRY, ATR = 80000.0, 100.0        # 1R = 200, TP = 80000 +- 400 at 2x/4x


def bar(i, o, h, l, c):
    return dict(dt=side_dt + timedelta(minutes=5 * i), o=o, h=h, l=l, c=c)


# SELL: price falls 4xATR -> TP is hit and the stop (above entry) is not
sell_tp = [bar(1, 79620, 79650, 79560, 79580), bar(2, 79580, 79600, 79550, 79560)]
out, r, held, _ = R.walk(ENTRY, "SELL", ATR, sell_tp)
check("I: SELL walk detects TP when price falls to the target", out == "TP", f"got {out}")
check("I: SELL TP pays exactly the planned 2R", abs(r - 2.0) < 1e-9, f"R={r}")

# SELL: price rises 2xATR -> SL is hit even though the bar's HIGH is the adverse side
sell_sl = [bar(1, 80100, 80300, 80090, 80290)]
out, r, held, _ = R.walk(ENTRY, "SELL", ATR, sell_sl)
check("I: SELL walk detects SL on a rising bar (high is the adverse extreme)", out == "SL", f"got {out}")
check("I: SELL SL costs exactly 1R", abs(r + 1.0) < 1e-9, f"R={r}")

# mirror symmetry: BUY on the mirrored path must give the mirrored outcome
buy_tp = [bar(1, 80380, 80440, 80350, 80420), bar(2, 80420, 80450, 80400, 80440)]
out_b, r_b, _, _ = R.walk(ENTRY, "BUY", ATR, buy_tp)
check("I: BUY walk mirrors the SELL walk (both hit TP)", out_b == "TP" and out == "SL",
      f"buy={out_b} (sell mirror of the same bars was {out})")

# a bar that touches BOTH levels resolves to the stop (conservative tie-break)
both = [bar(1, 80000, 80450, 79750, 80300)]
out, _, _, _ = R.walk(ENTRY, "BUY", ATR, both)
check("I: bar spanning both levels resolves to the STOP (conservative)", out == "SL", f"got {out}")

# BE ratchet: must NOT arm below the trigger, MUST arm at/above it
quiet = [bar(1, 80000, 80120, 79990, 80050), bar(2, 80050, 80060, 79780, 79800)]
out, r, _, _ = R.walk(ENTRY, "BUY", ATR, quiet, be_trigger=0.75)
check("I: BE ratchet does NOT arm below its trigger (+0.60R < +0.75R)", out == "SL", f"got {out}")
armed = [bar(1, 80150, 80260, 80100, 80250), bar(2, 80250, 80255, 79990, 80010)]
out, r, _, _ = R.walk(ENTRY, "BUY", ATR, armed, be_trigger=0.75)
check("I: BE ratchet arms at +0.75R and exits at breakeven", out == "BE" and abs(r) < 1e-9,
      f"got {out} R={r}")

# horizon: a trade that never reaches TP before the cap must not be scored as a win
slow = [bar(i, 80000 + i * 5, 80010 + i * 5, 79990 + i * 5, 80000 + i * 5) for i in range(1, 40)]
out, r, held, _ = R.walk(ENTRY, "BUY", ATR, slow, horizon_min=60, start_dt=side_dt)
check("I: horizon ends flat -> TIME marked to market, never a fabricated TP",
      out == "TIME" and held == 12, f"got {out} after {held} bars")

# cascade: one position at a time + cooldown (two signals 10 min apart -> one taken)
slow_tp = [bar(1, 79700, 79720, 79680, 79700), bar(2, 79700, 79710, 79650, 79680),
           bar(3, 79680, 79690, 79500, 79520)]
sigs = [dict(dt=side_dt, side="SELL", atr=ATR, entry=ENTRY),
        dict(dt=side_dt + timedelta(minutes=7), side="SELL", atr=ATR, entry=ENTRY)]
taken, skipped, results = R.cascade(sigs, slow_tp, horizon_min=240)
check("I: cascade replay holds one position at a time", taken == 1 and skipped == 1,
      f"taken={taken} skipped={skipped}")
sigs = [dict(dt=side_dt, side="SELL", atr=ATR, entry=ENTRY),
        dict(dt=side_dt + timedelta(minutes=20), side="SELL", atr=ATR, entry=ENTRY)]
taken, skipped, _ = R.cascade(sigs, [sell_sl[0]] + [bar(4, 79900, 79910, 79790, 79800)],
                              horizon_min=240)
check("I: cascade applies the SL cooldown after a loss", taken == 1 and skipped == 1,
      f"taken={taken} skipped={skipped}")

# --- Scenario J ---
print("\nScenario J: handoff_check tolerance policy (5 trades / 48 h, no crying wolf)")
import handoff_check as HC  # noqa: E402

J_DOC = {
    "as_of_utc": "2026-10-01 02:05", "data_collection": "1937",
    "closed_trades": "124", "wins_losses": "54W/70L", "win_rate_pct": "43.5",
    "engine_ledger_usd": "260.19", "true_equity_usd": "-131.63",
    "live_era_trades": "70", "live_era_net_usd": "+32.20",
    "log_covered_trades": "70", "log_bars": "6518",
    "log_last_bar_utc": "2026-10-01 02:05", "skip_rows": "117",
    "open_trade": "SELL #124 @ 83602.0", "spread_usd_per_trade": "0.40",
}


def j_stale(doc=None, **live_over):
    """Keys HC.compare() calls STALE when the live data differs by live_over."""
    live = dict(J_DOC)
    live.update(live_over)
    rows = HC.compare(doc or J_DOC, live)
    return sorted(k for k, _d, _l, verdict, _n in rows if verdict == "STALE")


# normal drift: the box trades and logs while the doc sleeps -> never STALE
check("J: identical snapshot is fresh", j_stale() == [])
check("J: one new M5 bar is normal drift (was STALE via log_last_bar_utc)",
      j_stale(as_of_utc="2026-10-01 02:10", data_collection="1938", log_bars="6519",
              log_last_bar_utc="2026-10-01 02:10") == [])
check("J: one closed trade + a new open trade is normal drift (was STALE via wins_losses)",
      j_stale(closed_trades="125", wins_losses="55W/70L", win_rate_pct="44.0",
              engine_ledger_usd="262.10", true_equity_usd="-129.73",
              live_era_trades="71", live_era_net_usd="+33.10", log_covered_trades="71",
              log_bars="6600", log_last_bar_utc="2026-10-01 09:00",
              open_trade="BUY #125 @ 83700.0") == [])
check("J: an open-trade change alone is normal drift", j_stale(open_trade="none") == [])
check("J: 47 h of log is still fresh",
      j_stale(log_bars=str(6518 + 47 * 12), log_last_bar_utc="2026-10-03 01:05") == [])
five = dict(closed_trades="129", wins_losses="57W/72L", win_rate_pct="44.2",
            engine_ledger_usd="270.19", true_equity_usd="-121.63", live_era_trades="75",
            live_era_net_usd="+42.20", log_covered_trades="75", open_trade="none")
check("J: 5 closed trades behind is still fresh (the documented tolerance)", j_stale(**five) == [])

# genuinely behind or contradictory -> STALE
six = dict(five, closed_trades="130", wins_losses="58W/72L", win_rate_pct="44.6",
           live_era_trades="76", log_covered_trades="76")
stale6 = j_stale(**six)
check("J: 6 closed trades behind is STALE (count and outcomes both flagged)",
      "closed_trades" in stale6 and "wins_losses" in stale6, f"stale={stale6}")
check("J: 49 h of log is STALE",
      "log_last_bar_utc" in j_stale(log_bars=str(6518 + 49 * 12),
                                    log_last_bar_utc="2026-10-03 03:05"))
check("J: changed outcomes with an unchanged trade count are STALE (ledger edited?)",
      j_stale(wins_losses="53W/71L", win_rate_pct="42.7") == ["win_rate_pct", "wins_losses"])
check("J: a snapshot NEWER than the data is STALE (lost data / stale checkout)",
      j_stale(log_last_bar_utc="2026-10-01 01:00") == ["log_last_bar_utc"])
check("J: a different cost assumption is STALE (config must match exactly)",
      j_stale(spread_usd_per_trade="0.60") == ["spread_usd_per_trade"])
check("J: a key missing from the doc is STALE",
      j_stale(doc={k: v for k, v in J_DOC.items() if k != "skip_rows"}) == ["skip_rows"])
check("J: tolerances stay tied to the documented 5 trades / 48 h",
      HC.TRADE_TOLERANCE == 5 and HC.MAX_AGE_HOURS == 48
      and HC.BAR_TOLERANCE == HC.MAX_AGE_HOURS * 12,
      f"{HC.TRADE_TOLERANCE} trades, {HC.MAX_AGE_HOURS} h, {HC.BAR_TOLERANCE} rows")

# --- Scenario K ------------------------------------------------------------
print("\nScenario K: XM quote + contract-spec logger (tools/mt5_quotes.py, read-only sidecar)")
import ast  # noqa: E402
import collections  # noqa: E402
import hashlib  # noqa: E402
import mt5_quotes as Q  # noqa: E402

K_T0 = 1790823600  # 2026-10-01 03:00:00 UTC
K_SECRETS = ("123456789", "Jane Doe", "XMGlobal-MT5 7", "99999.5", "jane", "Common")


class KClock:
    def __init__(self, t):
        self.t = float(t)

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


class KMT5(types.ModuleType):
    """A fake terminal. Bars are synthesised from UTC with the offset in force when each
    bar OPENED (history keeps the raw times it was created with); ticks carry the current
    server time. Any trading call is recorded - the logger must never make one."""
    TIMEFRAME_M5 = 5
    ORDER_TYPE_BUY = 0

    def __init__(self, clock, offset=10800, history_start=K_T0 - 300 * 400):
        super().__init__("MetaTrader5")
        self.clock, self.offset, self.history_start = clock, offset, history_start
        self.flip_utc = self.offset_after = None
        self.spread, self.bid, self.mode, self.frozen = 40.0, 83000.0, "ok", None
        self.stops_level = 100
        self.used, self.trading_calls, self.unknown = collections.Counter(), [], set()
        for name in Q.FORBIDDEN_API:                       # recorded, never legitimately called
            setattr(self, name, (lambda n: lambda *a, **k: self.trading_calls.append(n))(name))

    def __getattr__(self, name):
        self.unknown.add(name)
        raise AttributeError(name)

    def _off_at(self, utc):
        return self.offset_after if (self.flip_utc is not None and utc >= self.flip_utc) else self.offset

    def symbol_info_tick(self, symbol):
        self.used["symbol_info_tick"] += 1
        T = collections.namedtuple("Tick", "time bid ask last volume time_msc flags volume_real")
        if self.mode == "none":
            return None
        if self.mode == "bad":
            return T(int(self.clock.t + self._off_at(self.clock.t)), 0.0, 0.0, 0, 0, 0, 0, 0)
        if self.mode == "crossed":
            return T(int(self.clock.t + self._off_at(self.clock.t) - 0.4), self.bid, self.bid - 5, 0, 0, 0, 0, 0)
        if self.mode == "stale":                           # a frozen tick: its time never moves
            if self.frozen is None:
                self.frozen = int(self.clock.t + self._off_at(self.clock.t) - 5)
            return T(self.frozen, self.bid, self.bid + self.spread, 0, 0, 0, 0, 0)
        self.frozen = None
        return T(int(self.clock.t + self._off_at(self.clock.t) - 0.4), self.bid, self.bid + self.spread,
                 0, 0, 0, 0, 0)

    def symbol_info(self, symbol):
        self.used["symbol_info"] += 1
        S = collections.namedtuple("S", "name description path digits point spread spread_float "
                                   "trade_calc_mode trade_mode trade_exemode filling_mode order_mode "
                                   "expiration_mode trade_stops_level trade_freeze_level "
                                   "trade_contract_size volume_min volume_max volume_step swap_mode "
                                   "swap_long swap_short swap_rollover3days session_deals bidhigh")
        return S("BTCUSD", "Bitcoin vs US Dollar", "Crypto\\BTCUSD", 2, 0.01, 4000, True, 2, 4, 2, 3, 127,
                 15, self.stops_level, 0, 1.0, 0.01, 100.0, 0.01, 5, -30.0, -10.0, 3, 7, 99999.0)

    def account_info(self):
        self.used["account_info"] += 1
        A = collections.namedtuple("A", "login name server balance equity profit trade_mode leverage "
                                   "margin_mode currency trade_allowed company margin_free credit")
        return A(123456789, "Jane Doe", "XMGlobal-MT5 7", 99999.5, 99998.0, 1.5, 0, 500, 2, "USD", True,
                 "XM Global Limited", 99990.0, 0.0)

    def terminal_info(self):
        self.used["terminal_info"] += 1
        Tm = collections.namedtuple("Tm", "build connected trade_allowed maxbars company name path "
                                    "data_path commondata_path ping_last")
        return Tm(5000, True, True, 100000, "XM Global Limited", "MetaTrader 5", "C:\\Users\\jane\\MT5",
                  "C:\\Users\\jane\\MT5\\data", "C:\\Users\\jane\\Common", 77000)

    def order_calc_profit(self, action, symbol, volume, price_open, price_close):
        self.used["order_calc_profit"] += 1
        return round((price_close - price_open) * volume * 1.0, 2)

    def order_calc_margin(self, action, symbol, volume, price):
        self.used["order_calc_margin"] += 1
        return round(price * volume / 500.0, 2)

    def _bar(self, u):
        k = (u // 300) % 1000
        return {"time": u + self._off_at(u), "open": 80000.0 + k, "high": 80010.0 + k, "low": 79990.0 + k,
                "close": 80003.0 + k, "tick_volume": 100 + k % 50, "spread": 4000, "real_volume": 0}

    def copy_rates_from_pos(self, symbol, tf, pos, count):
        self.used["copy_rates_from_pos"] += 1
        assert pos == 1, "the logger must only read CLOSED bars (start_pos 1)"
        last_open = int(self.clock.t // 300) * 300 - 300
        n = min(count, (last_open - self.history_start) // 300 + 1)
        return [self._bar(last_open - 300 * (n - 1 - i)) for i in range(n)]

    def shutdown(self):
        self.used["shutdown"] += 1

    def initialize(self):
        self.used["initialize"] += 1
        return True

    def symbol_select(self, symbol, enable):
        self.used["symbol_select"] += 1
        return True


def k_new(tmp, clk, fm, **kw):
    kw.setdefault("backfill_bars", 60)
    logs = []
    return Q.XmLogger(fm, "BTCUSD", tmp, log=logs.append, sleep=clk.sleep, **kw), logs


def k_run(lg, clk, seconds):
    """Poll on the logger's own 5 s grid for `seconds` of fake time."""
    end = clk.t + seconds
    t = lg.next_poll_time(clk.t)
    while t < end:
        clk.t = t
        lg.step(t)
        t = lg.next_poll_time(t)


def k_quotes(tmp, day="2026-10-01"):
    with open(os.path.join(tmp, f"quotes-{day}.csv"), newline="") as f:
        return list(csv.DictReader(f))


def k_candles(tmp):
    with open(os.path.join(tmp, "candles_m5.csv"), newline="") as f:
        return list(csv.DictReader(f))


def k_steps(rows):
    t = [Q.parse_utc(r["bar_close_utc"]) for r in rows]
    return {int(b - a) for a, b in zip(t, t[1:])}


# K1: read-only by construction (AST, so docstrings that NAME the forbidden calls are fine)
src_tree = ast.parse(open(os.path.join(HERE, "mt5_quotes.py")).read())
used_names = {n.attr for n in ast.walk(src_tree) if isinstance(n, ast.Attribute)} | \
             {n.id for n in ast.walk(src_tree) if isinstance(n, ast.Name)}
hit = sorted(set(Q.FORBIDDEN_API) & used_names)
check("K: the logger never references a trading API (order_send/positions/history/login...)",
      not hit, f"found {hit}")
check("K: it imports without MetaTrader5 (pure functions usable on Linux)", hasattr(Q, "XmLogger"))
check("K: no engine import, so it can never touch the order path",
      not any(isinstance(n, (ast.Import, ast.ImportFrom)) and
              any(a.name.split(".")[0] in ("engine", "trade_filter") for a in getattr(n, "names", []))
              for n in ast.walk(src_tree)))

# K2: server-offset estimator (MT5 'time' is broker server time, not UTC)
check("K: a fresh tick on a +3 h server -> offset 10800",
      Q.estimate_offset(K_T0 + 10800 - 1, K_T0) == 10800)
check("K: a fresh tick on a -5 h server -> offset -18000",
      Q.estimate_offset(K_T0 - 18000 - 2, K_T0) == -18000)
check("K: a tick 20 min old is NOT used to learn the offset (rounding would be ambiguous)",
      Q.estimate_offset(K_T0 + 10800 - 1200, K_T0) is None)
check("K: an empty tick time gives no offset", Q.estimate_offset(0, K_T0) is None)
check("K: tick age uses the offset (a 3 h-behind stale tick is 3 h old, not fresh)",
      abs(Q.tick_age_s(K_T0 + 10800 - 10800, 10800, K_T0) - 10800) < 1e-6)

# K3: a session of polls -> aligned rows, point sample + envelope, no duplicates
tmp = tempfile.mkdtemp()
try:
    clk = KClock(K_T0 + 7)                       # start mid-window on purpose
    fm = KMT5(clk)
    lg, logs = k_new(tmp, clk, fm)
    lg.start(clk(), clock=clk)
    check("K: the server offset is learned from live ticks at start-up", lg.offset == 10800, f"{lg.offset}")
    # scripted spreads: 40 for the first poll of every window, then 41..45
    n = [0]
    real_step = lg.step

    def scripted(now):
        fm.spread = 40.0 + (n[0] % 6)
        n[0] += 1
        return real_step(now)

    lg.step = scripted
    k_run(lg, clk, 190)
    lg.flush_window(clk.t)
    rows = k_quotes(tmp)
    stamps = [r["ts_utc"] for r in rows]
    check("K: quote rows land on the 30 s grid (UTC)", all(x[-2:] in ("00", "30") for x in stamps), f"{stamps[:3]}")
    check("K: no duplicate or out-of-order quote stamps", stamps == sorted(set(stamps)), f"{len(stamps)} rows")
    full = [r for r in rows if r["n_ok"] == "6"]
    check("K: a full window holds 6 polls (30 s / 5 s)", len(full) >= 4, f"{[r['n_ok'] for r in rows]}")
    check("K: the point sample is the FIRST valid poll; spread = ask - bid",
          all(abs(float(r["ask"]) - float(r["bid"]) - float(r["spread"])) < 0.005 for r in rows))
    check("K: spread_min/max bracket the point sample",
          all(float(r["spread_min"]) <= float(r["spread"]) <= float(r["spread_max"]) for r in rows))
    check("K: the envelope catches spikes between row stamps",
          max(float(r["spread_max"]) for r in rows) > max(float(r["spread"]) for r in rows) - 1e-9
          and any(float(r["spread_max"]) > float(r["spread"]) for r in rows))
    check("K: the half-window start is flagged LATE (the sample was not at the boundary)",
          rows[0]["flags"] == "LATE" and all(r["flags"] == "" for r in rows[1:]), f"{[r['flags'] for r in rows]}")
    check("K: the row carries the server offset and a small tick age",
          all(r["srv_offset_s"] == "10800" and 0 <= float(r["tick_age_s"]) < 5 for r in rows))

    # K4: shadow candles - first-run back-fill, UTC conversion, closed bars only
    cds = k_candles(tmp)
    check("K: first run back-fills the requested number of closed M5 bars", len(cds) == 60, f"{len(cds)}")
    check("K: candles are ascending, unique, 300 s apart", k_steps(cds) == {300}, f"{k_steps(cds)}")
    last_open_utc = int((K_T0 + 190) // 300) * 300 - 300
    check("K: bar_close_utc = server open - offset + 5 min (the forward_test_log convention)",
          Q.parse_utc(cds[-1]["bar_close_utc"]) == last_open_utc + 300
          and int(cds[-1]["time_srv"]) == last_open_utc + 10800, f"{cds[-1]}")
    check("K: only CLOSED bars are logged (newest close <= now)",
          Q.parse_utc(cds[-1]["bar_close_utc"]) <= clk.t)
    check("K: bar spread (points) and tick volume are kept for the parity/spread cross-check",
          cds[-1]["spread_pts"] == "4000" and int(cds[-1]["tick_volume"]) > 0)

    # K5: restart on the same files -> no duplicates; 25 min downtime -> the gap heals
    stamps_before, bars_before = len(k_quotes(tmp)), len(k_candles(tmp))
    lg2, logs2 = k_new(tmp, clk, fm)
    lg2.start(clk(), clock=clk)
    check("K: a restart resumes after the last quote row and the last candle",
          lg2.last_stamp is not None and lg2.last_bar_open_utc == last_open_utc)
    k_run(lg2, clk, 70)
    lg2.flush_window(clk.t)
    st2 = [r["ts_utc"] for r in k_quotes(tmp)]
    check("K: a restart never duplicates a quote row", st2 == sorted(set(st2)) and len(st2) > stamps_before)
    clk.t += 25 * 60                               # the sidecar was down for 25 minutes
    lg3, logs3 = k_new(tmp, clk, fm)
    lg3.start(clk(), clock=clk)
    k_run(lg3, clk, 40)
    lg3.flush_window(clk.t)
    cds2 = k_candles(tmp)
    check("K: a gap is healed from terminal history with no hole and no duplicate",
          k_steps(cds2) == {300} and len(cds2) > bars_before + 4, f"{len(cds2)} bars, steps {k_steps(cds2)}")
    check("K: the heal is announced in the log", any("healed a gap" in m for m in logs3), f"{logs3[-3:]}")

    # K6: bad / stale / crossed quotes are recorded explicitly, never silently skipped
    def last_rows(k):
        lg3.flush_window(clk.t)
        return k_quotes(tmp)[-k:]
    fm.mode = "none"
    k_run(lg3, clk, 65)
    r_none = last_rows(2)
    fm.mode = "bad"
    k_run(lg3, clk, 65)
    r_bad = last_rows(2)
    fm.mode = "crossed"
    k_run(lg3, clk, 65)
    r_crossed = last_rows(2)
    fm.mode = "stale"
    off_before = lg3.offset
    n_changes_before = sum(1 for m in logs3 if "offset changed" in m)
    k_run(lg3, clk, 3900)       # > 1 h: the frozen tick passes through 'exactly an hour old'
    r_stale = last_rows(3)
    check("K: no tick -> NOQUOTE rows (outages are explicit)",
          all(r["flags"] == "NOQUOTE" and r["bid"] == "" and r["n_ok"] == "0" for r in r_none), f"{r_none}")
    check("K: zero-price ticks -> BADQUOTE rows", all(r["flags"] == "BADQUOTE" for r in r_bad), f"{r_bad}")
    check("K: crossed quotes (ask < bid) are never logged as a negative spread",
          all(r["flags"] == "BADQUOTE" and r["spread"] == "" for r in r_crossed), f"{r_crossed}")
    check("K: a frozen tick is flagged STALE", all("STALE" in r["flags"] for r in r_stale), f"{r_stale}")
    check("K: a feed frozen for over an hour does NOT move the learned server offset (a tick exactly "
          "N hours old looks like a fresh tick on a server N hours behind)",
          lg3.offset == off_before == 10800
          and sum(1 for m in logs3 if "offset changed" in m) == n_changes_before, f"{lg3.offset}")
    fm.mode = "ok"
    k_run(lg3, clk, 70)

    # K7: server DST fall-back (+3 h -> +2 h) keeps the candle series continuous in UTC
    fm.flip_utc, fm.offset_after = int(clk.t) + 200, 7200
    k_run(lg3, clk, 1500)
    lg3.flush_window(clk.t)
    cds3 = k_candles(tmp)
    offs = [int(r["offset_s"]) for r in cds3]
    check("K: the logger notices the server offset change (needs 2 consistent fresh ticks)",
          lg3.offset == 7200 and any("offset changed" in m for m in logs3), f"offset {lg3.offset}")
    check("K: across the DST change the candle series has NO hole and NO duplicate (UTC resume)",
          k_steps(cds3) == {300}, f"steps {k_steps(cds3)}")
    check("K: candles before the change keep +3 h, after it +2 h",
          10800 in offs and 7200 in offs and offs == sorted(offs, reverse=True), f"{collections.Counter(offs)}")
    flip_close = next(r for r in cds3 if int(r["offset_s"]) == 7200)
    straddle = cds3[cds3.index(flip_close) - 1]
    check("K: the bar that opened before the DST change and closed after it is dated correctly "
          "(old raw time, previous offset) - never an hour into the future",
          Q.parse_utc(straddle["bar_close_utc"]) <= fm.flip_utc + 300 and straddle["offset_s"] == "10800"
          and max(Q.parse_utc(r["bar_close_utc"]) for r in cds3) <= clk.t,
          f"straddle {straddle['bar_close_utc']} flip {Q.utc_str(fm.flip_utc)}")
    check("K: the quote rows switch offset with it",
          {"10800", "7200"} <= {r["srv_offset_s"] for r in k_quotes(tmp)})

    # K8: contract-spec snapshot - allow-listed, decoded, change-logged, nothing identifying
    spec = json.load(open(os.path.join(tmp, "symbol_spec.json")))
    dec = spec["decoded"]
    check("K: spec decodes account kind, execution mode and filling flags",
          dec["account_kind"] == "DEMO" and dec["execution_mode"] == "MARKET"
          and dec["filling_allowed_flags"] == ["FOK", "IOC"] and dec["margin_mode"] == "RETAIL_HEDGING", f"{dec}")
    check("K: spec records stops level, volume step, swap and contract size",
          spec["symbol_info"]["trade_stops_level"] == 100 and spec["symbol_info"]["volume_step"] == 0.01
          and spec["symbol_info"]["swap_long"] == -30.0 and spec["symbol_info"]["trade_contract_size"] == 1.0)
    check("K: the order_calc probe confirms 0.01 lot x $100 = $1.00",
          spec["probes"]["calc_profit_usd_0.01lot_plus_100usd"] == 1.0, f"{spec['probes']}")
    check("K: terminal maxbars is recorded (it caps how much history can be back-filled)",
          spec["terminal"]["maxbars"] == 100000)
    blob = "".join(open(os.path.join(tmp, f), encoding="utf-8", errors="replace").read()
                   for f in sorted(os.listdir(tmp)))
    leaked = [x for x in K_SECRETS if x in blob]
    check("K: PRIVACY - no login, name, server, balance or Windows path in any output file",
          not leaked, f"leaked {leaked}")
    check("K: PRIVACY - the allow-lists contain no identifying field",
          not ({"login", "name", "server", "balance", "equity", "profit", "margin_free"} & set(Q.ACCOUNT_FIELDS))
          and not ({"path", "data_path", "commondata_path"} & set(Q.TERMINAL_FIELDS)))
    hist = open(os.path.join(tmp, "symbol_spec_history.jsonl")).read().splitlines()
    h0 = json.loads(hist[0])["hash"]
    lg3.snapshot_spec(clk.t + 7 * 3600)
    check("K: an unchanged spec is NOT re-appended to the history",
          len(open(os.path.join(tmp, "symbol_spec_history.jsonl")).read().splitlines()) == len(hist))
    fm.stops_level = 250                          # the broker widens the stops level
    lg3.snapshot_spec(clk.t + 14 * 3600)
    hist2 = open(os.path.join(tmp, "symbol_spec_history.jsonl")).read().splitlines()
    check("K: a CHANGED spec (stops level) is appended and logged",
          len(hist2) == len(hist) + 1 and json.loads(hist2[-1])["hash"] != h0
          and json.loads(hist2[-1])["symbol_info"]["trade_stops_level"] == 250
          and any("CHANGED" in m for m in logs3))

    # K12: what the fake terminal saw - read-only, and only the documented calls
    allowed = {"symbol_info_tick", "symbol_info", "account_info", "terminal_info", "order_calc_profit",
               "order_calc_margin", "copy_rates_from_pos", "shutdown", "initialize", "symbol_select"}
    check("K: read-only - not one trading call reached the terminal", fm.trading_calls == [],
          f"{fm.trading_calls}")
    check("K: only the documented read calls were used", set(fm.used) <= allowed and not fm.unknown,
          f"used {sorted(fm.used)} unknown {sorted(fm.unknown)}")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# K9: file hygiene - schema drift, torn line, CRLF, midnight rotation
tmp = tempfile.mkdtemp()
try:
    clk = KClock(K_T0 + 1)
    fm = KMT5(clk)
    lg, logs = k_new(tmp, clk, fm)
    lg.start(clk(), clock=clk)
    k_run(lg, clk, 100)
    lg.flush_window(clk.t)
    qpath = os.path.join(tmp, "quotes-2026-10-01.csv")
    txt = open(qpath, newline="").read()
    open(qpath, "w", newline="").write(txt.replace("n_ok,n_bad", "n_ok,n_bad,extra", 1))
    lg2, logs2 = k_new(tmp, clk, fm)
    lg2.start(clk(), clock=clk)
    k_run(lg2, clk, 70)
    lg2.flush_window(clk.t)
    aside = [f for f in os.listdir(tmp) if f.startswith("quotes-2026-10-01.csv.old-")]
    check("K: a drifted header moves the file ASIDE instead of appending misaligned rows",
          len(aside) == 1 and open(qpath).readline().strip().split(",") == Q.QUOTE_FIELDS
          and any("schema drift" in m for m in logs2), f"{aside}")
    with open(qpath, "ab") as f:
        f.write(b"2026-10-01 05:00:00,83000.00,830")      # killed mid-write: no newline
    lg3, logs3 = k_new(tmp, clk, fm)
    lg3.start(clk(), clock=clk)
    k_run(lg3, clk, 70)
    lg3.flush_window(clk.t)
    lines = open(qpath).read().splitlines()
    bad = [ln for ln in lines[1:] if len(ln.split(",")) != len(Q.QUOTE_FIELDS)]
    check("K: a torn last line stays isolated and the next row is intact",
          len(bad) == 1 and len(lines[-1].split(",")) == len(Q.QUOTE_FIELDS), f"bad {bad}")
    check("K: readers skip the torn line", all(len(r) == len(Q.QUOTE_FIELDS) for r in
                                              [x.split(",") for x in lines[1:] if x not in bad]))
    check("K: no carriage return in any file (the Wine Python would write CRLF in text mode)",
          not any(b"\r" in open(os.path.join(tmp, f), "rb").read() for f in os.listdir(tmp)))
    clk.t = float(K_T0 - 3 * 3600 + 86400 - 40)            # 40 s before 2026-10-02 00:00 UTC
    lg4, logs4 = k_new(tmp, clk, fm)
    lg4.start(clk(), clock=clk)
    k_run(lg4, clk, 100)
    lg4.flush_window(clk.t)
    days = sorted(f for f in os.listdir(tmp) if f.startswith("quotes-") and f.endswith(".csv"))
    d2 = k_quotes(tmp, "2026-10-02")
    check("K: quote files rotate at UTC midnight", days == ["quotes-2026-10-01.csv", "quotes-2026-10-02.csv"]
          and d2 and d2[0]["ts_utc"] == "2026-10-02 00:00:00", f"{days} {d2[:1]}")
    # an older history can be inserted into an existing candle file (--backfill N)
    older = lg4.candle_rows([fm._bar(K_T0 - 300 * 500 + 300 * i) for i in range(5)], clk.t)
    added, total = Q.merge_candles(os.path.join(tmp, "candles_m5.csv"), older)
    cds = k_candles(tmp)
    check("K: merge_candles inserts older history, sorted and unique",
          added == 5 and [int(r["time_srv"]) for r in cds] == sorted({int(r["time_srv"]) for r in cds}),
          f"added {added}")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# K10/K11: watchdog and the real loop (injected clock + sleep, no real waiting)
tmp = tempfile.mkdtemp()
try:
    clk = KClock(K_T0 + 1)
    fm = KMT5(clk)
    lg, logs = k_new(tmp, clk, fm)
    lg.start(clk(), clock=clk)
    k_run(lg, clk, 30)
    fm.mode = "none"
    code = None
    try:
        k_run(lg, clk, 1200)
    except SystemExit as e:
        code = e.code
    check("K: 15 minutes without a quote exits 2 so systemd restarts a clean process", code == 2, f"{code}")
    check("K: before exiting it re-initialises the MT5 link (once a minute)",
          fm.used["shutdown"] >= 5 and fm.used["initialize"] >= 5, f"{fm.used['shutdown']}")
    check("K: the outage is in the data as NOQUOTE rows",
          sum(1 for r in k_quotes(tmp) if r["flags"] == "NOQUOTE") >= 20)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

tmp = tempfile.mkdtemp()
try:
    clk = KClock(K_T0 + 2.3)
    fm = KMT5(clk)
    seen = []
    lg, logs = k_new(tmp, clk, fm)
    real = lg.step

    def spy(now):
        seen.append(round(now, 3))
        if len(seen) >= 14:
            raise KeyboardInterrupt
        return real(now)

    lg.step = spy
    lg.run_forever(clock=clk)
    gaps = {round(b - a, 3) for a, b in zip(seen, seen[1:])}
    check("K: run_forever polls on a steady 5 s grid and ends cleanly on interrupt",
          len(seen) == 14 and gaps == {5.0}, f"{gaps}")
    check("K: the partial window is flushed on shutdown", len(k_quotes(tmp)) >= 2)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# K14: the CLI modes the on-box checklist tells the operator to run (docs/XM-LOGGER.md section 3)
import contextlib  # noqa: E402,F811
import io  # noqa: E402,F811


def k_cli(argv, env=None, fm=None):
    clk = KClock(K_T0 + 1)
    fm = fm or KMT5(clk, history_start=K_T0 - 300 * 500)
    fm.clock = clk
    old = dict(os.environ)
    os.environ.update(env or {})
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            rc = Q.main(argv, mt5mod=fm, clock=clk, sleep=clk.sleep)
    finally:
        os.environ.clear()
        os.environ.update(old)
    return rc, buf.getvalue(), fm


tmp = tempfile.mkdtemp()
try:
    rc, out, fm = k_cli(["--spec", "--dir", tmp])
    try:
        parsed = json.loads(out)
    except ValueError:
        parsed = None
    check("K: --spec prints PURE JSON (nothing before or after it) and writes no file",
          rc == 0 and parsed is not None and os.listdir(tmp) == [], f"rc {rc} files {os.listdir(tmp)}")
    check("K: --spec output carries no login/name/server/balance/path",
          not [x for x in K_SECRETS if x in out] and parsed["decoded"]["account_kind"] == "DEMO",
          f"{[x for x in K_SECRETS if x in out]}")
    rc, out, fm = k_cli(["--once", "--dir", tmp], {"MT5_QUOTES_BACKFILL_BARS": "200"})
    names = sorted(os.listdir(tmp))
    i_spec, i_off, i_back = (out.find("contract spec recorded"), out.find("server offset +3h"),
                             out.find("first run - back-filled 200"))
    check("K: --once learns the offset, records the spec, back-fills and writes a quote row, in that order",
          rc == 0 and 0 <= i_spec < i_off < i_back and "quote row" in out
          and names == ["candles_m5.csv", "quotes-2026-10-01.csv", "symbol_spec.json", "symbol_spec_history.jsonl"],
          f"rc {rc} {names}\n{out[:300]}")
    check("K: --once is read-only too", fm.trading_calls == [] and not fm.unknown)
    rc, out, fm = k_cli(["--backfill", "400", "--dir", tmp])
    cds = k_candles(tmp)
    check("K: --backfill N merges older history into the existing file (sorted, unique, no overwrite)",
          rc == 0 and len(cds) == 400 and k_steps(cds) == {300} and "200 new rows merged" in out,
          f"rc {rc} {len(cds)} rows; {out.strip()}")
    rc, out, fm = k_cli(["--backfill", "400", "--dir", tmp])
    check("K: a second --backfill is idempotent (0 new rows)", rc == 0 and "0 new rows merged" in out and
          len(k_candles(tmp)) == 400, out.strip())
    if Q.mt5 is None:
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                Q.main(["--spec"])
            code = None
        except SystemExit as e:
            code = e.code
        check("K: without MetaTrader5 the CLI refuses with a clear message and exit 1 (Linux python)",
              code == 1 and "install it in the WINE python" in buf.getvalue(), f"{code}")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# K13: the deploy wiring that gets the logger's data to main (static: autosync is bash with side
# effects, so it is exercised by a throwaway-remote test, but these lines must never regress)
auto = open(os.path.join(HERE, "autosync.sh")).read()
data_line = next((ln for ln in auto.splitlines() if ln.startswith("DATA_FILES=")), "")
check("K: autosync commits xm_data/ with the other live data (else the logger's output never reaches main)",
      "xm_data" in data_line, data_line)
check("K: an autosync merge conflict in xm_data/ resolves server-wins like the other data files",
      "|xm_data/*)" in auto and "git checkout --ours" in auto.split("|xm_data/*)")[1][:80])
check("K: the digest carries the logger's liveness line (advisory)", "xm_quote_report.py --quiet" in auto)
alert_block = auto.split('"xm logger: STALE"*)')[1].split(";;")[0] if '"xm logger: STALE"*)' in auto else "$"
check("K: the STALE alert text has no changing numbers, so alert_once's dedupe cannot flood the chat",
      "$XM_MSG" not in alert_block and "mt5quotes-btc" in alert_block, alert_block.strip()[:90])
check("K: the unit file installs as mt5quotes-btc and never carries a login or password",
      "mt5quotes-btc" in open(os.path.join(ROOT, "deploy", "mt5quotes.service")).read()
      and not any(w in open(os.path.join(ROOT, "deploy", "mt5quotes.service")).read().lower().replace(
          "never put a login", "").replace("or password", "")
          for w in ("password=", "login=", "mt5_login", "mt5_password")))

check("K: an incompatible interval/poll falls back to 30/5 instead of mis-aligning rows",
      (lambda lg: (lg.interval, lg.poll))(Q.XmLogger(KMT5(KClock(K_T0)), "BTCUSD", "/nonexistent-never-written",
                                                    interval=30, poll=7, log=lambda m: None)) == (30, 5))

# --- Scenario L ------------------------------------------------------------
print("\nScenario L: xm_quote_report (the logger's data -> spread, cost and parity answers)")
import contextlib  # noqa: E402
import io  # noqa: E402
import xm_quote_report as X  # noqa: E402

L_DAY0 = int(Q.parse_utc("2026-09-14 00:00:00"))          # a Monday


def l_model(t):
    """Deterministic spread model ($/BTC): session level, weekend x2.4 (UTC Sat/Sun)."""
    d = datetime.fromtimestamp(t, tz=timezone.utc)
    base = 38.0 if d.hour < 8 else 44.0 if d.hour < 13 else 56.0 if d.hour < 21 else 42.0
    return base * (2.4 if d.weekday() >= 5 else 1.0)


def l_write_quotes(qdir, days=15, step=60, holes=(), tweak=None):
    """Write quotes-YYYY-MM-DD.csv files in the logger's exact schema."""
    os.makedirs(qdir, exist_ok=True)
    by_day = {}
    for t in range(L_DAY0, L_DAY0 + days * 86400, step):
        if any(a <= t < b for a, b in holes):
            continue
        sp = l_model(t) + ((t // step * 7919) % 11 - 5) * 0.4
        row = {"ts_utc": Q.utc_str(t), "bid": "83000.00", "ask": "%.2f" % (83000 + sp), "spread": "%.2f" % sp,
               "spread_min": "%.2f" % (sp - 1), "spread_max": "%.2f" % (sp + 3), "n_ok": 2, "n_bad": 0,
               "tick_age_s": "0.9", "srv_offset_s": 10800, "flags": ""}
        if tweak:
            tweak(t, row)
        by_day.setdefault(row["ts_utc"][:10], []).append(row)
    for day, rows in by_day.items():
        with open(os.path.join(qdir, f"quotes-{day}.csv"), "w", newline="") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(Q.QUOTE_FIELDS)
            for r in rows:
                w.writerow([r[k] for k in Q.QUOTE_FIELDS])


# L1: the reader parses what the REAL writer produced, and survives a torn line
tmp = tempfile.mkdtemp()
try:
    clk = KClock(K_T0 + 1)
    fm = KMT5(clk)
    lg, _ = k_new(tmp, clk, fm)
    lg.start(clk(), clock=clk)
    k_run(lg, clk, 200)
    lg.flush_window(clk.t)
    rows_a, bad_a, nf_a = X.load_quotes(tmp)
    check("L: the report parses the logger's own quote files (writer and reader share one schema)",
          len(rows_a) >= 6 and bad_a == 0 and nf_a == 1 and rows_a == sorted(rows_a, key=lambda s: s.t),
          f"{len(rows_a)} rows, {bad_a} malformed")
    with open(os.path.join(tmp, "quotes-2026-10-01.csv"), "a") as f:
        f.write("2026-10-01 05:00:00,83000.00,830")             # killed mid-write
    rows_b, bad_b, _ = X.load_quotes(tmp)
    check("L: a torn line is skipped and counted, never fatal", len(rows_b) == len(rows_a) and bad_b == 1,
          f"{len(rows_b)} rows, {bad_b} malformed")
    cds_l = X.load_candles(tmp)
    check("L: the candle reader parses the logger's candle file", len(cds_l) == 60 and
          cds_l[-1]["close"] == datetime(2026, 10, 1, 3, 0), f"{len(cds_l)}")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# L2: coverage, complete days/weekends, outages -> the Stage B-i clock
tmp = tempfile.mkdtemp()
try:
    full_dir, holey_dir = os.path.join(tmp, "full"), os.path.join(tmp, "holey")
    l_write_quotes(full_dir)
    thu, sun = L_DAY0 + 3 * 86400, L_DAY0 + 13 * 86400            # Thu 17 Sep, Sun 27 Sep
    l_write_quotes(holey_dir, holes=[(thu + 4 * 3600, thu + 10 * 3600), (sun, sun + 8 * 3600)])
    s_full, _, _ = X.load_quotes(full_dir)
    s_hole, _, _ = X.load_quotes(holey_dir)
    cf, ch = X.coverage(s_full), X.coverage(s_hole)
    check("L: the inferred cadence is the logger's (60 s here)", cf["interval"] == 60, f"{cf['interval']}")
    check("L: 15 clean days = 15 complete days and 2 complete weekends -> Stage B-i exit MET",
          X.stage_b_progress(cf) == (15, 2, True), f"{X.stage_b_progress(cf)}")
    check("L: a 6 h outage and an 8 h Sunday outage cost 2 days and 1 weekend -> NOT met",
          X.stage_b_progress(ch) == (13, 1, False), f"{X.stage_b_progress(ch)}")
    check("L: outages are listed longest first", [round(d / 3600) for _, d in ch["outages"]] == [8, 6],
          f"{[(round(d / 3600)) for _, d in ch['outages']]}")
    check("L: blackout windows are counted per day against the engine's own windows",
          set(X.blackout_days(s_full, 60).values()) == {15} and len(X.blackout_days(s_full, 60)) == 3,
          f"{X.blackout_days(s_full, 60)}")

    # a 40-minute frozen-feed run that leaves rows behind (e.g. a Saturday maintenance window)
    sat = L_DAY0 + 5 * 86400 + 7 * 3600

    def freeze(t, row):
        if sat <= t < sat + 40 * 60:
            row["flags"] = "STALE"
    l_write_quotes(os.path.join(tmp, "frozen"), days=7, tweak=freeze)
    s_fz, _, _ = X.load_quotes(os.path.join(tmp, "frozen"))
    runs = X.unusable_runs(s_fz, 60)
    check("L: a 40-minute run of STALE rows (rows kept, no quotes) is reported as an outage a gap list cannot see",
          len(runs) == 1 and runs[0][0] == sat and abs(runs[0][1] - 40 * 60) <= 60, f"{runs}")
    check("L: a clean dataset has no unusable runs", X.unusable_runs(s_full, 60) == [])

    # L3: spread statistics against the generating model
    good = [s for s in s_full if X.usable(s)]
    ny_wd = X.summarize([s.spread for s in good if X.session_of(s.t) == "NY" and not X.is_weekend(s.t)])
    asia_wd = X.summarize([s.spread for s in good if X.session_of(s.t) == "ASIA" and not X.is_weekend(s.t)])
    wd = X.summarize([s.spread for s in good if not X.is_weekend(s.t)])
    we = X.summarize([s.spread for s in good if X.is_weekend(s.t)])
    check("L: session medians recover the model (NY weekday ~56, Asia weekday ~38)",
          abs(ny_wd["med"] - 56) < 1.5 and abs(asia_wd["med"] - 38) < 1.5, f"{ny_wd['med']:.1f} {asia_wd['med']:.1f}")
    check("L: the weekend/weekday ratio recovers the x2.4 widening",
          2.0 < we["med"] / wd["med"] < 2.8, f"{we['med'] / wd['med']:.2f}")
    vals = [s.spread for s in good]
    n_we = sum(1 for s in good if X.is_weekend(s.t))
    check("L: every weekend sample is above the $87 break-even, no weekday sample is",
          abs(X.share_above(vals, 87.0) - 100.0 * n_we / len(good)) < 0.5, f"{X.share_above(vals, 87.0):.1f}%")
    check("L: share-above is monotone in the threshold",
          X.share_above(vals, 40) >= X.share_above(vals, 60) >= X.share_above(vals, 87) >= X.share_above(vals, 500))
    check("L: UTC Saturday and Sunday are the weekend; a Friday 23:59 is not",
          X.is_weekend(L_DAY0 + 5 * 86400) and X.is_weekend(L_DAY0 + 6 * 86400 + 86399)
          and not X.is_weekend(L_DAY0 + 5 * 86400 - 1))
    check("L: blackout membership follows trade_filter (07:55-09:00, 13:25-15:15 UTC)",
          X.blackout_of(L_DAY0 + 8 * 3600) is not None and X.blackout_of(L_DAY0 + 14 * 3600) is not None
          and X.blackout_of(L_DAY0 + 11 * 3600) is None and X.blackout_of(L_DAY0 + 7 * 3600 + 54 * 60) is None)
    check("L: percentile helper interpolates", X.pct([1, 2, 3, 4], 0.5) == 2.5 and X.pct([], .5) is None)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# L4/L5: bad rows never reach the statistics; the bar-close subset excludes LATE rows
tmp = tempfile.mkdtemp()
try:
    def tweak(t, row):
        if t % 3600 == 0:
            row["spread"], row["flags"] = "9999.00", "STALE"
        if t % 3600 == 60:
            row["bid"] = row["ask"] = row["spread"] = row["spread_min"] = row["spread_max"] = ""
            row["flags"], row["n_ok"] = "NOQUOTE", 0
        if t % 3600 == 120:
            row["spread"], row["flags"] = "8888.00", "NOOFFSET"
        if t % 300 == 0:
            row["spread"] = "99.00"
            if t % 3600 == 300:
                row["flags"] = "LATE"
    l_write_quotes(tmp, days=2, tweak=tweak)
    s2, _, _ = X.load_quotes(tmp)
    good2 = [s for s in s2 if X.usable(s)]
    check("L: STALE / NOOFFSET / NOQUOTE rows are excluded from spread statistics",
          max(s.spread for s in good2) < 1000 and all(not (s.flags & X.BAD_FLAGS) for s in good2),
          f"{len(good2)} of {len(s2)} usable")
    bar = [s.spread for s in good2 if int(s.t) % 300 == 0 and "LATE" not in s.flags]
    check("L: the bar-close subset is the :00/:05 rows only, minus LATE ones",
          bar and set(bar) == {99.0} and 0 < len(bar) < len([s for s in good2 if int(s.t) % 300 == 0]),
          f"{len(bar)}")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# L6: measured cost on the ledger's trades (half the spread in, half out)
tmp = tempfile.mkdtemp()
try:
    def tweak(t, row):
        if abs(t - (L_DAY0 + 10 * 3600)) <= 120:
            row["spread"] = "40.00"
        if abs(t - (L_DAY0 + 11 * 3600)) <= 120:
            row["spread"] = "60.00"
    l_write_quotes(tmp, days=1, tweak=tweak)
    s3, _, _ = X.load_quotes(tmp)
    dt0 = datetime(2026, 9, 14, 0, 0)
    tr = [dict(et=dt0 + timedelta(hours=10, seconds=20), xt=dt0 + timedelta(hours=11, seconds=5), profit=1.0),
          dict(et=dt0 + timedelta(hours=10), xt=dt0 + timedelta(days=3), profit=5.0),            # exit has no quote
          dict(et=dt0 - timedelta(days=2), xt=dt0 - timedelta(days=2) + timedelta(hours=1), profit=5.0)]
    tc = X.trade_costs(tr, s3, 1.0)
    check("L: cost = (entry spread + exit spread) / 2 x 0.01 lot = $0.50 for $40 in / $60 out",
          len(tc) == 1 and abs(tc[0][1] - 0.50) < 1e-9, f"{[(round(c, 3)) for _, c, _, _ in tc]}")
    check("L: trades without a fresh quote at BOTH ends are skipped, not guessed", len(tc) == 1)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# L7/L8: candle parity vs the forward-test log, time-shift scan, bar-spread check
import random as _rnd  # noqa: E402
_rnd.seed(5)
walk, px = [], 83000.0
for i in range(700):
    o = px
    px = px + _rnd.gauss(0, 25)
    hi, lo = max(o, px) + abs(_rnd.gauss(0, 12)), min(o, px) - abs(_rnd.gauss(0, 12))
    close_dt = datetime(2026, 9, 14, 0, 0) + timedelta(minutes=5 * (i + 1))
    walk.append(dict(dt=close_dt + timedelta(seconds=(1 if i % 7 == 0 else 2 if i % 11 == 0 else 0)),
                     o=o, h=hi, l=lo, c=px))


def l_candles(shift_h=0, noise=3.0):
    out = []
    for b in walk:
        n = _rnd.gauss(0, noise)
        close = datetime(b["dt"].year, b["dt"].month, b["dt"].day, b["dt"].hour, b["dt"].minute) + timedelta(hours=shift_h)
        out.append(dict(close=close, o=b["o"] + n, h=b["h"] + n + 1, l=b["l"] + n - 1, c=b["c"] + n, tv=250.0,
                        sp=4000.0, off=10800.0))
    return out


good_c = l_candles()
pairs0 = X.pair_candles(good_c, walk)
check("L: log rows stamped a second or two late still join (5-minute grid)", len(pairs0) == 700, f"{len(pairs0)}")
ps = X.parity_stats(pairs0)
check("L: parity stats recover the injected noise and agree on direction",
      ps["close_abs"]["med"] < 6 and ps["dir_agree"] > 99 and abs(ps["close_bias"]) < 1.0, f"{ps['close_abs']['med']:.2f}")
sc0 = X.shift_scan(good_c, walk)
check("L: correctly stamped candles: the time-shift scan's best shift is 0",
      min(sc0, key=sc0.get) == 0 and not X.shifted_days(good_c, walk, min_pairs=60), f"{sc0}")
bad_c = l_candles(shift_h=1)
sc1 = X.shift_scan(bad_c, walk)
check("L: candles stamped one hour late are caught (best shift -1 h) and the days flagged",
      min(sc1, key=sc1.get) == -1 and len(X.shifted_days(bad_c, walk, min_pairs=60)) >= 1, f"{sc1}")

tmp = tempfile.mkdtemp()
try:
    l_write_quotes(tmp, days=2, step=30)
    s4, _, _ = X.load_quotes(tmp)
    cs = []
    for k in range(60):                     # 5 h of NY-session candles (live spread ~$56) inside the quote span
        close = datetime(2026, 9, 14, 14, 0) + timedelta(minutes=5 * k)
        cs.append(dict(close=close, o=1, h=1, l=1, c=1, tv=1.0, off=10800.0,
                       sp=round(l_model(close.replace(tzinfo=timezone.utc).timestamp() - 150) * 100)))
    ok = X.bar_spread_check(cs, s4, 0.01)
    for c in cs:
        c["sp"] = 4000.0                    # a constant $40 that ignores the live $56
    flat = X.bar_spread_check(cs, s4, 0.01)
    check("L: bar spreads consistent with the live samples -> AGREES (history usable)",
          ok["verdict"] == "AGREES" and ok["inside"] > 90, f"{ok}")
    check("L: a constant $40 bar spread against live $56 samples -> DISAGREES (never trusted as history)",
          flat["verdict"] == "DISAGREES" and flat["inside"] < 20 and flat["med_diff"] > 5, f"{flat}")
    check("L: too little overlap -> INSUFFICIENT, not a guess",
          X.bar_spread_check(cs[:5], s4, 0.01)["verdict"] == "INSUFFICIENT")

    # --quiet (run by autosync every 15 minutes) must not re-read the whole history forever
    old_dir = os.path.join(tmp, "oldfiles")
    os.makedirs(old_dir)
    with open(os.path.join(old_dir, "quotes-2026-01-01.csv"), "w") as f:
        f.write("this,is,not,the,schema\n1,2,3,4,5\n")             # would count as malformed if it were read
    shutil.copy(os.path.join(tmp, "quotes-2026-09-14.csv"), old_dir)
    _, bad_all, _ = X.load_quotes(old_dir)
    _, bad_since, _ = X.load_quotes(old_dir, since=Q.parse_utc("2026-09-01 00:00:00"))
    check("L: day files older than the window are skipped unread by name (bounded autosync cost)",
          bad_all == 1 and bad_since == 0, f"{bad_all} vs {bad_since}")
    check("L: --quiet looks back at most %d days" % X.QUIET_WINDOW_DAYS, X.QUIET_WINDOW_DAYS >= 2 * X.TARGET_DAYS)

    # L9: the one-line advisory used by autosync's digest
    now_l = Q.parse_utc("2026-09-15 23:59:30") + 120
    args = type("A", (), dict(root=tmp, dir=".", now=now_l))()
    line_ok = X.quiet_line(args)
    args_stale = type("A", (), dict(root=tmp, dir=".", now=now_l + 3 * 3600))()
    line_stale = X.quiet_line(args_stale)
    empty = tempfile.mkdtemp()
    line_none = X.quiet_line(type("A", (), dict(root=empty, dir="xm_data", now=now_l))())
    shutil.rmtree(empty, ignore_errors=True)
    check("L: --quiet says OK while rows are fresh", line_ok.startswith("xm logger: OK"), line_ok)
    check("L: --quiet says STALE (and names the unit) once rows stop", "STALE" in line_stale and "mt5quotes-btc" in line_stale,
          line_stale)
    check("L: --quiet says 'not collecting yet' with no data", "not collecting yet" in line_none, line_none)

    # L10: the full text report renders every section on a small synthetic repo root
    root = os.path.join(tmp, "root")
    os.makedirs(os.path.join(root, "xm_data"))
    for fn in os.listdir(tmp):
        if fn.startswith("quotes-"):
            shutil.copy(os.path.join(tmp, fn), os.path.join(root, "xm_data", fn))
    with open(os.path.join(root, "xm_data", "candles_m5.csv"), "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(Q.CANDLE_FIELDS)
        for c in good_c:
            w.writerow([c["close"].strftime(Q.TS_FMT), "%.2f" % c["o"], "%.2f" % c["h"], "%.2f" % c["l"],
                        "%.2f" % c["c"], 250, 4000, 0, 10800])
    with open(os.path.join(root, "forward_test_log.csv"), "w", newline="") as f:
        w = csv.writer(f, lineterminator="\r\n")
        w.writerow(["Timestamp", "Open", "High", "Low", "Close"])
        for b in walk:
            w.writerow([b["dt"].strftime(Q.TS_FMT), "%.2f" % b["o"], "%.2f" % b["h"], "%.2f" % b["l"], "%.2f" % b["c"]])
    with open(os.path.join(root, "trades.csv"), "w", newline="") as f:
        w = csv.writer(f, lineterminator="\r\n")
        w.writerow(["Trade_Num", "Trade_Type", "Entry_Time", "Exit_Time", "Entry_Price", "Stop_Loss", "Take_Profit",
                    "Exit_Price", "Exit_Reason", "Profit", "Balance_After", "RSI_At_Entry", "ATR_At_Entry",
                    "Wick_Ratio_At_Entry", "EMA50_At_Entry", "EMA200_At_Entry"])
        for i in range(12):
            et = datetime(2026, 9, 14, 8, 0) + timedelta(hours=i)
            w.writerow([i + 1, "BUY", et.strftime(Q.TS_FMT), (et + timedelta(minutes=20)).strftime(Q.TS_FMT), "83000.00",
                        "82833.40", "83333.20", "83333.20", "TP", "3.33", "1000", "50", "83.30", "40%", "83000", "82000"])
    with open(os.path.join(root, "xm_data", "symbol_spec.json"), "w") as f:
        json.dump({"symbol_info": {"trade_contract_size": 1.0, "volume_min": 0.01, "point": 0.01},
                   "decoded": {"account_kind": "DEMO"}, "account": {}, "terminal": {}, "probes": {}}, f)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = X.main(["--root", root, "--now", str(now_l)])
    out = buf.getvalue()
    heads = [h for h in ("== 1. LOGGER", "== 2. SPREAD", "== 3. COST", "== 4. PARITY", "== 5. SPEC") if h in out]
    check("L: the full report renders all five sections without error", rc == 0 and len(heads) == 5, f"rc {rc}, {heads}")
    check("L: the report quotes the review's reference numbers (break-even, hard cap, share of 1R)",
          "hard-cap proposal $60/BTC" in out and "% of median 1R" in out and "break-even $" in out)
    check("L: the report has no --spread flag (docs command blocks may only carry --spread 0.40)",
          "--spread" not in open(os.path.join(HERE, "xm_quote_report.py")).read().split('ap = argparse')[1])
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# --- summary ---------------------------------------------------------------
# autosync.sh gates every deploy on this exit code - never remove it.
print()
if FAILURES:
    print(f"SMOKE TEST FAILED: {FAILURES}")
    sys.exit(1)
print("SMOKE TEST PASSED")
