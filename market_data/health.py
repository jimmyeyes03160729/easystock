"""Deterministic, allowlisted provider health from actual request/quote evidence."""
import json
import math
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

TPE = timezone(timedelta(hours=8))
DEFAULT_DIR = '/home/ubuntu/easystock-market-data'
POLICIES = {
    'shioaji': {'kind': 'quote', 'max_age': 90, 'worker_age': 120},
    'esun': {'kind': 'stream', 'max_age': 90, 'worker_age': 120},
    'fugle': {'kind': 'scheduled', 'max_age': 180},
    'firebase': {'kind': 'request', 'max_age': 180},
    'gemini': {'kind': 'on_demand', 'max_age': 86400},
    'openai': {'kind': 'on_demand', 'max_age': 86400},
}
LABELS = {'shioaji': '永豐行情', 'esun': '玉山行情', 'fugle': 'Fugle',
          'firebase': 'Firebase', 'gemini': 'Gemini', 'openai': 'OpenAI'}
ERRORS = {'connection_failed', 'authentication_failed', 'disconnected', 'websocket_error',
          'heartbeat_timeout', 'timeout', 'parser_invalid', 'subscription_error',
          'request_failed', 'quote_request_failed', 'quote_stale', 'not_configured',
          'http_error', 'publish_failed', 'calendar_error', 'future_timestamp'}
DIAGNOSTICS = {'connected', 'authenticated', 'subscribed', 'parser_ok', 'last_ok_at',
               'last_data_at', 'last_event_at', 'last_error_at', 'quote_at', 'checked_at', 'last_heartbeat_at',
               'configured', 'latency_ms', 'consecutive_failures', 'reconnect_count', 'subscription_count',
               'error_code', 'provider_version', 'retry_after_seconds', 'reconnect_state'}


def data_dir():
    return Path(os.environ.get('EASYSTOCK_MARKET_DATA_DIR', DEFAULT_DIR))


def timestamp(value):
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return result.astimezone(TPE) if result.tzinfo else None
    except (AttributeError, ValueError, TypeError, OverflowError):
        return None


def age(value, now):
    at = timestamp(value)
    seconds = (now - at).total_seconds() if at else None
    return round(max(0, seconds), 2) if seconds is not None and seconds >= -2 else None


def sanitize(value):
    """Whitelist typed fields; never copy free text, URLs, accounts or exceptions."""
    result = {}
    for key in DIAGNOSTICS:
        item = value.get(key)
        if key.endswith('_at'):
            at = timestamp(item)
            if at: result[key] = at.isoformat()
        elif key in ('connected', 'authenticated', 'subscribed', 'parser_ok', 'configured'):
            if isinstance(item, bool): result[key] = item
        elif key == 'error_code':
            if item in ERRORS: result[key] = item
        elif key == 'provider_version':
            if item == '1': result[key] = item
        elif key == 'reconnect_state':
            if item in ('idle', 'connected', 'backoff'): result[key] = item
        elif isinstance(item, (int, float)) and not isinstance(item, bool) and math.isfinite(item) and 0 <= item <= 1e9:
            result[key] = item
    return result


def read_json(filename):
    try:
        if filename.stat().st_size > 1024 * 1024: return {}
        value = json.loads(filename.read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, UnicodeError):
        return {}


def atomic(filename, value):
    filename.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix=filename.name, suffix='.tmp', dir=filename.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as output:
            json.dump(value, output, ensure_ascii=False, allow_nan=False)
        os.chmod(name, 0o600)
        os.replace(name, filename)
    finally:
        if os.path.exists(name): os.unlink(name)


def observe(provider, *, ok, quote_at=None, latency_ms=None, error_code='request_failed', **fields):
    """Best effort instrumentation: health writes cannot interrupt any caller."""
    if provider not in POLICIES: return
    root = data_dir()
    if not root.exists() and not os.environ.get('EASYSTOCK_MARKET_DATA_DIR'): return
    try:
        now = datetime.now(TPE).isoformat()
        old = sanitize(read_json(root / (provider + '.json')))
        row = {**old, **sanitize(fields), 'checked_at': now, 'parser_ok': bool(ok)}
        if latency_ms is not None: row.update(sanitize({'latency_ms': latency_ms}))
        if ok:
            row.update(last_ok_at=now, consecutive_failures=0)
            row.pop('error_code', None)
            if quote_at:
                row.update(quote_at=quote_at, last_data_at=now)
        else:
            row.update(last_error_at=now, error_code=error_code if error_code in ERRORS else 'request_failed',
                       consecutive_failures=old.get('consecutive_failures', 0) + 1)
        atomic(root / (provider + '.json'), sanitize(row))
    except (OSError, ValueError, TypeError):
        pass


def market_session(now=None, calendar=None):
    now = (now or datetime.now(TPE)).astimezone(TPE)
    try:
        if calendar is None:
            from market_calendar import is_market_open
            calendar = is_market_open
        opened, _, _ = calendar(now.date())
        if not opened: return 'CLOSED'
        return 'OPEN' if 9 * 60 <= now.hour * 60 + now.minute < 13 * 60 + 30 else 'CLOSED'
    except Exception:
        return 'UNKNOWN'


def provider_health(provider, evidence, now, session):
    if provider == 'fugle':
        from .fugle_pipeline import cached_health
        return cached_health(evidence, now)
    row = sanitize(evidence)
    policy = POLICIES[provider]
    kind = policy['kind']
    quote_age = age(row.get('quote_at'), now)
    ok_age = age(row.get('last_ok_at'), now)
    worker_age = age(row.get('checked_at'), now)
    heartbeat_age = age(row.get('last_heartbeat_at'), now)
    quote = timestamp(row.get('quote_at'))
    future = any(timestamp(row.get(key)) and age(row[key], now) is None for key in row if key.endswith('_at'))
    failed = bool(row.get('consecutive_failures', 0))
    fresh = quote is not None and quote.date() == now.date() and quote_age is not None and quote_age <= policy['max_age']
    if not row: status = 'UNKNOWN'
    elif future: status = 'DEGRADED'
    elif kind == 'on_demand' and (worker_age is None or worker_age > policy['max_age']): status = 'UNKNOWN'
    elif failed and row.get('error_code') in ('parser_invalid', 'quote_stale'): status = 'DEGRADED'
    elif failed or row.get('connected') is False: status = 'OFFLINE'
    elif kind == 'stream' and (worker_age is None or worker_age > policy['worker_age']): status = 'OFFLINE'
    elif kind == 'stream' and (row.get('authenticated') is not True or row.get('subscribed') is not True): status = 'DEGRADED'
    elif kind == 'stream' and (heartbeat_age is None or heartbeat_age > 90): status = 'DEGRADED'
    elif row.get('parser_ok') is not True: status = 'DEGRADED'
    elif kind == 'quote' and session == 'CLOSED':
        status = 'MARKET_CLOSED' if quote and quote.date() == now.date() else 'UNKNOWN'
    elif kind == 'stream' and session == 'CLOSED': status = 'MARKET_CLOSED'
    elif kind in ('quote', 'stream'): status = 'ONLINE' if fresh and worker_age is not None and worker_age <= policy['worker_age'] else 'DEGRADED'
    else: status = 'ONLINE' if ok_age is not None and ok_age <= policy['max_age'] else 'UNKNOWN' if kind == 'on_demand' else 'DEGRADED'
    diagnostic = {**row, 'status': status, 'age_seconds': quote_age if kind in ('quote', 'stream') else ok_age,
                  'fresh': bool(fresh), 'heartbeat_age_seconds': heartbeat_age,
                  'freshness_limit_seconds': policy['max_age']}
    return diagnostic


def aggregate(now=None, session=None, root=None):
    now = (now or datetime.now(TPE)).astimezone(TPE)
    session = session or market_session(now)
    root = root or data_dir()
    providers = {name: provider_health(name, read_json(root / (name + '.json')), now, session) for name in POLICIES}
    usable = [name for name in ('shioaji', 'esun') if providers[name]['status'] == 'ONLINE' and providers[name]['fresh']]
    common = {'schema_version': 1, 'generated_at': now.isoformat(), 'market_state': session}
    public = {**common, 'providers': {name: {'status': row['status'], 'last_checked_at': row.get('checked_at')}
                                    for name, row in providers.items()}}
    private = {**common, 'providers': providers, 'market_data': {'usable': bool(usable), 'sources': usable}}
    return public, private
