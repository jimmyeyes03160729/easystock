"""Atomic paper-only fills. No broker API; SQLite is the source of truth."""
import json
import math
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone, timedelta
from easystock_admin.store import db_path

TPE = timezone(timedelta(hours=8))
FEE_RATE = .001425 * .28
TAX_RATE = .0015


def valid_price(price):
    price = float(price)
    if not math.isfinite(price) or price <= 0:
        raise ValueError('invalid_price')
    return price


def _event(db, now, symbol, name, price, action, reason):
    db.execute('INSERT INTO paper_trade_events(date,time_str,symbol,name,price,action,reason,created_at) VALUES(?,?,?,?,?,?,?,?)',
               (now.date().isoformat(), now.strftime('%H:%M:%S'),symbol,name,price,action,reason,now.timestamp()))


def buy(symbol, name, price):
    symbol, name, price = str(symbol), str(name), valid_price(price)
    now = datetime.now(TPE)
    with closing(sqlite3.connect(db_path(),timeout=5)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        settings = db.execute('SELECT current_capital,status FROM paper_trade_settings WHERE id=1').fetchone()
        if not settings or settings[1] != 'running':
            return {'status':'stopped','shares':0}
        if db.execute('SELECT 1 FROM paper_trade_positions WHERE symbol=?',(symbol,)).fetchone():
            return {'status':'already_open','shares':0}
        capital = float(settings[0])
        held = db.execute('SELECT entry_price,shares FROM paper_trade_positions').fetchall()
        reserved = sum(p*q + max(20,round(p*q*FEE_RATE)) for p,q in held)
        budget = min(capital*.8, capital-reserved)
        shares = max(0,math.floor(budget/(price*1000))*1000)
        while shares and price*shares+max(20,round(price*shares*FEE_RATE)) > budget:
            shares -= 1000
        if not shares:
            _event(db,now,symbol,name,price,'略過','可用模擬資金不足（含持倉保留額與手續費）')
            return {'status':'insufficient_cash','shares':0}
        trade_id = uuid.uuid4().hex
        db.execute('INSERT INTO paper_trade_positions VALUES(?,?,?,?,?)',
                   (symbol,name,price,shares,now.isoformat()))
        db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',('paper-position:'+symbol,trade_id))
        _event(db,now,symbol,name,price,'買進',f'模擬成交 {shares} 股；trade_id={trade_id}')
        return {'status':'bought','shares':shares,'trade_id':trade_id}


def sell(symbol, price, reason='', trade_id=None):
    symbol, price = str(symbol), valid_price(price)
    now = datetime.now(TPE)
    with closing(sqlite3.connect(db_path(),timeout=5)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        if trade_id:
            receipt = db.execute('SELECT value FROM meta WHERE key=?',('paper-settlement:'+trade_id,)).fetchone()
            if receipt:
                return dict(json.loads(receipt[0]), already_settled=True)
        row = db.execute('SELECT name,entry_price,shares FROM paper_trade_positions WHERE symbol=?',(symbol,)).fetchone()
        if not row:
            return {'status':'no_position'}
        identity = db.execute('SELECT value FROM meta WHERE key=?',('paper-position:'+symbol,)).fetchone()
        actual_id = identity[0] if identity else 'legacy-'+uuid.uuid4().hex
        if trade_id and trade_id != actual_id:
            raise ValueError('paper_position_identity_mismatch')
        name, entry, shares = row
        settings = db.execute('SELECT current_capital FROM paper_trade_settings WHERE id=1').fetchone()
        if not settings:
            raise ValueError('paper_settings_missing')
        start = float(settings[0])
        costs = max(20,round(entry*shares*FEE_RATE))+max(20,round(price*shares*FEE_RATE))+round(price*shares*TAX_RATE)
        pnl = round((price-entry)*shares-costs,2)
        end = round(start+pnl,2)
        day = now.date().isoformat()
        previous = db.execute('SELECT start_balance,net_pnl,symbols,costs,trades_count FROM paper_trade_logs WHERE date=?',(day,)).fetchone()
        daily = (previous[0],previous[1]+pnl,previous[2]+','+symbol,previous[3]+costs,previous[4]+1) if previous else (start,pnl,symbol,costs,1)
        db.execute('INSERT OR REPLACE INTO paper_trade_logs VALUES(?,?,?,?,?,?,?,?)',
                   (day,daily[0],end,daily[1],daily[2],daily[3],daily[4],now.timestamp()))
        db.execute('UPDATE paper_trade_settings SET current_capital=?,updated_at=? WHERE id=1',(end,now.timestamp()))
        db.execute('DELETE FROM paper_trade_positions WHERE symbol=?',(symbol,))
        db.execute('DELETE FROM meta WHERE key=?',('paper-position:'+symbol,))
        result = dict(status='sold',trade_id=actual_id,date=day,start_balance=start,end_balance=end,net_pnl=pnl,costs=costs)
        db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',('paper-settlement:'+actual_id,json.dumps(result)))
        _event(db,now,symbol,name,price,'賣出',f'{reason}；淨損益 {pnl:+.2f}；trade_id={actual_id}')
        return result


def open_positions():
    with closing(sqlite3.connect(db_path(),timeout=5)) as db:
        rows = db.execute('SELECT p.symbol,p.name,p.entry_price,p.shares,p.entry_time,m.value FROM paper_trade_positions p LEFT JOIN meta m ON m.key=\'paper-position:\'||p.symbol').fetchall()
        return [dict(zip(('symbol','name','entry_price','shares','entry_time','trade_id'),r)) for r in rows]
