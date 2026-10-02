"""Atomic paper-only fills; daily usage is rebuilt from SQLite BUY fills."""
import json
import sqlite3
from contextlib import closing
from easystock_admin.store import db_path


def ledger_kind():
    """Read-only classification; migration is performed by the installer/Store."""
    path=db_path().resolve()
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=5)) as db:
        db.row_factory=sqlite3.Row
        cols={r[1] for r in db.execute('PRAGMA table_info(paper_trade_settings)')}
        if 'semantics_version' not in cols:
            return 'legacy'
        row=db.execute('SELECT semantics_version FROM paper_trade_settings WHERE id=1').fetchone()
        import paper_ledger
        if row and row[0] == paper_ledger.SEMANTICS:
            paper_ledger.period(db)
            return 'daily_limit'
        return 'legacy'


def _require_migrated():
    if ledger_kind() != 'daily_limit':
        raise RuntimeError('Paper daily limit migration required; run canonical updater')


def buy(symbol,name,price,execution_id=None):
    _require_migrated()
    import paper_ledger
    return paper_ledger.buy(symbol,name,price,path=db_path(),execution_id=execution_id)


def sell(symbol,price,reason='',trade_id=None):
    _require_migrated()
    import paper_ledger
    return paper_ledger.sell(symbol,price,reason,path=db_path(),trade_id=trade_id)


def open_positions():
    _require_migrated()
    import paper_ledger
    path=db_path().resolve()
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=5)) as db:
        db.row_factory=sqlite3.Row
        pid=paper_ledger.period(db)
        rows=db.execute('SELECT * FROM paper_trade_positions').fetchall()
        if any(r['period_id'] != pid for r in rows):
            raise RuntimeError('paper positions belong to another period')
        return [dict(dict(r),trade_id=paper_ledger.position_identity(db,r)) for r in rows]


def daily_bought_symbols(day):
    path=db_path().resolve()
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
        import paper_ledger
        db.row_factory=sqlite3.Row
        return {str(row[0]) for row in db.execute(
            "SELECT DISTINCT symbol FROM paper_trade_fills WHERE period_id=? AND trade_date=? AND side='BUY'",
            (paper_ledger.period(db),day))}


def settlement_receipt(trade_id):
    path=db_path().resolve()
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
        row=db.execute('SELECT value FROM meta WHERE key=?',('paper-settlement:'+str(trade_id),)).fetchone()
        return json.loads(row[0]) if row else None
