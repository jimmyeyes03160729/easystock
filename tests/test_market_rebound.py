from datetime import datetime,timedelta
from market_rebound import ReboundGuard

START=datetime.fromisoformat('2026-10-15T09:00:00+08:00')
RED={'valid':True,'level':'RED','gate_action':'BLOCK','gate_reason':'market_risk_red','quote_at':START.isoformat()}

def inputs(now,price=100,volume=1000,stock_price=100):
    at=now.isoformat()
    context={'indices':{k:{'price':price,'quote_at':at} for k in ('taiex','otc')}}
    equity={'day':now.date().isoformat(),'generated_at':at,'rows':{str(2000+i):{'exchange':'TWSE' if i<300 else 'TPEX','price':stock_price,'day_volume':volume,'quote_at':at,'received_at':at} for i in range(600)}}
    worker={'checked_at':at,'connected':True,'authenticated':True,'parser_ok':True}
    return context,equity,worker

def warm(g,volume_multiplier=2,stock_rising=True,index_rising=True):
    result=None
    for second in range(0,421,5):
        now=START+timedelta(seconds=second)
        # Three-minute normalized volume rate doubles after the baseline window.
        volume=1000+min(second,240)*10+max(0,second-240)*10*volume_multiplier
        p=100+second*.002 if index_rising else 100
        c,e,w=inputs(now,p,volume,100+second*.002 if stock_rising else 100)
        result=g.update(dict(RED,quote_at=now.isoformat()),c,e,w,now)
    return result

def test_release_requires_both_indices_volume_and_broad_stock_participation():
    assert warm(ReboundGuard())['rebound_mode']
    assert not warm(ReboundGuard(),volume_multiplier=1)['rebound_mode']
    assert not warm(ReboundGuard(),stock_rising=False)['rebound_mode']
    assert not warm(ReboundGuard(),index_rising=False)['rebound_mode']

def test_fast_drop_reblocks_without_waiting_for_base_red_and_cools_down():
    g=ReboundGuard();assert warm(g)['rebound_mode']
    now=START+timedelta(seconds=425);c,e,w=inputs(now,100,20000,102)
    result=g.update(RED,c,e,w,now)
    assert result['gate_action']=='BLOCK' and result['gate_reason']=='rebound_fast_drop'
    now+=timedelta(seconds=5);c,e,w=inputs(now,101,20050,102)
    assert g.update(RED,c,e,w,now)['gate_reason']=='rebound_cooldown'

def test_slow_decline_triggers_on_green_base():
    g=ReboundGuard();reason=None
    for second in range(0,241,5):
        now=START+timedelta(seconds=second);c,e,w=inputs(now,100-second*.0006)
        result=g.update(dict(RED,gate_action='PASS',level='GREEN',quote_at=now.isoformat()),c,e,w,now)
        if result['gate_reason']=='rebound_slow_decline':reason=True
    assert reason

def test_missing_stale_future_and_new_day_never_open_red():
    g=ReboundGuard();assert warm(g)['rebound_mode']
    now=START+timedelta(seconds=425);c,e,w=inputs(now,101)
    w['authenticated']=False;assert not g.update(RED,c,e,w,now)['rebound_mode']
    c,e,w=inputs(now,101);c['indices']['otc']['quote_at']=(now+timedelta(seconds=1)).isoformat()
    assert g.update(RED,c,e,w,now)['gate_action']=='BLOCK'
    tomorrow=now+timedelta(days=1);c,e,w=inputs(tomorrow,101)
    assert not g.update(RED,c,e,w,tomorrow)['rebound_mode']

def test_repeated_generated_timestamp_cannot_invent_receipt_history():
    g=ReboundGuard()
    now=START;c,e,w=inputs(now)
    for second in range(0,61,5):
        t=START+timedelta(seconds=second);c2,e2,w2=inputs(t,100+second*.002)
        e2['rows']=e['rows'];g.update(RED,c2,e2,w2,t)
    assert len(g.snapshots)==1

def test_single_quote_crash_blocks_before_thirty_seconds_of_history():
    g=ReboundGuard()
    for seconds,price in [(0,100),(5,99.8)]:
        now=START+timedelta(seconds=seconds);c,e,w=inputs(now,price)
        result=g.update(dict(RED,level='GREEN',gate_action='PASS',quote_at=now.isoformat()),c,e,w,now)
    assert result['gate_reason']=='rebound_fast_drop' and result['gate_action']=='BLOCK'
