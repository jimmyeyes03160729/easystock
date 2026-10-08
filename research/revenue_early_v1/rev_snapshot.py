#!/usr/bin/env python3
"""REVENUE_EARLY_V1 Part B collector: daily MOPS t21sc03 snapshots that date each company's revenue filing.

Runs every evening (cron 21:10 Taiwan time); acts only on calendar days 1-15 and then snapshots revenue month M-1
(sii/otc, domestic kind 0 and foreign kind 1). Each page is kept gzipped with its fetch time and compile date, and
the first compile date at which a company's row appears is recorded once (INSERT OR IGNORE). Reads no price.
"""
import gzip, re, sqlite3, sys, time, urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'
TPE = timezone(timedelta(hours=8))
URL = 'https://mopsov.twse.com.tw/nas/t21/{mkt}/t21sc03_{roc}_{m}_{kind}.html'     # same source as revenue_v1
ROW = re.compile(r'<tr align=right><td align=center>\s*([0-9A-Z]{4,6})\s*</td>')
COMPILED = re.compile(r'出表日期[：:]\s*(\d+)/(\d+)/(\d+)')
PAGES = [(mkt, kind) for mkt in ('sii', 'otc') for kind in (0, 1)]
LAST_DAY = 15


def revenue_month(today):
    """Revenue month snapshotted on a calendar date, or None outside days 1-15."""
    if today.day > LAST_DAY:
        return None
    first = today.replace(day=1) - timedelta(days=1)
    return '%04d-%02d' % (first.year, first.month)


def parse(html):
    c = COMPILED.search(html)
    compiled = '%04d-%02d-%02d' % (int(c.group(1)) + 1911, int(c.group(2)), int(c.group(3))) if c else None
    return compiled, sorted(set(ROW.findall(html)))


def init(db):
    db.execute('''CREATE TABLE IF NOT EXISTS first_seen (symbol TEXT NOT NULL, month TEXT NOT NULL, market TEXT NOT NULL,
        kind INTEGER NOT NULL, compiled TEXT NOT NULL, fetched_at TEXT NOT NULL, PRIMARY KEY(symbol, month))''')
    db.execute('''CREATE TABLE IF NOT EXISTS snapshots (month TEXT NOT NULL, market TEXT NOT NULL, kind INTEGER NOT NULL,
        fetched_at TEXT NOT NULL, status TEXT NOT NULL, compiled TEXT, rows INTEGER, bytes INTEGER, raw TEXT)''')


def record(db, month, mkt, kind, fetched_at, body, raw_name):
    """Store one fetched page; returns the number of newly first-seen companies."""
    compiled, codes = parse(body.decode('big5', 'replace'))
    if compiled is None:
        db.execute('INSERT INTO snapshots VALUES (?,?,?,?,?,?,?,?,?)',
                   (month, mkt, kind, fetched_at, 'no_compile_date', None, len(codes), len(body), raw_name))
        return 0
    before = db.total_changes
    db.executemany('INSERT OR IGNORE INTO first_seen VALUES (?,?,?,?,?,?)',
                   [(s, month, mkt, kind, compiled, fetched_at) for s in codes])
    new = db.total_changes - before
    db.execute('INSERT INTO snapshots VALUES (?,?,?,?,?,?,?,?,?)',
               (month, mkt, kind, fetched_at, 'ok', compiled, len(codes), len(body), raw_name))
    return new


def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (research; monthly revenue)'})
    for attempt in range(3):
        try:
            return urllib.request.urlopen(req, timeout=60).read()
        except Exception as e:
            print('retry', url, type(e).__name__, flush=True)
            time.sleep(20 * (attempt + 1))
    return None


def main(now=None, fetcher=fetch, data=DATA, pause=time.sleep):
    now = now or datetime.now(TPE)
    month = revenue_month(now.date())
    if month is None:
        print('outside filing window', now.date(), flush=True)
        return 0
    y, m = map(int, month.split('-'))
    raw = data / 'raw' / month
    raw.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(data / 'announcements.sqlite')
    init(db)
    failed = 0
    for mkt, kind in PAGES:
        fetched_at = datetime.now(TPE).isoformat(timespec='seconds')
        body = fetcher(URL.format(mkt=mkt, roc=y - 1911, m=m, kind=kind))
        if body is None:
            db.execute('INSERT INTO snapshots VALUES (?,?,?,?,?,?,?,?,?)', (month, mkt, kind, fetched_at, 'fetch_failed', None, None, None, None))
            failed += 1
        else:
            name = '%s_%d_%s_%s.html.gz' % (mkt, kind, now.date().isoformat(), fetched_at.replace(':', ''))
            (raw / name).write_bytes(gzip.compress(body))
            new = record(db, month, mkt, kind, fetched_at, body, name)
            print(month, mkt, kind, 'new', new, flush=True)
        db.commit()
        pause(3)
    db.close()
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
