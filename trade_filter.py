#!/usr/bin/env python3
"""
Lightweight pre-trade filter & Portfolio Risk Gatekeeper - Nasdaq (US100Cash) M15 version.

Acts as the final gatekeeper for portfolio/state-level rules.
(Strategy-level rules like RSI, Wick, Floor/Ceiling, Slope, and Trend are handled
in engine.py.)

XM Nasdaq-100 Cash Index CFD (US100Cash, M15) risk & session controls:
  - Escalating SL cooldowns (30m / 60m = 2 / 4 M15 bars)
  - Daily-loss circuit breaker (3 SLs or -$15 realized daily loss in UTC day)
  - DST-aware America/New_York market quiet hours (weekend + 17:00-18:00 ET CME break)
  - DST-aware America/New_York session blackouts (08:30 ET macro, 09:30 ET cash open,
    16:45-18:15 ET daily close & rollover spread spike)
  - Percentage-based M15 ATR bounds adaptive to index level (0.04% - 0.80%)
  - Schema-drift tripwire on trades.csv

Timestamps on disk (Entry_Time, Exit_Time, skipped_trades.csv) are always UTC.
Session blackouts and market closures convert UTC -> America/New_York via stdlib
zoneinfo so US DST transitions never shift the NYSE/CME open or rollover break.
"""

import csv
import os
from datetime import date, datetime, time, timedelta, timezone, tzinfo

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:                      # pragma: no cover - Python < 3.9
    ZoneInfo = None

    class ZoneInfoNotFoundError(Exception):
        pass


class USEasternFallback(tzinfo):
    """Stdlib fixed-rule US Eastern (EST/EDT) `tzinfo` - needs no `tzdata` package.

    Only used when `ZoneInfo("America/New_York")` raises `ZoneInfoNotFoundError`.
    That happens on Windows/Wine Python builds (the Wine MT5 sidecars run
    `C:/Python312/python.exe`) because the IANA database is NOT in the stdlib and
    `tzdata` was never pip-installed into the Wine interpreter.

    Rules (post-2007 US federal law, which covers every date this bot can trade):
      * DST starts: 2nd Sunday of March,   02:00 EST -> 03:00 EDT  (= 07:00 UTC)
      * DST ends:   1st Sunday of November, 02:00 EDT -> 01:00 EST (= 06:00 UTC)

    Permanent fix inside the Wine prefix (keeps `ZoneInfo` authoritative):
      wine C:/Python312/python.exe -m pip install tzdata
    """

    STD = timedelta(hours=-5)            # EST
    DST = timedelta(hours=-4)            # EDT
    _HOUR = timedelta(hours=1)

    @staticmethod
    def _nth_sunday(year, month, n):
        first = date(year, month, 1)
        first_sunday = first + timedelta(days=(6 - first.weekday()) % 7)   # Sun == 6
        return first_sunday + timedelta(weeks=n - 1)

    @classmethod
    def _bounds_local(cls, year):
        """(DST start, DST end) as naive America/New_York wall-clock datetimes."""
        start = datetime.combine(cls._nth_sunday(year, 3, 2), time(2, 0))
        end = datetime.combine(cls._nth_sunday(year, 11, 1), time(2, 0))
        return start, end

    def _is_dst_local(self, local, fold=0):
        start, end = self._bounds_local(local.year)
        if not (start <= local < end):
            return False
        # 02:00-03:00 wall time on the spring-forward Sunday does not exist; fold=0
        # resolves it as EST, matching the IANA database.
        if start <= local < start + self._HOUR and not fold:
            return False
        # 01:00-02:00 wall time on the fall-back Sunday happens twice: fold=0 is
        # the first (EDT) pass, fold=1 is the repeated (EST) pass.
        if end - self._HOUR <= local and fold:
            return False
        return True

    def dst(self, dt):
        if dt is None:
            return timedelta(0)
        return self._HOUR if self._is_dst_local(dt.replace(tzinfo=None), getattr(dt, "fold", 0)) else timedelta(0)

    def utcoffset(self, dt):
        if dt is None:
            return self.STD
        return self.DST if self.dst(dt) else self.STD

    def fromutc(self, dt):
        """UTC -> Eastern (called by `astimezone()` / `fromtimestamp(tz=...)`)."""
        naive_utc = dt.replace(tzinfo=None)
        start_local, end_local = self._bounds_local(naive_utc.year)
        start_utc = start_local - self.STD      # 02:00 EST = 07:00 UTC (2nd Sunday of March)
        end_utc = end_local - self.DST          # 02:00 EDT = 06:00 UTC (1st Sunday of November)
        is_dst = start_utc <= naive_utc < end_utc
        local = naive_utc + (self.DST if is_dst else self.STD)
        if not is_dst and end_local - self._HOUR <= local < end_local:
            local = local.replace(fold=1)       # repeated EST hour after the fall-back
        return local.replace(tzinfo=self)

    def tzname(self, dt):
        return "EDT" if self.dst(dt) else "EST"

    def __repr__(self):
        return "USEasternFallback()"


def load_ny_tz():
    """America/New_York via `zoneinfo`, falling back to the fixed US DST rule.

    Never raises: a missing (or corrupt) tzdata install must not stop the engine
    or the session gate. Under Wine install it with
    `wine C:/Python312/python.exe -m pip install tzdata` (docs/XM-LOGGER.md).
    """
    if ZoneInfo is not None:
        try:
            return ZoneInfo("America/New_York")
        except ZoneInfoNotFoundError:
            return USEasternFallback()
        except Exception:                   # corrupt tzdata / unexpected OSError
            return USEasternFallback()
    return USEasternFallback()


NY_TZ = load_ny_tz()

DATA_DIR = os.getenv("NASDAQ_DATA_DIR", "/opt/nasdaq")
TRADES_LOG = os.getenv("NASDAQ_TRADES_FILE", os.path.join(DATA_DIR, "trades.csv"))
SKIP_LOG = os.getenv("NASDAQ_SKIP_FILE", os.path.join(DATA_DIR, "skipped_trades.csv"))
LOOKBACK = 30      # trailing rows used for the consecutive-SL streak
DAY_WINDOW = 400   # rows read for the daily-loss count across the full UTC day

# === Settings (Risk & Volatility Controls) ===
SL_COOLDOWN_BASE_MINUTES = 30       # 2 M15 bars after 1 SL
SL_COOLDOWN_ESCALATED_MINUTES = 60  # 4 M15 bars after 2+ consecutive SLs
MAX_DAILY_LOSSES = 3                # Halt trading for the rest of the UTC day after 3 SLs
MAX_DAILY_LOSS_USD = 15.0           # Halt trading if realized UTC-day P/L <= -$15.00

# === Percentage-based M15 ATR bounds (adaptive to US100Cash price) ===
# At 20,000: MIN is 0.04% (8.0 pts) | MAX is 0.80% (160.0 pts)
MIN_ATR_PERCENT = 0.0004
MAX_ATR_PERCENT = 0.0080

# === Session Blackout Windows (America/New_York local exchange time, DST-aware) ===
# Evaluated in America/New_York so US DST changes (March / November) automatically
# align with the 08:30 ET macro releases, 09:30 ET NASDAQ cash bell, and 17:00 ET CME break.
BLACKOUT_WINDOWS_ET = [
    (8, 25, 8, 40, "US 08:30 ET High-Impact Macro Releases"),
    (9, 25, 9, 45, "NASDAQ 09:30 ET Cash Open Whip-Saw"),
    (16, 45, 18, 15, "CME Daily Close & Rollover Break"),
]
# Alias kept for tools (e.g. xm_quote_report.py) that inspect window definitions.
BLACKOUT_WINDOWS = BLACKOUT_WINDOWS_ET


def _as_utc(dt: datetime = None) -> datetime:
    if dt is None:
        return datetime.now(timezone.utc)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def is_market_quiet(now_utc: datetime = None) -> bool:
    """True when US100Cash (CME Globex Nasdaq-100 / XM Cash CFD) is closed.

    Schedule in America/New_York (handles EDT/EST automatically):
      - Closed weekends: Friday 16:55 ET -> Sunday 18:10 ET
      - Daily CME maintenance break (Mon-Thu): 16:55 ET -> 18:10 ET
    """
    et = _as_utc(now_utc).astimezone(NY_TZ)
    wd = et.weekday()  # 0=Mon .. 4=Fri, 5=Sat, 6=Sun
    mins = et.hour * 60 + et.minute
    close_min = 16 * 60 + 55   # 16:55 ET
    reopen_min = 18 * 60 + 10  # 18:10 ET

    if wd == 5:  # Saturday
        return True
    if wd == 4 and mins >= close_min:  # Friday after close
        return True
    if wd == 6 and mins < reopen_min:  # Sunday before reopen
        return True
    if wd in (0, 1, 2, 3) and close_min <= mins < reopen_min:  # Mon-Thu CME break
        return True
    return False


def blackout_label_for_utc(now_utc: datetime = None) -> str | None:
    """Return the active America/New_York blackout window label for `now_utc`, or None."""
    et = _as_utc(now_utc).astimezone(NY_TZ)
    if et.weekday() == 5 or (et.weekday() == 6 and (et.hour * 60 + et.minute) < 18 * 60):
        return None
    t = et.time()
    for sh, sm, eh, em, label in BLACKOUT_WINDOWS_ET:
        if time(sh, sm) <= t <= time(eh, em):
            return label
    return None


def is_in_blackout(now: datetime = None) -> tuple[bool, str]:
    now_u = _as_utc(now)
    label = blackout_label_for_utc(now_u)
    if label:
        return True, f"Blackout: {label}"
    if is_market_quiet(now_u):
        return True, "Blackout: Market Closed (Weekend / Daily Break)"
    return False, ""


def load_recent_trades(n=LOOKBACK) -> list:
    if not os.path.isfile(TRADES_LOG):
        return []
    rows = []
    try:
        with open(TRADES_LOG, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
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
    today_str = _as_utc(now).strftime("%Y-%m-%d")
    count = 0
    for t in trades:
        ext = t.get("Exit_Time") or t.get("Entry_Time") or ""
        if ext.startswith(today_str) and (t.get("Exit_Reason") or "").strip().upper() == "SL":
            count += 1
    return count


def get_daily_net_pnl(trades: list, now: datetime = None) -> float:
    """Sums realized Profit for trades that exited today in UTC."""
    if not trades:
        return 0.0
    today_str = _as_utc(now).strftime("%Y-%m-%d")
    total = 0.0
    for t in trades:
        ext = t.get("Exit_Time") or t.get("Entry_Time") or ""
        if ext.startswith(today_str):
            try:
                total += float(str(t.get("Profit", "0") or "0").replace(",", ""))
            except (TypeError, ValueError):
                continue
    return total


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
    """Circuit breaker: halts trading if daily SL count or daily $ loss limit is hit."""
    daily_sls = get_daily_sl_count(trades, now)
    if daily_sls >= MAX_DAILY_LOSSES:
        return True, f"Daily Loss Limit Reached ({daily_sls}/{MAX_DAILY_LOSSES} SLs today) - Trading Halted"
    daily_pnl = get_daily_net_pnl(trades, now)
    if daily_pnl <= -MAX_DAILY_LOSS_USD:
        return True, f"Daily Loss Limit Reached (${daily_pnl:.2f} <= -${MAX_DAILY_LOSS_USD:.2f} today) - Trading Halted"
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
        exit_time = datetime.strptime(last["Exit_Time"], "%Y-%m-%d %H:%M:%S")
        exit_time = exit_time.replace(tzinfo=timezone.utc)
        cooldown_end = exit_time + timedelta(minutes=cooldown_minutes)
        now_u = _as_utc(now)

        if now_u < cooldown_end:
            remaining = int((cooldown_end - now_u).total_seconds() / 60) + 1
            streak_info = f" ({consecutive_sls} consecutive SLs -> {cooldown_minutes}m cooldown)" if consecutive_sls >= 2 else ""
            return True, f"SL Cooldown: {remaining} min remaining{streak_info}"
    except Exception:
        pass

    return False, ""


def log_skip(reason: str, price=None, atr=None):
    file_exists = os.path.isfile(SKIP_LOG)
    try:
        os.makedirs(os.path.dirname(SKIP_LOG) or ".", exist_ok=True)
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
    Note: RSI, Wick, Floor/Ceiling, Slope, and Trend direction are validated in engine.py.
    """
    # 1. Time blackout / closed market
    in_bo, bo_reason = is_in_blackout(now)
    if in_bo:
        log_skip(bo_reason, current_price, current_atr)
        return False, bo_reason

    trades = load_recent_trades(n=DAY_WINDOW)

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

    # 4. Percentage-based M15 ATR Filter (adaptive to US100Cash price)
    if current_atr is not None and current_price is not None and current_price > 0:
        atr_percent = current_atr / current_price

        if atr_percent < MIN_ATR_PERCENT:
            reason = f"ATR too low ({atr_percent*100:.3f}% < {MIN_ATR_PERCENT*100:.3f}%)"
            log_skip(reason, current_price, current_atr)
            return False, reason

        if atr_percent > MAX_ATR_PERCENT:
            reason = f"ATR too high - News volatility ({atr_percent*100:.3f}% > {MAX_ATR_PERCENT*100:.3f}%)"
            log_skip(reason, current_price, current_atr)
            return False, reason

    return True, "OK"


if __name__ == "__main__":
    allow, reason = should_take_trade(
        current_atr=35.00,
        current_price=20500.00,
        ema_fast=20510.00,
        ema_slow=20480.00,
    )
    print(f"Allow: {allow} | Reason: {reason}")
