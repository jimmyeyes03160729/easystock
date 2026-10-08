"""Cost-aware daytrade rules: tick sizes, breakeven exits, cost veto, spread estimate."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import itertools
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import paper_execution as pe
import strategy_engine
from position_manager import PositionManager
from daytrade_learning.research import profile_hash, simulate

TPE = timezone(timedelta(hours=8))
AT = datetime(2026, 10, 7, 10, 0, tzinfo=TPE)
COSTS = json.loads((ROOT / 'daytrade_learning/settings.json').read_text(encoding='utf-8'))


def test_tick_size_boundaries():
    assert [float(pe.tick_size(p)) for p in (9.99, 10, 49.95, 50, 99.9, 100, 499.5, 500, 999, 1000)] == \
        [.01, .05, .05, .1, .1, .5, .5, 1, 1, 5]


def test_roundtrip_cost_is_dominated_by_minimum_fee_and_tick_for_cheap_stocks():
    # 10 NTD: 20+20 fee, 15 tax on 10,000 plus a 0.05 tick = 1.05%
    assert abs(pe.roundtrip_cost_pct(10) - 1.05) < 1e-9
    assert pe.roundtrip_cost_pct(300) < .45 < pe.roundtrip_cost_pct(100)


def test_breakeven_exit_price_is_lowest_covering_tick():
    for entry in (9.87, 10, 23.45, 50, 99.9, 100, 137.5, 300, 512, 1015):
        price = Decimal(str(pe.breakeven_exit_price(entry)))
        paid = Decimal(str(entry)) * 1000 + pe.fee(Decimal(str(entry)) * 1000)
        net = lambda p: p * 1000 - pe.fee(p * 1000) - pe.tax(p * 1000)
        assert net(price) >= paid
        assert net(price - pe.tick_size(price - Decimal('0.001'))) < paid
        assert price % pe.tick_size(price) == 0


def test_cost_aware_levels_cover_costs_plus_one_tick():
    # 300: covering price 301.0, +1 tick for the bid -> 301.5, activation one tick above.
    assert pe.cost_aware_breakeven(300, .0035, .006) == (301.5, 302.0)
    # Configured levels remain the minimum.
    floor, activate = pe.cost_aware_breakeven(1015, .02, .03)
    assert (floor, activate) == (round(1015 * 1.02, 2), round(1015 * 1.03, 2))


CLOCK = itertools.count(1)


def ticks(manager, prices):
    for price in prices:
        event = manager.on_tick('TEST', price, AT + timedelta(seconds=next(CLOCK)))
        if event:
            return event
    return None


def open_manager(**kw):
    manager = PositionManager(**kw)
    manager.open_position('TEST', 'Test', 300, AT, 90, ['r'])
    return manager


def test_default_breakeven_is_unchanged():
    manager = open_manager()
    assert ticks(manager, [302.0, 301.5]) is None          # above legacy 0.35% floor
    assert ticks(manager, [301.0])['trade']['exit_reason'] == '動態保本出場'


def test_cost_aware_breakeven_exits_at_cost_floor():
    manager = open_manager(cost_aware_breakeven=True)
    assert ticks(manager, [301.9, 301.5]) is None          # never reached activation 302.0
    event = ticks(manager, [302.0, 301.5])
    assert event['trade']['exit_reason'] == '動態保本出場'
    assert event['trade']['exit_price'] == 301.5


def test_cost_aware_breakeven_uses_paper_fill_price():
    manager = open_manager(cost_aware_breakeven=True)
    position = manager.get_position('TEST')
    assert manager.breakeven_prices(position) == (301.5, 302.0)
    position['paper_entry_price'] = 300.5                   # bought at the ask
    assert manager.breakeven_prices(position) == pe.cost_aware_breakeven(300.5, .0035, .006)


class Store:
    def __init__(self):
        self.saved = []

    def save(self, trade, armed=None):
        self.saved.append(dict(trade))


def test_research_close_records_spread_adjusted_return():
    manager = PositionManager(research_mode=True, research_store=Store())
    manager.open_position('TEST', 'Test', 100, AT, 90, ['r'])
    trade = manager.close_position('TEST', 101, AT + timedelta(minutes=5), 'test')['trade']
    assert abs(trade['research_spread_cost_pct'] - .5) < 1e-9   # one 0.5 tick at 100
    assert abs(trade['research_net_after_spread_pct'] - (trade['research_net_pnl_pct'] - .5)) < 1e-9


def bars(close, n):
    return [{'open': close, 'high': close * 1.001, 'low': close * .999, 'close': close, 'volume': 1000}
            for _ in range(n)]


def test_cost_veto_is_opt_in():
    rows5, rows15 = bars(10, 8), bars(10, 3)
    assert '交易成本過高' not in strategy_engine.evaluate_daytrade(rows5, rows15)['vetoes']
    with patch.object(strategy_engine, 'MAX_ROUNDTRIP_COST_PCT', .6):
        assert '交易成本過高' in strategy_engine.evaluate_daytrade(rows5, rows15)['vetoes']
        assert '交易成本過高' not in strategy_engine.evaluate_daytrade(bars(300, 8), bars(300, 3))['vetoes']


POLICY = {'stop_loss_pct': .008, 'take_profit_pct': .012}


def test_disabled_rules_keep_profile_hash():
    disabled = dict(POLICY, cost_aware_breakeven=False, max_roundtrip_cost_pct=0)
    assert profile_hash(COSTS, disabled) == profile_hash(COSTS, POLICY)
    assert profile_hash(COSTS, dict(POLICY, cost_aware_breakeven=True)) != profile_hash(COSTS, POLICY)
    assert profile_hash(COSTS, dict(POLICY, max_roundtrip_cost_pct=.6)) != profile_hash(COSTS, POLICY)


def sim_fixture(price, policy):
    day = '2026-09-10'
    sample = {'symbol': 'TEST', 'observed_at': day + 'T09:30:00+08:00', 'quote_at': day + 'T09:30:00+08:00',
              'price': price, 'return_5m_pct': .2, 'radar_selected': True, 'policy': policy,
              'metrics': {'surge_60s': 2, 'buy_ratio_60s': .6, 'classified_ratio_60s': .8,
                          'amount_60s': 5000000, 'history_seconds': 350}}
    flat = lambda at, high, low: {'at': at, 'open': price, 'high': high, 'low': low, 'close': price, 'volume': 100}
    pack = {'date': day, 'previous_close': {'price': price, 'date': '2026-09-09'},
            'limit_up': price * 1.1, 'limit_down': price * .9,
            'bars': [flat(day + 'T09:31:00+08:00', price * 1.009, price),
                     flat(day + 'T09:32:00+08:00', price * 1.009, price * 1.0047)]}
    return sample, pack


def test_simulation_follows_opt_in_rules():
    # Entry 300.3: legacy floor 301.35 is not touched by a 301.41 low, so the
    # trailing stop exits; the cost-aware floor 301.5 is checked first and is.
    s, p = sim_fixture(300, POLICY)
    assert simulate(s, p, COSTS)[0]['reason'] == '移動停利'
    s, p = sim_fixture(300, dict(POLICY, cost_aware_breakeven=True))
    row, why = simulate(s, p, COSTS)
    assert why is None and row['reason'] == '動態保本出場' and row['exit_price'] < 301.5
    s, p = sim_fixture(10, dict(POLICY, max_roundtrip_cost_pct=.6))
    assert simulate(s, p, COSTS)[1] == 'cost_filter'


def test_flat_limit_up_bar_is_not_a_short_low_break():
    # A locked limit-up bar has open == high == low == close; touching the recent low is not breaking it.
    locked = [{'open': 110, 'high': 110, 'low': 110, 'close': 110, 'volume': 1000} for _ in range(8)]
    assert '5分K破短低' not in strategy_engine.evaluate_daytrade(locked, bars(110, 3))['vetoes']
    broken = locked[:-1] + [{'open': 110, 'high': 110, 'low': 109.5, 'close': 109.5, 'volume': 1000}]
    assert '5分K破短低' in strategy_engine.evaluate_daytrade(broken, bars(110, 3))['vetoes']
