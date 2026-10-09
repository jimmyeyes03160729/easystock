from datetime import datetime, timedelta, timezone
from market_events.revenue_watch import Watch, positive_evidence, period_date

TPE = timezone(timedelta(hours=8))
NOW = datetime(2026, 10, 9, 18, tzinfo=TPE)


def fixtures():
    event = dict(symbol='2330',name='台積電',subject='公告營收創歷史新高',body=None,
                 spoke_date='2026-10-8',subject_key='abc',first_seen_at='2026-10-09T12:00:00+08:00',sources='TWSE')
    event['spoke_date']='2026-10-08'
    return event, {'2330':dict(rev_yoy=10,rev_mom=5,revenue_period='11509')}


def is_open(day):
    return day.weekday()<5 and day.isoformat()!='2026-10-09'


def test_growth_requires_both_and_recent_month(tmp_path):
    event, rev = fixtures()
    w=Watch(tmp_path/'watch.sqlite')
    for value in (0,-1,None,float('nan')):
        rev['2330']['rev_mom']=value
        assert w.capture([event],rev,NOW,is_open)['added']==0
    rev['2330']['rev_mom']=5
    rev['2330']['revenue_period']='11506'
    assert w.capture([event],rev,NOW,is_open)['added']==0


def test_positive_is_content_not_event_category():
    for subject,body in [('召開法說會',None),('董事會通過財報',None),('澄清媒體報導營收創新高','營收創新高'),
                         ('營收未成長',None),('可能取得訂單',None),('營收成長但獲利衰退',None)]:
        assert positive_evidence(subject,body) is None
    assert positive_evidence('自結損益','本季轉虧為盈。')=='本季轉虧為盈'


def test_forward_only_and_deduplicated_with_frozen_evidence(tmp_path):
    event,rev=fixtures()
    w=Watch(tmp_path/'watch.sqlite')
    assert w.capture([event],rev,NOW,is_open)['added']==1
    row=w.snapshot(NOW)['rows'][0]
    assert row['target_day']=='2026-10-12' and row['reference_day']=='2026-10-08'
    assert row['signal_at']==NOW.isoformat()
    assert w.capture([event],rev,NOW+timedelta(days=3),is_open)['added']==0
    event['subject_key']='def'
    assert w.capture([event],rev,NOW,is_open)['added']==0
    rev['2330']['rev_mom']=99
    assert w.snapshot(NOW)['rows'][0]['rev_mom']==5
    w.db.close()
    assert Watch(tmp_path/'watch.sqlite').snapshot(NOW)['summary']['total']==1


def test_exact_day_ohlc_and_no_partial_bar_results(tmp_path):
    event,rev=fixtures(); w=Watch(tmp_path/'watch.sqlite')
    w.capture([event],rev,NOW,is_open)
    ref=dict(date='2026-10-08',open=99,high=101,low=98,close=100,volume=100)
    target=dict(date='2026-10-12',open=102,high=105,low=99,close=104,volume=100)
    w.store_bars({'2330':ref},NOW)
    morning=datetime(2026,10,12,10,tzinfo=TPE)
    w.store_bars({'2330':target},morning)
    assert w.snapshot(morning)['summary']['complete']==0
    evening=morning.replace(hour=18)
    w.store_bars({'2330':{**target,'date':'2026-10-13'}},evening+timedelta(days=1))
    assert w.snapshot(evening+timedelta(days=1))['rows'][0]['status']=='missing_data'
    w.store_bars({'2330':target},evening)
    o=w.snapshot(evening)['rows'][0]['outcome']
    assert o['close_pct']==4 and o['high_pct']==5 and o['low_pct']==-1
    assert o['open_to_close_pct']==1.9608


def test_missing_growth_or_price_never_counts_as_zero_return(tmp_path):
    event,rev=fixtures(); w=Watch(tmp_path/'watch.sqlite')
    event['first_seen_at']='2026-10-10T12:00:00+08:00'
    assert w.capture([event],rev,NOW,is_open)['added']==0
    event['first_seen_at']='2026-10-09T12:00:00+08:00'
    w.capture([event],rev,NOW,is_open)
    s=w.snapshot(NOW+timedelta(days=4))
    assert s['summary']['up_rate'] is None and s['summary']['mean_close_pct'] is None
    assert s['rows'][0]['status']=='missing_data'


def test_period_parsing():
    assert period_date('11509').isoformat()=='2026-09-01'
    assert period_date('2026/09').isoformat()=='2026-09-01'
    assert period_date('11513') is None
