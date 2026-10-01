#!/usr/bin/env python3
"""
live_path_probe - does engine.py's LIVE order path survive contact with a broker?

Runs engine.BitcoinEngine with TRADING_MODE forced to "LIVE" against a FAKE
MetaTrader5 module that follows the DOCUMENTED MQL5 semantics:

  * history_deals_get(ticket=X)   -> deals whose DEAL_ORDER == X   (an ORDER ticket)
  * history_deals_get(position=X) -> deals whose DEAL_POSITION_ID == X
  * a server-side SL/TP close is executed under a NEW order ticket, so it is not
    found by the entry order's ticket
    (https://www.mql5.com/en/docs/python_metatrader5/mt5historydealsget_py)

Why this exists: the forward test never executes execute_live_trade /
check_live_exits / restart-with-an-open-position, and tools/smoke_test.py has no
LIVE scenario - so the order path has never run anywhere. The probes below are
the questions a demo-account run would answer, asked cheaply and offline. The
findings (docs/REVIEW-2026-10-01.md section 6) are why TRADING_MODE must stay
FORWARD_TEST.

Safety: no real terminal, no network, no Telegram, no /opt/bitcoin and none of
the repo's data files are touched - the engine runs against temp directories,
`requests`/`dotenv`/`twelvedata` are stubbed, and engine.py is only READ (its
source is exec'd in a throwaway module with TRADING_MODE swapped).

THIS IS NOT A SUBSTITUTE FOR A DEMO-ACCOUNT RUN: the fake encodes what the docs
say, not what XM's server does (filling modes, execution mode and retcodes are
broker-specific). Fix the findings, keep this probe green, THEN go to demo.

Severity: BLOCKER / HIGH findings make the exit code 1; ADVISORY items are
"verify on the demo account" notes.

Usage:  python3 tools/live_path_probe.py
"""
import collections
import json
import os
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

# ---- stub third-party deps (same approach as tools/smoke_test.py, but forced) ----
for _name in ("requests", "dotenv", "twelvedata"):
    _mod = types.ModuleType(_name)
    if _name == "requests":
        _mod.post = lambda *a, **k: None          # nothing can reach Telegram
    if _name == "dotenv":
        _mod.load_dotenv = lambda *a, **k: None   # .env is never read
    if _name == "twelvedata":
        _mod.TDClient = object
    sys.modules[_name] = _mod

Deal = collections.namedtuple("Deal", "ticket order position_id entry profit price")
Res = collections.namedtuple("Res", "retcode order deal comment")


class FakeMT5(types.ModuleType):
    """Just enough of the MetaTrader5 module, with the documented lookup semantics."""
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    TRADE_ACTION_DEAL = 1
    ORDER_TIME_GTC = 0
    ORDER_FILLING_FOK = 0
    ORDER_FILLING_IOC = 1
    ORDER_FILLING_RETURN = 2
    TRADE_RETCODE_DONE = 10009
    DEAL_ENTRY_IN = 0
    DEAL_ENTRY_OUT = 1
    TIMEFRAME_M5 = 5

    def __init__(self):
        super().__init__("MetaTrader5")
        self.reset()

    def reset(self):
        self.deals, self.sent, self.positions = [], [], []
        self.bid, self.ask = 83000.0, 83040.0        # $40 = the measured XM spread
        self.symbol_filling = self.ORDER_FILLING_IOC  # a symbol that does NOT allow FOK
        self.next_order = 1001
        self.send_returns_none = False

    # --- terminal / symbol -------------------------------------------------
    def initialize(self):
        return True

    def last_error(self):
        return (1, "ok")

    def account_info(self):
        return types.SimpleNamespace(login=1, balance=200.0, currency="USD", trade_mode=0)

    def symbol_select(self, symbol, enable):
        return True

    def symbol_info(self, symbol):
        return types.SimpleNamespace(point=0.01, filling_mode=self.symbol_filling)

    def symbol_info_tick(self, symbol):
        return types.SimpleNamespace(bid=self.bid, ask=self.ask)

    # --- trading -----------------------------------------------------------
    def order_send(self, request):
        self.sent.append(request)
        if self.send_returns_none:
            return None
        order = self.next_order
        self.next_order += 1
        self.deals.append(Deal(order + 1000, order, order, self.DEAL_ENTRY_IN, 0.0, request["price"]))
        return Res(self.TRADE_RETCODE_DONE, order, order + 1000, "done")

    def positions_get(self, *a, **k):
        return tuple(self.positions)

    def history_deals_get(self, *a, ticket=None, position=None, **k):
        out = [d for d in self.deals
               if (ticket is None or d.order == ticket) and (position is None or d.position_id == position)]
        return tuple(out) if out else ()

    def server_closes_position(self, position_id, price, profit):
        """SL/TP fires on the broker: a NEW order ticket carries the closing deal."""
        order = self.next_order
        self.next_order += 1
        self.deals.append(Deal(order + 1000, order, position_id, self.DEAL_ENTRY_OUT, profit, price))


fake = FakeMT5()
sys.modules["MetaTrader5"] = fake

# ---- load engine.py's source as a LIVE-mode module (the file itself is untouched) ----
_src = open(os.path.join(ROOT, "engine.py"), encoding="utf-8").read()
if 'TRADING_MODE = "FORWARD_TEST"' not in _src:
    sys.exit("live_path_probe: engine.py no longer has the TRADING_MODE = \"FORWARD_TEST\" line "
             "this probe swaps - update the probe")
_src = _src.replace('TRADING_MODE = "FORWARD_TEST"', 'TRADING_MODE = "LIVE"', 1)
engine = types.ModuleType("engine_live_probe")
engine.__file__ = os.path.join(ROOT, "engine.py")
sys.modules["engine_live_probe"] = engine
import trade_filter  # noqa: E402

exec(compile(_src, "engine.py[LIVE-probe]", "exec"), engine.__dict__)

FINDINGS = []   # (severity, label, ok)


def check(severity, label, ok, detail=""):
    FINDINGS.append((severity, label, ok))
    tag = "ok" if ok else severity
    print(f"  [{tag:8s}] {label}" + (f"  ({detail})" if detail else ""))


def fresh_engine(tmp, status=None):
    engine.LOG_FILE_PATH = os.path.join(tmp, "log.csv")
    engine.STATUS_FILE_PATH = os.path.join(tmp, "status.json")
    engine.TRADES_LOG_PATH = os.path.join(tmp, "trades.csv")
    trade_filter.TRADES_LOG = engine.TRADES_LOG_PATH
    trade_filter.SKIP_LOG = os.path.join(tmp, "skips.csv")
    if status:
        with open(engine.STATUS_FILE_PATH, "w") as fh:
            json.dump(status, fh)
    eng = engine.BitcoinEngine()
    eng.atr, eng.rsi, eng.ema_fast, eng.ema_slow = 100.0, 50.0, 83000.0, 82900.0
    return eng


def quiet(fn, *a, **k):
    """Run engine code with its chatty prints suppressed (the verdict lines are ours)."""
    import contextlib
    import io
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **k)


def probe_close_detection():
    print("Probe 1 - the broker closes the position (SL/TP): does the engine notice and log it?")
    with tempfile.TemporaryDirectory() as tmp:
        fake.reset()
        e = quiet(fresh_engine, tmp)
        quiet(e.execute_live_trade, "BUY", 83040.0, 0.3, "2026-10-01 00:00:00")
        check("BLOCKER", "entry accepted and tracked (sanity)", e.trade_active_live and e.active_ticket == 1001)
        fake.server_closes_position(position_id=1001, price=82840.0, profit=-2.00)
        quiet(e.check_live_exits)
        check("BLOCKER", "broker-side close is detected and logged",
              (not e.trade_active_live) and e.losses == 1,
              f"trade_active_live={e.trade_active_live} losses={e.losses}; the engine asks "
              "history_deals_get(ticket=<ENTRY order>) but the close is a different order")


def probe_restart():
    print("\nProbe 2 - the process restarts (autosync deploy, crash) while a position is open")
    with tempfile.TemporaryDirectory() as tmp:
        fake.reset()
        status = {"trade_active": True, "trade_type": "BUY", "entry_price": 83040.0,
                  "stop_loss": 82840.0, "take_profit": 83440.0, "entry_time": "2026-10-01 00:00:00",
                  "current_trade_num": 5, "entry_rsi": 50.0, "entry_atr": 100.0}
        e = quiet(fresh_engine, tmp, status)
        check("BLOCKER", "restored engine re-attaches to the broker position",
              e.trade_active_live and e.active_ticket is not None,
              f"trade_active={e.trade_active} trade_active_live={e.trade_active_live} "
              f"active_ticket={e.active_ticket}; run_live never calls check_position, "
              "check_live_exits needs the ticket")
        fake.deals.append(Deal(2001, 1001, 1001, fake.DEAL_ENTRY_IN, 0.0, 83040.0))
        fake.server_closes_position(position_id=1001, price=83440.0, profit=+4.00)
        quiet(e.check_live_exits)
        check("BLOCKER", "after the broker closes it, the engine leaves the 'in trade' state",
              not (e.trade_active or e.trade_active_live),
              f"trade_active={e.trade_active}: no new signal can ever fire and the fill is never logged")


def probe_spread_guard():
    print("\nProbe 3 - order dispatch while the spread is abnormal ($500: weekend / news)")
    with tempfile.TemporaryDirectory() as tmp:
        fake.reset()
        fake.bid, fake.ask = 83000.0, 83500.0
        e = quiet(fresh_engine, tmp)
        quiet(e.execute_live_trade, "BUY", 83000.0, 0.3, "2026-10-01 00:00:00")
        check("BLOCKER", "no order is sent when spread >> the assumed $40", len(fake.sent) == 0,
              f"orders sent={len(fake.sent)} at ask-bid=${fake.ask - fake.bid:.0f} "
              "(the handoff already names a live spread check as a LIVE blocker)")


def probe_request_hygiene():
    print("\nProbe 4 - order request hygiene")
    with tempfile.TemporaryDirectory() as tmp:
        fake.reset()
        e = quiet(fresh_engine, tmp)
        quiet(e.execute_live_trade, "SELL", 83000.0, 0.3, "2026-10-01 00:00:00")
        req = fake.sent[-1] if fake.sent else {}
        check("HIGH", "type_filling follows the symbol's allowed filling modes (this fake symbol allows IOC only)",
              req.get("type_filling") == fake.symbol_filling,
              f"sent type_filling={req.get('type_filling')} (0 = FOK, hard-coded); "
              "a real server answers retcode 10030 INVALID_FILL")
        dev_usd = req.get("deviation", 0) * 0.01
        check("ADVISORY", "deviation is a deliberate value for this symbol's execution mode",
              dev_usd >= 5.0,
              f"deviation={req.get('deviation')} points = ${dev_usd:.2f} on a 0.01-point symbol; irrelevant under "
              "Market Execution, a requote storm under Instant - check symbol_info().trade_exemode on the demo")


def probe_unknown_state():
    print("\nProbe 5 - order_send returns None (terminal disconnect / timeout): is the state safe?")
    with tempfile.TemporaryDirectory() as tmp:
        fake.reset()
        fake.send_returns_none = True
        e = quiet(fresh_engine, tmp)
        raised = None
        try:
            quiet(e.execute_live_trade, "BUY", 83040.0, 0.3, "2026-10-01 00:00:00")
        except Exception as ex:   # noqa: BLE001 - the point is to see what escapes
            raised = type(ex).__name__
        check("HIGH", "a None result is handled (no exception; position reconciled before any retry)",
              raised is None, f"raised={raised}")


def probe_duplicate_exposure():
    print("\nProbe 6 - the broker already holds a position with this bot's magic number")
    with tempfile.TemporaryDirectory() as tmp:
        fake.reset()
        fake.positions = [types.SimpleNamespace(ticket=555, magic=engine.MAGIC_NUMBER, symbol="BTCUSD",
                                                type=0, volume=0.01)]
        e = quiet(fresh_engine, tmp)       # fresh state: the engine believes it is flat
        quiet(e.execute_live_trade, "BUY", 83040.0, 0.3, "2026-10-01 00:00:00")
        check("HIGH", "no second order is sent while a position with our magic is open", len(fake.sent) == 0,
              f"orders sent={len(fake.sent)}; engine.py never calls positions_get, so only its in-memory "
              "flag stands between a restart/None-result and double exposure")


def main():
    print("live_path_probe - engine.py LIVE path vs a fake MT5 (documented semantics), temp dirs only\n")
    for probe in (probe_close_detection, probe_restart, probe_spread_guard, probe_request_hygiene,
                  probe_unknown_state, probe_duplicate_exposure):
        probe()
    bad = [f for f in FINDINGS if not f[2]]
    blockers = [f for f in bad if f[0] in ("BLOCKER", "HIGH")]
    adv = [f for f in bad if f[0] == "ADVISORY"]
    print(f"\n{len(FINDINGS) - len(bad)}/{len(FINDINGS)} checks clean | "
          f"{sum(1 for f in bad if f[0] == 'BLOCKER')} BLOCKER, {sum(1 for f in bad if f[0] == 'HIGH')} HIGH, "
          f"{len(adv)} ADVISORY")
    if blockers:
        print("LIVE PATH NOT READY - keep TRADING_MODE = FORWARD_TEST (docs/REVIEW-2026-10-01.md section 6).")
        return 1
    print("No blocker/high findings against the fake. Next gate: the demo-account run (the fake is not XM).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
