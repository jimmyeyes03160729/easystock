"""0050 benchmark helpers: page parsing, dividend and split factors, window return, costs and the comparison."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'research' / 'revenue_v1'))
import etf0050 as E  # noqa: E402
import rev_bench as RB  # noqa: E402


def test_parse_days_and_exrights():
    days = E.parse_days({'stat': 'OK', 'data': [['114/06/02', '21,228,875', '3,738,759,521', '178.00', '178.05', '175.25', '175.90', '-3.85', '71,584', ''],
                                                 ['114/06/03', '0', '0', '--', '--', '--', '--', '0.00', '0', '']]})
    assert days == [('2025-06-02', 178.0, 175.9, 21228875.0, 3738759521.0)]
    assert E.parse_days({'stat': '很抱歉'}) == []
    row = ['114年01月17日', '0050', '元大台灣50', '198.05', '195.35', '2.700000', '息']
    other = ['114年01月17日', '00940', 'x', '9.41', '9.38', '0.03', '息']
    assert E.parse_exrights({'data': [row, other]}) == [('2025-01-17', 198.05, 195.35, '息')]


def test_daily_factor_dividend_split_and_plain_day():
    assert E.daily_factor(100.0, 101.0, None) == pytest.approx(1.01)
    assert E.daily_factor(198.05, 196.0, (198.05, 195.35)) == pytest.approx((196.0 + 2.70) / 198.05)
    assert E.daily_factor(181.3, 45.5, None) == pytest.approx(45.5 * 4 / 181.3)         # 1-for-4 split, no dividend record
    assert E.daily_factor(100.0, 80.0, None) == pytest.approx(0.8)                       # a real -20% day is not a split


def test_open_to_close_return_chains_the_days():
    days = [('2025-01-15', 100.0, 101.0), ('2025-01-16', 101.0, 103.0), ('2025-01-17', 99.0, 100.0)]
    exdiv = {'2025-01-17': (103.0, 100.5)}
    r = E.open_to_close_return(days, exdiv, '2025-01-16', '2025-01-17')
    assert r == pytest.approx((103.0 / 101.0) * ((100.0 + 2.5) / 103.0) - 1)
    assert E.open_to_close_return(days, exdiv, '2025-01-16', '2025-01-16') == pytest.approx(103.0 / 101.0 - 1)
    assert E.open_to_close_return(days, exdiv, '2025-01-18', '2025-01-17') is None


def test_cost_uses_the_etf_tax():
    # 50 TWD x 1000: fee 20 (minimum) each leg + 0.1% tax of 50 = 20 + 20 + 50 on 50,000
    assert E.cost_pct(50.0, 50.0) == pytest.approx((20 + 20 + 50) / 50000 * 100)


def test_compare_and_t_stat():
    days = [('2025-01-02', 100.0, 101.0), ('2025-01-03', 101.0, 102.0), ('2025-01-06', 102.0, 103.0)]
    ev = [{'month': '2024-12', 'entry': '2025-01-02', 'exit': '2025-01-03', 'top': 5.0, 'universe': 1.0},
          {'month': '2025-01-x', 'entry': '2025-01-03', 'exit': '2025-01-06', 'top': -1.0, 'universe': 0.5}]
    out = RB.compare(ev, days, {})
    assert out['events'] == 2 and out['beat_etf'] == 1
    assert out['mean_diff_pct'] == pytest.approx(out['mean_net_pct'] - out['mean_etf_pct'])
    assert RB.compare([{'month': 'm', 'entry': '2025-02-03', 'exit': '2025-02-04', 'top': 1.0, 'universe': 0.0}], days, {}) is None
    assert RB.t_stat([1.0]) is None and RB.t_stat([1.0, 2.0, 3.0]) == pytest.approx(3.4641, abs=1e-3)
