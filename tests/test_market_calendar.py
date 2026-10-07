#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for Taiwan Market Calendar and Holiday / Typhoon Detection."""

import json
import sys
import tempfile
from datetime import date
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

# 將專案根目錄加入 sys.path，以支援直接執行 python tests/test_market_calendar.py
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import market_calendar
from market_calendar import (
    CalendarUnavailable,
    is_market_open,
    parse_date,
    check_dgpa_typhoon_closure,
    fetch_twse_calendar,
)


def twse_response(rows):
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"stat": "OK", "data": rows}
    return resp


ROWS_2026 = [[d, n, ""] for d, n in market_calendar.BUILTIN_2026_CLOSED.items()]
ROWS_2027 = [["2027-01-01", "中華民國開國紀念日", ""], ["2027-02-05", "農曆除夕及春節", ""],
             ["2027-02-08", "農曆除夕及春節", ""], ["2027-03-01", "和平紀念日補假", ""],
             ["2027-05-01", "勞動節", ""], ["2027-10-11", "國慶日補假", ""]]


class TestMarketCalendar(unittest.TestCase):

    def test_weekend_closure(self):
        """測試週末例假日必須休市"""
        # 2026-09-26 為星期六
        is_open, reason, details = is_market_open(date(2026, 9, 26))
        self.assertFalse(is_open)
        self.assertTrue(details["is_weekend"])
        self.assertIn("週末例假日休市", reason)

        # 2026-09-27 為星期日
        is_open, reason, details = is_market_open(date(2026, 9, 27))
        self.assertFalse(is_open)
        self.assertTrue(details["is_weekend"])
        self.assertIn("週末例假日休市", reason)

    def test_scheduled_twse_holidays(self):
        """測試證交所排定之國定假日休市"""
        # 2026-09-25 為中秋節 (星期五)
        is_open, reason, details = is_market_open("2026-09-25")
        self.assertFalse(is_open)
        self.assertTrue(details["is_scheduled_holiday"])
        self.assertIn("中秋節", reason)

        # 2026-09-28 為孔子誕辰紀念日 / 教師節 (星期一)
        is_open, reason, details = is_market_open("2026-09-28")
        self.assertFalse(is_open)
        self.assertTrue(details["is_scheduled_holiday"])
        self.assertIn("教師節", reason)

        # 2026-02-12 為春節市場無交易日
        is_open, reason, details = is_market_open("2026-02-12")
        self.assertFalse(is_open)
        self.assertTrue(details["is_scheduled_holiday"])
        self.assertIn("市場無交易", reason)

        # 2026-01-01 開國紀念日
        is_open, reason, details = is_market_open("2026-01-01")
        self.assertFalse(is_open)
        self.assertTrue(details["is_scheduled_holiday"])
        self.assertIn("開國紀念日", reason)

    def test_normal_trading_days(self):
        """測試非假日之正常開盤日"""
        # 2026-09-24 為星期四，今日為正常交易日
        with patch("market_calendar.check_dgpa_typhoon_closure", return_value=(False, "無天然災害停班")):
            is_open, reason, details = is_market_open("2026-09-24")
            self.assertTrue(is_open)
            self.assertIn("正常開盤", reason)

        # 2026-09-29 為下週二，非假日
        with patch("market_calendar.check_dgpa_typhoon_closure", return_value=(False, "無天然災害停班")):
            is_open, reason, details = is_market_open("2026-09-29")
            self.assertTrue(is_open)
            self.assertIn("正常開盤", reason)

    def test_typhoon_closure_detection(self):
        """測試當台北市政府宣布停止上班時，台股判定休市"""
        # 模擬 2026-09-29 發生颱風，台北市宣布全日停止上班
        with patch("market_calendar.check_dgpa_typhoon_closure", return_value=(True, "臺北市宣布停止上班（颱風/天然災害休市）")):
            is_open, reason, details = is_market_open("2026-09-29")
            self.assertFalse(is_open)
            self.assertTrue(details["is_typhoon_closure"])
            self.assertIn("颱風", reason)
            self.assertIn("臺北市宣布停止上班", reason)

    def test_manual_override_closure(self):
        """測試透過環境變數手動指定額外休市日"""
        with patch.dict("os.environ", {"EXTRA_CLOSED_DATES": "2026-09-29,2026-10-01"}):
            is_open, reason, details = is_market_open("2026-09-29")
            self.assertFalse(is_open)
            self.assertTrue(details["is_extra_closed"])
            self.assertIn("手動指定特殊休市日", reason)

    def test_twse_calendar_fetch(self):
        """測試取得 TWSE 行事曆回傳非空字典且包含主要節日"""
        cal = fetch_twse_calendar(2026)
        self.assertIn("2026-09-25", cal)
        self.assertIn("2026-01-01", cal)
        # 「開始交易日」2026-01-02 不應被計為休市
        self.assertNotIn("2026-01-02", cal)


class TestUnpublishedYear(unittest.TestCase):
    """未公布年份不可默認開盤，也不可把其他年度資料當成本年度。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = patch.object(market_calendar, "CALENDAR_CACHE_DIR", Path(self.tmp.name))
        self.cache.start()

    def tearDown(self):
        self.cache.stop()
        self.tmp.cleanup()

    def test_other_year_response_is_rejected_and_fails_closed(self):
        # TWSE 對未公布年份曾回傳當年度資料
        with patch("market_calendar.requests.get", return_value=twse_response(ROWS_2026)) as get:
            with self.assertRaises(CalendarUnavailable):
                fetch_twse_calendar(2027)
            with self.assertRaises(CalendarUnavailable):
                is_market_open("2027-01-04")
        self.assertIn("date=20270101", get.call_args[0][0])
        self.assertFalse((Path(self.tmp.name) / "calendar-2027.json").exists())

    def test_poisoned_cache_from_other_year_is_ignored(self):
        payload = {"year": 2027, "closed_map": market_calendar.BUILTIN_2026_CLOSED}
        (Path(self.tmp.name) / "calendar-2027.json").write_text(json.dumps(payload), encoding="utf-8")
        with patch("market_calendar.requests.get", side_effect=OSError("offline")):
            with self.assertRaises(CalendarUnavailable):
                fetch_twse_calendar(2027)

    def test_published_year_is_used_and_cached(self):
        with patch("market_calendar.requests.get", return_value=twse_response(ROWS_2027 + ROWS_2026)):
            cal = fetch_twse_calendar(2027)
        self.assertEqual(set(cal), {r[0] for r in ROWS_2027})
        with patch("market_calendar.requests.get", side_effect=OSError("offline")):
            is_open, reason, details = is_market_open("2027-01-01")
        self.assertFalse(is_open)
        self.assertTrue(details["is_scheduled_holiday"])


if __name__ == "__main__":
    unittest.main()
