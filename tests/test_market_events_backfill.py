import sqlite3

import pytest

from market_events import backfill as b
from market_events import tracker as t
from tests.test_market_events import CALENDAR_HTML

# Trimmed from a real t05st01 page (6176, ROC 114).
HISTORY_HTML = """<table><tr class='tblHead'><th>公司代號</th></tr>
<tr class='even'>
<td style='text-align:left !important;'>&nbsp;2330</td><td>&nbsp;台積電</td><td>&nbsp;114/01/24</td><td>&nbsp;15:59:48</td>
<td><pre><font size='3'>&nbsp;公告決議民國113年度第四季合併財務報告 之董事會預計召開日期為114年02月12日</font></pre></td>
<td align='center'><input type='button' value='詳細資料' onclick="document.t05st01_fm.co_id.value='2330';document.t05st01_fm.TYPEK.value='sii';openWindow(this.form ,'');">
</td>
</tr>
<tr class='odd'>
<td>&nbsp;2330</td><td>&nbsp;台積電</td><td>&nbsp;114/02/12</td><td>&nbsp;14:57:17</td>
<td><pre><font size='3'>&nbsp;本公司民國113年度合併財務報告業經董事會決議通過</font></pre></td>
<td align='center'><input type='button' value='詳細資料' onclick="document.t05st01_fm.TYPEK.value='sii';">
</td>
</tr></table>"""
EMPTY_HTML = '<html><body><h3>查無資料</h3></body></html>'
COMPANIES = {b.TWSE_COMPANIES_URL: [{'公司代號': '2330'}, {'公司代號': '6176'}],
             b.TPEX_COMPANIES_URL: [{'SecuritiesCompanyCode': '2221'}]}


def make_db():
    db = sqlite3.connect(':memory:')
    db.row_factory = sqlite3.Row
    db.executescript(t.SCHEMA)
    db.executescript(b.PROGRESS_SCHEMA)
    return db


def quiet_pacer(**kw):
    return b.Pacer(0, sleep=lambda s: None, **kw)


def test_parse_history():
    rows = b.parse_history(HISTORY_HTML)
    assert [(r['symbol'], r['spoke_date'], r['spoke_time'], r['market']) for r in rows] == [
        ('2330', '2025-01-24', '15:59:48', 'sii'), ('2330', '2025-02-12', '14:57:17', 'sii')]
    db = make_db()
    t.store_announcements(db, rows, 'x')
    cats = dict(db.execute('SELECT spoke_date, category FROM announcements').fetchall())
    assert cats == {'2025-01-24': 'board_meeting_scheduled', '2025-02-12': 'financial_report_approved'}
    assert db.execute("SELECT meeting_date FROM announcements WHERE spoke_date='2025-01-24'").fetchone()[0] == '2025-02-12'


def test_months():
    assert b.months('2025-11', '2026-02') == [(114, 11), (114, 12), (115, 1), (115, 2)]


def test_announcement_backfill_resumes_and_retries_failures():
    db = make_db()
    calls = []

    def fetch(url, data=None, as_json=False):
        if as_json:
            return COMPANIES[url]
        calls.append(data['co_id'])
        if data['co_id'] == '6176' and calls.count('6176') == 1:
            raise RuntimeError('Remote end closed connection')
        return HISTORY_HTML if data['co_id'] == '2330' else EMPTY_HTML

    first = b.backfill_announcements(db, [114], fetch=fetch, pacer=quiet_pacer())
    assert first == {'total': 3, 'skipped_done': 0, 'ok': 2, 'failed': 1, 'rows': 2}
    second = b.backfill_announcements(db, [114], fetch=fetch, pacer=quiet_pacer())
    assert second == {'total': 3, 'skipped_done': 2, 'ok': 1, 'failed': 0, 'rows': 0}
    assert calls == ['2221', '2330', '6176', '6176']


def test_unexpected_page_counts_as_failure():
    db = make_db()
    fetch = lambda url, data=None, as_json=False: COMPANIES[url] if as_json else '<html>error</html>'
    stats = b.backfill_announcements(db, [114], fetch=fetch, pacer=quiet_pacer(fail_limit=10), limit=1)
    assert stats['failed'] == 1


def test_pacer_stops_when_blocked():
    sleeps = []
    pacer = b.Pacer(10, sleep=sleeps.append, fail_limit=2, backoff=1800, max_backoffs=1)
    pacer.failed(); pacer.failed()          # second failure -> one backoff
    assert sleeps == [30, 1800]
    pacer.failed()
    with pytest.raises(b.Pacer.Blocked):
        pacer.failed()


def test_conference_backfill():
    db = make_db()
    fetch = lambda url, data: CALENDAR_HTML if data['TYPEK'] == 'sii' else EMPTY_HTML
    stats = b.backfill_conferences(db, '2026-10', '2026-11', fetch=fetch, pacer=quiet_pacer())
    assert stats == {'total': 4, 'skipped_done': 0, 'ok': 4, 'failed': 0, 'rows': 4}
    assert db.execute('SELECT COUNT(*) FROM conferences').fetchone()[0] == 2


def test_conference_month_is_zero_padded():
    # MOPS silently returns 查無資料 for month '9'; only '09' works.
    db = make_db()
    sent = []

    def fetch(url, data):
        sent.append(data['month'])
        return CALENDAR_HTML if len(data['month']) == 2 else EMPTY_HTML

    stats = b.backfill_conferences(db, '2026-09', '2026-10', fetch=fetch, pacer=quiet_pacer())
    assert sent == ['09', '09', '10', '10'] and stats['rows'] == 8
    tracker_sent = []
    t.sync(make_db(), today=__import__('datetime').date(2026, 1, 5),
           fetch=lambda url, data=None, as_json=False: [] if as_json else (tracker_sent.append(data['month']) or '') if data else '',
           pause=lambda s: None)
    assert tracker_sent == ['01', '01', '02', '02', '03', '03']
