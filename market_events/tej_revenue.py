"""Collect licensed TEJ revenue dates privately; never turn old data into live signals."""
from __future__ import annotations

import argparse
import calendar
import csv
import gzip
import json
import math
import os
import re
import sqlite3
import warnings
from datetime import date, datetime
from pathlib import Path

from market_events.tracker import TPE, data_dir


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def iso_day(value):
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except ValueError:
        return None


def normalize(row, observed_at, table):
    symbol = str(row.get('coid', ''))
    period, announced = iso_day(row.get('mdate')), iso_day(row.get('annd_s'))
    if not re.fullmatch(r'\d{4}', symbol) or not period or not announced:
        return None
    if announced[:7] < period[:7] or announced > observed_at[:10]:
        return None
    # Metadata confirms these are consolidated-preferred since 2013. Trial SDK
    # responses have misaligned later columns; never infer their mapping by position.
    revenue, yoy, mom = [number(row.get(k)) for k in ('d0001', 'd0003', 'd0004')]
    basis = 'reported_consolidated_preferred_since_2013'
    if any(v is None for v in (revenue, yoy, mom)) or revenue < 0:
        return None
    return dict(symbol=symbol, revenue_period=period[:7].replace('-', ''),
                revenue_thousand_twd=revenue, rev_yoy=yoy, rev_mom=mom,
                revenue_announcement_day=announced, revenue_source='TEJ',
                revenue_table=table, revenue_basis=basis, observed_at=observed_at)


def connect(path):
    db = sqlite3.connect(path)
    db.execute('''CREATE TABLE IF NOT EXISTS revenues (
        symbol TEXT, period TEXT, payload TEXT NOT NULL,
        PRIMARY KEY(symbol, period))''')
    return db


def save_rows(db, rows, now, table):
    count = 0
    for row in rows:
        record = normalize(row, now.isoformat(), table)
        if record:
            db.execute('INSERT OR REPLACE INTO revenues VALUES(?,?,?)',
                       (record['symbol'], record['revenue_period'], json.dumps(record)))
            count += 1
    db.commit()
    return count


def merge_recent(official, path, now):
    """Optional local cache; no SDK or credential is needed by the live observer."""
    merged = dict(official)
    if not path.exists():
        return merged
    db = sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True)
    try:
        for (payload,) in db.execute('SELECT payload FROM revenues ORDER BY period'):
            row = json.loads(payload)
            period = datetime.strptime(row['revenue_period'], '%Y%m').date()
            age = (now.year-period.year)*12+now.month-period.month
            seen = datetime.fromisoformat(row['observed_at'])
            if not 0 <= age <= 2 or seen > now or row['revenue_announcement_day'] > now.date().isoformat():
                continue
            old = merged.get(row['symbol']) or {}
            old_period = re.sub(r'\D', '', str(old.get('revenue_period', '')))
            if len(old_period) == 5:
                old_period = str(int(old_period[:3])+1911)+old_period[3:]
            # Official rows win equal-month ties; TEJ can fill a newer filed month.
            if row['revenue_period'] > old_period:
                merged[row['symbol']] = row
    finally:
        db.close()
    return merged


def load_key(path):
    value = path.read_text(encoding='utf-8-sig').strip().splitlines()[0]
    if '=' in value:
        value = value.split('=', 1)[1]
    return value.strip().strip('"').strip("'")


def collect(folder, key_file, table, now, api, import_cache=None):
    folder.mkdir(parents=True, exist_ok=True)
    db = connect(folder/'tej-revenue.sqlite')
    status = dict(checked_at=now.isoformat(), source='TEJ', table=table,
                  imported_rows=0, recent_rows=0, months=[], errors=[])
    try:
        if import_cache:
            with gzip.open(import_cache, 'rt', encoding='utf-8') as f:
                status['imported_rows'] = save_rows(db, csv.DictReader(f), now, table)
        api.ApiConfig.api_key = load_key(key_file)
        for offset in (1, 2):
            year, month = now.year, now.month-offset
            if month <= 0:
                year, month = year-1, month+12
            info = api.ApiConfig.info()
            remaining = int(info.get('rowsDayLimit', 0))-int(info.get('todayRows', 0))
            request_remaining = int(info.get('reqDayLimit', 0))-int(info.get('todayReqCount', 0))
            # A default TEJ page is up to 10,000 rows. Leave a 5,000-row reserve.
            if remaining < 15000 or request_remaining < 10:
                status['errors'].append('quota_reserve')
                break
            start, end = date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter('always')
                frame = api.get(table, mdate={'gte':start.isoformat(), 'lte':end.isoformat()}, paginate=False)
            if len(frame) >= 10000 or any('limit' in str(w.message).lower() or 'page' in str(w.message).lower() for w in caught):
                status['errors'].append('incomplete_page')
                break
            records = frame.to_dict(orient='records')
            required = {'coid', 'mdate', 'annd_s', 'd0001', 'd0003', 'd0004'}
            if records and not required.issubset(records[0]):
                status['errors'].append('unsupported_schema')
                break
            if any(iso_day(r.get('mdate')) is None or not start.isoformat() <= iso_day(r['mdate']) <= end.isoformat() for r in records):
                status['errors'].append('out_of_range_response')
                break
            count = save_rows(db, records, now, table)
            status['months'].append(dict(period=start.strftime('%Y%m'), fetched=len(frame), accepted=count))
            status['recent_rows'] += count
        status['state'] = ('partial' if status['errors'] else
                           'ok' if status['recent_rows'] else 'no_recent_data')
    except Exception as exc:
        # Never publish provider exception text, which can contain authenticated URLs.
        status['state'] = 'error'
        status['errors'].append(type(exc).__name__)
    finally:
        status['stored_rows'] = db.execute('SELECT COUNT(*) FROM revenues').fetchone()[0]
        status['latest_period'] = db.execute('SELECT MAX(period) FROM revenues').fetchone()[0]
        db.close()
    tmp = folder/'tej-revenue-status.tmp'
    tmp.write_text(json.dumps(status, ensure_ascii=False), encoding='utf-8')
    tmp.replace(folder/'tej-revenue-status.json')
    return status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--import-cache', type=Path)
    args = parser.parse_args()
    import tejapi
    status = collect(data_dir(), Path(os.getenv('TEJ_KEY_FILE', '/home/ubuntu/easystock-research/tej/tej.env')),
                     os.getenv('TEJ_REVENUE_TABLE', 'TRAIL/TASALE'), datetime.now(TPE), tejapi, args.import_cache)
    print(json.dumps(status, ensure_ascii=False))
    return 1 if status['state'] == 'error' else 0


if __name__ == '__main__':
    raise SystemExit(main())
