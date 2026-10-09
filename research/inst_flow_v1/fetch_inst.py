#!/usr/bin/env python3
"""Fetch daily per-stock institutional net buy/sell (TWSE T86, TPEx 3itrade_hedge) into SQLite. Research only.

Slow on purpose (>= 5 s between requests) because both hosts throttle bursts. Days are taken from the official daily DB
trading calendar and limited to <= LAST_DAY (the hard cutoff). Raw pages are kept gzipped for provenance; the run is
resumable (pages already stored are skipped).
"""
import gzip, json, re, sqlite3, sys, time, urllib.request
from pathlib import Path

ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('/home/ubuntu/easystock-research/inst_flow_v1/data')
DAILY_DB = '/home/ubuntu/easystock-learning-data/rebound/market-daily.sqlite'
FIRST_DAY, LAST_DAY = '2022-01-03', '2026-10-02'
SPACING_S = 5.0
COMMON = re.compile(r'^[1-9]\d{3}$')
TWSE_URL = 'https://www.twse.com.tw/rwd/zh/fund/T86?date={ymd}&selectType=ALL&response=json'
TPEX_URL = 'https://www.tpex.org.tw/web/stock/3insti/daily_trade/3itrade_hedge_result.php?l=zh-tw&o=json&se=EW&t=D&d={roc}'


def num(s):
    s = str(s).replace(',', '').strip()
    return int(s) if re.fullmatch(r'-?\d+', s) else None


def parse_twse(payload):
    """symbol -> (foreign_net, trust_net, dealer_net, total_net, consistent) in shares; foreign includes foreign dealers."""
    out = {}
    if payload.get('stat') != 'OK':
        return out
    for r in payload.get('data') or []:
        sym = r[0].strip()
        if not COMMON.match(sym) or len(r) < 19:
            continue
        f, fd, it, d, tot = num(r[4]), num(r[7]), num(r[10]), num(r[11]), num(r[18])
        if None in (f, fd, it, d, tot):
            continue
        out[sym] = (f + fd, it, d, tot, f + fd + it + d == tot)
    return out


def parse_tpex(payload):
    out = {}
    tables = payload.get('tables') or []
    for r in (tables[0].get('data') or []) if tables else []:
        sym = r[0].strip()
        if not COMMON.match(sym) or len(r) < 24:
            continue
        f, it, d, tot = num(r[10]), num(r[13]), num(r[22]), num(r[23])
        if None in (f, it, d, tot):
            continue
        out[sym] = (f, it, d, tot, f + it + d == tot)
    return out


def get(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (research; institutional flows)'})
    for attempt in range(4):
        try:
            return urllib.request.urlopen(req, timeout=60).read()
        except Exception as e:
            print('retry', type(e).__name__, url[-40:], flush=True)
            time.sleep(30 * (attempt + 1))
    return None


def main():
    (ROOT / 'raw').mkdir(parents=True, exist_ok=True)
    daily = sqlite3.connect('file:%s?mode=ro' % DAILY_DB, uri=True)
    days = [d for (d,) in daily.execute("SELECT day FROM sessions WHERE exchange='TWSE' AND status='open' AND day >= ? AND day <= ? ORDER BY day",
                                         (FIRST_DAY, LAST_DAY))]
    daily.close()
    db = sqlite3.connect(ROOT / 'inst.sqlite')
    db.execute('''CREATE TABLE IF NOT EXISTS inst (symbol TEXT NOT NULL, day TEXT NOT NULL, market TEXT NOT NULL,
        foreign_net INTEGER, trust_net INTEGER, dealer_net INTEGER, total_net INTEGER, consistent INTEGER,
        PRIMARY KEY(symbol, day))''')
    db.execute('CREATE TABLE IF NOT EXISTS pages (page TEXT PRIMARY KEY, day TEXT, market TEXT, rows INTEGER, inconsistent INTEGER, bytes INTEGER)')
    done = {r[0] for r in db.execute('SELECT page FROM pages')}
    for day in days:
        for mkt in ('twse', 'tpex'):
            page = '%s_%s' % (mkt, day)
            if page in done:
                continue
            y, m, d = day.split('-')
            url = TWSE_URL.format(ymd=y + m + d) if mkt == 'twse' else TPEX_URL.format(roc='%d/%s/%s' % (int(y) - 1911, m, d))
            body = get(url)
            if body is None:
                print('FAILED', page, flush=True)
                time.sleep(SPACING_S)
                continue
            (ROOT / 'raw' / (page + '.json.gz')).write_bytes(gzip.compress(body))
            try:
                rows = (parse_twse if mkt == 'twse' else parse_tpex)(json.loads(body))
            except Exception as e:
                print('PARSE_FAIL', page, type(e).__name__, flush=True)
                time.sleep(SPACING_S)
                continue
            db.executemany('INSERT OR REPLACE INTO inst VALUES (?,?,?,?,?,?,?,?)',
                           [(s, day, mkt, v[0], v[1], v[2], v[3], int(v[4])) for s, v in rows.items()])
            db.execute('INSERT OR REPLACE INTO pages VALUES (?,?,?,?,?,?)',
                       (page, day, mkt, len(rows), sum(1 for v in rows.values() if not v[4]), len(body)))
            db.commit()
            print(page, len(rows), flush=True)
            time.sleep(SPACING_S)
    db.close()


if __name__ == '__main__':
    main()
