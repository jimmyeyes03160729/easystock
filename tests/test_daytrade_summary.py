"""Tests for the daily summary report builder and intraday log parsers.

These tests use only in-memory fixtures; they do not call journalctl,
modify the paper ledger, write model artifacts, or send messages.
"""
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

import paper_ledger
from daytrade_summary_push import build_daily_summary
from daytrade_summary_report import (
    parse_model_decisions,
    parse_market_risk,
    parse_market_data,
    parse_radar_peak,
    no_trade_reason,
    format_probability,
    format_threshold,
)


class LogParsingTests(unittest.TestCase):
    def test_model_decisions_count_evaluated_accepted_and_max_probability(self):
        lines = [
            '[MODEL_DECISION] symbol=2303 evaluated=True accepted=True probability=0.72 threshold=0.6 reason=evaluated',
            '[MODEL_DECISION] symbol=1101 evaluated=True accepted=False probability=0.59 threshold=0.6 reason=evaluated',
            '[MODEL_DECISION] symbol=3701 evaluated=True accepted=False probability=0.45 threshold=0.6 reason=evaluated',
        ]
        result = parse_model_decisions(lines)
        self.assertEqual(result['evaluations'], 3)
        self.assertEqual(result['accepted_count'], 1)
        self.assertEqual(result['max_probability'], 0.72)
        self.assertEqual(result['max_probability_symbol'], '2303')

    def test_model_decisions_exclude_none_probability_from_max(self):
        lines = [
            '[MODEL_DECISION] symbol=2303 evaluated=True accepted=False probability=None threshold=0.6 reason=missing_or_invalid_features',
            '[MODEL_DECISION] symbol=1101 evaluated=True accepted=False probability=0.55 threshold=0.6 reason=evaluated',
        ]
        result = parse_model_decisions(lines)
        self.assertEqual(result['evaluations'], 2)
        self.assertEqual(result['missing_feature_count'], 1)
        self.assertEqual(result['max_probability'], 0.55)
        self.assertEqual(result['max_probability_symbol'], '1101')

    def test_model_decisions_skip_not_evaluated(self):
        lines = [
            '[MODEL_DECISION] symbol=2303 evaluated=False accepted=False probability=0.8 threshold=0.6 reason=inactive',
        ]
        result = parse_model_decisions(lines)
        self.assertEqual(result['evaluations'], 0)
        self.assertIsNone(result['max_probability'])

    def test_market_risk_takes_last_valid_state(self):
        lines = [
            '[MARKET_RISK] premarket=GREEN live=GREEN effective=GREEN gate=PASS reason=market_risk_pass veto=- radar_candidates=0',
            '[MARKET_RISK] premarket=YELLOW live=GREEN effective=YELLOW gate=PASS reason=market_risk_pass veto=- radar_candidates=3',
        ]
        state = parse_market_risk(lines)
        self.assertEqual(state['effective'], 'YELLOW')
        self.assertEqual(state['gate'], 'PASS')

    def test_market_data_takes_last_valid_state(self):
        lines = [
            '[MARKET_DATA] shioaji=HEALTHY esun=DEGRADED premarket=HEALTHY',
            '[MARKET_DATA] shioaji=HEALTHY esun=HEALTHY premarket=HEALTHY',
        ]
        state = parse_market_data(lines)
        self.assertEqual(state['esun'], 'HEALTHY')

    def test_radar_peak_uses_max_not_sum(self):
        lines = [
            '⚡ Instant-volume radar: qualified=5 Top=5',
            '⚡ Instant-volume radar: qualified=12 Top=12',
            '⚡ Instant-volume radar: qualified=22 Top=22',
            '⚡ Instant-volume radar: qualified=17 Top=17',
        ]
        self.assertEqual(parse_radar_peak(lines), 22)

    def test_format_probability_and_threshold(self):
        self.assertEqual(format_probability(0.59079), '0.5908')
        self.assertEqual(format_probability(None), '--')
        self.assertEqual(format_threshold(0.6), '0.6000')
        self.assertEqual(format_threshold(None), '--')


class NoTradeReasonTests(unittest.TestCase):
    def test_no_reason_when_trades_present(self):
        self.assertEqual(no_trade_reason({'trades_count': 1}, {}, {}, 0), '')

    def test_market_risk_red(self):
        self.assertEqual(
            no_trade_reason({'trades_count': 0}, {}, {'effective': 'RED'}, 5),
            'Market Risk RED'
        )

    def test_market_risk_block(self):
        self.assertEqual(
            no_trade_reason({'trades_count': 0}, {}, {'effective': 'GREEN', 'gate': 'BLOCK'}, 5),
            'Market Risk BLOCK'
        )

    def test_no_radar_candidates(self):
        self.assertEqual(
            no_trade_reason({'trades_count': 0}, {}, {'effective': 'GREEN', 'gate': 'PASS'}, 0),
            '無有效 Radar candidates'
        )

    def test_probability_below_threshold(self):
        metrics = {'trades_count': 0}
        decisions = {'evaluations': 10, 'accepted_count': 0, 'max_probability': 0.5908, 'threshold': 0.6}
        self.assertEqual(
            no_trade_reason(metrics, decisions, {'effective': 'GREEN', 'gate': 'PASS'}, 5),
            'AI 最高 0.5908 < Threshold 0.6000'
        )

    def test_all_vetoed(self):
        metrics = {'trades_count': 0}
        decisions = {'evaluations': 10, 'accepted_count': 0, 'max_probability': 0.72, 'threshold': 0.6}
        self.assertEqual(
            no_trade_reason(metrics, decisions, {'effective': 'GREEN', 'gate': 'PASS'}, 5),
            '所有候選被 strategy veto'
        )

    def test_no_evaluations(self):
        metrics = {'trades_count': 0}
        decisions = {'evaluations': 0, 'accepted_count': 0}
        self.assertEqual(
            no_trade_reason(metrics, decisions, {'effective': 'GREEN', 'gate': 'PASS'}, 5),
            '未產生有效 AI 評估'
        )


class ReportBuilderTests(unittest.TestCase):
    def _make_ledger(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        path = Path(tmp.name) / 'state.sqlite'
        # Initialize schema and start a paper trade period.
        import easystock_admin.store as admin_store
        s = admin_store.Store(path=path)
        s.start_paper_trade(100000)
        with closing(sqlite3.connect(path)) as db:
            db.execute("UPDATE paper_trade_settings SET start_date='2026-10-01'")
            db.commit()
        return path, tmp

    def _cleanup(self, tmp):
        shutil.rmtree(tmp.name, ignore_errors=True)

    def test_zero_trades_still_produces_report(self):
        path, tmp = self._make_ledger()
        try:
            text = build_daily_summary(path, '2026-10-01', intraday_state={}, model_state={})
            self.assertIsNotNone(text)
            self.assertIn('📊 EasyStock 當沖日報', text)
            self.assertIn('日期：2026-10-01', text)
            self.assertIn('今日模擬當沖 0 筆。', text)
            self.assertIn('買進：0 筆', text)
            self.assertIn('賣出：0 筆', text)
            self.assertIn('100,000.00', text)
        finally:
            self._cleanup(tmp)

    def test_trades_reported_correctly(self):
        path, tmp = self._make_ledger()
        try:
            ts = '2026-10-01T09:30:00+08:00'
            buy = paper_ledger.buy('2303', '聯電', 100, path=path, timestamp=ts)
            paper_ledger.sell('2303', 101, path=path, timestamp=ts, trade_id=buy['trade_id'])
            text = build_daily_summary(path, '2026-10-01', intraday_state={}, model_state={})
            self.assertIn('買進：1 筆', text)
            self.assertIn('賣出：1 筆', text)
            self.assertIn('勝 / 敗：1 / 0', text)
            self.assertIn('聯電', text)
            self.assertNotIn('【無交易主因】', text)
        finally:
            self._cleanup(tmp)

    def test_intraday_state_shown_in_report(self):
        path, tmp = self._make_ledger()
        try:
            intraday = {
                'model_decisions': {
                    'evaluations': 4222,
                    'accepted_count': 0,
                    'missing_feature_count': 179,
                    'max_probability': 0.5908,
                    'max_probability_symbol': '2303',
                },
                'market_risk': {'effective': 'GREEN', 'gate': 'PASS'},
                'market_data': {'shioaji': 'HEALTHY', 'esun': 'HEALTHY', 'premarket': 'HEALTHY'},
                'radar_peak': 28,
            }
            model = {'version': 'research-2026-09-24', 'trained_through': '2026-09-24', 'threshold': 0.6}
            text = build_daily_summary(path, '2026-10-01', intraday_state=intraday, model_state=model)
            self.assertIn('Market Risk：GREEN / PASS', text)
            self.assertIn('Shioaji：HEALTHY', text)
            self.assertIn('玉山：HEALTHY', text)
            self.assertIn('Premarket：HEALTHY', text)
            self.assertIn('Radar 最高候選數：28', text)
            self.assertIn('Active Model：research-2026-09-24', text)
            self.assertIn('Threshold：0.6000', text)
            self.assertIn('今日模型評估：4222 次', text)
            self.assertIn('今日最高 Probability：0.5908', text)
            self.assertIn('最高分股票：2303', text)
            self.assertIn('AI 最高 0.5908 < Threshold 0.6000', text)
        finally:
            self._cleanup(tmp)

    def test_missing_intraday_state_shows_unknown_not_failure(self):
        path, tmp = self._make_ledger()
        try:
            text = build_daily_summary(path, '2026-10-01', intraday_state=None, model_state=None)
            self.assertIsNotNone(text)
            self.assertIn('Market Risk：UNKNOWN / UNKNOWN', text)
            self.assertIn('Shioaji：UNKNOWN', text)
            self.assertIn('玉山：UNKNOWN', text)
            self.assertIn('Premarket：UNKNOWN', text)
        finally:
            self._cleanup(tmp)


if __name__ == '__main__':
    unittest.main()
