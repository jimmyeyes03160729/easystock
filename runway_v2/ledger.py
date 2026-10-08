"""Runway V2: 獨立 SQLite 模擬帳本
專屬資料表結構，與主帳本 state.sqlite 徹底隔離，零干擾。
"""
from __future__ import annotations
import sqlite3
import time
from pathlib import Path
from .config import DB_DIR, DB_PATH

# PositionManagerV2.update_price 分批停利那一腿的 exit_reason (manager.py 釘選，不可改)
PARTIAL_EXIT_REASON = "分批停利 50%"


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
    """每一腿出場呼叫一次 (分批停利 50% 與剩餘部位各一次)。
    gross_pnl / fee / tax / net_pnl 逐腿累加，exit_time / exit_price / exit_reason / return_pct 為最後一腿。
    """
    conn = get_connection(db_path)
    with conn:
        conn.execute(
            """
            UPDATE runway_v2_trades SET
                exit_time = ?,
                exit_price = ?,
                exit_reason = ?,
                gross_pnl = COALESCE(gross_pnl, 0) + ?,
                fee = COALESCE(fee, 0) + ?,
                tax = COALESCE(tax, 0) + ?,
                net_pnl = COALESCE(net_pnl, 0) + ?,
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


# ---------------------------------------------------------------------------
# 盤中部位狀態 sidecar (重啟還原用)
# runway_v2_trades 只存進場股數與出場結果；停損價、最高價、分批/移動停利旗標與剩餘股數
# 由 runner 寫入此表，重啟後 runway_v2/restore.py 用來重建 PositionManagerV2.positions。
# 全數平倉或遺留處理後刪除該列，因此表內只有「仍在盤中管理」的部位。
# ---------------------------------------------------------------------------
ORPHANED = "ORPHANED"


def init_position_state(db_path: Path | str | None = None) -> None:
    conn = get_connection(db_path)
    with conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS runway_v2_position_state (
            trade_id TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            shares INTEGER NOT NULL,
            stop_price REAL NOT NULL,
            highest_price REAL NOT NULL,
            current_price REAL NOT NULL,
            half_closed INTEGER NOT NULL DEFAULT 0,
            trailing_active INTEGER NOT NULL DEFAULT 0,
            price_time TEXT,
            updated_at REAL NOT NULL
        )
        """)
    conn.close()


def save_position_state(
    trade_id: str,
    symbol: str,
    shares: int,
    stop_price: float,
    highest_price: float,
    current_price: float,
    half_closed: bool,
    trailing_active: bool,
    price_time: str | None = None,
    db_path: Path | str | None = None,
) -> None:
    conn = get_connection(db_path)
    with conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO runway_v2_position_state (
                trade_id, symbol, shares, stop_price, highest_price, current_price,
                half_closed, trailing_active, price_time, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trade_id,
                symbol,
                int(shares),
                float(stop_price),
                float(highest_price),
                float(current_price),
                1 if half_closed else 0,
                1 if trailing_active else 0,
                price_time,
                time.time(),
            ),
        )
    conn.close()


def delete_position_state(trade_id: str, db_path: Path | str | None = None) -> None:
    conn = get_connection(db_path)
    with conn:
        conn.execute("DELETE FROM runway_v2_position_state WHERE trade_id = ?", (trade_id,))
    conn.close()


def load_position_states(db_path: Path | str | None = None) -> dict[str, dict]:
    init_position_state(db_path)
    conn = get_connection(db_path)
    rows = conn.execute("SELECT * FROM runway_v2_position_state").fetchall()
    conn.close()
    return {r["trade_id"]: dict(r) for r in rows}


def get_unfinished_trades(db_path: Path | str | None = None) -> list[dict]:
    """仍有股數在手的交易：OPEN，或最後一腿是分批停利 50% 的 CLOSED (剩餘一半尚未出場)。
    剩餘部位出場時 record_exit 會覆寫 exit_reason，因此「最後一腿為分批停利」即代表剩餘部位未平倉。
    """
    init_db(db_path)
    conn = get_connection(db_path)
    rows = conn.execute(
        "SELECT * FROM runway_v2_trades WHERE status = 'OPEN' "
        "OR (status = 'CLOSED' AND exit_reason = ?) ORDER BY id ASC",
        (PARTIAL_EXIT_REASON,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_orphaned(
    trade_id: str,
    resolved_time: str,
    note: str,
    db_path: Path | str | None = None,
) -> None:
    """前一交易日遺留、沒有出場價的部位。
    OPEN 列改為 status='ORPHANED' (無出場價、損益留空，不算成交筆數)；
    已分批停利的列維持 CLOSED 與第一腿損益，只在 exit_reason 註明剩餘部位遺留。
    exit_time 記處理當下，exit_price 不寫入，不捏造價格。
    """
    conn = get_connection(db_path)
    with conn:
        conn.execute(
            "UPDATE runway_v2_trades SET status = ?, exit_time = ?, exit_reason = ? "
            "WHERE trade_id = ? AND status = 'OPEN'",
            (ORPHANED, resolved_time, note, trade_id),
        )
        conn.execute(
            "UPDATE runway_v2_trades SET exit_reason = ? "
            "WHERE trade_id = ? AND status = 'CLOSED' AND exit_reason = ?",
            (f"{PARTIAL_EXIT_REASON}；{note}", trade_id, PARTIAL_EXIT_REASON),
        )
        conn.execute("DELETE FROM runway_v2_position_state WHERE trade_id = ?", (trade_id,))
    conn.close()
