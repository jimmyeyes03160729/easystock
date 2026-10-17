import base64
import hashlib
import hmac
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import types
import unittest
from unittest.mock import patch,Mock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ['ADMIN_OWNER_EMAIL']='owner@example.test'
from easystock_admin.store import Store,Denied,Conflict,validate,read_live_settings,OWNER
INITIAL={'min_price':20,'max_price':100,'max_gain_pct':5,'max_recommendations':30}
ORIGIN='https://admin.example.com'
CLIENT='123456-test.apps.googleusercontent.com'
ORDER={'client_order_id':'0123456789abcdef-0001','symbol':'2330','action':'BUY','price':100,'quantity':1,'is_odd_lot':False,'ca_passwd':'pw'}

class StoreTests(unittest.TestCase):
    def test_unconfigured_owner_is_denied(self):
        with patch('easystock_admin.store.OWNER',''):
            with self.assertRaises(Denied):
                self.s.login({'email':'','email_verified':True,'sub':'1','nonce':'n'},'n')
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'state.sqlite';self.s=Store(self.path,INITIAL)
    def tearDown(self):self.tmp.cleanup()
    def test_owner_email_verified_and_nonce(self):
        for claims in ({'email':'other@gmail.com','email_verified':True,'sub':'1','nonce':'n'},
                       {'email':OWNER,'email_verified':False,'sub':'1','nonce':'n'},
                       {'email':OWNER,'email_verified':True,'sub':'1','nonce':'wrong'}):
            with self.assertRaises(Denied):self.s.login(claims,'n')
    def test_owner_subject_pinned(self):
        self.s.login({'email':OWNER,'email_verified':True,'sub':'1','nonce':'n'},'n')
        with self.assertRaises(Denied):self.s.login({'email':OWNER,'email_verified':True,'sub':'2','nonce':'n'},'n')
    def test_challenge_one_use(self):
        token,nonce=self.s.challenge();self.assertEqual(self.s.take_challenge(token),nonce)
        with self.assertRaises(Denied):self.s.take_challenge(token)
    def test_expired_challenge(self):
        token,_=self.s.challenge()
        with self.s.tx() as db:db.execute('UPDATE challenges SET expires=0')
        with self.assertRaises(Denied):self.s.take_challenge(token)
    def test_only_allowed_fields_and_valid_ranges(self):
        for values in ({**INITIAL,'stop_loss':1},{**INITIAL,'min_price':101},{**INITIAL,'max_price':True},{**INITIAL,'max_gain_pct':float('nan')},{**INITIAL,'max_gain_pct':1.123},{**INITIAL,'max_recommendations':31},{**INITIAL,'max_recommendations':2.5}):
            with self.assertRaises(ValueError):validate(values)
    def test_entry_limits_are_fixed_and_need_no_database(self):
        with patch.dict(os.environ,{'EASYSTOCK_ADMIN_DB':str(self.path.parent/'missing.sqlite')}):
            for key in ('EASYSTOCK_ENTRY_MIN_PRICE','EASYSTOCK_ENTRY_MAX_PRICE','EASYSTOCK_ENTRY_MAX_GAIN_PCT','EASYSTOCK_ENTRY_MAX_RECOMMENDATIONS'):
                os.environ.pop(key,None)
            self.assertEqual(read_live_settings(),{'min_price':1,'max_price':2000,'max_gain_pct':8,'max_recommendations':30})
    def test_entry_limits_env_override_is_validated(self):
        with patch.dict(os.environ,{'EASYSTOCK_ENTRY_MAX_GAIN_PCT':'9.5','EASYSTOCK_ENTRY_MAX_RECOMMENDATIONS':'20'}):
            self.assertEqual(read_live_settings()['max_gain_pct'],9.5);self.assertEqual(read_live_settings()['max_recommendations'],20)
        with patch.dict(os.environ,{'EASYSTOCK_ENTRY_MAX_RECOMMENDATIONS':'31'}):
            with self.assertRaises(ValueError):read_live_settings()
    def test_health_reads_nested_paper_trade_settings(self):
        from easystock_admin.health import snapshot
        with patch.dict(os.environ, {'EASYSTOCK_LEARNING_DATA': str(self.path.parent/'learning'), 'EASYSTOCK_HISTORY_DATA': str(self.path.parent/'history')}):
            result = snapshot(self.s)
        paper = next(row for row in result['signals'] if row['key'] == 'paper_trade')
        self.assertEqual(paper['state'], 'idle')
        self.s.start_paper_trade(200000)
        with patch.dict(os.environ, {'EASYSTOCK_LEARNING_DATA': str(self.path.parent/'learning'), 'EASYSTOCK_HISTORY_DATA': str(self.path.parent/'history')}):
            result = snapshot(self.s)
        paper = next(row for row in result['signals'] if row['key'] == 'paper_trade')
        self.assertEqual(paper['state'], 'ok')
        self.assertEqual(paper['metrics']['daily_buy_limit'], 200000)
        self.assertEqual(paper['metrics']['daily_buy_remaining'], 200000)

    def health_env(self, learning=None):
        return {'EASYSTOCK_LEARNING_DATA': str(learning or self.path.parent/'learning'), 'EASYSTOCK_HISTORY_DATA': str(self.path.parent/'history')}

    def test_health_reports_unidentified_deployment_as_warning(self):
        from easystock_admin.health import snapshot
        with patch.dict(os.environ, {**self.health_env(), 'EASYSTOCK_RELEASE_FILE': str(self.path.parent/'missing-release.json')}, clear=False), \
             patch('easystock_admin.release.running_commit', return_value=''):
            for key in ('EASYSTOCK_RELEASE_ID', 'EASYSTOCK_SOURCE_COMMIT'):
                os.environ.pop(key, None)
            result = snapshot(self.s)
        signal = next(row for row in result['signals'] if row['key'] == 'deployment_release')
        self.assertEqual(signal['state'], 'warning')
        self.assertIn('不能確認', signal['detail'])

    def test_health_flags_release_record_that_lags_the_checkout(self):
        from easystock_admin.health import snapshot
        marker = self.path.parent/'release-info.json'
        marker.write_text(json.dumps({'release_id': 'main-old', 'source_commit': 'a'*40}))
        with patch.dict(os.environ, {**self.health_env(), 'EASYSTOCK_RELEASE_FILE': str(marker)}), \
             patch('easystock_admin.release.running_commit', return_value='b'*40):
            result = snapshot(self.s)
        signal = next(row for row in result['signals'] if row['key'] == 'deployment_release')
        self.assertEqual(signal['state'], 'warning')
        self.assertIn('bbbbbbbbbbbb', signal['detail']); self.assertIn('未更新', signal['detail'])

    def test_health_lists_failed_vm_services(self):
        from easystock_admin.health import snapshot
        listing = ('easystock-intraday.service loaded inactive dead Intraday\n'
                   'easystock-events-backfill.service loaded failed failed Backfill\n'
                   'easystock-esun-marketdata.service loaded active running E.SUN\n'
                   'easystock-codex-executor@x.service loaded failed failed Codex\n')
        completed = __import__('subprocess').CompletedProcess([], 0, stdout=listing, stderr='')
        with patch.dict(os.environ, self.health_env()), patch('subprocess.run', return_value=completed):
            result = snapshot(self.s)
        signal = next(row for row in result['signals'] if row['key'] == 'vm_services')
        self.assertEqual(signal['state'], 'error')
        self.assertIn('easystock-events-backfill', signal['detail'])
        self.assertNotIn('codex-executor', signal['detail'])
        self.assertEqual(signal['metrics'], {'service_total': 3, 'service_running': 1, 'service_failed': 1})

    def test_health_reads_training_action_field(self):
        from easystock_admin.health import snapshot
        learning = self.path.parent/'learning'; learning.mkdir()
        (learning/'training-status.json').write_text(json.dumps({'action': 'blocked', 'sample_count': 1200}))
        with patch.dict(os.environ, self.health_env(learning)):
            result = snapshot(self.s)
        training = next(row for row in result['signals'] if row['key'] == 'daily_training')
        self.assertEqual(training['state'], 'warning')
        self.assertIn('門檻尚未達成', training['detail'])
        self.assertEqual(training['metrics']['samples'], 1200)

    def test_health_omits_retired_model_panels(self):
        from easystock_admin.health import snapshot
        with patch.dict(os.environ, self.health_env()):
            result = snapshot(self.s)
        keys = {row['key'] for row in result['signals']}
        self.assertFalse(keys & {'candidate_model', 'model_profile', 'model_runtime_consistency'})
        self.assertNotIn('model_runtime_consistency', result)
        html = (ROOT/'easystock_admin/static/index.html').read_text(encoding='utf-8')
        for retired in ('runtimeModelPanel', 'modelLogPanel', 'syncVm', 'liveConsolePanel', 'liveKill'):
            self.assertNotIn(retired, html)

    def test_vm_sync_is_not_a_maintenance_action(self):
        from easystock_admin.operations import execute
        with patch('easystock_admin.operations._run') as run:
            with self.assertRaises(Denied):
                execute(self.s, 'sync-vm', 'SYNC_VM')
            run.assert_not_called()

    def test_health_does_not_claim_resume_without_worker_status(self):
        from easystock_admin.health import snapshot
        history=self.path.parent/'history';history.mkdir()
        (history/'progress.json').write_text(json.dumps({'stop_reason':'pair_limit','archived_stock_days':10,'target_stock_days':20,'failed_stock_days':0}))
        with patch('easystock_admin.operations.status', return_value={}), patch.dict(os.environ,{'EASYSTOCK_LEARNING_DATA':str(self.path.parent/'learning'),'EASYSTOCK_HISTORY_DATA':str(history)}):
            result=snapshot(self.s)
        signal=next(row for row in result['signals'] if row['key']=='history_collection')
        self.assertEqual(signal['state'],'idle');self.assertIn('無法確認',signal['detail'])
class WebTests(unittest.TestCase):
    def test_paper_start_uses_daily_limit_and_rejects_cash_payload(self):
        csrf=self.login().json['csrf']
        ok=self.post('paper-trade/start',{'daily_buy_limit':1000000},csrf)
        self.assertEqual(ok.status_code,200)
        self.assertEqual(ok.json['settings']['daily_buy_limit'],1000000)
        self.assertNotIn('current_capital',ok.json['settings'])
        old=self.post('paper-trade/start',{'initial_capital':1000000},csrf)
        self.assertEqual(old.status_code,400)

    def setUp(self):
        from flask import Flask
        from easystock_admin.web import register_admin
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(Path(self.tmp.name)/'db',INITIAL)
        self.env=patch.dict(os.environ,{'ADMIN_GOOGLE_CLIENT_ID':CLIENT,'ADMIN_PUBLIC_ORIGIN':ORIGIN});self.env.start()
        self.nonce=''
        self.claims={'email':OWNER,'email_verified':True,'sub':'owner'}
        self.app=Flask(__name__)
        register_admin(self.app,self.store,lambda credential,client:{**self.claims,'nonce':self.nonce})
        self.client=self.app.test_client()
    def tearDown(self):self.env.stop();self.tmp.cleanup()
    def post(self,path,data,csrf=None,origin=ORIGIN):
        return self.client.post('/admin/'+path,base_url=ORIGIN,json=data,headers={'Origin':origin,**({'X-CSRF-Token':csrf} if csrf else {})})
    def login(self):
        self.nonce=self.post('challenge',{}).json['nonce']
        response=self.post('login',{'credential':'x'*60})
        return response
    def test_anonymous_cannot_read_or_write(self):
        self.assertEqual(self.client.get('/admin/health',base_url=ORIGIN).status_code,403)
        self.assertEqual(self.client.put('/admin/pipeline-settings',base_url=ORIGIN,json={'values':{},'version':1},headers={'Origin':ORIGIN}).status_code,403)
    def test_stock_settings_endpoint_is_removed(self):
        self.login()
        self.assertEqual(self.client.get('/admin/settings',base_url=ORIGIN).status_code,404)
    def test_wrong_origin_cannot_start_login(self):
        self.assertEqual(self.post('challenge',{},origin='https://evil.example').status_code,403)
    def test_notifications_require_login_csrf_origin_and_version(self):
        path='/admin/notifications';data={'line_trade':False,'line_summary':False,'telegram_trade':False,'telegram_summary':False,'version':1}
        self.assertEqual(self.client.get(path,base_url=ORIGIN).status_code,403)
        csrf=self.login().json['csrf']
        self.assertEqual(self.client.put(path,base_url=ORIGIN,json=data,headers={'Origin':ORIGIN}).status_code,403)
        self.assertEqual(self.client.put(path,base_url=ORIGIN,json=data,headers={'Origin':'https://evil.example','X-CSRF-Token':csrf}).status_code,403)
        self.assertEqual(self.client.put(path,base_url=ORIGIN,json=data,headers={'Origin':ORIGIN,'X-CSRF-Token':csrf}).status_code,200)
        self.assertEqual(self.client.put(path,base_url=ORIGIN,json=data,headers={'Origin':ORIGIN,'X-CSRF-Token':csrf}).status_code,409)
    def test_line_quota_limited_none_and_failure_do_not_expose_token(self):
        import easystock_admin.web as web
        self.login()
        token='quota-secret-token';user='U'+'1'*32
        def response(value):
            result=Mock();result.raise_for_status=Mock();result.json=lambda:value;return result
        with patch.dict(os.environ,{'LINE_CHANNEL_ACCESS_TOKEN':token,'LINE_USER_ID':user,'LINE_CONFIG_FILE':str(Path(self.tmp.name)/'none')},clear=False):
            web._LINE_QUOTA_CACHE.update(at=0,value=None)
            with patch('requests.get',side_effect=[response({'type':'limited','value':200}),response({'totalUsage':35})]):
                limited=self.client.get('/admin/line-quota',base_url=ORIGIN)
            self.assertEqual((limited.json['used'],limited.json['limit'],limited.json['remaining']),(35,200,165))
            self.assertNotIn(token,limited.get_data(as_text=True))
            web._LINE_QUOTA_CACHE.update(at=0,value=None)
            with patch('requests.get',side_effect=[response({'type':'none'}),response({'totalUsage':35})]):
                unlimited=self.client.get('/admin/line-quota',base_url=ORIGIN)
            self.assertIsNone(unlimited.json['limit']);self.assertIsNone(unlimited.json['remaining'])
            web._LINE_QUOTA_CACHE.update(at=0,value=None)
            with patch('requests.get',side_effect=__import__('requests').Timeout(token)):
                failed=self.client.get('/admin/line-quota',base_url=ORIGIN)
            self.assertEqual(failed.status_code,503);self.assertNotIn(token,failed.get_data(as_text=True))
    def test_login_cookie_and_csrf(self):
        response=self.login();self.assertEqual(response.status_code,200)
        cookie=response.headers.getlist('Set-Cookie')[0]
        for text in ('Secure','HttpOnly','SameSite=Strict'):self.assertIn(text,cookie)
        current=self.client.get('/admin/pipeline-settings',base_url=ORIGIN).json
        data={'values':{**current['values'],'history_max_pairs':6},'version':current['version']}
        denied=self.client.put('/admin/pipeline-settings',base_url=ORIGIN,json=data,headers={'Origin':ORIGIN})
        self.assertEqual(denied.status_code,403)
        ok=self.client.put('/admin/pipeline-settings',base_url=ORIGIN,json=data,headers={'Origin':ORIGIN,'X-CSRF-Token':response.json['csrf']})
        self.assertEqual(ok.status_code,200);self.assertEqual(ok.json['values']['history_max_pairs'],6)
    def test_wrong_google_user_denied(self):
        self.claims['email']='attacker@gmail.com'
        self.assertEqual(self.login().status_code,403)
    def test_logout_revokes_server_session(self):
        response=self.login();csrf=response.json['csrf']
        self.assertEqual(self.post('logout',{},csrf).status_code,200)
        self.assertEqual(self.client.get('/admin/session',base_url=ORIGIN).status_code,401)
    def test_unconfigured_login_is_disabled(self):
        with patch.dict(os.environ,{'ADMIN_GOOGLE_CLIENT_ID':''}):
            self.assertFalse(self.client.get('/admin/config',base_url=ORIGIN).json['ready'])
            self.assertEqual(self.post('challenge',{}).status_code,403)

    def test_real_order_requires_csrf_and_explicit_server_switch(self):
        response = self.login()
        csrf = response.json['csrf']
        with patch.dict(os.environ, {
            'LIVE_ORDERING_ENABLED': '1',
            'LIVE_ORDERING_CONFIRMATION': 'wrong',
        }, clear=False):
            denied = self.client.post('/admin/api/order/place', base_url=ORIGIN,
                json=ORDER, headers={'Origin': ORIGIN, 'X-CSRF-Token': csrf})
        self.assertEqual(denied.status_code, 403)
        self.assertIn('隔離', denied.json['message'])
        denied_no_csrf = self.client.post('/admin/api/order/place', base_url=ORIGIN,
            json=ORDER, headers={'Origin': ORIGIN})
        self.assertEqual(denied_no_csrf.status_code, 403)

class GoogleCryptoTests(unittest.TestCase):
    def test_real_signature_audience_and_expiry_verification(self):
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization
        from google.auth import crypt,jwt
        from easystock_admin.web import verify_google
        import time
        key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        private=key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
        public=key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        signer=crypt.RSASigner.from_string(private,key_id='offline-test-key')
        now=int(time.time())
        payload={'iss':'https://accounts.google.com','aud':CLIENT,'iat':now,'exp':now+300,'sub':'owner','email':OWNER,'email_verified':True,'nonce':'n'}
        response=types.SimpleNamespace(status=200,data=json.dumps({'offline-test-key':public}).encode())
        with patch('google.auth.transport.requests.Request',return_value=Mock(return_value=response)):
            token=jwt.encode(signer,payload).decode()
            self.assertEqual(verify_google(token,CLIENT)['sub'],'owner')
            with self.assertRaises(ValueError):verify_google(token,'wrong-client')
            expired=jwt.encode(signer,{**payload,'iat':now-600,'exp':now-300}).decode()
            with self.assertRaises(ValueError):verify_google(expired,CLIENT)
            pieces=token.split('.');pieces[2]=('A' if pieces[2][0]!='A' else 'B')+pieces[2][1:]
            with self.assertRaises(ValueError):verify_google('.'.join(pieces),CLIENT)

class WebhookTests(unittest.TestCase):
    def test_signature_verified_webhook_is_silent_for_stock_commands(self):
        with tempfile.TemporaryDirectory() as temp:
            env={'EASYSTOCK_ADMIN_DB':str(Path(temp)/'db'),'LINE_CHANNEL_SECRET':'TEST_ONLY_SECRET'}
            with patch.dict(os.environ,env):
                spec=importlib.util.spec_from_file_location('tested_webhook',ROOT/'line_stock_bot.py')
                module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
                client=module.app.test_client()
                for text in ('P2330','K2330','#2330','P大盤','指令'):
                    payload=json.dumps({'events':[{'type':'message','replyToken':'reply','source':{'type':'user','userId':'u'},'message':{'type':'text','text':text}}]}).encode()
                    self.assertEqual(client.post('/callback',data=payload,headers={'X-Line-Signature':'bad'}).status_code,400)
                    signature=base64.b64encode(hmac.new(b'TEST_ONLY_SECRET',payload,hashlib.sha256).digest()).decode()
                    self.assertEqual(client.post('/callback',data=payload,headers={'X-Line-Signature':signature}).status_code,200)

if __name__=='__main__':unittest.main()
