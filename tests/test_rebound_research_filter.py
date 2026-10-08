import pytest

from rebound_learning.research_filter import MIN_UNSEEN_TRADES, evaluate, market_on, profit_factor_ok, trade


def pick(day, bias, close_d20, symbol='1101'):
    bars = [{'time': f'd{i}', 'open': 10, 'high': 10.2, 'low': 9.9, 'close': 10} for i in range(19)]
    bars.append({'time': 'd19', 'open': 10, 'high': 10.2, 'low': 9.9, 'close': close_d20})
    return {'date': day, 'symbol': symbol, 'taiex_bias_ma60_pct': bias, 'target': 12, 'invalid': 9, 'bars': bars}


def days(prefix, n):
    return [f'{prefix}-{i:03d}' for i in range(n)]


def test_filter_and_trade():
    assert market_on({'taiex_bias_ma60_pct': 0.5}) and not market_on({'taiex_bias_ma60_pct': -0.1})
    assert not market_on({'taiex_bias_ma60_pct': None})
    assert trade(pick('x', 1, 10.5)) == pytest.approx(5 - 0.6)
    assert profit_factor_ok({'trades': 3, 'profit_factor': None})   # no losing trade
    assert not profit_factor_ok({'trades': 0, 'profit_factor': None})
    assert not profit_factor_ok({'trades': 9, 'profit_factor': 1.0})
    assert trade({**pick('x', 1, 10.5), 'bars': None}) is None


def test_decision_paths():
    good_unseen = [pick(d, 1.0, 10.5) for d in days('2022', MIN_UNSEEN_TRADES)]
    bad_off = [pick(d, -1.0, 8.0) for d in days('2022b', 50)]  # filtered out: never traded
    good_exposed = [pick(d, 1.0, 10.3) for d in days('2024', 40)]
    bad_exposed = [pick(d, 1.0, 9.8) for d in days('2024', 40)]
    folds = (('2024', '2024~'),)

    r = evaluate(good_unseen + bad_off, good_exposed, folds=folds)
    assert r['unseen_2022']['filtered']['trades'] == MIN_UNSEEN_TRADES
    assert r['unseen_2022']['unfiltered_descriptive']['trades'] == MIN_UNSEEN_TRADES + 50
    assert r['decision']['outcome'] == 'CONFIRMATION_CANDIDATE' and r['decision']['production_ready'] is False

    assert evaluate(good_unseen, bad_exposed, folds=folds)['decision']['outcome'] == 'REJECTED'
    few = good_unseen[:MIN_UNSEEN_TRADES - 1]
    assert evaluate(few, good_exposed, folds=folds)['decision']['outcome'] == 'INCONCLUSIVE_HOLDOUT_DECIDES'
    assert evaluate(few, bad_exposed, folds=folds)['decision']['outcome'] == 'REJECTED'
    losing = [pick(d, 1.0, 9.5) for d in days('2022', MIN_UNSEEN_TRADES)]
    assert evaluate(losing, good_exposed, folds=folds)['decision']['stage1_unseen_2022'] == 'FAIL'
