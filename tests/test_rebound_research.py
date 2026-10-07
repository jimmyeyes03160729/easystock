from datetime import date, timedelta
import json

import pytest

from rebound_learning import research
from rebound_learning.official import audit, run
from rebound_learning.research import evaluate, load_rows, simulate
from rebound_learning.schema import connect
from rebound_learning_fixture import bars
from test_rebound_learning_v2 import _market_with


def bar(o, h, l, c):
    return {'open': o, 'high': h, 'low': l, 'close': c}


def test_simulate_bracket_rules():
    flat = [bar(10, 10.2, 9.9, 10)] * 10
    assert simulate(flat[:9], 12, 9) is None                       # incomplete horizon
    assert simulate([bar(12.5, 13, 12, 12.5)] + flat[1:], 12, 9) is None  # D1 opens above target: no fill
    assert simulate([bar(10, 10.1, 8.5, 12.5)] + flat[1:], 12, 9) == pytest.approx(-10)  # stop first in a bar
    gap = [bar(10, 10.1, 9.5, 9.8), bar(8, 8.2, 7.9, 8)] + flat[2:]
    assert simulate(gap, 12, 9) == pytest.approx(-20)                # D2 gap through stop exits at open
    win = [bar(10, 10.1, 9.5, 9.8), bar(10, 12.3, 9.9, 12)] + flat[2:]
    assert simulate(win, 12, 9) == pytest.approx(20)
    assert simulate([bar(10, 10.1, 9.9, 10)] * 9 + [bar(10, 10.5, 9.9, 10.5)], 12, 9) == pytest.approx(5)


def _synthetic(days=400, per_day=6, seed=7):
    import random
    rng = random.Random(seed)
    start, calendar, rows = date(2023, 1, 2), [], []
    d = start
    while len(calendar) < days:
        if d.weekday() < 5:
            calendar.append(d.isoformat())
        d += timedelta(days=1)
    for day in calendar:
        for j in range(per_day):
            signal = rng.gauss(0, 1)
            net = 2.0 * signal + rng.gauss(0, 1)  # the feature predicts the outcome
            rows.append({'date': day, 'symbol': f'{1000 + j}', 'kind': 'PENDING' if j < 4 else 'BOTTOM_ZONE',
                         'x': [signal, rng.gauss(0, 1), None if j == 0 else 1.0],
                         'breakout': j % 2 == 0, 'score': 60 + j, 'gross': net + 0.6, 'net': net})
    return rows, calendar


def test_evaluate_embargo_criteria_and_selection():
    pytest.importorskip('sklearn')
    rows, calendar = _synthetic()
    folds = ((calendar[200], calendar[259]), (calendar[260], calendar[319]), (calendar[320], calendar[399]))
    report = evaluate(rows, calendar, folds=folds, variants=research.VARIANTS[:2])
    for variant in report['variants'].values():
        for fold, (start, _) in zip(variant['folds'], folds):
            first = calendar.index(start)
            assert fold['train_cutoff'] == calendar[first - research.EMBARGO_SESSIONS]
        assert variant['pooled']['delta_mean_net_pct'] > 0     # a predictive feature beats rule order
        assert set(variant['criteria']) >= {'A_pooled_delta_positive', 'G_bootstrap_p10_delta_positive', 'ALL_PASS'}
    wide = report['variants']['RIDGE_WIDE_POOL']['folds'][0]['train_rows']
    narrow = report['variants']['RIDGE_RULE_ONLY']['folds'][0]['train_rows']
    assert wide > narrow
    assert report['decision']['production_ready'] is False
    assert report['decision']['outcome'] in ('SHADOW_CANDIDATE', 'REJECTED')


def test_reserved_partition_is_never_loaded(tmp_path, monkeypatch):
    monkeypatch.setenv('EASYSTOCK_REBOUND_DATA_DIR', str(tmp_path))
    source = bars()
    last = date.fromisoformat(source[-1]['time'])
    extra = []
    for d in range(1, 40):
        day = last + timedelta(days=d)
        if day.weekday() < 5:
            extra.append({'time': day.isoformat(), 'open': 10.6, 'high': 10.8, 'low': 10.4, 'close': 10.7,
                          'volume': 1, 'amount': 10_000_000})
    market = _market_with(source + extra)
    signal = source[-1]['time']
    with connect(tmp_path / 'v2.sqlite') as db:
        run(market, db, signal, signal, progress=False)
        monkeypatch.setattr(research, 'HISTORICAL_START', '2020-01-01')
        loaded, names, _ = load_rows(db, market, reserved_from=extra[-1]['time'])
        assert [r['date'] for r in loaded] == [signal] and names
        # Horizon would reach the reserved partition: the row is not loaded at all.
        assert load_rows(db, market, reserved_from=extra[5]['time'])[0] == []
        # Signals on/after the reserved start are never loaded.
        assert load_rows(db, market, reserved_from=signal)[0] == []
        monkeypatch.setitem(research.SETTINGS, 'reserved_confirmation_start', signal)
        report = audit(market, db, write=False)
        assert report['total_rows'] == 0 and report['blinded_from'] == signal
