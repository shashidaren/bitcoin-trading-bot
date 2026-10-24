#!/usr/bin/env python3
"""
Execution-safety probe for engine.py's LIVE path (direct MetaTrader5 AND Linux
Wine mt5_bridge/ sidecar) on US100Cash.

Runs ONLY in temporary directories against an in-process fake MetaTrader5 module:
never touches repo files, never opens a socket, never talks to a terminal.

Exit 0 = all BLOCKER and HIGH checks passed.
Exit 1 = at least one BLOCKER or HIGH finding failed.
"""
import contextlib
import csv
import importlib.util
import io
import json
import os
import sys
import tempfile
import threading
import time
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import trade_filter as TF  # noqa: E402


class FakeMT5(types.ModuleType):
    """Minimal MetaTrader5 surface matching documented MQL5 Python API semantics."""
    TRADE_ACTION_DEAL = 1
    TRADE_ACTION_SLTP = 6
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    ORDER_TIME_GTC = 0
    ORDER_FILLING_FOK = 0
    ORDER_FILLING_IOC = 1
    ORDER_FILLING_RETURN = 2
    SYMBOL_FILLING_FOK = 1     # bitmask on symbol_info().filling_mode
    SYMBOL_FILLING_IOC = 2     # bitmask 2 -> ORDER_FILLING_IOC = 1
    TRADE_RETCODE_DONE = 10009
    ACCOUNT_TRADE_MODE_DEMO = 0
    ACCOUNT_TRADE_MODE_CONTEST = 1
    ACCOUNT_TRADE_MODE_REAL = 2
    DEAL_ENTRY_IN = 0
    DEAL_ENTRY_OUT = 1
    DEAL_ENTRY_OUT_BY = 3
    DEAL_REASON_SL = 4
    DEAL_REASON_TP = 5

    def __init__(self):
        super().__init__("MetaTrader5")
        self.reset()

    def reset(self):
        self.sent = []
        self.checked = []
        self.positions = []
        self.deals = []
        self.bid = 20500.00
        self.ask = 20502.50
        self.balance = 200.00
        self.equity = 200.00
        self.symbol_filling = self.SYMBOL_FILLING_IOC
        self.send_returns_none = False
        self.retcode = self.TRADE_RETCODE_DONE
        self.trade_mode = self.ACCOUNT_TRADE_MODE_DEMO
        self._next_ticket = 9001

    def initialize(self, **_kw):
        return True

    def shutdown(self):
        return None

    def last_error(self):
        return (1, "Success")

    def terminal_info(self):
        return types.SimpleNamespace(connected=True, trade_allowed=True)

    def account_info(self):
        return types.SimpleNamespace(
            login=12345678,
            server="XMGlobal-MT5 7",
            trade_mode=self.trade_mode,
            trade_allowed=True,
            balance=self.balance,
            equity=self.equity,
            currency="USD",
        )

    def symbol_select(self, _sym, _enable=True):
        return True

    def symbol_info(self, sym):
        return types.SimpleNamespace(
            name=sym,
            visible=True,
            filling_mode=self.symbol_filling,
            trade_mode=4,
            digits=2,
            point=0.01,
            trade_contract_size=1.0,
            trade_stops_level=0,
            volume_min=0.10,
            volume_max=500.0,
            volume_step=0.01,
        )

    def symbol_info_tick(self, _sym):
        return types.SimpleNamespace(bid=self.bid, ask=self.ask, last=self.bid, time=int(time.time()))

    def positions_get(self, **kw):
        ps = list(self.positions)
        if "symbol" in kw:
            ps = [p for p in ps if p.symbol == kw["symbol"]]
        if "ticket" in kw:
            ps = [p for p in ps if p.ticket == kw["ticket"]]
        return tuple(ps)

    def history_deals_get(self, _from_dt=None, _to_dt=None, **kw):
        ds = list(self.deals)
        if "position" in kw:
            ds = [d for d in ds if getattr(d, "position_id", None) == kw["position"]]
        return tuple(ds)

    def order_check(self, request):
        self.checked.append(dict(request))
        return types.SimpleNamespace(retcode=0, comment="Done")

    def order_send(self, request):
        self.sent.append(dict(request))
        if self.send_returns_none:
            return None
        if self.retcode != self.TRADE_RETCODE_DONE:
            return types.SimpleNamespace(retcode=self.retcode, comment="rejected")
        fill = self.ask if request.get("type") == self.ORDER_TYPE_BUY else self.bid
        t = self._next_ticket
        self._next_ticket += 1
        if request.get("position"):
            self.positions = [p for p in self.positions if p.ticket != request["position"]]
            return types.SimpleNamespace(retcode=self.TRADE_RETCODE_DONE, order=t, deal=t + 500,
                                         price=fill, volume=request.get("volume", 0.10), comment="closed")
        self.positions.append(types.SimpleNamespace(
            ticket=t, identifier=t, symbol=request["symbol"], type=request["type"],
            volume=request["volume"], price_open=fill,
            sl=request.get("sl", 0.0), tp=request.get("tp", 0.0),
            profit=0.0, swap=0.0, magic=request.get("magic", 0),
            time=int(time.time()), comment=request.get("comment", ""),
        ))
        return types.SimpleNamespace(retcode=self.TRADE_RETCODE_DONE, order=t, deal=t + 100,
                                     price=fill, volume=request["volume"], comment="filled")


fake = FakeMT5()
sys.modules["MetaTrader5"] = fake
for _mod_name in ("requests", "dotenv", "twelvedata"):
    if _mod_name not in sys.modules:
        _m = types.ModuleType(_mod_name)
        if _mod_name == "requests":
            _m.post = lambda *_a, **_k: None
        elif _mod_name == "dotenv":
            _m.load_dotenv = lambda *_a, **_k: False
        elif _mod_name == "twelvedata":
            _m.TDClient = object
        sys.modules[_mod_name] = _m

with open(os.path.join(ROOT, "engine.py"), encoding="utf-8") as _fh:
    _src = _fh.read()
assert 'TRADING_MODE = "FORWARD_TEST"' in _src, "engine.py did not declare TRADING_MODE = FORWARD_TEST"
_spec = importlib.util.spec_from_loader("engine_live_under_test", loader=None)
engine = importlib.util.module_from_spec(_spec)
exec(compile(_src.replace('TRADING_MODE = "FORWARD_TEST"', 'TRADING_MODE = "LIVE"', 1),
             os.path.join(ROOT, "engine.py"), "exec"), engine.__dict__)

import mt5_executor as MTE  # noqa: E402


def quiet(fn, *a, **kw):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **kw)


def fresh_engine(tmp, use_bridge=False):
    engine.TRADES_LOG_PATH = os.path.join(tmp, "trades.csv")
    engine.LOG_FILE_PATH = os.path.join(tmp, "forward_test_log.csv")
    engine.STATUS_FILE_PATH = os.path.join(tmp, "status.json")
    engine.MT5_FEED_FILE = os.path.join(tmp, "mt5_last_candle.json")
    engine.MT5_WARMUP_FILE = os.path.join(tmp, "mt5_warmup_candles.json")
    engine.MT5_ORDER_DIR = os.path.join(tmp, "mt5_bridge")
    engine.JOURNAL_FILE_PATH = os.path.join(tmp, "journal.csv")
    TF.TRADES_LOG = engine.TRADES_LOG_PATH
    TF.SKIP_LOG = os.path.join(tmp, "skipped_trades.csv")
    engine.mt5 = None if use_bridge else fake
    e = quiet(engine.NasdaqEngine)
    e.atr = 65.0
    e.rsi = 54.0
    e.ema_fast = 20510.0
    e.ema_slow = 20420.0
    return e


FINDINGS = []


def check(sev, title, ok, detail):
    FINDINGS.append((sev, title, ok, detail))
    tag = "PASS" if ok else f"FAIL [{sev}]"
    print(f"  [{tag}] {title}")
    if not ok:
        print(f"         -> {detail}")


def probe_close_detection():
    print("Probe 1 - broker closes US100Cash position at SL between polls: does the bot record it?")
    with tempfile.TemporaryDirectory() as tmp:
        fake.reset()
        e = quiet(fresh_engine, tmp)
        quiet(e.execute_live_trade, "BUY", 20502.5, 0.30, "2026-10-20 14:30:00")
        assert len(fake.positions) == 1, "setup: order did not create a position"
        pos = fake.positions[0]
        fake.positions.clear()
        fake.balance = 187.00
        fake.equity = 187.00
        fake.deals.append(types.SimpleNamespace(
            ticket=777, order=888, position_id=pos.ticket, symbol="US100Cash",
            entry=fake.DEAL_ENTRY_OUT, reason=fake.DEAL_REASON_SL,
            price=pos.sl, volume=0.10, profit=-13.00, commission=0.0, swap=0.0, fee=0.0,
            magic=engine.MAGIC_NUMBER, time=int(time.time()),
        ))

        quiet(e.check_live_exits)

        rows = list(csv.DictReader(open(engine.TRADES_LOG_PATH))) if os.path.isfile(engine.TRADES_LOG_PATH) else []
        check("BLOCKER", "closed broker trade is written to trades.csv", len(rows) == 1,
              f"trades.csv has {len(rows)} rows")
        sl_cnt = TF.get_daily_sl_count(TF.load_recent_trades())
        check("BLOCKER", "SL close is visible to trade_filter daily SL / streak gates",
              sl_cnt >= 1 and e.losses == 1,
              f"daily_sls={sl_cnt}, engine.losses={e.losses}")
        check("HIGH", "status.json clears trade_active once the broker position is gone",
              not json.load(open(engine.STATUS_FILE_PATH)).get("trade_active"),
              "status.json still says trade_active=true")


def probe_restart():
    print("\nProbe 2 - engine restarts while an MT5 US100Cash position is still open")
    with tempfile.TemporaryDirectory() as tmp:
        fake.reset()
        e1 = quiet(fresh_engine, tmp)
        quiet(e1.execute_live_trade, "BUY", 20502.5, 0.30, "2026-10-20 14:30:00")
        assert len(fake.positions) == 1
        e2 = quiet(fresh_engine, tmp)
        in_live = bool(e2.trade_active_live or e2.trade_active)
        check("BLOCKER", "restarted engine knows a broker position is open",
              in_live and json.load(open(engine.STATUS_FILE_PATH)).get("trade_active") is True,
              f"trade_active_live={e2.trade_active_live}, trade_active={e2.trade_active}")


def probe_spread_guard():
    print("\nProbe 3 - spread widens to 80 pts ($8.00 at 0.10 lot) during news spike")
    with tempfile.TemporaryDirectory() as tmp:
        fake.reset()
        fake.bid, fake.ask = 20500.0, 20580.0
        e = quiet(fresh_engine, tmp)
        quiet(e.execute_live_trade, "BUY", 20502.5, 0.30, "2026-10-20 14:30:00")
        check("HIGH", "entry refused when live spread exceeds MAX_SPREAD_POINTS",
              len(fake.sent) == 0,
              f"orders sent={len(fake.sent)} at 80-pt spread")


def probe_request_hygiene():
    print("\nProbe 4 - order_send request fields vs XM US100Cash symbol spec")
    with tempfile.TemporaryDirectory() as tmp:
        fake.reset()
        fake.symbol_filling = fake.SYMBOL_FILLING_IOC   # bitmask 2 -> ORDER_FILLING_IOC = 1
        e = quiet(fresh_engine, tmp)
        quiet(e.execute_live_trade, "BUY", 20502.5, 0.30, "2026-10-20 14:30:00")
        req = fake.sent[-1]
        check("HIGH", "type_filling maps SYMBOL_FILLING_IOC (2) to ORDER_FILLING_IOC (1)",
              req.get("type_filling") == fake.ORDER_FILLING_IOC,
              f"sent type_filling={req.get('type_filling')}")
        check("ADVISORY", "deviation is scaled for US100Cash index points (>= 50 pts)",
              req.get("deviation", 0) >= 50,
              f"deviation={req.get('deviation')}")


def probe_unknown_state():
    print("\nProbe 5 - order_send returns None (terminal disconnect / timeout): is state safe?")
    with tempfile.TemporaryDirectory() as tmp:
        fake.reset()
        fake.send_returns_none = True
        e = quiet(fresh_engine, tmp)
        raised = None
        try:
            quiet(e.execute_live_trade, "BUY", 20502.5, 0.30, "2026-10-20 14:30:00")
            # Second attempt must be quarantined without sending a duplicate order
            quiet(e.execute_live_trade, "BUY", 20502.5, 0.30, "2026-10-20 14:30:05")
        except Exception as ex:
            raised = type(ex).__name__
        check("HIGH", "a None result is handled without exception and quarantines retries",
              raised is None and e.live_unknown_order is True and len(fake.sent) == 1,
              f"raised={raised}, live_unknown_order={e.live_unknown_order}, sent={len(fake.sent)}")


def probe_duplicate_exposure():
    print("\nProbe 6 - broker already holds a US100Cash position with this bot's magic number")
    with tempfile.TemporaryDirectory() as tmp:
        fake.reset()
        fake.positions = [types.SimpleNamespace(
            ticket=555, identifier=555, magic=engine.MAGIC_NUMBER, symbol="US100Cash",
            type=0, volume=0.10, price_open=20500.0, sl=20370.0, tp=20760.0,
            profit=0.0, swap=0.0, time=int(time.time()), comment="",
        )]
        e = quiet(fresh_engine, tmp)
        quiet(e.execute_live_trade, "BUY", 20502.5, 0.30, "2026-10-20 14:30:00")
        check("HIGH", "no second order is sent while a position with our magic is open",
              len(fake.sent) == 0,
              f"orders sent={len(fake.sent)}")


def probe_wine_bridge():
    print("\nProbe 7 - Linux Wine mt5_bridge/ IPC round-trip (engine <-> Mt5Executor)")
    with tempfile.TemporaryDirectory() as tmp:
        fake.reset()
        bridge_dir = os.path.join(tmp, "mt5_bridge")
        halt_file = os.path.join(tmp, "HALT")
        ex = MTE.Mt5Executor(
            mt5_mod=fake,
            bridge_dir=bridge_dir,
            symbol="US100Cash",
            magic=engine.MAGIC_NUMBER,
            enabled=True,
            allow_real=False,
            halt_file=halt_file,
            flatten_on_halt=True,
            max_spread_points=8.0,
            log=lambda _m: None,
        )
        ex.step()  # publish initial flat positions.json

        e = quiet(fresh_engine, tmp, use_bridge=True)
        stop_ev = threading.Event()

        def pump():
            while not stop_ev.is_set():
                ex.step()
                stop_ev.wait(0.05)

        t = threading.Thread(target=pump, daemon=True)
        t.start()
        try:
            quiet(e.execute_live_trade, "BUY", 20502.5, 0.30, "2026-10-20 14:30:00")
            check("BLOCKER", "Wine bridge opens US100Cash 0.10-lot order and marks engine trade_active_live",
                  e.trade_active_live is True and len(fake.positions) == 1,
                  f"trade_active_live={e.trade_active_live}, positions={len(fake.positions)}")

            # Trigger HALT file -> executor flattens open position -> engine records close!
            with open(halt_file, "w") as hf:
                hf.write("emergency halt\n")
            deadline = time.time() + 2.0
            while len(fake.positions) > 0 and time.time() < deadline:
                time.sleep(0.05)
            fake.deals.append(types.SimpleNamespace(
                ticket=999, order=998, position_id=9001, symbol="US100Cash",
                entry=fake.DEAL_ENTRY_OUT, reason=fake.DEAL_REASON_SL,
                price=20500.0, volume=0.10, profit=-0.25, commission=0.0, swap=0.0, fee=0.0,
                magic=engine.MAGIC_NUMBER, time=int(time.time()),
            ))
            ex.step()
            quiet(e.check_live_exits)
            check("HIGH", "HALT file flattens broker position via executor and reconciles engine",
                  len(fake.positions) == 0 and e.trade_active_live is False and e.losses == 1,
                  f"positions={len(fake.positions)}, trade_active_live={e.trade_active_live}, losses={e.losses}")
        finally:
            stop_ev.set()
            t.join(timeout=1.0)


def main():
    print("live_path_probe - engine.py + mt5_executor.py LIVE path vs fake MT5 (US100Cash), temp dirs only\n")
    for probe in (probe_close_detection, probe_restart, probe_spread_guard, probe_request_hygiene,
                  probe_unknown_state, probe_duplicate_exposure, probe_wine_bridge):
        probe()
    bad = [f for f in FINDINGS if not f[2]]
    blockers = [f for f in bad if f[0] in ("BLOCKER", "HIGH")]
    adv = [f for f in bad if f[0] == "ADVISORY"]
    print(f"\n{len(FINDINGS) - len(bad)}/{len(FINDINGS)} checks clean | "
          f"{sum(1 for f in bad if f[0] == 'BLOCKER')} BLOCKER, {sum(1 for f in bad if f[0] == 'HIGH')} HIGH, "
          f"{len(adv)} ADVISORY")
    if blockers:
        print("LIVE PATH NOT READY - keep TRADING_MODE = FORWARD_TEST.")
        return 1
    print("All BLOCKER/HIGH checks clean against fake MT5 (direct + Wine bridge). Next gate: XM demo account.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
