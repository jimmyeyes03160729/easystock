"""Daily BUY-notional limit, independent performance; no broker orders.
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
SEMANTICS = 'daily-buy-limit-v1'


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
    additions = {
        'paper_trade_settings': {'daily_buy_limit':'REAL', 'performance_base':'REAL',
            'legacy_pnl_adjustment':'REAL', 'semantics_version':'TEXT', 'migration_date':'TEXT'},
        'paper_trade_periods': {'daily_buy_limit':'REAL','performance_base':'REAL','semantics_version':'TEXT'},
        'paper_trade_fills': {'buy_limit_remaining_after':'REAL','semantics_version':'TEXT'},
        'paper_trade_logs': {'daily_buy_limit':'REAL','daily_buy_used':'REAL','buy_fees':'REAL',
            'sell_fees':'REAL','tax':'REAL','gross_pnl':'REAL','semantics_version':'TEXT'},
    }
    for table, fields in additions.items():
        columns = {r[1] for r in con.execute(f'PRAGMA table_info({table})')}
        for name, declaration in fields.items():
            if name not in columns:
                con.execute(f'ALTER TABLE {table} ADD COLUMN {name} {declaration}')
    con.execute('CREATE INDEX IF NOT EXISTS paper_daily_buy ON paper_trade_fills(period_id,trade_date,side)')


def migrate(con):
    """Additive and idempotent. Never change fills, logs or position values."""
    init_schema(con)
    con.row_factory = sqlite3.Row
    acct = con.execute('SELECT * FROM paper_trade_settings WHERE id=1').fetchone()
    if not acct:
        return
    saved = con.execute("SELECT value FROM meta WHERE key='paper_trade_period_current'").fetchone()
    if not saved:
        if con.execute('SELECT 1 FROM paper_trade_fills LIMIT 1').fetchone():
            raise RuntimeError('Existing fills without period metadata require reconciliation')
        if con.execute('SELECT 1 FROM paper_trade_positions LIMIT 1').fetchone():
            raise RuntimeError('Legacy positions without BUY fills require reconciliation')
        pid = uuid.uuid4().hex
        con.execute('INSERT INTO paper_trade_periods(id,created_at,starting_cash,archive_path,daily_buy_limit,performance_base,semantics_version) VALUES(?,?,?,?,?,?,?)',
            (pid,now().isoformat(),acct['initial_capital'],'',acct['initial_capital'],acct['initial_capital'],SEMANTICS))
        con.execute("INSERT INTO meta(key,value) VALUES('paper_trade_period_current',?)",(pid,))
    pid = period(con)
    if con.execute('SELECT 1 FROM paper_trade_positions WHERE period_id IS NULL OR period_id!=? LIMIT 1',(pid,)).fetchone():
        raise RuntimeError('Unreconciled legacy positions; migration cannot fabricate BUY fills')
    if acct['semantics_version'] == SEMANTICS:
        if acct['daily_buy_limit'] is None or acct['performance_base'] is None or acct['legacy_pnl_adjustment'] is None:
            raise RuntimeError('Incomplete daily limit migration')
        return
    if acct['semantics_version'] is not None:
        raise RuntimeError('Unsupported paper account semantics')
    today=now().date().isoformat()
    if (con.execute("SELECT 1 FROM paper_trade_events WHERE date=? AND action='買進' LIMIT 1",(today,)).fetchone()
            and not con.execute("SELECT 1 FROM paper_trade_fills WHERE period_id=? AND trade_date=? AND side='BUY' LIMIT 1",(pid,today)).fetchone()):
        raise RuntimeError('Today has legacy BUY events without fills; daily usage requires reconciliation')
    realized = sum((money(r[0]) for r in con.execute("SELECT realized_pnl FROM paper_trade_fills WHERE period_id=? AND side='SELL'",(pid,))),Decimal(0))
    positions = open_positions(con,pid)
    cost = sum((money(d(r['entry_price'])*r['shares']) for r in positions),Decimal(0))
    open_fees = sum((money(r['buy_fee']) for r in positions),Decimal(0))
    adjustment = money(d(acct['current_capital'])+cost-d(acct['initial_capital'])-realized+open_fees)
    con.execute('UPDATE paper_trade_settings SET daily_buy_limit=initial_capital,performance_base=initial_capital,legacy_pnl_adjustment=?,semantics_version=?,migration_date=? WHERE id=1',
                (float(adjustment),SEMANTICS,now().date().isoformat()))


def daily_metrics(con, pid, day):
    acct = account(con)
    if acct['semantics_version'] != SEMANTICS:
        raise RuntimeError('Daily limit migration required')
    rows = con.execute('SELECT * FROM paper_trade_fills WHERE period_id=? AND trade_date=? ORDER BY id',(pid,day)).fetchall()
    used = sum((money(r['gross']) for r in rows if r['side']=='BUY'),Decimal(0))
    buy_fees = sum((money(r['fee']) for r in rows if r['side']=='BUY'),Decimal(0))
    sell_fees = sum((money(r['fee']) for r in rows if r['side']=='SELL'),Decimal(0))
    tax = sum((money(r['tax']) for r in rows),Decimal(0))
    closed = [r for r in rows if r['side']=='SELL']
    gross_pnl = Decimal(0)
    for sell_row in closed:
        entry = next((r for r in reversed(rows) if r['side']=='BUY' and r['symbol']==sell_row['symbol'] and r['id']<sell_row['id']),None)
        if entry is None:
            raise RuntimeError('SELL without same-day BUY evidence')
        gross_pnl += money(sell_row['realized_pnl'])+money(entry['fee'])+money(sell_row['fee'])+money(sell_row['tax'])
    limit = money(acct['daily_buy_limit'])
    net = money(gross_pnl-buy_fees-sell_fees-tax)
    realized = sum((money(r[0]) for r in con.execute("SELECT realized_pnl FROM paper_trade_fills WHERE period_id=? AND side='SELL'",(pid,))),Decimal(0))
    open_fees = sum((money(r['buy_fee']) for r in open_positions(con,pid)),Decimal(0))
    cumulative = money(d(acct['legacy_pnl_adjustment'])+realized-open_fees)
    return {'trade_date':day,'daily_buy_limit':float(limit),'daily_buy_used':float(used),
        'daily_buy_remaining':float(max(Decimal(0),limit-used)), 'realized_pnl':float(money(gross_pnl)),
        'buy_fees':float(buy_fees),'sell_fees':float(sell_fees),'fees':float(buy_fees+sell_fees),
        'tax':float(tax),'net_pnl':float(net),'trades_count':len(closed),
        'wins':sum(r['realized_pnl']>0 for r in closed),'losses':sum(r['realized_pnl']<=0 for r in closed),
        'return_pct':float(net/used*100) if used else None,
        'limit_utilization_pct':float(used/limit*100) if limit else None,
        'performance_base':float(acct['performance_base']), 'cumulative_net_pnl':float(cumulative),
        'equity':float(money(d(acct['performance_base'])+cumulative)), 'semantics_version':SEMANTICS}


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


def skipped(con, stamp, symbol, name, price, reason, skip_reason=None):
    event(con, stamp, symbol, name, price, '略過', reason)
    return {'status':'skipped', 'reason':reason, 'shares':0, 'skip_reason': skip_reason}


def buy(symbol, name, price, path=None, timestamp=None, execution_id=None):
    stamp = datetime_tpe(timestamp)
    symbol, name, price = str(symbol), str(name), d(price)
    if price <= 0 or price > Decimal('10000000'):
        raise ValueError('invalid buy price')
    with transaction(path) as con:
        if execution_id:
            previous=con.execute('SELECT value FROM meta WHERE key=?',('paper-buy:'+str(execution_id),)).fetchone()
            if previous:
                receipt=json.loads(previous['value'])
                if receipt['symbol'] != symbol or d(receipt['entry_price']) != price or receipt['trade_date'] != stamp.date().isoformat():
                    raise ValueError('paper_buy_identity_mismatch')
                return dict(receipt,already_bought=True)
        pid, acct = period(con), account(con)
        if acct['status'] != 'running':
            return skipped(con, stamp, symbol, name, price, '模擬帳戶已暫停', skip_reason='stopped')
        if con.execute('SELECT 1 FROM paper_trade_positions WHERE symbol=?', (symbol,)).fetchone():
            return skipped(con, stamp, symbol, name, price, '本期此檔已持倉，禁止覆蓋原部位', skip_reason='already_open')
        stale = con.execute('SELECT symbol FROM paper_trade_positions WHERE period_id IS NULL OR period_id!=? OR entry_date IS NULL OR entry_date!=?', (pid, stamp.date().isoformat())).fetchall()
        if stale:
            return skipped(con, stamp, symbol, name, price, '存在跨日未結部位，禁止新增模擬買進', skip_reason='stale_position')
        metrics = daily_metrics(con,pid,stamp.date().isoformat())
        remaining = money(metrics['daily_buy_remaining'])
        shares = int(remaining // (price * LOT)) * LOT
        while shares > 0:
            gross = money(price * shares)
            buy_fee = fee(gross, BUY_RATE)
            if gross <= remaining:
                break
            shares -= LOT
        if shares <= 0:
            return skipped(con, stamp, symbol, name, price,
                           f'今日剩餘買進額度 {remaining:,.2f} 元不足以買進一張',
                           skip_reason='daily_buy_limit_exceeded')
        trade_id = uuid.uuid4().hex
        after = money(remaining - gross)
        con.execute('''INSERT INTO paper_trade_positions(symbol,name,entry_price,shares,entry_time,period_id,entry_date,buy_fee)
           VALUES(?,?,?,?,?,?,?,?)''', (symbol,name,float(price),shares,stamp.isoformat(),pid,stamp.date().isoformat(),float(buy_fee)))
        event(con, stamp, symbol, name, price, '買進',
              f'成交 {shares} 股；買進手續費 {buy_fee:,.2f} 元；今日已用買進額度 {metrics["daily_buy_used"]+float(gross):,.2f} 元；今日剩餘買進額度 {after:,.2f} 元')
        con.execute('''INSERT INTO paper_trade_fills(period_id,transaction_id,trade_date,event_time,side,symbol,name,price,shares,gross,fee,tax,realized_pnl,cash_after,reason,buy_limit_remaining_after,semantics_version)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
          (pid,trade_id,stamp.date().isoformat(),stamp.isoformat(),'BUY',symbol,name,float(price),shares,
           float(gross),float(buy_fee),0.0,0.0,float(after),'買進',float(after),SEMANTICS))
        con.execute('INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)', ('paper-position:'+symbol,trade_id))
        refresh_day(con,pid,stamp.date().isoformat())
        result={'trade_id':trade_id, 'status':'bought','symbol':symbol,'shares':shares,
                'daily_buy_remaining':float(after),'cost':float(gross),'buy_fee':float(buy_fee),
                'entry_price':float(price),'trade_date':stamp.date().isoformat()}
        if execution_id:
            con.execute('INSERT INTO meta(key,value) VALUES(?,?)',('paper-buy:'+str(execution_id),json.dumps(result)))
        return result


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
        after = money(daily_metrics(con,pid,stamp.date().isoformat())['daily_buy_remaining'])
        con.execute('DELETE FROM paper_trade_positions WHERE symbol=? AND period_id=?',(symbol,pid))
        event(con, stamp, symbol, str(r['name']), exit_price, '賣出',
              f'{reason}；賣出 {shares} 股；已實現淨損益 {pnl:+,.2f} 元；今日剩餘買進額度 {after:,.2f} 元（賣出不回補）')
        con.execute('''INSERT INTO paper_trade_fills(period_id,transaction_id,trade_date,event_time,side,symbol,name,price,shares,gross,fee,tax,realized_pnl,cash_after,reason,buy_limit_remaining_after,semantics_version)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
          (pid,f'{pid}:SELL:{actual_id}',stamp.date().isoformat(),stamp.isoformat(),'SELL',symbol,r['name'],float(exit_price),shares,
           float(gross),float(sell_fee),float(tax),float(pnl),float(after),str(reason),float(after),SEMANTICS))
        refresh_day(con,pid,stamp.date().isoformat())
        result = {'status':'sold','symbol':symbol,'shares':shares,'daily_buy_remaining':float(after),
                  'equity':daily_metrics(con,pid,stamp.date().isoformat())['equity'],'net_pnl':float(pnl),
                  'costs':float(buy_fee+sell_fee+tax),'trade_id':actual_id}
        con.execute('INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)',
                    ('paper-settlement:'+actual_id,json.dumps(result)))
        con.execute('DELETE FROM meta WHERE key=?', ('paper-position:'+symbol,))
        return result


def refresh_day(con, pid, day):
    metrics = daily_metrics(con,pid,day)
    pending = bool(open_positions(con,pid))
    status = 'pending' if pending else 'settled'
    # Preserve cash-era historical summaries. Migration itself never refreshes logs.
    previous = con.execute('SELECT * FROM paper_trade_logs WHERE date=?',(day,)).fetchone()
    if previous and previous['semantics_version'] is None and day < account(con)['migration_date']:
        return {'date':day,'status':previous['settlement_status'],'net_pnl':previous['net_pnl'],'trades_count':previous['trades_count']}
    names = ', '.join(dict.fromkeys(r['symbol']+' '+r['name'] for r in con.execute("SELECT symbol,name FROM paper_trade_fills WHERE period_id=? AND trade_date=? AND side='SELL'",(pid,day))))
    con.execute('''INSERT INTO paper_trade_logs(date,start_balance,end_balance,net_pnl,symbols,costs,trades_count,created_at,period_id,settlement_status,daily_buy_limit,daily_buy_used,buy_fees,sell_fees,tax,gross_pnl,semantics_version)
       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
       ON CONFLICT(date) DO UPDATE SET start_balance=excluded.start_balance,end_balance=excluded.end_balance,
       net_pnl=excluded.net_pnl,symbols=excluded.symbols,costs=excluded.costs,trades_count=excluded.trades_count,
       created_at=excluded.created_at,period_id=excluded.period_id,settlement_status=excluded.settlement_status,
       daily_buy_limit=excluded.daily_buy_limit,daily_buy_used=excluded.daily_buy_used,buy_fees=excluded.buy_fees,
       sell_fees=excluded.sell_fees,tax=excluded.tax,gross_pnl=excluded.gross_pnl,semantics_version=excluded.semantics_version''',
       (day,metrics['equity']-metrics['net_pnl'],metrics['equity'],metrics['net_pnl'],names,
        metrics['fees']+metrics['tax'],metrics['trades_count'],time.time(),pid,status,
        metrics['daily_buy_limit'],metrics['daily_buy_used'],metrics['buy_fees'],metrics['sell_fees'],metrics['tax'],metrics['realized_pnl'],SEMANTICS))
    return dict(metrics,date=day,status=status)


def finalize_today(path=None):
    stamp = now()
    with transaction(path) as con:
        pid = period(con)
        positions = open_positions(con,pid)
        if any(r['entry_date'] != stamp.date().isoformat() for r in positions):
            raise RuntimeError('有跨日殘留持倉：須人工核對，禁止自動結算')
        return refresh_day(con,pid,stamp.date().isoformat())



def snapshot(path=None):
    p = Path(path or path_default())
    with sqlite3.connect(p.resolve().as_uri()+'?mode=ro',uri=True,timeout=5) as con:
        con.row_factory=sqlite3.Row
        con.execute('BEGIN')
        pid=period(con)
        acct=account(con)
        positions=[dict(r) for r in open_positions(con,pid)]
        position_cost=sum((money(d(r['entry_price'])*int(r['shares'])) for r in positions),Decimal('0'))
        fills=con.execute('SELECT COUNT(*) n FROM paper_trade_fills WHERE period_id=?',(pid,)).fetchone()['n']
        today=now().date().isoformat()
        metrics=daily_metrics(con,pid,today)
        events=[{'time':r['time_str'],'symbol':r['symbol'],'name':r['name'],'price':r['price'],
                 'action':r['action'],'reason':r['reason']} for r in con.execute('''SELECT time_str,symbol,name,price,action,reason FROM paper_trade_events WHERE date=? ORDER BY id DESC LIMIT 100''',(today,))]
        logs=[{'date':r['date'],'equity_start':r['start_balance'],'equity_end':r['end_balance'],
               'net_pnl':r['net_pnl'],'symbols':r['symbols'],'costs':r['costs'],'trades_count':r['trades_count'],
               'status':r['settlement_status'],'daily_buy_limit':r['daily_buy_limit'],
               'daily_buy_used':r['daily_buy_used'],'buy_fees':r['buy_fees'],'sell_fees':r['sell_fees'],
               'tax':r['tax'],'gross_pnl':r['gross_pnl'],'semantics_version':r['semantics_version']} for r in con.execute('''SELECT * FROM paper_trade_logs WHERE period_id=? OR period_id IS NULL ORDER BY date DESC LIMIT 30''',(pid,))]
        return {'settings':{**metrics,**{k:acct[k] for k in ('status','start_date','updated_at')}},
                'period_id':pid,'positions':positions,'events':events,'logs':logs,
                'summary':{**metrics,'position_cost':float(position_cost),
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
