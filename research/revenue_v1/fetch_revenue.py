#!/usr/bin/env python3
"""Fetch MOPS monthly revenue summary tables (TWSE sii / TPEx otc, domestic + foreign) into SQLite.

Research only. Revenue months are limited to <= LAST_MONTH so nothing published after the hard cutoff is read.
Raw pages are kept gzipped next to the database for provenance; the 出表日期 (compile date) of each page is stored
because the tables are compiled after the fact and can contain later corrections.
"""
import gzip, re, sqlite3, sys, time, urllib.request
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else '/home/ubuntu/easystock-research/revenue_v1/data')
FIRST_MONTH, LAST_MONTH = (2020, 1), (2026, 8)
URL = 'https://mopsov.twse.com.tw/nas/t21/{mkt}/t21sc03_{roc}_{m}_{kind}.html'
ROW = re.compile(r'<tr align=right><td align=center>\s*([0-9A-Z]{4,6})\s*</td><td align=left>(.*?)</td>(.*?)</tr>', re.S)
CELL = re.compile(r'<td[^>]*>(.*?)</td>', re.S)
COMPILED = re.compile(r'出表日期[：:]\s*(\d+)/(\d+)/(\d+)')


def months():
    y, m = FIRST_MONTH
    while (y, m) <= LAST_MONTH:
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def num(s):
    s = re.sub(r'<[^>]+>|&nbsp;|,|\s', '', s)
    try:
        return float(s)
    except ValueError:
        return None


def parse(html):
    c = COMPILED.search(html)
    compiled = '%04d-%02d-%02d' % (int(c.group(1)) + 1911, int(c.group(2)), int(c.group(3))) if c else None
    rows = []
    for code, name, rest in ROW.findall(html):
        cells = CELL.findall(rest)
        if len(cells) < 8:
            continue
        v = [num(x) for x in cells[:8]]
        note = re.sub(r'<[^>]+>|&nbsp;', '', cells[8]).strip() if len(cells) > 8 else ''
        rows.append((code, re.sub(r'<[^>]+>', '', name).strip(), *v, note))
    return compiled, rows


def main():
    raw = ROOT / 'raw'
    raw.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(ROOT / 'revenue.sqlite')
    db.execute('''CREATE TABLE IF NOT EXISTS revenue (
        symbol TEXT NOT NULL, month TEXT NOT NULL, market TEXT NOT NULL, kind INTEGER NOT NULL, name TEXT,
        revenue REAL, prev_month REAL, last_year REAL, mom_pct REAL, yoy_pct REAL, cum REAL, last_cum REAL, cum_pct REAL,
        note TEXT, compiled TEXT, PRIMARY KEY(symbol, month))''')
    db.execute('CREATE TABLE IF NOT EXISTS pages (page TEXT PRIMARY KEY, month TEXT, rows INTEGER, compiled TEXT, bytes INTEGER)')
    done = {r[0] for r in db.execute('SELECT page FROM pages')}
    for y, m in months():
        for mkt in ('sii', 'otc'):
            for kind in (0, 1):
                page = '%s_%d_%d_%d' % (mkt, y - 1911, m, kind)
                if page in done:
                    continue
                url = URL.format(mkt=mkt, roc=y - 1911, m=m, kind=kind)
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (research; monthly revenue)'})
                for attempt in range(3):
                    try:
                        body = urllib.request.urlopen(req, timeout=60).read()
                        break
                    except Exception as e:
                        print('retry', page, type(e).__name__, flush=True)
                        time.sleep(20 * (attempt + 1))
                else:
                    print('FAILED', page, flush=True)
                    continue
                (raw / (page + '.html.gz')).write_bytes(gzip.compress(body))
                compiled, rows = parse(body.decode('big5', 'replace'))
                month = '%04d-%02d' % (y, m)
                db.executemany('INSERT OR REPLACE INTO revenue VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                               [(r[0], month, mkt, kind, *r[1:], compiled) for r in rows])
                db.execute('INSERT OR REPLACE INTO pages VALUES (?,?,?,?,?)', (page, month, len(rows), compiled, len(body)))
                db.commit()
                print(page, len(rows), compiled, flush=True)
                time.sleep(3)
    db.close()


if __name__ == '__main__':
    main()
