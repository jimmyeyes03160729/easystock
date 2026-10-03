"""Point-in-time synthetic execution checks; fixtures never write production."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from paper_execution import execution, fee, tax
from position_manager import PositionManager, PaperWallet

AT=datetime(2026,10,2,10,tzinfo=timezone(timedelta(hours=8)))


def quote(at=AT, **changes):
    return dict(eligibility=True, quote_at=at.isoformat(), bid=100, ask=100.5,
                bid_shares=2000, ask_shares=3000, **changes)


def test_canonical_fee_and_tax_boundaries():
    assert fee(1000)==20
    assert fee(100000)==40
    assert fee(Decimal('1000.5'), Decimal('1'))==1001
    assert tax(100000)==150
    assert tax(101000)==152
    assert tax(100333)==150
    assert tax(100334)==151
    assert tax(Decimal('100333.33'))==150  # no intermediate cent rounding
    assert tax(100000,eligible=False)==300
    assert tax(100000,same_day=False)==300


@pytest.mark.parametrize('eligible,reason',[(False,'daytrade_ineligible'),(None,'daytrade_eligibility_unknown')])
def test_ineligible_or_unknown_never_fills(eligible,reason):
    evidence=quote(); evidence['eligibility']=eligible
    assert execution(evidence,'BUY',AT)['skip_reason']==reason


@pytest.mark.parametrize('delta',[-16,1,-86400])
def test_stale_future_or_previous_day_quote(delta):
    assert execution(quote(AT+timedelta(seconds=delta)),'BUY',AT)['skip_reason']=='quote_stale'


@pytest.mark.parametrize('side,field', [('BUY','ask'),('SELL','bid')])
def test_limit_lock_without_counterparty(side,field):
    evidence=quote(); evidence[field]=0
    assert execution(evidence,side,AT,1000)['skip_reason']=='no_counterparty'


def test_execution_uses_directional_book_and_lot_depth():
    assert execution(quote(),'BUY',AT)['price']==100.5
    assert execution(quote(),'BUY',AT)['max_shares']==3000
    assert execution(quote(),'SELL',AT,1000)['price']==100
    assert execution(quote(),'SELL',AT,3000)['status']=='pending'
    assert execution(quote(),'SELL',AT,1)['status']=='pending'


def test_cutoff_and_force_exit_remain_strategy_policy():
    before=AT.replace(hour=12,minute=29,second=59)
    cutoff=AT.replace(hour=12,minute=30)
    assert execution(quote(before),'BUY',before)['status']=='executable'
    assert execution(quote(cutoff),'BUY',cutoff)['skip_reason']=='entry_cutoff'
    manager=PositionManager()
    assert not manager.can_open_now(cutoff)
    force=AT.replace(hour=12,minute=55)
    assert manager.is_force_exit_time(force)
    assert execution(quote(force),'SELL',force,1000)['status']=='executable'
    assert execution({},'SELL',force,1000)['status']=='pending'


def test_eligibility_skip_preserves_research_and_single_attempt():
    attempt=Mock(return_value={'status':'skipped','skip_reason':'daytrade_ineligible'})
    manager=PositionManager(research_mode=True,before_open=attempt)
    first=manager.open_position('3189','fixture',1015,AT,61,[])
    assert first['position']['research_execution']=='TRACKED'
    assert first['position']['paper_execution']=='SKIPPED'
    for _ in range(20):
        assert manager.open_position('3189','fixture',1015,AT,61,[]) is None
    attempt.assert_called_once()


def test_paper_wallet_never_falls_back_to_signal_price(monkeypatch):
    monkeypatch.setattr('position_manager.read_paper_trade_settings',lambda: {})
    wallet=PaperWallet()
    buy=Mock()
    monkeypatch.setattr('paper_account.buy',buy)
    assert wallet.open_fill('3189','fixture',1015)['status']=='skipped'
    buy.assert_not_called()


def test_unfilled_sell_remains_pending(monkeypatch):
    monkeypatch.setattr('position_manager.read_paper_trade_settings',lambda: {})
    monkeypatch.setattr('paper_account.settlement_receipt',lambda _: None)
    monkeypatch.setattr('paper_account.open_positions',lambda: [dict(symbol='3189',shares=1000)])
    sell=Mock(); monkeypatch.setattr('paper_account.sell',sell)
    wallet=PaperWallet()
    assert wallet.close_and_settle('3189',999,trade_id='fixture')['status']=='pending'
    sell.assert_not_called()


def test_root_vm_compliance_sources_match():
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    for name in ('paper_execution.py','paper_account.py','paper_ledger.py','position_manager.py','intraday_live.py'):
        assert (root/name).read_bytes()==(root/'vm_runtime'/name).read_bytes()


def test_sdk_adapter_reads_directional_evidence_without_order_calls():
    # Execute the actual method without importing network-initializing runtime.
    import ast
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    tree=ast.parse((root/'intraday_live.py').read_text(encoding='utf-8'))
    engine=next(node for node in tree.body if isinstance(node,ast.ClassDef) and node.name=='IntradayLiveEngine')
    method=next(node for node in engine.body if isinstance(node,ast.FunctionDef) and node.name=='paper_execution_evidence')
    namespace={'as_datetime':lambda value: value}
    exec(compile(ast.Module(body=[method],type_ignores=[]),'<runtime-method>','exec'),namespace)
    contract=SimpleNamespace(day_trade=SimpleNamespace(value='Yes'),category='24')
    snapshot=SimpleNamespace(ts=AT,buy_price=100,sell_price=100.5,buy_volume=2,sell_volume=3)
    api=SimpleNamespace(snapshots=Mock(return_value=[snapshot]))
    runtime=SimpleNamespace(contracts={'3189':contract},api=api)
    evidence=namespace['paper_execution_evidence'](runtime,'3189')
    assert execution(evidence,'BUY',AT)['max_shares']==3000
    assert execution(evidence,'SELL',AT,2000)['price']==100
    contract.day_trade=None
    assert namespace['paper_execution_evidence'](runtime,'3189')['eligibility'] is None
    api.snapshots.side_effect=RuntimeError('offline')
    assert namespace['paper_execution_evidence'](runtime,'3189')=={}
