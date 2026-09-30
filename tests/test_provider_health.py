import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
import pytest
from market_data.health import TPE, aggregate, provider_health, sanitize, market_session, observe
from market_data.context import esun_index_snapshot

NOW=datetime(2026,9,30,10,30,tzinfo=TPE)
def good():
    return dict(connected=True,authenticated=True,subscribed=True,parser_ok=True,
                last_ok_at=NOW.isoformat(),last_data_at=NOW.isoformat(),quote_at=NOW.isoformat(),
                checked_at=NOW.isoformat(),last_heartbeat_at=NOW.isoformat())

@pytest.mark.parametrize('change,session,expected',[
    ({},'OPEN','ONLINE'),
    ({'quote_at':(NOW-timedelta(minutes=10)).isoformat()},'OPEN','DEGRADED'),
    ({'connected':False},'OPEN','OFFLINE'),
    ({'connected':False},'CLOSED','OFFLINE'),
    ({'quote_at':(NOW-timedelta(days=1)).isoformat()},'CLOSED','MARKET_CLOSED'),
    ({'parser_ok':False,'error_code':'parser_invalid','consecutive_failures':1},'OPEN','DEGRADED'),
    ({'quote_at':None,'last_data_at':None},'OPEN','DEGRADED'),
    ({'quote_at':(NOW+timedelta(minutes=1)).isoformat()},'OPEN','DEGRADED'),
    ({'last_heartbeat_at':(NOW-timedelta(minutes=10)).isoformat()},'OPEN','DEGRADED'),
    ({'checked_at':(NOW-timedelta(minutes=10)).isoformat()},'OPEN','OFFLINE'),
])
def test_stream_requires_actual_fresh_evidence(change,session,expected):
    assert provider_health('esun',{**good(),**change},NOW,session)['status']==expected

@pytest.mark.parametrize('sj,es,usable',[(True,False,True),(False,True,True),(False,False,False)])
def test_independent_market_sources(tmp_path,sj,es,usable):
    for key,healthy in [('shioaji',sj),('esun',es)]:
        (tmp_path/(key+'.json')).write_text(json.dumps(good() if healthy else {'connected':False}))
    public,private=aggregate(NOW,'OPEN',tmp_path)
    assert private['market_data']['usable']==usable
    assert 'market_risk' not in public

def test_public_allowlist_and_private_sanitization(tmp_path):
    evil={**good(),'error_code':'password=abc https://a/?token=abc','api_key':'abc',
          'account_id':'123','path':'/etc/key','ip':'192.0.2.10','traceback':'secret',
          'latency_ms':25,'reconnect_count':3,'authorization':'Bearer xxx'}
    (tmp_path/'esun.json').write_text(json.dumps(evil))
    public,private=aggregate(NOW,'OPEN',tmp_path)
    assert set(public['providers']['esun'])=={'status','last_checked_at'}
    assert private['providers']['esun']['latency_ms']==25
    assert private['providers']['esun']['reconnect_count']==3
    for payload in (public,private):
        text=json.dumps(payload)
        for secret in ('password','api_key','account_id','/etc/key','192.0.2.10','Bearer','traceback'):
            assert secret not in text

def test_calendar_and_taipei_date():
    calls=[]
    def calendar(day):calls.append(day);return False,'holiday',{}
    assert market_session(NOW,calendar)=='CLOSED'
    assert calls==[NOW.date()]
    assert market_session(NOW,lambda _: (True,'',{}))=='OPEN'
    assert market_session(NOW.replace(hour=14),lambda _: (True,'',{}))=='CLOSED'
    assert sanitize({'quote_at':'2026-09-30T02:30:00Z'})['quote_at']==NOW.isoformat()

def test_idle_ai_is_standby_not_offline():
    assert provider_health('openai',{},NOW,'OPEN')['status']=='UNKNOWN'
    assert provider_health('gemini',{'last_ok_at':(NOW-timedelta(days=3)).isoformat()},NOW,'OPEN')['status']=='UNKNOWN'

def test_stale_but_parsed_response_has_market_closed_semantics(tmp_path,monkeypatch):
    monkeypatch.setenv('EASYSTOCK_MARKET_DATA_DIR',str(tmp_path))
    stale=NOW-timedelta(days=1)
    observe('shioaji',ok=True,quote_at=stale.isoformat(),connected=True)
    row=json.loads((tmp_path/'shioaji.json').read_text())
    row['checked_at']=NOW.isoformat();row['last_ok_at']=NOW.isoformat();row['last_data_at']=NOW.isoformat()
    assert provider_health('shioaji',row,NOW,'OPEN')['status']=='DEGRADED'
    assert provider_health('shioaji',row,NOW,'CLOSED')['status']=='MARKET_CLOSED'

def test_context_never_uses_receipt_as_quote_time(tmp_path,monkeypatch):
    monkeypatch.setenv('EASYSTOCK_MARKET_DATA_DIR',str(tmp_path))
    (tmp_path/'esun.json').write_text(json.dumps(good()))
    (tmp_path/'context.json').write_text(json.dumps({'indices':{'taiex':{'source':'esun','symbol':'IX0001',
        'quote_at':NOW.isoformat(),'received_at':(NOW+timedelta(minutes=5)).isoformat(),'change_pct':.5}}}))
    assert esun_index_snapshot(NOW)['datetime']==NOW.isoformat()
    assert esun_index_snapshot(NOW+timedelta(minutes=5)) is None

def test_observation_io_failure_does_not_interrupt(monkeypatch,tmp_path):
    monkeypatch.setenv('EASYSTOCK_MARKET_DATA_DIR',str(tmp_path))
    with patch('market_data.health.atomic',side_effect=OSError('secret')):
        observe('shioaji',ok=True)

def test_admin_health_requires_auth():
    from flask import Flask
    from easystock_admin.web import register_admin
    from easystock_admin.store import Denied
    class Store:
        def session(self,_):raise Denied('denied')
    app=Flask(__name__);register_admin(app,Store())
    assert app.test_client().get('/admin/health').status_code==403

def test_vm_admin_provider_views_match_canonical_source():
    root=Path(__file__).resolve().parents[1]
    for name in ('intraday_live.py','easystock_admin/health.py','easystock_admin/static/admin.js','easystock_admin/static/index.html'):
        assert (root/name).read_bytes()==(root/'vm_runtime'/name).read_bytes()

def test_invalid_fugle_payload_does_not_report_online(tmp_path,monkeypatch):
    from market_data.publish import probe_fugle
    monkeypatch.setenv('EASYSTOCK_MARKET_DATA_DIR',str(tmp_path));monkeypatch.setenv('FUGLE_API_KEY','test-only')
    class Response:
        def raise_for_status(self):pass
        def json(self):return {'symbol':'2330','lastPrice':'nan','lastUpdated':NOW.timestamp()*1e6}
    with patch('market_data.publish.requests.get',return_value=Response()):probe_fugle(NOW,'OPEN')
    data=json.loads((tmp_path/'fugle.json').read_text())
    assert data['parser_ok'] is False
    assert 'test-only' not in json.dumps(data)
