"""Offline research only. No orders, LINE pushes, Firebase writes or model promotion."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen

TPE = timezone(timedelta(hours=8))
FEATURES = ('gain_pct', 'return_5m_pct', 'volume_ratio', 'vwap_distance_pct', 'market_gain_pct')


def stamp(value):
    t = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if t.tzinfo is None:
        raise ValueError('Timestamp must include timezone')
    return t.astimezone(TPE)


def number(x):
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x):
        raise ValueError('Expected finite number')
    return float(x)


def encode(x):
    return json.dumps(x, ensure_ascii=False, sort_keys=True, allow_nan=False)


def gate(snapshot, settings):
    """Run on a fresh snapshot both before recommendation and before LINE send."""
    price, prev = number(snapshot['price']), number(snapshot['previous_close'])
    lo, hi, cap = (number(settings[k]) for k in ('min_price', 'max_price', 'max_gain_pct'))
    if not (0 < lo <= hi and 0 <= cap <= 100 and price > 0 and prev > 0):
        raise ValueError('Invalid prices or settings')
    age = (stamp(snapshot['observed_at']) - stamp(snapshot['quote_at'])).total_seconds()
    if not 0 <= age <= 60:
        return False, 'stale_or_future_quote'
    if stamp(snapshot['observed_at']).date() != stamp(snapshot['quote_at']).date():
        return False, 'quote_date_mismatch'
    if price < lo or price > hi:
        return False, 'price_range'
    if (price / prev - 1) * 100 > cap + 1e-9:
        return False, 'gain_cap'
    return True, 'eligible'


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=15)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, day TEXT, body TEXT);
        CREATE TABLE IF NOT EXISTS outcomes(id TEXT PRIMARY KEY REFERENCES events(id), body TEXT);
        CREATE TABLE IF NOT EXISTS bars(symbol TEXT, at TEXT, body TEXT, PRIMARY KEY(symbol,at));
        ''')

    def immutable(self, table, key, body):
        old = self.db.execute(f'SELECT body FROM {table} WHERE id=?', (key,)).fetchone()
        value = encode(body)
        if old:
            if old[0] != value:
                raise ValueError('Conflicting immutable record: ' + key)
            return
        with self.db:
            if table == 'events':
                day = stamp(body['observed_at']).date().isoformat()
                self.db.execute('INSERT INTO events VALUES(?,?,?)', (key, day, value))
            else:
                self.db.execute('INSERT INTO outcomes VALUES(?,?)', (key, value))

    def capture(self, event):
        # Adapter must calculate features ONLY from data available at observed_at.
        event = json.loads(encode(event))
        observed = stamp(event['observed_at'])
        if stamp(event['features_as_of']) > observed:
            raise ValueError('Future features')
        if (observed - stamp(event['features_as_of'])).total_seconds() > 60:
            raise ValueError('Stale features')
        if not isinstance(event['baseline_selected'], bool):
            raise ValueError('baseline_selected must be boolean')
        for key in ('symbol', 'policy_version', 'universe_version'):
            if not isinstance(event[key], str) or not event[key]:
                raise ValueError('Missing ' + key)
        event['features'] = {k: number(event['features'][k]) for k in FEATURES}
        eligible, reason = gate(event, event['settings'])
        gain = (event['price'] / event['previous_close'] - 1) * 100
        if abs(event['features']['gain_pct'] - gain) > 1e-6:
            raise ValueError('Inconsistent gain feature')
        event['eligible'], event['exclusion_reason'] = eligible, reason
        # Generated ID cannot be reused for a different symbol/time/policy.
        key = hashlib.sha256(encode([event['symbol'], observed.isoformat(), event['policy_version']]).encode()).hexdigest()[:24]
        event['id'] = key
        self.immutable('events', key, event)
        return key

    def bar(self, bar):
        b = json.loads(encode(bar))
        t = stamp(b['at'])  # end of COMPLETED one-minute regular-session bar
        if stamp(b['available_at']) < t:
            raise ValueError('Incomplete bar')
        o, h, l, c = (number(b[k]) for k in ('open', 'high', 'low', 'close'))
        if not 0 < l <= min(o, c) <= max(o, c) <= h or number(b['volume']) < 0:
            raise ValueError('Invalid OHLCV')
        b['at'] = t.isoformat()
        old = self.db.execute('SELECT body FROM bars WHERE symbol=? AND at=?', (b['symbol'], b['at'])).fetchone()
        if old and old[0] != encode(b):
            raise ValueError('Conflicting bar; keep corrections separately')
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO bars VALUES(?,?,?)', (b['symbol'], b['at'], encode(b)))

    def outcome(self, result):
        """Adapter supplies actual or explicitly simulated fills; never infer fills from highs."""
        r = json.loads(encode(result))
        row = self.db.execute('SELECT body FROM events WHERE id=?', (r['id'],)).fetchone()
        if row is None:
            raise ValueError('Unknown event')
        event = json.loads(row[0])
        if r['kind'] not in ('actual', 'simulation'):
            raise ValueError('Unknown fill kind')
        if not r.get('execution_policy'):
            raise ValueError('Execution policy required')
        start, end = stamp(r['entry_at']), stamp(r['exit_at'])
        if not stamp(event['observed_at']) <= start <= end or end.date() != stamp(event['observed_at']).date():
            raise ValueError('Not a same-day post-signal outcome')
        entry, exit_price, qty, costs = (number(r[k]) for k in ('entry_price', 'exit_price', 'shares', 'cost_twd'))
        if min(entry, exit_price, qty) <= 0 or costs < 0:
            raise ValueError('Invalid fill or costs')
        # Prices must include slippage. cost_twd includes both fees and sell-side tax.
        r['net_return_pct'] = ((exit_price-entry)*qty-costs)/(entry*qty)*100
        self.immutable('outcomes', r['id'], r)

    def rows(self, day=None):
        sql = 'SELECT e.body,o.body FROM events e LEFT JOIN outcomes o ON e.id=o.id'
        rows = self.db.execute(sql + (' WHERE e.day=?' if day else '') + ' ORDER BY e.day,e.id', (day,) if day else ())
        return [(json.loads(a), json.loads(b) if b else None) for a, b in rows]


def metrics(values):
    return {'count': len(values), 'win_rate': sum(v > 0 for v in values)/len(values) if values else None,
            'mean_net_return_pct': sum(values)/len(values) if values else None}


def surge_events(store, day, threshold_pct=2.0):
    """Post-close discovery, 5-minute close-to-close rise; never a training feature."""
    grouped = {}
    for symbol, _, body in store.db.execute('SELECT symbol,at,body FROM bars ORDER BY symbol,at'):
        bar = json.loads(body)
        t = stamp(bar['at'])
        if t.date().isoformat() == day:
            grouped.setdefault(symbol, {})[t] = bar
    found = []
    for symbol, bars in grouped.items():
        last_event = None
        for t, bar in sorted(bars.items()):
            window = [bars.get(t-timedelta(minutes=i)) for i in range(6)]
            if any(b is None for b in window):
                continue
            gain = (bar['close']/window[-1]['close']-1)*100
            if gain >= threshold_pct and (last_event is None or t-last_event >= timedelta(minutes=5)):
                found.append({'symbol':symbol,'at':t.isoformat(),'gain_5m_pct':gain})
                last_event = t
    return {'definition':'5-minute close-to-close rise', 'threshold_pct':threshold_pct,
            'symbols_with_bars':len(grouped),'count':len(found),
            'top_events':sorted(found,key=lambda e:e['gain_5m_pct'],reverse=True)[:30],
            'scope':'Only stored bars; not a whole-market completeness claim'}


def report(store, day):
    datetime.strptime(day, '%Y-%m-%d')
    rows = store.rows(day)
    return {'date': day, 'mode': 'research_only', 'events': len(rows),
            'eligible': sum(e['eligible'] for e, _ in rows),
            'missing_outcomes': sum(o is None for _, o in rows),
            'surges': surge_events(store, day),
            'actual': metrics([o['net_return_pct'] for _, o in rows if o and o['kind']=='actual']),
            'simulation': metrics([o['net_return_pct'] for _, o in rows if o and o['kind']=='simulation']),
            'warning': 'Signal averages are not portfolio returns. Missing outcomes are not losses or wins.'}


def gemini_review(summary):
    key, model = os.environ.get('GEMINI_API_KEY'), os.environ.get('GEMINI_REVIEW_MODEL')
    if not key or not model:
        return {'status': 'skipped', 'reason': 'GEMINI_API_KEY or GEMINI_REVIEW_MODEL missing'}
    if not re.fullmatch(r'[A-Za-z0-9._-]+', model):
        raise ValueError('Invalid model name')
    schema = {'type':'OBJECT', 'properties': {'summary': {'type':'STRING'},
        'hypotheses': {'type':'ARRAY', 'items': {'type':'STRING'}},
        'data_gaps': {'type':'ARRAY', 'items': {'type':'STRING'}}},
        'required':['summary','hypotheses','data_gaps']}
    prompt = ('你是台股研究助理。只依提供的統計，用繁體中文產生收盤檢討。不得虛構股票、新聞、'
              '因果或勝率改善；假設必須標明待驗證。不得提供下單指令。資料缺少時明說。JSON資料：' + encode(summary))
    body = {'contents':[{'parts':[{'text':prompt}]}], 'generationConfig':{
        'responseMimeType':'application/json', 'responseSchema':schema, 'temperature':0.2}}
    req = Request('https://generativelanguage.googleapis.com/v1beta/models/'+model+':generateContent',
                  data=encode(body).encode(), headers={'Content-Type':'application/json','x-goog-api-key':key})
    try:
        with urlopen(req, timeout=45) as response:
            raw = json.load(response)
        parts = raw['candidates'][0]['content']['parts']
        data = json.loads(''.join(p.get('text','') for p in parts))
        if not isinstance(data.get('summary'), str) or any(not isinstance(data.get(k), list) or any(not isinstance(v,str) for v in data[k]) for k in ('hypotheses','data_gaps')):
            raise ValueError('Invalid response schema')
        return {'status':'ok','model':model,'review':data,'use':'post_close_only'}
    except Exception as exc:
        # Never log API responses/headers or keys.
        return {'status':'failed','error_type':type(exc).__name__}


def train(store):
    """Candidate experiment only. Fixed last 20 dates held out, one date gap, no promotion."""
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.linear_model import LogisticRegression
    rows = [(e,o) for e,o in store.rows() if o and e['eligible'] and o['kind']=='simulation']
    policies = {(e['policy_version'], o['execution_policy'], e['universe_version'], encode(e['settings'])) for e,o in rows}
    if len(policies) != 1:
        return {'status':'blocked','reason':'Need one consistent signal, execution, universe and settings version'}
    dates = sorted({stamp(e['observed_at']).date().isoformat() for e,o in rows})
    if len(dates) < 81 or len(rows) < 500:
        return {'status':'blocked','reason':'Need at least 81 dates and 500 labeled simulation events','dates':len(dates),'samples':len(rows)}
    fit_dates, test_dates = set(dates[:-21]), set(dates[-20:])
    fit = [(e,o) for e,o in rows if stamp(e['observed_at']).date().isoformat() in fit_dates]
    test = [(e,o) for e,o in rows if stamp(e['observed_at']).date().isoformat() in test_dates]
    y = [int(o['net_return_pct']>0) for e,o in fit]
    if min(sum(y),len(y)-sum(y)) < 30:
        return {'status':'blocked','reason':'Need at least 30 positive and 30 nonpositive training outcomes'}
    model = make_pipeline(StandardScaler(), LogisticRegression(C=1.0,max_iter=2000,random_state=7))
    model.fit([[e['features'][k] for k in FEATURES] for e,o in fit],y)
    p = model.predict_proba([[e['features'][k] for k in FEATURES] for e,o in test])[:,1]
    selected = [o['net_return_pct'] for (e,o),v in zip(test,p) if v >= .6]
    baseline = [o['net_return_pct'] for e,o in test if e['baseline_selected']]
    scaler, clf = model.steps[0][1], model.steps[1][1]
    return {'status':'candidate_only','deployment_allowed':False,
            'train_through':dates[-22],'gap_date':dates[-21],'test_from':dates[-20],'test_through':dates[-1],
            'train_samples':len(fit),'test_samples':len(test), 'threshold':.6,
            'candidate':metrics(selected),'baseline':metrics(baseline),
            'brier_score':sum((float(v)-int(o['net_return_pct']>0))**2 for (e,o),v in zip(test,p))/len(test),
            'model':{'features':FEATURES,'mean':scaler.mean_.tolist(),'scale':scaler.scale_.tolist(),
                     'coef':clf.coef_[0].tolist(),'intercept':float(clf.intercept_[0])},
            'limitations':['Uncalibrated scores; not a claimed success probability',
                'No capital/overlap/portfolio drawdown simulation yet',
                'Repeated use of the same holdout invalidates independent evaluation',
                'Forward shadow validation and dated walk-forward folds required before production']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', required=True)
    sub = parser.add_subparsers(dest='command', required=True)
    ingest = sub.add_parser('ingest'); ingest.add_argument('file')
    review = sub.add_parser('review'); review.add_argument('--date',required=True); review.add_argument('--gemini',action='store_true')
    sub.add_parser('train')
    args = parser.parse_args()
    store = Store(args.db)
    if args.command == 'ingest':
        counts = {'event':0,'bar':0,'outcome':0}
        with open(args.file, encoding='utf-8') as source:
            for line in source:
                obj = json.loads(line)
                kind, data = obj['type'],obj['data']
                {'event':store.capture,'bar':store.bar,'outcome':store.outcome}[kind](data)
                counts[kind] += 1
        result = {'imported':counts}
    elif args.command == 'review':
        result = report(store,args.date)
        if args.gemini:
            result['ai'] = gemini_review(result)
    else:
        result = train(store)
    print(encode(result))


if __name__ == '__main__':
    main()
