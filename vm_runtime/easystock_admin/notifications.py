"""Owner-only personal notification policy and private runtime configuration."""
import os
import re
import time
from pathlib import Path


POLICY_FIELDS = ('line_trade', 'line_summary', 'telegram_trade', 'telegram_summary')


def initialize(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS notification_policy(
      id INTEGER PRIMARY KEY CHECK(id=1),
      line_trade INTEGER NOT NULL DEFAULT 0,
      line_summary INTEGER NOT NULL DEFAULT 0,
      telegram_trade INTEGER NOT NULL DEFAULT 0,
      telegram_summary INTEGER NOT NULL DEFAULT 0,
      version INTEGER NOT NULL DEFAULT 1,
      updated REAL NOT NULL DEFAULT 0
    );
    INSERT OR IGNORE INTO notification_policy(id,updated) VALUES(1,0);
    CREATE TABLE IF NOT EXISTS notification_receipts(
      key TEXT PRIMARY KEY, channel TEXT NOT NULL, status TEXT NOT NULL, created REAL NOT NULL
    );
    ''')
    cols = {row[1] for row in db.execute('PRAGMA table_info(notification_receipts)')}
    if 'kind' not in cols:
        db.execute("ALTER TABLE notification_receipts ADD COLUMN kind TEXT NOT NULL DEFAULT 'trade'")


def _private_values():
    from dotenv import dotenv_values
    values = {}
    for filename in (
        os.environ.get('TELEGRAM_CONFIG_FILE', '/home/ubuntu/easystock-telegram.env'),
        os.environ.get('LINE_CONFIG_FILE', '/home/ubuntu/easystock/.env'),
    ):
        path = Path(filename)
        if path.is_file():
            values.update(dotenv_values(path))
    return values


def line_config():
    values = _private_values()
    token = str(os.environ.get('LINE_CHANNEL_ACCESS_TOKEN') or values.get('LINE_CHANNEL_ACCESS_TOKEN') or '').strip()
    # LINE_TARGET_ID is accepted only when it is demonstrably a user target.
    target = str(os.environ.get('LINE_USER_ID') or values.get('LINE_USER_ID') or
                 os.environ.get('LINE_TARGET_ID') or values.get('LINE_TARGET_ID') or '').strip()
    if not token or not re.fullmatch(r'U[0-9A-Fa-f]{32}', target):
        return '', ''
    return token, target


def telegram_config():
    values = _private_values()
    token = str(os.environ.get('TELEGRAM_BOT_TOKEN') or values.get('TELEGRAM_BOT_TOKEN') or '').strip()
    chat = str(os.environ.get('TELEGRAM_CHAT_ID') or values.get('TELEGRAM_CHAT_ID') or
               os.environ.get('TELEGRAM_USER_ID') or values.get('TELEGRAM_USER_ID') or '').strip()
    if not re.fullmatch(r'[0-9]+:[A-Za-z0-9_-]{30,}', token) or not re.fullmatch(r'[1-9][0-9]{3,19}', chat):
        return '', ''
    return token, chat


def policy(store):
    with store.tx() as db:
        row = db.execute('SELECT line_trade,line_summary,telegram_trade,telegram_summary,version,updated FROM notification_policy WHERE id=1').fetchone()
    return {**dict(zip(POLICY_FIELDS, map(bool, row[:4]))), 'version': int(row[4]), 'updated_at': row[5]}


def state(store):
    values = policy(store)
    with store.tx() as db:
        deliveries = [{'channel': row[0], 'kind': row[1], 'status': row[2], 'at': row[3]} for row in db.execute(
            'SELECT channel,kind,status,created FROM notification_receipts ORDER BY created DESC LIMIT 12')]
    return {
        'version': values['version'],
        'line': {'configured': bool(all(line_config())), 'trade': values['line_trade'], 'summary': values['line_summary']},
        'telegram': {'configured': bool(all(telegram_config())), 'trade': values['telegram_trade'], 'summary': values['telegram_summary']},
        'deliveries': deliveries,
    }


def update(store, data):
    from .store import Conflict
    if not isinstance(data, dict) or set(data) != set(POLICY_FIELDS) | {'version'}:
        raise ValueError('通知設定欄位不正確。')
    if type(data['version']) is not int or any(type(data[key]) is not bool for key in POLICY_FIELDS):
        raise ValueError('請提供四個通知開關與設定版本。')
    with store.tx() as db:
        before = db.execute('SELECT line_trade,line_summary,telegram_trade,telegram_summary,version FROM notification_policy WHERE id=1').fetchone()
        result = db.execute('''UPDATE notification_policy SET line_trade=?,line_summary=?,telegram_trade=?,telegram_summary=?,
            version=version+1,updated=? WHERE id=1 AND version=?''',
            (*(int(data[key]) for key in POLICY_FIELDS), time.time(), data['version']))
        if not result.rowcount:
            raise Conflict('通知設定已變更，請重新載入。')
        store._audit(db, 'google', 'personal_notification_policy', {
            'before': dict(zip(POLICY_FIELDS, map(bool, before[:4]))),
            'after': {key: data[key] for key in POLICY_FIELDS},
        })
    return state(store)
