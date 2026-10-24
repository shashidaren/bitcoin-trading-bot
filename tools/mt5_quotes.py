#!/usr/bin/env python3
"""XM quote + contract-spec logger for US100Cash (Stage B-i) - READ-ONLY Wine sidecar.

Why this exists (docs/HANDOFF.md section 7):
  1) Measures XM's actual live spread on US100Cash across Asia, London, NY cash
     open, and rollover windows (quotes-YYYY-MM-DD.csv, every 30 s).
  2) Back-fills up to MT5_QUOTES_BACKFILL_BARS (default 12,000 M15 bars = ~6 months
     of US100Cash trading history!) into candles_m15.csv on first start, giving both
     feed-parity audits AND an immediate 6-month broker dataset for tools/backtest.py.
  3) Snapshots allow-listed contract specs (symbol_spec.json) with zero PII.

PRIVACY: Never dumps login, name, server, balance, equity, or Windows paths.
READ-ONLY: Never references any trading API (FORBIDDEN_API AST-checked in smoke_test.py).

Run (manual test):
  export WINEPREFIX=~/.mt5
  xvfb-run --auto-servernum wine C:/Python312/python.exe Z:/opt/nasdaq/tools/mt5_quotes.py --spec
  xvfb-run --auto-servernum wine C:/Python312/python.exe Z:/opt/nasdaq/tools/mt5_quotes.py --once
Or as a service (deploy/mt5quotes.service):
  sudo systemctl enable --now mt5quotes-nasdaq
"""
import argparse
import csv
import hashlib
import json
import math
import os
import sys
import time
from datetime import date, datetime, time as dtime, timedelta, timezone, tzinfo

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:                      # pragma: no cover - Python < 3.9
    ZoneInfo = None

    class ZoneInfoNotFoundError(Exception):
        pass

try:
    import MetaTrader5 as mt5
except ImportError:          # Linux box, CI, smoke test: importable, just not runnable
    mt5 = None

SCHEMA_VERSION = 1
TS_FMT = "%Y-%m-%d %H:%M:%S"
M15_SECONDS = 900
BAR_SECONDS = M15_SECONDS


class USEasternFallback(tzinfo):
    """Stdlib fixed-rule US Eastern (EST/EDT) `tzinfo` - needs no `tzdata` package.

    Only used when `ZoneInfo("America/New_York")` raises `ZoneInfoNotFoundError`,
    i.e. inside the Wine MT5 interpreter (`C:/Python312/python.exe`) where the
    IANA database is absent because `tzdata` was never pip-installed.

    Rules (post-2007 US federal law):
      * DST starts: 2nd Sunday of March,    02:00 EST -> 03:00 EDT (= 07:00 UTC)
      * DST ends:   1st Sunday of November, 02:00 EDT -> 01:00 EST (= 06:00 UTC)

    Permanent fix inside the Wine prefix:
      wine C:/Python312/python.exe -m pip install tzdata
    (twin of the class in trade_filter.py - this sidecar stays import-free of the
    repo on purpose so it can run standalone under Z:\\opt\\nasdaq\\tools.)
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
        start = datetime.combine(cls._nth_sunday(year, 3, 2), dtime(2, 0))
        end = datetime.combine(cls._nth_sunday(year, 11, 1), dtime(2, 0))
        return start, end

    def _is_dst_local(self, local, fold=0):
        start, end = self._bounds_local(local.year)
        if not (start <= local < end):
            return False
        # 02:00-03:00 wall time on the spring-forward Sunday does not exist; fold=0
        # resolves it as EST, matching the IANA database.
        if start <= local < start + self._HOUR and not fold:
            return False
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
        start_utc = start_local - self.STD      # 02:00 EST = 07:00 UTC
        end_utc = end_local - self.DST          # 02:00 EDT = 06:00 UTC
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
    """America/New_York via `zoneinfo`, falling back to the fixed US DST rule."""
    if ZoneInfo is not None:
        try:
            return ZoneInfo("America/New_York")
        except ZoneInfoNotFoundError:
            return USEasternFallback()
        except Exception:                   # corrupt tzdata / unexpected OSError
            return USEasternFallback()
    return USEasternFallback()


NY_TZ = load_ny_tz()

QUOTE_FIELDS = ["ts_utc", "bid", "ask", "spread", "spread_min", "spread_max",
                "n_ok", "n_bad", "tick_age_s", "srv_offset_s", "flags"]
CANDLE_FIELDS = ["bar_close_utc", "open", "high", "low", "close", "tick_volume",
                 "spread_pts", "time_srv", "offset_s"]

QUOTES_PREFIX = "quotes-"
CANDLES_FILE = "candles_m15.csv"
SPEC_FILE = "symbol_spec.json"
SPEC_HISTORY_FILE = "symbol_spec_history.jsonl"

# --- tunables ---------------------------------------------------------------------------
DEFAULT_DIR = "Z:/opt/nasdaq/xm_data"        # Wine's Z: is the Linux root
LAG_S = 1.0                  # sample just after the boundary so the new M15 bar's quotes exist
STALE_TICK_S = 120           # a point-sample tick older than this is flagged STALE
OFFSET_MAX_AGE_S = 300       # residual (tick age + clock skew) allowed when learning the offset
OFFSET_CONFIRM = 2           # a CHANGED offset must be seen on this many consecutive fresh ticks
MAX_OFFSET_H = 14            # implausible beyond +-14 h
SPEC_EVERY_S = 6 * 3600      # re-read the contract spec this often (changes are history-logged)
REINIT_AFTER_S = 60          # no valid quote this long -> shutdown()/initialize() again
DEAD_AFTER_S = 900           # ...and this long -> exit(2) so systemd restarts a clean process
MAX_FETCH_BARS = 5000        # per gap-heal call (~52 days of M15)
CANDLE_RETRY_S = 10          # throttle for re-asking history about the same closed bar
HEARTBEAT_S = 3600           # one stdout line per hour
ERR_LOG_EVERY_S = 300        # repeated identical errors are printed at most this often
FUTURE_SLACK_S = 120         # a "closed" bar may not end later than now + this
SETTLE_TRIES = 5             # first-run back-fill: re-ask while the terminal downloads history
SETTLE_WAIT_S = 3.0

# --- what is allowed into a public repo (explicit allow-lists, never a dump) -------------
SYMBOL_FIELDS = (
    "name", "description", "path", "currency_base", "currency_profit", "currency_margin",
    "digits", "point", "spread_float", "trade_calc_mode", "trade_mode", "trade_exemode",
    "filling_mode", "order_mode", "expiration_mode", "order_gtc_mode",
    "trade_stops_level", "trade_freeze_level",
    "trade_contract_size", "trade_tick_size", "trade_tick_value",
    "trade_tick_value_profit", "trade_tick_value_loss",
    "volume_min", "volume_max", "volume_step", "volume_limit",
    "swap_mode", "swap_long", "swap_short", "swap_rollover3days",
    "swap_sunday", "swap_monday", "swap_tuesday", "swap_wednesday",
    "swap_thursday", "swap_friday", "swap_saturday",
    "margin_initial", "margin_maintenance", "margin_hedged", "margin_hedged_use_leg",
    "start_time", "expiration_time",
)
ACCOUNT_FIELDS = (                      # NOT login, name, server, balance, equity, profit, margin
    "trade_mode", "margin_mode", "leverage", "currency", "currency_digits",
    "limit_orders", "margin_so_mode", "margin_so_call", "margin_so_so",
    "trade_allowed", "trade_expert", "fifo_close", "company",
)
TERMINAL_FIELDS = (                     # NOT path, data_path, commondata_path (Windows user names)
    "build", "connected", "trade_allowed", "tradeapi_disabled", "maxbars", "company", "name",
)
TERMINAL_VOLATILE = ("connected",)

# --- decoders for the numeric enums/bitmasks (documented MT5 values) ---------------------
FILLING_BITS = {1: "FOK", 2: "IOC", 4: "BOC"}
ORDER_MODE_BITS = {1: "MARKET", 2: "LIMIT", 4: "STOP", 8: "STOP_LIMIT", 16: "SL", 32: "TP",
                   64: "CLOSE_BY"}
EXPIRATION_BITS = {1: "GTC", 2: "DAY", 4: "SPECIFIED", 8: "SPECIFIED_DAY"}
EXEMODE = {0: "REQUEST", 1: "INSTANT", 2: "MARKET", 3: "EXCHANGE"}
SYMBOL_TRADE_MODE = {0: "DISABLED", 1: "LONG_ONLY", 2: "SHORT_ONLY", 3: "CLOSE_ONLY", 4: "FULL"}
CALC_MODE = {0: "FOREX", 1: "FUTURES", 2: "CFD", 3: "CFD_INDEX", 4: "CFD_LEVERAGE",
             5: "FOREX_NO_LEVERAGE"}
SWAP_MODE = {0: "DISABLED", 1: "POINTS", 2: "CURRENCY_SYMBOL", 3: "CURRENCY_MARGIN",
             4: "CURRENCY_DEPOSIT", 5: "INTEREST_CURRENT", 6: "INTEREST_OPEN",
             7: "REOPEN_CURRENT", 8: "REOPEN_BID"}
ACCOUNT_TRADE_MODE = {0: "DEMO", 1: "CONTEST", 2: "REAL"}
ACCOUNT_MARGIN_MODE = {0: "RETAIL_NETTING", 1: "EXCHANGE", 2: "RETAIL_HEDGING"}
WEEKDAY = {0: "SUN", 1: "MON", 2: "TUE", 3: "WED", 4: "THU", 5: "FRI", 6: "SAT"}

# The trading API this sidecar must never touch (Scenario K walks the AST for these names).
FORBIDDEN_API = ("order_send", "order_check", "positions_get", "positions_total", "orders_get",
                 "orders_total", "history_orders_get", "history_deals_get", "history_orders_total",
                 "history_deals_total", "login", "market_book_add")


# =========================================================================================
# small pure helpers
# =========================================================================================
def utc_str(epoch):
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime(TS_FMT)


def parse_utc(text):
    return datetime.strptime(text.strip(), TS_FMT).replace(tzinfo=timezone.utc).timestamp()


def is_cme_closed(epoch: float) -> bool:
    """True during CME Globex US100Cash closure (Fri 16:55 ET -> Sun 18:10 ET, and Mon-Thu 16:55-18:10 ET)."""
    et = datetime.fromtimestamp(float(epoch), tz=timezone.utc).astimezone(NY_TZ)
    wd = et.weekday()
    mins = et.hour * 60 + et.minute
    if wd == 5:
        return True
    if wd == 4 and mins >= 16 * 60 + 55:
        return True
    if wd == 6 and mins < 18 * 60 + 10:
        return True
    if wd in (0, 1, 2, 3) and (16 * 60 + 55) <= mins < (18 * 60 + 10):
        return True
    return False


def _env_num(name, default, cast=int):
    try:
        return cast(float(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


def jsonable(v):
    if isinstance(v, (bool, int, float, str)) or v is None:
        return v
    item = getattr(v, "item", None)
    if callable(item):
        try:
            return item()
        except Exception:
            pass
    return str(v)


def clean_label(text):
    return " ".join(str(text or "").split())[:80]


def estimate_offset(tick_time_srv, now_epoch, max_age_s=OFFSET_MAX_AGE_S):
    """Broker-server offset from UTC in seconds (whole hours), or None."""
    if not tick_time_srv:
        return None
    d = float(tick_time_srv) - float(now_epoch)
    off = int(round(d / 3600.0)) * 3600
    if abs(off) > MAX_OFFSET_H * 3600 or abs(d - off) > max_age_s:
        return None
    return off


def tick_age_s(tick_time_srv, offset_s, now_epoch):
    if offset_s is None or not tick_time_srv:
        return None
    return float(now_epoch) - (float(tick_time_srv) - offset_s)


def decode_bits(value, table):
    try:
        v = int(value)
    except (TypeError, ValueError):
        return None
    return [name for bit, name in sorted(table.items()) if v & bit]


def decode_enum(value, table):
    try:
        v = int(value)
    except (TypeError, ValueError):
        return None
    return table.get(v, "?%d" % v)


def read_csv_rows(path, fields):
    out = []
    try:
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if header != list(fields):
                return out
            for parts in reader:
                if len(parts) == len(fields):
                    out.append(dict(zip(fields, parts)))
    except (OSError, UnicodeDecodeError):
        pass
    return out


def last_csv_row(path, fields):
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 8192))
            data = f.read().decode("utf-8", "replace")
    except OSError:
        return None
    for ln in reversed([x for x in data.splitlines() if x.strip()]):
        try:
            parts = next(csv.reader([ln]))
        except (csv.Error, StopIteration):
            continue
        if len(parts) == len(fields) and parts != list(fields):
            return dict(zip(fields, parts))
    return None


class CsvAppender:
    """Append-only CSV: header on create, schema-drift protection, torn-line repair."""

    def __init__(self, path, fields, log=print):
        self.path, self.fields, self.log = path, list(fields), log
        self._ready = False

    def _prepare(self):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        if os.path.exists(self.path) and os.path.getsize(self.path) > 0:
            with open(self.path, "r", newline="", encoding="utf-8", errors="replace") as f:
                header = f.readline().rstrip("\r\n")
            if header.split(",") != self.fields:
                aside = "%s.old-%s" % (self.path, time.strftime("%Y%m%dT%H%M%S", time.gmtime()))
                os.replace(self.path, aside)
                self.log("mt5_quotes: WARNING schema drift in %s - moved to %s, starting a "
                         "fresh file" % (os.path.basename(self.path), os.path.basename(aside)))
            else:
                with open(self.path, "rb") as f:
                    f.seek(-1, os.SEEK_END)
                    last = f.read(1)
                if last != b"\n":
                    with open(self.path, "ab") as f:
                        f.write(b"\n")
        if not os.path.exists(self.path) or os.path.getsize(self.path) == 0:
            with open(self.path, "w", newline="", encoding="utf-8") as f:
                csv.writer(f, lineterminator="\n").writerow(self.fields)
        self._ready = True

    def append(self, rows):
        if not rows:
            return
        if (not self._ready or not os.path.exists(self.path)
                or os.path.getsize(self.path) == 0):
            self._ready = False
            self._prepare()
        with open(self.path, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f, lineterminator="\n")
            for r in rows:
                w.writerow([r.get(k, "") for k in self.fields])
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass


def atomic_write_text(path, text):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


# =========================================================================================
# contract-spec snapshot
# =========================================================================================
def _pick(obj, fields):
    return {k: (jsonable(getattr(obj, k, None)) if obj is not None else None) for k in fields}


def spec_hash(spec):
    term = {k: v for k, v in (spec.get("terminal") or {}).items() if k not in TERMINAL_VOLATILE}
    core = {"symbol": spec.get("symbol"), "symbol_info": spec.get("symbol_info"),
            "account": spec.get("account"), "terminal": term}
    blob = json.dumps(core, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


def build_spec(mt5mod, symbol, label="", now=None):
    """Allow-listed, decoded contract snapshot. Never raises; missing pieces become None."""
    now = time.time() if now is None else now
    err = []

    def call(name, *args):
        fn = getattr(mt5mod, name, None)
        if fn is None:
            err.append("%s: not available" % name)
            return None
        try:
            return fn(*args)
        except Exception as e:
            err.append("%s: %s" % (name, e))
            return None

    si = call("symbol_info", symbol)
    acct = call("account_info")
    term = call("terminal_info")
    tick = call("symbol_info_tick", symbol)

    sym = _pick(si, SYMBOL_FIELDS)
    spec = {
        "schema": SCHEMA_VERSION,
        "symbol": symbol,
        "captured_utc": utc_str(now),
        "label": clean_label(label),
        "symbol_info": sym,
        "spread_points_now": jsonable(getattr(si, "spread", None)) if si is not None else None,
        "account": _pick(acct, ACCOUNT_FIELDS),
        "terminal": _pick(term, TERMINAL_FIELDS),
    }
    spec["decoded"] = {
        "account_kind": decode_enum(spec["account"].get("trade_mode"), ACCOUNT_TRADE_MODE),
        "margin_mode": decode_enum(spec["account"].get("margin_mode"), ACCOUNT_MARGIN_MODE),
        "symbol_trade_mode": decode_enum(sym.get("trade_mode"), SYMBOL_TRADE_MODE),
        "execution_mode": decode_enum(sym.get("trade_exemode"), EXEMODE),
        "filling_allowed_flags": decode_bits(sym.get("filling_mode"), FILLING_BITS),
        "order_types_allowed": decode_bits(sym.get("order_mode"), ORDER_MODE_BITS),
        "expiration_allowed": decode_bits(sym.get("expiration_mode"), EXPIRATION_BITS),
        "calc_mode": decode_enum(sym.get("trade_calc_mode"), CALC_MODE),
        "swap_mode": decode_enum(sym.get("swap_mode"), SWAP_MODE),
        "swap_triple_day": decode_enum(sym.get("swap_rollover3days"), WEEKDAY),
    }

    probes = {}
    bid = jsonable(getattr(tick, "bid", None)) if tick is not None else None
    if bid:
        buy = getattr(mt5mod, "ORDER_TYPE_BUY", 0)
        # Pure calculators (no order created): on US100Cash (contract_size=1.0),
        # 0.10 lot x +100 index points = $10.00 ($0.10/pt).
        probes["calc_profit_usd_0.10lot_plus_100pts"] = jsonable(
            call("order_calc_profit", buy, symbol, 0.10, bid, bid + 100.0))
        probes["calc_margin_usd_0.10lot"] = jsonable(call("order_calc_margin", buy, symbol, 0.10, bid))
        probes["price_used"] = bid
    spec["probes"] = probes
    if si is None:
        err.append("symbol_info returned None for %s" % symbol)
    if acct is None:
        err.append("account_info returned None")
    if err:
        spec["errors"] = err[:6]
    spec["hash"] = spec_hash(spec)
    return spec


# =========================================================================================
# quote window aggregation
# =========================================================================================
class QuoteWindow:
    """Accumulates the polls of one interval into a single CSV row."""

    def __init__(self, grid_epoch):
        self.grid = grid_epoch
        self.first = None
        self.smin = None
        self.smax = None
        self.n_ok = 0
        self.n_none = 0
        self.n_invalid = 0

    @property
    def n_bad(self):
        return self.n_none + self.n_invalid

    def add_ok(self, poll_epoch, bid, ask, age, offset):
        sp = ask - bid
        if self.first is None:
            self.first = (poll_epoch, bid, ask, age, offset)
        self.smin = sp if self.smin is None else min(self.smin, sp)
        self.smax = sp if self.smax is None else max(self.smax, sp)
        self.n_ok += 1

    def add_bad(self, kind):
        if kind == "bad":
            self.n_invalid += 1
        else:
            self.n_none += 1

    def row(self, digits, poll_s, stale_s=STALE_TICK_S):
        d = max(int(digits), 2)
        fmt = "%." + str(d) + "f"
        out = {"ts_utc": utc_str(self.grid), "n_ok": self.n_ok, "n_bad": self.n_bad}
        flags = []
        if self.first is None:
            flags.append("BADQUOTE" if self.n_invalid else "NOQUOTE")
            out.update(bid="", ask="", spread="", spread_min="", spread_max="",
                       tick_age_s="", srv_offset_s="")
        else:
            poll_epoch, bid, ask, age, offset = self.first
            out["bid"], out["ask"] = fmt % bid, fmt % ask
            out["spread"] = fmt % round(ask - bid, d)
            out["spread_min"] = fmt % round(self.smin, d)
            out["spread_max"] = fmt % round(self.smax, d)
            out["tick_age_s"] = "" if age is None else "%.1f" % age
            out["srv_offset_s"] = "" if offset is None else int(offset)
            if offset is None:
                flags.append("NOOFFSET")
            if age is not None and age > stale_s:
                flags.append("STALE")
            if poll_epoch - self.grid > poll_s + 1.5:
                flags.append("LATE")
            if self.n_invalid:
                flags.append("BADQUOTE")
        out["flags"] = ";".join(flags)
        return out


# =========================================================================================
# the logger
# =========================================================================================
class XmLogger:
    """All state and I/O lives here; terminal module, sleep, and clock are injected."""

    def __init__(self, mt5mod, symbol, out_dir, interval=30, poll=5, lag=LAG_S,
                 stale_s=STALE_TICK_S, backfill_bars=12000, label="", log=None,
                 spec_every_s=SPEC_EVERY_S, sleep=None, respect_market_hours=False):
        self.mt5, self.symbol, self.out_dir = mt5mod, symbol, out_dir
        self.log = log or (lambda m: print(m, flush=True))
        self.sleep = sleep or time.sleep
        self.respect_market_hours = bool(respect_market_hours)
        self.interval, self.poll, self.lag = int(interval), int(poll), float(lag)
        if self.poll < 1 or self.interval < self.poll or self.interval % self.poll:
            self.log("mt5_quotes: interval %s / poll %s are not compatible (poll must divide the "
                     "interval) - using 30 / 5" % (interval, poll))
            self.interval, self.poll = 30, 5
        self.stale_s, self.backfill_bars = stale_s, int(backfill_bars)
        self.label, self.spec_every_s = clean_label(label), spec_every_s
        self.tf_m15 = getattr(mt5mod, "TIMEFRAME_M15", 15)

        self.window = None
        self.started_at = None
        self.last_stamp = None
        self.last_bar_open_utc = None
        self.offset = None
        self.prev_offset = None
        self._pending_offset = None
        self._prev_tick_time = None
        self.digits = 2
        self.last_ok_poll = None
        self.last_reinit = -1e18
        self.last_candle_try = -1e18
        self.last_candle_target = None
        self.next_spec_at = 0.0
        self.last_spec_hash = None
        self.next_heartbeat = 0.0
        self.last_spread = None
        self.rows_written = 0
        self.candles_written = 0
        self._appenders = {}
        self._err_seen = {}

    # ---- plumbing ------------------------------------------------------------------
    def _err(self, key, msg, now):
        if now - self._err_seen.get(key, -1e18) >= ERR_LOG_EVERY_S:
            self._err_seen[key] = now
            self.log("mt5_quotes: %s" % msg)

    def _appender(self, path, fields):
        a = self._appenders.get(path)
        if a is None:
            a = self._appenders[path] = CsvAppender(path, fields, log=self.log)
        return a

    def quotes_path(self, epoch):
        return os.path.join(self.out_dir, "%s%s.csv" % (
            QUOTES_PREFIX, datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%d")))

    @property
    def candles_path(self):
        return os.path.join(self.out_dir, CANDLES_FILE)

    def grid(self, now):
        return int((now - self.lag + 0.5) // self.interval) * self.interval

    def next_poll_time(self, now):
        return (math.floor((now - self.lag) / self.poll) + 1) * self.poll + self.lag

    def off_txt(self):
        return "unknown" if self.offset is None else "%+gh" % (self.offset / 3600.0)

    # ---- start-up ------------------------------------------------------------------
    def learn_digits(self):
        try:
            d = getattr(self.mt5.symbol_info(self.symbol), "digits", None)
        except Exception:
            d = None
        if isinstance(d, int) and 0 <= d <= 8:
            self.digits = d

    def resume(self, now):
        last_q = last_csv_row(self.quotes_path(now), QUOTE_FIELDS)
        if last_q:
            try:
                self.last_stamp = parse_utc(last_q["ts_utc"])
            except ValueError:
                pass
        last_c = last_csv_row(self.candles_path, CANDLE_FIELDS)
        if last_c:
            try:
                self.last_bar_open_utc = int(parse_utc(last_c["bar_close_utc"])) - M15_SECONDS
            except ValueError:
                pass

    def learn_offset(self, now, tries=10, clock=None):
        clock = clock or time.time
        for _ in range(tries):
            self._poll_tick(now)
            if self.offset is not None:
                return True
            self.sleep(1.0)
            now = clock()
        return False

    def start(self, now, clock=None):
        os.makedirs(self.out_dir, exist_ok=True)
        self.started_at = now
        self.learn_digits()
        self.resume(now)
        self.learn_offset(now, clock=clock)
        spec = self.snapshot_spec(now, force=True) or {}
        self.log("mt5_quotes: %s | account %s | server offset %s | quotes every %ds (poll %ds) -> %s"
                 " | resume: last quote %s, last candle %s" % (
                     self.symbol, (spec.get("decoded") or {}).get("account_kind") or "?",
                     self.off_txt(), self.interval, self.poll, self.out_dir,
                     utc_str(self.last_stamp) if self.last_stamp else "none",
                     utc_str(self.last_bar_open_utc + M15_SECONDS) if self.last_bar_open_utc else "none"))

    # ---- tick handling -------------------------------------------------------------
    def _poll_tick(self, now):
        try:
            t = self.mt5.symbol_info_tick(self.symbol)
        except Exception as e:
            self._err("tick", "symbol_info_tick failed: %s" % e, now)
            return ("none",)
        if t is None:
            return ("none",)
        try:
            bid, ask, tt = float(t.bid), float(t.ask), int(t.time)
        except (AttributeError, TypeError, ValueError):
            return ("bad",)
        if not (bid > 0 and ask > 0 and ask >= bid):
            return ("bad",)
        fresh = self._prev_tick_time is not None and tt != self._prev_tick_time
        self._prev_tick_time = tt
        if fresh:
            self._note_offset(estimate_offset(tt, now))
        return ("ok", bid, ask, tt)

    def _note_offset(self, cand):
        if cand is None:
            return
        if self.offset is None:
            self.offset = cand
            return
        if cand == self.offset:
            self._pending_offset = None
            return
        n = self._pending_offset[1] + 1 if (self._pending_offset and self._pending_offset[0] == cand) else 1
        self._pending_offset = (cand, n)
        if n >= OFFSET_CONFIRM:
            self.log("mt5_quotes: server offset changed %s -> %+gh (DST?)" % (self.off_txt(), cand / 3600.0))
            self.prev_offset, self.offset, self._pending_offset = self.offset, cand, None

    # ---- one poll ------------------------------------------------------------------
    def step(self, now):
        g = self.grid(now)
        if self.window is None or self.window.grid != g:
            self.flush_window(now)
            self.window = QuoteWindow(g)
        res = self._poll_tick(now)
        if res[0] == "ok":
            _, bid, ask, tt = res
            self.window.add_ok(now, bid, ask, tick_age_s(tt, self.offset, now), self.offset)
            self.last_ok_poll = now
            self.last_spread = ask - bid
            self._maybe_sync_candles(now, tt)
        else:
            self.window.add_bad(res[0])
        self._watchdog(now)
        if now >= self.next_spec_at:
            self.snapshot_spec(now)
        if now >= self.next_heartbeat:
            self.next_heartbeat = now + HEARTBEAT_S
            self.log("mt5_quotes: %s UTC | spread %s | rows written %d | candles written %d | "
                     "offset %s" % (utc_str(now)[:16],
                                    "n/a" if self.last_spread is None else "%.2f pts" % self.last_spread,
                                    self.rows_written, self.candles_written, self.off_txt()))
        return res

    def _watchdog(self, now):
        if self.respect_market_hours and is_cme_closed(now):
            # Do not restart-loop during CME weekend closure or daily 17:00-18:00 ET break
            self.last_ok_poll = now
            return
        ref = self.last_ok_poll if self.last_ok_poll is not None else (
            self.started_at if self.started_at is not None else now)
        quiet = now - ref
        if quiet > REINIT_AFTER_S and now - self.last_reinit > REINIT_AFTER_S:
            self.last_reinit = now
            self._err("reinit", "no valid quote for %.0f s - re-initializing the MT5 link" % quiet, now)
            try:
                self.mt5.shutdown()
                if self.mt5.initialize():
                    self.mt5.symbol_select(self.symbol, True)
            except Exception as e:
                self._err("reinit2", "re-initialize failed: %s" % e, now)
        if quiet > DEAD_AFTER_S:
            self.flush_window(now)
            self.log("mt5_quotes: no valid quote for %.0f s - exiting for a clean restart" % quiet)
            raise SystemExit(2)

    # ---- quote rows ----------------------------------------------------------------
    def flush_window(self, now):
        w, self.window = self.window, None
        if w is None or (w.n_ok == 0 and w.n_bad == 0):
            return None
        if self.last_stamp is not None and w.grid <= self.last_stamp:
            return None
        row = w.row(self.digits, self.poll, self.stale_s)
        try:
            self._appender(self.quotes_path(w.grid), QUOTE_FIELDS).append([row])
        except OSError as e:
            self._err("write-quote", "cannot write quote row: %s" % e, now)
            return None
        self.last_stamp = w.grid
        self.rows_written += 1
        return row

    # ---- candles -------------------------------------------------------------------
    def _last_bar_srv(self):
        if self.last_bar_open_utc is None or self.offset is None:
            return None
        return self.last_bar_open_utc + self.offset

    def _maybe_sync_candles(self, now, tick_time_srv):
        if self.offset is None:
            return
        closed_srv = (int(tick_time_srv) // M15_SECONDS) * M15_SECONDS - M15_SECONDS
        last = self._last_bar_srv()
        if last is not None and closed_srv <= last:
            return
        if self.last_candle_target == closed_srv and now - self.last_candle_try < CANDLE_RETRY_S:
            return
        self.last_candle_try, self.last_candle_target = now, closed_srv
        self.sync_candles(now, closed_srv)

    def fetch_rates(self, want, now, settle=False):
        best, prev = [], -1
        for _ in range(SETTLE_TRIES if settle else 1):
            try:
                rates = self.mt5.copy_rates_from_pos(self.symbol, self.tf_m15, 1, int(want))
            except Exception as e:
                self._err("rates", "copy_rates_from_pos failed: %s" % e, now)
                rates = None
            n = 0 if rates is None else len(rates)
            if n > len(best):
                best = list(rates)
            if not settle or n >= want or n <= prev:
                break
            prev = n
            self.sleep(SETTLE_WAIT_S)
        return best

    def candle_rows(self, rates, now, after_utc=None):
        cands = [o for o in (self.offset, self.prev_offset) if o is not None]
        if not cands:
            return []
        fmt = "%." + str(max(self.digits, 2)) + "f"
        picked = {}
        for r in rates:
            try:
                t = int(r["time"])
                for off in cands:
                    u = t - off
                    if after_utc is not None and u <= after_utc:
                        continue
                    if u + M15_SECONDS > now + FUTURE_SLACK_S:
                        continue
                    try:
                        sp = int(r["spread"])
                    except (KeyError, IndexError, TypeError, ValueError):
                        sp = ""
                    picked.setdefault(u, {
                        "bar_close_utc": utc_str(u + M15_SECONDS),
                        "open": fmt % float(r["open"]), "high": fmt % float(r["high"]),
                        "low": fmt % float(r["low"]), "close": fmt % float(r["close"]),
                        "tick_volume": int(r["tick_volume"]), "spread_pts": sp,
                        "time_srv": t, "offset_s": int(off),
                    })
                    break
            except (KeyError, IndexError, TypeError, ValueError):
                continue
        return [picked[u] for u in sorted(picked)]

    def sync_candles(self, now, closed_srv):
        if self.offset is None:
            return 0
        last = self._last_bar_srv()
        first_run = last is None
        if first_run:
            want, settle = self.backfill_bars, True
        else:
            gap = (closed_srv - last) // M15_SECONDS
            if gap <= 0:
                return 0
            want, settle = min(MAX_FETCH_BARS, int(gap)), False
        rates = self.fetch_rates(want, now, settle=settle)
        rows = self.candle_rows(rates, now, after_utc=self.last_bar_open_utc)
        if not rows:
            return 0
        try:
            self._appender(self.candles_path, CANDLE_FIELDS).append(rows)
        except OSError as e:
            self._err("write-candle", "cannot write candles: %s" % e, now)
            return 0
        self.last_bar_open_utc = int(parse_utc(rows[-1]["bar_close_utc"])) - M15_SECONDS
        self.candles_written += len(rows)
        if first_run:
            self.log("mt5_quotes: first run - back-filled %d closed M15 bars (asked for %d; %s -> %s "
                     "UTC close). The terminal serves at most its 'Max bars in chart'." % (
                         len(rows), want, rows[0]["bar_close_utc"], rows[-1]["bar_close_utc"]))
        elif len(rows) > 1:
            self.log("mt5_quotes: healed a gap of %d closed M15 bars up to %s UTC" % (
                len(rows), rows[-1]["bar_close_utc"]))
        return len(rows)

    # ---- contract spec -------------------------------------------------------------
    def snapshot_spec(self, now, force=False):
        if not force and now < self.next_spec_at:
            return None
        self.next_spec_at = now + self.spec_every_s
        spec = build_spec(self.mt5, self.symbol, self.label, now)
        prev = self.last_spec_hash if self.last_spec_hash is not None else self._history_last_hash()
        try:
            atomic_write_text(os.path.join(self.out_dir, SPEC_FILE),
                              json.dumps(spec, indent=2, sort_keys=True) + "\n")
            if spec["hash"] != prev:
                with open(os.path.join(self.out_dir, SPEC_HISTORY_FILE), "a",
                          newline="", encoding="utf-8") as f:
                    f.write(json.dumps(spec, sort_keys=True, separators=(",", ":")) + "\n")
                dec = spec["decoded"]
                self.log("mt5_quotes: contract spec %s (hash %s): %s, %s execution, filling %s, "
                         "stops level %s" % ("recorded" if prev is None else "CHANGED", spec["hash"],
                                             dec.get("account_kind"), dec.get("execution_mode"),
                                             dec.get("filling_allowed_flags"),
                                             spec["symbol_info"].get("trade_stops_level")))
        except OSError as e:
            self._err("write-spec", "cannot write the spec snapshot: %s" % e, now)
        self.last_spec_hash = spec["hash"]
        return spec

    def _history_last_hash(self):
        try:
            with open(os.path.join(self.out_dir, SPEC_HISTORY_FILE), "rb") as f:
                f.seek(0, os.SEEK_END)
                f.seek(max(0, f.tell() - 65536))
                lines = [x for x in f.read().decode("utf-8", "replace").splitlines() if x.strip()]
            return json.loads(lines[-1]).get("hash") if lines else None
        except Exception:
            return None

    # ---- run -----------------------------------------------------------------------
    def run_forever(self, clock=None):
        clock = clock or time.time
        self.start(clock(), clock=clock)
        target = 0.0
        try:
            while True:
                now = clock()
                target = self.next_poll_time(max(now, target))
                if target > now:
                    self.sleep(target - now)
                try:
                    self.step(clock())
                except SystemExit:
                    raise
                except Exception as e:
                    self._err("step", "poll error: %s (continuing)" % e, clock())
        except KeyboardInterrupt:
            pass
        finally:
            self.flush_window(clock())


def merge_candles(path, rows):
    """Merge `rows` into the candle file keyed by bar_close_utc: sorted, unique, atomic."""
    by_key = {}
    for r in read_csv_rows(path, CANDLE_FIELDS):
        by_key[r["bar_close_utc"]] = r
    added = 0
    for r in rows:
        k = r["bar_close_utc"]
        if k not in by_key:
            by_key[k] = {f: str(r.get(f, "")) for f in CANDLE_FIELDS}
            added += 1
    lines = [",".join(CANDLE_FIELDS)]
    for k in sorted(by_key):
        lines.append(",".join(str(by_key[k].get(f, "")) for f in CANDLE_FIELDS))
    atomic_write_text(path, "\n".join(lines) + "\n")
    return added, len(by_key)


# =========================================================================================
# CLI
# =========================================================================================
def _connect(symbol, m):
    if m is None:
        print("mt5_quotes: MetaTrader5 package missing - install it in the WINE python:\n"
              "  wine C:/Python312/python.exe -m pip install MetaTrader5", flush=True)
        sys.exit(1)
    if not m.initialize():
        print("mt5_quotes: MT5 initialize failed: %s (is the terminal running and logged in, "
              "in this prefix?)" % (m.last_error(),), flush=True)
        sys.exit(1)
    if not m.symbol_select(symbol, True):
        print("mt5_quotes: symbol_select(%s) failed: %s (check the exact symbol name in Market "
              "Watch; XM uses US100Cash for Nasdaq-100 Cash CFD)" % (symbol, m.last_error()), flush=True)
        sys.exit(1)


def main(argv=None, mt5mod=None, clock=None, sleep=None):
    ap = argparse.ArgumentParser(description="XM US100Cash quote + contract-spec logger (read-only)")
    ap.add_argument("--spec", action="store_true", help="print the contract-spec snapshot; write nothing")
    ap.add_argument("--once", action="store_true", help="one cycle, then exit")
    ap.add_argument("--backfill", type=int, metavar="N",
                    help="merge the last N closed M15 bars into candles_m15.csv, then exit "
                         "(stop mt5quotes-nasdaq first: the merge rewrites the file)")
    ap.add_argument("--dir", default=os.environ.get("MT5_QUOTES_DIR", DEFAULT_DIR))
    a = ap.parse_args(argv)

    m = mt5mod if mt5mod is not None else mt5
    clock = clock or time.time
    symbol = os.environ.get("MT5_QUOTES_SYMBOL", "US100Cash")
    label = os.environ.get("MT5_QUOTES_LABEL", "")
    respect_hours = os.environ.get("MT5_QUOTES_SKIP_QUIET", "1").strip() not in ("0", "false", "no")
    _connect(symbol, m)
    try:
        if a.spec:
            print(json.dumps(build_spec(m, symbol, label, clock()), indent=2, sort_keys=True))
            return 0
        lg = XmLogger(m, symbol, a.dir,
                      interval=_env_num("MT5_QUOTES_INTERVAL", 30), poll=_env_num("MT5_QUOTES_POLL", 5),
                      backfill_bars=_env_num("MT5_QUOTES_BACKFILL_BARS", 12000), label=label,
                      sleep=sleep, respect_market_hours=(respect_hours and not a.once))
        if a.backfill:
            os.makedirs(a.dir, exist_ok=True)
            lg.learn_digits()
            if not lg.learn_offset(clock(), clock=clock):
                print("mt5_quotes: server offset unknown (no fresh tick) - cannot stamp UTC; "
                      "retry while the market is quoting", flush=True)
                return 1
            rates = lg.fetch_rates(a.backfill, clock(), settle=True)
            added, total = merge_candles(lg.candles_path, lg.candle_rows(rates, clock()))
            print("mt5_quotes: backfill asked for %d bars, terminal returned %d, %d new rows merged "
                  "(file now %d rows, offset %s)" % (a.backfill, len(rates), added, total, lg.off_txt()),
                  flush=True)
            return 0
        if a.once:
            lg.start(clock(), clock=clock)
            lg.step(clock())
            row = lg.flush_window(clock())
            last = last_csv_row(lg.candles_path, CANDLE_FIELDS) or {}
            print("mt5_quotes --once: quote row = %s" % (row,), flush=True)
            print("mt5_quotes --once: candles written this run %d, newest bar_close_utc in file = %s"
                  % (lg.candles_written, last.get("bar_close_utc", "none")), flush=True)
            return 0
        try:
            lg.run_forever(clock=clock)
        finally:
            print("mt5_quotes: stopped", flush=True)
        return 0
    finally:
        m.shutdown()


if __name__ == "__main__":
    sys.exit(main())
