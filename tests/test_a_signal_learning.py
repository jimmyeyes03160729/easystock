from datetime import datetime,timedelta
import copy
import pytest
from daytrade_learning.a_signal_learning import pattern_features,market_features,make_rows,summarize,candidate_status,checked_day,TPE

DAY='2026-10-14'
ENTRY=DAY+'T09:35:03+08:00'


def pack():
    start=datetime(2026,10,14,9,tzinfo=TPE)
    return {'bars':[{'at':(start+timedelta(minutes=i)).isoformat(),'open':100+i,'close':101+i,'high':102+i,'low':99+i,'volume':10+i} for i in range(40)]}


def trade(key='test',paper='SKIPPED'):
    return {'episode_id':key,'symbol':'2330','status':'CLOSED','entry_time':ENTRY,'exit_time':DAY+'T10:00:00+08:00',
            'entry_features':{'gain_pct':2,'return_5m_pct':1,'surge_60s':3,'buy_ratio_60s':.7,'amount_60s':10000},
            'research_net_after_spread_pct':.2,'paper_execution':paper,'paper_skip_reason':'daily_buy_limit_exceeded'}


def test_post_entry_bar_changes_cannot_change_pattern_features():
    p=pack();first,_=pattern_features(p,ENTRY)
    for r in p['bars'][35:]:r.update(open=10000,close=50000,high=100000,low=1,volume=900000)
    assert pattern_features(p,ENTRY)[0]==first
    assert first['upper_wick_ratio']==pytest.approx(1/3)


def test_missing_minute_is_not_silently_filled():
    p=pack();del p['bars'][30]
    assert pattern_features(p,ENTRY)==({},'gap_in_last_ten_minutes')


def test_market_late_receipt_and_future_quote_are_not_features():
    snaps=[]
    for minute,price in [(29,100),(34,101)]:
        at=f'{DAY}T09:{minute:02}:00+08:00'
        snaps.append({'received_at':at,'indices':{'taiex':{'price':price,'quote_at':at,'received_at':at}}})
    f,t=market_features(snaps,ENTRY);assert f['taiex_return_5m_pct']==pytest.approx(1)
    late=copy.deepcopy(snaps[-1]);late['received_at']=DAY+'T09:36:00+08:00'
    assert market_features([snaps[0],late],ENTRY)[0]['taiex_return_5m_pct'] is None
    assert f['otc_return_5m_pct'] is None


def test_wallet_skipped_signal_is_included_and_missing_outcome_is_not_a_loss():
    incomplete=trade('missing');del incomplete['research_net_after_spread_pct']
    rows,excluded=make_rows([trade(),trade('filled','FILLED'),incomplete],{'2330':pack()},[],DAY)
    r=summarize(rows,excluded)
    assert r['groups']['all']['count']==2 and r['groups']['paper_skipped']['count']==1
    assert excluded=={'missing_cost_and_spread_label':1}
    assert r['missing_features']['taiex_return_5m_pct']==2
    assert candidate_status(rows)['deployment_allowed'] is False
    assert candidate_status(rows)['status']=='BLOCKED'


def test_reserved_old_dates_and_path_injection_are_rejected():
    for day in ['2026-10-02','2026-10-13','../../2026-10-14','2099-10-14']:
        with pytest.raises(ValueError):checked_day(day)


def test_legacy_null_features_are_missing_not_fabricated():
    t=trade();t.update(entry_features=None,entry_gate_evidence=None)
    rows,_=make_rows([t],{'2330':pack()},[],DAY)
    assert 'gain_pct' in rows[0]['missing_features']
    assert rows[0]['policy_version'] is None


def test_extended_feature_trainer_uses_all_columns_and_checks_width():
    from daytrade_learning.research import fit_logistic,logistic_probabilities
    rows=[{'features':[float(i)]*15,'net_return_pct':1 if i>=5 else -1} for i in range(10)]
    model=fit_logistic(rows,iterations=30,feature_count=15)
    assert len(model['coef'])==15
    scores=logistic_probabilities(model,rows)
    assert scores[-1]>scores[0]
    with pytest.raises(ValueError,match='width'):
        fit_logistic(rows,iterations=1,feature_count=5)


def test_forward_candidate_rejects_context_captured_after_entry():
    from daytrade_learning.a_signal_learning import FEATURES
    row={'day':'2026-10-15','entry_time':'2026-10-15T10:00:00+08:00',
         'online_captured_at':'2026-10-15T10:00:01+08:00','policy_version':'synthetic',
         'online_features':{k:1 for k in FEATURES},'missing_features':[]}
    assert candidate_status([row]).get('eligible_online_samples',0)==0
    row['online_captured_at']='2026-10-15T09:59:59+08:00'
    assert candidate_status([row])['eligible_online_samples']==1
