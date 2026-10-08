from datetime import date, timedelta

import pytest

from rebound_learning.official import run
from rebound_learning.research_horizon import EXITS, evaluate, load_picks, simulate_exit
from rebound_learning.schema import connect
from rebound_learning_fixture import bars
from test_rebound_learning_v2 import _market_with


def bar(o, h, l, c):
    return {'open': o, 'high': h, 'low': l, 'close': c}


def test_exit_rules():
    flat = [bar(10, 10.2, 9.9, 10)] * 19 + [bar(10, 10.6, 9.9, 10.5)]
    assert simulate_exit(flat[:19], 12, 9, stop=False, take=False, horizon=20) is None
    assert simulate_exit([bar(12.5, 13, 12, 12.5)] + flat[1:], 12, 9, stop=False, take=False, horizon=20) is None
    assert simulate_exit(flat, 12, 9, stop=False, take=False, horizon=20) == pytest.approx(5)
    assert simulate_exit(flat, 12, 9, stop=False, take=False, horizon=5) == pytest.approx(0)
    dip = [flat[0], bar(9.5, 9.6, 8.5, 9)] + flat[2:]
    assert simulate_exit(dip, 12, 9, stop=True, take=False, horizon=20) == pytest.approx(-10)
    assert simulate_exit(dip, 12, 9, stop=False, take=False, horizon=20) == pytest.approx(5)
    spike = [flat[0], bar(10, 12.5, 9.9, 10)] + flat[2:]
    assert simulate_exit(spike, 12, 9, stop=True, take=True, horizon=20) == pytest.approx(20)
    assert simulate_exit(spike, 12, 9, stop=True, take=False, horizon=20) == pytest.approx(5)
    gap = [flat[0], bar(8, 8.2, 7.9, 8)] + flat[2:]
    assert simulate_exit(gap, 12, 9, stop=True, take=True, horizon=20) == pytest.approx(-20)


def test_reserved_partition_and_picks(tmp_path, monkeypatch):
    monkeypatch.setenv('EASYSTOCK_REBOUND_DATA_DIR', str(tmp_path))
    source = bars()
    last = date.fromisoformat(source[-1]['time'])
    extra = []
    for d in range(1, 60):
        day = last + timedelta(days=d)
        if day.weekday() < 5:
            extra.append({'time': day.isoformat(), 'open': 10.6, 'high': 10.8, 'low': 10.4, 'close': 10.7,
                          'volume': 1, 'amount': 10_000_000})
    market = _market_with(source + extra)
    signal = source[-1]['time']
    import rebound_learning.research_horizon as horizon
    monkeypatch.setattr(horizon, 'HISTORICAL_START', '2020-01-01')
    with connect(tmp_path / 'v2.sqlite') as db:
        run(market, db, signal, signal, progress=False)
        picks = load_picks(db, market, reserved_from=extra[-1]['time'])
        assert [p['date'] for p in picks] == [signal] and len(picks[0]['bars']) == 20
        assert load_picks(db, market, reserved_from=extra[15]['time']) == []  # 20-session horizon not complete
        assert load_picks(db, market, reserved_from=signal) == []
    folds = ((signal, signal),)
    report = evaluate(picks, folds=folds)
    assert set(report['exits']) == {name for name, *_ in EXITS}
    assert report['exits']['TIME_H20']['folds'][0]['trades'] == 1
    assert report['decision']['production_ready'] is False
    assert report['decision']['outcome'] == 'REJECTED'  # one trade cannot satisfy E (>= 100 per fold)
