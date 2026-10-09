import json
import sqlite3
from datetime import date

from market_events import tracker as t

# Trimmed from real 2026-10-08 OpenAPI / MOPS responses.
TWSE_ROWS = [
    {'出表日期': '1151009', '發言日期': '1151008', '發言時間': '163150', '公司代號': '6176', '公司名稱': '瑞儀',
     '主旨 ': '公告本公司召開法人說明會', '符合條款': '第12款', '事實發生日': '1151029',
     '說明': '符合條款第四條第XX款：12\r\n事實發生日：115/10/29\r\n1.召開法人說明會之日期：115/10/29\r\n'
             '2.召開法人說明會之時間：14 時 00 分 \r\n3.召開法人說明會之地點：線上直播 https://www.zucast.com/webcast/FHFR0R3a\r\n'
             '4.法人說明會擇要訊息：115年第三季營運成果及公司未來展望\r\n5.其他應敘明事項：無。'},
    {'出表日期': '1151009', '發言日期': '1151008', '發言時間': '152756', '公司代號': '2845', '公司名稱': '遠東銀',
     '主旨 ': '公佈本公司115年9月份自結合併淨利及每股盈餘', '符合條款': '第51款', '事實發生日': '1151008', '說明': '1.事實發生日:115/10/08'},
    {'出表日期': '1151009', '發言日期': '1151008', '發言時間': '64327', '公司代號': '4912', '公司名稱': '聯德控股-KY',
     '主旨 ': '公告本公司115年9月份自結合併營收情形', '符合條款': '第51款', '事實發生日': '1151008', '說明': ''},
]
TPEX_ROWS = [
    {'Date': '1151008', '發言日期': '1151007', '發言時間': '102241', 'SecuritiesCompanyCode': '2221', 'CompanyName': '大甲',
     '主旨': '本公司受邀參加中信證券、合庫證券及富邦證券舉辦之線上法人說明會', '符合條款': '第12款', '事實發生日': '1151008',
     '說明': '符合條款第四條第XX款：12\r\n1.召開法人說明會之日期：115/10/08 ~ 115/10/13\r\n2.召開法人說明會之時間：14 時 00 分 \r\n'
             '3.召開法人說明會之地點：線上\r\n4.法人說明會擇要訊息：說明本公司營運概況。\r\n5.其他應敘明事項：無'},
]
CALENDAR_HTML = """<table id='myTable'>
<tr class='even' data-type='body' >
<td>2308</td><td>台達電</td>
<td align='center'>115/10/05 至 115/10/13</td>
<td align='center'>21:00</td>
<td>美國</td>
<td>本公司受Jefferies證券邀請</td>
<td><a href='#' onclick='document.fm_fileDownload.fileName.value="230820260730M001.pdf";document.fm_fileDownload.submit();'><u>230820260730M001.pdf</u></a></td>
<td><a href='#' onclick='document.fm_fileDownload.fileName.value="230820260730E001.pdf";document.fm_fileDownload.submit();'><u>230820260730E001.pdf</u></a></td>
<td><a href='https://www.deltaww.com/zh-TW/investors/analyst-meeting' target='_blink'>x</a></td>
<td>&nbsp;</td><td>無</td><td><input type='button' value='查詢'></td>
</tr>
<tr class='odd' data-type='body' >
<td>6176</td><td>瑞儀</td><td align='center'>115/10/29</td><td align='center'>14:00</td>
<td>線上直播</td><td>115年第三季營運成果</td>
<td>內容檔案於當日會後公告於公開資訊觀測站</td><td>內容檔案於當日會後公告於公開資訊觀測站</td><td>無</td>
<td>影音資訊網址：<a target='_blank' href='https://www.zucast.com/webcast/FHFR0R3a'>x</a><br></td>
<td>無</td><td></td>
</tr></table>"""
REALTIME_HTML = """<table class='hasBorder'><tr class='tblHead'><th>公司代號</th></tr>
<tr class='even'>
<td>2301</td>
<td style='text-align:left !important;' nowrap>光寶科</td>
<td style='text-align:left !important;'>115/10/09</td>
<td style='text-align:left !important;'>09:23:52</td>
<td style='text-align:left !important;'>公告本公司董事會訂於115年10月30日召開
審議第三季合併財務報告</td>
<td><input type='button' value='詳細資料'></td></tr>
<tr class='odd'>
<td>2845</td><td>遠東銀</td><td>115/10/08</td><td>15:27:56</td>
<td>公佈本公司115年9月份自結合併淨利及每股盈餘</td><td></td></tr></table>"""


def make_db():
    db = sqlite3.connect(':memory:')
    db.row_factory = sqlite3.Row
    db.executescript(t.SCHEMA)
    return db


def test_date_and_time_helpers():
    assert t.roc_to_iso('1151008') == '2026-10-08'
    assert t.roc_to_iso('115/10/8') == '2026-10-08'
    assert t.roc_to_iso('115年10月30日') == '2026-10-30'
    assert t.roc_to_iso('') is None
    assert t.hms('64327') == '06:43:27'
    assert t.hms('09:23:52') == '09:23:52'


def test_classify():
    assert t.classify('公告本公司召開法人說明會') == 'investor_conference'
    assert t.classify('本公司將參加國票證券舉辦之投資人會議') == 'investor_conference'
    assert t.classify('其他事項', clause='第12款') == 'investor_conference'
    assert t.classify('公告本公司董事會通過115年第二季合併財務報告') == 'financial_report_approved'
    assert t.classify('公告本公司董事會訂於115年10月30日召開審議第三季合併財務報告') == 'board_meeting_scheduled'
    assert t.classify('公告本公司115年9月自結合併損益') == 'self_reported_earnings'
    assert t.classify('公告本公司自行結算一一五年九月份合併損益') == 'self_reported_earnings'
    assert t.classify('公告本公司115年9月份自結合併營收情形') == 'self_reported_revenue'
    assert t.classify('公告本公司股票面額變更') == 'other'
    assert t.board_meeting_date('公告本公司董事會訂於115年10月30日召開') == '2026-10-30'


def test_parse_conference_body_range():
    parsed = t.parse_conference_body(TPEX_ROWS[0]['說明'])
    assert parsed['start_date'] == '2026-10-08' and parsed['end_date'] == '2026-10-13'
    assert parsed['time'] == '14:00' and parsed['location'] == '線上'


def test_parse_calendar():
    rows = t.parse_conference_calendar(CALENDAR_HTML, 'sii')
    assert [r['symbol'] for r in rows] == ['2308', '6176']
    delta = rows[0]
    assert (delta['start_date'], delta['end_date'], delta['time']) == ('2026-10-05', '2026-10-13', '21:00')
    assert delta['slides_zh'] == '230820260730M001.pdf' and delta['slides_en'] == '230820260730E001.pdf'
    assert delta['website'].startswith('https://www.deltaww.com')
    assert rows[1]['slides_zh'] is None and rows[1]['video_urls'] == ['https://www.zucast.com/webcast/FHFR0R3a']


def test_realtime_then_openapi_merge_into_one_announcement():
    db = make_db()
    assert t.store_announcements(db, t.parse_realtime(REALTIME_HTML), 'a') == 2
    assert t.store_announcements(db, t.parse_openapi_announcements(TWSE_ROWS, 'sii'), 'b') == 2  # 2845 already known
    row = db.execute("SELECT * FROM announcements WHERE symbol='2845'").fetchone()
    assert row['sources'] == 'mops_realtime,openapi_sii' and row['market'] == 'sii' and row['body']
    assert row['category'] == 'self_reported_earnings'
    board = db.execute("SELECT * FROM announcements WHERE symbol='2301'").fetchone()
    assert board['category'] == 'board_meeting_scheduled' and board['meeting_date'] == '2026-10-30'


def test_conference_from_announcement_and_calendar_merge():
    db = make_db()
    t.store_announcements(db, t.parse_openapi_announcements(TWSE_ROWS, 'sii'), 'a')
    t.store_conferences(db, t.parse_conference_calendar(CALENDAR_HTML, 'sii'), 'b')
    rows = db.execute("SELECT * FROM conferences WHERE symbol='6176'").fetchall()
    assert len(rows) == 1
    assert rows[0]['sources'] == 'announcement,mops_calendar'
    assert rows[0]['location'] == '線上直播'  # calendar wins over parsed announcement text
    assert json.loads(rows[0]['video_urls']) == ['https://www.zucast.com/webcast/FHFR0R3a']


def test_build_day_events_tags():
    db = make_db()
    t.store_announcements(db, t.parse_openapi_announcements(TWSE_ROWS, 'sii'), 'a')
    t.store_announcements(db, t.parse_openapi_announcements(TPEX_ROWS, 'otc'), 'a')
    t.store_announcements(db, t.parse_realtime(REALTIME_HTML), 'a')
    t.store_conferences(db, t.parse_conference_calendar(CALENDAR_HTML, 'sii'), 'a')

    day = t.build_day_events(db, date(2026, 10, 9))
    s = day['symbols']
    assert s['2308']['tags'] == ['conference_today']
    assert s['2221']['tags'] == ['conference_today']
    assert s['2845']['tags'] == ['earnings_released']
    assert s['4912']['tags'] == ['revenue_released']
    assert s['2301']['tags'] == ['board_meeting_announced']
    assert '6176' not in s  # 20 days out, beyond the lookahead

    later = t.build_day_events(db, date(2026, 10, 27))['symbols']
    assert later['6176']['tags'] == ['conference_upcoming'] and later['6176']['events'][0]['days_until'] == 2
    assert t.build_day_events(db, date(2026, 10, 30))['symbols']['2301']['tags'] == ['board_meeting_today']
    assert t.build_day_events(db, date(2026, 10, 14))['symbols']['2308']['tags'] == ['conference_recent']


def test_report_deadline():
    assert t.report_deadline(date(2026, 10, 9)) == {'quarter': 'Q3', 'fiscal_year': 2026, 'deadline': '2026-11-14',
                                                    'days_left': 36, 'in_window': False}
    assert t.report_deadline(date(2026, 11, 14))['in_window'] is True
    q4 = t.report_deadline(date(2026, 12, 1))
    assert (q4['quarter'], q4['fiscal_year'], q4['deadline']) == ('Q4', 2026, '2027-03-31')


def test_sync_records_per_source_errors_and_continues():
    db = make_db()

    def fetch(url, data=None, as_json=False):
        if 'openapi.twse' in url:
            return TWSE_ROWS
        if 'tpex' in url:
            raise RuntimeError('tpex down')
        if 't05sr01_1' in url:
            return REALTIME_HTML
        return CALENDAR_HTML if data['TYPEK'] == 'sii' and data['month'] == '10' else '<table></table>'

    summary = t.sync(db, today=date(2026, 10, 9), fetch=fetch, pause=lambda s: None)
    assert summary['openapi_twse']['rows'] == 3 and 'error' in summary['openapi_tpex']
    assert summary['mops_calendar_sii_11510']['rows'] == 2 and summary['mops_calendar_otc_11512']['rows'] == 0
    assert db.execute("SELECT COUNT(*) FROM fetch_log WHERE status='error'").fetchone()[0] == 1
    assert t.sync(db, realtime_only=True, fetch=fetch, pause=lambda s: None).keys() == {'mops_realtime'}


def test_main_writes_latest(tmp_path, monkeypatch):
    monkeypatch.setenv('EASYSTOCK_MARKET_EVENTS_DIR', str(tmp_path))
    assert t.main(['--no-fetch', '--date', '2026-10-09']) == 0
    payload = json.loads((tmp_path / 'events-latest.json').read_text(encoding='utf-8'))
    assert payload['date'] == '2026-10-09' and payload['symbols'] == {}
