"""Idempotent delivery of canonical paper trade and daily-summary events."""
import hashlib
import json
import time
import uuid
from datetime import datetime, timedelta, timezone
import requests


TPE = timezone(timedelta(hours=8))


def event_identity(event, text):
    event = event if isinstance(event, dict) else {}
    data = next((event[k] for k in ('position', 'trade') if isinstance(event.get(k), dict)), event)
    identity = {'kind': event.get('type'), 'trade_id': event.get('trade_id') or data.get('trade_id'),
                'symbol': data.get('symbol'), 'entry_time': str(data.get('entry_time') or ''),
                'exit_time': str(data.get('exit_time') or '')}
    if not identity['trade_id'] and not identity['entry_time']:
        identity['day'] = datetime.now(TPE).date().isoformat()
        identity['text_hash'] = hashlib.sha256(text.encode()).hexdigest()
    return hashlib.sha256(json.dumps(identity, sort_keys=True, default=str).encode()).hexdigest()


def _reserve(store, channel, kind, event_key):
    key = hashlib.sha256(f'{channel}:{kind}:{event_key}'.encode()).hexdigest()
    with store.tx() as db:
        inserted = db.execute('INSERT OR IGNORE INTO notification_receipts(key,channel,status,created,kind) VALUES(?,?,?,?,?)',
                              (key, channel, 'pending', time.time(), kind)).rowcount
    return key if inserted else ''


def _finish(store, key, status):
    try:
        with store.tx() as db:
            db.execute('UPDATE notification_receipts SET status=? WHERE key=?', (status, key))
    except Exception:
        print('[NOTIFY] receipt update unavailable')


def _line_send(text, event_key):
    from easystock_admin.notifications import line_config
    token, target = line_config()
    if not token or not target:
        return 'disabled'
    retry_key = str(uuid.UUID(hashlib.md5(event_key.encode()).hexdigest()))
    try:
        response = requests.post('https://api.line.me/v2/bot/message/push',
            headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json', 'X-Line-Retry-Key': retry_key},
            json={'to': target, 'messages': [{'type': 'text', 'text': text[:5000]}]}, timeout=(3, 10), allow_redirects=False)
        if 200 <= response.status_code < 300 or (response.status_code == 409 and response.headers.get('x-line-accepted-request-id')):
            return 'sent'
        return 'failed'
    except requests.RequestException:
        return 'unknown'


def _telegram_send(text):
    from easystock_admin.notifications import telegram_config
    token, chat = telegram_config()
    if not token or not chat:
        return 'disabled'
    try:
        response = requests.post('https://api.telegram.org/bot' + token + '/sendMessage',
            json={'chat_id': chat, 'text': text[:4096], 'link_preview_options': {'is_disabled': True}},
            timeout=(3, 8), allow_redirects=False)
        return 'sent' if response.status_code == 200 and response.json().get('ok') is True else 'failed'
    except (requests.RequestException, ValueError, TypeError):
        # An ambiguous timeout is never retried automatically.
        return 'unknown'


def _send(text, kind, event_key, store=None):
    if not isinstance(text, str) or not text.strip():
        return False
    from easystock_admin.store import Store
    from easystock_admin.notifications import policy
    try:
        store = store or Store()
        switches = policy(store)
    except Exception:
        print('[NOTIFY] private state unavailable; delivery skipped')
        return False
    delivered = False
    for channel in ('line', 'telegram'):
        if not switches[f'{channel}_{kind}']:
            continue
        key = _reserve(store, channel, kind, event_key)
        if not key:
            continue
        try:
            status = _line_send(text, event_key) if channel == 'line' else _telegram_send(text)
        except Exception:
            status = 'unknown'
        _finish(store, key, status)
        print('[NOTIFY]', channel, kind, status)
        delivered = delivered or status == 'sent'
    return delivered


def send_trade(text, event=None, event_key=None, store=None, **_ignored):
    return _send(text, 'trade', event_key or event_identity(event, text), store)


def send_daily_summary(text, day=None, store=None):
    day = day or datetime.now(TPE).date().isoformat()
    return _send(text, 'summary', 'daily-summary:' + day, store)


# Compatibility for callers/tests that need the direct channel result.
def telegram_send(text, store=None):
    return _telegram_send(text)
