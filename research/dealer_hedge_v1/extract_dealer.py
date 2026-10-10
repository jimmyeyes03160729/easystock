#!/usr/bin/env python3
"""Split the dealer column of the stored INST_FLOW_V1 pages into proprietary (自行買賣) and hedging (避險) net shares.

Reads only the gzipped raw TWSE T86 / TPEx 3itrade_hedge pages already fetched for 2022-01-03..2026-10-02; no network.
A row is kept only when proprietary + hedging equals the page's dealer total (consistency flag stored per row).
"""
import gzip, json, re, sqlite3, sys
from pathlib import Path

RAW = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('/home/ubuntu/easystock-research/inst_flow_v1/data/raw')
OUT_DB = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).resolve().parent / 'data' / 'dealer.sqlite'
LAST_DAY = '2026-10-02'
COMMON = re.compile(r'^[1-9]\d{3}$')
TWSE_FIELDS = {11: '自營商買賣超股數', 14: '自營商買賣超股數(自行買賣)', 17: '自營商買賣超股數(避險)'}


def num(s):
    s = str(s).replace(',', '').strip()
    return int(s) if re.fullmatch(r'-?\d+', s) else None


def parse_twse(payload):
    """symbol -> (self_net, hedge_net, dealer_net, consistent); None when the header is not the expected layout."""
    if payload.get('stat') != 'OK':
        return {}
    fields = payload.get('fields') or []
    if any(len(fields) <= i or fields[i] != name for i, name in TWSE_FIELDS.items()):
        return None
    out = {}
    for r in payload.get('data') or []:
        sym = r[0].strip()
        if not COMMON.match(sym) or len(r) < 19:
            continue
        d, sf, hg = num(r[11]), num(r[14]), num(r[17])
        if None not in (d, sf, hg):
            out[sym] = (sf, hg, d, sf + hg == d)
    return out


def parse_tpex(payload):
    """TPEx columns: 14-16 dealer proprietary, 17-19 dealer hedging, 20-22 dealer total (buy, sell, net)."""
    out = {}
    tables = payload.get('tables') or []
    for r in (tables[0].get('data') or []) if tables else []:
        sym = r[0].strip()
        if not COMMON.match(sym) or len(r) < 24:
            continue
        sf, hg, d = num(r[16]), num(r[19]), num(r[22])
        if None not in (d, sf, hg):
            out[sym] = (sf, hg, d, sf + hg == d)
    return out


def main():
    OUT_DB.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(OUT_DB)
    db.execute('''CREATE TABLE IF NOT EXISTS dealer (symbol TEXT NOT NULL, day TEXT NOT NULL, market TEXT NOT NULL,
        self_net INTEGER, hedge_net INTEGER, dealer_net INTEGER, consistent INTEGER, PRIMARY KEY(symbol, day))''')
    db.execute('CREATE TABLE IF NOT EXISTS pages (page TEXT PRIMARY KEY, day TEXT, market TEXT, rows INTEGER, inconsistent INTEGER, layout_ok INTEGER)')
    bad_layout = 0
    for p in sorted(RAW.glob('*.json.gz')):
        page = p.name[:-len('.json.gz')]
        mkt, day = page.split('_', 1)
        if day > LAST_DAY:
            continue
        rows = (parse_twse if mkt == 'twse' else parse_tpex)(json.loads(gzip.decompress(p.read_bytes())))
        if rows is None:
            bad_layout += 1
            db.execute('INSERT OR REPLACE INTO pages VALUES (?,?,?,?,?,?)', (page, day, mkt, 0, 0, 0))
            continue
        db.executemany('INSERT OR REPLACE INTO dealer VALUES (?,?,?,?,?,?,?)',
                       [(s, day, mkt, v[0], v[1], v[2], int(v[3])) for s, v in rows.items()])
        db.execute('INSERT OR REPLACE INTO pages VALUES (?,?,?,?,?,?)',
                   (page, day, mkt, len(rows), sum(1 for v in rows.values() if not v[3]), 1))
    db.commit()
    n_pages, n_rows, n_bad = db.execute('SELECT COUNT(*), SUM(rows), SUM(inconsistent) FROM pages').fetchone()
    db.close()
    print('pages=%d rows=%d inconsistent=%d bad_layout=%d' % (n_pages, n_rows or 0, n_bad or 0, bad_layout))


if __name__ == '__main__':
    main()
