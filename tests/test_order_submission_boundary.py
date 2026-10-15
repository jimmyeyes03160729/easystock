"""Mock SDK only: never contacts a broker or submits a real order."""
from types import SimpleNamespace as NS
from unittest.mock import Mock,patch
import time
import pytest
from easystock_admin.order_service import OrderService,OrderNotSubmitted

LIVE={'LIVE_ORDERING_ENABLED':'1','LIVE_ORDERING_CONFIRMATION':'I_UNDERSTAND_LIVE_ORDERING'}

@pytest.fixture
def service(monkeypatch,tmp_path):
    from easystock_admin import order_service as module
    for k,v in LIVE.items():monkeypatch.setenv(k,v)
    ca=tmp_path/'fake.pfx';ca.write_bytes(b'not-a-real-certificate');monkeypatch.setattr(module,'CA_DEFAULT_PATH',str(ca))
    monkeypatch.setattr(module,'sj',NS(constant=NS(Action=NS(Buy='Buy',Sell='Sell'),StockOrderLot=NS(Common='Common',IntradayOdd='IntradayOdd'),OrderType=NS(ROD='ROD'),StockPriceType=NS(LMT='LMT'))))
    s=OrderService();s.api=Mock(stock_account=NS());s.is_logged_in=True;s._last_login_time=time.time();s.account_info={'person_id':'FAKE'}
    s.api.activate_ca.return_value=True;s._find_contract=Mock(return_value=NS(code='2330'))
    s.api.place_order.return_value=NS(order=NS(id='TEST-ORDER'),status=NS(status='Submitted'))
    return s

def place(s,**kw):return s.place_order('2330','BUY',100,1,False,'TEST-SECRET',**kw)

def test_certificate_false_or_error_never_reaches_broker(service):
    for failure in (False,RuntimeError('401 token TEST-SECRET')):
        service.api.activate_ca.side_effect=failure if isinstance(failure,Exception) else None
        service.api.activate_ca.return_value=False
        with pytest.raises(OrderNotSubmitted) as exc:place(service)
        assert exc.value.stage=='certificate' and 'TEST-SECRET' not in str(exc.value)
        service.api.place_order.assert_not_called()
    assert not service.is_logged_in

def test_missing_contract_and_build_failure_are_definitely_not_submitted(service):
    service._find_contract.return_value=None
    with pytest.raises(OrderNotSubmitted) as exc:place(service)
    assert exc.value.stage=='contract';service.api.place_order.assert_not_called()
    service._find_contract.return_value=NS();service.api.Order.side_effect=ValueError('sensitive payload')
    with pytest.raises(OrderNotSubmitted) as exc:place(service)
    assert exc.value.stage=='order_build' and 'sensitive' not in str(exc.value)

def test_pre_submit_failure_is_not_sent_but_submission_error_is_never_retried(service):
    with pytest.raises(OrderNotSubmitted):place(service,before_submit=Mock(side_effect=RuntimeError('blocked')))
    service.api.place_order.assert_not_called()
    service.api.place_order.side_effect=RuntimeError('401 or timeout after send')
    with pytest.raises(RuntimeError) as exc:place(service)
    assert not isinstance(exc.value,OrderNotSubmitted)
    service.api.place_order.assert_called_once()
    assert not service.is_logged_in

def test_missing_receipt_is_unknown_and_ack_is_not_a_fill(service):
    service.api.place_order.return_value=None
    with pytest.raises(RuntimeError) as exc:place(service)
    assert not isinstance(exc.value,OrderNotSubmitted)
    service.api.place_order.return_value=NS(order=NS(id='ACK'),status=NS(status='Submitted'))
    assert place(service)['status']=='Submitted'

def test_failed_refresh_does_not_use_dead_session(service):
    service._last_login_time=0;service.reconnect=Mock(side_effect=RuntimeError('401'))
    with pytest.raises(OrderNotSubmitted) as exc:place(service)
    assert exc.value.stage=='ready' and exc.value.code=='broker_auth_rejected'
    service.api.place_order.assert_not_called()

def test_explicit_login_refreshes_native_cached_token_when_supported(monkeypatch):
    import easystock_admin.order_service as module
    class API:
        stock_account=NS(person_name='Test',person_id='FAKE',account_id='1234567',broker_id='TEST')
        set_default_account=Mock()
        def login(self,api_key,secret_key,force_refresh=False):self.refreshed=force_refresh
    api=API();monkeypatch.setenv('SJ_API_KEY','test-key');monkeypatch.setenv('SJ_SECRET_KEY','test-secret')
    factory=Mock(return_value=api)
    monkeypatch.setattr(module,'sj',NS(Shioaji=factory));monkeypatch.setattr(module.time,'sleep',lambda _:None)
    s=OrderService();s.login()
    assert api.refreshed and s.is_logged_in
    factory.assert_called_once_with(simulation=False)
