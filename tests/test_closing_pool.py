"""Synthetic evidence tests; these fixtures are never published as performance."""
import json
from datetime import datetime
from unittest.mock import patch
import pytest
from eight_methods.rules import TPE,CLOSING,closing
from eight_methods.feed import build
from eight_methods.company_shares import normalize,source_day
from eight_methods.closing_inputs import enrich
from runway_v2 import closing_pool as P
from runway_v2.closing_experiment import ClosingExperiment
from runway_v2.replay import apply,Cache
from runway_v2.lanes import LaneSuite

def at(clock,day='2026-10-14'):
    return datetime.fromisoformat(day+'T'+clock+'+08:00')

def candidate(symbol='2330',volume=20_000_000):
    r={'symbol':symbol,'name':'測試','price':104,'previous_close':100,'quote_at':at('13:24:20').isoformat(),
       'day_volume':volume,'past_volumes':[10_000_000]*5,'past_closes':list(range(40,101)),
       'turnover_pct':5,'market_cap':10e9,'cap_currency':'TWD','benchmark_gain_pct':1,'day_high':105}
    return dict(r,**closing(r,at('13:24:30')))

def feed(rows=None):
    return {'version':CLOSING,'ruleset':'TW_CLOSING_RULES_V1','day':'2026-10-14',
            'updated_at':at('13:24:30').isoformat(),'rows':rows or [candidate()]}

def freeze(root,rows=None):
    P.observe(feed(rows),root,at('13:24:30'))
    with patch('runway_v2.closing_pool.next_session',return_value='2026-10-15'),patch('market_calendar.is_market_open',return_value=(True,'test')):
        return P.freeze(root,'2026-10-14','2026-10-15',at('13:25:00'))

def test_full_eight_gates_freshness_lot_cap_and_fixed_volume_ranking():
    rows=[candidate(str(2300+i),20_000_000+i) for i in range(15)]
    selected=P.select(feed(rows))
    assert len(selected)==10 and selected[0]['symbol']=='2314'
    assert P.select(feed([dict(candidate(),price=201)]))==[]
    assert P.select(feed([dict(candidate(),quote_at=at('13:24:31').isoformat())]))==[]
    assert P.select(feed([dict(candidate(),quote_at=at('13:23:59').isoformat())]))==[]
    for field,value in [('complete',False),('phase','auction'),('conditions',candidate()['conditions'][:-1])]:
        assert not P.select(feed([dict(candidate(),**{field:value})]))
    broken=candidate();broken['conditions'][2]['state']='insufficient'
    assert not P.select(feed([broken]))

def test_freeze_is_immutable_hash_verified_and_never_fills_missing_candidates(tmp_path):
    p=freeze(tmp_path)
    assert p['symbols']==['2330'] and p['production_effect']=='B1_SHADOW_ONLY'
    P.observe(feed([candidate('2317')]),tmp_path,at('13:24:40'))
    assert P.freeze(tmp_path,'2026-10-14','2026-10-15',at('14:00:00'))['symbols']==['2330']
    path=tmp_path/'pools/2026-10-15.json';x=json.loads(path.read_text(encoding='utf-8'));x['symbols']=['9999'];P.write(path,x)
    with pytest.raises(ValueError,match='invalid_pool_receipt'):P.load(tmp_path,'2026-10-15')
    with patch('runway_v2.closing_pool.next_session',return_value='2026-10-15'),patch('market_calendar.is_market_open',return_value=(True,'test')):
        empty=P.freeze(tmp_path/'empty','2026-10-14','2026-10-15',at('14:00:00'))
    assert empty['symbols']==[] and empty['status']=='EMPTY_DATA_INSUFFICIENT'
    with pytest.raises(ValueError):P.freeze(tmp_path,'2026-10-14','2026-10-15',at('13:24:59'))

def test_official_share_sources_use_issued_common_not_capital_or_par():
    r=normalize([{'公司代號':'2330','出表日期':'1151013','已發行普通股數或TDR原股發行股數':'400,000,000','實收資本額':'1'}],'TWSE',at('07:30:00').isoformat())
    assert r['2330']['issued_common_shares']==400_000_000
    assert source_day('1151013')=='2026-10-13'
    assert not normalize([{'公司代號':'2330','出表日期':'1151013','實收資本額':'4000000000'}],'TWSE',at('07:30:00').isoformat())
    r=normalize([{'SecuritiesCompanyCode':'6488','Date':'2026/10/13','IssueShares':'400000000'}],'TPEX',at('07:30:00').isoformat())
    assert r['6488']['asof_day']=='2026-10-13'

def test_input_join_requires_predecision_issuance_and_receipt_same_units(tmp_path):
    q={'symbol':'2330','price':104,'day_high':105,'quote_at':at('13:24:20').isoformat(),
       'received_at':at('13:24:21').isoformat(),'exchange':'TWSE','day_volume':20_000_000}
    sp=tmp_path/'snapshot.json';mp=tmp_path/'shares.json'
    P.write(sp,{'schema_version':1,'day':'2026-10-14','generated_at':at('13:24:22').isoformat(),'rows':{'2330':q}})
    meta={'issued_common_shares':400_000_000,'exchange':'TWSE','asof_day':'2026-10-13','received_at':at('07:30:00').isoformat(),'source':'official'}
    P.write(mp,{'rows':{'2330':meta}});rows={};enrich(rows,sp,mp,at('13:24:30'))
    assert rows['2330']['turnover_pct']==5 and rows['2330']['market_cap']==41_600_000_000
    P.write(mp,{'rows':{'2330':dict(meta,received_at=at('13:24:31').isoformat())}})
    rows={};enrich(rows,sp,mp,at('13:24:30'));assert 'market_cap' not in rows['2330']
    P.write(sp,{'schema_version':1,'day':'2026-10-13','generated_at':at('13:24:22').isoformat(),'rows':{'2330':q}})
    assert enrich({},sp,mp,at('13:24:30'))

def test_full_market_does_not_expand_opening_or_publish_unqualified_new_names():
    rows={'2330':candidate(),'2317':dict(candidate('2317'),price=100),'2300':candidate('2300')}
    result=build(rows,at('13:24:30'),opening_symbols={'2330'})
    assert [r['symbol'] for r in result['opening_eight']['rows']]==['2330']
    assert {r['symbol'] for r in result['closing_eight']['rows']}=={'2330','2300'}

def test_shadow_balances_lists_preserves_inputs_and_never_exceeds_budget(tmp_path):
    freeze(tmp_path,[candidate('2330'),candidate('2317')])
    t=at('08:55:00','2026-10-15');trial=ClosingExperiment(tmp_path,lambda s:'active',t,record=False,book_limit=3)
    try:
        for arm in trial.arms.values():assert not arm.entry_symbols
        trial.on_tick('2300',100,t,1,10)
        assert all('2300' in arm.tapes for arm in trial.arms.values())
        trial.select(['2300'],set(),at('09:00:01','2026-10-15'));assert trial.control is None
        ranked,pinned=trial.select(['2300','2301','2302'],{'2499'},at('09:00:02','2026-10-15'))
        assert len(pinned)==3 and '2499' in pinned
        assert trial.arms['closing'].entry_symbols=={'2330','2317'}
        assert trial.arms['control'].entry_symbols=={'2300','2301'}
        trial.select(['2500','2501'],set(),at('09:00:03','2026-10-15'))
        assert trial.control['symbols']==['2300','2301']
        assert all(a.active_lanes==('B1',) for a in trial.arms.values())
        assert trial.arms['control'].path!=trial.arms['closing'].path
    finally:trial.close()

def test_missing_pool_does_not_change_formal_quota(tmp_path):
    t=at('09:00:00','2026-10-15');trial=ClosingExperiment(tmp_path,lambda s:'active',t,record=False)
    try:
        assert trial.select(['2330'],{'2317'},t)==(['2330'],{'2317'})
        trial.advance(t);assert json.loads((tmp_path/'latest.json').read_text(encoding='utf-8'))['comparison_status']=='EXCLUDED_NO_VALID_CLOSING_POOL'
    finally:trial.close()

def test_entry_universe_change_replays_causally_without_changing_default_lanes(tmp_path):
    s=LaneSuite(tmp_path/'live.sqlite',sender=lambda *_:None)
    try:
        assert set(s.active_lanes)=={'B1','B2','B3'} and s.entry_symbols is None
        apply(s,{'kind':'entry_universe','data':{'symbols':['2330']}})
        assert s.entry_symbols=={'2330'}
    finally:s.worker.shutdown(wait=True)

def test_audit_excludes_missing_source_without_claiming_zero_profit(tmp_path):
    from runway_v2.closing_audit import audit
    result=audit(tmp_path,'2026-10-15')
    assert result['status']=='EXCLUDED' and result['arms']=={} and 'net_pnl_difference' not in result


def test_frozen_missing_data_and_complete_failures_are_distinct(tmp_path):
    missing=candidate();missing['conditions'][0]['state']='insufficient';missing['complete']=False
    a=freeze(tmp_path/'missing',[missing])
    assert a['status']=='EMPTY_DATA_INSUFFICIENT' and a['assessment']['insufficient']==1
    failed=candidate();failed['conditions'][0]['state']='fail';failed['passed']=7
    b=freeze(tmp_path/'failed',[failed])
    assert b['status']=='EMPTY_NO_MATCH' and b['assessment']['failed']==1


def test_snapshot_loaded_before_cutoff_survives_file_replacement_and_future_still_rejected(tmp_path):
    from eight_methods.closing_inputs import read_json,merge_current_indices
    sp=tmp_path/'s.json';mp=tmp_path/'m.json'
    snapshot={'schema_version':1,'day':'2026-10-14','generated_at':at('13:24:21').isoformat(),
              'rows':{'2330':{'price':104,'exchange':'TWSE','quote_at':at('13:24:20').isoformat(),
                              'received_at':at('13:24:21').isoformat()}}}
    P.write(sp,snapshot);loaded=read_json(sp)
    P.write(sp,dict(snapshot,generated_at=at('13:24:31').isoformat()))
    rows={};assert not enrich(rows,sp,mp,at('13:24:30'),snapshot=loaded,shares={'unused':{}})
    assert rows['2330']['price']==104
    assert enrich({},sp,mp,at('13:24:30'))  # True future is still rejected.
    context={'indices':{'taiex':{'price':100,'quote_at':at('13:24:29').isoformat(),'received_at':at('13:24:30').isoformat()}}}
    merge_current_indices(rows,context,at('13:24:30'))
    assert rows['IX0001']['price']==100 and rows['IX0001']['quotes']==[]
    later={};merge_current_indices(later,context,at('13:24:29'))
    assert 'IX0001' not in later


def test_main_decides_after_slow_reads_and_never_backdates_after_cutoff(tmp_path,monkeypatch):
    from eight_methods import feed as F
    import sys
    market=tmp_path/'market';out=tmp_path/'out';out.mkdir()
    trial=tmp_path/'trial'
    monkeypatch.setenv('EASYSTOCK_MARKET_DATA_DIR',str(market));monkeypatch.setenv('B1_CLOSING_POOL_DIR',str(trial))
    monkeypatch.setattr(F,'OUT',out)
    row=candidate()
    P.write(market/'equity-snapshot.json',{'schema_version':1,'day':'2026-10-14','generated_at':at('13:24:21').isoformat(),
        'rows':{'2330':dict(row,exchange='TWSE',received_at=at('13:24:21').isoformat())}})
    monkeypatch.setattr(F,'read_journal',lambda *_:({'2330':dict(row,quotes=[])},[]))
    monkeypatch.setattr(F,'enrich_daily',lambda *_:[])
    monkeypatch.setattr('market_data.opening_observations.merge_indices',lambda *_:[])
    monkeypatch.setattr('market_calendar.is_market_open',lambda *_:(False,'test'))
    class Clock:
        ticks=iter([at('13:24:00'),at('13:24:22'),at('13:25:00'),at('13:25:01')])
        @classmethod
        def now(cls,*_):return next(cls.ticks)
    monkeypatch.setattr(F,'datetime',Clock);monkeypatch.setattr(sys,'argv',['feed'])
    F.main()
    result=json.loads((out/'closing_eight.json').read_text())
    assert result['updated_at']==at('13:25:01').isoformat()
    assert '缺當日有效尾盤行情快照' not in result['diagnostics']
    assert result['rows'][0]['phase']=='auction'
    assert not (trial/'observations/2026-10-14.json').exists()
