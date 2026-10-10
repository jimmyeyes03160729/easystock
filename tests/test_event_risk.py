import math
import sqlite3

from research.event_risk_v1 import event_risk as er

DAYS = ['2025-03-07', '2025-03-10', '2025-03-11', '2025-03-12']   # Fri, Mon, Tue, Wed


def test_post_report_window_spans_weekend_and_excludes_intraday_filings():
    ann = [('2330', '2025-03-07', '14:30:00'),   # after Friday close -> Monday
           ('2317', '2025-03-08', '10:00:00'),   # Saturday -> Monday
           ('2454', '2025-03-10', '09:00:00'),   # exactly D 09:00 -> Monday (inclusive)
           ('2303', '2025-03-10', '09:00:01'),   # intraday Monday -> no tag at all
           ('2882', '2025-03-10', '14:00:00'),   # after Monday close -> Tuesday
           ('1301', '2025-03-07', '13:30:00')]   # exactly P 13:30 -> excluded (open interval)
    tags = er.tag_events(DAYS, ann, [], [])
    assert tags[('2330', '2025-03-10')] == {'POST_REPORT'}
    assert tags[('2317', '2025-03-10')] == {'POST_REPORT'}
    assert tags[('2454', '2025-03-10')] == {'POST_REPORT'}
    assert not any(k[0] == '2303' for k in tags)
    assert tags[('2882', '2025-03-11')] == {'POST_REPORT'}
    assert not any(k[0] == '1301' for k in tags)


def test_conference_and_board_tags():
    conf = [('2308', '2025-03-10', '2025-03-11'), ('2412', '2025-03-08', '2025-03-08')]  # Saturday conference
    board = [('2330', '2025-03-01', '2025-03-11'), ('2317', '2025-03-11', '2025-03-11')]  # second filed same day -> no tag
    tags = er.tag_events(DAYS, [], conf, board)
    assert tags[('2308', '2025-03-10')] == {'CONF_START'}
    assert tags[('2308', '2025-03-12')] == {'POST_CONF'}
    assert tags[('2412', '2025-03-10')] == {'POST_CONF'}
    assert tags[('2330', '2025-03-11')] == {'BOARD_DAY'}
    assert ('2317', '2025-03-11') not in tags


def test_clustered_se_matches_iid_when_one_obs_per_day():
    vals = [('d%d' % i, x) for i, x in enumerate([1.0, 2.0, 3.0, 4.0])]
    mean, se, n = er.clustered_mean(vals)
    assert mean == 2.5 and n == 4
    assert math.isclose(se, math.sqrt(sum((x - 2.5) ** 2 for _, x in vals)) / 4)


def test_classify_rules():
    halves_neg = [{'excess_oc_bps': -10}, {'excess_oc_bps': -30}]
    base = {'excess_oc_bps': -25, 't': -2.5, 'sd_ratio': 1.0, 'abs_gap_ratio': 1.0}
    assert er.classify(299, base, halves_neg) == 'INSUFFICIENT'
    assert er.classify(500, base, halves_neg) == 'SKIP_SUPPORTED'
    assert er.classify(500, base, [{'excess_oc_bps': -10}, {'excess_oc_bps': 5}]) == 'NO_EFFECT'
    assert er.classify(500, {**base, 't': -1.5, 'sd_ratio': 1.31}, halves_neg) == 'SIZE_DOWN_CANDIDATE'
    assert er.classify(500, {**base, 't': -1.5, 'abs_gap_ratio': 1.5}, halves_neg) == 'SIZE_DOWN_CANDIDATE'


def make_bars(path):
    db = sqlite3.connect(path)
    db.executescript('''CREATE TABLE bars (symbol TEXT, day TEXT, exchange TEXT, open REAL, high REAL, low REAL, close REAL,
                        volume REAL, amount REAL, reference REAL);
                        CREATE TABLE amount_ranks (symbol TEXT, day TEXT, rank REAL);''')
    days = ['2025-01-03', '2025-01-06', '2025-01-07', '2026-10-02', '2026-10-05']
    for d in days:
        for sym, rank in (('2330', 0.01), ('0050', 0.01), ('9999', 0.9)):
            db.execute('INSERT INTO bars VALUES (?,?,?,?,?,?,?,?,?,?)', (sym, d, 'TWSE', 100, 103, 99, 102, 1, 1, 100))
            db.execute('INSERT INTO amount_ranks VALUES (?,?,?)', (sym, d, rank))
    db.commit()
    db.close()


def make_events(path):
    db = sqlite3.connect(path)
    db.executescript('''CREATE TABLE announcements (symbol TEXT, spoke_date TEXT, spoke_time TEXT, category TEXT, meeting_date TEXT);
                        CREATE TABLE conferences (symbol TEXT, start_date TEXT, end_date TEXT);''')
    db.execute("INSERT INTO announcements VALUES ('2330','2025-01-06','15:00:00','financial_report_approved',NULL)")
    db.execute("INSERT INTO announcements VALUES ('2330','2026-10-02','15:00:00','financial_report_approved',NULL)")  # tags 10-05: unreadable
    db.commit()
    db.close()


def test_load_respects_ceiling_universe_and_common_stock(tmp_path):
    bars, events = tmp_path / 'b.sqlite', tmp_path / 'e.sqlite'
    make_bars(str(bars))
    make_events(str(events))
    days, rows, ann, conf, board = er.load(str(bars).replace('\\', '/'), str(events).replace('\\', '/'))
    assert days == ['2025-01-03', '2025-01-06', '2025-01-07', '2026-10-02']
    assert {(r['symbol'], r['day']) for r in rows} == {('2330', '2025-01-06'), ('2330', '2025-01-07'), ('2330', '2026-10-02')}
    assert ann == [('2330', '2025-01-06', '15:00:00')]
    res = er.run(days, rows, ann, conf, board)
    assert res['events']['POST_REPORT']['summary']['n'] == 1
    assert res['events']['POST_REPORT']['decision'] == 'INSUFFICIENT'
    r = rows[0]
    assert math.isclose(r['gap'], 0.0) and math.isclose(r['oc'], 0.02) and math.isclose(r['range'], 0.04)
    assert er.final_lines(res)[0].startswith('EVENT_RISK_V1 universe_stock_days=3')
