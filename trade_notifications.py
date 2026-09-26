"""Independent group delivery, at most one attempt per event/channel.

An ambiguous timeout is NOT blindly retried: Telegram has no sendMessage
idempotency key. Receipts contain hashes/status only, never credentials/body.
"""
import hashlib
import json
from datetime import datetime, timedelta, timezone
import time
import requests


def event_identity(event, text):
    event = event if isinstance(event, dict) else {}
    data = next((event[k] for k in ('position', 'trade') if isinstance(event.get(k), dict)), event)
    # The live PositionManager uses position.entry_time, not trade_id.
    # Include date/time so identical short messages on different days are distinct.
    identity = {'kind': event.get('type'), 'trade_id': event.get('trade_id') or data.get('trade_id'),
                'symbol': data.get('symbol'), 'entry_time': str(data.get('entry_time') or ''),
                'exit_time': str(data.get('exit_time') or '')}
    if not identity['trade_id'] and not identity['entry_time']:
        identity['day'] = datetime.now(timezone(timedelta(hours=8))).date().isoformat()
        identity['text_hash'] = hashlib.sha256(text.encode()).hexdigest()
    return hashlib.sha256(json.dumps(identity, sort_keys=True, default=str).encode()).hexdigest()


def telegram_send(text, store):
    from easystock_admin.notifications import telegram_config
    token, group = telegram_config()
    with store.tx() as db:
        enabled = db.execute('SELECT push FROM telegram_policy WHERE id=1').fetchone()[0]
    if not token or not group or not enabled: return 'disabled'
    # Plain text, bounded to Telegram's 4096-character limit; no paid broadcast.
    try:
        response = requests.post('https://api.telegram.org/bot' + token + '/sendMessage',
            json={'chat_id': group, 'text': text[:4096], 'link_preview_options': {'is_disabled': True}},
            timeout=(3, 8), allow_redirects=False)
        if response.status_code == 200 and response.json().get('ok') is True: return 'sent'
        return 'failed'
    except requests.RequestException:
        return 'unknown'
    except (ValueError, TypeError):
        return 'unknown'


def send_trade(text, line_send, entry_check=None, event_key=None, store=None):
    if not isinstance(text, str) or not text.strip(): return False
    from easystock_admin.store import Store
    try: store = store or Store()
    except Exception:
        print('[NOTIFY] private state unavailable; delivery skipped')
        return False
    event_key = event_key or event_identity(None, text)
    delivered = False
    for channel in ('telegram', 'line'):
        key = hashlib.sha256((channel + ':' + event_key).encode()).hexdigest()
        try:
            if entry_check is not None and not entry_check(): continue
            if channel == 'line':
                from easystock_admin.conversations import state as line_state
                line = line_state(store)
                if not line['values']['trade_push'] or not any(row['push'] for row in line['conversations']): continue
            if channel == 'telegram':
                from easystock_admin.notifications import telegram_config
                if not all(telegram_config()): continue
                with store.tx() as db:
                    if not db.execute('SELECT push FROM telegram_policy WHERE id=1').fetchone()[0]: continue
            with store.tx() as db:
                inserted = db.execute('INSERT OR IGNORE INTO notification_receipts VALUES(?,?,?,?)',
                                      (key, channel, 'pending', time.time())).rowcount
            if not inserted: continue
            status = telegram_send(text, store) if channel == 'telegram' else ('sent' if line_send(text, entry_check=entry_check) else 'failed')
        except Exception:
            # Exception strings can include Telegram's credential-bearing URL.
            status = 'unknown'
        try:
            with store.tx() as db:
                db.execute('UPDATE notification_receipts SET status=? WHERE key=?', (status, key))
        except Exception:
            print('[NOTIFY]', channel, 'receipt update unavailable')
        print('[NOTIFY]', channel, status)
        delivered = delivered or status == 'sent'
    return delivered
