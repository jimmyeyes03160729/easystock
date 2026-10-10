#!/usr/bin/env python3
"""0050 benchmark: daily bars and ex-dividend records from TWSE, and a dividend- and split-adjusted open-to-close return.

Research only. STOCK_DAY (one request per month) and TWT49U (one request per year) are fetched slowly and kept in
SQLite. The daily DB used by the other studies does not hold ETFs.
"""
import re, sqlite3, sys, time, urllib.request, json
from pathlib import Path

DB = Path('/home/ubuntu/easystock-research/revenue_v1/data/etf0050.sqlite')
DAY_URL = 'https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date={ym}01&stockNo=0050&response=json'
EXR_URL = 'https://www.twse.com.tw/rwd/zh/exRight/TWT49U?startDate={y}0101&endDate={y}1231&response=json'
SYMBOL = '0050'
ETF_TAX = 0.001
SPLIT_RATIOS = (2, 3, 4, 5, 10)


def roc_to_iso(s):
    m = re.match(r'^(\d{2,3})[/年](\d{2})[/月](\d{2})', s.strip())
    return '%04d-%s-%s' % (int(m.group(1)) + 1911, m.group(2), m.group(3)) if m else None


def num(s):
    s = str(s).replace(',', '').strip()
    try:
        return float(s)
    except ValueError:
        return None


def parse_days(payload):
    out = []
    if payload.get('stat') != 'OK':
        return out
    for r in payload.get('data') or []:
        d, o, c = roc_to_iso(r[0]), num(r[3]), num(r[6])
        if d and o and c:
            out.append((d, o, c, num(r[1]), num(r[2])))
    return out


def parse_exrights(payload):
    out = []
    for r in payload.get('data') or []:
        if r[1].strip() == SYMBOL:
            d, pc, ref = roc_to_iso(r[0]), num(r[3]), num(r[4])
            if d and pc and ref:
                out.append((d, pc, ref, r[6].strip()))
    return out


def daily_factor(prev_close, close, exdiv):
    """Total-return factor of one day: dividend add-back on a listed ex-dividend day, split detection otherwise."""
    if exdiv:
        pc, ref = exdiv
        return (close + (pc - ref)) / pc
    ratio = prev_close / close
    for s in SPLIT_RATIOS:
        if abs(ratio / s - 1) < 0.25:
            return close * s / prev_close
    return close / prev_close


def open_to_close_return(days, exdiv, entry, exit_):
    """Gross total return from the open of `entry` to the close of `exit_`; days = [(date, open, close, ...)] sorted; exdiv = {date: (prev_close, ref)}."""
    idx = {d[0]: i for i, d in enumerate(days)}
    if entry not in idx or exit_ not in idx or idx[exit_] < idx[entry]:
        return None
    i0, i1 = idx[entry], idx[exit_]
    factor = days[i0][2] / days[i0][1]
    for i in range(i0 + 1, i1 + 1):
        factor *= daily_factor(days[i - 1][2], days[i][2], exdiv.get(days[i][0]))
    return factor - 1


def cost_pct(entry_price, exit_price, shares=1000):
    """Fee on both legs (paper_execution rule) and the 0.1% ETF transaction tax on the sale, in percent of the entry amount."""
    fee = lambda a: max(20.0, int(a * 0.001425 * 0.28 + 0.5))
    ea, xa = entry_price * shares, exit_price * shares
    return (fee(ea) + fee(xa) + int(xa * ETF_TAX + 0.5)) / ea * 100


def get(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (research; 0050 benchmark)'})
    for attempt in range(3):
        try:
            return json.loads(urllib.request.urlopen(req, timeout=60).read())
        except Exception as e:
            print('retry', type(e).__name__, url[-30:], flush=True)
            time.sleep(20 * (attempt + 1))
    return {}


def load(path=DB):
    db = sqlite3.connect(path)
    days = db.execute('SELECT day, open, close FROM bars ORDER BY day').fetchall()
    exdiv = {d: (pc, ref) for d, pc, ref in db.execute('SELECT day, prev_close, ref FROM exrights')}
    db.close()
    return days, exdiv


def update(first='2022-01', last='2026-10', path=DB, spacing=6.0):
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.execute('CREATE TABLE IF NOT EXISTS bars (day TEXT PRIMARY KEY, open REAL, close REAL, volume REAL, amount REAL)')
    db.execute('CREATE TABLE IF NOT EXISTS exrights (day TEXT PRIMARY KEY, prev_close REAL, ref REAL, kind TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS fetched (key TEXT PRIMARY KEY)')
    done = {r[0] for r in db.execute('SELECT key FROM fetched')}
    y, m = map(int, first.split('-'))
    ly, lm = map(int, last.split('-'))
    while (y, m) <= (ly, lm):
        key = 'day_%04d%02d' % (y, m)
        if key not in done or (y, m) == (ly, lm):
            rows = parse_days(get(DAY_URL.format(ym='%04d%02d' % (y, m))))
            db.executemany('INSERT OR REPLACE INTO bars VALUES (?,?,?,?,?)', [(d, o, c, v, a) for d, o, c, v, a in rows])
            db.execute('INSERT OR REPLACE INTO fetched VALUES (?)', (key,))
            db.commit()
            print(key, len(rows), flush=True)
            time.sleep(spacing)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    for yr in range(int(first[:4]), ly + 1):
        key = 'exr_%d' % yr
        if key not in done or yr == ly:
            for d, pc, ref, kind in parse_exrights(get(EXR_URL.format(y=yr))):
                db.execute('INSERT OR REPLACE INTO exrights VALUES (?,?,?,?)', (d, pc, ref, kind))
            db.execute('INSERT OR REPLACE INTO fetched VALUES (?)', (key,))
            db.commit()
            print(key, flush=True)
            time.sleep(spacing)
    db.close()


if __name__ == '__main__':
    update(*(sys.argv[1:3] if len(sys.argv) >= 3 else ('2022-01', '2026-10')))
