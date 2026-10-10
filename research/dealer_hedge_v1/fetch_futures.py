#!/usr/bin/env python3
"""Fetch TAIEX futures (TX) institutional open interest from the free FinMind API into SQLite. Research only.

Dataset TaiwanFuturesInstitutionalInvestors, data_id TX, 2021-12-01..2026-10-02 (hard cutoff), one request per year
chunk, raw responses kept gzipped. No token is used (free level: 300 requests per hour).
"""
import gzip, json, sqlite3, sys, time, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent / 'data'
URL = 'https://api.finmindtrade.com/api/v4/data?'
CHUNKS = (('2021-12-01', '2022-12-31'), ('2023-01-01', '2023-12-31'), ('2024-01-01', '2024-12-31'),
          ('2025-01-01', '2025-12-31'), ('2026-01-01', '2026-10-02'))
LAST_DAY = '2026-10-02'
INVESTORS = {'外資': 'foreign', '投信': 'trust', '自營商': 'dealer'}


def rows_of(payload):
    """(day, investor, long_oi, short_oi, long_deal, short_deal) for TX rows on or before LAST_DAY."""
    if payload.get('status') != 200:
        raise ValueError('FinMind status %s: %s' % (payload.get('status'), payload.get('msg')))
    out = []
    for r in payload.get('data') or []:
        who = INVESTORS.get(r.get('institutional_investors'))
        if r.get('futures_id') != 'TX' or who is None or r['date'] > LAST_DAY:
            continue
        out.append((r['date'], who, int(r['long_open_interest_balance_volume']), int(r['short_open_interest_balance_volume']),
                    int(r['long_deal_volume']), int(r['short_deal_volume'])))
    return out


def main():
    (ROOT / 'raw_futures').mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(ROOT / 'futures.sqlite')
    db.execute('''CREATE TABLE IF NOT EXISTS tx_inst (day TEXT NOT NULL, investor TEXT NOT NULL, long_oi INTEGER, short_oi INTEGER,
        long_deal INTEGER, short_deal INTEGER, PRIMARY KEY(day, investor))''')
    for start, end in CHUNKS:
        q = urllib.parse.urlencode({'dataset': 'TaiwanFuturesInstitutionalInvestors', 'data_id': 'TX', 'start_date': start, 'end_date': end})
        req = urllib.request.Request(URL + q, headers={'User-Agent': 'Mozilla/5.0 (research; futures institutional)'})
        body = urllib.request.urlopen(req, timeout=120).read()
        (ROOT / 'raw_futures' / ('tx_%s_%s.json.gz' % (start, end))).write_bytes(gzip.compress(body))
        rows = rows_of(json.loads(body))
        db.executemany('INSERT OR REPLACE INTO tx_inst VALUES (?,?,?,?,?,?)', rows)
        db.commit()
        print(start, end, len(rows), flush=True)
        time.sleep(15)
    n, lo, hi = db.execute("SELECT COUNT(DISTINCT day), MIN(day), MAX(day) FROM tx_inst WHERE investor='foreign'").fetchone()
    db.close()
    print('foreign days=%d %s..%s' % (n, lo, hi))


if __name__ == '__main__':
    main()
