from datetime import datetime, timedelta, timezone
from deploy.audit_research_replay import replay, audit, GATES
import sqlite3

AT = datetime(2026,10,1,10,33,43,tzinfo=timezone(timedelta(hours=8)))
SECOND = AT.replace(hour=12,minute=7,second=1)


def predicate(at, accepted=True):
    return {'kind':'predicate','symbol':'3189','at':at.isoformat(),'price':1015,
            'quote_at':at.isoformat(),'decision_mode':'model',
            'gates':{gate:accepted for gate in GATES},
            'model_decision':{'active':True,'evaluated':True,'approved':True,'accepted':True,
                              'probability':.7,'threshold':.6}}


def tick(at, price):
    return {'kind':'tick','symbol':'3189','at':at.isoformat(),'price':price}


def timeline(events):
    return {'coverage':{'complete_ticks':True,'complete_predicates':True,
                        'complete_technical_decisions':True},'events':events}


def test_sparse_samples_never_become_fake_historical_trades(tmp_path):
    result = audit(tmp_path,'2026-10-01','3189')
    assert result['status'] == 'cannot_reconstruct_without_lookahead'
    assert result['historical_trades_written'] == 0
    assert not (tmp_path/'research.sqlite').exists()
    assert replay({'events':[predicate(AT)]},'2026-10-01','3189')['status'] == result['status']


def test_first_still_open_at_1207_is_one_episode():
    result = replay(timeline([predicate(AT),tick(AT+timedelta(seconds=10),1020),
                              predicate(SECOND),tick(AT.replace(hour=12,minute=55),1020)]),
                    '2026-10-01','3189')
    assert result['status'] == 'deterministic_read_only_replay'
    assert result['closed_count'] == 1
    assert result['episodes'][0]['entry_time'] == AT.isoformat()


def test_closed_rearmed_first_allows_second_episode():
    result = replay(timeline([predicate(AT),tick(AT+timedelta(minutes=1),1000),
                              predicate(SECOND-timedelta(seconds=10),False),predicate(SECOND),
                              tick(SECOND+timedelta(minutes=1),1030)]),'2026-10-01','3189')
    assert result['status'] == 'deterministic_read_only_replay'
    assert result['closed_count'] == 2
    assert result['historical_trades_written'] == result['paper_fills_written'] == 0


def test_closed_without_false_setup_is_not_second_episode():
    result = replay(timeline([predicate(AT),tick(AT+timedelta(minutes=1),1000),predicate(SECOND)]),
                    '2026-10-01','3189')
    assert result['closed_count'] == 1


def test_future_bar_or_unordered_tick_is_not_reconstructed():
    future = {'kind':'strategy','symbol':'3189','at':(AT+timedelta(minutes=1)).isoformat(),
              'bar_completed_at':(AT+timedelta(minutes=5)).isoformat(),
              'result':{'vetoes':['跌破VWAP'],'price':1010}}
    for events in ([predicate(AT),future], [predicate(AT),tick(AT-timedelta(seconds=1),1000)]):
        assert replay(timeline(events),'2026-10-01','3189')['status'] == 'cannot_reconstruct_without_lookahead'


def test_rejected_model_cannot_be_attested_as_accepted():
    row = predicate(AT)
    row['model_decision']['probability'] = .4
    assert replay(timeline([row]),'2026-10-01','3189')['status'] == 'cannot_reconstruct_without_lookahead'


def test_wallet_skip_observation_is_read_only_and_never_proves_replayed_entry(tmp_path):
    path = tmp_path/'wallet.sqlite'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE paper_trade_events (date TEXT,symbol TEXT,action TEXT,time_str TEXT,price REAL,reason TEXT,created_at REAL)')
        db.execute("INSERT INTO paper_trade_events VALUES('2026-10-01','3189','略過','10:33:43',1015,'可用現金 199652 不足',1)")
    before = path.read_bytes()
    result = audit(tmp_path,'2026-10-01','3189',path)
    assert path.read_bytes() == before
    assert result['status'] == 'cannot_reconstruct_without_lookahead'
    assert result['paper_cash_skip_count'] == 1
    assert result['paper_cash_skip_observations'][0]['at'] == '10:33:43'
    assert '199652' not in str(result)
