"""Broker-free tests of quota, asynchronous failure and quote continuity."""
from market_data.subscriptions import QuoteSubscriptions


def fixture(**kwargs):
    now, sent = [0], []
    manager = QuoteSubscriptions(lambda *args: sent.append(args), clock=lambda: now[0], **kwargs)
    return manager, now, sent


def ack(manager, symbol, kind='BidAsk', code=200, detail=''):
    topic = 'TIC' if kind == 'Tick' else 'QUO'
    manager.event(code, 16 if code == 200 else 4, f'{detail} {topic}/v1/STK/*/TSE/{symbol}')


def test_170_ticks_plus_20_books_share_190_slots():
    m, _, sent = fixture()
    for n in range(170):
        assert m.request(str(n), 'Tick')
    m.select_books([str(n) for n in range(170)])
    assert m.reserved() == 190
    assert len([r for r in sent if r[1] == 'BidAsk']) == 20
    assert not m.request('171', 'Tick')
    assert not m.request('21', 'BidAsk')


def test_rejection_is_not_success_and_retry_waits():
    m, now, sent = fixture()
    m.request('2330', 'BidAsk')
    assert m.status('2330', 'BidAsk') == 'pending'
    ack(m, '2330', code=400, detail='Max Num Subscriptions Exceeded')
    assert m.status('2330', 'BidAsk') == 'failed' and m.reserved() == 0
    assert not m.request('2330', 'BidAsk')
    now[0] = 31
    assert m.request('2330', 'BidAsk')
    ack(m, '2330')
    assert m.status('2330', 'BidAsk') == 'active'
    assert len(sent) == 2


def test_cancel_holds_slot_until_ack_and_pins_open_position():
    m, now, sent = fixture(book_limit=2)
    m.select_books(['2330', '2317'])
    ack(m, '2330'); ack(m, '2317')
    now[0] = 61
    m.select_books(['2303'], pinned=['2330'])
    assert m.status('2330', 'BidAsk') == 'active'
    assert m.status('2317', 'BidAsk') == 'cancelling'
    assert m.status('2303', 'BidAsk') == 'unselected'
    m.select_books(['2303'], pinned=['2330'])
    assert sent.count(('2317', 'BidAsk', False)) == 1
    ack(m, '2317')
    m.select_books(['2303'], pinned=['2330'])
    assert m.status('2303', 'BidAsk') == 'pending'
    assert m.reserved() == 2


def test_candidate_rank_changes_do_not_reset_book_history_every_three_seconds():
    m, now, sent = fixture(book_limit=1)
    m.select_books(['2330', '2317'])
    now[0] = 3
    m.select_books(['2317', '2330'])
    assert sent == [('2330', 'BidAsk', True)]
    now[0] = 61
    m.select_books(['2317', '2330'])
    assert sent[-1] == ('2330', 'BidAsk', False)


def test_confirmed_absence_can_finish_cancellation_even_with_outer_200():
    m, _, _ = fixture()
    m.request('2330', 'BidAsk'); m.cancel('2330', 'BidAsk')
    ack(m, '2330', detail="Subscription Not Found Response code: '400'")
    assert m.reserved() == 0


def test_cancel_rejection_keeps_slot_and_retries_after_cooldown():
    m, now, sent = fixture(book_limit=1)
    m.request('2330', 'BidAsk'); m.cancel('2330', 'BidAsk')
    ack(m, '2330', code=400)
    assert m.reserved() == 1
    assert not m.request('2317', 'BidAsk')
    now[0] = 31
    m.retry_cancellations()
    assert sent.count(('2330', 'BidAsk', False)) == 2


def test_data_confirmation_does_not_undo_pending_cancellation():
    m, _, _ = fixture()
    m.request('2330', 'BidAsk'); m.confirm_data('2330', 'BidAsk')
    assert m.status('2330', 'BidAsk') == 'active'
    m.cancel('2330', 'BidAsk'); m.confirm_data('2330', 'BidAsk')
    assert m.status('2330', 'BidAsk') == 'cancelling'


def test_uncertain_transport_error_cannot_release_a_possible_subscription():
    def send(*args):
        raise TimeoutError()
    m = QuoteSubscriptions(send)
    assert not m.request('2330', 'BidAsk')
    assert m.reserved() == 1 and m.status('2330', 'BidAsk') == 'pending'


def test_shared_total_includes_nonstock_slots_configured_as_smaller_budget():
    m, _, _ = fixture(limit=2)
    m.request('2330', 'Tick'); m.request('2330', 'BidAsk')
    assert not m.request('2317', 'Tick')


def test_synchronous_broker_rejection_is_returned_as_failure():
    m, _, _ = fixture()
    m.send = lambda symbol, kind, subscribe: ack(m, symbol, kind, code=400)
    assert not m.request('2330', 'BidAsk')


def test_quote_events_are_safe_during_concurrent_reservations():
    from concurrent.futures import ThreadPoolExecutor
    m, _, _ = fixture(limit=10, tick_limit=10)
    with ThreadPoolExecutor(max_workers=8) as workers:
        accepted = list(workers.map(lambda n: m.request(str(n), 'Tick'), range(100)))
    assert sum(accepted) == 10 and m.reserved() == 10
