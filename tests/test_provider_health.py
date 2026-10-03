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


def test_health_only_rule_merge_preserves_private_feeds():
    from tools.firebase_rules import preserved_public_paths
    from types import SimpleNamespace
    statuses = iter([200, 401, 401, 401])
    with patch('tools.firebase_rules.requests.get', side_effect=lambda *a, **k: SimpleNamespace(status_code=next(statuses))):
        assert preserved_public_paths('https://example.test', ['summary', 'rebound_feed', 'provider_health', 'premarket_status']) == ['summary', 'provider_health', 'premarket_status']


def test_esun_event_timestamp_and_quote_error_are_safe_diagnostics():
    assert sanitize({'last_event_at':NOW.isoformat(), 'error_code':'quote_request_failed'}) == {'last_event_at':NOW.isoformat(), 'error_code':'quote_request_failed'}

def test_stale_but_parsed_response_has_market_closed_semantics(tmp_path,monkeypatch):
    monkeypatch.setenv('EASYSTOCK_MARKET_DATA_DIR',str(tmp_path))
    stale=NOW-timedelta(days=1)
    observe('shioaji',ok=True,quote_at=stale.isoformat(),connected=True)
    row=json.loads((tmp_path/'shioaji.json').read_text())
    row['checked_at']=NOW.isoformat();row['last_ok_at']=NOW.isoformat();row['last_data_at']=NOW.isoformat()
    assert provider_health('shioaji',row,NOW,'OPEN')['status']=='DEGRADED'
    assert provider_health('shioaji',row,NOW,'CLOSED')['status']=='UNKNOWN'
    today={**good(),'quote_at':NOW.isoformat()}
    assert provider_health('shioaji',today,NOW.replace(hour=15),'CLOSED')['status']=='MARKET_CLOSED'


def test_fugle_is_a_scheduled_provider_without_vm_key(tmp_path,monkeypatch):
    monkeypatch.delenv('FUGLE_API_KEY',raising=False)
    public,private=aggregate(NOW,'CLOSED',tmp_path)
    assert public['providers']['fugle']['status']=='UNKNOWN'
    assert private['providers']['fugle']['kind']=='scheduled'
    assert 'configured' not in public['providers']['fugle']


def test_market_gate_diagnostics_are_private_and_sanitized(tmp_path,monkeypatch):
    from market_data.diagnostics import save_gate, read_gate
    monkeypatch.setenv('EASYSTOCK_MARKET_DATA_DIR',str(tmp_path))
    gate={'level':'GREEN','market_condition_reason':'fresh_live_green','data_health':'DEGRADED',
          'gate_reason':'market_risk_pass','selected_source':'esun','premarket_level':'UNKNOWN',
          'premarket_reason':'premarket_missing_or_stale',
          'sources':{'esun':{'status':'HEALTHY','quote_at':NOW.isoformat(),'age_seconds':0,
                             'usable':True,'api_key':'test-secret'}}}
    save_gate(gate,now=NOW,premarket_date='2026-09-29',model_ready=True,
              radar_candidate_count=3,block_counts={'market_data_unavailable':8})
    assert 'test-secret' not in (tmp_path/'market-gate.json').read_text()
    data=read_gate()
    assert data['selected_source']=='esun'
    assert data['entry_block_evaluations']['market_data_unavailable']==8
    assert 'test-secret' not in json.dumps(data)
    history=(tmp_path/('market-gate-'+NOW.date().isoformat()+'.jsonl')).read_text()
    assert 'test-secret' not in history
    assert json.loads(history)['sources']['esun']['quote_at']==NOW.isoformat()

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

def test_fugle_cache_does_not_expose_unlisted_fields(tmp_path):
    (tmp_path/'fugle.json').write_text(json.dumps({'status':'ONLINE','checked_at':NOW.isoformat(),
        'kind':'scheduled','workflow_source':'github_actions','api_key':'test-only',
        'exception':'private-error','run_id':'123','expected_scan_date':'2026-09-30',
        'scan_date':'2026-09-30','last_success_at':NOW.isoformat(),
        'data_generated_at':NOW.isoformat(),'freshness':'on_schedule'}))
    public,private=aggregate(NOW,'CLOSED',tmp_path)
    assert public['providers']['fugle']=={'status':'ONLINE','last_checked_at':NOW.isoformat()}
    assert 'test-only' not in json.dumps(private)
    assert 'private-error' not in json.dumps(private)
