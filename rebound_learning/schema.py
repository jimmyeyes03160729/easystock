"""Private, idempotent SQLite store for candidate snapshots and later labels."""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from . import DATASET_SCHEMA_VERSION, FEATURE_SCHEMA_VERSION, STRATEGY_VERSION

DEFAULT_ROOT = Path('/home/ubuntu/easystock-learning-data/rebound')


def database_path() -> Path:
    return Path(os.environ.get('EASYSTOCK_REBOUND_DATA_DIR', DEFAULT_ROOT)) / 'dataset.sqlite'


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = path or database_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('PRAGMA busy_timeout=10000')
    db.executescript('''
        CREATE TABLE IF NOT EXISTS candidates (
            id TEXT PRIMARY KEY,
            strategy_version TEXT NOT NULL,
            feature_schema_version INTEGER NOT NULL,
            signal_date TEXT NOT NULL,
            symbol TEXT NOT NULL,
            candidate_kind TEXT NOT NULL,
            snapshot TEXT NOT NULL,
            label TEXT,
            UNIQUE(strategy_version, feature_schema_version, signal_date, symbol)
        );
        CREATE INDEX IF NOT EXISTS candidate_date ON candidates(signal_date);
        CREATE TABLE IF NOT EXISTS daily_bars (
            symbol TEXT NOT NULL,
            day TEXT NOT NULL,
            bar TEXT NOT NULL,
            PRIMARY KEY(symbol, day)
        );
        CREATE TABLE IF NOT EXISTS scan_days (
            day TEXT PRIMARY KEY,
            symbols_scanned INTEGER NOT NULL,
            symbols_expected INTEGER NOT NULL,
            source TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS trading_days (
            day TEXT PRIMARY KEY
        );
    ''')
    db.commit()
    return db


def identity(signal_date: str, symbol: str, kind: str,
             strategy_version: str = STRATEGY_VERSION,
             feature_schema_version: int = FEATURE_SCHEMA_VERSION) -> str:
    return f'{strategy_version}:{feature_schema_version}:{signal_date}:{symbol}:{kind}'


def stable_json(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def save_candidate(db: sqlite3.Connection, row: dict) -> None:
    key = identity(row['signal_date'], row['symbol'], row['candidate_kind'],
                   row['strategy_version'], row['feature_schema_version'])
    existing = db.execute('''SELECT id,snapshot FROM candidates WHERE strategy_version=?
        AND feature_schema_version=? AND signal_date=? AND symbol=?''',
        (row['strategy_version'], row['feature_schema_version'], row['signal_date'], row['symbol'])).fetchone()
    serialized = stable_json(row)
    if existing:
        if existing['id'] != key or existing['snapshot'] != serialized:
            raise ValueError(f'candidate_snapshot_changed:{row["signal_date"]}:{row["symbol"]}')
        return
    db.execute('INSERT INTO candidates VALUES (?,?,?,?,?,?,?,NULL)',
               (key, row['strategy_version'], row['feature_schema_version'],
                row['signal_date'], row['symbol'], row['candidate_kind'], serialized))


def save_bar(db: sqlite3.Connection, symbol: str, bar: dict) -> None:
    value = stable_json(bar)
    old = db.execute('SELECT bar FROM daily_bars WHERE symbol=? AND day=?',
                     (symbol, bar['time'])).fetchone()
    if old:
        if old['bar'] != value:
            raise ValueError(f'bar_changed:{symbol}:{bar["time"]}')
        return
    db.execute('INSERT INTO daily_bars VALUES (?,?,?)', (symbol, bar['time'], value))


def candidates(db: sqlite3.Connection):
    for row in db.execute('SELECT id,snapshot,label FROM candidates ORDER BY signal_date,symbol'):
        yield row['id'], json.loads(row['snapshot']), json.loads(row['label']) if row['label'] else None
