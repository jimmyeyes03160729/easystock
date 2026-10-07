"""G1-G20: synthetic tracked source only; no production data, broker or AI API."""
import copy
import json
import sqlite3
import subprocess
import tempfile
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
import pytest
from guardian.scanner import load_policy,scan,scan_files
from guardian.models import build_report
from guardian.report import save_report,read_report,output_directory
from guardian.diff_review import review
from guardian.ai_review import parse_response,optional_review,security_summary
from guardian.notify import notify

POLICY,MANIFEST=load_policy()
EMPTY={'byte_equivalent':[],'allowed_different':{},'runtime_only':{}}


def check(files,manifest=None):
    return scan_files({p:s.encode() if isinstance(s,str) else s for p,s in files.items()},POLICY,manifest or EMPTY)


def ids(rows):return {r['id'] for r in rows}


def test_G1_research_executor_import_and_alias_call():
    rows=check({'daytrade_learning/new.py':'from easystock_admin.order_service import order_service as broker\ndef run():\n    broker.place_order()\n'})
    assert 'TRADING-001' in ids(rows)
    assert all(r['severity']=='CRITICAL' for r in rows)


def test_G2_paper_live_ledger_and_inverse():
    assert 'TRADING-002' in ids(check({'paper_account.py':"def settle(db):\n    db.execute('INSERT INTO live_trade_orders VALUES (?)')\n"}))
    assert 'TRADING-002' in ids(check({'easystock_admin/live_console.py':"def settle(db):\n    db.execute('INSERT INTO paper_trade_fills VALUES (?)')\n"}))


def test_G3_default_true_and_guard_bypass():
    for path,source in [('deploy/runtime.service','Environment=LIVE_ORDERING_ENABLED=true'),('live.py',"import os\nos.environ['LIVE_ORDERING_ENABLED']='true'"),('live.py',"import os\nactive=os.environ.get('LIVE_ORDERING_ENABLED','true')")]:
        assert 'TRADING-007' in ids(check({path:source}))
    for path,source in [('config.py','LIVE_ORDERING_ENABLED=True'),('config.py',"import os\nactive=os.getenv('LIVE_ORDERING_ENABLED','true')"),('client.js',"const active=process.env.LIVE_ORDERING_ENABLED || 'true';")]:
        assert 'TRADING-007' in ids(check({path:source}))
    assert 'TRADING-003' in ids(check({'easystock_admin/order_service.py':'def live_ordering_enabled():\n    return True\n'}))


def test_G4_normal_double_guard_and_no_keyword_only_approval():
    good="import os\ndef live_ordering_enabled():\n    return os.environ.get('LIVE_ORDERING_ENABLED','').lower() in ('true','1') and os.environ.get('LIVE_ORDERING_CONFIRMATION') == 'I_UNDERSTAND_LIVE_ORDERING'\n"
    assert not check({'easystock_admin/order_service.py':good})
    bad="def live_ordering_enabled():\n    return 'LIVE_ORDERING_ENABLED' and 'LIVE_ORDERING_CONFIRMATION' and 'I_UNDERSTAND_LIVE_ORDERING'\n"
    assert 'TRADING-003' in ids(check({'easystock_admin/order_service.py':bad}))


def test_G5_fake_key_finding_without_value_in_evidence():
    key='sk-'+'a9Zq'*12
    rows=check({'config.py':f'API_KEY={key!r}\n'})
    assert 'SECURITY-001' in ids(rows)
    assert key not in json.dumps(rows)


def test_G6_example_placeholder_allowed():
    assert not check({'.env.example':'API_KEY="YOUR_API_KEY"\nLIVE_ORDERING_ENABLED=false\nCA_PASSWORD="CHANGE_ME"'})


def test_G7_tracked_certificate_never_read():
    rows=check({'cert/client.p12':None})
    assert rows[0]['id']=='SECURITY-002' and rows[0]['severity']=='CRITICAL'


def test_G8_required_byte_mirror_drift():
    manifest={**EMPTY,'byte_equivalent':['paper_account.py']}
    rows=check({'paper_account.py':'x=1','vm_runtime/paper_account.py':'x=2'},manifest)
    assert 'ARCH-002' in ids(rows)


def test_G9_runtime_only_and_explicit_wrapper_difference():
    manifest={**EMPTY,'allowed_different':{'calendar.py':'wrapper delegates root'},'runtime_only':{'provider.js':'canonical Node provider'}}
    assert not check({'calendar.py':'x=1','vm_runtime/calendar.py':'x=2','vm_runtime/provider.js':'const x=1;'},manifest)


def test_G10_approved_overwrite_outside_champion():
    rows=check({'daytrade_learning/promote.py':"def run():\n    model='latest-approved.json'\n    save(model, {})\n"})
    assert 'RESEARCH-004' in ids(rows)


def test_G11_holdout_outcomes_taint_training():
    rows=check({'daytrade_learning/train.py':"def train_model():\n    data=read('PHASE2C_FUTURE_60D/outcomes.json')\n    alias=data\n    estimator.fit(alias)\n"})
    assert 'RESEARCH-001' in ids(rows)


def test_G12_normal_trial_metadata_allowed():
    assert not check({'daytrade_learning/research_governance/trial.py':"def validate(trial):\n    return trial['authorization_id'],trial['schema_version']\n"})


def test_G13_structural_duplicate_fee_evidence():
    body='def fee(price, quantity):\n    value=price*quantity*0.001425\n    return max(20,value)\n'
    rows=check({'fee_a.py':body,'cost/b.py':body.replace('def fee','def fee_total')})
    assert 'ARCH-001' in ids(rows)
    assert len(next(r for r in rows if r['id']=='ARCH-001')['evidence'])==2


def test_G14_public_identity_projection():
    assert 'SECURITY-003' in ids(check({'public_feed.py':"def payload(person):\n    return {'national_id':person.id}\n"}))


def test_G15_private_diagnostic_no_public_exposure():
    assert not check({'easystock_admin/health.py':"def private():\n    return {'certificate_path_configured':True}\n"})


def make_repo(folder,files):
    root=Path(folder)/'repo';root.mkdir()
    subprocess.run(['git','init','-q',str(root)],check=True)
    for p,value in files.items():
        path=root/p;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(value,encoding='utf-8')
    for args in (['add','.'],['-c','user.name=Test','-c','user.email=test@example.test','commit','-qm','fixture']):
        subprocess.run(['git','-C',str(root),*args],check=True)
    return root


def test_G16_diff_changed_critical_files_and_historical_tree(tmp_path):
    root=make_repo(tmp_path,{'strategy_engine.py':'x=1\n'})
    base=subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()
    (root/'strategy_engine.py').write_text('x=2\n')
    subprocess.run(['git','-C',str(root),'-c','user.name=Test','-c','user.email=test@example.test','commit','-qam','change'],check=True)
    report=review(root,base,'HEAD')
    assert report['review_required'] and 'strategy_engine.py' in report['changed_critical_files']
    assert 'DIFF-001' in ids(report['findings'])


def test_G17_failure_unknown_not_resolved(tmp_path):
    root=make_repo(tmp_path,{'x.py':'x=1'})
    prior=build_report(check({'paper_x.py':"def f(db):\n db.execute('INSERT INTO live_trade_orders VALUES(?)')"}),'test')
    with patch('guardian.scanner.scan_files',side_effect=RuntimeError('private secret stack')):
        result=scan(root,previous=prior)
    assert result['overall_status']=='UNKNOWN'
    assert not result['resolved_findings'] and 'private secret stack' not in json.dumps(result)


def test_G18_stable_fingerprint_and_first_seen():
    one=check({'daytrade_learning/new.py':'from easystock_admin.order_service import executor'})
    two=check({'daytrade_learning/new.py':'\n\nfrom easystock_admin.order_service import executor'})
    assert one[0]['fingerprint']==two[0]['fingerprint']
    prior=build_report(one,'a',at='2026-01-01T00:00:00+00:00')
    current=build_report(two,'b',prior,at='2026-01-02T00:00:00+00:00')
    assert current['findings'][0]['first_seen']==prior['generated_at']


def test_G19_resolved_history_retained():
    prior=build_report(check({'x.p12':None}),'a')
    clean=build_report([],'b',prior)
    assert clean['overall_status']=='SAFE' and len(clean['resolved_findings'])==1
    assert len(build_report([],'c',clean)['history'])==1


def test_G20_no_repo_mutation_or_non_git_execution(tmp_path):
    root=make_repo(tmp_path,{'x.py':"raise RuntimeError('must never import scanned source')"})
    before={p.relative_to(root).as_posix():p.read_bytes() for p in root.rglob('*') if p.is_file()}
    run=subprocess.run
    def read_only(command,**kwargs):
        assert command[0]=='git' and command[6] in ('ls-files','rev-parse','show','diff','log','ls-tree')
        assert kwargs['env']['GIT_OPTIONAL_LOCKS']=='0' and 'core.fsmonitor=false' in command
        assert not kwargs.get('shell')
        return run(command,**kwargs)
    with patch('subprocess.run',side_effect=read_only):result=scan(root)
    assert result['scanner_complete']
    save_report(root,tmp_path/'reports',result)
    after={p.relative_to(root).as_posix():p.read_bytes() for p in root.rglob('*') if p.is_file()}
    assert before==after
    with pytest.raises(ValueError):output_directory(root,root/'reports')
    with pytest.raises(ValueError):output_directory(root,'/home/ubuntu/easystock-admin/reports')


def test_future_features_and_normal_future_labels():
    bad="def features(frame):\n    result=frame.close.shift(-1)\n    return result"
    assert 'RESEARCH-002' in ids(check({'rebound_learning/features.py':bad}))
    good="def labels(frame):\n    return frame.close.shift(-1)"
    assert not check({'rebound_learning/labels.py':good})
    assert 'RESEARCH-002' in ids(check({'market_data/context.py':"def context(frame):\n return merge_asof(frame, direction='forward')"}))
    assert 'RESEARCH-002' in ids(check({'rebound_learning/features.py':"def features(frame):\n feature=frame['future_close']\n return feature"}))


def test_profile_mixing_and_missing_idempotency():
    assert 'RESEARCH-003' in ids(check({'daytrade_learning/train.py':"def run(profile_hash,rows):\n    estimator.fit(rows)"}))
    rows=check({'orders.py':"def new_route():\n    api.place_order()"})
    assert {'TRADING-003','TRADING-005'} <= ids(rows)


def test_kill_flatten_and_local_broker_override():
    assert 'TRADING-004' in ids(check({'control.py':"def kill(kill):\n    if kill:\n        broker.flatten_all()"}))
    assert 'TRADING-006' in ids(check({'sync.py':"def sync(local):\n    broker.positions=local"}))


def test_optional_ai_invalid_json_and_commands_never_execute():
    assert optional_review({},env={})['status']=='NOT_CONFIGURED'
    assert optional_review({},env={'GUARDIAN_AI_PROVIDER':'unknown','GUARDIAN_AI_API_KEY':'example'})['status']=='PROVIDER_UNAVAILABLE'
    assert parse_response('not JSON')['status']=='AI_REVIEW_INVALID'
    row={'severity':'HIGH','category':'ARCHITECTURE','title':'Review','path':'x.py','line':1,'impact':'risk','recommendation':'Review boundary','blocks_live_auto':True}
    assert parse_response(json.dumps({'findings':[row]}))['status']=='REVIEW_AVAILABLE'
    row['recommendation']='sudo deploy now'
    assert parse_response(json.dumps({'findings':[row]}))['status']=='AI_REVIEW_INVALID'


def test_owner_notifications_only_high_dedup_and_no_db_changes(tmp_path):
    database=tmp_path/'private.sqlite'
    with closing(sqlite3.connect(database)) as db:
        db.execute('CREATE TABLE notification_policy(id INTEGER,line_summary INTEGER,telegram_summary INTEGER)')
        db.execute('INSERT INTO notification_policy VALUES(1,1,1)');db.commit()
    root=tmp_path/'repo';root.mkdir();report=build_report(check({'x.p12':None}),'abc')
    before=database.read_bytes();seen=[]
    senders={c:lambda text:seen.append(text) or 'sent' for c in ('line','telegram')}
    assert notify(root,tmp_path/'reports',report,database,senders)['status']=='COMPLETED'
    notify(root,tmp_path/'reports',report,database,senders)
    assert len(seen)==2 and database.read_bytes()==before
    assert 'x.p12' not in seen[0]
    assert notify(root,tmp_path/'reports',build_report([],'a'),database,senders)['status']=='NO_HIGH_FINDINGS'


def test_baseline_cannot_accept_critical(tmp_path):
    root=make_repo(tmp_path,{'cert.p12':'not read as source'})
    report=scan(root)
    fp=report['findings'][0]['fingerprint']
    with patch('guardian.scanner.json.loads',wraps=json.loads) as reader:
        # Baseline handling is tested with an actual copy of policy and manifest outside production.
        directory=tmp_path/'policy';directory.mkdir()
        policy=copy.deepcopy(POLICY);policy['mirror_manifest']='mirror.json'
        (directory/'policy.yaml').write_text(json.dumps(policy));(directory/'mirror.json').write_text(json.dumps({'schema_version':1,**EMPTY}))
        (directory/'guardian-baseline.json').write_text(json.dumps({'accepted':[{'fingerprint':fp,'reason':'not permitted'}]}))
        result=scan(root,policy_path=directory/'policy.yaml')
    assert result['overall_status']=='DANGER' and result['findings'][0]['baseline_rejected']


def test_bounded_report_and_security_summary(tmp_path):
    root=tmp_path/'repo';root.mkdir()
    report=build_report([],'a');save_report(root,tmp_path/'reports',report)
    assert read_report(tmp_path/'reports')['overall_status']=='SAFE'
    raw={'Results':[{'Target':'private/path','Secrets':[{'Match':'never copy this'}],'Vulnerabilities':[{'VulnerabilityID':'CVE-2026-1','Severity':'HIGH','Code':'secret'}]}]}
    assert 'never copy' not in json.dumps(security_summary(raw)) and 'private/path' not in json.dumps(security_summary(raw))


def test_paper_aliases_are_not_broker_calls_or_cross_scope_exemptions():
    assert not check({'position_manager.py':'def settle():\n from paper_account import buy as sim\n sim()\n'})
    assert not check({'paper_account.py':'import paper_ledger as sim\ndef settle():\n sim.buy()\n'})
    assert not check({'deploy/check.py':"import importlib\ndef verify():\n account=importlib.import_module('paper_account')\n account.sell()\n"})
    assert 'TRADING-003' in ids(check({'orders.py':'def mock():\n from paper_account import buy\ndef live(buy):\n buy()\n'}))
    assert 'TRADING-002' in ids(check({'paper_new.py':'from easystock_admin.order_service import place_order as fire\ndef run():\n fire()\n'}))


def test_jwt_real_shapes_still_detected_in_tests_and_public_endpoint_redacted():
    jwt='eyJ'+'a'*16+'.'+'b'*24+'.'+'c'*24
    rows=check({'tests/fixture.py':f'token={jwt!r}'})
    assert 'SECURITY-001' in ids(rows) and jwt not in json.dumps(rows)
    endpoint='https://'+'example.ngrok-free.dev/admin'
    rows=check({'index.html':f'<a href="{endpoint}">Owner</a>'})
    assert 'SECURITY-004' in ids(rows) and endpoint not in json.dumps(rows)
    assert not check({'tests/mock.py':"person_id='A123456789'"})
    assert 'SECURITY-001' in ids(check({'credentials.py':"person_id='A123456789'"}))
    assert 'SECURITY-001' in ids(check({'.env.example':'API_KEY='+'qZ9'*16}))


def test_guarded_retention_and_image_cleanup_not_production_delete():
    assert not check({'ops/Dockerfile':'RUN rm -rf /var/lib/apt/lists/*'})
    assert 'DEPLOY-002' in ids(check({'deploy/danger.sh':'rm -rf "$HOME/data"'}))


def test_admin_guardian_owner_auth_and_read_only_projection(tmp_path,monkeypatch):
    from test_admin_order_safety import AdminOrderWebTests,ORIGIN
    from easystock_admin.guardian_view import snapshot
    fixture=AdminOrderWebTests(methodName='runTest');fixture.setUp()
    try:
        monkeypatch.setenv('GUARDIAN_REPORT_DIR',str(tmp_path/'reports'))
        assert fixture.client.get('/admin/api/guardian',base_url=ORIGIN).json['overall_status']=='UNKNOWN'
        report=build_report(check({'cert.p12':None}),'a'*40)
        save_report(Path.cwd(),tmp_path/'reports',report)
        response=fixture.client.get('/admin/api/guardian',base_url=ORIGIN)
        assert response.status_code==200 and response.json['enforcement'] is False
        assert response.json['findings'][0]['evidence'][0]['path']=='cert.p12'
        assert str(tmp_path) not in response.get_data(as_text=True)
        with fixture.store.tx() as db:db.execute("UPDATE session_owners SET email='nonowner@example.test'")
        assert fixture.client.get('/admin/api/guardian',base_url=ORIGIN).status_code==403
        fixture.client.delete_cookie('__Host-easystock_admin',domain='admin.example.com')
        assert fixture.client.get('/admin/api/guardian',base_url=ORIGIN).status_code==401
        assert fixture.client.post('/admin/api/guardian',base_url=ORIGIN).status_code==405
        report['generated_at']='2020-01-01T00:00:00+00:00';save_report(Path.cwd(),tmp_path/'reports',report)
        assert snapshot()['overall_status']=='UNKNOWN'
    finally:fixture.tearDown()


def test_workflows_permissions_and_no_deployment_or_provider_secret():
    import yaml
    root=Path(__file__).resolve().parents[1]
    for name in ('guardian-daily.yml','guardian-weekly.yml','codeql.yml'):
        raw=(root/'.github/workflows'/name).read_text()
        value=yaml.load(raw,Loader=yaml.BaseLoader)
        assert value['permissions']=={'contents':'read'}
        assert all(job.get('permissions',{}).get('contents','read')=='read' for job in value['jobs'].values())
        assert 'secrets.' not in raw and 'ssh ' not in raw and 'update_vm_main' not in raw and 'git push' not in raw
        assert not any('write' in str(job.get('permissions',{})) for job in value['jobs'].values()) or name=='codeql.yml'
    service=(root/'deploy/easystock-architecture-guardian.service').read_text()
    assert 'ProtectSystem=strict' in service and 'ReadWritePaths=/home/ubuntu/easystock-architecture-guardian' in service
