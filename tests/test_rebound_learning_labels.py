from datetime import date,timedelta

import pytest

from rebound_learning.labels import label_candidate


SNAP={'signal_date':'2026-09-28','evidence':{'target_price':110,'invalid_price':95}}


def days(n=20):
    result=[]; day=date(2026,9,29)
    while len(result)<n:
        if day.weekday()<5:
            result.append({'time':day.isoformat(),'open':100,'high':102,'low':98,'close':101})
        day+=timedelta(days=1)
    return result


def test_success_fail_timeout_ambiguous():
    base=days()
    success=[dict(x) for x in base];success[1]['high']=111
    fail=[dict(x) for x in base];fail[2]['low']=94
    ambiguous=[dict(x) for x in base];ambiguous[1].update(high=111,low=94)
    assert label_candidate(SNAP,success)['label']=='SUCCESS'
    assert label_candidate(SNAP,fail)['label']=='FAIL'
    assert label_candidate(SNAP,base)['label']=='TIMEOUT'
    got=label_candidate(SNAP,ambiguous)
    assert got['label']=='AMBIGUOUS' and not got['trainable']
    assert got['days_to_target']==got['days_to_invalid']==2


def test_d1_open_trading_horizons_outcomes_and_maturity():
    future=days();got=label_candidate(SNAP,future)
    assert got['entry_date']==future[0]['time']
    assert got['entry_price']==future[0]['open']
    assert got['label_maturity_date']==future[9]['time']
    assert (date.fromisoformat(future[9]['time'])-date.fromisoformat(SNAP['signal_date'])).days>10
    assert got['return_20d_pct'] is not None
    assert got['MFE_5d_pct']==2 and got['MAE_5d_pct']==-2
    partial=label_candidate(SNAP,future[:7])
    assert partial['label'] is None and partial['return_10d_pct'] is None
    assert partial['return_5d_pct'] is not None and partial['return_20d_pct'] is None


def test_future_k_changes_label_not_d0_candidate():
    future=days(); variant=[dict(x) for x in future];variant[4]['high']=111
    assert label_candidate(SNAP,future)['label']=='TIMEOUT'
    assert label_candidate(SNAP,variant)['label']=='SUCCESS'


def test_entry_outside_bracket_is_untrainable():
    future=days();future[0]['open']=111
    got=label_candidate(SNAP,future)
    assert got['reason']=='entry_outside_bracket' and not got['trainable']
    assert 'entry_price' not in got


def test_invalid_future_date_rejected():
    with pytest.raises(ValueError):label_candidate(SNAP,[{'time':SNAP['signal_date']}])


def test_missing_stock_bar_does_not_shift_market_horizon():
    market=days(); missing=[bar for i,bar in enumerate(market) if i!=3]
    result=label_candidate(SNAP,missing,trading_days=[bar['time'] for bar in market])
    assert result['label'] is None
    assert result['reason']=='missing_horizon_bar'
    assert result['return_5d_pct'] is None
