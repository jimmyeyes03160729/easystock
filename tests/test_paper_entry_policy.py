from datetime import datetime,timedelta,timezone
from unittest.mock import Mock
import pytest
from paper_entry_policy import PaperEntryPolicy
from position_manager import PositionManager,PaperWallet
AT=datetime(2026,10,2,10,tzinfo=timezone(timedelta(hours=8)))
def evidence(value=3000,**changes):
    v=dict(source='shioaji_common_stock_tick_total_volume',unit='lot',value=value,quote_at=AT.isoformat());v.update(changes)
    return {'cumulative_volume':v}
@pytest.mark.parametrize('value,reason',[(2999,'low_volume'),(3000,None),(50000,None),(float('nan'),'volume_unverified'),(None,'volume_unverified'),(True,'volume_unverified')])
def test_explicit_lots_without_magnitude_conversion(value,reason):
    result=PaperEntryPolicy().check('2303','fixture',100,evidence(value),AT)
    assert (result or {}).get('skip_reason')==reason
@pytest.mark.parametrize('changes',[{'unit':'share'},{'source':'yesterday_volume'},{'quote_at':(AT-timedelta(seconds=4)).isoformat()},{'quote_at':(AT+timedelta(seconds=1)).isoformat()}])
def test_bad_source_unit_and_time_never_fill(changes):
    assert PaperEntryPolicy().check('2303','fixture',100,evidence(**changes),AT)['skip_reason']=='volume_unverified'
def test_price_and_etf_only_block_paper_execution(monkeypatch):
    import position_manager as P
    class Clock(datetime):
        @classmethod
        def now(cls,*_):return AT
    monkeypatch.setattr(P,'datetime',Clock);monkeypatch.setattr(P,'read_paper_trade_settings',lambda:{})
    wallet=PaperWallet();wallet.entry_policy=PaperEntryPolicy();wallet.allocation_slots=5
    wallet.execution_evidence=lambda _:dict(eligibility=True,quote_at=AT.isoformat(),bid=1000,ask=1001,bid_shares=2000,ask_shares=2000,**evidence())
    buy=Mock();monkeypatch.setattr('paper_account.buy',buy)
    manager=PositionManager(research_mode=True,before_open=wallet.open_fill)
    event=manager.open_position('3443','fixture',1000,AT,70,['fixture'])
    assert event['position']['research_execution']=='TRACKED'
    assert event['position']['paper_skip_reason']=='price_out_of_range'
    assert manager.open_position('3443','fixture',1000,AT,70,[]) is None
    buy.assert_not_called()
    assert PaperEntryPolicy().check('0050','ETF',100,evidence(),AT)['skip_reason']=='etf_ineligible'
