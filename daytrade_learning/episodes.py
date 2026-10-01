"""Durable research episodes; paper cash remains in the separate paper ledger."""
import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path


def research_path():
    return Path(os.environ.get('LEARNING_DATA_DIR', '/home/ubuntu/easystock-learning-data')) / 'research.sqlite'


def encode(value):
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(type(value).__name__)


def read_trades(path, day=None, status=None):
    """Read existing evidence without creating files or editing history."""
    path = Path(path).resolve()
    if not path.exists():
        return []
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
        query = 'SELECT payload FROM research_trades'
        clauses, params = [], []
        if day is not None:
            clauses.append('day=?')
            params.append(day)
        if status is not None:
            clauses.append('status=?')
            params.append(status)
        if clauses:
            query += ' WHERE ' + ' AND '.join(clauses)
        return [json.loads(row[0]) for row in db.execute(query + ' ORDER BY rowid', params)]


def research_days(path):
    path = Path(path).resolve()
    if not path.exists():
        return set()
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro', uri=True)) as db:
        return {row[0] for row in db.execute('SELECT DISTINCT day FROM research_trades')}


def mirror_entry(current, payload):
    """Late publish retries cannot reopen a closed or replace a newer episode."""
    current = dict(current or {})
    if current.get('scan_date') and str(payload['entry_time'])[:10] != current['scan_date']:
        return current
    identity = payload.get('research_trade_id') or payload.get('trade_id')
    closed = current.get('closed_trades') or {}
    if isinstance(closed, dict) and identity in closed:
        return current
    positions = dict(current.get('open_positions') or {})
    prior = positions.get(payload['symbol']) or {}
    if str(prior.get('entry_time','')) > str(payload['entry_time']):
        return current
    if ((prior.get('research_trade_id') or prior.get('trade_id')) == identity
            and str(prior.get('last_update_at', '')) > str(payload.get('last_update_at', ''))):
        return current
    positions[payload['symbol']] = payload
    current['open_positions'] = positions
    return current


def mirror_exit(current, payload, identity):
    """Closing episode #1 must never erase an already-published episode #2."""
    current = dict(current or {})
    if current.get('scan_date') and str(payload['entry_time'])[:10] != current['scan_date']:
        return current
    positions = dict(current.get('open_positions') or {})
    prior = positions.get(payload['symbol']) or {}
    if (prior.get('research_trade_id') or prior.get('trade_id')) == identity:
        positions.pop(payload['symbol'], None)
    closed = current.get('closed_trades') or {}
    closed = dict(closed) if isinstance(closed, dict) else {str(i):row for i,row in enumerate(closed)}
    closed[identity] = payload
    current.update(open_positions=positions, closed_trades=closed)
    return current


class ResearchStore:
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else research_path()
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE IF NOT EXISTS research_trades '
                       '(id TEXT PRIMARY KEY, day TEXT NOT NULL, symbol TEXT NOT NULL, '
                       'status TEXT NOT NULL, payload TEXT NOT NULL)')
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS research_open_symbol "
                       "ON research_trades(symbol) WHERE status='OPEN'")
            db.execute('CREATE TABLE IF NOT EXISTS research_rearm '
                       '(day TEXT, symbol TEXT, armed INTEGER, observed_at TEXT, PRIMARY KEY(day,symbol))')
        self.path.chmod(0o600)

    def save(self, trade, armed=None):
        payload = json.dumps(trade, default=encode, allow_nan=False, ensure_ascii=False)
        day = str(trade['entry_time'])[:10]
        with closing(sqlite3.connect(self.path, timeout=5)) as db, db:
            db.execute('INSERT INTO research_trades VALUES(?,?,?,?,?) '
                       'ON CONFLICT(id) DO UPDATE SET status=excluded.status,payload=excluded.payload',
                       (trade['research_trade_id'], day, trade['symbol'], trade['status'], payload))
            if armed is not None:
                self._state(db, day, trade['symbol'], armed, trade.get('exit_time', trade['entry_time']))

    @staticmethod
    def _state(db, day, symbol, armed, at):
        db.execute('INSERT OR REPLACE INTO research_rearm VALUES(?,?,?,?)',
                   (day, symbol, int(armed), str(at)))

    def arm(self, symbol, at):
        with closing(sqlite3.connect(self.path)) as db, db:
            self._state(db, str(at)[:10], symbol, True, at)

    def state(self, day):
        with closing(sqlite3.connect(self.path)) as db:
            return {symbol: (bool(armed), at) for symbol, armed, at in
                    db.execute('SELECT symbol,armed,observed_at FROM research_rearm WHERE day=?', (day,))}

    def trades(self, day=None, status=None):
        return read_trades(self.path, day, status)
