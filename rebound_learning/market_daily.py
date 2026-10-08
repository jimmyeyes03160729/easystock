"""Official TWSE/TPEx whole-market daily archive for rebound research v2.

One request per exchange per session returns every listed/OTC stock, so the
universe includes stocks that later delisted (no survivorship selection).
Prices are stored raw; ``adj_factor`` records the exchange-published
ex-rights/dividend reference price divided by the previous close, so readers
can adjust a history using only events up to the date they are standing on.
Nothing here publishes a feed, touches Firebase or trains a model.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

TPE = timezone(timedelta(hours=8))
TWSE_QUOTES = 'https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX'
TWSE_EX_RIGHTS = 'https://www.twse.com.tw/rwd/zh/exRight/TWT49U'
TPEX_QUOTES = 'https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes'
TPEX_INDEX = 'https://www.tpex.org.tw/www/zh-tw/indexInfo/sectinx'
TAIEX = '發行量加權股價指數'
TPEX_COMPOSITE = '櫃買指數'
# TWSE asks clients to stay well below 3 requests / 5 seconds.
MIN_INTERVAL = float(os.environ.get('REBOUND_MARKET_MIN_INTERVAL_SECONDS', '3.2'))
DEFAULT_ROOT = Path('/home/ubuntu/easystock-learning-data/rebound')
STOCK = re.compile(r'^[1-9]\d{3}$')


def market_path() -> Path:
    return Path(os.environ.get('EASYSTOCK_REBOUND_DATA_DIR', DEFAULT_ROOT)) / 'market-daily.sqlite'


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = path or market_path()
    if str(path) != ':memory:':
        Path(path).parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('PRAGMA busy_timeout=10000')
    db.executescript('''
        CREATE TABLE IF NOT EXISTS sessions (
            day TEXT NOT NULL,
            exchange TEXT NOT NULL,
            status TEXT NOT NULL,
            stock_count INTEGER NOT NULL,
            fetched_at TEXT NOT NULL,
            PRIMARY KEY(day, exchange)
        );
        CREATE TABLE IF NOT EXISTS bars (
            symbol TEXT NOT NULL,
            day TEXT NOT NULL,
            exchange TEXT NOT NULL,
            open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL, close REAL NOT NULL,
            volume REAL NOT NULL, amount REAL NOT NULL,
            reference REAL,
            PRIMARY KEY(symbol, day)
        );
        CREATE INDEX IF NOT EXISTS bars_day ON bars(day);
        CREATE TABLE IF NOT EXISTS indices (
            day TEXT NOT NULL, name TEXT NOT NULL, close REAL NOT NULL,
            PRIMARY KEY(day, name)
        );
        CREATE TABLE IF NOT EXISTS ex_rights (
            symbol TEXT NOT NULL, day TEXT NOT NULL,
            previous_close REAL NOT NULL, reference REAL NOT NULL,
            PRIMARY KEY(symbol, day)
        );
        CREATE TABLE IF NOT EXISTS ex_rights_months (month TEXT PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS amount_ranks (
            symbol TEXT NOT NULL, day TEXT NOT NULL, rank REAL NOT NULL,
            PRIMARY KEY(symbol, day)
        );
        CREATE TABLE IF NOT EXISTS tpex_next_reference (
            symbol TEXT NOT NULL, day TEXT NOT NULL, reference REAL NOT NULL,
            PRIMARY KEY(symbol, day)
        );
    ''')
    db.commit()
    return db


def number(value) -> float | None:
    text = re.sub(r'<[^>]*>', '', str(value or '')).replace(',', '').strip()
    if not text or set(text) <= set('-X '):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def roc_to_iso(value: str) -> str:
    year, month, day = (int(x) for x in re.findall(r'\d+', value)[:3])
    return date(year + 1911, month, day).isoformat()


def _bar(symbol, day, exchange, opening, high, low, close, volume, amount, reference):
    values = (opening, high, low, close)
    if any(v is None or v <= 0 for v in values):
        return None  # no trade that session; never fabricate a flat bar
    if high < max(opening, close, low) or low > min(opening, close):
        raise ValueError(f'bad_ohlc:{exchange}:{symbol}:{day}')
    return {'symbol': symbol, 'day': day, 'exchange': exchange,
            'open': opening, 'high': high, 'low': low, 'close': close,
            'volume': volume or 0.0, 'amount': amount or 0.0, 'reference': reference}


def parse_twse(payload: dict, day: str) -> tuple[list[dict], dict[str, float]]:
    """Return (stock bars, {index name: close}); empty bars mean no session."""
    if payload.get('stat') != 'OK' or str(payload.get('date')) != day.replace('-', ''):
        return [], {}
    bars, indices = [], {}
    for table in payload.get('tables') or []:
        fields = table.get('fields') or []
        if fields[:2] == ['指數', '收盤指數']:
            for row in table.get('data') or []:
                if row[0] == TAIEX and number(row[1]) is not None:
                    indices['TAIEX'] = number(row[1])
        elif fields[:1] == ['證券代號'] and '收盤價' in fields:
            col = {name: i for i, name in enumerate(fields)}
            for row in table.get('data') or []:
                symbol = str(row[0]).strip()
                if not STOCK.match(symbol):
                    continue
                sign = re.sub(r'<[^>]*>', '', row[col['漲跌(+/-)']]).strip()
                close, diff = number(row[col['收盤價']]), number(row[col['漲跌價差']])
                # On "X" (ex-rights/no comparison) days TWSE's change is not a
                # reference; TWT49U supplies it separately.
                reference = None
                if close is not None and diff is not None and sign in ('+', '-', ''):
                    reference = round(close - diff if sign == '+' else close + diff, 4)
                bar = _bar(symbol, day, 'TWSE', number(row[col['開盤價']]), number(row[col['最高價']]),
                           number(row[col['最低價']]), close, number(row[col['成交股數']]),
                           number(row[col['成交金額']]), reference)
                if bar:
                    bars.append(bar)
    return bars, indices


def parse_tpex(payload: dict, day: str) -> tuple[list[dict], dict[str, float]]:
    """TPEx rows carry the *next* session's reference price."""
    if str(payload.get('stat', '')).lower() != 'ok' or str(payload.get('date')) != day.replace('-', ''):
        return [], {}
    bars, next_reference = [], {}
    for table in payload.get('tables') or []:
        fields = table.get('fields') or []
        if fields[:1] != ['代號'] or '收盤' not in fields:
            continue
        col = {name.replace(' ', ''): i for i, name in enumerate(fields)}
        for row in table.get('data') or []:
            symbol = str(row[0]).strip()
            if not STOCK.match(symbol):
                continue
            ref = number(row[col['次日參考價']]) if '次日參考價' in col else None
            if ref:
                next_reference[symbol] = ref
            bar = _bar(symbol, day, 'TPEX', number(row[col['開盤']]), number(row[col['最高']]),
                       number(row[col['最低']]), number(row[col['收盤']]), number(row[col['成交股數']]),
                       number(row[col['成交金額(元)']]), None)
            if bar:
                bars.append(bar)
    return bars, next_reference


def parse_tpex_index(payload: dict) -> float | None:
    for table in payload.get('tables') or []:
        for row in table.get('data') or []:
            if str(row[0]).strip() == TPEX_COMPOSITE:
                return number(row[1])
    return None


def parse_ex_rights(payload: dict) -> list[dict]:
    if payload.get('stat') != 'OK':
        return []
    fields = payload.get('fields') or []
    col = {name: i for i, name in enumerate(fields)}
    out = []
    for row in payload.get('data') or []:
        symbol = str(row[col['股票代號']]).strip()
        before, reference = number(row[col['除權息前收盤價']]), number(row[col['除權息參考價']])
        if STOCK.match(symbol) and before and reference:
            out.append({'symbol': symbol, 'day': roc_to_iso(row[col['資料日期']]),
                        'previous_close': before, 'reference': reference})
    return out


class Client:
    def __init__(self, session: requests.Session | None = None, interval: float = MIN_INTERVAL):
        self.session = session or requests.Session()
        self.session.headers.update({'User-Agent': 'Mozilla/5.0 EasyStockResearch/1.0',
                                     'Accept': 'application/json'})
        self.interval = interval
        self.last = 0.0

    def get(self, url: str, params: dict) -> dict:
        for attempt in range(4):
            wait = self.interval - (time.monotonic() - self.last)
            if wait > 0:
                time.sleep(wait)
            self.last = time.monotonic()
            try:
                response = self.session.get(url, params=params, timeout=30)
                if response.status_code == 200:
                    return response.json()
            except (requests.RequestException, ValueError):
                pass
            time.sleep(10 * (attempt + 1))
        raise RuntimeError(f'fetch_failed:{url}:{params}')


def _store_session(db, day, exchange, bars, indices):
    now = datetime.now(TPE).isoformat(timespec='seconds')
    if not bars and day >= now[:10]:
        return  # not published yet; only past sessions may be recorded closed
    for bar in bars:
        old = db.execute('SELECT open,high,low,close FROM bars WHERE symbol=? AND day=?',
                         (bar['symbol'], day)).fetchone()
        if old and tuple(old) != (bar['open'], bar['high'], bar['low'], bar['close']):
            raise ValueError(f'bar_changed:{bar["symbol"]}:{day}')
        db.execute('''INSERT OR IGNORE INTO bars VALUES (?,?,?,?,?,?,?,?,?,?)''',
                   (bar['symbol'], day, exchange, bar['open'], bar['high'], bar['low'], bar['close'],
                    bar['volume'], bar['amount'], bar['reference']))
    for name, close in indices.items():
        db.execute('INSERT OR REPLACE INTO indices VALUES (?,?,?)', (day, name, close))
    db.execute('INSERT OR REPLACE INTO sessions VALUES (?,?,?,?,?)',
               (day, exchange, 'open' if bars else 'closed', len(bars), now))


def fetch_day(db, client: Client, day: str) -> dict:
    done = {row['exchange'] for row in db.execute('SELECT exchange FROM sessions WHERE day=?', (day,))}
    result = {}
    compact = day.replace('-', '')
    if 'TWSE' not in done:
        bars, indices = parse_twse(client.get(TWSE_QUOTES, {'date': compact, 'type': 'ALLBUT0999',
                                                             'response': 'json'}), day)
        _store_session(db, day, 'TWSE', bars, indices)
        result['TWSE'] = len(bars)
    if 'TPEX' not in done:
        slash = day.replace('-', '/')
        bars, next_reference = parse_tpex(client.get(TPEX_QUOTES, {'date': slash, 'response': 'json'}), day)
        indices = {}
        if bars:
            close = parse_tpex_index(client.get(TPEX_INDEX, {'date': slash, 'response': 'json'}))
            if close is not None:
                indices['TPEX'] = close
        _store_session(db, day, 'TPEX', bars, indices)
        # Today's "next reference" is the following session's reference.
        db.executemany('INSERT OR REPLACE INTO tpex_next_reference VALUES (?,?,?)',
                       ((symbol, day, ref) for symbol, ref in next_reference.items()))
        result['TPEX'] = len(bars)
    db.commit()
    return result


def fetch_ex_rights(db, client: Client, month: str) -> int:
    """TWSE dividend/rights reference prices for one calendar month."""
    first = date.fromisoformat(month + '-01')
    last = (first.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    rows = parse_ex_rights(client.get(TWSE_EX_RIGHTS, {
        'startDate': first.strftime('%Y%m%d'), 'endDate': last.strftime('%Y%m%d'), 'response': 'json'}))
    db.executemany('INSERT OR REPLACE INTO ex_rights VALUES (?,?,?,?)',
                   ((r['symbol'], r['day'], r['previous_close'], r['reference']) for r in rows))
    if last < datetime.now(TPE).date():
        db.execute('INSERT OR IGNORE INTO ex_rights_months VALUES (?)', (month,))
    db.commit()
    return len(rows)


def weekdays(start: str, end: str) -> list[str]:
    day, stop, out = date.fromisoformat(start), date.fromisoformat(end), []
    while day <= stop:
        if day.weekday() < 5:
            out.append(day.isoformat())
        day += timedelta(days=1)
    return out


def adjustment_factor(previous_close: float | None, reference: float | None) -> float:
    """Exchange reference / previous close; 1 when there is no published event."""
    if not previous_close or not reference:
        return 1.0
    factor = reference / previous_close
    return 1.0 if abs(factor - 1) < 0.0005 else round(factor, 8)


def refresh_amount_ranks(db) -> int:
    """v1 definition: (count with larger amount + 1) / stocks traded that session."""
    days = [r[0] for r in db.execute('''SELECT DISTINCT day FROM bars
        WHERE day NOT IN (SELECT DISTINCT day FROM amount_ranks) ORDER BY day''')]
    for day in days:
        rows = db.execute('SELECT symbol,amount FROM bars WHERE day=? ORDER BY amount DESC', (day,)).fetchall()
        ranks, previous, position = [], None, 0
        for i, r in enumerate(rows):
            if r['amount'] != previous:
                position, previous = i + 1, r['amount']
            ranks.append((r['symbol'], day, position / len(rows)))
        db.executemany('INSERT OR REPLACE INTO amount_ranks VALUES (?,?,?)', ranks)
    db.commit()
    return len(days)


def with_factors(db, symbol: str, rows: list) -> list[dict]:
    """Raw bars plus adj_factor; the first row has no previous bar (factor 1).

    adj_factor on day t applies to bars *before* t, so a reader standing on
    D0 only multiplies by factors of sessions <= D0 (no future information).
    """
    if not rows:
        return []
    days = (rows[0]['day'], rows[-1]['day'])
    ex = {r['day']: (r['previous_close'], r['reference']) for r in db.execute(
        'SELECT * FROM ex_rights WHERE symbol=? AND day BETWEEN ? AND ?', (symbol, *days))}
    nxt = {r[0]: r[1] for r in db.execute(
        'SELECT day,reference FROM tpex_next_reference WHERE symbol=? AND day BETWEEN ? AND ?',
        (symbol, *days))}
    bars, previous = [], None
    for r in rows:
        factor, status = 1.0, 'none'
        if previous is not None:
            if r['exchange'] == 'TPEX':
                factor = adjustment_factor(previous['close'], nxt.get(previous['day']))
            elif r['day'] in ex:
                factor = adjustment_factor(*ex[r['day']])
            elif r['reference'] is None:
                status = 'unknown'  # TWSE "X" without a published TWT49U event
            if factor != 1.0:
                status = 'event'
        bars.append({'time': r['day'], 'exchange': r['exchange'],
                     'open': r['open'], 'high': r['high'], 'low': r['low'],
                     'close': r['close'], 'volume': r['volume'], 'amount': r['amount'],
                     'adj_factor': factor, 'adj_status': status})
        previous = r
    return bars


def load_histories(db, symbols: list[str] | None = None):
    """Yield (symbol, exchange, bars) one stock at a time to bound memory."""
    names = symbols or [r[0] for r in db.execute('SELECT DISTINCT symbol FROM bars ORDER BY symbol')]
    for symbol in names:
        rows = db.execute('SELECT * FROM bars WHERE symbol=? ORDER BY day', (symbol,)).fetchall()
        yield symbol, (rows[-1]['exchange'] if rows else None), with_factors(db, symbol, rows)


def future_bars(db, symbol: str, signal_date: str, limit: int = 20, *,
                before: str | None = None, through: str | None = None) -> list[dict]:
    """Bars after D0 on its price basis; optional bounds apply BEFORE fetching.

    Historical research must supply ``before`` to protect its reserved partition.
    ``through`` also prevents suspensions from extending a calendar horizon.
    Unbounded calls remain available for the separate daily label collector.
    """
    if limit < 1 or (before is not None and signal_date >= before):
        raise ValueError('invalid_future_bar_boundary')
    query, args = 'SELECT * FROM bars WHERE symbol=? AND day>=?', [symbol, signal_date]
    if before is not None:
        query += ' AND day<?'
        args.append(before)
    if through is not None:
        query += ' AND day<=?'
        args.append(through)
    query += ' ORDER BY day LIMIT ?'
    rows = db.execute(query, (*args, limit + 1)).fetchall()
    if not rows or rows[0]['day'] != signal_date:
        rows = [None] + rows  # D0 missing: never invent a factor across a gap
    out, cum = [], 1.0
    for bar in with_factors(db, symbol, [r for r in rows if r is not None])[1 if rows[0] else 0:]:
        cum *= bar['adj_factor']
        out.append({'time': bar['time'], **{k: round(bar[k] / cum, 6) for k in ('open', 'high', 'low', 'close')},
                    'volume': bar['volume'], 'amount': bar['amount']})
    return out[:limit]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--from', dest='start', default='2022-01-03')
    parser.add_argument('--to', dest='end', default=datetime.now(TPE).date().isoformat())
    parser.add_argument('--status', action='store_true', help='print archive coverage and exit')
    args = parser.parse_args()
    with connect() as db:
        if args.status:
            row = db.execute('''SELECT COUNT(DISTINCT day), MIN(day), MAX(day) FROM sessions
                                WHERE status='open' ''').fetchone()
            print(json.dumps({'open_sessions': row[0], 'first': row[1], 'last': row[2],
                              'bars': db.execute('SELECT COUNT(*) FROM bars').fetchone()[0],
                              'symbols': db.execute('SELECT COUNT(DISTINCT symbol) FROM bars').fetchone()[0],
                              'ex_rights': db.execute('SELECT COUNT(*) FROM ex_rights').fetchone()[0]}))
            return
        client = Client()
        today = datetime.now(TPE)
        days = [d for d in weekdays(args.start, args.end)
                # The current session is only final after the exchanges publish.
                if d < today.date().isoformat() or today.hour >= 15]
        months = sorted({d[:7] for d in days})
        done_months = {r[0] for r in db.execute('SELECT month FROM ex_rights_months')}
        for month in months:
            if month not in done_months:
                fetch_ex_rights(db, client, month)
        for n, day in enumerate(days, start=1):
            counts = fetch_day(db, client, day)
            if counts:
                print(f'[market] {day} {counts} ({n}/{len(days)})', file=sys.stderr, flush=True)


if __name__ == '__main__':
    main()
