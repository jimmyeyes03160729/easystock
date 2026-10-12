"""Exact A evidence path + synthetic SDK metadata/quotes; no production writes."""
import ast
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from market_data.shioaji import StockMetadataCache
from paper_execution import execution
from runway_v2.lanes import TPE

NOW = datetime(2026, 10, 12, 10, tzinfo=TPE)


class Info:
    def __init__(self, fields):
        self.fields = fields

    def dict(self):
        return dict(self.fields)


def fixture(fields=None, legacy=False):
    tree = ast.parse(Path('intraday_live.py').read_text(encoding='utf8'))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'IntradayLiveEngine')
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'paper_execution_evidence')
    scope = {'StockMetadataCache': StockMetadataCache, 'now_tpe': lambda: NOW, 'as_datetime': lambda x: x}
    exec(compile(ast.Module(body=[method], type_ignores=[]), '<actual-a-paper-method>', 'exec'), scope)
    base = SimpleNamespace(code='TEST')
    quote = SimpleNamespace(ts=NOW, buy_price=100, sell_price=100.5, buy_volume=2, sell_volume=3)
    fields = {'code':'TEST','category':'24','day_trade':'Yes', **(fields or {})}
    api = SimpleNamespace(contracts=SimpleNamespace(info=Mock(return_value=Info(fields))),
        snapshots=Mock(return_value=[quote]), place_order=Mock(side_effect=AssertionError('no orders')))
    if legacy:
        del api.contracts
        base = SimpleNamespace(**fields)
    engine = SimpleNamespace(contracts={'TEST':base}, api=api)
    read = lambda: scope['paper_execution_evidence'](engine, 'TEST')
    return engine, read, quote


@pytest.mark.parametrize('flag', ['Yes','OnlyBuy'])
def test_v2_metadata_restores_ordinary_stock_long_execution(flag):
    engine, read, _ = fixture({'day_trade':flag})
    evidence = read()
    assert evidence['eligibility'] is True
    assert evidence['eligibility_detail'] == f'day_trade={flag} category=24'
    decision = execution(evidence, 'BUY', NOW)
    assert decision['status'] == 'executable'
    assert decision['price'] == 100.5 and decision['max_shares'] == 3000
    assert execution(evidence,'SELL',NOW,2000)['price'] == 100
    engine.api.contracts.info.assert_called_once_with(engine.contracts['TEST'])
    engine.api.snapshots.assert_called_once_with([engine.contracts['TEST']], timeout=3000)
    engine.api.place_order.assert_not_called()


@pytest.mark.parametrize('category', ['',None,'00','ETF','ETN'])
def test_missing_sector_etf_etn_do_not_become_ordinary_stock_fills(category):
    _, read, _ = fixture({'category':category})
    evidence = read()
    assert evidence['eligibility'] is None
    assert execution(evidence,'BUY',NOW)['skip_reason'] == 'daytrade_eligibility_unknown'


@pytest.mark.parametrize('flag,reason', [('No','daytrade_ineligible'),(None,'daytrade_eligibility_unknown'),
    (True,'daytrade_eligibility_unknown'),('Unknown.Yes','daytrade_eligibility_unknown')])
def test_no_unknown_or_malformed_flags_cannot_fill(flag,reason):
    _, read, _ = fixture({'day_trade':flag})
    assert execution(read(),'BUY',NOW)['skip_reason'] == reason


def test_metadata_rechecked_on_every_attempt_and_failure_never_reuses_permission():
    engine, read, _ = fixture()
    assert read()['eligibility'] is True
    engine.api.contracts.info.return_value = Info({'code':'TEST','category':'24','day_trade':'No'})
    assert read()['eligibility'] is False
    engine.api.contracts.info.side_effect = RuntimeError('secret-not-in-evidence')
    evidence = read()
    assert evidence['eligibility'] is None
    assert 'secret-not-in-evidence' not in str(evidence)
    assert engine.api.contracts.info.call_count == 3


def test_wrong_stock_metadata_and_absent_contract_remain_unknown():
    engine, read, _ = fixture({'code':'OTHER'})
    assert read()['eligibility'] is None
    engine.contracts.clear()
    assert read() == {'eligibility':None,'eligibility_detail':'contract_missing'}


def test_snapshot_failure_is_separate_from_valid_metadata():
    engine, read, _ = fixture()
    engine.api.snapshots.side_effect = RuntimeError('offline')
    evidence = read()
    assert evidence['eligibility'] is True
    assert evidence['quote_error'] == 'snapshot_failed:RuntimeError'
    assert execution(evidence,'BUY',NOW)['skip_reason'] == 'quote_unavailable'
    assert execution(evidence,'SELL',NOW,2000)['status'] == 'pending'


def test_valid_permission_still_cannot_fill_stale_or_thin_quote():
    _, read, quote = fixture()
    quote.ts = NOW-timedelta(seconds=16)
    assert execution(read(),'BUY',NOW)['skip_reason'] == 'quote_stale'
    quote.ts = NOW
    quote.sell_volume = .5
    assert execution(read(),'BUY',NOW)['skip_reason'] == 'no_counterparty'


def test_legacy_stock_and_reference_absence_do_not_change_a_close_source():
    _, read, _ = fixture({'day_trade':'OnlyBuy'}, legacy=True)
    # A eligibility needs category/permission, not B's contract reference.
    assert execution(read(),'BUY',NOW)['status'] == 'executable'
    tree = ast.parse(Path('intraday_live.py').read_text(encoding='utf8'))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'IntradayLiveEngine')
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'fresh_entry_quote')
    code = ast.unparse(method)
    assert 'self.api.kbars' in code and 'rows[-1].close' in code
    assert 'metadata' not in code and "'reference'" not in code


def test_a_execution_cutoff_and_b_short_permission_remain_distinct():
    engine, read, _ = fixture({'day_trade':'OnlyBuy'})
    evidence = read()
    assert execution(evidence,'BUY',NOW.replace(hour=9,minute=29))['skip_reason'] == 'entry_cutoff'
    assert execution(evidence,'BUY',NOW.replace(hour=12,minute=30))['skip_reason'] == 'entry_cutoff'
    metadata = StockMetadataCache().read(engine.api,engine.contracts['TEST'],'TEST',NOW)
    assert metadata['day_trade'] == 'OnlyBuy' and metadata['day_trade'] != 'Yes'


def test_a_runtime_mirror_stays_byte_identical():
    assert Path('intraday_live.py').read_bytes() == Path('vm_runtime/intraday_live.py').read_bytes()
