"""Group-only notification controls. Credentials never enter public state or audit."""
import json
import os
import re
from pathlib import Path


def initialize(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS telegram_policy(id INTEGER PRIMARY KEY CHECK(id=1),push INTEGER NOT NULL DEFAULT 0,version INTEGER NOT NULL DEFAULT 1);
    INSERT OR IGNORE INTO telegram_policy(id) VALUES(1);
    CREATE TABLE IF NOT EXISTS notification_receipts(key TEXT PRIMARY KEY,channel TEXT NOT NULL,status TEXT NOT NULL,created REAL NOT NULL);
    ''')


def telegram_config():
    from dotenv import dotenv_values
    path = Path(os.environ.get('TELEGRAM_CONFIG_FILE', '/home/ubuntu/easystock-telegram.env'))
    values = dotenv_values(path) if path.is_file() else {}
    token = os.environ.get('TELEGRAM_BOT_TOKEN', values.get('TELEGRAM_BOT_TOKEN') or '').strip()
    group = os.environ.get('TELEGRAM_GROUP_ID', values.get('TELEGRAM_GROUP_ID') or '').strip()
    if not re.fullmatch(r'[0-9]+:[A-Za-z0-9_-]{30,}', token) or not re.fullmatch(r'-[1-9][0-9]{4,19}', group):
        return '', ''
    return token, group


def state(store):
    from .conversations import state as line_state
    line = line_state(store)
    groups = []
    for row in line['conversations']:
        groups.append({**row, 'platform': 'line',
                       'replies': bool(row['replies'] and line['values']['replies'] and line['values']['groups']),
                       'push': bool(row['push'] and line['values']['trade_push'])})
    with store.tx() as db:
        push, version = db.execute('SELECT push,version FROM telegram_policy WHERE id=1').fetchone()
        deliveries = [{'channel': r[0], 'status': r[1], 'at': r[2]} for r in db.execute(
            'SELECT channel,status,created FROM notification_receipts ORDER BY created DESC LIMIT 10')]
    token, group = telegram_config()
    groups.append({'id': 'configured', 'platform': 'telegram', 'kind': 'group',
                   'label': 'Telegram 當沖群組', 'configured': bool(token and group),
                   'push': bool(push), 'version': version})
    return {'groups': groups, 'deliveries': deliveries}


def update(store, platform, key, data):
    from .store import Conflict
    required = {'push', 'version'} | ({'replies'} if platform == 'line' else set())
    if platform not in ('line', 'telegram') or set(data) != required:
        raise ValueError('群組設定欄位不正確。')
    if type(data['version']) is not int or any(type(data[k]) is not bool for k in required - {'version'}):
        raise ValueError('請提供開關與設定版本。')
    with store.tx() as db:
        if platform == 'telegram':
            if key != 'configured': raise ValueError('群組不存在。')
            if data['push'] and not all(telegram_config()): raise ValueError('Telegram 尚未設定完成。')
            result = db.execute('UPDATE telegram_policy SET push=?,version=version+1 WHERE id=1 AND version=?',
                                (data['push'], data['version']))
        else:
            result = db.execute("UPDATE line_conversations SET replies=?,push=?,version=version+1 WHERE id=? AND version=? AND kind='group' AND archived=0",
                                (data['replies'], data['push'], key, data['version']))
            # Normalize legacy global switches without changing other groups' effective settings.
            raw = db.execute('SELECT body FROM line_policy WHERE id=1').fetchone()[0]
            old = json.loads(raw)
            db.execute('UPDATE line_conversations SET replies=replies * ?,push=push * ? WHERE id<>?',
                       (bool(old['replies'] and old['groups']), bool(old['trade_push']), key))
            from .conversations import DEFAULTS
            db.execute('UPDATE line_policy SET body=?,version=version+1 WHERE id=1', (json.dumps(DEFAULTS),))
        if not result.rowcount: raise Conflict('群組設定已變更，請重新載入。')
        store._audit(db, 'google', 'notification_group', {'platform': platform, 'id': key, **data})
    return state(store)
