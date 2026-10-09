"""Forward-only revenue + positive announcement observation; never places orders."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
from datetime import datetime, date, timedelta, timezone
from pathlib import Path

TPE = timezone(timedelta(hours=8))
VERSION = 'revenue-positive-v1'
POSITIVE = re.compile(r'營收.{0,12}(?:創.{0,4}新高|成長|增加)|(?:獲利|淨利|每股盈餘|EPS).{0,12}(?:成長|增加|創.{0,4}新高)|轉虧為盈|訂單.{0,12}(?:增加|成長|滿載)|(?:取得|獲得|簽訂).{0,16}(?:訂單|供貨合約)|(?:上修|調升).{0,12}(?:展望|營收|獲利|財測)', re.I)
NEGATIVE = re.compile(r'不(?:會|再|及|如|能|確定)?(?:成長|增加)|未(?:成長|增加|取得)|衰退|下滑|減少|虧損擴大|下修|調降|澄清|不實|無法確認|無此|並非|非屬|尚未|預計|可能|若|假設')


def number(value):
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None


def positive_evidence(subject, body):
    """Conservative clause matching, with negation/hypothetical exclusion."""
    if re.search(r'澄清|不實|傳聞', str(subject or '')):
        return None
    text = str(subject or '') + '\n' + str(body or '')
    for clause in re.split(r'[。；;\n]', text):
        if POSITIVE.search(clause) and not NEGATIVE.search(clause):
            return clause.strip()[:240]
    return None


def period_date(value):
    s = re.sub(r'\D', '', str(value or ''))
    try:
        if len(s) == 5:
            return date(int(s[:3]) + 1911, int(s[3:]), 1)
        if len(s) == 6:
            return date(int(s[:4]), int(s[4:]), 1)
    except ValueError:
        pass
    return None


def trading_date(day, direction, is_open, include=False):
    if not include:
        day += timedelta(days=direction)
    for _ in range(40):
        if is_open(day):
            return day.isoformat()
        day += timedelta(days=direction)
    raise RuntimeError('Trading calendar unavailable')


def announced_revenue_period(subject, body, event_day):
    text = re.sub(r'\s+', '', str(subject or '') + '\n' + str(body or ''))
    matches = re.findall(r'(?:(\d{3,4})年)?(\d{1,2})月(?:份)?(?:之)?(?:自結)?(?:合併)?營收', text)
    periods = []
    for year, month in matches:
        y, m = int(year) if year else event_day.year, int(month)
        if year and y < 1911:
            y += 1911
        if not year and m > event_day.month:
            y -= 1
        if 1 <= m <= 12:
            periods.append(date(y,m,1))
    return max(periods) if periods else None


class Watch:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS signals(id TEXT PRIMARY KEY, symbol TEXT, payload TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS bars(symbol TEXT, day TEXT, payload TEXT NOT NULL, PRIMARY KEY(symbol,day));
          CREATE TABLE IF NOT EXISTS processed_events(id TEXT PRIMARY KEY);
        ''')

    def capture(self, announcements, revenues, now, is_open):
        stats = dict(events=0, growth=0, positive=0, added=0, newer_revenue_pending=0)
        for event in announcements:
            stats['events'] += 1
            rev = revenues.get(event['symbol']) or {}
            yoy, mom = number(rev.get('rev_yoy')), number(rev.get('rev_mom'))
            period = period_date(rev.get('revenue_period'))
            if yoy is None or mom is None or yoy <= 0 or mom <= 0 or period is None:
                continue
            age = (now.year-period.year)*12 + now.month-period.month
            if not 0 <= age <= 2:
                continue
            try:
                announced = announced_revenue_period(event.get('subject'),event.get('body'),date.fromisoformat(event['spoke_date']))
            except ValueError:
                continue
            if announced and announced > period:
                stats['newer_revenue_pending'] += 1
                continue
            stats['growth'] += 1
            evidence = positive_evidence(event.get('subject'), event.get('body'))
            if not evidence:
                continue
            # Delayed/backfilled announcements never masquerade as historical signals.
            try:
                event_day = date.fromisoformat(event['spoke_date'])
                seen = datetime.fromisoformat(event['first_seen_at']).astimezone(TPE)
            except (KeyError, ValueError):
                continue
            if not 0 <= (now.date()-event_day).days <= 7 or seen > now:
                continue
            stats['positive'] += 1
            event_key = hashlib.sha256((event['symbol']+'|'+event['spoke_date']+'|'+event['subject_key']+'|'+str(rev['revenue_period'])).encode()).hexdigest()[:24]
            if self.db.execute('SELECT 1 FROM processed_events WHERE id=?', (event_key,)).fetchone():
                continue
            target_day = trading_date(now.date(), 1, is_open)
            key = hashlib.sha256((event['symbol']+'|'+target_day+'|'+VERSION).encode()).hexdigest()[:24]
            self.db.execute('INSERT INTO processed_events VALUES(?)', (event_key,))
            if self.db.execute('SELECT 1 FROM signals WHERE id=?', (key,)).fetchone():
                continue
            signal = dict(id=key, symbol=event['symbol'], name=event.get('name') or event['symbol'],
                          signal_at=now.isoformat(), announcement_day=event['spoke_date'],
                          event_first_seen_at=event['first_seen_at'], subject=event.get('subject'), evidence=evidence,
                          source=event.get('sources'), source_url='https://mops.twse.com.tw/mops/#/web/t05st01',
                          rev_yoy=yoy, rev_mom=mom, revenue_period=rev['revenue_period'],
                          revenue_observed_at=now.isoformat(), rules_version=VERSION,
                          reference_day=trading_date(now.date(), -1, is_open, include=True),
                          target_day=target_day)
            self.db.execute('INSERT INTO signals VALUES(?,?,?)', (key, event['symbol'], json.dumps(signal, ensure_ascii=False)))
            stats['added'] += 1
        self.db.commit()
        return stats

    def store_bars(self, quotes, now):
        # Official daily bars are accepted only after close; no partial-day results.
        for symbol, row in quotes.items():
            day = row.get('date')
            if not day or day > now.date().isoformat() or (day == now.date().isoformat() and now.hour < 16):
                continue
            vals = [number(row.get(k)) for k in ('open', 'high', 'low', 'close')]
            if number(row.get('volume')) is None or number(row.get('volume')) <= 0:
                continue
            if any(v is None or v <= 0 for v in vals) or not vals[2] <= min(vals[0], vals[3]) <= max(vals[0], vals[3]) <= vals[1]:
                continue
            self.db.execute('INSERT OR REPLACE INTO bars VALUES(?,?,?)', (symbol, day, json.dumps(row)))
        self.db.commit()

    def snapshot(self, now, stats=None, errors=None):
        rows = []
        for stored in self.db.execute('SELECT payload FROM signals'):
            row = json.loads(stored[0])
            # Old captures with a later announced month remain in SQLite for audit,
            # but do not enter the active observations or aggregate performance.
            announced = announced_revenue_period(row.get('subject'),row.get('evidence'),date.fromisoformat(row['announcement_day']))
            if announced and announced > period_date(row['revenue_period']):
                continue
            def bar(day):
                r = self.db.execute('SELECT payload FROM bars WHERE symbol=? AND day=?', (row['symbol'], day)).fetchone()
                return json.loads(r[0]) if r else None
            ref, target = bar(row['reference_day']), bar(row['target_day'])
            row.update(reference_close=ref['close'] if ref else None, status='waiting', outcome=None)
            if target and ref:
                row['status'] = 'complete'
                row['outcome'] = {k: target[k] for k in ('open','high','low','close')}
                row['outcome'].update({k+'_pct': round((target[k]/ref['close']-1)*100, 4) for k in ('open','high','low','close')})
                row['outcome']['open_to_close_pct'] = round((target['close']/target['open']-1)*100, 4)
            elif row['target_day'] < now.date().isoformat() or (row['target_day'] == now.date().isoformat() and now.hour >= 16):
                row['status'] = 'missing_data'
            rows.append(row)
        rows.sort(key=lambda r: (r['signal_at'],r['symbol']), reverse=True)
        completed = [r for r in rows if r['status']=='complete']
        up = sum(r['outcome']['close_pct'] > 0 for r in completed)
        return dict(generated_at=now.isoformat(), rules_version=VERSION, mode='observation',
                    stats=stats or {}, errors=errors or [], summary=dict(total=len(rows), complete=len(completed),
                    up=up, up_rate=round(up/len(completed)*100,2) if completed else None,
                    mean_close_pct=round(sum(r['outcome']['close_pct'] for r in completed)/len(completed),4) if completed else None),
                    rows=rows[:200], displayed_limit=200)


def main():
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1]/'.env')
    from market_events.tracker import data_dir
    from market_calendar import is_market_open
    from update_market import fetch_json, parse_revenue, fetch_twse_daily_quotes, parse_twse_quotes, parse_tpex_quotes
    from firebase_store import FirebaseStore
    now = datetime.now(TPE)
    folder = data_dir()
    folder.mkdir(parents=True, exist_ok=True)
    watch = Watch(folder/'revenue-watch.sqlite')
    errors, revenues, quotes = [], {}, {}
    for market, url in (('TWSE','https://openapi.twse.com.tw/v1/opendata/t187ap05_L'),
                        ('TPEx','https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O')):
        try:
            revenues.update(parse_revenue(fetch_json(url, required=True)))
        except Exception:
            errors.append(market+' revenue unavailable')
    for market, fetcher in (
        ('TWSE', lambda: parse_twse_quotes(fetch_twse_daily_quotes())),
        ('TPEx', lambda: parse_tpex_quotes(fetch_json('https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes', required=True)))):
        try:
            quotes.update(fetcher())
        except Exception:
            errors.append(market+' daily quotes unavailable')
    event_path = folder/'events.sqlite'
    events = []
    if event_path.exists():
        db = sqlite3.connect(event_path.as_uri()+'?mode=ro', uri=True)
        db.row_factory = sqlite3.Row
        events = [dict(r) for r in db.execute('SELECT * FROM announcements WHERE spoke_date>=?', ((now.date()-timedelta(days=7)).isoformat(),))]
        db.close()
    else:
        errors.append('announcement database unavailable')
    calendar = {}
    def is_open(day):
        if day not in calendar:
            calendar[day] = is_market_open(day)[0]
        return calendar[day]
    stats = watch.capture(events, revenues, now, is_open)
    watch.store_bars(quotes, now)
    snapshot = watch.snapshot(now, stats, errors)
    path = folder/'revenue-watch-latest.json'
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(snapshot,ensure_ascii=False),encoding='utf-8')
    tmp.replace(path)
    FirebaseStore().root.child('public_feed').child('revenue_observation').set(snapshot)
    print(json.dumps(dict(stats=stats,summary=snapshot['summary'],errors=errors)))
    watch.db.close()


if __name__ == '__main__':
    main()
