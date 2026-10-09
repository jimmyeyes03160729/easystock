#!/usr/bin/env python3
"""One-off history backfill for the market events store (same events.sqlite as the tracker).

  python -m market_events.backfill conferences --start 2025-01 --end 2026-09
      MOPS t100sb02_1 per market/month (2 requests per month).
  python -m market_events.backfill announcements --years 114 115
      MOPS t05st01 per company per ROC year: every material announcement with second-level timestamps
      (subject only). Covers companies listed on TWSE/TPEx today, so delisted names are missing.

Progress is kept in `backfill_progress`, so a rerun resumes where it stopped. mopsov drops connections from IPs
that burst requests: requests are spaced `--pause` seconds apart, and after several consecutive failures the run
backs off; if failures persist it stops with exit code 2 rather than deepen a block.
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
import time
from typing import Any, Callable

from market_events import tracker as t

TWSE_COMPANIES_URL = 'https://openapi.twse.com.tw/v1/opendata/t187ap03_L'
TPEX_COMPANIES_URL = 'https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O'
MOPS_HISTORY_URL = 'https://mopsov.twse.com.tw/mops/web/ajax_t05st01'
EMPTY_MARK = '查無'  # "查無資料" / "資料庫中查無需求資料"

PROGRESS_SCHEMA = """
CREATE TABLE IF NOT EXISTS backfill_progress (
    task TEXT NOT NULL, item TEXT NOT NULL, status TEXT NOT NULL, rows INTEGER, fetched_at TEXT NOT NULL,
    PRIMARY KEY (task, item));
"""


def parse_history(page: str) -> list[dict]:
    """Rows of a t05st01 company/year page."""
    out = []
    for chunk in t.ROW_SPLIT.split(page)[1:]:
        body = chunk.split('</tr>')[0]
        cells = t.TD.findall(body)
        if len(cells) < 5:
            continue
        symbol, name, spoke, spoke_time, subject = (t.strip_tags(c) for c in cells[:5])
        spoke_iso = t.roc_to_iso(spoke)
        if not re.fullmatch(r'[0-9A-Z]{4,6}', symbol) or not spoke_iso or not subject:
            continue
        market = re.search(r"TYPEK\.value='(\w+)'", body)
        out.append({'symbol': symbol, 'name': name, 'market': market.group(1) if market else None,
                    'spoke_date': spoke_iso, 'spoke_time': t.hms(spoke_time), 'subject': subject, 'clause': None,
                    'fact_date': None, 'body': None, 'source': 'mops_history'})
    return out


def companies(fetch: Callable[..., Any]) -> list[tuple[str, str]]:
    out = []
    for url, market in ((TWSE_COMPANIES_URL, 'sii'), (TPEX_COMPANIES_URL, 'otc')):
        for row in fetch(url, as_json=True):
            symbol = t.field(row, '公司代號', 'SecuritiesCompanyCode')
            if re.fullmatch(r'[0-9A-Z]{4,6}', symbol):
                out.append((symbol, market))
    return sorted(set(out))


def months(start: str, end: str) -> list[tuple[int, int]]:
    y, m = map(int, start.split('-'))
    ey, em = map(int, end.split('-'))
    out = []
    while (y, m) <= (ey, em):
        out.append((y - 1911, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


class Pacer:
    """Spaces requests and backs off on consecutive failures; raises Blocked when failures persist."""

    class Blocked(RuntimeError):
        pass

    def __init__(self, pause: float, sleep: Callable[[float], None] = time.sleep,
                 fail_limit: int = 3, backoff: float = 1800, max_backoffs: int = 3):
        self.pause, self.sleep = pause, sleep
        self.fail_limit, self.backoff, self.max_backoffs = fail_limit, backoff, max_backoffs
        self.failures = self.backoffs = 0

    def ok(self):
        self.failures = self.backoffs = 0
        self.sleep(self.pause)

    def failed(self):
        self.failures += 1
        if self.failures < self.fail_limit:
            self.sleep(self.pause * 3)
            return
        if self.backoffs >= self.max_backoffs:
            raise self.Blocked('%d consecutive failures after %d backoffs' % (self.failures, self.backoffs))
        self.backoffs += 1
        self.failures = 0
        print('backoff', self.backoffs, 'sleeping', self.backoff, flush=True)
        self.sleep(self.backoff)


def _done(db, task) -> set[str]:
    return {r[0] for r in db.execute("SELECT item FROM backfill_progress WHERE task=? AND status='ok'", (task,))}


def _mark(db, task, item, status, rows=None):
    db.execute('INSERT OR REPLACE INTO backfill_progress VALUES (?,?,?,?,?)',
               (task, item, status, rows, t.now_tpe().isoformat(timespec='seconds')))
    db.commit()


def run_items(db, task, items, fetch_item, pacer: Pacer, store) -> dict:
    """Fetch each pending item once; failures are retried on the next run."""
    done = _done(db, task)
    pending = [i for i in items if i[0] not in done]
    stats = {'total': len(items), 'skipped_done': len(items) - len(pending), 'ok': 0, 'failed': 0, 'rows': 0}
    for n, (key, args) in enumerate(pending, 1):
        try:
            rows = fetch_item(*args)
        except Exception as exc:
            stats['failed'] += 1
            _mark(db, task, key, 'error')
            print('fail', key, str(exc)[:120], flush=True)
            pacer.failed()
            continue
        store(rows)
        _mark(db, task, key, 'ok', len(rows))
        stats['ok'] += 1
        stats['rows'] += len(rows)
        if n % 50 == 0:
            print('progress', task, n, '/', len(pending), 'rows', stats['rows'], flush=True)
        pacer.ok()
    return stats


def backfill_conferences(db, start, end, *, fetch=t.http_fetch, pacer: Pacer) -> dict:
    seen_at = t.now_tpe().isoformat(timespec='seconds')
    items = [('%s_%d%02d' % (mk, y, m), (mk, y, m)) for y, m in months(start, end) for mk in ('sii', 'otc')]

    def fetch_item(market, roc_year, month):
        page = fetch(t.MOPS_CONFERENCE_URL, {'encodeURIComponent': '1', 'step': '1', 'firstin': '1', 'off': '1',
                                             'TYPEK': market, 'year': str(roc_year), 'month': '%02d' % month, 'co_id': ''})
        if 'myTable' not in page and EMPTY_MARK not in page:
            raise RuntimeError('unexpected page (%d bytes)' % len(page))
        return t.parse_conference_calendar(page, market)

    return run_items(db, 'conferences', items, fetch_item, pacer, lambda rows: t.store_conferences(db, rows, seen_at))


def backfill_announcements(db, years, *, fetch=t.http_fetch, pacer: Pacer, limit: int | None = None) -> dict:
    seen_at = t.now_tpe().isoformat(timespec='seconds')
    items = [('%s_%d' % (sym, y), (sym, y)) for y in years for sym, _ in companies(fetch)]
    items = items[:limit] if limit else items

    def fetch_item(symbol, roc_year):
        page = fetch(MOPS_HISTORY_URL, {'encodeURIComponent': '1', 'step': '1', 'firstin': '1', 'off': '1',
                                        'keyword4': '', 'code1': '', 'TYPEK2': '', 'checkbtn': '', 'queryName': 'co_id',
                                        'inpuType': 'co_id', 'TYPEK': 'all', 'co_id': symbol, 'year': str(roc_year),
                                        'month': '', 'b_date': '', 'e_date': ''})
        rows = parse_history(page)
        if not rows and EMPTY_MARK not in page:
            raise RuntimeError('unexpected page (%d bytes)' % len(page))
        return rows

    return run_items(db, 'announcements', items, fetch_item, pacer, lambda rows: t.store_announcements(db, rows, seen_at))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = ap.add_subparsers(dest='task', required=True)
    c = sub.add_parser('conferences')
    c.add_argument('--start', required=True, help='YYYY-MM')
    c.add_argument('--end', required=True, help='YYYY-MM')
    a = sub.add_parser('announcements')
    a.add_argument('--years', type=int, nargs='+', required=True, help='ROC years, e.g. 114 115')
    a.add_argument('--limit', type=int, help='only the first N company-years (smoke test)')
    for p in (c, a):
        p.add_argument('--pause', type=float, default=10.0)
    args = ap.parse_args(argv)

    db = t.connect()
    db.executescript(PROGRESS_SCHEMA)
    pacer = Pacer(args.pause)
    try:
        if args.task == 'conferences':
            stats = backfill_conferences(db, args.start, args.end, pacer=pacer)
        else:
            stats = backfill_announcements(db, args.years, pacer=pacer, limit=args.limit)
    except Pacer.Blocked as exc:
        print('STOPPED', exc, flush=True)
        return 2
    print('DONE', args.task, stats, flush=True)
    return 0 if stats['failed'] == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
