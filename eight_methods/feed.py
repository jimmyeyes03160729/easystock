"""Read-only observer of existing Shioaji journal / official daily bars.

No broker connection, database writes, holdout reads or orders. Only the two
new public feed keys are published. Run as a separate operator-approved job.
"""
import argparse
import json
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from .rules import TPE, OPENING, CLOSING, SOURCE_OPEN, opening, closing, stamp

DATA = Path(os.getenv('EIGHT_JOURNAL_DIR', '/home/ubuntu/easystock-learning-data'))
DAILY = Path(os.getenv('EIGHT_DAILY_DB', '/home/ubuntu/easystock-learning-data/rebound/market-daily.sqlite'))
OUT = Path(os.getenv('EIGHT_OUT_DIR', '/home/ubuntu/easystock-eight-methods'))

def read_journal(path, now):
    rows = {}
    if not path.exists():
        return rows, ['缺少今日 Shioaji journal']
    errors = 0
    with path.open(encoding='utf-8') as f:
        for line in f:
            try:
                item = json.loads(line)
                if item.get('kind') != 'sample':
                    continue
                r = item['data']
                observed, quote, available = stamp(r['observed_at']), stamp(r['quote_at']), stamp(item['recorded_at'])
                if observed > now or available > now or quote > observed or quote.date() != now.date():
                    continue
                symbol = str(r['symbol'])
                if not re.fullmatch(r'[1-9]\d{3}|IX0001|IX0043', symbol):
                    continue
                target = rows.setdefault(symbol, {'symbol': symbol, 'name': r.get('name', symbol), 'quotes': []})
                target['quotes'].append({'price': r['price'], 'quote_at': r['quote_at'], 'available_at': item['recorded_at']})
                if 'quote_at' not in target or quote >= stamp(target['quote_at']):
                    target.update(price=r['price'], quote_at=r['quote_at'])
            except (ValueError, KeyError, TypeError):
                errors += 1
    return rows, [f'journal 無效列 {errors}'] if errors else []

def enrich_daily(rows, path, now):
    if not path.exists():
        return ['缺官方日 K 資料庫']
    db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
    try:
        for r in rows.values():
            if r['symbol'] in ('IX0001', 'IX0043'):
                name = '發行量加權股價指數' if r['symbol'] == 'IX0001' else '櫃買指數'
                data = db.execute('SELECT close FROM indices WHERE name=? AND day<? ORDER BY day DESC LIMIT 1', (name, now.date().isoformat())).fetchone()
                r['previous_close'] = data[0] if data else None
                continue
            bars = db.execute('SELECT day,close,volume,exchange FROM bars WHERE symbol=? AND day<? ORDER BY day DESC LIMIT 61', (r['symbol'], now.date().isoformat())).fetchall()
            if not bars:
                continue
            session = db.execute("SELECT max(day) FROM sessions WHERE exchange=? AND status='open' AND day<?", (bars[0][3], now.date().isoformat())).fetchone()[0]
            if bars[0][0] != session:
                continue  # suspension / stale symbol history
            r.update(previous_close=bars[0][1], past_closes=[b[1] for b in reversed(bars)],
                     past_volumes=[b[2] for b in reversed(bars)], exchange=bars[0][3], daily_as_of=session)
    except sqlite3.Error:
        return ['官方日 K schema 不完整']
    finally:
        db.close()
    return []

def build(rows, now, diagnostics=()):
    opened, closed, markets = [], [], []
    for r in rows.values():
        base = {k: r.get(k) for k in ('symbol', 'name', 'price', 'quote_at', 'daily_as_of')}
        obs = dict(base, **opening(r.get('previous_close'), r.get('quotes', []), now))
        if r['symbol'] in ('IX0001', 'IX0043'):
            markets.append(obs)
        else:
            opened.append(obs)
            benchmark = rows.get('IX0043' if r.get('exchange') == 'TPEX' else 'IX0001', {})
            try:
                at = stamp(benchmark['quote_at'])
                prev = benchmark['previous_close']
                if 0 <= (now-at).total_seconds() <= 30 and prev > 0:
                    r = dict(r, benchmark_gain_pct=(benchmark['price']/prev-1)*100)
            except (KeyError, ValueError, TypeError):
                pass
            closed.append(dict(base, **closing(r, now)))
    for symbol, name in [('IX0001', '加權指數'), ('IX0043', '櫃買指數')]:
        if not any(r['symbol'] == symbol for r in markets):
            markets.append(dict(symbol=symbol, name=name, **opening(None, [], now)))
    common = {'schema_version': 1, 'day': now.date().isoformat(), 'updated_at': now.isoformat(),
              'timezone': 'Asia/Taipei', 'diagnostics': list(diagnostics),
              'scope': '既有 journal 實際觀察股票；非全市場掃描。journal 每五分鐘取樣，邊界缺 Tick 不補值。',
              'source': 'Shioaji 成交時間戳 journal + 官方 TWSE/TPEx 日 K（唯讀）'}
    return {'opening_eight': dict(common, version=OPENING, reference=SOURCE_OPEN, rows=opened, markets=markets),
            'closing_eight': dict(common, version=CLOSING, ruleset='TW_CLOSING_RULES_V1', rows=closed)}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--publish', action='store_true')
    args = parser.parse_args()
    now = datetime.now(TPE)
    rows, diagnostics = read_journal(DATA / ('journal-' + now.date().isoformat() + '.jsonl'), now)
    if args.publish:
        from firebase_store import FirebaseStore
        store = FirebaseStore()
        # Reuse an existing bounded, exchange-timestamped projection. Its volume
        # is intentionally not treated as cumulative market volume.
        try:
            current = store.root.child('intraday_live').child('a_candidates').get() or {}
            for r in current.get('rows', []):
                symbol = str(r.get('symbol', ''))
                if re.fullmatch(r'[1-9]\d{3}', symbol) and stamp(r['quote_at']) <= now:
                    target = rows.setdefault(symbol, {'symbol': symbol, 'name': r.get('name', symbol), 'quotes': []})
                    if 'quote_at' not in target or stamp(r['quote_at']) >= stamp(target['quote_at']):
                        target.update(price=r.get('price'), quote_at=r['quote_at'])
        except (ValueError, TypeError, KeyError, AttributeError):
            diagnostics.append('既有即時觀察投影不可用')
    diagnostics += enrich_daily(rows, DAILY, now)
    feeds = build(rows, now, diagnostics)
    OUT.mkdir(parents=True, exist_ok=True)
    for key, feed in feeds.items():
        path = OUT / (key + '.json')
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps(feed, ensure_ascii=False, allow_nan=False), encoding='utf-8')
        tmp.replace(path)
    if args.publish:
        node = store.root.child('public_feed')
        for key, feed in feeds.items():
            node.child(key).set(feed)
    print(json.dumps({'observed_stocks': len(feeds['opening_eight']['rows']), 'diagnostics': diagnostics}, ensure_ascii=False))

if __name__ == '__main__':
    main()
