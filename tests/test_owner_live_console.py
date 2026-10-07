"""A1-A16: fake broker only; isolated DB, no production account/orders."""
import copy
import json
import os
import sqlite3
import time
from datetime import datetime
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo
from test_admin_order_safety import AdminOrderWebTests, LIVE, ORIGIN, OWNER, order
from easystock_admin.order_service import order_service, OrderService
from easystock_admin.live_console import LiveConsole
from easystock_admin.store import Denied, digest


def broker(positions=None, orders=None):
    return {'source':'shioaji','connected':True,'authenticated':True,'complete':True,
            'account_fingerprint':'f'*24,
            'updated_at':datetime.now(ZoneInfo('Asia/Taipei')).isoformat(),
            'account':{'account_id':'***6543','broker_id':'9A95','person_name':'Owner'},
            'positions':positions or [],'orders':orders or [],'deals':[],
            'pnl':{'unrealized':0,'realized_today':None}}


def position(qty=2000):
    return {'symbol':'2330','name':'Test','quantity':qty,'available_to_sell':qty}


class OwnerConsoleTests(AdminOrderWebTests):
    def setUp(self):
        super().setUp()
        self.data = broker()
        self.mock_sync = patch.object(order_service, 'broker_snapshot', side_effect=lambda: copy.deepcopy(self.data))
        self.mock_sync.start()
        self.mock_login = patch.object(order_service, 'login', return_value=self.data['account'])
        self.mock_login.start()
        self.mock_quote = patch.object(order_service, 'get_quote', side_effect=lambda symbol: {
            'symbol':symbol,'quote_at':datetime.now(ZoneInfo('Asia/Taipei')).isoformat(),
            'bids':[{'price':100,'volume':1}],'asks':[{'price':100.5,'volume':1}]})
        self.mock_quote.start()

    def tearDown(self):
        self.mock_sync.stop();self.mock_login.stop();self.mock_quote.stop()
        super().tearDown()

    def get_live(self):
        return self.client.get('/admin/api/live-console', base_url=ORIGIN)

    def verify(self, **kw):
        value = order(action='SELL', **kw);value.pop('ca_passwd')
        return self.post('api/live-console/sell-verify', value, self.csrf)

    def sell(self, ticket, **kw):
        return order(action='SELL',sell_verification_id=ticket,confirm_sell='SELL',confirm_account='***6543',**kw)

    def test_A1_A2_A3_owner_boundary_and_no_secrets(self):
        good=self.get_live();self.assertEqual(good.status_code,200)
        self.assertEqual(good.json['mode'],'OFF');self.assertFalse(good.json['live_auto_enabled'])
        self.assertEqual(good.json['broker']['account']['account_id'],'***6543')
        self.assertNotIn('9876543',good.get_data(as_text=True))
        with self.store.tx() as db:
            db.execute("UPDATE session_owners SET email='nonowner@example.test'")
        self.assertEqual(self.get_live().status_code,403)
        self.client.delete_cookie('__Host-easystock_admin', domain='admin.example.com')
        self.assertEqual(self.get_live().status_code,401)

    def test_A6_A7_A8_guards_allow_only_mock_activation_skeleton(self):
        self.get_live()
        for enabled,confirmation in [('false',''),('true','')]:
            with patch.dict(os.environ, {'LIVE_ORDERING_ENABLED':enabled,'LIVE_ORDERING_CONFIRMATION':confirmation}):
                self.assertFalse(self.get_live().json['activation_allowed'])
                self.assertEqual(self.post('api/live-console',{'mode':'LIVE AUTO'},self.csrf,'put').status_code,403)
        with patch.dict(os.environ,LIVE):
            self.assertTrue(self.get_live().json['activation_allowed'])
            r=self.post('api/live-console',{'mode':'LIVE AUTO'},self.csrf,'put')
            self.assertEqual(r.status_code,200);self.assertFalse(r.json['execution_engine'])
        self.assertFalse(self.get_live().json['live_auto_enabled'])

    def test_A9_A10_A11_sell_csrf_availability_and_validation(self):
        value=order(action='SELL');value.pop('ca_passwd')
        self.assertEqual(self.post('api/live-console/sell-verify',value).status_code,403)
        self.data=broker([position(500)])
        self.assertEqual(self.verify().status_code,403)
        for kw in [{'price':100.3},{'price':-1},{'quantity':0}]:
            self.assertEqual(self.verify(**kw).status_code,400)
        value['action']='INVALID'
        self.assertEqual(self.post('api/live-console/sell-verify',value,self.csrf).status_code,400)
        self.data['complete']=False;self.data['positions'][0]['available_to_sell']=5000
        self.assertEqual(self.verify().status_code,403)

    def test_A12_A15_A16_two_confirmations_mock_once_paper_isolated(self):
        self.data=broker([position()]);verified=self.verify();self.assertEqual(verified.status_code,200)
        ticket=verified.json['verification_id'];body=self.sell(ticket)
        before=self.rows('SELECT * FROM paper_trade_positions')+self.rows('SELECT * FROM paper_trade_fills')
        with patch.dict(os.environ,LIVE),patch.object(order_service,'place_order',return_value={'order_id':'BROKER1','status':'Submitted'}) as submit:
            denied={**body,'confirm_sell':'no'}
            self.assertEqual(self.post('api/order/place',denied,self.csrf).status_code,403)
            self.assertEqual(self.post('api/order/place',body).status_code,403)
            self.assertEqual(self.post('api/order/place',body,self.csrf).status_code,200)
            self.assertEqual(self.post('api/order/place',body,self.csrf).status_code,409)
            submit.assert_called_once()
        self.assertEqual(before,self.rows('SELECT * FROM paper_trade_positions')+self.rows('SELECT * FROM paper_trade_fills'))
        self.assertEqual(len(self.rows('SELECT * FROM live_trade_orders')),1)
        audits=json.dumps(self.rows('SELECT * FROM live_trade_events')+self.rows('SELECT * FROM audit'))
        self.assertIn(OWNER,audits);self.assertIn('live_sell_verify',audits);self.assertNotIn('secret-pw',audits);self.assertNotIn(ticket,audits)

    def test_A13_A14_mismatch_pauses_auto_kill_never_flattens(self):
        self.data=broker([position()]);self.assertEqual(self.get_live().json['auto_state'],'AUTO PAUSED')
        self.assertEqual(self.get_live().json['reconciliation'],'RECONCILIATION REQUIRED')
        self.assertEqual(self.rows('SELECT * FROM live_trade_positions'),[])
        with patch.object(order_service,'place_order') as submit,patch.dict(os.environ,LIVE):
            self.data=broker();self.get_live()
            self.post('api/live-console',{'mode':'LIVE AUTO'},self.csrf,'put')
            killed=self.post('api/live-console',{'kill':True},self.csrf,'put')
            self.assertFalse(killed.json['live_auto_enabled'])
            with self.assertRaises(Denied):LiveConsole(self.store,order_service,OWNER).authorize_auto()
            submit.assert_not_called()

    def test_ticket_bound_to_session_order_expiry_and_fresh_broker(self):
        self.data=broker([position(3000)]);ticket=self.verify().json['verification_id']
        with patch.dict(os.environ,LIVE),patch.object(order_service,'place_order') as submit:
            self.assertEqual(self.post('api/order/place',self.sell(ticket,price=101),self.csrf).status_code,403)
            with self.store.tx() as db:db.execute('UPDATE live_sell_tickets SET expires=0')
            self.assertEqual(self.post('api/order/place',self.sell(ticket),self.csrf).status_code,403)
            submit.assert_not_called()

    def test_changed_broker_account_fails_closed_even_when_display_suffix_matches(self):
        self.data=broker([position()]);self.get_live()
        self.data['account_fingerprint']='a'*24
        response=self.get_live()
        self.assertFalse(response.json['broker']['complete'])
        self.assertEqual(response.json['broker']['error_code'],'broker_account_mismatch')
        self.assertEqual(self.verify().status_code,403)

    def test_final_submit_guard_rechecks_quote_and_combined_reservations(self):
        self.data=broker([position(2000)]);ticket=self.verify().json['verification_id']
        def mock_execution(**kwargs):
            self.data['positions'][0]['available_to_sell']=500
            kwargs['before_submit']()  # Not a broker submit: exercise adjacent execution guard.
            raise AssertionError('must not reach submit')
        with patch.dict(os.environ,LIVE),patch.object(order_service,'place_order',side_effect=mock_execution):
            response=self.post('api/order/place',self.sell(ticket),self.csrf)
        self.assertEqual(response.status_code,400)
        self.assertEqual(json.loads(self.rows('SELECT body FROM live_trade_orders')[0][0])['status'],'unknown')
        with self.assertRaises(Denied):LiveConsole.check_quote({'quote_at':None})

    def test_verification_ticket_cannot_cross_owner_sessions_or_origins(self):
        self.data=broker([position()]);ticket=self.verify().json['verification_id']
        token,csrf=self.store.login({'email':OWNER,'email_verified':True,'sub':'owner','nonce':'fixture'},'fixture')
        self.client.set_cookie('__Host-easystock_admin',token,domain='admin.example.com')
        with patch.dict(os.environ,LIVE),patch.object(order_service,'place_order') as submit:
            self.assertEqual(self.post('api/order/place',self.sell(ticket),csrf).status_code,403)
            wrong=self.client.put('/admin/api/live-console',base_url=ORIGIN,json={'kill':True},headers={'Origin':'https://evil.example','X-CSRF-Token':csrf})
            self.assertEqual(wrong.status_code,403);submit.assert_not_called()

    def test_reconciliation_compares_order_fields_not_only_identifiers(self):
        from easystock_admin.broker_read import identity
        local={**order(),'status':'submitted','broker_order_id':identity('fixture')};local.pop('ca_passwd');local.pop('client_order_id')
        with self.store.tx() as db:db.execute('INSERT INTO live_trade_orders VALUES(?,?)',('fixture-client-order',json.dumps(local)))
        self.data=broker(orders=[{'order_id':identity('fixture'),'symbol':'2330','side':'BUY','qty':1000,'price':100,'status':'Submitted','filled_qty':0}])
        self.assertEqual(self.get_live().json['reconciliation'],'OK')
        for key,value in [('qty',2000),('price',101),('status','Cancelled'),('filled_qty',100)]:
            self.data['orders'][0][key]=value
            self.assertEqual(self.get_live().json['reconciliation'],'RECONCILIATION REQUIRED')
            self.data['orders'][0].update(qty=1000,price=100,status='Submitted',filled_qty=0)

    def test_parallel_ticket_reservations_cannot_oversell_and_ambiguous_never_retries(self):
        self.data=broker([position(1000)])
        first=self.verify().json['verification_id'];second=self.verify(client_order_id='0123456789abcdef-0002').json['verification_id']
        with patch.dict(os.environ,LIVE),patch.object(order_service,'place_order',side_effect=RuntimeError('password=leaked CA_PATH=/private')) as submit:
            self.assertEqual(self.post('api/order/place',self.sell(first),self.csrf).status_code,400)
            rejected=self.post('api/order/place',self.sell(second,client_order_id='0123456789abcdef-0002'),self.csrf)
            self.assertEqual(rejected.status_code,403);submit.assert_called_once()
        self.assertNotIn('leaked',json.dumps(self.rows('SELECT * FROM audit')))
        self.assertEqual(self.get_live().json['auto_state'],'AUTO PAUSED')


def test_A4_A5_read_adapter_masks_and_refreshes_backend_before_availability():
    from easystock_admin.broker_read import snapshot
    account=NS(account_id='9876543',broker_id='9A95')
    p=NS(id=1,code='2330',quantity=5000,yd_quantity=3000,price=100,last_price=101,pnl=5000,cond='Cash',direction='Buy')
    trade=NS(order=NS(account=account,order_lot='Common',id='secret-broker-id',action='Sell',price=100,quantity=1),
             status=NS(order_quantity=1,deal_quantity=0,cancel_quantity=0,status='Submitted',order_datetime=datetime.now(ZoneInfo('Asia/Taipei')),deals=[]),
             contract=NS(security_type='STK',code='2330'))
    api=Mock(stock_account=account);api.list_positions.return_value=[p];api.list_trades.return_value=[trade];api.list_profit_loss.return_value=[]
    service=OrderService();service.api=api;service.is_logged_in=True;service.account_info={'account_id':account.account_id,'person_id':'A123456789'};service._find_contract=lambda symbol:NS(name='Test')
    result=snapshot(service,NS(Unit=NS(Share='Share')))
    assert result['complete'];assert result['positions'][0]['available_to_sell']==2000
    assert api.mock_calls[0][0]=='update_status'
    for secret in ('9876543','A123456789','secret-broker-id'):assert secret not in json.dumps(result)
    trade.status.order_quantity=0
    assert not snapshot(service,NS(Unit=NS(Share='Share')))['complete']
    trade.status.order_quantity=1
    api.update_status.side_effect=RuntimeError('PASSWORD secret')
    failed=snapshot(service,NS(Unit=NS(Share='Share')));assert not failed['complete'];assert 'secret' not in json.dumps(failed)


def test_broker_submit_not_ready_is_not_retried():
    import easystock_admin.order_service as module
    constants=NS(Action=NS(Buy='Buy',Sell='Sell'),StockOrderLot=NS(Common='Common',IntradayOdd='IntradayOdd'),StockOrderType=NS(ROD='ROD'),StockPriceType=NS(LMT='LMT'))
    service=OrderService();service.api=Mock(stock_account=NS());service.is_logged_in=True;service._last_login_time=time.time();service.account_info={'person_id':'FAKE'}
    service.api.place_order.side_effect=RuntimeError('NotReady accepted but response lost')
    with patch.object(module,'sj',NS(constant=constants)),patch.dict(os.environ,LIVE),patch.object(module.Path,'exists',return_value=True),patch.object(service,'_find_contract',return_value=NS()):
        try:service.place_order('2330','SELL',100,1,False,'fake')
        except RuntimeError:pass
    service.api.place_order.assert_called_once()
