"""OPEN_FADE_V1: row construction, daily ranking, criteria and classification."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for sub in ('research/open_fade_v1', 'research/passive_fill_v1', 'research/hv60_v1', '.'):
    sys.path.insert(0, str(ROOT / sub))
import ofd_finalize as FZ  # noqa: E402
import ofd_run as RUN  # noqa: E402
import pf_fill as F  # noqa: E402

S = 1_000_000
D0 = 0


def ticks(rows):
    cols = list(zip(*rows))
    return F.Ticks([D0 + c * S for c in cols[0]], *[list(c) for c in cols[1:]])


def test_row_for_needs_open_tick_and_fresh_touch_quotes():
    t = ticks([(9 * 3600 + 5, 103.0, 1, 1, 102.9, 103.1, 5, 5),
               (9 * 3600 + 30 * 60 - 10, 104.0, 1, 1, 103.9, 104.1, 5, 5),
               (12 * 3600 + 55 * 60 - 10, 102.0, 1, 2, 101.9, 102.1, 5, 5)])
    r = RUN.row_for(t, D0, 100.0)
    assert r['gap'] == pytest.approx(3.0) and r['run'] == pytest.approx(4.0)
    assert r['mid'] == pytest.approx((102.0 / 104.0 - 1) * 1e4)
    assert r['short_net'] < (103.9 / 102.1 - 1) * 1e4 - 20            # bid 103.9 sold, ask 102.1 bought, minus fees and tax
    assert RUN.row_for(t, D0, None) is None and RUN.row_for(t, D0, 0.0) is None
    late = ticks([(9 * 3600 + 120, 103.0, 1, 1, 102.9, 103.1, 5, 5)] + [(12 * 3600 + 55 * 60 - 10, 102.0, 1, 2, 101.9, 102.1, 5, 5)])
    assert RUN.row_for(late, D0, 100.0) is None                         # no tick within 09:00:60 of the open
    stale = ticks([(9 * 3600 + 5, 103.0, 1, 1, 102.9, 103.1, 5, 5), (12 * 3600 + 55 * 60 - 10, 102.0, 1, 2, 101.9, 102.1, 5, 5)])
    assert RUN.row_for(stale, D0, 100.0) is None                        # last tick before 09:30 is older than 30 s


def mk(sym, key_value, short_net=-30.0, mid=-10.0):
    return {'sym': sym, 'gap': key_value, 'run': key_value, 'short_net': short_net, 'long_net': -40.0, 'mid': mid}


def test_ranking_and_day_event():
    rows = [mk('%04d' % (1000 + i), float(i)) for i in range(60)]
    rows[59]['short_net'] = 50.0
    top, bottom, k = FZ.top_bottom(rows, 'gap')
    assert k == 6 and [r['sym'] for r in top][:2] == ['1059', '1058'] and bottom[-1]['sym'] == '1000'
    ev = FZ.day_event(rows, 'gap')
    assert ev['k'] == 6 and ev['base'] == pytest.approx((59 * -30.0 + 50.0) / 60)
    assert ev['top'] == pytest.approx((5 * -30.0 + 50.0) / 6) and ev['excess'] == pytest.approx(ev['top'] - ev['base'])
    assert ev['quota3'] == pytest.approx((2 * -30.0 + 50.0) / 3)
    assert FZ.day_event(rows[:49], 'gap') is None


def events(top, exc, per_fold=100):
    return [{'fold': f, 'top': top + (1.0 if i % 2 else -1.0), 'excess': exc + (1.0 if i % 2 else -1.0)} for f in FZ.FOLDS for i in range(per_fold)]


def test_criteria_and_classification():
    c, st = FZ.criteria(events(10.0, 5.0))
    assert all(c.values()) and FZ.classify(c) == 'STRONG' and st['t_excess'] > 2
    c, _ = FZ.criteria(events(-10.0, 5.0))
    assert FZ.classify(c) == 'RELATIVE_ONLY'
    c, _ = FZ.criteria(events(-10.0, -5.0))
    assert FZ.classify(c) == 'NO_EDGE'
    c, _ = FZ.criteria(events(10.0, 5.0, per_fold=50))
    assert FZ.classify(c) == 'INSUFFICIENT'


def test_v2_uses_only_days_below_the_v1_symbol_threshold_and_decides_on_folds_1_to_4(tmp_path, monkeypatch):
    import json
    import ofd_finalize_v2 as V2
    work = tmp_path / 'work'
    work.mkdir()

    def day(date, fold, n, shift):
        rows = [{'sym': '%04d' % (1000 + i), 'gap': float(i), 'run': float(i), 'short_net': -30.0 + ((60.0 + shift) if i >= n - 4 else 0.0),
                 'long_net': -40.0, 'mid': -10.0, 'hv': 0, 'core': int(i < 20)} for i in range(n)]
        (work / (date + '.json')).write_text(json.dumps({'date': date, 'fold': fold, 'failed': 0, 'rows': rows}))

    k = 0
    for fold in (1, 2, 3, 4):
        for _ in range(45):
            day('2025-01-%03d-%d' % (k, fold), fold, 40, float(k % 7 - 3))
            k += 1
    day('2026-06-01', 5, 70, 0.0)          # consumed by V1 (>= 50 valid symbols)
    day('2025-02-01', 1, 20, 0.0)          # too few symbols
    monkeypatch.setattr(V2, 'WORK', work)
    monkeypatch.setattr(V2, 'OUT', tmp_path / 'out')
    V2.main()
    d = json.loads((tmp_path / 'out' / 'OPEN_FADE_V2_DECISION.json').read_text())
    assert d['counts'] == {'DAYS_CONSUMED_BY_V1': 1, 'DAYS_TOO_FEW_SYMBOLS': 1, 'DAYS_USED': 180}
    r = d['results']['gap|ALL']
    assert r['stats']['events'] == 180 and r['stats']['mean_top_size'] == 4 and r['classification'] == 'STRONG'
    assert d['family'] == 'STRONG_CANDIDATE'
