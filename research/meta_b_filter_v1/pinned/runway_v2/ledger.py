"""Runway V2: 獨立 SQLite 模擬帳本
專屬資料表結構，與主帳本 state.sqlite 徹底隔離，零干擾。
"""
from __future__ import annotations
import sqlite3
import time
from pathlib import Path
from .config import DB_DIR, DB_PATH


def get_connection(db_path: Path | str | None = None) -> sqlite3.Connection:
    target = Path(db_path or DB_PATH)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    conn = sqlite3.connect(str(target), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path | str | None = None) -> None:
    conn = get_connection(db_path)
    with conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS runway_v2_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id TEXT UNIQUE NOT NULL,
            symbol TEXT NOT NULL,
            name TEXT NOT NULL,
            side TEXT NOT NULL DEFAULT 'BUY',
            entry_time TEXT NOT NULL,
            entry_price REAL NOT NULL,
            shares INTEGER NOT NULL,
            signal_type TEXT NOT NULL,
            score REAL NOT NULL,
            reasons TEXT NOT NULL,
            
            exit_time TEXT,
            exit_price REAL,
            exit_reason TEXT,
            
            gross_pnl REAL,
            fee REAL,
            tax REAL,
            net_pnl REAL,
            return_pct REAL,
            status TEXT NOT NULL DEFAULT 'OPEN',
            created_at REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS runway_v2_daily_summary (
            date TEXT PRIMARY KEY,
            total_trades INTEGER NOT NULL DEFAULT 0,
            win_trades INTEGER NOT NULL DEFAULT 0,
            loss_trades INTEGER NOT NULL DEFAULT 0,
            win_rate REAL NOT NULL DEFAULT 0.0,
            total_net_pnl REAL NOT NULL DEFAULT 0.0,
            best_trade_pnl REAL NOT NULL DEFAULT 0.0,
            worst_trade_pnl REAL NOT NULL DEFAULT 0.0,
            updated_at REAL NOT NULL
        );
        """)
    conn.close()


def record_entry(
    trade_id: str,
    symbol: str,
    name: str,
    entry_time: str,
    entry_price: float,
    shares: int,
    signal_type: str,
    score: float,
    reasons: list[str],
    db_path: Path | str | None = None,
) -> None:
    conn = get_connection(db_path)
    with conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO runway_v2_trades (
                trade_id, symbol, name, side, entry_time, entry_price, shares,
                signal_type, score, reasons, status, created_at
            ) VALUES (?, ?, ?, 'BUY', ?, ?, ?, ?, ?, ?, 'OPEN', ?)
            """,
            (
                trade_id,
                symbol,
                name,
                entry_time,
                entry_price,
                shares,
                signal_type,
                score,
                ", ".join(reasons),
                time.time(),
            ),
        )
    conn.close()


def record_exit(
    trade_id: str,
    exit_time: str,
    exit_price: float,
    exit_reason: str,
    gross_pnl: float,
    fee: float,
    tax: float,
    net_pnl: float,
    return_pct: float,
    db_path: Path | str | None = None,
) -> None:
    conn = get_connection(db_path)
    with conn:
        conn.execute(
            """
            UPDATE runway_v2_trades SET
                exit_time = ?,
                exit_price = ?,
                exit_reason = ?,
                gross_pnl = ?,
                fee = ?,
                tax = ?,
                net_pnl = ?,
                return_pct = ?,
                status = 'CLOSED'
            WHERE trade_id = ?
            """,
            (
                exit_time,
                exit_price,
                exit_reason,
                gross_pnl,
                fee,
                tax,
                net_pnl,
                return_pct,
                trade_id,
            ),
        )
    conn.close()


def get_open_trades(db_path: Path | str | None = None) -> list[dict]:
    init_db(db_path)
    conn = get_connection(db_path)
    rows = conn.execute(
        "SELECT * FROM runway_v2_trades WHERE status = 'OPEN'"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_daily_trades(day: str, db_path: Path | str | None = None) -> list[dict]:
    init_db(db_path)
    conn = get_connection(db_path)
    rows = conn.execute(
        "SELECT * FROM runway_v2_trades WHERE entry_time LIKE ? ORDER BY id ASC",
        (f"{day}%",),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
