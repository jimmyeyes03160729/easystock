"""Safety and causal fixtures, not evidence of trading profitability."""
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
import ast
from pathlib import Path
import pytest

from daytrade_learning.a_recovery_v2 import (
    ARMS, Policy, Portfolio, completed, deployment_gate, execution_time,
    position_size, recovery_setup, screening_cost, shifted, technical_reason,
)
from deploy.backtest_a_recovery_v2 import group_bars, simulate, validate_exploration_archive
import daytrade_learning.a_recovery_v2 as research

TPE = timezone(timedelta(hours=8))
DAY = '2026-10-01'
NOW = datetime(2026, 10, 1, 9, 20, tzinfo=TPE)


def pattern():
    rows = [
        dict(open=98, high=99, low=97, close=98, volume=100),
        dict(open=98, high=99.6, low=98, close=99.5, volume=100),
        dict(open=98.7, high=99, low=98.5, close=98.9, volume=50),
        dict(open=98.9, high=99.25, low=98.7, close=99.2, volume=140),
    ]
    return [dict(r, date=(NOW.replace(hour=9, minute=0) + timedelta(minutes=i * 5)).isoformat())
            for i, r in enumerate(rows)]


def signal(now=None, symbol='TEST'):
    now = now or NOW.replace(minute=40)
    return dict(symbol=symbol, at=(now - timedelta(minutes=1)).isoformat(),
                rank=0, score=75, recovery=True, recovery_reason='confirmed',
                execution_at=now, previous=100, confirming_high=102, vwap=101)


def test_independent_recovery_requires_ordered_reclaim_pullback_confirmation():
    rows = pattern()
    assert recovery_setup(rows, NOW, 100, 99.2)[0]
    assert not recovery_setup(rows, NOW, 97, 99.2)[0]
    assert not recovery_setup(rows, NOW, None, 99.2)[0]
    assert not recovery_setup(rows[:3], NOW, 100, 99.2)[0]


@pytest.mark.parametrize('kind', ['future', 'unfinished', 'weak_confirm', 'chase', 'large_pullback'])
def test_invalid_recovery_never_becomes_an_entry(kind):
    rows = pattern(); price = 99.2; now = NOW
    if kind == 'future':
        rows[-1]['date'] = (NOW + timedelta(minutes=5)).isoformat()
    elif kind == 'unfinished':
        now = NOW - timedelta(seconds=1)
    elif kind == 'weak_confirm':
        rows[-1]['volume'] = 1
    elif kind == 'chase':
        price = 101
    else:
        rows[-2]['low'] = 97
    assert not recovery_setup(rows, now, 100, price)[0]


def test_future_and_previous_day_bars_cannot_change_completed_features():
    rows = pattern()
    future = dict(rows[-1], date=(NOW + timedelta(minutes=5)).isoformat(), close=1000)
    old = dict(rows[0], date=(NOW - timedelta(days=1)).isoformat(), close=1)
    assert completed([old] + rows + [future], NOW) == rows
    assert recovery_setup([old] + rows + [future], NOW, 100, 99.2) == recovery_setup(rows, NOW, 100, 99.2)
    with pytest.raises(ValueError):
        completed(rows + [rows[-1]], NOW)
    with pytest.raises(ValueError):
        execution_time(datetime(2026, 10, 1))


def test_decision_buffer_crosses_minute_boundary_before_execution():
    at = NOW.replace(minute=30, second=59)
    assert execution_time(at) == NOW.replace(minute=32, second=0)
    assert execution_time(at.replace(second=3)) == NOW.replace(minute=31, second=0)


def test_policy_is_frozen_and_rejects_invalid_parameters():
    policy = Policy()
    with pytest.raises(FrozenInstanceError):
        policy.allocation_fraction = 1
    for kwargs in (dict(allocation_fraction=2), dict(daily_buy_limit=float('nan')), dict(early_slots=6)):
        with pytest.raises(ValueError):
            Policy(**kwargs)
    assert policy.fingerprint() == Policy().fingerprint()


def test_cap_whole_lots_and_high_price_skip_are_explicit():
    at = NOW.replace(minute=40)
    assert position_size(12.25, 1000000, 0, at, 'baseline')[0] == 81000
    assert position_size(12.25, 1000000, 0, at, 'allocation_only')[0] == 24000
    assert position_size(582, 1000000, 0, at, 'allocation_only') == (0, 'lot_exceeds_allocation')
    assert position_size(100, 50000, 0, at, 'allocation_only')[0] == 0


def test_slots_release_by_time_and_never_open_after_cutoff():
    at = NOW.replace(minute=40)
    assert position_size(100, 1000000, 2, at, 'allocation_only')[1] == 'slot_reservation'
    assert position_size(100, 1000000, 2, at.replace(hour=10), 'allocation_only')[0] > 0
    assert position_size(100, 1000000, 4, at.replace(hour=10), 'allocation_only')[0] == 0
    assert position_size(100, 1000000, 4, at.replace(hour=11), 'allocation_only')[0] > 0
    assert position_size(100, 1000000, 0, at.replace(hour=12, minute=30), 'baseline')[0] == 0


def test_sell_does_not_replenish_allowance_or_allow_same_stock_reentry():
    book = Portfolio('allocation_only'); at = NOW.replace(minute=40)
    assert book.open(signal(at), 100, at) is None
    used = book.used
    book.close('TEST', 101, at + timedelta(minutes=5), 'test_exit')
    assert book.used == used
    assert book.open(signal(at), 100, at + timedelta(minutes=6)) == 'same_stock_reentry'
    trade = book.trades[0]
    assert trade['net_pnl'] == round(trade['gross_pnl'] - trade['costs'], 2)


@pytest.mark.parametrize('arm', ARMS)
def test_hard_stop_and_force_exit_survive_every_arm(arm):
    at = NOW.replace(minute=40); book = Portfolio(arm)
    book.open(signal(at), 100, at)
    book.segment('TEST', 100, 97, at + timedelta(seconds=15))
    assert book.trades[0]['reason'] == 'hard_stop'
    book = Portfolio(arm)
    book.open(signal(at), 100, at)
    book.tick('TEST', 101, at.replace(hour=12, minute=55))
    assert book.trades[0]['reason'] == 'force_exit'


def test_structural_trend_does_not_apply_uniform_breakeven():
    at = NOW.replace(minute=40)
    old, trend = Portfolio('allocation_only'), Portfolio('recovery_structural')
    for book in (old, trend):
        book.open(signal(at), 100, at)
        book.tick('TEST', 103, at + timedelta(minutes=1))
        book.tick('TEST', 100.5, at + timedelta(minutes=2))
    assert old.trades[0]['reason'] == 'breakeven'
    assert 'TEST' in trend.positions


def test_technical_exit_needs_completed_evidence_not_intraminute_low():
    rows = pattern()
    rows[-1].update(close=98.2, low=98.0, high=99.3)
    assert technical_reason(rows, NOW, False) == 'below_vwap'
    assert technical_reason(rows, NOW, True) is None
    rows[-2].update(close=98.1, low=98.0)
    assert technical_reason(rows, NOW, True) == 'two_completed_closes_below_vwap'
    assert technical_reason(rows, NOW - timedelta(seconds=1), True) is None


def test_marked_drawdown_not_just_closed_trade_pnl_is_reported():
    book = Portfolio('allocation_only'); at = NOW.replace(minute=40)
    book.open(signal(at), 100, at); book.mark({'TEST':100})
    book.mark({'TEST':98.5})
    assert book.max_drawdown > 1000
    book.mark({'TEST':102})
    assert book.max_drawdown > 1000 and book.peak > 0


def test_execution_ticks_and_costs_are_aligned_not_double_counted():
    assert shifted(50, -1, 1) == 49.95
    assert shifted(499.5, 1, 2) == 501
    assert screening_cost(100, 2) > screening_cost(100, 1) > 0
    with pytest.raises(ValueError):
        shifted(0, 1, 1)


def test_archive_experiment_cannot_pass_deployment_even_if_returns_positive():
    reports=[]
    for i in range(10):
        for arm in ARMS:
            for ticks in (1,2):
                for path in ('low-first','high-first'):
                    reports.append(dict(day=f'2026-09-{i+1:02}', split='holdout', arm=arm, ticks=ticks,
                        path=path, net_pnl=100, max_drawdown_twd=50, unresolved=[]))
    gate=deployment_gate(reports)
    assert not gate['deployment_allowed']
    assert 'missing_complete_forward_eligibility_depth_and_market_evidence' in gate['reasons']
    reports[-1]['unresolved']=['TEST']
    assert not deployment_gate(reports,complete_forward_evidence=True)['deployment_allowed']


def test_no_live_imports_or_production_wiring():
    core=Path('daytrade_learning/a_recovery_v2.py').read_text(encoding='utf-8')
    imports=[]
    for node in ast.walk(ast.parse(core)):
        if isinstance(node,ast.Import):imports += [n.name for n in node.names]
        if isinstance(node,ast.ImportFrom):imports.append(node.module)
    assert not any(s in {'shioaji','firebase_admin','sqlite3','paper_account','position_manager','intraday_live'} for s in imports)
    for source in ('intraday_live.py','vm_runtime/intraday_live.py','paper_account.py'):
        assert 'a_recovery_v2' not in Path(source).read_text(encoding='utf-8')


def synthetic_data(symbols, price=80):
    at = NOW.replace(minute=40)
    row = dict(open=price, high=price, low=price, close=price, volume=100)
    return {s: dict(minutes={at:row, at.replace(hour=12, minute=55):row}, b5=([], [])) for s in symbols}


def test_simulator_allocation_only_preserves_baseline_entry_ranking():
    at = NOW.replace(minute=40)
    signals = [dict(signal(at, 'FIRST'), rank=0, score=70),
               dict(signal(at, 'SECOND'), rank=1, score=99)]
    data = synthetic_data(['FIRST', 'SECOND'])
    for arm in ('baseline', 'allocation_only'):
        result = simulate(data, signals, DAY, arm, 1, 'low-first', research, Policy())
        assert result['trades'][0]['symbol'] == 'FIRST'
        assert not result['unresolved'] and result['buy_used'] <= 1000000
        assert all(t['entry_at'] == at.isoformat() for t in result['trades'])


def test_simulator_rechecks_lower_vwap_at_execution():
    at = NOW.replace(minute=40)
    request = dict(signal(at), price=80, vwap=80, confirming_high=81)
    result = simulate(synthetic_data(['TEST'], 79.9), [request], DAY,
                      'recovery_allocation', 1, 'low-first', research, Policy())
    assert result['closed_count'] == 0
    assert result['skips']['execution_moved_outside_recovery_limits'] == 1


def test_simulator_positive_recovery_fixture_executes_and_liquidates():
    at = NOW.replace(minute=40)
    request = dict(signal(at), price=80, vwap=80, confirming_high=81)
    result = simulate(synthetic_data(['TEST']), [request], DAY,
                      'recovery_structural', 1, 'high-first', research, Policy())
    assert result['closed_count'] == 1 and not result['unresolved']
    assert result['trades'][0]['reason'] == 'force_exit'
    assert result['trades'][0]['shares'] == 3000
    assert result['net_pnl'] < 0  # Flat prices still lose fees, tax and adverse ticks.


def test_missing_quote_never_drops_open_liability_from_mark():
    book = Portfolio('allocation_only'); at = NOW.replace(minute=40)
    book.open(signal(at), 100, at)
    book.mark({'TEST':100})
    previous = book.max_drawdown
    book.mark({})
    assert book.max_drawdown == previous and previous > 0


@pytest.mark.parametrize('price,remaining,count', [(0,1000,0), (float('nan'),1000,0),
                                                  (100,-1,0), (100,1000,-1)])
def test_invalid_sizing_inputs_fail_closed(price, remaining, count):
    with pytest.raises(ValueError):
        position_size(price, remaining, count, NOW, 'baseline')


def test_grouped_bars_require_complete_consecutive_minutes():
    rows = [dict(at=(NOW.replace(minute=0)+timedelta(minutes=i)).isoformat(),
                 open=80, high=81, low=79, close=80, volume=10) for i in range(5)]
    grouped, ends = group_bars(rows, 5)
    assert len(grouped) == 1 and ends == [NOW.replace(minute=5)]
    assert group_bars(rows[:-1], 5) == ([], [])


def test_archive_only_training_flag_is_not_misread_as_bad_price_data():
    audit = dict(ticks=5, training_eligible=False,
                 reason='archive only; historical reference prices, universe and replay still required')
    payload = dict(ticks={}, kbars={}, audit=dict(audit))
    auditor = lambda ticks,bars,day: audit
    assert validate_exploration_archive(payload, DAY, auditor) is False
    payload['audit']['ticks'] = 6
    with pytest.raises(ValueError, match='collection_audit_mismatch'):
        validate_exploration_archive(payload, DAY, auditor)
    payload['audit'].update(ticks=5, reason='corrupt data')
    with pytest.raises(ValueError, match='unknown_training_exclusion'):
        validate_exploration_archive(payload, DAY, auditor)
