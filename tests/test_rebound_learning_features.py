from copy import deepcopy

import pytest

from range_rebound import build_rebound_feed, evaluate_technical
from rebound_learning.collector import collect,verified_financial,SETTINGS
from rebound_learning.features import extract,near_miss_diagnostics
from rebound_learning_fixture import bars,verified_stock


def test_deterministic_and_future_bar_is_rejected():
    source=bars(); day=source[-1]['time']
    tech=evaluate_technical(source,day,source[-1]['close'])
    assert tech['eligible']
    a=extract(source,day,tech)
    assert a==extract(deepcopy(source),day,deepcopy(tech))
    assert len(a)<=30
    assert a['volume_ratio_5d'] is not None
    changed=deepcopy(source)+[{'time':'2027-01-01',**{k:1 for k in ('open','high','low','close')}}]
    with pytest.raises(ValueError,match='future'):
        extract(changed,day,tech)
    with pytest.raises(ValueError,match='future'):
        collect('2330',changed,day)


def test_production_baseline_unchanged_and_passed_pending():
    source=bars(); day=source[-1]['time']; stock=verified_stock(day)
    before=build_rebound_feed({'2330':stock},{'2330':source},day,'test','2026-01-01T00:00:00Z')
    passed=collect('2330',source,day,stock=stock)
    pending=collect('2330',source,day)
    after=build_rebound_feed({'2330':stock},{'2330':source},day,'test','2026-01-01T00:00:00Z')
    assert before==after
    assert passed['candidate_kind']=='PASSED'
    assert pending['candidate_kind']=='PENDING'
    assert 'label' not in passed and 'entry_price' not in passed


def test_financial_future_publication_not_used():
    source=bars(); day=source[-1]['time']; stock=verified_stock(day)
    stock['field_meta']['eps']['published_at']='2027-01-01T00:00:00+08:00'
    assert verified_financial(stock,day)['data_available'] is False
    row=collect('2330',source,day,stock=stock)
    assert row['candidate_kind']=='PENDING'
    assert row['financial_data_available'] is False
    assert row['historical_market_context_available'] is False


def test_missing_volume_is_null_not_zero():
    source=bars();source[-1]['volume']=None;day=source[-1]['time']
    row=collect('2330',source,day)
    assert row['features']['volume_ratio_5d'] is None


def test_clear_rejection_is_not_near_miss():
    source=bars(); source[-1]['low']=2
    assert near_miss_diagnostics(source,source[-1]['time'],tolerance=SETTINGS['near_miss_tolerance']) is None
    assert collect('2330',source,source[-1]['time'],settings={**SETTINGS,'rejected_control_hash_modulus':10**30}) is None


def test_near_miss_numeric_threshold():
    source=bars(); day=source[-1]['time']
    # Move D0 close just beyond a numerical boundary, retaining a valid candle.
    found=[]
    for close in (10.55,10.6,10.65,10.7,10.75,10.8,10.85,10.9,10.95,11.0,11.05,11.1,11.15,11.2):
        variant=deepcopy(source);variant[-1].update(open=10.05,close=close,high=close+.1)
        if evaluate_technical(variant,day,close)['eligible']:continue
        row=collect('2330',variant,day)
        if row and row['candidate_kind']=='NEAR_MISS':found.append(row)
    assert found, 'fixture should have a single nearby numeric failure'
    assert found[0]['evidence']['failed_rule'] in ('range_position','net_rr','distance_to_support')
