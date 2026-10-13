from datetime import datetime,timedelta
from types import SimpleNamespace
import threading
from unittest.mock import Mock

import pytest
from market_data.dual_books import DualBooks
from market_data.health import TPE,atomic
from runway_v2.lanes import LaneSuite
from runway_v2.replay import apply

NOW=datetime(2026,10,13,9,3,tzinfo=TPE)


def quote(at=NOW,volume=10):
    return dict(datetime=at.isoformat(),received_at=at.isoformat(),
        bid_price=[100-i*.5 for i in range(5)],ask_price=[100.5+i*.5 for i in range(5)],
        bid_volume=[volume]*5,ask_volume=[volume]*5)


@pytest.fixture
def router(tmp_path):
    suite=LaneSuite(tmp_path/'private.sqlite',sender=lambda *_:None,offline=True)
    suite.advance(NOW)
    native=SimpleNamespace(status=Mock(return_value='active'),select_books=Mock())
    r=DualBooks(native,suite,tmp_path,esun_size_unit='lots')
    r.requested=['2330']
    yield r
    suite.worker.shutdown(wait=True)


def publish(r,q=None,epoch='first',connected=True,at=NOW):
    atomic(r.directory/'esun-books.json',dict(schema_version=1,provider='esun',epoch=epoch,
        connected=connected,generated_at=at.isoformat(),states={'2330':'active'},books={'2330':q or quote(at)}))


def test_primary_and_native_backup_never_mix_history(router):
    r=router;r.native_quote('2330',quote(),NOW)
    assert r.suite.books['2330'][-1]['source']=='shioaji'
    publish(r);r.poll(NOW)
    assert len(r.suite.books['2330'])==1 and r.suite.books['2330'][-1]['source']=='esun'
    publish(r,connected=False);r.poll(NOW)
    assert len(r.suite.books['2330'])==1 and r.suite.books['2330'][-1]['source']=='shioaji'


def test_epoch_change_resets_continuity(router):
    r=router;publish(r);r.poll(NOW)
    publish(r,quote(NOW+timedelta(seconds=1)),epoch='second',at=NOW+timedelta(seconds=1))
    r.poll(NOW+timedelta(seconds=1))
    assert len(r.suite.books['2330'])==1
    assert r.suite.books['2330'][-1]['source_epoch']=='second'


def test_unknown_unit_never_enters_depth(router):
    r=router;r.unit=None;r.native.status.return_value='unselected';publish(r);r.poll(NOW)
    assert '2330' not in r.suite.books
    assert r.status('2330')=='unit_unverified'


def test_shares_are_normalized_only_with_explicit_contract(router):
    r=router;r.unit='shares';publish(r,quote(volume=1000));r.poll(NOW)
    assert r.suite.books['2330'][-1]['av']==1


@pytest.mark.parametrize('mutate',[
    lambda q:q.update(datetime=(NOW-timedelta(seconds=4)).isoformat()),
    lambda q:q.update(received_at=(NOW+timedelta(seconds=1)).isoformat()),
    lambda q:q.update(bid_price=[100]*5),
    lambda q:q.update(ask_volume=[-1]*5),
    lambda q:q.update(ask_price=[None]*5),
    lambda q:q.update(bid_volume=[True]*5),
    lambda q:q.update(ask_volume=[10]*4),
    lambda q:q.update(simtrade=True),
])
def test_bad_esun_data_never_becomes_a_book(router,mutate):
    r=router;r.native.status.return_value='unselected';q=quote();mutate(q);publish(r,q);r.poll(NOW)
    assert '2330' not in r.suite.books


def test_worker_file_age_and_all_source_loss_clear_books(router):
    r=router;r.native.status.return_value='unselected';publish(r);r.poll(NOW)
    r.poll(NOW+timedelta(seconds=3))
    assert '2330' not in r.suite.books
    assert r.status('2330')=='unselected'


def test_held_books_request_renews_without_radar(router):
    r=router;r.suite.state['B1']['positions']['2330']={}
    r.poll(NOW)
    import json
    assert json.loads((r.directory/'b-books-request.json').read_text())['pinned']==['2330']


def test_replay_book_reset_and_provenance(router):
    r=router;r.native_quote('2330',quote(),NOW)
    apply(r.suite,{'kind':'book_reset','data':{'symbol':'2330','reason':'provider_or_epoch_changed','source':'esun','source_epoch':'new'}})
    assert '2330' not in r.suite.books


def test_unit_reason_rejects_signal(router):
    r=router;r.suite._observation_statuses={'2330':'unit_unverified'}
    assert r.suite._observation_check('2330',NOW)==(None,'五檔數量單位未確認')


def test_native_status_and_good_cached_esun_quote_cannot_extend_dead_worker(router):
    r=router;publish(r);r.poll(NOW)
    r.native_quote('2330',quote(NOW+timedelta(seconds=2.5)),NOW+timedelta(seconds=2.5))
    assert r.suite.books['2330'][-1]['source']=='shioaji'


def test_sdk_decimal_vectors_are_valid_native_backup(router):
    from decimal import Decimal
    q=quote()
    for key in ('bid_price','ask_price','bid_volume','ask_volume'):q[key]=[Decimal(str(x)) for x in q[key]]
    router.native_quote('2330',q,NOW)
    assert router.suite.books['2330'][-1]['source']=='shioaji'


@pytest.mark.parametrize('scale,expected',[(1,'lots'),(1000,'shares')])
def test_three_exact_distinct_native_pairs_unlock_only_that_symbol(router,scale,expected):
    r=router;r.unit=None
    for i in range(3):
        at=NOW+timedelta(seconds=i)
        r.native_quote('2330',quote(at,10+i),at)
        publish(r,quote(at,(10+i)*scale),at=at);r.poll(at)
        if i<2:assert r.suite.books['2330'][-1]['source']=='shioaji'
    assert r.verified_units=={'2330':expected}
    assert r.suite.books['2330'][-1]['source']=='esun'
    assert r.suite.books['2330'][-1]['av']==12
    assert len(r.suite.books['2330'])==1


def test_repeated_same_pair_cannot_manufacture_unit_verification(router):
    r=router;r.unit=None;r.native_quote('2330',quote(),NOW);publish(r)
    for _ in range(10):r.poll(NOW)
    assert r.verified_units=={} and len(r.unit_samples['2330'])==1


def test_unit_conflict_and_reconnect_revoke_per_symbol_calibration(router):
    r=router;r.unit=None
    for i in range(3):
        at=NOW+timedelta(seconds=i);r.native_quote('2330',quote(at,10+i),at)
        publish(r,quote(at,10+i),at=at);r.poll(at)
    assert r.verified_units['2330']=='lots'
    at=NOW+timedelta(seconds=3);r.native_quote('2330',quote(at,13),at)
    publish(r,quote(at,99),at=at);r.poll(at)
    assert r.verified_units=={} and r.suite.books['2330'][-1]['source']=='shioaji'
    assert r.counters['unit_conflict']==1
    publish(r,quote(at,13),epoch='new',at=at);r.poll(at)
    assert len(r.unit_samples['2330'])==1


def test_calibration_slots_rotate_but_exit_backup_is_pinned(router):
    r=router;r.esun_states={'2330':'active'};r.verified_units={'2330':'lots'}
    r.select(['2330','2317'],{'2330'},NOW)
    r.native.select_books.assert_called_once_with(['2317'],{'2330'})


def test_b1_uses_verified_esun_even_when_native_slot_is_unselected(router):
    r=router;r.unit=None;s=r.suite
    s.market={'valid':True,'gate_action':'PASS','observed_at':NOW.timestamp()}
    s.rows={'2330':{'symbol':'2330','name':'synthetic','previous_close':119,
                   'price':121.5,'sector':'01','observed_at':NOW.timestamp()},
            'P1':{'previous_close':100,'price':102,'sector':'01','observed_at':NOW.timestamp()},
            'P2':{'previous_close':100,'price':102,'sector':'01','observed_at':NOW.timestamp()}}
    for sec,p in [(50,120),(40,122),(30,121.5),(20,122),(9,120.5),(7,121),(5,121),(3,121.5),(1,121.5),(0,121.5)]:
        s.on_tick('2330',p,NOW-timedelta(seconds=sec),1,10)
    for sec in range(10,-1,-1):
        at=NOW-timedelta(seconds=sec)
        q=dict(datetime=at.isoformat(),received_at=at.isoformat(),bid_price=[121-i*.5 for i in range(5)],
               ask_price=[121.5+i*.5 for i in range(5)],bid_volume=[20+sec]*5,ask_volume=[5]*5)
        if sec>=8:r.native_quote('2330',q,at)
        if sec==7:r.native.status.return_value='unselected'
        publish(r,q,at=at);r.poll(at)
    s.register_subscription_status(r.status);s.advance(NOW)
    assert s.state['B1']['entries']==1
    assert s.state['B1']['positions']['2330']['book_source']=='esun'
    assert r.native.status('2330','BidAsk')=='unselected'


def test_ipc_write_failure_preserves_native_exit_books(router,monkeypatch):
    r=router;r.native_quote('2330',quote(),NOW)
    def fail(*_a,**_k):raise PermissionError('synthetic')
    monkeypatch.setattr('market_data.dual_books.atomic',fail)
    r.poll(NOW)
    r.select(['2330'],{'2330'},NOW)
    assert r.suite.books['2330'][-1]['source']=='shioaji'
    assert r.counters['ipc_write_failed']==2
    r.native.select_books.assert_called_once_with(['2330'],{'2330'})
