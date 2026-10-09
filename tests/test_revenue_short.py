"""REVENUE_SHORT_V1: portfolio construction with unfillable limit-up opens, criteria and the homepage rule."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'research' / 'revenue_v1'))
import rev_short as S  # noqa: E402


def test_portfolios_rank_before_the_open_and_leave_unfilled_top10_slots_in_cash():
    scores = {'%04d' % (1000 + i): float(i) for i in range(1, 31)}          # 30 names, 1030 scores highest
    ret = {s: 1.0 for s in scores}
    ret['1030'] = 10.0
    p = S.portfolios(scores, ret, limit_up={'1030'})
    assert p['n_dec'] == 2                                                   # ceil(3) decile minus the limit-up name
    assert p['dec'] == pytest.approx(1.0)
    assert p['top10_names'][0] == '1030' and p['n_top10'] == 9
    assert p['top10'] == pytest.approx(0.9)                                  # nine filled slots at 1%, one slot in cash
    assert p['n_universe'] == 29 and p['universe'] == pytest.approx(1.0)
    assert S.portfolios({'1001': 1.0}, {'1001': 1.0}, limit_up={'1001'}) is None


def months(top, excess, n=10):
    return [{'fold': f, 'top': top + (0.1 if k % 2 else -0.1), 'excess': excess + (0.01 if k % 2 else -0.01), 'n': n}
            for f in S.R.FOLDS for k in range(10)]


def test_criteria_size_gate_and_per_million_figure():
    c, st = S.criteria(months(0.8, 0.3), min_size=8)
    assert all(c.values()) and S.R.classify(c) == 'STRONG'
    assert st['twd_per_1m_per_event'] == 8000 and st['win_months'] == 50
    assert st['mean_top_net_slip_pct'] == pytest.approx(0.4)
    c, _ = S.criteria(months(0.8, 0.3, n=7), min_size=8)
    assert c['G'] is False and S.R.classify(c) == 'INSUFFICIENT'


def result(cls, a=True, b=True, excess=0.2):
    return {'classification': cls, 'criteria': {'A': a, 'B': b}, 'stats': {'mean_excess_pct': excess}}


def test_homepage_rule():
    assert S.decide({'DEC|H10': result('STRONG'), 'TOP10|H10': result('WEAK')}) == {'horizon': 'H10', 'list': 'TOP10'}
    assert S.decide({'DEC|H10': result('STRONG'), 'TOP10|H10': result('WEAK', b=False)}) == {'horizon': 'H10', 'list': 'DECILE'}
    assert S.decide({'DEC|H10': result('STRONG'), 'TOP10|H10': result('STRONG', excess=-0.1)})['list'] == 'DECILE'
    assert S.decide({'DEC|H10': result('WEAK'), 'TOP10|H10': result('STRONG')}) == {'horizon': 'H5', 'list': 'DECILE'}
