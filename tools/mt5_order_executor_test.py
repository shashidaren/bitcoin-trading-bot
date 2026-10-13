#!/usr/bin/env python3
"""Offline regression tests for the Wine MT5 order executor (no broker/network)."""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

from mt5_order_executor import ExecutorConfig, MT5OrderExecutor, SafetyError  # noqa: E402
from mt5_order_protocol import OrderBridge, utc_iso  # noqa: E402

NOW = datetime(2026, 10, 13, 9, 5, 0, tzinfo=timezone.utc)


class FakeMT5:
    # Request/action constants.
    TRADE_ACTION_DEAL = 1
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    ORDER_TIME_GTC = 0
    ORDER_FILLING_FOK = 0
    ORDER_FILLING_IOC = 1
    ORDER_FILLING_RETURN = 2

    # Symbol filling flags are a bitmask; order filling enums above are not.
    SYMBOL_FILLING_FOK = 1
    SYMBOL_FILLING_IOC = 2
    SYMBOL_TRADE_EXECUTION_MARKET = 2
    SYMBOL_TRADE_MODE_DISABLED = 0
    SYMBOL_TRADE_MODE_FULL = 4

    # Account/deal/order result constants.
    ACCOUNT_TRADE_MODE_DEMO = 0
    ACCOUNT_TRADE_MODE_REAL = 2
    TRADE_RETCODE_DONE = 10009
    TRADE_RETCODE_DONE_PARTIAL = 10010
    TRADE_RETCODE_PLACED = 10008
    TRADE_RETCODE_TIMEOUT = 10012
    TRADE_RETCODE_CONNECTION = 10031
    TRADE_RETCODE_ERROR = 10011
    DEAL_ENTRY_IN = 0
    DEAL_ENTRY_OUT = 1
    DEAL_ENTRY_INOUT = 2
    DEAL_ENTRY_OUT_BY = 3
    DEAL_REASON_SL = 4
    DEAL_REASON_TP = 5

    def __init__(self):
        self.reset()

    def reset(self):
        self.initialized = False
        self.shutdown_called = False
        self.bid = 83000.0
        self.ask = 83040.0
        self.quote_offset_seconds = 7200  # XM-style broker server time, normalized by executor.
        self.quote_age_seconds = 0
        self.strip_server_stops = False
        self.trade_mode = self.ACCOUNT_TRADE_MODE_DEMO
        self.account_trade_allowed = True
        self.terminal_trade_allowed = True
        self.equity = 200.0
        self.balance = 200.0
        self.check_retcode = 0
        self.send_retcode = self.TRADE_RETCODE_DONE
        self.send_returns_none = False
        self.create_position_when_none = True
        self.position_query_fails = False
        self.history_query_fails = False
        self.positions = []
        self.pending_orders = []
        self.deals = []
        self.sent = []
        self.checks = []
        self.history_calls = []
        self.next_order = 4001

    def initialize(self):
        self.initialized = True
        return True

    def shutdown(self):
        self.shutdown_called = True

    def last_error(self):
        return (0, "fake")

    def account_info(self):
        return SimpleNamespace(trade_mode=self.trade_mode,
                               trade_allowed=self.account_trade_allowed,
                               balance=self.balance, equity=self.equity,
                               currency="USD")

    def terminal_info(self):
        return SimpleNamespace(connected=True, trade_allowed=self.terminal_trade_allowed)

    def symbol_select(self, symbol, enable):
        return symbol == "BTCUSD" and enable is True

    def symbol_info(self, symbol):
        if symbol != "BTCUSD":
            return None
        return SimpleNamespace(
            point=0.01, trade_tick_size=0.01, digits=2,
            filling_mode=self.SYMBOL_FILLING_IOC,
            trade_exemode=self.SYMBOL_TRADE_EXECUTION_MARKET,
            trade_mode=self.SYMBOL_TRADE_MODE_FULL,
            trade_stops_level=1,
            volume_min=0.01, volume_max=10.0, volume_step=0.01,
        )

    def symbol_info_tick(self, symbol):
        age = self.quote_age_seconds
        return SimpleNamespace(
            bid=self.bid, ask=self.ask,
            time=int(NOW.timestamp() + self.quote_offset_seconds - age),
            time_msc=int((NOW.timestamp() + self.quote_offset_seconds - age) * 1000),
        )

    def positions_get(self, *args, **kwargs):
        if self.position_query_fails:
            return None
        symbol = kwargs.get("symbol")
        if symbol is not None:
            return tuple(p for p in self.positions if p.symbol == symbol)
        return tuple(self.positions)

    def orders_get(self, *args, **kwargs):
        return tuple(self.pending_orders)

    def history_deals_get(self, *args, **kwargs):
        self.history_calls.append((args, dict(kwargs)))
        if self.history_query_fails:
            return None
        ticket = kwargs.get("ticket")
        position = kwargs.get("position")
        if ticket is not None:
            found = [d for d in self.deals if d.order == ticket]
        elif position is not None:
            found = [d for d in self.deals if d.position_id == position]
        else:
            # Date-range query for daily P/L and comment recovery.
            found = list(self.deals)
        return tuple(found)

    def order_check(self, request):
        self.checks.append(dict(request))
        return SimpleNamespace(retcode=self.check_retcode,
                               comment="fake order check")

    def order_send(self, request):
        self.sent.append(dict(request))
        if self.send_retcode not in (self.TRADE_RETCODE_DONE,
                                     self.TRADE_RETCODE_DONE_PARTIAL):
            return SimpleNamespace(retcode=self.send_retcode, order=0, deal=0,
                                   comment="fake rejected")
        if self.send_returns_none and not self.create_position_when_none:
            return None
        order, deal_ticket = self._fill(request)
        if self.send_returns_none:
            return None
        return SimpleNamespace(retcode=self.send_retcode, order=order,
                               deal=deal_ticket, comment="fake done")

    def _fill(self, request):
        order = self.next_order
        deal_ticket = order + 10000
        self.next_order += 1
        position_id = order + 20000
        now_epoch = int(NOW.timestamp())
        self.deals.append(SimpleNamespace(
            ticket=deal_ticket, order=order, position_id=position_id,
            entry=self.DEAL_ENTRY_IN, profit=0.0, commission=-0.10,
            swap=0.0, fee=0.0, price=request["price"], volume=request["volume"],
            magic=request["magic"], symbol=request["symbol"],
            comment=request["comment"], reason=0, time=now_epoch,
        ))
        self.positions.append(SimpleNamespace(
            ticket=order, identifier=position_id, magic=request["magic"],
            symbol=request["symbol"], type=request["type"], volume=request["volume"],
            price_open=request["price"],
            sl=0.0 if self.strip_server_stops else request["sl"],
            tp=0.0 if self.strip_server_stops else request["tp"],
            comment=request["comment"], time=now_epoch,
        ))
        return order, deal_ticket

    def close_position(self, position_id, price, profit, commission=-0.20,
                       swap=-0.05, fee=-0.10, reason=None):
        position = next(p for p in self.positions if p.identifier == position_id)
        self.positions.remove(position)
        ticket = self.next_order + 10000
        order = self.next_order
        self.next_order += 1
        self.deals.append(SimpleNamespace(
            ticket=ticket, order=order, position_id=position_id,
            entry=self.DEAL_ENTRY_OUT, profit=profit, commission=commission,
            swap=swap, fee=fee, price=price, volume=position.volume,
            magic=position.magic, symbol=position.symbol, comment="broker close",
            reason=self.DEAL_REASON_TP if reason is None else reason,
            time=int(NOW.timestamp()),
        ))


class OrderExecutorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="btc_mt5_order_")
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        self.halt = os.path.join(self.root, "MT5_ORDER_HALT")
        self.mt5 = FakeMT5()
        self.config = ExecutorConfig(
            root=self.root, enabled=True, account_kind="demo", starting_equity=200.0,
            symbol="BTCUSD", magic=987655, volume=0.01, halt_file=self.halt,
            max_spread_usd=60.0, max_spread_to_1r=0.70,
            quote_max_age_seconds=60.0, intent_max_age_seconds=120.0,
            max_daily_stop_losses=3, max_daily_loss_usd=10.0,
            max_drawdown_usd=30.0, baseline_tolerance_usd=1.0,
        )
        self.executor = self._new_executor(self.mt5, self.config)
        self.assertTrue(self.executor.connect())

    def _new_executor(self, mt5, config):
        return MT5OrderExecutor(mt5, config=config, clock=lambda: NOW, logger=lambda _msg: None)

    def _submit(self, suffix="1", **kwargs):
        intent_id = suffix.rjust(32, "0")
        direction = kwargs.pop("direction", "BUY")
        atr = kwargs.pop("atr", 100.0)
        symbol = kwargs.pop("symbol", "BTCUSD")
        volume = kwargs.pop("volume", 0.01)
        if kwargs:
            raise TypeError("unexpected intent fields: %s" % sorted(kwargs))
        bridge = OrderBridge(self.root)
        bridge.submit_open(direction, atr, signal_ts="2026-10-13 09:00:00",
                           symbol=symbol, volume=volume, created_at=utc_iso(NOW),
                           intent_id=intent_id)
        return intent_id

    def _result(self, intent_id):
        result = OrderBridge(self.root).get_result(intent_id)
        self.assertIsNotNone(result)
        return result

    def test_sidecar_module_imports_without_meta_trader_package(self):
        # This test process has not installed/imported MetaTrader5. The worker
        # accepts an injected module and imports the vendor package only in main.
        self.assertNotIn("MetaTrader5", sys.modules)

    def test_demo_mode_and_explicit_start_equity_are_mandatory(self):
        untouched = FakeMT5()
        real_config = ExecutorConfig(root=self.root, enabled=True, account_kind="real",
                                     starting_equity=200.0)
        real = self._new_executor(untouched, real_config)
        self.assertFalse(real.connect())
        self.assertFalse(untouched.initialized)

        no_baseline = ExecutorConfig(root=os.path.join(self.root, "no-baseline"),
                                     enabled=True, account_kind="demo")
        missing = self._new_executor(untouched, no_baseline)
        self.assertFalse(missing.connect())
        self.assertFalse(untouched.initialized)
        self.assertEqual(untouched.sent, [])

        real_account = FakeMT5()
        real_account.trade_mode = real_account.ACCOUNT_TRADE_MODE_REAL
        another = self._new_executor(real_account,
                                     ExecutorConfig(root=os.path.join(self.root, "real"),
                                                    enabled=True, account_kind="demo",
                                                    starting_equity=200.0))
        self.assertFalse(another.connect())
        self.assertTrue(real_account.initialized)
        self.assertEqual(real_account.sent, [])

    def test_disabled_executor_never_initializes_terminal(self):
        mt5 = FakeMT5()
        config = ExecutorConfig(root=os.path.join(self.root, "disabled"), enabled=False,
                                account_kind="demo", starting_equity=200.0)
        executor = self._new_executor(mt5, config)
        self.assertFalse(executor.connect())
        self.assertFalse(mt5.initialized)
        self.assertEqual(mt5.sent, [])

    def test_spread_hard_and_relative_1r_guards_reject_before_send(self):
        self.mt5.ask = self.mt5.bid + 61.0
        hard = self._submit("2")
        self.executor.poll_once()
        self.assertEqual(self._result(hard)["reason_code"], "SPREAD_HARD_CAP")
        self.assertEqual(self.mt5.sent, [])

        self.mt5.ask = self.mt5.bid + 30.0
        ratio = self._submit("3", atr=20.0)
        self.executor.poll_once()
        self.assertEqual(self._result(ratio)["reason_code"], "SPREAD_TO_1R")
        self.assertEqual(self.mt5.sent, [])

    def test_stale_quote_and_order_check_rejection_never_send(self):
        self.mt5.quote_age_seconds = 120
        stale = self._submit("4")
        self.executor.poll_once()
        self.assertEqual(self._result(stale)["reason_code"], "QUOTE_STALE")
        self.assertEqual(self.mt5.sent, [])

        self.mt5.quote_age_seconds = 0
        self.mt5.check_retcode = 10016
        checked = self._submit("5")
        self.executor.poll_once()
        self.assertEqual(self._result(checked)["reason_code"], "ORDER_CHECK_REJECTED")
        self.assertEqual(len(self.mt5.checks), 1)
        self.assertEqual(self.mt5.sent, [])

    def test_filling_mode_decoder_maps_symbol_flags_to_order_enums(self):
        info = self.mt5.symbol_info("BTCUSD")
        info.filling_mode = self.mt5.SYMBOL_FILLING_FOK
        self.assertEqual(self.executor._choose_filling_mode(info), self.mt5.ORDER_FILLING_FOK)
        info.filling_mode = 0
        info.trade_exemode = 1  # Instant/Request execution permits RETURN.
        self.assertEqual(self.executor._choose_filling_mode(info), self.mt5.ORDER_FILLING_RETURN)
        info.trade_exemode = self.mt5.SYMBOL_TRADE_EXECUTION_MARKET
        with self.assertRaises(SafetyError):
            self.executor._choose_filling_mode(info)

    def test_market_order_uses_allowed_filling_flag_and_attaches_frozen_geometry(self):
        intent_id = self._submit("6")
        self.executor.poll_once()
        result = self._result(intent_id)
        self.assertEqual(result["status"], "OPEN")
        request = self.mt5.sent[0]
        self.assertEqual(request["type_filling"], self.mt5.ORDER_FILLING_IOC)
        self.assertEqual(request["type"], self.mt5.ORDER_TYPE_BUY)
        self.assertEqual(request["price"], 83040.0)
        self.assertEqual(request["sl"], 82840.0)
        self.assertEqual(request["tp"], 83440.0)
        self.assertEqual(request["magic"], self.config.magic)
        self.assertLessEqual(len(request["comment"]), 31)
        self.assertEqual(result["entry_price"], 83040.0)
        self.assertEqual(result["spread_usd"], 40.0)
        self.assertEqual(len(self.mt5.checks), 1)

    def test_missing_broker_side_stops_latches_position_as_unknown(self):
        self.mt5.strip_server_stops = True
        intent_id = self._submit("a")
        self.executor.poll_once()
        result = self._result(intent_id)
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertEqual(result["reason_code"], "MISSING_OR_INVALID_STOPS")
        self.assertEqual(self.executor.state["halted_reason"], "UNPROTECTED_POSITION")
        self.assertEqual(len(self.mt5.sent), 1)
        later = self._submit("d")
        self.executor.poll_once()
        self.assertEqual(self._result(later)["status"], "REJECTED")
        self.assertEqual(len(self.mt5.sent), 1)

    def test_sell_uses_bid_and_mirrored_stop_target(self):
        intent_id = "0" * 31 + "a"
        OrderBridge(self.root).submit_open(
            "SELL", 100.0, created_at=utc_iso(NOW), intent_id=intent_id)
        self.executor.poll_once()
        result = self._result(intent_id)
        request = self.mt5.sent[0]
        self.assertEqual(result["status"], "OPEN")
        self.assertEqual(request["type"], self.mt5.ORDER_TYPE_SELL)
        self.assertEqual(request["price"], 83000.0)
        self.assertEqual(request["sl"], 83200.0)
        self.assertEqual(request["tp"], 82600.0)

    def test_pre_send_received_intent_resumes_safely_after_restart(self):
        intent_id = self._submit("b")
        queued = os.path.join(self.config.inbox, intent_id + ".json")
        with open(queued, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        self.executor.state["intents"][intent_id] = {
            "intent_id": intent_id, "intent": payload, "status": "RECEIVED",
            "reason_code": None, "message": "", "created_at_utc": utc_iso(NOW),
            "comment_tag": "BTC:" + intent_id[:24],
        }
        self.executor._save_state()  # simulate crash after durable RECEIVED, before order_send
        restarted = self._new_executor(self.mt5, self.config)
        self.assertTrue(restarted.connect())
        restarted.poll_once()
        self.assertEqual(OrderBridge(self.root).get_result(intent_id)["status"], "OPEN")
        self.assertEqual(len(self.mt5.sent), 1)

    def test_none_send_result_is_unknown_and_is_never_retried(self):
        self.mt5.send_returns_none = True
        self.mt5.create_position_when_none = False
        intent_id = self._submit("7")
        self.executor.poll_once()
        self.assertEqual(self._result(intent_id)["status"], "UNKNOWN")
        self.assertEqual(len(self.mt5.sent), 1)

        restarted = self._new_executor(self.mt5, self.config)
        self.assertTrue(restarted.connect())
        restarted.poll_once()
        self.assertEqual(len(self.mt5.sent), 1)
        another = self._submit("8")
        restarted.poll_once()
        self.assertEqual(self._result(another)["status"], "REJECTED")
        self.assertEqual(len(self.mt5.sent), 1)

    def test_ambiguous_none_with_position_is_reconciled_without_retry(self):
        self.mt5.send_returns_none = True
        intent_id = self._submit("9")
        self.executor.poll_once()
        self.assertEqual(self._result(intent_id)["status"], "OPEN")
        self.assertEqual(len(self.mt5.sent), 1)
        self.executor.poll_once()
        self.assertEqual(len(self.mt5.sent), 1)

    def test_pending_order_with_bot_magic_latches_and_blocks(self):
        self.mt5.pending_orders.append(SimpleNamespace(
            ticket=777, magic=self.config.magic, symbol="BTCUSD", type=0))
        intent_id = self._submit("c")
        self.executor.poll_once()
        self.assertEqual(self._result(intent_id)["status"], "REJECTED")
        self.assertEqual(self.executor.state["halted_reason"], "ORPHAN_ORDER")
        self.assertEqual(self.mt5.sent, [])

    def test_existing_bot_magic_position_blocks_new_order(self):
        self.mt5.positions.append(SimpleNamespace(
            ticket=888, identifier=888, magic=self.config.magic, symbol="BTCUSD",
            type=self.mt5.ORDER_TYPE_BUY, volume=0.01, price_open=83000,
            sl=82800, tp=83400, comment="unknown position"))
        intent_id = self._submit("10")
        self.executor.poll_once()
        self.assertEqual(self._result(intent_id)["status"], "REJECTED")
        self.assertEqual(self._result(intent_id)["reason_code"], "SAFETY_GUARD")
        self.assertEqual(self.mt5.sent, [])
        self.assertEqual(self.executor.state["halted_reason"], "ORPHAN_POSITION")

    def test_closed_position_uses_position_history_and_all_cost_components(self):
        intent_id = self._submit("11")
        self.executor.poll_once()
        opened = self._result(intent_id)
        self.assertEqual(opened["status"], "OPEN")
        position_id = opened["position_id"]
        self.mt5.close_position(position_id, 83440.0, profit=4.0)
        self.executor.poll_once()
        closed = self._result(intent_id)
        self.assertEqual(closed["status"], "CLOSED")
        self.assertEqual(closed["exit_reason"], "TP")
        self.assertAlmostEqual(closed["gross_profit"], 4.0)
        self.assertAlmostEqual(closed["commission"], -0.30)  # entry and exit commission
        self.assertAlmostEqual(closed["swap"], -0.05)
        self.assertAlmostEqual(closed["fee"], -0.10)
        self.assertAlmostEqual(closed["net_profit"], 3.55)
        self.assertTrue(any("position" in kwargs for _args, kwargs in self.mt5.history_calls))

    def test_manual_halt_and_terminal_permissions_are_enforced(self):
        with open(self.halt, "w") as handle:
            handle.write("halt\n")
        halted = self._submit("12")
        self.executor.poll_once()
        self.assertEqual(self._result(halted)["status"], "REJECTED")
        self.assertEqual(self.mt5.sent, [])
        os.unlink(self.halt)

        self.mt5.terminal_trade_allowed = False
        disabled = self._submit("13")
        self.executor.poll_once()
        self.assertEqual(self._result(disabled)["status"], "REJECTED")
        self.assertEqual(self.mt5.sent, [])

    def test_daily_sl_daily_loss_and_unknown_history_fail_closed(self):
        for position_id in (101, 102, 103):
            self.mt5.deals.append(SimpleNamespace(
                ticket=position_id + 1000, order=position_id, position_id=position_id,
                entry=self.mt5.DEAL_ENTRY_OUT, profit=-1.0, commission=0.0,
                swap=0.0, fee=0.0, magic=self.config.magic, symbol="BTCUSD",
                reason=self.mt5.DEAL_REASON_SL, time=int(NOW.timestamp())))
        intent_id = self._submit("14")
        self.executor.poll_once()
        self.assertEqual(self._result(intent_id)["reason_code"], "DAILY_SL_LIMIT")
        self.assertEqual(self.mt5.sent, [])

        # A fresh worker/root demonstrates the separate daily-net gate.
        root = os.path.join(self.root, "daily-loss")
        config = ExecutorConfig(root=root, enabled=True, account_kind="demo",
                                starting_equity=200.0, halt_file=os.path.join(root, "HALT"))
        mt5 = FakeMT5()
        mt5.deals.append(SimpleNamespace(
            ticket=9001, order=900, position_id=900, entry=mt5.DEAL_ENTRY_OUT,
            profit=-10.01, commission=0.0, swap=0.0, fee=0.0,
            magic=config.magic, symbol=config.symbol, reason=0, time=int(NOW.timestamp())))
        executor = self._new_executor(mt5, config)
        self.assertTrue(executor.connect())
        bridge = OrderBridge(root)
        loss_id = "0" * 31 + "f"
        bridge.submit_open("BUY", 100, created_at=utc_iso(NOW), intent_id=loss_id)
        executor.poll_once()
        self.assertEqual(bridge.get_result(loss_id)["reason_code"], "DAILY_LOSS_LIMIT")
        self.assertEqual(mt5.sent, [])

        mt5.history_query_fails = True
        unknown_id = "0" * 31 + "e"
        bridge.submit_open("BUY", 100, created_at=utc_iso(NOW), intent_id=unknown_id)
        executor.poll_once()
        self.assertEqual(bridge.get_result(unknown_id)["reason_code"], "DAILY_HISTORY_UNAVAILABLE")
        self.assertEqual(mt5.sent, [])

    def test_daily_risk_normalizes_server_time_across_utc_midnight(self):
        root = os.path.join(self.root, "midnight")
        config = ExecutorConfig(
            root=root, enabled=True, account_kind="demo", starting_equity=200.0,
            symbol="BTCUSD", magic=987655, volume=0.01,
            halt_file=os.path.join(root, "HALT"), max_daily_stop_losses=1)
        mt5 = FakeMT5()
        previous_day = NOW.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(minutes=5)
        mt5.deals.append(SimpleNamespace(
            ticket=7001, order=700, position_id=700, entry=mt5.DEAL_ENTRY_OUT,
            profit=-1.0, commission=0.0, swap=0.0, fee=0.0,
            magic=config.magic, symbol=config.symbol, reason=mt5.DEAL_REASON_SL,
            time=int(previous_day.timestamp() + mt5.quote_offset_seconds)))
        executor = self._new_executor(mt5, config)
        self.assertTrue(executor.connect())
        intent_id = "0" * 31 + "c"
        OrderBridge(root).submit_open("BUY", 100, created_at=utc_iso(NOW), intent_id=intent_id)
        executor.poll_once()
        self.assertEqual(OrderBridge(root).get_result(intent_id)["status"], "OPEN")
        self.assertEqual(len(mt5.sent), 1)

    def test_drawdown_kill_is_persisted_across_restart(self):
        self.mt5.equity = 169.99
        self.executor.poll_once()  # latch while flat, even with no queued signal
        self.assertEqual(self.executor.state["halted_reason"], "MAX_DRAWDOWN")
        first = self._submit("15")
        self.executor.poll_once()
        self.assertEqual(self._result(first)["status"], "REJECTED")
        self.assertEqual(self.executor.state["halted_reason"], "MAX_DRAWDOWN")

        self.mt5.equity = 200.0
        restarted = self._new_executor(self.mt5, self.config)
        self.assertTrue(restarted.connect())
        second = self._submit("16")
        restarted.poll_once()
        self.assertEqual(self._result(second)["status"], "REJECTED")
        self.assertEqual(self.mt5.sent, [])
        self.assertEqual(restarted.state["halted_reason"], "MAX_DRAWDOWN")

    def test_bad_volume_symbol_stale_timestamp_and_baseline_are_rejected(self):
        invalid_volume = self._submit("17", volume=0.02)
        self.executor.poll_once()
        self.assertEqual(self._result(invalid_volume)["reason_code"], "BAD_VOLUME")
        self.assertEqual(self.mt5.sent, [])

        bad_symbol = self._submit("18", symbol="BTCUSDm")
        self.executor.poll_once()
        self.assertEqual(self._result(bad_symbol)["reason_code"], "BAD_SYMBOL")
        self.assertEqual(self.mt5.sent, [])

        stale_id = "0" * 31 + "b"
        OrderBridge(self.root).submit_open(
            "BUY", 100, created_at=utc_iso(NOW - timedelta(minutes=5)),
            intent_id=stale_id)
        self.executor.poll_once()
        self.assertEqual(self._result(stale_id)["reason_code"], "STALE_INTENT")
        self.assertEqual(self.mt5.sent, [])

        root = os.path.join(self.root, "baseline-mismatch")
        mismatch = self._new_executor(self.mt5, ExecutorConfig(
            root=root, enabled=True, account_kind="demo", starting_equity=300.0,
            halt_file=os.path.join(root, "HALT")))
        self.assertFalse(mismatch.connect())
        self.assertEqual(self.mt5.sent, [])

    def test_persisted_risk_policy_change_requires_manual_review(self):
        changed = FakeMT5()
        config = ExecutorConfig(
            root=self.root, enabled=True, account_kind="demo", starting_equity=200.0,
            symbol="BTCUSD", magic=987655, volume=0.01, halt_file=self.halt,
            max_spread_usd=55.0, max_spread_to_1r=0.70,
            quote_max_age_seconds=60.0, intent_max_age_seconds=120.0,
            max_daily_stop_losses=3, max_daily_loss_usd=10.0,
            max_drawdown_usd=30.0, baseline_tolerance_usd=1.0)
        restarted = self._new_executor(changed, config)
        self.assertFalse(restarted.connect())
        self.assertEqual(changed.sent, [])

    def test_position_query_failure_leaves_intent_queued(self):
        self.mt5.position_query_fails = True
        intent_id = self._submit("19")
        self.executor.poll_once()
        self.assertIsNone(OrderBridge(self.root).get_result(intent_id))
        self.assertEqual(self.mt5.sent, [])
        self.assertTrue(os.path.isfile(os.path.join(self.config.inbox, intent_id + ".json")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
