"""Synthetic fixtures verify replay mechanics; never published as real performance."""
from datetime import datetime,timedelta
import gzip,json
from pathlib import Path

from runway_v2.lanes import LaneSuite,TPE
from runway_v2.replay_journal import InputRecorder
from runway_v2.replay import Cache,load_day,replay_events,build_report,trade_metrics


def record_fixture(tmp_path):
    clock=[datetime(2026,10,12,8,59,tzinfo=TPE)]
    rec=InputRecorder(tmp_path/'recordings',now=lambda:clock[0])
    live=LaneSuite(tmp_path/'live.sqlite',sender=lambda *_:None,recorder=rec)
    save=live._save
    live._save=lambda *_args,**_kwargs:None
    start=clock[0]; now=start.replace(hour=9,minute=3)
    live.advance(start)
    rows=[dict(symbol='TEST',name='測試股',previous_close=119,price=121.5,sector='01'),
          dict(symbol='P1',previous_close=100,price=102,sector='01'),
          dict(symbol='P2',previous_close=100,price=102,sector='01')]
    def book(at,bid=121,depth=20):
        live.on_bidask('TEST',dict(datetime=at,bid_price=[bid-i*.5 for i in range(5)],
            ask_price=[bid+.5+i*.5 for i in range(5)],bid_volume=[depth]*5,ask_volume=[depth/3]*5))
    at=start+timedelta(seconds=15)
    while at<=start.replace(hour=13,minute=0):
        clock[0]=at
        if at==now:
            live.on_radar_update(rows,Cache({}),{r['symbol']:r['previous_close'] for r in rows},at,market={'valid':True,'gate_action':'PASS'})
            for sec,p in ((50,120),(40,122),(30,121.5),(20,122),(9,120.5),(7,121),(5,121),(3,121.5),(1,121.5),(0,121.5)):
                live.on_tick('TEST',p,at-timedelta(seconds=sec),1,10)
            for sec in (10,6,0): book(at-timedelta(seconds=sec))
        if at==now.replace(minute=10): book(at,bid=122)
        live.advance(at)
        at+=timedelta(seconds=15)
    save(clock[0],force=True)
    live.close_recording(); live.worker.shutdown(wait=True)
    assert rec.finished
    return rec,live


def test_exact_replay_matches_live_fee_and_trade_path(tmp_path):
    rec,live=record_fixture(tmp_path)
    events,profile,errors=load_day(rec.folder)
    assert not errors and profile['eligibility']['B1']['eligible']
    assert not profile['eligibility']['B2']['eligible']
    result=replay_events(events)
    assert result['mismatched_clocks']==0 and result['state']==live.state
    trade=result['state']['B1']['trades'][0]
    assert trade['net_pnl']==500-48-48-183
    report=build_report(rec.folder.parent,db_path=tmp_path/'live.sqlite',since='2026-10-12',until='2026-10-12')
    assert report['summary']['B1']['valid_days']==1
    assert report['daily'][0]['comparison']['persisted_live_match'] is True
    assert report['summary']['B1']['scenarios']['extra1tick']['net_pnl']==trade['net_pnl']-1000
    # A repeat run uses reviewed cached trades, while still hashing its raw inputs.
    again=build_report(rec.folder.parent,db_path=tmp_path/'live.sqlite',since='2026-10-12',until='2026-10-12')
    assert again['summary']==report['summary']


def test_delay_preserves_quote_age_and_cannot_use_a_future_quote(tmp_path):
    rec,live=record_fixture(tmp_path)
    events,_,_=load_day(rec.folder)
    delayed=replay_events(events,1000)
    # Current-tick/book confirmation is unavailable at the entry clock. At the
    # next 15s clock it is stale, so latency cannot invent the baseline fill.
    assert delayed['state']['B1']['trades']==[]


def test_checksum_and_unsealed_sources_are_excluded(tmp_path):
    rec,_=record_fixture(tmp_path)
    rec.path.write_bytes(rec.path.read_bytes()+b'corrupt')
    report=build_report(rec.folder.parent,since='2026-10-12',until='2026-10-12')
    assert report['summary']['B1']['valid_days']==0
    assert report['summary']['B1']['scenarios']['baseline']['net_pnl'] is None
    assert any('雜湊' in s for s in report['daily'][0]['lanes']['B1']['reasons'])
    meta=json.loads(rec.meta_path.read_text(encoding='utf-8'));meta['complete']=False
    rec.meta_path.write_text(json.dumps(meta),encoding='utf-8')
    _,_,errors=load_day(rec.folder)
    assert any('未完整' in e for e in errors)


def test_missing_five_level_history_is_not_a_zero_profit_day(tmp_path):
    p=tmp_path/'history/raw/2026-10-08';p.mkdir(parents=True)
    (p/'2330.json.gz').write_bytes(gzip.compress(b'{}'))
    report=build_report(tmp_path/'recordings',[tmp_path/'history'],since='2026-10-01',until='2026-10-09')
    assert len(report['daily'])==1
    for s in report['summary'].values():
        assert s['valid_days']==0 and s['scenarios']['baseline']['win_rate'] is None
        assert s['scenarios']['baseline']['net_pnl'] is None


def test_recorder_loss_is_visible_and_replay_never_sends(tmp_path):
    rec=InputRecorder(tmp_path/'recordings',now=lambda:datetime(2026,10,12,9,tzinfo=TPE),max_bytes=0)
    rec.record('clock',{'now':'2026-10-12T09:00:00+08:00'})
    rec.close()
    meta=json.loads(rec.meta_path.read_text(encoding='utf-8'))
    assert meta['complete'] is False and meta['errors']>0


def test_realized_drawdown_and_net_win_rate():
    trades=[dict(exit_time=str(i),net_pnl=p,shares=1000,entry_price=120,exit_price=121) for i,p in enumerate([500,-700,200])]
    m=trade_metrics(trades)
    assert m['win_rate']==66.67 and m['max_realized_drawdown']==700 and m['net_pnl']==0


def test_preopen_startup_gap_does_not_exclude_a_complete_open_session(tmp_path):
    rec,_=record_fixture(tmp_path)
    with gzip.open(rec.path,'rt',encoding='utf-8') as stream: events=[json.loads(line) for line in stream]
    # A long login/warmup interval before 09:00 is outside all strategy windows.
    events[1]['data']['now']='2026-10-12T08:55:00+08:00'
    raw=''.join(json.dumps(e,ensure_ascii=False)+'\n' for e in events).encode()
    rec.path.write_bytes(gzip.compress(raw))
    import hashlib
    meta=json.loads(rec.meta_path.read_text(encoding='utf-8'))
    meta['sha256']=hashlib.sha256(rec.path.read_bytes()).hexdigest()
    rec.meta_path.write_text(json.dumps(meta),encoding='utf-8')
    _,profile,errors=load_day(rec.folder)
    assert not errors and profile['eligibility']['B1']['eligible']
    assert profile['max_clock_gap']>30 and profile['max_clock_gap_by_lane']['B1']<=30
