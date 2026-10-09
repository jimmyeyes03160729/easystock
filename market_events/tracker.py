#!/usr/bin/env python3
"""Collect investor conferences (法說會) and earnings releases (財報/自結損益) for TWSE and TPEx stocks.

Sources (all public, no token):
  * TWSE OpenAPI t187ap04_L / TPEx OpenAPI mopsfin_t187ap04_O -- material announcements with full body.
    These are a once-a-day snapshot of the PREVIOUS day (TPEx lags one more day), so every run is
    accumulated into SQLite; a missed day is only recoverable from the realtime list while it is current.
  * MOPS t05sr01_1 -- today's material announcements as they are filed (subject only, no body).
  * MOPS t100sb02_1 -- investor conference calendar per market/month, including future months,
    with slide file names and webcast/replay links.

Announcements are classified by subject/clause; conferences found in either source are merged into one table.
`build_day_events` turns the store into per-symbol tags for a trading day, written to events-YYYY-MM-DD.json.
The tracker only records and tags; nothing here gates orders.

Usage:
  python -m market_events.tracker                 # sync everything, write today's tags
  python -m market_events.tracker --realtime-only # just poll today's announcements (cheap, intraday)
  python -m market_events.tracker --show 2330     # print stored events for one symbol
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

TPE = timezone(timedelta(hours=8))
DEFAULT_DIR = '/home/ubuntu/easystock-market-events'
UA = 'Mozilla/5.0 (EasyStock market events tracker)'

TWSE_ANNOUNCE_URL = 'https://openapi.twse.com.tw/v1/opendata/t187ap04_L'
TPEX_ANNOUNCE_URL = 'https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap04_O'
MOPS_REALTIME_URL = 'https://mopsov.twse.com.tw/mops/web/t05sr01_1'
MOPS_CONFERENCE_URL = 'https://mopsov.twse.com.tw/mops/web/ajax_t100sb02_1'

CONFERENCE_CLAUSE = '第12款'          # 第四條第十二款: 召開法人說明會
CONFERENCE_LOOKAHEAD_DAYS = 5
# Statutory filing deadlines (month, day) per quarter; Q4/annual is due the following year.
REPORT_DEADLINES = {1: (5, 15), 2: (8, 14), 3: (11, 14), 4: (3, 31)}
DEADLINE_WINDOW_DAYS = 5

CATEGORIES = ('investor_conference', 'financial_report_approved', 'board_meeting_scheduled',
              'self_reported_earnings', 'self_reported_revenue', 'other')


# ---------------------------------------------------------------- helpers

def data_dir() -> Path:
    return Path(os.environ.get('EASYSTOCK_MARKET_EVENTS_DIR', DEFAULT_DIR))


def now_tpe() -> datetime:
    return datetime.now(TPE)


def roc_to_iso(value: Any) -> str | None:
    """'1151008', '115/10/08', '115年10月8日' -> '2026-10-08'."""
    s = str(value or '').strip()
    m = re.fullmatch(r'(\d{2,3})(\d{2})(\d{2})', s) or re.search(r'(\d{2,3})\s*[/年.-]\s*(\d{1,2})\s*[/月.-]\s*(\d{1,2})', s)
    if not m:
        return None
    try:
        return date(int(m.group(1)) + 1911, int(m.group(2)), int(m.group(3))).isoformat()
    except ValueError:
        return None


def hms(value: Any) -> str | None:
    """'64327' / '09:23:52' -> '06:43:27' / '09:23:52'."""
    digits = re.sub(r'\D', '', str(value or ''))
    if not digits or len(digits) > 6:
        return None
    digits = digits.zfill(6)
    return '%s:%s:%s' % (digits[:2], digits[2:4], digits[4:])


def norm_subject(subject: str) -> str:
    return re.sub(r'\s+', '', subject or '')


def strip_tags(fragment: str) -> str:
    text = re.sub(r'<br\s*/?>', '\n', fragment, flags=re.I)
    text = html.unescape(re.sub(r'<[^>]+>', '', text))
    return '\n'.join(line.strip() for line in text.splitlines() if line.strip())


def field(row: dict, *names: str) -> str:
    """Look up a column tolerating stray whitespace in OpenAPI keys (TWSE ships '主旨 ')."""
    cleaned = {str(k).strip(): v for k, v in row.items()}
    for name in names:
        if cleaned.get(name) not in (None, ''):
            return str(cleaned[name]).strip()
    return ''


def previous_weekday(day: date) -> date:
    day -= timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


# ---------------------------------------------------------------- classification

def classify(subject: str, clause: str = '', body: str = '') -> str:
    s = norm_subject(subject)
    if CONFERENCE_CLAUSE in (clause or '') or re.search(r'法人說明會|法說會|投資論壇|業績發表會|投資人說明會|投資人會議', s):
        return 'investor_conference'
    report = re.search(r'財務報告|財務報表|財報|季報|年報', s)
    if '董事會' in s and report and re.search(r'通過|承認|決議', s) and not re.search(r'訂於|召開日期|預計', s):
        return 'financial_report_approved'
    if '董事會' in s and re.search(r'訂於|召開日期|預計召開|召開董事會|董事會召開', s):
        return 'board_meeting_scheduled'
    # Quarterly EPS releases without 自結 wording, e.g. 台積公司2024年第四季每股盈餘新台幣14.45元
    if re.search(r'第[一二三四1-4]季|年度|上半年', s) and re.search(r'每股盈餘|EPS', s, re.I) and '董事會' not in s:
        return 'self_reported_earnings'
    if re.search(r'自結|自行結算', s):
        if re.search(r'損益|盈餘|淨利|EPS|每股|獲利|稅後|稅前', s, re.I):
            return 'self_reported_earnings'
        if '營收' in s:
            return 'self_reported_revenue'
    return 'other'


def board_meeting_date(subject: str, body: str = '') -> str | None:
    """Best-effort date the board convenes, from '董事會訂於115年11月10日召開' style text."""
    for text in (norm_subject(subject), norm_subject(body)):
        m = re.search(r'(?:董事會.{0,12}?(?:訂於|日期(?:為|[:：])?|於))(\d{2,3}年\d{1,2}月\d{1,2}日|\d{2,3}/\d{1,2}/\d{1,2})', text)
        if m:
            return roc_to_iso(m.group(1))
    return None


def parse_conference_body(body: str) -> dict | None:
    """Pull date/time/place/summary out of a 第12款 announcement body."""
    text = (body or '').replace('\r', '')
    m = re.search(r'法人說明會之日期[:：]\s*(\d{2,3}/\d{1,2}/\d{1,2})(?:\s*[~～至-]\s*(\d{2,3}/\d{1,2}/\d{1,2}))?', text)
    if not m:
        return None
    start = roc_to_iso(m.group(1))
    end = roc_to_iso(m.group(2)) if m.group(2) else start
    t = re.search(r'法人說明會之時間[:：]\s*(\d{1,2})\s*時\s*(\d{1,2})\s*分', text)
    place = re.search(r'法人說明會之地點[:：]\s*(.+)', text)
    summary = re.search(r'法人說明會擇要訊息[:：]\s*(.*?)(?:\n\s*5\.|\Z)', text, re.S)
    links = re.findall(r'https?://[^\s，,）)]+', text)
    return {
        'start_date': start, 'end_date': end,
        'time': '%02d:%02d' % (int(t.group(1)), int(t.group(2))) if t else '',
        'location': place.group(1).strip() if place else None,
        'summary': ' '.join(summary.group(1).split()) if summary else None,
        'video_urls': links,
    }


# ---------------------------------------------------------------- parsers

def parse_openapi_announcements(rows: Iterable[dict], market: str) -> list[dict]:
    out = []
    for row in rows or []:
        symbol = field(row, '公司代號', 'SecuritiesCompanyCode')
        subject = field(row, '主旨')
        spoke = roc_to_iso(field(row, '發言日期'))
        if not symbol or not subject or not spoke:
            continue
        clause, body = field(row, '符合條款'), field(row, '說明')
        out.append({
            'symbol': symbol, 'name': field(row, '公司名稱', 'CompanyName'), 'market': market,
            'spoke_date': spoke, 'spoke_time': hms(field(row, '發言時間')), 'subject': subject.replace('\r', ''),
            'clause': clause, 'fact_date': roc_to_iso(field(row, '事實發生日')), 'body': body.replace('\r', ''),
            'source': 'openapi_' + market,
        })
    return out


ROW_SPLIT = re.compile(r"<tr class='(?:even|odd)'[^>]*>", re.I)
TD = re.compile(r'<td[^>]*>(.*?)</td>', re.S | re.I)


def parse_realtime(page: str) -> list[dict]:
    out = []
    for chunk in ROW_SPLIT.split(page)[1:]:
        cells = TD.findall(chunk.split('</tr>')[0])
        if len(cells) < 5:
            continue
        symbol, name, spoke, spoke_time, subject = (strip_tags(c) for c in cells[:5])
        spoke_iso = roc_to_iso(spoke)
        if not re.fullmatch(r'[0-9A-Z]{4,6}', symbol) or not spoke_iso:
            continue
        out.append({'symbol': symbol, 'name': name, 'market': None, 'spoke_date': spoke_iso,
                    'spoke_time': hms(spoke_time), 'subject': subject, 'clause': None, 'fact_date': None,
                    'body': None, 'source': 'mops_realtime'})
    return out


def parse_conference_calendar(page: str, market: str) -> list[dict]:
    out = []
    for chunk in re.split(r"<tr class='(?:even|odd)' data-type='body'[^>]*>", page)[1:]:
        cells = TD.findall(chunk.split('</tr>')[0])
        if len(cells) < 11:
            continue
        dates = re.findall(r'\d{2,3}/\d{1,2}/\d{1,2}', strip_tags(cells[2]))
        if not dates:
            continue
        files = [re.search(r'fileName\.value="([^"]+)"', c) for c in (cells[6], cells[7])]
        website = re.findall(r"href='(https?://[^']+)'", cells[8])
        out.append({
            'symbol': strip_tags(cells[0]), 'name': strip_tags(cells[1]), 'market': market,
            'start_date': roc_to_iso(dates[0]), 'end_date': roc_to_iso(dates[-1]),
            'time': strip_tags(cells[3]), 'location': strip_tags(cells[4]) or None,
            'summary': strip_tags(cells[5]) or None,
            'slides_zh': files[0].group(1) if files[0] else None,
            'slides_en': files[1].group(1) if files[1] else None,
            'website': website[0] if website else None,
            'video_urls': re.findall(r"href='(https?://[^']+)'", cells[9]),
            'note': strip_tags(cells[10]) or None,
            'source': 'mops_calendar',
        })
    return out


# ---------------------------------------------------------------- storage

SCHEMA = """
CREATE TABLE IF NOT EXISTS announcements (
    symbol TEXT NOT NULL, spoke_date TEXT NOT NULL, subject_key TEXT NOT NULL,
    name TEXT, market TEXT, spoke_time TEXT, subject TEXT NOT NULL, clause TEXT, fact_date TEXT, body TEXT,
    category TEXT NOT NULL, meeting_date TEXT, sources TEXT NOT NULL, first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
    PRIMARY KEY (symbol, spoke_date, subject_key));
CREATE INDEX IF NOT EXISTS announcements_category ON announcements(category, spoke_date);
CREATE TABLE IF NOT EXISTS conferences (
    symbol TEXT NOT NULL, start_date TEXT NOT NULL, end_date TEXT NOT NULL, time TEXT NOT NULL,
    name TEXT, market TEXT, location TEXT, summary TEXT, slides_zh TEXT, slides_en TEXT, website TEXT,
    video_urls TEXT, note TEXT, sources TEXT NOT NULL, first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
    PRIMARY KEY (symbol, start_date, end_date, time));
CREATE INDEX IF NOT EXISTS conferences_dates ON conferences(start_date, end_date);
CREATE TABLE IF NOT EXISTS fetch_log (
    fetched_at TEXT NOT NULL, source TEXT NOT NULL, status TEXT NOT NULL, rows INTEGER, detail TEXT);
"""


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = path or data_dir() / 'events.sqlite'
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    return db


def _merge_sources(old: str | None, new: str) -> str:
    items = set(filter(None, (old or '').split(',')))
    items.add(new)
    return ','.join(sorted(items))


def store_announcements(db: sqlite3.Connection, rows: list[dict], seen_at: str) -> int:
    """Upsert announcements; returns how many were new. Later sources fill fields earlier ones lacked."""
    new = 0
    for r in rows:
        key = hashlib.sha1(norm_subject(r['subject']).encode()).hexdigest()[:16]
        category = classify(r['subject'], r.get('clause') or '', r.get('body') or '')
        meeting = board_meeting_date(r['subject'], r.get('body') or '') if category == 'board_meeting_scheduled' else None
        old = db.execute('SELECT sources FROM announcements WHERE symbol=? AND spoke_date=? AND subject_key=?',
                         (r['symbol'], r['spoke_date'], key)).fetchone()
        if old is None:
            new += 1
            db.execute('INSERT INTO announcements VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       (r['symbol'], r['spoke_date'], key, r['name'], r['market'], r['spoke_time'], r['subject'],
                        r['clause'], r['fact_date'], r['body'], category, meeting, r['source'], seen_at, seen_at))
        else:
            db.execute('''UPDATE announcements SET name=COALESCE(?,name), market=COALESCE(?,market),
                spoke_time=COALESCE(spoke_time,?), clause=COALESCE(?,clause), fact_date=COALESCE(?,fact_date),
                body=COALESCE(?,body), category=?, meeting_date=COALESCE(?,meeting_date), sources=?, last_seen_at=?
                WHERE symbol=? AND spoke_date=? AND subject_key=?''',
                       (r['name'] or None, r['market'], r['spoke_time'], r['clause'] or None, r['fact_date'],
                        r['body'] or None, category, meeting, _merge_sources(old['sources'], r['source']), seen_at,
                        r['symbol'], r['spoke_date'], key))
        if category == 'investor_conference' and r.get('body'):
            parsed = parse_conference_body(r['body'])
            if parsed:
                store_conferences(db, [{**parsed, 'symbol': r['symbol'], 'name': r['name'], 'market': r['market'],
                                        'slides_zh': None, 'slides_en': None, 'website': None, 'note': None,
                                        'source': 'announcement'}], seen_at)
    return new


def store_conferences(db: sqlite3.Connection, rows: list[dict], seen_at: str) -> int:
    new = 0
    for r in rows:
        k = (r['symbol'], r['start_date'], r['end_date'], r.get('time') or '')
        old = db.execute('SELECT sources, video_urls FROM conferences WHERE symbol=? AND start_date=? AND end_date=? AND time=?', k).fetchone()
        urls = list(dict.fromkeys((json.loads(old['video_urls']) if old and old['video_urls'] else []) + (r.get('video_urls') or [])))
        if old is None:
            new += 1
            db.execute('INSERT INTO conferences VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       (*k, r.get('name'), r.get('market'), r.get('location'), r.get('summary'), r.get('slides_zh'),
                        r.get('slides_en'), r.get('website'), json.dumps(urls, ensure_ascii=False), r.get('note'),
                        r['source'], seen_at, seen_at))
        else:
            # The MOPS calendar is the curated record, so it overrides text parsed from announcements.
            prefer = r['source'] == 'mops_calendar'
            cols = ('name', 'market', 'location', 'summary', 'slides_zh', 'slides_en', 'website', 'note')
            sets = ', '.join('%s=%s' % (c, 'COALESCE(?,%s)' % c if prefer else 'COALESCE(%s,?)' % c) for c in cols)
            db.execute('UPDATE conferences SET %s, video_urls=?, sources=?, last_seen_at=? '
                       'WHERE symbol=? AND start_date=? AND end_date=? AND time=?' % sets,
                       (*(r.get(c) for c in cols), json.dumps(urls, ensure_ascii=False),
                        _merge_sources(old['sources'], r['source']), seen_at, *k))
    return new


def log_fetch(db, source, status, rows=None, detail=None):
    db.execute('INSERT INTO fetch_log VALUES (?,?,?,?,?)',
               (now_tpe().isoformat(timespec='seconds'), source, status, rows, detail))


# ---------------------------------------------------------------- network

def http_fetch(url: str, data: dict | None = None, *, as_json: bool = False, retries: int = 3) -> Any:
    # urllib uses the OS trust store; certifi (requests) lacks the TWCA issuer on some hosts.
    last = None
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=body, headers={'User-Agent': UA})
            raw = urllib.request.urlopen(req, timeout=60).read()
            text = raw.decode('utf-8-sig')
            return json.loads(text) if as_json else text
        except Exception as exc:  # network, HTTP, or decode
            last = exc
            time.sleep(5 * (attempt + 1))
    raise RuntimeError('%s: %s' % (url, last))


def conference_months(today: date, ahead: int = 2) -> list[tuple[int, int]]:
    """Current month plus `ahead` future months, as (ROC year, month)."""
    out, y, m = [], today.year, today.month
    for _ in range(ahead + 1):
        out.append((y - 1911, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def sync(db: sqlite3.Connection, *, today: date | None = None, realtime_only: bool = False,
         fetch: Callable[..., Any] = http_fetch, pause: Callable[[float], None] = time.sleep) -> dict:
    today = today or now_tpe().date()
    seen_at = now_tpe().isoformat(timespec='seconds')
    summary: dict[str, Any] = {}

    def step(source, fn):
        try:
            count, new = fn()
            log_fetch(db, source, 'ok', count)
            summary[source] = {'rows': count, 'new': new}
        except Exception as exc:
            log_fetch(db, source, 'error', None, str(exc)[:500])
            summary[source] = {'error': str(exc)[:200]}
        db.commit()

    def announcements(url, market):
        rows = parse_openapi_announcements(fetch(url, as_json=True), market)
        return len(rows), store_announcements(db, rows, seen_at)

    def realtime():
        rows = parse_realtime(fetch(MOPS_REALTIME_URL))
        return len(rows), store_announcements(db, rows, seen_at)

    def calendar(market, roc_year, month):
        page = fetch(MOPS_CONFERENCE_URL, {'encodeURIComponent': '1', 'step': '1', 'firstin': '1', 'off': '1',
                                           'TYPEK': market, 'year': str(roc_year), 'month': str(month), 'co_id': ''})
        rows = parse_conference_calendar(page, market)
        return len(rows), store_conferences(db, rows, seen_at)

    step('mops_realtime', realtime)
    if not realtime_only:
        step('openapi_twse', lambda: announcements(TWSE_ANNOUNCE_URL, 'sii'))
        step('openapi_tpex', lambda: announcements(TPEX_ANNOUNCE_URL, 'otc'))
        for roc_year, month in conference_months(today):
            for market in ('sii', 'otc'):
                pause(10)  # mopsov drops connections from IPs that burst requests
                step('mops_calendar_%s_%d%02d' % (market, roc_year, month),
                     lambda market=market, roc_year=roc_year, month=month: calendar(market, roc_year, month))
    return summary


# ---------------------------------------------------------------- daily tags

def report_deadline(day: date) -> dict:
    """Next statutory quarterly-report deadline on or after `day`."""
    candidates = []
    for year in (day.year, day.year + 1):
        for q, (m, d) in REPORT_DEADLINES.items():
            due = date(year, m, d)
            candidates.append((due, q, year - 1 if q == 4 else year))
    due, quarter, fiscal_year = min(c for c in candidates if c[0] >= day)
    left = (due - day).days
    return {'quarter': 'Q%d' % quarter, 'fiscal_year': fiscal_year, 'deadline': due.isoformat(),
            'days_left': left, 'in_window': left <= DEADLINE_WINDOW_DAYS}


def build_day_events(db: sqlite3.Connection, day: date, lookahead: int = CONFERENCE_LOOKAHEAD_DAYS) -> dict:
    """Per-symbol event tags for trading day `day`.

    Tags:
      conference_today      a conference spans `day`
      conference_upcoming   starts within `lookahead` calendar days (days_until given)
      conference_recent     ended on the previous weekday (post-conference gap risk at today's open)
      earnings_released     self-reported earnings or board-approved financial report filed since the previous weekday
      revenue_released      self-reported monthly revenue filed since the previous weekday
      board_meeting_today   a scheduled board meeting (usually report approval) on `day`
      board_meeting_announced  a board-meeting notice filed since the previous weekday
    """
    d, prev = day.isoformat(), previous_weekday(day).isoformat()
    horizon = (day + timedelta(days=lookahead)).isoformat()
    symbols: dict[str, dict] = {}

    def add(symbol, name, tag, detail):
        entry = symbols.setdefault(symbol, {'name': name, 'tags': [], 'events': []})
        entry['name'] = entry['name'] or name
        if tag not in entry['tags']:
            entry['tags'].append(tag)
        entry['events'].append({'tag': tag, **detail})

    for r in db.execute('SELECT * FROM conferences WHERE end_date>=? AND start_date<=? ORDER BY start_date, time', (prev, horizon)):
        detail = {'start_date': r['start_date'], 'end_date': r['end_date'], 'time': r['time'], 'location': r['location'],
                  'summary': r['summary'], 'slides_zh': r['slides_zh'], 'video_urls': json.loads(r['video_urls'] or '[]')}
        if r['start_date'] <= d <= r['end_date']:
            add(r['symbol'], r['name'], 'conference_today', detail)
        elif r['start_date'] > d:
            add(r['symbol'], r['name'], 'conference_upcoming',
                {**detail, 'days_until': (date.fromisoformat(r['start_date']) - day).days})
        elif r['end_date'] == prev:
            add(r['symbol'], r['name'], 'conference_recent', detail)

    tag_by_category = {'self_reported_earnings': 'earnings_released', 'financial_report_approved': 'earnings_released',
                       'self_reported_revenue': 'revenue_released', 'board_meeting_scheduled': 'board_meeting_announced'}
    for r in db.execute('SELECT * FROM announcements WHERE spoke_date BETWEEN ? AND ? AND category IN (%s) ORDER BY spoke_date, spoke_time'
                        % ','.join('?' * len(tag_by_category)), (prev, d, *tag_by_category)):
        add(r['symbol'], r['name'], tag_by_category[r['category']],
            {'category': r['category'], 'spoke_date': r['spoke_date'], 'spoke_time': r['spoke_time'], 'subject': r['subject']})
    for r in db.execute("SELECT * FROM announcements WHERE category='board_meeting_scheduled' AND meeting_date=?", (d,)):
        add(r['symbol'], r['name'], 'board_meeting_today',
            {'meeting_date': r['meeting_date'], 'spoke_date': r['spoke_date'], 'subject': r['subject']})

    return {'date': d, 'generated_at': now_tpe().isoformat(timespec='seconds'),
            'report_deadline': report_deadline(day), 'symbols': dict(sorted(symbols.items()))}


def write_day_events(db: sqlite3.Connection, day: date, out_dir: Path | None = None) -> Path:
    out_dir = out_dir or data_dir()
    payload = build_day_events(db, day)
    path = out_dir / ('events-%s.json' % day.isoformat())
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding='utf-8')
    tmp.replace(path)
    latest = out_dir / 'events-latest.json'
    latest.write_text(path.read_text(encoding='utf-8'), encoding='utf-8')
    return path


def show_symbol(db: sqlite3.Connection, symbol: str, limit: int = 20) -> dict:
    confs = [dict(r) for r in db.execute('SELECT * FROM conferences WHERE symbol=? ORDER BY start_date DESC LIMIT ?', (symbol, limit))]
    anns = [dict(r) for r in db.execute("SELECT symbol, spoke_date, spoke_time, category, subject, meeting_date, sources FROM announcements "
                                        "WHERE symbol=? AND category!='other' ORDER BY spoke_date DESC, spoke_time DESC LIMIT ?", (symbol, limit))]
    return {'symbol': symbol, 'conferences': confs, 'announcements': anns}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--realtime-only', action='store_true', help="only poll MOPS today's announcement list")
    ap.add_argument('--no-fetch', action='store_true', help='skip network; just rebuild the day tags')
    ap.add_argument('--date', help='trading day for tags (YYYY-MM-DD, default today in Taipei)')
    ap.add_argument('--show', metavar='SYMBOL', help='print stored events for one symbol and exit')
    args = ap.parse_args(argv)

    db = connect()
    if args.show:
        print(json.dumps(show_symbol(db, args.show), ensure_ascii=False, indent=1))
        return 0
    day = date.fromisoformat(args.date) if args.date else now_tpe().date()
    summary = {} if args.no_fetch else sync(db, today=day, realtime_only=args.realtime_only)
    path = write_day_events(db, day)
    tagged = json.loads(path.read_text(encoding='utf-8'))['symbols']
    print(json.dumps({'sync': summary, 'events_file': str(path), 'tagged_symbols': len(tagged)}, ensure_ascii=False))
    db.close()
    failed = [k for k, v in summary.items() if 'error' in v]
    return 1 if failed and len(failed) == len(summary) else 0


if __name__ == '__main__':
    sys.exit(main())
