"""Isolated cash-ledger paper trading; no broker orders; all mutations are SQLite transactions.
The installer must initialize/rotate a period before this module is used.
"""
from __future__ import annotations
import datetime as dt
import json
import uuid
import math
import os
import sqlite3
import time
from contextlib import contextmanager
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

TPE = dt.timezone(dt.timedelta(hours=8))
BUY_RATE = Decimal('0.001425') * Decimal('0.28')
SELL_RATE = BUY_RATE
DAY_TAX_RATE = Decimal('0.0015')  # Only simulated eligible same-day stock day trades.
LOT = 1000


def path_default():
    return Path(os.environ.get('EASYSTOCK_ADMIN_DB', '/home/ubuntu/easystock-admin/state.sqlite'))


def d(x):
    v = Decimal(str(x))
    if not v.is_finite():
        raise ValueError('invalid nonfinite number')
    return v


def money(x):
    return d(x).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def fee(amount, rate):
    return max(Decimal('20'), (d(amount) * rate).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def now():
    return dt.datetime.now(TPE)


def datetime_tpe(value=None):
    if value is None:
        return now()
    if isinstance(value, dt.datetime):
        if value.tzinfo is None:
            raise ValueError('exit timestamp must include timezone')
        return value.astimezone(TPE)
    if isinstance(value, str):
        parsed = dt.datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            raise ValueError('exit timestamp must include timezone')
        return parsed.astimezone(TPE)
    raise ValueError('invalid exit timestamp')


@contextmanager
def transaction(path=None):
    p = Path(path or path_default())
    con = sqlite3.connect(p, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA busy_timeout=15000')
    try:
        con.execute('BEGIN IMMEDIATE')
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def init_schema(con):
    con.execute('''CREATE TABLE IF NOT EXISTS paper_trade_fills (
       id INTEGER PRIMARY KEY AUTOINCREMENT,
       period_id TEXT NOT NULL,
       transaction_id TEXT NOT NULL UNIQUE,
       trade_date TEXT NOT NULL,
       event_time TEXT NOT NULL,
       side TEXT NOT NULL CHECK (side IN ('BUY','SELL')),
       symbol TEXT NOT NULL, name TEXT NOT NULL,
       price REAL NOT NULL, shares INTEGER NOT NULL,
       gross REAL NOT NULL, fee REAL NOT NULL, tax REAL NOT NULL,
       realized_pnl REAL NOT NULL, cash_after REAL NOT NULL,
       reason TEXT NOT NULL DEFAULT ''
    )''')
    con.execute('''CREATE TABLE IF NOT EXISTS paper_trade_periods (
       id TEXT PRIMARY KEY, created_at TEXT NOT NULL,
       starting_cash REAL NOT NULL, archive_path TEXT NOT NULL
    )''')
    cols = {r[1] for r in con.execute('PRAGMA table_info(paper_trade_positions)')}
    for name, declaration in {
        'period_id':'TEXT', 'entry_date':'TEXT', 'buy_fee':'REAL NOT NULL DEFAULT 0',
    }.items():
        if name not in cols:
            con.execute(f'ALTER TABLE paper_trade_positions ADD COLUMN {name} {declaration}')
    cols = {r[1] for r in con.execute('PRAGMA table_info(paper_trade_logs)')}
    for name, declaration in {
        'period_id':'TEXT', "settlement_status":"TEXT NOT NULL DEFAULT 'pending'"
    }.items():
        if name not in cols:
            con.execute(f'ALTER TABLE paper_trade_logs ADD COLUMN {name} {declaration}')


def period(con):
    r = con.execute("SELECT value FROM meta WHERE key='paper_trade_period_current'").fetchone()
    if not r:
        raise RuntimeError('Paper trading period not initialized; run offline installer')
    pid = r['value']
    if not con.execute('SELECT 1 FROM paper_trade_periods WHERE id=?', (pid,)).fetchone():
        raise RuntimeError('paper period metadata missing')
    return pid


def account(con):
    r = con.execute('SELECT * FROM paper_trade_settings WHERE id=1').fetchone()
    if not r:
        raise RuntimeError('paper_trade_settings missing')
    return r


def open_positions(con, pid):
    return con.execute('SELECT * FROM paper_trade_positions WHERE period_id=? ORDER BY entry_date,entry_time', (pid,)).fetchall()


def event(con, stamp, symbol, name, price, action, reason):
    con.execute('''INSERT INTO paper_trade_events(date,time_str,symbol,name,price,action,reason,created_at)
       VALUES(?,?,?,?,?,?,?,?)''', (stamp.date().isoformat(), stamp.strftime('%H:%M:%S'),
       symbol, name, float(price), action, reason, time.time()))


def skipped(con, stamp, symbol, name, price, reason):
    event(con, stamp, symbol, name, price, '略過', reason)
    return {'status':'skipped', 'reason':reason, 'shares':0}


def buy(symbol, name, price, path=None, timestamp=None):
    stamp = datetime_tpe(timestamp)
    symbol, name, price = str(symbol), str(name), d(price)
    if price <= 0 or price > Decimal('10000000'):
        raise ValueError('invalid buy price')
    with transaction(path) as con:
        pid, acct = period(con), account(con)
        if acct['status'] != 'running':
            return skipped(con, stamp, symbol, name, price, '模擬帳戶已暫停')
        if con.execute('SELECT 1 FROM paper_trade_positions WHERE symbol=?', (symbol,)).fetchone():
            return skipped(con, stamp, symbol, name, price, '本期此檔已持倉，禁止覆蓋原部位')
        stale = con.execute('SELECT symbol FROM paper_trade_positions WHERE period_id IS NULL OR period_id!=? OR entry_date IS NULL OR entry_date!=?', (pid, stamp.date().isoformat())).fetchall()
        if stale:
            return skipped(con, stamp, symbol, name, price, '存在跨日未結部位，禁止新增模擬買進')
        cash = money(acct['current_capital'])
        max_budget = cash * Decimal('0.8')
        shares = int(max_budget // (price * LOT)) * LOT
        while shares > 0:
            gross = money(price * shares)
            buy_fee = fee(gross, BUY_RATE)
            if gross + buy_fee <= cash and gross <= max_budget:
                break
            shares -= LOT
        if shares <= 0:
            return skipped(con, stamp, symbol, name, price,
                           f'可用現金 {cash:,.2f} 元不足以支付一張買進成本與手續費（單檔上限八成）')
        trade_id = uuid.uuid4().hex
        after = money(cash - gross - buy_fee)
        con.execute('''INSERT INTO paper_trade_positions(symbol,name,entry_price,shares,entry_time,period_id,entry_date,buy_fee)
           VALUES(?,?,?,?,?,?,?,?)''', (symbol,name,float(price),shares,stamp.isoformat(),pid,stamp.date().isoformat(),float(buy_fee)))
        con.execute('UPDATE paper_trade_settings SET current_capital=?,updated_at=? WHERE id=1', (float(after),time.time()))
        event(con, stamp, symbol, name, price, '買進',
              f'成交 {shares} 股；成交金額 {gross:,.2f} 元；買進手續費 {buy_fee:,.2f} 元；剩餘現金 {after:,.2f} 元')
        con.execute('''INSERT INTO paper_trade_fills(period_id,transaction_id,trade_date,event_time,side,symbol,name,price,shares,gross,fee,tax,realized_pnl,cash_after,reason)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
          (pid,trade_id,stamp.date().isoformat(),stamp.isoformat(),'BUY',symbol,name,float(price),shares,
           float(gross),float(buy_fee),0.0,0.0,float(after),'買進'))
        con.execute('INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)', ('paper-position:'+symbol,trade_id))
        refresh_day(con,pid,stamp.date().isoformat())
        return {'trade_id':trade_id, 'status':'bought','symbol':symbol,'shares':shares,'cash':float(after),'cost':float(gross),'buy_fee':float(buy_fee)}


def sell(symbol, exit_price, reason='', path=None, timestamp=None, trade_id=None):
    stamp = datetime_tpe(timestamp)
    symbol, exit_price = str(symbol), d(exit_price)
    if exit_price <= 0 or exit_price > Decimal('10000000'):
        raise ValueError('invalid exit price')
    with transaction(path) as con:
        if trade_id:
            receipt = con.execute('SELECT value FROM meta WHERE key=?', ('paper-settlement:'+trade_id,)).fetchone()
            if receipt:
                return dict(json.loads(receipt['value']), already_settled=True)
        pid, acct = period(con), account(con)
        r = con.execute('SELECT * FROM paper_trade_positions WHERE symbol=? AND period_id=?',(symbol,pid)).fetchone()
        if not r:
            return {'status':'no_position','symbol':symbol}
        if str(r['entry_date']) != stamp.date().isoformat():
            raise RuntimeError(f'跨日殘留持倉 {symbol}：禁止使用另一交易日行情自動補賣')
        actual_id = position_identity(con,r)
        if trade_id and trade_id != actual_id:
            raise ValueError('paper_position_identity_mismatch')
        shares = int(r['shares'])
        gross = money(exit_price * shares)
        sell_fee, tax = fee(gross, SELL_RATE), money(gross * DAY_TAX_RATE).quantize(Decimal('1'),rounding=ROUND_HALF_UP)
        entry_amount, buy_fee = money(d(r['entry_price']) * shares), money(r['buy_fee'])
        pnl = money(gross - entry_amount - buy_fee - sell_fee - tax)
        after = money(d(acct['current_capital']) + gross - sell_fee - tax)
        con.execute('DELETE FROM paper_trade_positions WHERE symbol=? AND period_id=?',(symbol,pid))
        con.execute('UPDATE paper_trade_settings SET current_capital=?,updated_at=? WHERE id=1',(float(after),time.time()))
        event(con, stamp, symbol, str(r['name']), exit_price, '賣出',
              f'{reason}；賣出 {shares} 股；賣出金額 {gross:,.2f} 元；已實現淨損益 {pnl:+,.2f} 元；剩餘現金 {after:,.2f} 元')
        con.execute('''INSERT INTO paper_trade_fills(period_id,transaction_id,trade_date,event_time,side,symbol,name,price,shares,gross,fee,tax,realized_pnl,cash_after,reason)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
          (pid,f'{pid}:SELL:{symbol}:{stamp.isoformat()}',stamp.date().isoformat(),stamp.isoformat(),'SELL',symbol,r['name'],float(exit_price),shares,
           float(gross),float(sell_fee),float(tax),float(pnl),float(after),str(reason)))
        refresh_day(con,pid,stamp.date().isoformat())
        result = {'status':'sold','symbol':symbol,'shares':shares,'cash':float(after),
                  'end_balance':float(after),'net_pnl':float(pnl),
                  'costs':float(buy_fee+sell_fee+tax),'trade_id':actual_id}
        con.execute('INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)',
                    ('paper-settlement:'+actual_id,json.dumps(result)))
        con.execute('DELETE FROM meta WHERE key=?', ('paper-position:'+symbol,))
        return result


def refresh_day(con, pid, day):
    acct = account(con)
    fills = con.execute('SELECT * FROM paper_trade_fills WHERE period_id=? AND trade_date=? ORDER BY id',(pid,day)).fetchall()
    if not fills:
        return None
    prev = con.execute('''SELECT end_balance FROM paper_trade_logs WHERE period_id=? AND date<? AND settlement_status='settled'
       ORDER BY date DESC LIMIT 1''',(pid,day)).fetchone()
    base = money(prev['end_balance']) if prev else money(acct['initial_capital'])
    realized = sum((money(r['realized_pnl']) for r in fills if r['side']=='SELL'),Decimal('0'))
    names = ', '.join(dict.fromkeys(r['symbol']+' '+r['name'] for r in fills if r['side']=='SELL'))
    costs = sum((money(r['fee'])+money(r['tax']) for r in fills),Decimal('0'))
    count = sum(r['side']=='SELL' for r in fills)
    pending = con.execute('SELECT COUNT(*) n FROM paper_trade_positions WHERE period_id=?',(pid,)).fetchone()['n']
    # The log is finalized only when all positions are closed. During the day, it is not a final equity statement.
    status = 'pending' if pending else 'settled'
    closing = money(acct['current_capital']) if not pending else base + realized
    net = money(closing-base) if not pending else money(realized)
    con.execute('''INSERT INTO paper_trade_logs(date,start_balance,end_balance,net_pnl,symbols,costs,trades_count,created_at,period_id,settlement_status)
       VALUES(?,?,?,?,?,?,?,?,?,?)
       ON CONFLICT(date) DO UPDATE SET start_balance=excluded.start_balance,end_balance=excluded.end_balance,
       net_pnl=excluded.net_pnl,symbols=excluded.symbols,costs=excluded.costs,trades_count=excluded.trades_count,
       created_at=excluded.created_at,period_id=excluded.period_id,settlement_status=excluded.settlement_status''',
       (day,float(base),float(closing),float(net),names,float(costs),count,time.time(),pid,status))
    return {'date':day,'status':status,'net_pnl':float(net),'trades_count':count}


def finalize_today(path=None):
    stamp = now()
    with transaction(path) as con:
        pid = period(con)
        positions = open_positions(con,pid)
        if any(r['entry_date'] != stamp.date().isoformat() for r in positions):
            raise RuntimeError('有跨日殘留持倉：須人工核對，禁止自動結算')
        result = refresh_day(con,pid,stamp.date().isoformat())
        if result:
            return result
        if positions:
            return {'date':stamp.date().isoformat(),'status':'pending','reason':'open positions without fills'}
        acct=account(con)
        prev=con.execute('SELECT end_balance FROM paper_trade_logs WHERE period_id=? AND settlement_status=? ORDER BY date DESC LIMIT 1',(pid,'settled')).fetchone()
        base=money(prev['end_balance']) if prev else money(acct['initial_capital'])
        final_cash=money(acct['current_capital'])
        con.execute('''INSERT INTO paper_trade_logs(date,start_balance,end_balance,net_pnl,symbols,costs,trades_count,created_at,period_id,settlement_status)
            VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(date) DO NOTHING''',
            (stamp.date().isoformat(),float(base),float(final_cash),float(final_cash-base),'',0.0,0,time.time(),pid,'settled'))
        return {'date':stamp.date().isoformat(),'status':'settled','trades_count':0}



def snapshot(path=None):
    p = Path(path or path_default())
    with sqlite3.connect(p,timeout=5) as con:
        con.row_factory=sqlite3.Row
        pid=period(con)
        acct=account(con)
        positions=[dict(r) for r in open_positions(con,pid)]
        cash=money(acct['current_capital'])
        position_cost=sum((money(d(r['entry_price'])*int(r['shares'])) for r in positions),Decimal('0'))
        realized=con.execute("SELECT COALESCE(SUM(realized_pnl),0) v FROM paper_trade_fills WHERE period_id=? AND side='SELL'",(pid,)).fetchone()['v']
        fills=con.execute('SELECT COUNT(*) n FROM paper_trade_fills WHERE period_id=?',(pid,)).fetchone()['n']
        today=now().date().isoformat()
        events=[{'time':r['time_str'],'symbol':r['symbol'],'name':r['name'],'price':r['price'],
                 'action':r['action'],'reason':r['reason']} for r in con.execute('''SELECT time_str,symbol,name,price,action,reason FROM paper_trade_events WHERE date=? ORDER BY id DESC LIMIT 100''',(today,))]
        logs=[{'date':r['date'],'start_balance':r['start_balance'],'end_balance':r['end_balance'],
               'net_pnl':r['net_pnl'],'symbols':r['symbols'],'costs':r['costs'],'trades_count':r['trades_count'],
               'status':r['settlement_status']} for r in con.execute('''SELECT * FROM paper_trade_logs WHERE period_id=? ORDER BY date DESC LIMIT 30''',(pid,))]
        return {'settings':{k:acct[k] for k in ('initial_capital','current_capital','status','start_date','updated_at')},
                'period_id':pid,'positions':positions,'events':events,'logs':logs,
                'summary':{'cash':float(cash),'position_cost':float(position_cost),
                           'equity_at_cost':float(cash+position_cost),'realized_pnl':float(money(realized)),
                           'unrealized_pnl':None,'open_positions':len(positions),'fills':fills,
                           'pending':bool(positions)}}


def toggle(path=None):
    with transaction(path) as con:
        pid, acct=period(con),account(con)
        if acct['status']=='running':
            next_status='stopped'
        else:
            positions=open_positions(con,pid)
            if positions and any(r['entry_date'] != now().date().isoformat() for r in positions):
                raise ValueError('存在跨日未結部位；禁止啟動新交易，請先核對／封存')
            next_status='running'
        con.execute('UPDATE paper_trade_settings SET status=?,updated_at=? WHERE id=1',(next_status,time.time()))
    return snapshot(path)


def position_identity(con, row):
    saved = con.execute('SELECT value FROM meta WHERE key=?', ('paper-position:'+row['symbol'],)).fetchone()
    if saved:
        return saved['value']
    # Recover identities of positions created by the pre-existing cash ledger.
    fill = con.execute("SELECT transaction_id FROM paper_trade_fills WHERE period_id=? AND symbol=? AND side='BUY' AND event_time=? ORDER BY id DESC LIMIT 1",
                       (row['period_id'],row['symbol'],row['entry_time'])).fetchone()
    if not fill:
        raise RuntimeError('paper position has no matching BUY fill')
    return fill['transaction_id']
