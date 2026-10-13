"""Synthetic SDK-v2/legacy metadata and the actual radar -> B1 path. No login."""
import ast
from datetime import datetime, timedelta, time as dtime
from enum import Enum
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import threading

import pytest
from market_data.shioaji import StockMetadataCache
from runway_v2.lanes import LaneSuite, TPE

NOW = datetime(2026, 10, 12, 9, 3, tzinfo=TPE)
BASE = SimpleNamespace(code='TEST')  # SDK BaseContract has no optional metadata.


class DayTrade(Enum):
    Yes = 'Yes'
    OnlyBuy = 'OnlyBuy'
    No = 'No'


def info(code='TEST', **changes):
    return {'code': code, 'reference': 119, 'category': '01',
            'day_trade': DayTrade.Yes, **changes}


class InfoRecord:
    """VM StockInfo exposes metadata through dict(), not BaseContract attrs."""
    def __init__(self, data):
        self.data = data
        self.base = BASE

    def dict(self):
        return dict(self.data)


def api_with(record):
    api = SimpleNamespace(contracts=SimpleNamespace(info=Mock(return_value=record)))
    api.place_order = Mock(side_effect=AssertionError('broker orders forbidden'))
    return api


def test_v2_base_is_resolved_to_info_dict_and_not_replaced():
    api = api_with(InfoRecord(info()))
    result = StockMetadataCache().read(api, BASE, 'TEST', NOW)
    assert result == {'reference': 119, 'category': '01', 'day_trade': 'Yes',
                      'metadata_source': 'sdk_info', 'metadata_status': 'ready'}
    api.contracts.info.assert_called_once_with(BASE)
    assert vars(BASE) == {'code': 'TEST'}
    api.place_order.assert_not_called()


def test_legacy_stock_attributes_are_supported_without_v2_namespace():
    result = StockMetadataCache().read(SimpleNamespace(), SimpleNamespace(**info()), 'TEST', NOW)
    assert result['reference'] == 119
    assert result['category'] == '01'
    assert result['day_trade'] == 'Yes'
    assert result['metadata_source'] == 'legacy_contract'


def test_info_record_can_identify_its_stock_through_base():
    fields = info()
    del fields['code']
    result = StockMetadataCache().read(api_with(InfoRecord(fields)), BASE, 'TEST', NOW)
    assert result['reference'] == 119 and result['metadata_status'] == 'ready'


@pytest.mark.parametrize('flag,expected', [(DayTrade.Yes, 'Yes'), (DayTrade.OnlyBuy, 'OnlyBuy'),
    (DayTrade.No, 'No'), ('Yes', 'Yes'), ('DayTrade.Yes', 'Yes'), (None, None), (True, None),
    ('UNKNOWN', None), ('Unknown.Yes', None), ('No.Yes', None), ('DayTrade.No.Yes', None)])
def test_short_eligibility_is_explicit_not_truthiness(flag, expected):
    result = StockMetadataCache().read(api_with(info(day_trade=flag)), BASE, 'TEST', NOW)
    assert result['day_trade'] == expected


@pytest.mark.parametrize('reference', [None, 0, -1, True, float('nan'), float('inf'), 'bad'])
def test_missing_or_invalid_reference_is_not_filled_with_a_price(reference):
    result = StockMetadataCache().read(api_with(info(reference=reference)), BASE, 'TEST', NOW)
    assert result['reference'] is None
    assert result['metadata_status'] != 'ready'


def test_info_error_mismatch_or_malformed_payload_remains_unknown():
    for record in [None, info(code='OTHER'), InfoRecord({'reference': 119, 'category': '01', 'day_trade': 'Yes', 'code': 'OTHER'})]:
        result = StockMetadataCache().read(api_with(record), BASE, 'TEST', NOW)
        assert result['reference'] is None
        assert result['category'] == ''
        assert result['day_trade'] is None
    api = api_with(info())
    api.contracts.info.side_effect = RuntimeError('secret-do-not-log')
    # Even a populated legacy-like object must not hide a v2 lookup failure.
    result = StockMetadataCache().read(api, SimpleNamespace(**info()), 'TEST', NOW)
    assert result['metadata_status'] == 'unavailable'
    assert 'secret-do-not-log' not in str(result)


def test_cache_has_bounded_retry_and_day_rollover_without_stale_fallback():
    api, cache = api_with(info()), StockMetadataCache()
    result = cache.read(api, BASE, 'TEST', NOW)
    result['reference'] = 1
    assert cache.read(api, BASE, 'TEST', NOW + timedelta(seconds=59))['reference'] == 119
    assert api.contracts.info.call_count == 1
    api.contracts.info.side_effect = RuntimeError('offline')
    assert cache.read(api, BASE, 'TEST', NOW + timedelta(seconds=60))['reference'] is None
    cache.read(api, BASE, 'TEST', NOW + timedelta(seconds=74))
    assert api.contracts.info.call_count == 2
    cache.read(api, BASE, 'TEST', NOW + timedelta(seconds=75))
    assert api.contracts.info.call_count == 3
    assert cache.read(api, BASE, 'TEST', NOW + timedelta(days=1))['reference'] is None
    assert api.contracts.info.call_count == 4


def test_cached_metadata_cannot_be_used_for_missing_or_wrong_contract():
    api, cache = api_with(info()), StockMetadataCache()
    cache.read(api, BASE, 'TEST', NOW)
    for contract in [None, SimpleNamespace(code='OTHER')]:
        assert cache.read(api, contract, 'TEST', NOW)['reference'] is None


def test_cache_size_is_bounded():
    api = api_with(None)
    cache = StockMetadataCache()
    for i in range(600):
        cache.read(api, SimpleNamespace(code=str(i)), str(i), NOW)
    assert len(cache.cache) == 512


def engine_fixture(now=NOW):
    # Execute exact runtime methods without importing SDK/Firebase boot globals.
    tree = ast.parse(Path('intraday_live.py').read_text(encoding='utf8'))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'IntradayLiveEngine')
    methods = [n for n in cls.body if isinstance(n, ast.FunctionDef)
               and n.name in ('_b_lane_row', '_select_b_books', 'refresh_volume_radar')]
    scope = {'dtime': dtime, 'now_tpe': lambda: now, 'ENTRY_CUTOFF': dtime(12, 30),
             'RADAR_REFRESH_SECONDS': 3, 'time': SimpleNamespace(monotonic=lambda: 100),
             'num': lambda x: x, 'recommendation_limit': lambda: 3,
             'compute_volume_surge_metrics': lambda ticks, *_a, **_k: {'price': ticks[-1][3]},
             'qualifies_volume_surge': lambda _: False, 'MAX_ROUNDTRIP_COST_PCT': .6,
             'read_live_settings': lambda: {}}
    module = ast.Module(body=[ast.ClassDef(name='Engine', bases=[], keywords=[], body=methods, decorator_list=[])], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), '<runtime-radar-methods>', 'exec'), scope)
    engine = scope['Engine']()
    engine.quote_subscriptions = SimpleNamespace(select_books=Mock())
    engine._b_stock_metadata = StockMetadataCache()
    engine._b_metadata_log_at = engine._last_radar_refresh = 0
    engine._lock = threading.RLock()
    engine.scanner_top_symbols = set()
    engine._write_radar_top30 = Mock()
    engine.evaluate_instant_entry_candidates = Mock()
    engine.learning = SimpleNamespace(sample=Mock())
    engine.manager = SimpleNamespace(**{k: 0 for k in ('stop_loss_pct', 'take_profit_pct', 'exit_mode',
        'trailing_activate_pct', 'trailing_pullback_pct', 'breakeven_activate_pct',
        'breakeven_floor_pct', 'technical_exit_enabled', 'cost_aware_breakeven')})
    return engine


def test_actual_radar_passes_v2_metadata_to_b1_without_lane_a_cache(tmp_path):
    engine = engine_fixture()
    suite = LaneSuite(tmp_path / 'synthetic.sqlite', sender=lambda *_: None, offline=True)
    try:
        suite.advance(NOW)
        engine.runway_v2 = suite
        codes = ['TEST', 'P1', 'P2']
        engine.contracts = {s: SimpleNamespace(code=s) for s in codes}
        engine.api = api_with(None)
        engine.api.contracts.info.side_effect = lambda base: InfoRecord(info(base.code, reference=119 if base.code == 'TEST' else 100))
        engine.candidates = {s: {'name': '合成股票', 'industry': 'should-not-be-used'} for s in codes}
        engine.radar_universe_symbols = set(codes)
        engine.radar_ticks = {s: [(NOW.timestamp(), 1, 1, 121.5 if s == 'TEST' else 102, 1)] for s in codes}
        engine.radar_metrics = {}
        engine.bars = SimpleNamespace(rows5=lambda _: [])
        engine.market_risk = {'valid': True, 'gate_action': 'PASS'}
        for sec, price in [(50,120),(40,122),(30,121.5),(20,122),(9,120.5),(7,121),(5,121),(3,121.5),(1,121.5),(0,121.5)]:
            suite.on_tick('TEST', price, NOW-timedelta(seconds=sec), 1, 10)
        for sec in [10,6,0]:
            suite.on_bidask('TEST', {'datetime': NOW-timedelta(seconds=sec),
                'bid_price': [121-i*.5 for i in range(5)], 'ask_price': [121.5+i*.5 for i in range(5)],
                'bid_volume': [20]*5, 'ask_volume': [5]*5})
        engine.refresh_volume_radar(force=True)
        assert suite.rows['TEST']['previous_close'] == 119
        assert suite.rows['TEST']['sector'] == '01'
        assert suite.rows['TEST']['daytrade_short_allowed'] is True
        assert suite.rows['TEST']['metadata_source'] == 'sdk_info'
        suite.advance(NOW)
        assert suite.state['B1']['entries'] == 1  # Synthetic only; unchanged rule.
        assert suite.state['B1']['positions']['TEST']['shares'] == 1000
        engine.api.place_order.assert_not_called()
    finally:
        suite.worker.shutdown(wait=True)


def test_row_does_not_fallback_to_scanner_close_sector_or_short_flag():
    engine = engine_fixture()
    engine.contracts = {'TEST': BASE}
    engine.api = api_with(None)
    row = engine._b_lane_row('TEST', {'industry': '01', 'previous_close': 100,
        'sector': '01', 'daytrade_short_allowed': True}, {'price': 121.5}, NOW)
    assert row['previous_close'] is None
    assert row['sector'] == ''
    assert row['daytrade_short_allowed'] is False


@pytest.mark.parametrize('flag,allowed', [('Yes', True), ('OnlyBuy', False), ('No', False), (None, False)])
def test_row_short_permission_requires_exact_yes(flag, allowed):
    engine = engine_fixture()
    engine.contracts = {'TEST': BASE}
    engine.api = api_with(info(day_trade=flag))
    row = engine._b_lane_row('TEST', {}, {}, NOW)
    assert row['daytrade_short_allowed'] is allowed


def test_runtime_mirror_matches_and_registered_b_strategy_is_not_changed():
    assert Path('intraday_live.py').read_bytes() == Path('vm_runtime/intraday_live.py').read_bytes()
    source = Path('intraday_live.py').read_text(encoding='utf8')
    assert "prev_map = {str(r[\"symbol\"]): r.get(\"previous_close\") for r in lane_rows}" in source


def test_book_pool_omits_unaffordable_candidates_but_keeps_holdings_pinned():
    engine=engine_fixture()
    engine.runway_v2=SimpleNamespace(enabled=True,lock=threading.RLock(),state={'B1':{'positions':{'HELD':{}}}})
    engine._select_b_books([
        {'symbol':'EXPENSIVE','price':500,'previous_close':490},
        {'symbol':'CHEAP','price':199.5,'previous_close':198},
        {'symbol':'HELD','price':500,'previous_close':490}],NOW)
    engine.quote_subscriptions.select_books.assert_called_once_with(['CHEAP'],{'HELD'})


def test_book_pool_routes_to_dual_manager_when_explicitly_enabled():
    engine=engine_fixture()
    engine.runway_v2=SimpleNamespace(enabled=True,lock=threading.RLock(),state={'B1':{'positions':{}}})
    engine.dual_books=SimpleNamespace(select=Mock())
    engine._select_b_books([{'symbol':'CHEAP','price':100,'previous_close':99}],NOW)
    engine.dual_books.select.assert_called_once_with(['CHEAP'],set(),NOW)
    engine.quote_subscriptions.select_books.assert_not_called()
