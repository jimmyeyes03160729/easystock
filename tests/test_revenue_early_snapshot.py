"""REVENUE_EARLY_V1 collector: filing window, first-seen dating, failures recorded, no price access."""
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'research' / 'revenue_early_v1'))
import rev_snapshot as S  # noqa: E402

TPE = timezone(timedelta(hours=8))


def page(codes, compiled='115/11/03'):
    rows = ''.join('<tr align=right><td align=center> %s </td><td align=left>name</td><td>1</td></tr>' % c for c in codes)
    head = '出表日期：%s' % compiled if compiled else ''
    return ('<html>%s<table>%s</table></html>' % (head, rows)).encode('big5')


def test_revenue_month_only_on_days_1_to_15():
    assert S.revenue_month(date(2026, 11, 1)) == '2026-10'
    assert S.revenue_month(date(2026, 11, 15)) == '2026-10'
    assert S.revenue_month(date(2027, 1, 10)) == '2026-12'
    assert S.revenue_month(date(2026, 11, 16)) is None


def test_parse_compile_date_and_codes():
    compiled, codes = S.parse(page(['2330', '1101', '2330']).decode('big5'))
    assert compiled == '2026-11-03' and codes == ['1101', '2330']


def test_first_seen_keeps_the_earliest_snapshot(tmp_path):
    days = {'d': 3}

    def fetcher(url):
        if '/otc/' in url or url.endswith('_1.html'):
            return page([], '115/11/0%d' % days['d'])
        return page(['2330'] + (['1101'] if days['d'] >= 4 else []), '115/11/0%d' % days['d'])

    for d in (3, 4, 5):
        days['d'] = d
        assert S.main(datetime(2026, 11, d, 21, 10, tzinfo=TPE), fetcher, tmp_path, pause=lambda s: None) == 0
    db = sqlite3.connect(tmp_path / 'announcements.sqlite')
    got = dict(db.execute('SELECT symbol, compiled FROM first_seen WHERE month = ?', ('2026-10',)).fetchall())
    assert got == {'2330': '2026-11-03', '1101': '2026-11-04'}
    assert db.execute("SELECT count(*) FROM snapshots WHERE status = 'ok'").fetchone()[0] == 12
    assert len(list((tmp_path / 'raw' / '2026-10').glob('*.html.gz'))) == 12


def test_failures_and_missing_compile_date_are_recorded(tmp_path):
    def fetcher(url):
        if 'sii' in url and url.endswith('_0.html'):
            return None
        return page(['2330'], compiled=None)

    assert S.main(datetime(2026, 11, 2, 21, 10, tzinfo=TPE), fetcher, tmp_path, pause=lambda s: None) == 1
    db = sqlite3.connect(tmp_path / 'announcements.sqlite')
    status = sorted(r[0] for r in db.execute('SELECT status FROM snapshots'))
    assert status == ['fetch_failed', 'no_compile_date', 'no_compile_date', 'no_compile_date']
    assert db.execute('SELECT count(*) FROM first_seen').fetchone()[0] == 0


def test_outside_window_does_nothing(tmp_path):
    def fetcher(url):
        raise AssertionError('must not fetch')
    assert S.main(datetime(2026, 11, 20, 21, 10, tzinfo=TPE), fetcher, tmp_path) == 0
    assert not (tmp_path / 'announcements.sqlite').exists()


def test_collector_reads_no_price_source():
    src = (ROOT / 'research' / 'revenue_early_v1' / 'rev_snapshot.py').read_text(encoding='utf-8')
    for forbidden in ('market-daily', 'bars', 'paper_execution', 'twse.com.tw/exchangeReport'):
        assert forbidden not in src
