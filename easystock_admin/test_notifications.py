import contextlib
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from easystock_admin.store import Store, Conflict
from easystock_admin import conversations as c, notifications as n
from trade_notifications import send_trade, telegram_send, event_identity
import requests

TOKEN='123456:'+'x'*35
GROUP={'type':'group','groupId':'C'+'1'*32}

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.tmp.name)/'db',{'min_price':1,'max_price':100,'max_gain_pct':5})
        self.env=patch.dict(os.environ,{'TELEGRAM_BOT_TOKEN':TOKEN,'TELEGRAM_GROUP_ID':'-1001234567','TELEGRAM_CONFIG_FILE':str(Path(self.tmp.name)/'absent')});self.env.start()
        self.key=c.observe(self.store,GROUP)
        with self.store.tx() as db:
            db.execute('UPDATE line_conversations SET archived=0,push=1 WHERE id=?',(self.key,))
            db.execute('UPDATE telegram_policy SET push=1')
        self.http=patch('trade_notifications.requests.post',return_value=Mock(status_code=200,json=lambda:{'ok':True}));self.post=self.http.start()
        self.line=Mock(return_value=True)
    def tearDown(self):self.http.stop();self.env.stop();self.tmp.cleanup()
    def send(self,**kwargs):return send_trade('entry test',self.line,store=self.store,**kwargs)
    def test_both_channels_and_duplicate_receipt_survives_restart(self):
        self.assertTrue(self.send(event_key='trade:entry'))
        second=Store(self.store.path)
        self.assertFalse(send_trade('entry test',self.line,store=second,event_key='trade:entry'))
        self.post.assert_called_once();self.line.assert_called_once()
        args=self.post.call_args.kwargs
        self.assertEqual(args['json']['chat_id'],'-1001234567')
        self.assertNotIn('allow_paid_broadcast',args['json'])
        self.assertNotIn('parse_mode',args['json'])
        self.assertFalse(args['allow_redirects'])
    def test_distinct_entry_exit_are_both_delivered(self):
        self.send(event_key='entry:1');self.send(event_key='exit:1')
        self.assertEqual(self.post.call_count,2)
    def test_real_position_shape_distinguishes_day_and_exit(self):
        event={'type':'ENTRY','position':{'symbol':'TEST','entry_time':'2026-09-15T09:30:00+08:00'}}
        first=event_identity(event,'same compact text')
        self.assertEqual(first,event_identity(event,'text formatting changed'))
        event['position']['entry_time']='2026-09-16T09:30:00+08:00'
        self.assertNotEqual(first,event_identity(event,'same compact text'))
        exit_event={'type':'EXIT','trade':event['position']}
        self.assertNotEqual(event_identity(event,'same'),event_identity(exit_event,'same'))
    def test_live_engine_wrapper_calls_both_channels(self):
        import ast
        tree=ast.parse((Path(__file__).resolve().parents[1]/'intraday_live.py').read_text(encoding='utf-8'))
        wrapper=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='push_line_text')
        context={'_push_line_only':self.line}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[wrapper],type_ignores=[])),'<wrapper>','exec'),context)
        with patch('easystock_admin.store.Store',return_value=self.store):
            context['push_line_text']('ENTRY',event={'type':'ENTRY','position':{'symbol':'TEST','entry_time':'2026-09-15T09:30:00'}})
        self.post.assert_called_once();self.line.assert_called_once()
    def test_line_failure_does_not_suppress_telegram(self):
        self.line.side_effect=RuntimeError('line unavailable')
        self.assertTrue(self.send())
        self.post.assert_called_once()
    def test_telegram_timeout_does_not_suppress_line_or_leak_token(self):
        self.post.side_effect=requests.Timeout('https://api.telegram.org/bot'+TOKEN)
        capture=io.StringIO()
        with contextlib.redirect_stdout(capture):self.assertTrue(self.send())
        self.assertNotIn(TOKEN,capture.getvalue())
        self.line.assert_called_once()
        self.assertIn('unknown',[r['status'] for r in n.state(self.store)['deliveries']])
        self.send();self.post.assert_called_once()
    def test_telegram_api_rejection_is_failure(self):
        self.post.return_value=Mock(status_code=200,json=lambda:{'ok':False})
        self.assertEqual(telegram_send('test',self.store),'failed')
    def test_disabled_telegram_does_not_affect_line(self):
        n.update(self.store,'telegram','configured',{'push':False,'version':1})
        self.assertTrue(self.send());self.post.assert_not_called()
    def test_disabled_line_does_not_affect_telegram(self):
        n.update(self.store,'line',self.key,{'push':False,'replies':False,'version':1})
        self.assertTrue(self.send());self.line.assert_not_called();self.post.assert_called_once()
    def test_private_target_and_invalid_credentials_rejected(self):
        for override in ({'TELEGRAM_GROUP_ID':'1234567'},{'TELEGRAM_GROUP_ID':'@user'},{'TELEGRAM_BOT_TOKEN':'bad'}):
            with patch.dict(os.environ,override):self.assertEqual(telegram_send('test',self.store),'disabled')
        self.post.assert_not_called()
    def test_latest_entry_gate_applies_to_each_channel(self):
        self.assertTrue(self.send(entry_check=Mock(side_effect=[True,False])))
        self.post.assert_called_once();self.line.assert_not_called()
    def test_stale_entry_never_sends(self):
        self.assertFalse(self.send(entry_check=lambda:False))
        self.post.assert_not_called();self.line.assert_not_called()
    def test_controls_independent_and_conflict_safe(self):
        n.update(self.store,'line',self.key,{'push':False,'replies':True,'version':1})
        self.assertFalse(c.allowed(self.store,GROUP,'trade'))
        self.assertTrue(c.allowed(self.store,GROUP))
        self.assertTrue(n.state(self.store)['groups'][-1]['push'])
        with self.assertRaises(Conflict):n.update(self.store,'line',self.key,{'push':True,'replies':True,'version':1})
    def test_credentials_and_raw_ids_never_returned(self):
        data=str(n.state(self.store))
        for secret in (TOKEN,'-1001234567',GROUP['groupId']):self.assertNotIn(secret,data)
    def test_unknown_or_personal_rows_cannot_be_activated(self):
        unknown=c.observe(self.store,{'type':'group','groupId':'C'+'3'*32})
        with self.assertRaises(Conflict):n.update(self.store,'line',unknown,{'push':True,'replies':True,'version':1})
        self.assertEqual(len(n.state(self.store)['groups']),2)
    def test_api_requires_auth_origin_csrf_and_blocks_binding(self):
        from flask import Flask
        from easystock_admin.web import register_admin,SESSION
        import easystock_admin.store as stores
        origin='https://admin.example.com'
        with patch.dict(os.environ,{'ADMIN_PUBLIC_ORIGIN':origin,'ADMIN_GOOGLE_CLIENT_ID':'test.apps.googleusercontent.com'}),patch.object(stores,'OWNER','owner@example.com'),patch('easystock_admin.web.OWNER','owner@example.com'):
            app=Flask(__name__);register_admin(app,self.store);client=app.test_client()
            path='/admin/notification-groups/telegram/configured';body={'push':False,'version':1}
            self.assertEqual(client.get('/admin/notification-groups',base_url=origin).status_code,403)
            token,csrf=self.store.login({'email':'owner@example.com','email_verified':True,'sub':'1','nonce':'n'},'n')
            client.set_cookie(SESSION,token,domain='admin.example.com',secure=True)
            self.assertEqual(client.put(path,base_url=origin,json=body,headers={'Origin':origin}).status_code,403)
            self.assertEqual(client.put(path,base_url=origin,json=body,headers={'Origin':'https://evil.example','X-CSRF-Token':csrf}).status_code,403)
            headers={'Origin':origin,'X-CSRF-Token':csrf}
            self.assertEqual(client.put(path,base_url=origin,json=body,headers=headers).status_code,200)
            self.assertEqual(client.post('/admin/line-bind',base_url=origin,json={},headers=headers).status_code,403)
            self.assertEqual(client.put(path,base_url=origin,json=body,headers=headers).status_code,409)

if __name__=='__main__':unittest.main()
