"""Private conversation preferences. No message bodies or reply tokens are stored."""
import hashlib
import json
import re
import time

DEFAULTS = {'replies': True, 'groups': True, 'users': True,
            'trade_push': True, 'other_push': False}


def initialize(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS line_policy(id INTEGER PRIMARY KEY CHECK(id=1),body TEXT NOT NULL,version INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS line_conversations(id TEXT PRIMARY KEY,source_id TEXT NOT NULL,kind TEXT NOT NULL,label TEXT NOT NULL,replies INTEGER NOT NULL DEFAULT 1,push INTEGER NOT NULL DEFAULT 0,seen REAL NOT NULL,version INTEGER NOT NULL DEFAULT 1);
    ''')
    db.execute('INSERT OR IGNORE INTO line_policy VALUES(1,?,1)', (json.dumps(DEFAULTS),))


def identity(source):
    kind = source.get('type')
    key = {'group': 'groupId', 'room': 'roomId', 'user': 'userId'}.get(kind)
    sid = source.get(key, '') if key else ''
    prefix = {'group': 'C', 'room': 'R', 'user': 'U'}.get(kind, '!')
    if not isinstance(sid, str) or not re.fullmatch(prefix + r'[0-9a-fA-F]{32}', sid):
        return None
    return hashlib.sha256(sid.encode()).hexdigest()[:24], sid, kind


def observe(store, source, label=None):
    item = identity(source)
    if not item: return None
    key, sid, kind = item
    title = (label or ('個人' if kind == 'user' else '群組') + ' …' + sid[-6:])[:80]
    with store.tx() as db:
        db.execute('INSERT OR IGNORE INTO line_conversations(id,source_id,kind,label,seen) VALUES(?,?,?,?,?)',
                   (key, sid, kind, title, time.time()))
        # Receiving another webhook must never re-enable a disabled conversation.
        db.execute('UPDATE line_conversations SET seen=? WHERE id=?', (time.time(), key))
    return key


def state(store):
    with store.tx() as db:
        row = db.execute('SELECT body,version FROM line_policy WHERE id=1').fetchone()
        rows = db.execute('SELECT id,kind,label,replies,push,seen,version FROM line_conversations ORDER BY seen DESC LIMIT 500').fetchall()
    return {'values': json.loads(row[0]), 'version': row[1], 'conversations': [
        dict(zip(('id','kind','label','replies','push','last_seen','version'), r)) for r in rows]}


def update(store, data):
    from .store import Conflict
    if set(data) != {'values','version'} or not isinstance(data['values'], dict) or set(data['values']) != set(DEFAULTS):
        raise ValueError('LINE 設定欄位不正確。')
    if any(type(v) is not bool for v in data['values'].values()) or type(data['version']) is not int:
        raise ValueError('LINE 開關必須是布林值，並提供版本。')
    with store.tx() as db:
        result = db.execute('UPDATE line_policy SET body=?,version=version+1 WHERE id=1 AND version=?',
                            (json.dumps(data['values']),data['version']))
        if not result.rowcount: raise Conflict('LINE 設定已更新，請重新載入。')
        store._audit(db,'google','line_policy',data['values'])
    return state(store)


def update_conversation(store, key, data):
    from .store import Conflict
    if set(data) != {'replies','push','label','version'} or type(data['replies']) is not bool or type(data['push']) is not bool or type(data['version']) is not int:
        raise ValueError('對話設定欄位不正確。')
    if not isinstance(data['label'],str) or not 1 <= len(data['label'].strip()) <= 80:
        raise ValueError('名稱須為 1～80 字。')
    with store.tx() as db:
        result = db.execute('UPDATE line_conversations SET replies=?,push=?,label=?,version=version+1 WHERE id=? AND version=?',
            (data['replies'],data['push'],data['label'].strip(),key,data['version']))
        if not result.rowcount: raise Conflict('對話已更新或不存在，請重新載入。')
        store._audit(db,'google','line_conversation',{'id':key,**data})
    return state(store)


def allowed(store, source, category='reply'):
    item = identity(source)
    if not item: return False
    key, _, kind = item
    with store.tx() as db:
        row = db.execute('SELECT body FROM line_policy WHERE id=1').fetchone()
        preferences = json.loads(row[0])
        row = db.execute('SELECT replies,push FROM line_conversations WHERE id=?',(key,)).fetchone()
    # Unknown destinations may reply but must be registered before any paid push.
    if category == 'reply':
        return preferences['replies'] and preferences['users' if kind=='user' else 'groups'] and (not row or bool(row[0]))
    return bool(row and row[1]) and preferences['trade_push' if category=='trade' else 'other_push']
