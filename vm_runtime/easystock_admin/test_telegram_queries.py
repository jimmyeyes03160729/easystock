import os,sys,time,tempfile,unittest,json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from easystock_admin.store import Store
from easystock_admin import notifications as n
from telegram_queries import register_bridge,bridge_secret,enabled
import telegram_stock_bot as bot

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.env=patch.dict(os.environ,{'TELEGRAM_BOT_TOKEN':'123:'+'x'*35,'TELEGRAM_GROUP_ID':'-1001234567','TELEGRAM_CONFIG_FILE':str(self.root/'absent'),'LINE_CHART_DIR':str(self.root)});self.env.start()
        self.store=Store(self.root/'db',{'min_price':1,'max_price':100,'max_gain_pct':5})
        with self.store.tx() as db:db.execute('UPDATE telegram_policy SET replies=1')
        self.api=patch.object(bot,'api',return_value={});self.send=self.api.start()
    def tearDown(self):self.api.stop();self.env.stop();self.tmp.cleanup()
    def update(self,uid=1,**message):
        return {'update_id':uid,'message':{'message_id':8,'date':time.time(),'chat':{'id':-1001234567,'type':'supergroup'},'from':{'id':1,'is_bot':False},'text':'P大盤',**message}}
    def test_wrong_group_bot_stale_ignored_before_query(self):
        with patch.object(bot.requests,'post') as post:
            for uid,kwargs in enumerate([{'chat':{'id':-10022222,'type':'supergroup'}},{'from':{'is_bot':True}},{'date':time.time()-600}],1):bot.handle_update(self.store,self.update(uid,**kwargs))
            post.assert_not_called();self.send.assert_not_called()
    def test_private_chat_query_and_start(self):
        with patch.object(bot.requests,'post',return_value=Mock(status_code=200,json=lambda:{'messages':[{'type':'text','text':'private quote'}]})) as post:
            bot.handle_update(self.store,self.update(uid=10,chat={'id':12345,'type':'private'},text='P2330'))
            post.assert_called_once();self.send.assert_called_once()
            self.assertEqual(self.send.call_args.args[1]['chat_id'],'12345')
        self.send.reset_mock()
        bot.handle_update(self.store,self.update(uid=11,chat={'id':12345,'type':'private'},text='/start'))
        self.send.assert_called_once()
        self.assertIn('歡迎使用',self.send.call_args.args[1]['text'])
    def test_update_dedup_and_offset_persist(self):
        with patch.object(bot.requests,'post',return_value=Mock(status_code=200,json=lambda:{'messages':[{'type':'text','text':'quote'}]})) as post:
            bot.handle_update(self.store,self.update());bot.handle_update(Store(self.store.path),self.update())
            post.assert_called_once();self.send.assert_called_once()
            self.assertEqual(self.send.call_args.args[1]['chat_id'],'-1001234567')
    def test_reply_off_independent_of_push(self):
        n.update(self.store,'telegram','configured',{'push':True,'replies':False,'version':1})
        with patch.object(bot.requests,'post') as post:
            bot.handle_update(self.store,self.update());post.assert_not_called()
        self.assertTrue(n.state(self.store)['groups'][-1]['push'])
    def test_photo_reuses_png_and_flex_buttons(self):
        png=b'\x89PNG\r\n\x1a\nTEST';(self.root/'P_market.png').write_bytes(png)
        message={'type':'flex','altText':'加權指數','contents':{'hero':{'url':'https://host/charts/P_market.png'},'footer':{'contents':[{'action':{'type':'message','label':'K線','text':'K大盤'}}]}}}
        self.assertEqual(bot.send_messages(self.store,'-1001234567',[message]),1)
        self.assertEqual(self.send.call_args.args[0],'sendPhoto')
        self.assertEqual(self.send.call_args.kwargs['files']['photo'][1],png)
        markup=json.loads(self.send.call_args.args[1]['reply_markup'])
        self.assertEqual(markup['inline_keyboard'][0][0]['callback_data'],'q:K大盤')
    def test_missing_invalid_chart_not_uploaded(self):
        for url in ('https://evil/secret.env','file:///etc/passwd','https://host/nonexistent.png'):
            with self.assertRaises((ValueError,FileNotFoundError)):bot.image_bytes({'type':'image','originalContentUrl':url})
        self.send.assert_not_called()
    def test_callback_uses_same_query(self):
        update={'update_id':1,'callback_query':{'id':'c','from':{'is_bot':False},'data':'q:K大盤','message':self.update()['message']}}
        with patch.object(bot.requests,'post',return_value=Mock(status_code=200,json=lambda:{'messages':[]})) as post:
            bot.handle_update(self.store,update)
            self.assertEqual(post.call_args.kwargs['json']['text'],'K大盤')
            self.assertEqual(self.send.call_args.args[0],'answerCallbackQuery')
    def test_bridge_auth_group_filter_and_sanitized_errors(self):
        from flask import Flask
        app=Flask(__name__);parse=Mock(return_value=SimpleNamespace(kind='P'));handle=Mock(return_value=[{'type':'text','text':'查詢失敗 secret'}])
        register_bridge(app,self.store,parse,handle);client=app.test_client()
        body={'group':'-1001234567','text':'P大盤'}
        self.assertEqual(client.post('/internal/telegram-query',json=body).status_code,403)
        headers={'X-Telegram-Bridge':bridge_secret()}
        self.assertEqual(client.post('/internal/telegram-query',json={**body,'group':'1'},headers=headers).json['messages'],[])
        response=client.post('/internal/telegram-query',json=body,headers=headers)
        self.assertNotIn('secret',str(response.json));handle.assert_called_once()
        for _ in range(15):response=client.post('/internal/telegram-query',json=body,headers=headers)
        self.assertEqual(response.status_code,429)
    def test_bridge_disabled_does_not_fetch(self):
        from flask import Flask
        app=Flask(__name__);parse=Mock();handle=Mock();register_bridge(app,self.store,parse,handle)
        with self.store.tx() as db:db.execute('UPDATE telegram_policy SET replies=0')
        response=app.test_client().post('/internal/telegram-query',json={'group':'-1001234567','text':'#台積電'},headers={'X-Telegram-Bridge':bridge_secret()})
        self.assertEqual(response.json['messages'],[]);parse.assert_not_called()

if __name__=='__main__':unittest.main()
