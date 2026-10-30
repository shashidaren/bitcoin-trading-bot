"""Regression tests for tools/feed_doctor.py's XM witness.

The quote logger (tools/mt5_quotes.py) keys candles_m15.csv rows by
``bar_close_utc``. The witness used to treat that value as an OPEN time and
add another 15 minutes, so the reported bar age was one full bar too fresh:
a bar that closed 21 minutes ago was reported as "closed 6 min ago" and
could wrongly prove MT5 alive (witness threshold: 20 min) while the feed
was actually stale.

Run with ``python3 -m unittest discover -s tests -v``.
"""
import importlib.util
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_spec = importlib.util.spec_from_file_location(
    "feed_doctor", ROOT / "tools" / "feed_doctor.py")
feed_doctor = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(feed_doctor)

NOW = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
NOW_EPOCH = NOW.timestamp()
CANDLE_HEADER = "bar_close_utc,open,high,low,close,tick_volume,spread_pts,time_srv,offset_s"
QUOTES_HEADER = "ts_utc,bid,ask,spread,spread_min,spread_max,n_ok,n_bad,tick_age_s,srv_offset_s,flags"


def candle_row(bar_close_utc):
    return f"{bar_close_utc},20000,20010,19990,20005,100,290,1793361600,7200"


class WitnessCandleAgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.xm = Path(self.tmp.name) / "xm_data"
        self.xm.mkdir()

    def write_candles(self, text):
        (self.xm / "candles_m15.csv").write_text(text, encoding="utf-8")

    def test_bar_close_utc_is_a_close_time_not_an_open(self):
        # Bar closed at 11:39 -> exactly 21 minutes before NOW (12:00).
        self.write_candles(CANDLE_HEADER + "\n" + candle_row("2026-10-30 11:39:00") + "\n")
        w = feed_doctor.witness_quotes(str(self.xm), NOW_EPOCH)
        # The buggy code reported 21*60 - 900 = 360 s here.
        self.assertEqual(w["last_bar_close_age_s"], 21 * 60)
        self.assertEqual(w["last_bar_close_utc"], "2026-10-30 11:39:00")
        self.assertEqual(w["last_bar_open_utc"], "2026-10-30 11:24:00")

    def test_fresh_bar_age_is_exact(self):
        self.write_candles(CANDLE_HEADER + "\n" + candle_row("2026-10-30 11:55:00") + "\n")
        w = feed_doctor.witness_quotes(str(self.xm), NOW_EPOCH)
        self.assertEqual(w["last_bar_close_age_s"], 5 * 60)

    def test_header_only_file_reports_no_bar(self):
        self.write_candles(CANDLE_HEADER + "\n")
        w = feed_doctor.witness_quotes(str(self.xm), NOW_EPOCH)
        self.assertIsNone(w["last_bar_close_age_s"])
        self.assertIsNone(w["last_bar_close_utc"])
        self.assertIsNone(w["last_bar_open_utc"])

    def test_unknown_schema_fails_closed(self):
        self.write_candles("when,open\n2026-10-30 11:55:00,20000\n")
        w = feed_doctor.witness_quotes(str(self.xm), NOW_EPOCH)
        self.assertIsNone(w["last_bar_close_age_s"])
        self.assertIsNone(w["last_bar_close_utc"])

    def test_stale_witness_does_not_prove_mt5_alive(self):
        # Feed file missing; quote file present but an hour old (mtime), and the
        # newest witness bar closed 21 min ago: beyond the 20-min witness
        # threshold, so the verdict must NOT claim "MT5 itself is fine". With
        # the old +900 s bug this exact fixture produced that claim.
        root = Path(self.tmp.name)
        self.write_candles(CANDLE_HEADER + "\n" + candle_row("2026-10-30 11:39:00") + "\n")
        qpath = self.xm / "quotes-2026-10-30.csv"
        qpath.write_text(QUOTES_HEADER + "\n"
                         "2026-10-30 11:00:00,20000,20002.9,2.9,2.9,2.9,6,0,1.0,7200,\n",
                         encoding="utf-8")
        old = NOW_EPOCH - 3600
        os.utime(qpath, (old, old))
        report = feed_doctor.build_report(str(root), None, now_epoch=NOW_EPOCH,
                                          assume_open=True)
        self.assertEqual(report["witness"]["last_bar_close_age_s"], 21 * 60)
        steps = " ".join(report["verdict"][2])
        self.assertNotIn("MT5 itself is fine", steps)

    def test_fresh_witness_still_proves_mt5_alive(self):
        root = Path(self.tmp.name)
        self.write_candles(CANDLE_HEADER + "\n" + candle_row("2026-10-30 11:55:00") + "\n")
        qpath = self.xm / "quotes-2026-10-30.csv"
        qpath.write_text(QUOTES_HEADER + "\n"
                         "2026-10-30 11:59:00,20000,20002.9,2.9,2.9,2.9,6,0,1.0,7200,\n",
                         encoding="utf-8")
        os.utime(qpath, (NOW_EPOCH - 60, NOW_EPOCH - 60))
        report = feed_doctor.build_report(str(root), None, now_epoch=NOW_EPOCH,
                                          assume_open=True)
        steps = " ".join(report["verdict"][2])
        self.assertIn("MT5 itself is fine", steps)


if __name__ == "__main__":
    unittest.main()
