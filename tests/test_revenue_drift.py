"""REVENUE_DRIFT_V1 helpers: timing, signals, costs, deciles and the frozen classification."""
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'research' / 'revenue_v1'))
import rev_study as R  # noqa: E402


def test_add_months_wraps_years():
    assert R.add_months('2025-12', 1) == '2026-01'
    assert R.add_months('2026-01', -1) == '2025-12'
    assert R.add_months('2026-03', -12) == '2025-03'


def test_entry_session_is_the_session_after_the_rolled_deadline():
    s = ['2026-05-08', '2026-05-11', '2026-05-12', '2026-06-09', '2026-06-10', '2026-06-11']
    assert R.entry_session(s, '2026-04') == '2026-05-12'   # 10th is a Sunday -> deadline 11th -> enter 12th
    assert R.entry_session(s, '2026-05') == '2026-06-11'   # deadline on the 10th itself
    assert R.entry_session(s[:5], '2026-05') is None


def test_yoy_growth_and_sur():
    assert R.yoy(120, 100) == pytest.approx(0.2)
    assert R.yoy(120, 0) is None and R.growth(0, 100) is None
    hist = [0.1, 0.3] * 6                  # mean 0.2, population std 0.1
    assert R.sur(hist, 0.5) == pytest.approx(3.0)
    assert R.sur(hist[:11], 0.5) is None
    assert R.sur([0.2] * 12, 0.5) is None  # zero dispersion
    assert R.sur(hist[:11] + [None], 0.5) is None


def test_cost_uses_day_trade_or_ordinary_tax():
    # 100 TWD x 1000: fee 39.9 -> 40 each leg; tax 150 (day trade) or 300 (ordinary)
    assert R.cost_pct(100, 100, same_day=True) == pytest.approx(0.23)
    assert R.cost_pct(100, 100, same_day=False) == pytest.approx(0.38)


def test_deciles_take_ceil_ten_percent_with_symbol_tiebreak():
    scores = {'%04d' % i: float(i % 7) for i in range(1001, 1012)}   # 11 names -> 2 each side
    top, bottom = R.deciles(scores)
    assert top == ['1007', '1006']
    assert bottom == ['1001', '1008']


def months(top, excess, per_fold=10):
    return [{'fold': f, 'top': top, 'excess': excess + (0.01 if k % 2 else -0.01), 'n_top': 25}
            for f in R.FOLDS for k in range(per_fold)]


def test_criteria_and_classification():
    c, st = R.criteria(months(0.5, 0.3))
    assert all(c.values()) and R.classify(c) == 'STRONG'
    assert st['t_excess'] > 2
    c, _ = R.criteria(months(-0.5, 0.3))
    assert R.classify(c) == 'RELATIVE_ONLY'
    c, _ = R.criteria(months(-0.5, -0.3))
    assert R.classify(c) == 'NO_EDGE'
    c, _ = R.criteria(months(0.5, 0.3, per_fold=7))
    assert R.classify(c) == 'INSUFFICIENT'
    assert math.isclose(R.criteria(months(0.5, 0.3))[1]['mean_top_net_pct'], 0.5)
