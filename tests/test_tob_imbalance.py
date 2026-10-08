"""TOB_IMBALANCE_V1: imbalance buckets, point metrics, short-side net and the frozen classification."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for sub in ('research/tob_imbalance_v1', 'research/passive_fill_v1', 'research/hv60_v1', '.'):
    sys.path.insert(0, str(ROOT / sub))
import pf_fill as F  # noqa: E402
import tob_finalize as TF  # noqa: E402
import tob_run as T  # noqa: E402

S = 1_000_000


def test_imbalance_and_bucket_edges():
    assert T.imbalance(30, 10) == pytest.approx(0.5)
    assert T.imbalance(0, 0) is None
    assert [T.bucket(x) for x in (-1, -0.6, -0.59, -0.2, 0, 0.2, 0.21, 0.59, 0.6, 1)] == [
        'B1', 'B1', 'B2', 'B3', 'B3', 'B3', 'B4', 'B4', 'B5', 'B5']


def ticks(rows):
    cols = list(zip(*rows))
    return F.Ticks([c * S for c in cols[0]], *[list(c) for c in cols[1:]])


def test_point_uses_touch_sizes_and_costs():
    t = ticks([(0, 100.0, 1, 1, 99.9, 100.1, 80, 20), (60, 100.2, 1, 1, 100.1, 100.3, 10, 10)])
    p = T.point(t, 0, 60 * S)
    assert p['bucket'] == 'B5' and p['imb'] == pytest.approx(0.6)
    assert p['mid'] == pytest.approx((100.2 / 100.0 - 1) * 1e4)
    assert p['long_net'] < p['mid'] - 40           # buy ask 100.1, sell bid 100.1 + fees + tax
    assert p['short_net'] < -40
    assert T.point(t, 0, 600 * S) is None          # no fresh quote at the exit time
    assert T.point(ticks([(0, 100.0, 1, 1, 99.9, 100.1, 0, 0)]), 0, 0) is None


def test_short_net_matches_hand_calculation():
    # sell 100.00 / buy 99.00 x 1000: gross 1000 TWD; fees ~40 + ~40 (0.1425% x 0.28), tax 150 -> net ~770 of 100,000
    assert T.short_net_pct(100.0, 99.0) == pytest.approx(0.77, abs=0.005)


def day(fold, n_b, mid_b, net_b, n_a, mid_a, net_a, key='5m|ALL|'):
    return (fold, {key + 'B5': [n_b, mid_b, net_b, 0], key + 'ALL': [n_a, mid_a, net_a, 0]})


def test_excess_and_classification():
    days = {'d%02d' % i: day(1 + i % 5, 100, 100 * 3.0, 100 * -40.0, 1000, 1000 * 0.0, 1000 * -45.0) for i in range(20)}
    e = TF.excess(days, '5m|ALL|B5', '5m|ALL|ALL', 1)
    assert e['excess'] == pytest.approx(3.0) and e['n'] == 2000
    # identical days -> zero residuals -> no clustered SE; the criteria must then fail the t test
    s = TF.summarize(days, '5m', 'ALL', 'B5', 'LONG')
    assert s['net_bps'] == pytest.approx(-40.0) and s['directional_excess_mid_bps'] == pytest.approx(3.0)
    c = TF.criteria(s)
    assert c['C'] is False and c['D'] is False and c['G'] is False
    assert TF.classify(c) == 'INSUFFICIENT'
    ok = {'A': True, 'B': True, 'C': False, 'D': False, 'G': True}
    assert TF.classify(ok) == 'SIGNAL_COST_BLOCKED'
    assert TF.classify(dict(ok, A=False)) == 'NO_EDGE'
    assert TF.classify(dict(ok, C=True, D=True)) == 'STRONG'
    assert TF.classify(dict(ok, D=True)) == 'SIGNAL_COST_BLOCKED'
    assert TF.classify(dict(ok, C=True)) == 'WEAK'
