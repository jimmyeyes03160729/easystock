"""Verify the scheduled Fugle scan without exposing its credential to the VM."""

import os
import re
from datetime import date, datetime, time, timedelta

from .health import TPE, age, timestamp

WORKFLOW = 'intraday-picks'
SOURCE = 'github_actions'
PAYLOAD_SOURCE = 'legacy_fugle_overnight'
DEADLINE = time(13, 35)
STATUSES = {'ONLINE', 'DEGRADED', 'OFFLINE', 'UNKNOWN'}
FRESHNESS = {'on_schedule', 'overdue', 'invalid', 'no_evidence',
             'calendar_unavailable', 'publisher_stale', 'read_failed'}
ERRORS = {'missing_evidence', 'scan_overdue', 'evidence_invalid', 'payload_mismatch',
          'future_timestamp', 'explicit_failure', 'calendar_error', 'firebase_read_failed'}


def _day(value):
    try:
        if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            return None
        return date.fromisoformat(value)
    except ValueError:
        return None


def _counts(payload):
    candidate = payload.get('candidate_symbols')
    scanned = payload.get('scanned_symbols')
    return (type(candidate) is int and type(scanned) is int and
            0 <= scanned <= candidate <= 100_000 and
            (candidate == 0 or scanned > 0))


def _open(calendar, day):
    result = calendar(day)
    if not isinstance(result, tuple) or not result or type(result[0]) is not bool:
        raise ValueError('calendar_result_invalid')
    return result[0]


def schedule(now, calendar):
    """Return last due trading day and today's next deadline, if not yet due."""
    now = now.astimezone(TPE)
    today = now.date()
    today_open = _open(calendar, today) if today.weekday() < 5 else False
    today_due = datetime.combine(today, DEADLINE, TPE)
    if today_open and now >= today_due:
        return today, None
    for offset in range(1, 17):
        previous = today - timedelta(days=offset)
        if previous.weekday() < 5 and _open(calendar, previous):
            return previous, today_due if today_open else None
    raise ValueError('trading_day_not_found')


def _metadata(evidence):
    row = evidence if isinstance(evidence, dict) else {}
    raw_run = row.get('run_id')
    raw_attempt = row.get('run_attempt')
    raw_sha = row.get('commit_sha')
    return {
        'scan_date': _day(row.get('scan_date')).isoformat() if _day(row.get('scan_date')) else None,
        'last_success_at': timestamp(row.get('completed_at')).isoformat()
            if row.get('status') == 'success' and timestamp(row.get('completed_at')) else None,
        'data_generated_at': timestamp(row.get('data_generated_at')).isoformat()
            if timestamp(row.get('data_generated_at')) else None,
        'workflow_source': SOURCE if row.get('source') == SOURCE else None,
        'run_id': raw_run if isinstance(raw_run, str) and re.fullmatch(r'\d{1,20}', raw_run) else None,
        'run_attempt': raw_attempt if type(raw_attempt) is int and 1 <= raw_attempt <= 100 else None,
        'commit_sha': raw_sha if isinstance(raw_sha, str) and re.fullmatch(r'[0-9a-f]{40}', raw_sha) else None,
    }


def _result(now, expected=None, next_due=None, *, status='UNKNOWN', freshness='no_evidence',
            error_code=None, evidence=None, generated=None):
    safe = _metadata(evidence)
    return {
        'kind': 'scheduled', 'status': status, 'checked_at': now.astimezone(TPE).isoformat(),
        'expected_scan_date': expected.isoformat() if expected else None,
        'next_due_at': next_due.isoformat() if next_due else None,
        'freshness': freshness, 'error_code': error_code if error_code in ERRORS else None,
        'age_seconds': age(generated.isoformat(), now) if generated else None,
        'fresh': status == 'ONLINE', **safe,
    }


def unavailable(now):
    return _result(now, status='DEGRADED', freshness='read_failed', error_code='firebase_read_failed')


def evaluate(evidence, payload, now, calendar):
    """Require a due GitHub success *and* matching Firebase scan data."""
    now = now.astimezone(TPE)
    try:
        expected, next_due = schedule(now, calendar)
    except Exception:
        return _result(now, freshness='calendar_unavailable', error_code='calendar_error')
    if not isinstance(evidence, dict) or not evidence:
        return _result(now, expected, next_due, error_code='missing_evidence')

    common = dict(expected=expected, next_due=next_due, evidence=evidence)
    day = _day(evidence.get('scan_date'))
    completed = timestamp(evidence.get('completed_at'))
    valid_identity = (evidence.get('schema_version') == 1 and evidence.get('provider') == 'fugle'
                      and evidence.get('source') == SOURCE and evidence.get('workflow') == WORKFLOW)
    if not valid_identity or day is None or completed is None:
        return _result(now, status='DEGRADED', freshness='invalid', error_code='evidence_invalid', **common)
    if completed > now:
        return _result(now, status='DEGRADED', freshness='invalid', error_code='future_timestamp', **common)
    if day != expected:
        return _result(now, status='DEGRADED', freshness='overdue', error_code='scan_overdue', **common)
    if evidence.get('status') == 'failure':
        return _result(now, status='OFFLINE', freshness='invalid', error_code='explicit_failure', **common)
    if evidence.get('status') != 'success':
        return _result(now, status='DEGRADED', freshness='invalid', error_code='evidence_invalid', **common)

    published = payload if isinstance(payload, dict) else {}
    generated = timestamp(published.get('generated_at'))
    evidence_generated = timestamp(evidence.get('data_generated_at'))
    if (generated and generated > now) or (evidence_generated and evidence_generated > now):
        return _result(now, status='DEGRADED', freshness='invalid', error_code='future_timestamp', **common)
    matched = (published.get('scan_date') == day.isoformat()
               and published.get('source') == PAYLOAD_SOURCE
               and published.get('overnight_source') == 'fugle'
               and _counts(published)
               and generated is not None and evidence_generated is not None
               and generated == evidence_generated and generated.date() == day
               and generated <= completed)
    if not matched:
        return _result(now, status='DEGRADED', freshness='invalid', error_code='payload_mismatch', **common)
    return _result(now, status='ONLINE', freshness='on_schedule', generated=generated, **common)


def cached_health(value, now):
    """Allowlist the VM cache before exposing it to the Owner dashboard."""
    row = value if isinstance(value, dict) else {}
    checked = timestamp(row.get('checked_at'))
    result = {
        'kind': 'scheduled', 'status': row.get('status') if row.get('status') in STATUSES else 'UNKNOWN',
        'checked_at': checked.isoformat() if checked else None,
        'expected_scan_date': _day(row.get('expected_scan_date')).isoformat()
            if _day(row.get('expected_scan_date')) else None,
        'next_due_at': timestamp(row.get('next_due_at')).isoformat() if timestamp(row.get('next_due_at')) else None,
        'scan_date': _day(row.get('scan_date')).isoformat() if _day(row.get('scan_date')) else None,
        'last_success_at': timestamp(row.get('last_success_at')).isoformat()
            if timestamp(row.get('last_success_at')) else None,
        'data_generated_at': timestamp(row.get('data_generated_at')).isoformat()
            if timestamp(row.get('data_generated_at')) else None,
        'workflow_source': SOURCE if row.get('workflow_source') == SOURCE else None,
        'freshness': row.get('freshness') if row.get('freshness') in FRESHNESS else 'no_evidence',
        'error_code': row.get('error_code') if row.get('error_code') in ERRORS else None,
        'age_seconds': row.get('age_seconds') if type(row.get('age_seconds')) in (int, float)
            and 0 <= row.get('age_seconds') <= 1_000_000 else None,
        'run_id': row.get('run_id') if isinstance(row.get('run_id'), str)
            and re.fullmatch(r'\d{1,20}', row.get('run_id')) else None,
        'run_attempt': row.get('run_attempt') if type(row.get('run_attempt')) is int
            and 1 <= row.get('run_attempt') <= 100 else None,
        'commit_sha': row.get('commit_sha') if isinstance(row.get('commit_sha'), str)
            and re.fullmatch(r'[0-9a-f]{40}', row.get('commit_sha')) else None,
        'fresh': row.get('status') == 'ONLINE',
    }
    checked_age = age(result['checked_at'], now)
    if checked_age is None or checked_age > 180:
        result.update(status='UNKNOWN', freshness='publisher_stale', fresh=False)
    elif result['status'] == 'ONLINE' and not (
            result['workflow_source'] == SOURCE
            and result['scan_date'] == result['expected_scan_date']
            and result['last_success_at'] and result['data_generated_at']
            and result['freshness'] == 'on_schedule'):
        result.update(status='DEGRADED', freshness='invalid',
                      error_code='evidence_invalid', fresh=False)
    return result


def record_success(root, payload, now=None, environ=None):
    """Called only after scan_intraday has written its payload successfully."""
    env = os.environ if environ is None else environ
    if env.get('GITHUB_ACTIONS') != 'true':
        return False
    now = (now or datetime.now(TPE)).astimezone(TPE)
    run_id = env.get('GITHUB_RUN_ID', '')
    attempt = env.get('GITHUB_RUN_ATTEMPT', '')
    sha = env.get('GITHUB_SHA', '')
    event = env.get('GITHUB_EVENT_NAME', '')
    generated = timestamp(payload.get('generated_at')) if isinstance(payload, dict) else None
    if not (re.fullmatch(r'\d{1,20}', run_id) and re.fullmatch(r'\d{1,3}', attempt)
            and 1 <= int(attempt) <= 100 and re.fullmatch(r'[0-9a-f]{40}', sha)
            and event in ('schedule', 'workflow_dispatch') and generated
            and generated.date() == now.date() and generated <= now
            and payload.get('scan_date') == now.date().isoformat()
            and payload.get('source') == PAYLOAD_SOURCE
            and payload.get('overnight_source') == 'fugle'
            and _counts(payload)):
        raise ValueError('fugle_scan_evidence_invalid')
    evidence = {
        'schema_version': 1, 'provider': 'fugle', 'status': 'success',
        'scan_date': now.date().isoformat(), 'completed_at': now.isoformat(),
        'data_generated_at': generated.isoformat(), 'source': SOURCE,
        'workflow': WORKFLOW, 'run_id': run_id, 'run_attempt': int(attempt),
        'event_name': event, 'commit_sha': sha,
    }
    root.child('provider_evidence').child('fugle').set(evidence)
    return True
