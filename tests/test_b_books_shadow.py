from datetime import datetime, timedelta
import gzip
import importlib.util
import json
from pathlib import Path
import pytest

from market_data.b_shadow import JournalTail, ShadowComparison, affordable_pool, esun_quote, esun_stamp
from runway_v2.lanes import TPE


NOW = datetime(2026, 10, 13, 9, 3, tzinfo=TPE)


def book(at=NOW, symbol='2330'):
    return {'kind': 'book', 'provider': 'esun', 'symbol': symbol, 'received_at': at.isoformat(),
            'quote': {'datetime': at.isoformat(), 'bid_price': [121 - i * .5 for i in range(5)],
                      'ask_price': [121.5 + i * .5 for i in range(5)],
                      'bid_volume': [20] * 5, 'ask_volume': [6] * 5}}


def test_tail_waits_for_complete_crc_member_and_preserves_sequence(tmp_path):
    path = tmp_path / 'input.gz'
    one = gzip.compress(json.dumps({'seq': 1, 'kind': 'clock'}).encode() + b'\n')
    two = gzip.compress(json.dumps({'seq': 2, 'kind': 'clock'}).encode() + b'\n')
    path.write_bytes(one + two[:15])
    tail = JournalTail(path)
    assert [e['seq'] for e in tail.poll()] == [1]
    assert tail.poll() == []
    with path.open('ab') as source:
        source.write(two[15:])
    assert [e['seq'] for e in tail.poll()] == [2]
    assert tail.poll() == []


def test_tail_can_start_inside_a_previous_member(tmp_path):
    path = tmp_path / 'input.gz'
    chunks = [gzip.compress(json.dumps({'seq': n, 'payload': 'x' * n}).encode() + b'\n') for n in range(1, 20)]
    path.write_bytes(b''.join(chunks))
    tail = JournalTail(path, tail_bytes=150)
    events = tail.poll()
    assert events and events[-1]['seq'] == 19
    assert events[0]['seq'] > 1


def test_tail_fails_closed_on_sequence_gap_or_corruption(tmp_path):
    path = tmp_path / 'gap.gz'
    path.write_bytes(gzip.compress(b'{"seq":1}\n') + gzip.compress(b'{"seq":3}\n'))
    with pytest.raises(ValueError, match='sequence_gap'):
        JournalTail(path).poll()
    path = tmp_path / 'broken.gz'
    raw = bytearray(gzip.compress(b'{"seq":1}\n'))
    raw[-5] ^= 1
    path.write_bytes(raw)
    with pytest.raises(ValueError, match='corrupt'):
        JournalTail(path).poll()


@pytest.mark.parametrize('change', ['partial', 'future', 'stale', 'crossed', 'wrong_source', 'negative_size'])
def test_esun_normalization_fails_closed(change):
    payload = book()
    if change == 'partial':
        payload['quote']['bid_price'].pop()
    elif change == 'future':
        payload['quote']['datetime'] = (NOW + timedelta(seconds=1)).isoformat()
    elif change == 'stale':
        payload['quote']['datetime'] = (NOW - timedelta(seconds=4)).isoformat()
    elif change == 'crossed':
        payload['quote']['ask_price'][0] = 120
    elif change == 'wrong_source':
        payload['provider'] = 'shioaji'
    else:
        payload['quote']['ask_volume'][0] = -1
    with pytest.raises(ValueError):
        esun_quote(payload, NOW)


def test_pool_excludes_unaffordable_lots_without_changing_signal_rules():
    rows = [{'symbol': '2330', 'price': 201, 'previous_close': 200, 'sector': '24'},
            {'symbol': '2317', 'price': 121, 'previous_close': 120, 'sector': '24'},
            {'symbol': '0050', 'price': 10, 'previous_close': 9, 'sector': '24'}]
    assert affordable_pool(rows) == ['2317']


def test_utc_z_bridge_times_work_on_python_310_without_assuming_naive_timezone():
    assert esun_stamp('2026-10-13T01:03:00.000Z') == NOW
    assert esun_stamp('2026-10-13T01:03:00.000') is None
    payload = book()
    payload['quote']['datetime'] = '2026-10-13T01:03:00.000Z'
    payload['received_at'] = '2026-10-13T01:03:00.000Z'
    symbol, normalized = esun_quote(payload, NOW)
    assert symbol == '2330' and normalized['datetime'] == NOW
    assert payload['quote']['datetime'].endswith('Z')  # Original evidence is untouched.


def ready_study(tmp_path):
    study = ShadowComparison(tmp_path, ['2330'], NOW)
    for suite in study.suites.values():
        suite.rows = {'2330': {'symbol': '2330', 'previous_close': 119, 'price': 121.5,
                              'observed_at': NOW.timestamp(), 'sector': '24', 'daytrade_short_allowed': True}}
        for peer in ('2317', '2303'):
            suite.rows[peer] = {'previous_close': 100, 'price': 102, 'sector': '24', 'observed_at': NOW.timestamp()}
        suite.market = {'valid': True, 'gate_action': 'PASS', 'observed_at': NOW.timestamp()}
        for sec, price in ((50, 120), (40, 122), (30, 121.5), (20, 122), (9, 120.5),
                           (7, 121), (5, 121), (3, 121.5), (1, 121.5), (0, 121.5)):
            suite.on_tick('2330', price, NOW - timedelta(seconds=sec), 1, 10)
    study.source_states = {'2330': 'unselected'}
    study.source_clock_at = NOW
    study.last_source_receipt = NOW
    study.ingest_esun({'kind': 'ack', 'symbol': '2330'}, NOW)
    for sec in (10, 6, 0):
        at = NOW - timedelta(seconds=sec)
        study.ingest_esun(book(at), at)
    return study


def test_esun_acks_are_independent_of_unselected_native_manager_and_never_fill(tmp_path):
    study = ready_study(tmp_path)
    try:
        result = study.evaluate(NOW)
        assert result['shioaji_control:B1']['rejects']['未分配五檔額度'] == 1
        assert result['esun_shadow:B1']['ready_signal_events'] == 1
        assert all(not s['execution_allowed'] for s in study.signals)
        assert all(not suite.state['B1']['positions'] and suite.state['B1']['entries'] == 0
                   for suite in study.suites.values())
        assert study.report()['size_units_contract_verified'] is False
        assert study.report()['production_changed'] is False
        coverage = study.coverage(NOW)
        assert coverage['esun_shadow']['fresh_joined_symbols'] == 1
        assert coverage['shioaji_control']['fresh_book_symbols'] == 0
        study.suites['esun_shadow'].market['gate_action'] = 'BLOCK'
        assert study.evaluate(NOW)['esun_shadow:B1']['ready_signal_events'] == 0
        assert study.coverage(NOW)['esun_shadow']['fresh_joined_symbols'] == 1
    finally:
        study.close()


def test_disconnect_or_source_clock_failure_cannot_reuse_good_books(tmp_path):
    study = ready_study(tmp_path)
    try:
        study.ingest_esun({'kind': 'disconnected'}, NOW)
        assert study.evaluate(NOW)['esun_shadow:B1']['ready_signal_events'] == 0
        study.source_failed = True
        result = study.evaluate(NOW)
        assert result['esun_shadow:B1']['rejects']['journal_clock_stale_or_failed'] == 1
    finally:
        study.close()


def test_post_0910_is_not_claimed_as_b1_replay(tmp_path):
    study = ready_study(tmp_path)
    try:
        result = study.evaluate(NOW.replace(minute=10))
        assert result['esun_shadow:B1']['window'] == 'outside_entry_window'
        assert not any(s['lane'] == 'B1' for s in study.signals)
    finally:
        study.close()


def test_native_status_clock_is_not_used_as_tick_receipt_freshness(tmp_path):
    study = ready_study(tmp_path)
    try:
        study.source_clock_at = NOW - timedelta(seconds=10)
        result = study.evaluate(NOW)
        assert result['shioaji_control:B1']['rejects']['native_subscription_snapshot_stale'] == 1
        assert result['esun_shadow:B1']['ready_signal_events'] == 1
        assert result['esun_shadow:B1']['paired_comparison_available'] is False
        assert study.signals[0]['paired_native_status_fresh'] is False
    finally:
        study.close()


def test_source_receipt_future_is_not_retimestamped(tmp_path):
    study = ShadowComparison(tmp_path, ['2330'], NOW)
    try:
        with pytest.raises(ValueError, match='receipt'):
            study.ingest_source({'received_at': (NOW + timedelta(seconds=1)).isoformat()}, NOW)
    finally:
        study.close()


def test_driver_rejects_output_in_sources_or_existing_directory(tmp_path):
    path = Path(__file__).resolve().parents[1] / 'deploy/run_b_books_shadow.py'
    spec = importlib.util.spec_from_file_location('shadow_driver', path)
    driver = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(driver)
    args = ['--journal', str(tmp_path / 'source.gz'), '--bridge', str(tmp_path / 'bridge.cjs')]
    with pytest.raises(SystemExit):
        driver.parse(args + ['--output', str(tmp_path)])
    with pytest.raises(SystemExit):
        driver.parse(args + ['--output', str(path.parent / 'results')])
