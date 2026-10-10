#!/usr/bin/env python3
"""Fetch the MOPS listed / OTC company buyback summary table (all programs since 2008) into SQLite. Research only.

The table lists, per program: board resolution date, purpose, amount cap, planned shares, price range, planned period
start / end, and ex-post execution fields. Only the announcement-time columns are stored for the study; the raw page is
kept gzipped for provenance. Two requests only, spaced 12 s apart (mopsov drops connections after bursts).
"""
import gzip, re, sqlite3, sys, time, urllib.request
from pathlib import Path

ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('/home/ubuntu/easystock-research/buyback_v1/data')
URL = 'https://mopsov.twse.com.tw/mops/web/ajax_t35sc09'
DATE = re.compile(r'^(\d{2,3})/(\d{2})/(\d{2})$')
CODE = re.compile(r'^[1-9]\d{3}$')


def iso(s):
    m = DATE.match(s.strip())
    return '%04d-%s-%s' % (int(m.group(1)) + 1911, m.group(2), m.group(3)) if m else None


def num(s):
    s = re.sub(r'&nbsp;|,|\s', '', s)
    try:
        return float(s)
    except ValueError:
        return None


def clean(cell):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', cell).replace('&nbsp;', ' ')).strip()


def parse(html):
    """Announcement-time columns of every program row: seq, code, name, board date, purpose, cap, planned shares, price min/max, start, end."""
    out = []
    for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.S):
        cells = [clean(c) for c in re.findall(r'<td[^>]*>(.*?)</td>', tr, re.S)]
        if len(cells) < 12 or not cells[0].isdigit() or not CODE.match(cells[1]):
            continue
        board, start, end = iso(cells[3]), iso(cells[9]), iso(cells[10])
        if not board or not start or not end:
            continue
        out.append((cells[1], cells[2], board, cells[4], num(cells[5]), num(cells[6]), num(cells[7]), num(cells[8]), start, end))
    return out


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / 'raw').mkdir(exist_ok=True)
    db = sqlite3.connect(ROOT / 'buyback.sqlite')
    db.execute('''CREATE TABLE IF NOT EXISTS programs (symbol TEXT NOT NULL, name TEXT, board_date TEXT NOT NULL, purpose TEXT, cap_amount REAL,
        planned_shares REAL, price_min REAL, price_max REAL, start_date TEXT NOT NULL, end_date TEXT NOT NULL, market TEXT NOT NULL,
        PRIMARY KEY(symbol, board_date, start_date))''')
    for typek in ('sii', 'otc'):
        req = urllib.request.Request(URL, data=('encodeURIComponent=1&step=1&firstin=1&off=1&TYPEK=%s&year=115' % typek).encode(),
                                     headers={'User-Agent': 'Mozilla/5.0 (research; buyback summary)'})
        for attempt in range(3):
            try:
                body = urllib.request.urlopen(req, timeout=120).read()
                break
            except Exception as e:
                print('retry', typek, type(e).__name__, flush=True)
                time.sleep(30 * (attempt + 1))
        else:
            print('FAILED', typek)
            continue
        (ROOT / 'raw' / ('t35sc09_%s.html.gz' % typek)).write_bytes(gzip.compress(body))
        rows = parse(body.decode('utf-8', 'replace'))
        db.execute('DELETE FROM programs WHERE market = ?', (typek,))
        db.executemany('INSERT OR REPLACE INTO programs VALUES (?,?,?,?,?,?,?,?,?,?,?)', [r + (typek,) for r in rows])
        db.commit()
        print(typek, 'programs', len(rows), flush=True)
        time.sleep(12)
    db.close()


if __name__ == '__main__':
    main()
