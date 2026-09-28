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
from easystock_admin.line import handle_admin_command
INITIAL={'min_price':20,'max_price':100,'max_gain_pct':5,'max_recommendations':30}
ORIGIN='https://admin.example.com'
CLIENT='123456-test.apps.googleusercontent.com'

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
    def test_version_conflict_keeps_latest(self):
        self.s.update({**INITIAL,'max_price':80},1)
        with self.assertRaises(Conflict):self.s.update({**INITIAL,'max_price':90},1)
        self.assertEqual(self.s.get()['values']['max_price'],80)
    def test_only_allowed_fields_and_valid_ranges(self):
        for values in ({**INITIAL,'stop_loss':1},{**INITIAL,'min_price':101},{**INITIAL,'max_price':True},{**INITIAL,'max_gain_pct':float('nan')},{**INITIAL,'max_gain_pct':1.123},{**INITIAL,'max_recommendations':31},{**INITIAL,'max_recommendations':2.5}):
            with self.assertRaises(ValueError):validate(values)
    def test_line_binding_one_use_and_revocation(self):
        code=self.s.bind_code();self.s.line('user1','e1','bind',code)
        with self.assertRaises(Denied):self.s.line('user2','e2','bind',code)
        self.s.unlink()
        with self.assertRaises(Denied):self.s.line('user1','e3','update',{'max_price':90})
    def test_line_denied_unbound(self):
        with self.assertRaises(Denied):self.s.line('attacker','e1','update',{'max_price':90})
        self.assertEqual(self.s.get()['version'],1)
    def test_line_redelivery_does_not_reapply_after_web_edit(self):
        code=self.s.bind_code();self.s.line('u','bind1','bind',code)
        self.s.line('u','edit1','update',{'max_price':90})
        self.s.update({**INITIAL,'max_price':80},2)
        self.s.line('u','edit1','update',{'max_price':90})
        self.assertEqual(self.s.get()['values']['max_price'],80);self.assertEqual(self.s.get()['version'],3)
    def test_group_binding_denied(self):
        code=self.s.bind_code()
        reply=handle_admin_command('綁定管理員 '+code,{'type':'group','userId':'u'},'e',self.s)
        self.assertIn('私訊',reply);self.assertFalse(self.s.linked())
    def test_live_settings_reads_changes_without_restart(self):
        with patch.dict(os.environ,{'EASYSTOCK_ADMIN_DB':str(self.path)}):
            self.assertEqual(read_live_settings()['max_price'],100)
            self.s.update({**INITIAL,'max_price':80},1)
            self.assertEqual(read_live_settings()['max_price'],80)
    def test_missing_database_fails_closed(self):
        with patch.dict(os.environ,{'EASYSTOCK_ADMIN_DB':str(self.path.parent/'missing.sqlite')}):
            with self.assertRaises(sqlite3.Error):read_live_settings()

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
        self.assertEqual(paper['metrics']['current_capital'], 200000)

    def test_health_treats_auto_approved_paper_model_as_healthy(self):
        from easystock_admin.health import snapshot
        learning = self.path.parent/'learning'
        models = learning/'models'; models.mkdir(parents=True)
        (learning/'training-status.json').write_text(json.dumps({
            'status':'auto_approved_for_paper','samples':470,'version':'research-2026-09-24'
        }))
        (models/'candidate-2026-09-24.json').write_text(json.dumps({'status':'candidate_only'}))
        (models/'latest-approved.json').write_text(json.dumps({
            'approved':True,'deployment_allowed':True,'version':'research-2026-09-24','trained_through':'2026-09-24'
        }))
        with patch.dict(os.environ, {'EASYSTOCK_LEARNING_DATA': str(learning), 'EASYSTOCK_HISTORY_DATA': str(self.path.parent/'history')}):
            result = snapshot(self.s)
        training = next(row for row in result['signals'] if row['key'] == 'daily_training')
        candidate = next(row for row in result['signals'] if row['key'] == 'candidate_model')
        self.assertEqual(training['state'], 'ok')
        self.assertIn('自動核准', training['detail'])
        self.assertEqual(candidate['state'], 'ok')
        self.assertIn('不需人工審核', candidate['detail'])

    def test_health_exposes_profile_mismatch_warning(self):
        from easystock_admin.health import snapshot
        learning=self.path.parent/'learning';models=learning/'models';models.mkdir(parents=True)
        (models/'shadow-summary.json').write_text(json.dumps({'warnings':[{'type':'profile_mismatch','line':'frozen_baseline'}]}))
        with patch.dict(os.environ,{'EASYSTOCK_LEARNING_DATA':str(learning),'EASYSTOCK_HISTORY_DATA':str(self.path.parent/'history')}):
            result=snapshot(self.s)
        signal=next(row for row in result['signals'] if row['key']=='model_profile')
        self.assertEqual(signal['state'],'warning');self.assertIn('frozen_baseline',signal['detail'])

    def test_model_promotion_log_is_bounded_and_whitelisted(self):
        from easystock_admin.health import model_promotion_log
        learning=self.path.parent/'learning';models=learning/'models';models.mkdir(parents=True)
        entry={'promoted_at':'2026-09-28T16:10:00+08:00','promoted_model':'research-2026-09-28',
               'previous_model':'research-2026-09-27','backup_file':'archive/latest-approved-date.json',
               'trained_through':'2026-09-28','validation_mode':'test','secret':'hidden',
               'validation':[{'fold':1,'test_samples':94,'selected_count':30,'expected_value_pct':.2,'brier':.1,'extra':'hidden'}]}
        (models/'promotion-log.jsonl').write_text('bad json\n'+json.dumps(entry)+'\n',encoding='utf-8')
        with patch.dict(os.environ,{'EASYSTOCK_LEARNING_DATA':str(learning)}):result=model_promotion_log()
        self.assertEqual(len(result['entries']),1)
        self.assertEqual(result['entries'][0]['promoted_model'],'research-2026-09-28')
        self.assertNotIn('secret',result['entries'][0])
        self.assertNotIn('extra',result['entries'][0]['validation'][0])

    def test_model_promotion_log_pages_newest_first(self):
        from easystock_admin.health import model_promotion_log
        learning=self.path.parent/'learning';models=learning/'models';models.mkdir(parents=True)
        entries=[]
        for index in range(25):
            entries.append(json.dumps({'promoted_model':f'model-{index}','validation':[]}))
        (models/'promotion-log.jsonl').write_text('\n'.join(entries)+'\n',encoding='utf-8')
        with patch.dict(os.environ,{'EASYSTOCK_LEARNING_DATA':str(learning)}):
            first=model_promotion_log(page=1,page_size=10)
            second=model_promotion_log(page=2,page_size=10)
            third=model_promotion_log(page=3,page_size=10)
        self.assertEqual([r['promoted_model'] for r in first['entries']],[f'model-{i}' for i in range(24,14,-1)])
        self.assertEqual([r['promoted_model'] for r in second['entries']],[f'model-{i}' for i in range(14,4,-1)])
        self.assertEqual(len(third['entries']),5)
        self.assertTrue(first['has_more']);self.assertTrue(second['has_more']);self.assertFalse(third['has_more'])

class WebTests(unittest.TestCase):
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
        self.assertEqual(self.client.get('/admin/settings',base_url=ORIGIN).status_code,403)
        self.assertEqual(self.client.put('/admin/settings',base_url=ORIGIN,json={'values':INITIAL,'version':1},headers={'Origin':ORIGIN}).status_code,403)
    def test_wrong_origin_cannot_start_login(self):
        self.assertEqual(self.post('challenge',{},origin='https://evil.example').status_code,403)
    def test_line_policy_requires_login_csrf_and_origin(self):
        from easystock_admin.conversations import DEFAULTS
        path='/admin/line-policy';data={'values':DEFAULTS,'version':1}
        self.assertEqual(self.client.get(path,base_url=ORIGIN).status_code,403)
        csrf=self.login().json['csrf']
        self.assertEqual(self.client.put(path,base_url=ORIGIN,json=data,headers={'Origin':ORIGIN}).status_code,403)
        self.assertEqual(self.client.put(path,base_url=ORIGIN,json=data,headers={'Origin':'https://evil.example','X-CSRF-Token':csrf}).status_code,403)
        self.assertEqual(self.client.put(path,base_url=ORIGIN,json=data,headers={'Origin':ORIGIN,'X-CSRF-Token':csrf}).status_code,200)
    def test_login_cookie_and_csrf(self):
        response=self.login();self.assertEqual(response.status_code,200)
        cookie=response.headers.getlist('Set-Cookie')[0]
        for text in ('Secure','HttpOnly','SameSite=Strict'):self.assertIn(text,cookie)
        data={'values':{**INITIAL,'max_price':80},'version':1}
        denied=self.client.put('/admin/settings',base_url=ORIGIN,json=data,headers={'Origin':ORIGIN})
        self.assertEqual(denied.status_code,403)
        ok=self.client.put('/admin/settings',base_url=ORIGIN,json=data,headers={'Origin':ORIGIN,'X-CSRF-Token':response.json['csrf']})
        self.assertEqual(ok.status_code,200);self.assertEqual(ok.json['values']['max_price'],80)
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
    def test_signature_precedes_admin_binding(self):
        with tempfile.TemporaryDirectory() as temp:
            fake_line=types.ModuleType('line_bot');fake_line.reply_messages=Mock()
            groups=types.ModuleType('line_group_manager');groups.register_group=Mock()
            game=types.ModuleType('paper_trade_game');game.handle_game_command=lambda *a:None
            stock=types.ModuleType('stock_command_service');stock.CHART_DIR=Path(temp)/'cards';stock.handle_command=lambda *a:[];stock.parse_command=lambda *a:None
            env={'EASYSTOCK_ADMIN_DB':str(Path(temp)/'db'),'LINE_CHANNEL_SECRET':'TEST_ONLY_SECRET'}
            with patch.dict(os.environ,env),patch.dict(sys.modules,{'line_bot':fake_line,'line_group_manager':groups,'paper_trade_game':game,'stock_command_service':stock}):
                spec=importlib.util.spec_from_file_location('tested_webhook',ROOT/'line_stock_bot.py')
                module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
                code=module.ADMIN_STORE.bind_code()
                payload=json.dumps({'events':[{'type':'message','webhookEventId':'e1','replyToken':'reply','source':{'type':'user','userId':'u'},'message':{'type':'text','text':'綁定管理員 '+code}}]}).encode()
                client=module.app.test_client()
                self.assertEqual(client.post('/callback',data=payload,headers={'X-Line-Signature':'bad'}).status_code,400)
                self.assertFalse(module.ADMIN_STORE.linked())
                signature=base64.b64encode(hmac.new(b'TEST_ONLY_SECRET',payload,hashlib.sha256).digest()).decode()
                self.assertEqual(client.post('/callback',data=payload,headers={'X-Line-Signature':signature}).status_code,200)
                self.assertFalse(module.ADMIN_STORE.linked());fake_line.reply_messages.assert_not_called()
                groups.register_group.assert_not_called()

if __name__=='__main__':unittest.main()
