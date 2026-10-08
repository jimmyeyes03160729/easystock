import json
from datetime import date, timedelta
import sqlite3

import pytest

from deploy.prepare_rebound_historical_audit import prepare
from rebound_learning import research, research_horizon
from rebound_learning.market_daily import connect as market_connect, future_bars
from rebound_learning.research_correction import block_bootstrap
from rebound_learning.schema import connect
from rebound_learning.simulation import replay, session_bars, missing_outcome_threshold, cost_sensitivity


def flat(day=None):
    return {'time': day, 'open': 100, 'high': 101, 'low': 99, 'close': 100}


def test_early_exit_survives_later_missing_bar_and_short_horizon_is_independent():
    bars = [flat(), {**flat(), 'high': 111}] + [flat()] * 12 + [None] + [flat()] * 5
    resolved = replay(bars, 110, 90, stop=True, take=True, horizon=20)
    assert resolved == {'status': 'EXECUTED', 'gross': pytest.approx(10), 'exit_session': 2}
    assert replay(bars, 110, 90, stop=False, take=False, horizon=5)['gross'] == 0
    assert replay(bars, 110, 90, stop=False, take=False, horizon=20)['status'] == 'UNRESOLVED_MISSING_BAR'
    bars[1] = None
    assert replay(bars, 110, 90, stop=True, take=True, horizon=20)['status'] == 'UNRESOLVED_MISSING_BAR'
    bars[0] = None
    assert replay(bars, 110, 90, stop=True, take=True, horizon=20)['status'] == 'NO_FILL_D1_MISSING'


def test_gap_and_stop_priority_are_shared_by_p2_and_p3():
    bars = [flat(), {**flat(), 'open': 85, 'high': 112, 'low': 84}] + [flat()] * 18
    assert research.simulate(bars, 110, 90) == pytest.approx(-15)
    assert research_horizon.simulate_exit(bars, 110, 90, stop=True, take=True, horizon=20) == pytest.approx(-15)
    bars[0] = {**flat(), 'high': 112, 'low': 89}
    assert research.simulate(bars, 110, 90) == pytest.approx(-10)


def insert_bar(market, symbol, day, high=101):
    market.execute('INSERT INTO bars VALUES (?,?,?,?,?,?,?,?,?,?)',
                   (symbol, day, 'TWSE', 100, high, 99, 100, 1000, 10000000, 100))


def test_sql_boundary_applies_before_fetch_even_when_stock_is_suspended():
    market = market_connect(':memory:')
    for day in ('2026-10-01', '2026-10-06', '2026-10-07', '2026-10-08'):
        insert_bar(market, '2330', day)
    trace = []
    market.set_trace_callback(trace.append)
    actual = future_bars(market, '2330', '2026-10-01', 20, before='2026-10-07')
    assert [b['time'] for b in actual] == ['2026-10-06']
    bar_query = next(q for q in trace if 'SELECT * FROM bars' in q)
    assert "day<'2026-10-07'" in bar_query
    assert all('2026-10-08' not in q for q in trace)
    aligned = session_bars(market, '2330', '2026-10-01', ['2026-10-02', '2026-10-06'], before='2026-10-07')
    assert aligned[0] is None and aligned[1]['time'] == '2026-10-06'
    with pytest.raises(ValueError, match='boundary'):
        future_bars(market, '2330', '2026-10-07', before='2026-10-07')


def test_p2_and_p3_rank_without_future_availability_and_keep_slots(tmp_path):
    market = market_connect(':memory:')
    calendar = [(date(2024, 1, 1) + timedelta(days=i)).isoformat() for i in range(22)]
    with connect(tmp_path / 'dataset.sqlite') as db:
        db.executemany('INSERT INTO trading_days VALUES (?)', [(d,) for d in calendar])
        for j, symbol in enumerate(('A', 'B', 'C', 'D')):
            snapshot = {'signal_date': calendar[0], 'symbol': symbol, 'candidate_kind': 'PENDING',
                        'features': {'x': j, 'taiex_bias_ma60_pct': 1},
                        'evidence': {'confirmation': 'breakout', 'rule_score': 4 - j,
                                     'target_price': 110, 'invalid_price': 90}}
            db.execute('INSERT INTO candidates VALUES (?,?,?,?,?,?,?,NULL)',
                       (symbol, 'v', 2, calendar[0], symbol, 'PENDING', json.dumps(snapshot)))
            for i, day in enumerate(calendar):
                if symbol == 'A' and i == 1:
                    continue  # D1 missing; its rank slot cannot go to D
                insert_bar(market, symbol, day)
        rows, _, _ = research.load_rows(db, market, reserved_from='2024-02-01')
        picks = research_horizon.load_picks(db, market, reserved_from='2024-02-01')
    assert [r['symbol'] for r in rows] == ['A', 'B', 'C', 'D']
    assert [r['symbol'] for r in picks] == ['A', 'B', 'C']
    assert rows[0]['status'] == 'NO_FILL_D1_MISSING'
    assert research.select(rows, None)[calendar[0]] == [-0.6, -0.6]
    assert research.selection_status(rows, [4, 3, 2, 1]) == {'NO_FILL_D1_MISSING': 1, 'EXECUTED': 2}


def test_historical_export_never_selects_source_labels_or_reserved_rows(tmp_path):
    source, target = tmp_path / 'source', tmp_path / 'history'
    source.mkdir()
    with connect(source / 'dataset-v2.sqlite') as db:
        for day in ('2026-10-06', '2026-10-07'):
            db.execute('INSERT INTO trading_days VALUES (?)', (day,))
            db.execute('INSERT INTO candidates VALUES (?,?,?,?,?,?,?,?)',
                       (day, 'v', 2, day, '2330', 'PENDING', '{}', 'SECRET_LABEL'))
    market = market_connect(source / 'market-daily.sqlite')
    for day in ('2026-10-06', '2026-10-07'):
        insert_bar(market, '2330', day)
    market.commit()
    market.close()
    manifest = prepare(source, target)
    assert manifest['labels_read'] is False
    with sqlite3.connect(target / 'dataset-v2.sqlite') as db:
        assert db.execute('SELECT signal_date,label FROM candidates').fetchall() == [('2026-10-06', None)]
    with sqlite3.connect(target / 'market-daily.sqlite') as db:
        assert db.execute('SELECT day FROM bars').fetchall() == [('2026-10-06',)]
    with sqlite3.connect(source / 'dataset-v2.sqlite') as db:
        assert db.execute('SELECT label FROM candidates').fetchall() == [('SECRET_LABEL',), ('SECRET_LABEL',)]
    with pytest.raises(ValueError, match='outside_source'):
        prepare(source, source / 'child')


def test_cost_and_unresolved_thresholds_are_arithmetic_not_imputed_returns():
    assert cost_sensitivity([-0.27])['break_even_cost_pct'] == 0.33
    assert cost_sensitivity([-0.27])['scenarios']['0.45']['mean_net_pct'] == -0.12
    assert missing_outcome_threshold([-1, -2], 2)['unresolved_mean_net_to_break_even_pct'] == 1.5
    assert missing_outcome_threshold([-1], 0)['unresolved_mean_net_to_break_even_pct'] is None


def test_moving_blocks_preserve_fold_and_calendar_including_empty_days():
    calendar = [f'd{i:02d}' for i in range(20)]
    by_day = {day: [1.0] for day in calendar[:10]}
    # Full-fold blocks always sample exactly the original calendar: the empty
    # second fold cannot replace the first fold or create fictitious trades.
    actual = block_bootstrap(by_day, calendar, (('d00', 'd09'), ('d10', 'd19')), 10, samples=30)
    assert actual['p10'] == actual['p90'] == 1.0
    assert actual['calendar_sessions'] == 20 and actual['samples'] == 30
    assert actual == block_bootstrap(by_day, calendar, (('d00', 'd09'), ('d10', 'd19')), 10, samples=30)
    delta = block_bootstrap(by_day, calendar, (('d00', 'd09'),), 10, samples=30,
                           comparison={d: [0.25] for d in calendar[:10]})
    assert delta['p10'] == delta['p90'] == 0.75


def test_empty_bootstrap_is_reportable_without_nonfinite_json():
    assert research.bootstrap_delta({'d': []}, {'d': []})['p10'] is None
    assert research.bootstrap_mean({})['p10'] is None
    json.dumps(research.bootstrap_mean({}), allow_nan=False)
