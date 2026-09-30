"""Deterministic Fugle scheduled-run health, without network or credentials."""

import json
import ast
from pathlib import Path
import sys
import types
from datetime import date, datetime, timedelta
from unittest.mock import Mock, patch

import pytest

from market_data.fugle_pipeline import evaluate, record_success, schedule
from market_data.health import TPE, aggregate

NOW = datetime(2026, 10, 1, 1, 0, tzinfo=TPE)
GENERATED = '2026-09-30T13:28:20+08:00'
COMPLETED = '2026-09-30T13:30:00+08:00'


def calendar(day):
    return day.weekday() < 5 and day != date(2026, 9, 28), 'calendar', {}


def evidence(**changes):
    return {**dict(schema_version=1, provider='fugle', status='success', scan_date='2026-09-30',
                   completed_at=COMPLETED, data_generated_at=GENERATED,
                   source='github_actions', workflow='intraday-picks',
                   run_id='36673457508', run_attempt=1, commit_sha='a' * 40), **changes}


def payload(**changes):
    return {**dict(scan_date='2026-09-30', source='legacy_fugle_overnight',
                   overnight_source='fugle', generated_at=GENERATED,
                   candidate_symbols=0, scanned_symbols=0, overnight_candidates=[]), **changes}


def test_last_due_trading_day_success_is_online_even_after_midnight(tmp_path):
    result = evaluate(evidence(), payload(), NOW, calendar)
    assert result['status'] == 'ONLINE'
    assert result['kind'] == 'scheduled'
    assert result['expected_scan_date'] == '2026-09-30'
    assert result['next_due_at'] == '2026-10-01T13:35:00+08:00'
    assert result['run_id'] == '36673457508'
    (tmp_path / 'fugle.json').write_text(json.dumps(result))
    public, private = aggregate(NOW, 'CLOSED', tmp_path)
    assert public['providers']['fugle'] == {'status': 'ONLINE', 'last_checked_at': NOW.isoformat()}
    assert private['providers']['fugle']['workflow_source'] == 'github_actions'
    assert 'run_id' not in json.dumps(public)


def test_zero_candidates_still_means_a_successful_scan():
    assert evaluate(evidence(), payload(candidate_symbols=0, scanned_symbols=0), NOW, calendar)['status'] == 'ONLINE'


def test_whole_fugle_pool_failure_is_not_a_successful_scan():
    broken = payload(candidate_symbols=50, scanned_symbols=0)
    assert evaluate(evidence(), broken, NOW, calendar)['status'] == 'DEGRADED'
    environment = {'GITHUB_ACTIONS': 'true', 'GITHUB_RUN_ID': '1',
                   'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_SHA': 'a' * 40,
                   'GITHUB_EVENT_NAME': 'schedule'}
    with pytest.raises(ValueError):
        record_success(Mock(), broken, datetime(2026, 9, 30, 13, 30, tzinfo=TPE), environment)


def test_payload_alone_is_not_success():
    result = evaluate(None, payload(), NOW, calendar)
    assert result['status'] == 'UNKNOWN'


@pytest.mark.parametrize('changed', [
    {'scan_date': '2026-09-29'},
    {'source': 'other'},
    {'overnight_source': 'other'},
    {'generated_at': '2026-09-30T13:29:00+08:00'},
])
def test_payload_mismatch_is_degraded(changed):
    assert evaluate(evidence(), payload(**changed), NOW, calendar)['status'] == 'DEGRADED'


@pytest.mark.parametrize('bad_evidence,bad_payload', [
    ({'completed_at': '2026-10-01T01:01:00+08:00'}, {}),
    ({'data_generated_at': '2026-10-01T01:01:00+08:00'}, {}),
    ({}, {'generated_at': '2026-10-01T01:01:00+08:00'}),
])
def test_future_timestamps_are_degraded(bad_evidence, bad_payload):
    result = evaluate(evidence(**bad_evidence), payload(**bad_payload), NOW, calendar)
    assert (result['status'], result['error_code']) == ('DEGRADED', 'future_timestamp')


def test_today_is_not_due_before_deadline_but_is_due_after():
    before = datetime(2026, 10, 1, 13, 0, tzinfo=TPE)
    after = datetime(2026, 10, 1, 13, 36, tzinfo=TPE)
    assert schedule(before, calendar)[0] == date(2026, 9, 30)
    assert evaluate(evidence(), payload(), before, calendar)['status'] == 'ONLINE'
    assert schedule(after, calendar)[0] == date(2026, 10, 1)
    result = evaluate(evidence(), payload(), after, calendar)
    assert (result['status'], result['error_code']) == ('DEGRADED', 'scan_overdue')


def test_explicit_failure_is_offline_only_for_expected_run():
    result = evaluate(evidence(status='failure'), payload(), NOW, calendar)
    assert (result['status'], result['error_code']) == ('OFFLINE', 'explicit_failure')


def test_weekend_and_calendar_holiday_do_not_require_a_run():
    friday = datetime(2026, 9, 25, 13, 29, tzinfo=TPE)
    previous = date(2026, 9, 24)
    saturday = datetime(2026, 10, 3, 14, 0, tzinfo=TPE)
    assert schedule(friday, calendar)[0] == previous
    assert schedule(saturday, calendar)[0] == date(2026, 10, 2)


def test_calendar_failure_does_not_claim_success():
    result = evaluate(evidence(), payload(), NOW, Mock(side_effect=RuntimeError('failure')))
    assert (result['status'], result['error_code']) == ('UNKNOWN', 'calendar_error')


def test_stale_vm_cache_cannot_keep_public_online(tmp_path):
    old = NOW - timedelta(minutes=4)
    (tmp_path / 'fugle.json').write_text(json.dumps(evaluate(evidence(), payload(), old, calendar)))
    public, _ = aggregate(NOW, 'CLOSED', tmp_path)
    assert public['providers']['fugle']['status'] == 'UNKNOWN'


def test_record_success_writes_allowlisted_private_evidence_only_after_scan():
    root = Mock()
    run_time = datetime(2026, 9, 30, 13, 30, tzinfo=TPE)
    environment = {'GITHUB_ACTIONS': 'true', 'GITHUB_RUN_ID': '36673457508',
                   'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_SHA': 'a' * 40,
                   'GITHUB_EVENT_NAME': 'schedule', 'FUGLE_API_KEY': 'never-publish-me'}
    assert record_success(root, payload(), run_time, environment)
    sent = root.child.return_value.child.return_value.set.call_args.args[0]
    assert sent['status'] == 'success'
    assert sent['scan_date'] == '2026-09-30'
    assert sent['data_generated_at'] == GENERATED
    assert 'never-publish-me' not in json.dumps(sent)
    assert list(root.mock_calls)[-1].args == (sent,)


def test_record_success_rejects_stale_or_untrusted_invocation():
    root = Mock()
    assert record_success(root, payload(), NOW, {}) is False
    root.assert_not_called()
    environment = {'GITHUB_ACTIONS': 'true', 'GITHUB_RUN_ID': '1',
                   'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_SHA': 'a' * 40,
                   'GITHUB_EVENT_NAME': 'schedule'}
    with pytest.raises(ValueError):
        record_success(root, payload(), NOW, environment)
    root.assert_not_called()


def test_private_metadata_is_strictly_allowlisted():
    poisoned = evidence(api_key='secret', account='private', run_id='<script>',
                        commit_sha='bad', exception='token=secret')
    result = evaluate(poisoned, payload(), NOW, calendar)
    assert result['status'] == 'ONLINE'
    assert all(value not in json.dumps(result) for value in ('secret', '<script>', 'token=', 'private'))


def test_market_holiday_scan_returns_before_firebase_write():
    tree = ast.parse((Path(__file__).resolve().parents[1] / 'scan_intraday.py').read_text())
    main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'main')
    holiday = datetime(2026, 9, 28, 13, 20, tzinfo=TPE)
    clock = type('Clock', (), {'now': staticmethod(lambda _: holiday)})
    init_firebase = Mock()
    namespace = {'ENABLE_OVERNIGHT': True, 'FUGLE_API_KEY': 'test-only',
                 'datetime': clock, 'TPE': TPE, 'init_firebase': init_firebase}
    exec(compile(ast.Module(body=[main], type_ignores=[]), '<scanner>', 'exec'), namespace)
    market_calendar = types.ModuleType('market_calendar')
    market_calendar.is_market_open = lambda _: (False, 'holiday', {})
    with patch.dict(sys.modules, {'market_calendar': market_calendar}):
        namespace['main']()
    init_firebase.assert_not_called()


def test_vm_publisher_uses_private_pipeline_evidence_without_fugle_key(tmp_path, monkeypatch):
    from market_data import publish
    monkeypatch.setenv('EASYSTOCK_MARKET_DATA_DIR', str(tmp_path))
    monkeypatch.delenv('FUGLE_API_KEY', raising=False)
    database = {}

    def reference(path):
        ref = Mock()
        ref.get.return_value = {
            '/market_data/provider_evidence/fugle': evidence(),
            '/market_data/intraday_picks': payload(),
            '/market_data/active_release': 'release-fixture',
        }.get(path)
        ref.set.side_effect = lambda value: database.update({path: value})
        return ref

    firebase_store = types.ModuleType('firebase_store')
    firebase_store.FirebaseStore = Mock()
    firebase_admin = types.ModuleType('firebase_admin')
    firebase_admin.db = types.SimpleNamespace(reference=reference)
    market_calendar = types.ModuleType('market_calendar')
    market_calendar.is_market_open = calendar
    with patch.dict(sys.modules, {'firebase_store': firebase_store,
                                  'firebase_admin': firebase_admin,
                                  'market_calendar': market_calendar}), \
         patch.object(publish, 'market_session', return_value='CLOSED'), \
         patch.object(publish, 'datetime') as clock:
        clock.now.return_value = NOW
        publish.main()
    public = database['/market_data/provider_health']
    assert public['providers']['fugle']['status'] == 'ONLINE'
    assert set(public['providers']['fugle']) == {'status', 'last_checked_at'}
    assert json.loads((tmp_path / 'fugle.json').read_text())['run_id'] == '36673457508'
