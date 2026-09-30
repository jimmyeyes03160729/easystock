"""Offline regression cases for real risk versus missing market evidence."""
import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('market_risk_under_test', ROOT / 'market_risk.py')
RISK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RISK)
NOW = datetime(2026, 9, 30, 10, tzinfo=timezone(timedelta(hours=8)))


def brief(level='GREEN', day='2026-09-30'):
    return {'scan_date': day, 'generated_at': f'{day}T08:35:00+08:00',
            'base_risk_score': {'GREEN': 20, 'YELLOW': 50, 'RED': 80}[level]}


def quote(source, change=0, seconds=0, now=NOW):
    return RISK.snapshot_risk({'ts': (now + timedelta(seconds=seconds)).timestamp() * 1000,
                               'change_rate': change}, now, source=source)


class MarketRiskGateTests(unittest.TestCase):
    def test_fresh_premarket_and_live_green(self):
        gate = RISK.MarketGate().update(brief(), {'shioaji': quote('shioaji')}, NOW)
        self.assertEqual((gate['market_risk'], gate['gate_action']), ('GREEN', 'PASS'))

    def test_stale_premarket_does_not_turn_fresh_live_red(self):
        gate = RISK.MarketGate().update(brief(day='2026-09-29'), {'shioaji': quote('shioaji')}, NOW)
        self.assertEqual((gate['premarket_risk'], gate['market_risk']), ('UNKNOWN', 'GREEN'))

    def test_esun_fresh_when_shioaji_stale(self):
        sources = {'shioaji': quote('shioaji', seconds=-91), 'esun': quote('esun')}
        gate = RISK.MarketGate().update(brief(day='2026-09-29'), sources, NOW)
        self.assertEqual((gate['market_risk'], gate['source_count'], gate['source']), ('GREEN', 1, 'esun'))
        self.assertEqual(gate['data_health'], 'DEGRADED')

    def test_shioaji_fresh_when_esun_unavailable(self):
        sources = {'shioaji': quote('shioaji'), 'esun': RISK.snapshot_risk(None, NOW, source='esun')}
        self.assertEqual(RISK.MarketGate().update(brief(), sources, NOW)['gate_action'], 'PASS')

    def test_esun_fresh_when_shioaji_unavailable(self):
        sources = {'shioaji': RISK.snapshot_risk(None, NOW), 'esun': quote('esun')}
        self.assertEqual(RISK.MarketGate().update(brief(), sources, NOW)['source'], 'esun')

    def test_both_unavailable_blocks_without_fake_red(self):
        sources = {'shioaji': RISK.snapshot_risk(None, NOW), 'esun': RISK.snapshot_risk(None, NOW, source='esun')}
        gate = RISK.MarketGate().update(brief(), sources, NOW)
        self.assertEqual((gate['market_risk'], gate['gate_action'], gate['gate_reason']),
                         ('UNKNOWN', 'BLOCK', 'market_data_unavailable'))

    def test_premarket_red_yields_to_confirmed_live_recovery(self):
        machine = RISK.MarketGate(confirmations=2)
        states = []
        for step in range(4):
            current = NOW + timedelta(seconds=30 * step)
            states.append(machine.update(brief('RED'), {'shioaji': quote('shioaji', now=current)}, current)['market_risk'])
        self.assertEqual(states, ['RED', 'YELLOW', 'YELLOW', 'GREEN'])

    def test_repeated_same_quote_does_not_confirm_recovery(self):
        machine = RISK.MarketGate(confirmations=2)
        first = quote('shioaji')
        self.assertEqual(machine.update(brief('RED'), {'shioaji': first}, NOW)['market_risk'], 'RED')
        self.assertEqual(machine.update(brief('RED'), {'shioaji': first}, NOW + timedelta(seconds=30))['market_risk'], 'RED')

    def test_crash_blocks_immediately_even_after_green(self):
        machine = RISK.MarketGate()
        machine.update(brief(), {'shioaji': quote('shioaji')}, NOW)
        gate = machine.update(brief(), {'shioaji': quote('shioaji', change=-2.1)}, NOW)
        self.assertEqual((gate['market_risk'], gate['gate_reason']), ('RED', 'market_risk_red'))

    def test_yesterday_brief_is_never_fresh(self):
        self.assertEqual(RISK.premarket_context(brief(day='2026-09-29'), NOW)[0], 'UNKNOWN')

    def test_wrong_generated_date_is_never_fresh(self):
        value = brief()
        value['generated_at'] = '2026-09-29T08:35:00+08:00'
        self.assertEqual(RISK.premarket_context(value, NOW)[0], 'UNKNOWN')

    def test_future_or_stale_provider_quote_is_unusable(self):
        for seconds in (-91, 1):
            with self.subTest(seconds=seconds):
                self.assertFalse(quote('shioaji', seconds=seconds)['valid'])

    def test_one_fresh_provider_is_sufficient(self):
        gate = RISK.MarketGate().update(brief(),
            {'shioaji': quote('shioaji', seconds=-91), 'esun': quote('esun')}, NOW)
        self.assertTrue(gate['valid'])
        self.assertEqual(gate['gate_action'], 'PASS')

    def test_red_is_not_downgraded_by_second_green_source(self):
        gate = RISK.MarketGate().update(brief(),
            {'shioaji': quote('shioaji', change=-2.1), 'esun': quote('esun')}, NOW)
        self.assertEqual(gate['market_risk'], 'RED')


if __name__ == '__main__':
    unittest.main()
