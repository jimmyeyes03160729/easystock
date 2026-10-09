"""短期持股首頁資料：日期推算、待進場／持有中／已出場、開盤漲停留現金、下一批時間。"""
import math

import pytest

from short_term import feed as F

CLOSED = {'2026-10-09', '2026-10-10', '2026-10-25', '2026-10-26'}
is_closed = CLOSED.__contains__
SESSIONS = ['2026-10-01', '2026-10-02', '2026-10-05', '2026-10-06', '2026-10-07', '2026-10-08', '2026-10-12']
AFTER = ['2026-10-13', '2026-10-14', '2026-10-15', '2026-10-16', '2026-10-19', '2026-10-20', '2026-10-21', '2026-10-22',
         '2026-10-23', '2026-10-27']


def test_dates_use_recorded_sessions_then_the_calendar():
    assert F.next_session(SESSIONS[:-1], '2026-10-12', is_closed) == '2026-10-13'   # DB not yet updated for 10-12
    assert F.add_sessions(SESSIONS, '2026-10-13', 10, is_closed) == '2026-10-27'     # 10-26 is a holiday
    assert F.deadline_session('2026-09', SESSIONS, is_closed) == '2026-10-12'
    assert F.deadline_session('2026-10', SESSIONS, is_closed) == '2026-11-10'
    assert F.upcoming('2026-10-09', set(), SESSIONS, is_closed) == ('2026-10-12', '2026-10-13')
    assert F.upcoming('2026-10-12', {'2026-09'}, SESSIONS, is_closed) == ('2026-11-10', '2026-11-11')
    assert F.upcoming('2026-10-20', {'2026-09'}, SESSIONS, is_closed) == ('2026-11-10', '2026-11-11')


def fixture():
    symbols = ['%04d' % (2000 + i) for i in range(12)]
    months = ['2025-%02d' % m for m in range(9, 13)] + ['2026-%02d' % m for m in range(1, 10)]
    revenue = {s: {m: (1000 * math.exp(0.01 * ((k + i) % 3) + (0.02 * (12 - i) if m == '2026-09' else 0)), 1000.0)
                   for k, m in enumerate(months)} for i, s in enumerate(symbols)}
    names = {s: '公司%s' % s for s in symbols}
    picks = {'month': '2026-09', 'deadline_session': '2026-10-12',
             'signals': {'S2_SUR': {'n_scored': 12, 'top': symbols[:11], 'bottom': symbols[-1:], 'scored': symbols}}}
    bars = {s: {d: {'open': 50.0, 'close': 50.0, 'reference': 50.0} for d in SESSIONS} for s in symbols}
    return symbols, revenue, names, picks, bars


def test_waiting_batch_lists_top10_with_names_and_estimated_shares():
    symbols, revenue, names, picks, bars = fixture()
    b = F.build_batch(picks, revenue, names, SESSIONS, bars, {}, is_closed)
    assert b['status'] == 'waiting_entry' and b['entry_day'] == '2026-10-13' and b['exit_day'] == '2026-10-27'
    assert [r['symbol'] for r in b['positions']] == symbols[:10]
    first = b['positions'][0]
    assert first['name'] == '公司2000' and first['shares_est'] == 2000 and first['deadline_close'] == 50.0
    assert first['sur'] is not None and first['rev_yoy_pct'] == pytest.approx(round((math.exp(0.24) - 1) * 100, 1))


def test_holding_and_closed_batches_keep_unfilled_slots_in_cash():
    symbols, revenue, names, picks, bars = fixture()
    for s in symbols:
        bars[s]['2026-10-13'] = {'open': 50.0, 'close': 51.0, 'reference': 50.0}
        bars[s]['2026-10-14'] = {'open': 51.0, 'close': 55.0, 'reference': 51.0}
    bars[symbols[0]]['2026-10-13'] = {'open': 55.0, 'close': 55.0, 'reference': 50.0}  # opened limit-up
    sessions = SESSIONS + AFTER[:2]
    b = F.build_batch(picks, revenue, names, sessions, bars, {}, is_closed)
    assert b['status'] == 'holding' and b['mark_day'] == '2026-10-14'
    assert b['n_filled'] == 9 and b['n_unfilled'] == 1 and b['positions'][0]['filled'] is False
    one = (55 / 50 - 1) * 100 - F.R.cost_pct(50.0, 55.0, same_day=False)
    assert b['net_pct'] == pytest.approx(round(one * 9 / 10, 2))
    assert b['twd_per_1m'] == round(one * 9 / 10 * 10000)
    assert b['universe_net_pct'] == pytest.approx(round(one, 2)) and b['positions'][1]['shares'] == 2000
    for s in symbols:
        for d in AFTER[2:]:
            bars[s][d] = {'open': 55.0, 'close': 55.0, 'reference': 55.0}
    closed = F.build_batch(picks, revenue, names, SESSIONS + AFTER + ['2026-10-28'], bars, {}, is_closed)
    assert closed['status'] == 'closed' and closed['mark_day'] == '2026-10-27'
    feed = F.build_feed([closed], '2026-10-28', '2026-11-10', '2026-11-11', '2026-10-28T08:00:00+08:00')
    assert feed['current'] is None and feed['last_closed']['month'] == '2026-09'
    assert feed['record'] == {'batches': 1, 'wins': 1, 'twd_per_1m_total': closed['twd_per_1m']}
    assert feed['rules_version'] == 'revenue-sur-short-v1' and feed['strategy']['hold_sessions'] == 10


def test_ex_rights_drop_is_added_back():
    symbols, revenue, names, picks, bars = fixture()
    for s in symbols:
        bars[s]['2026-10-13'] = {'open': 50.0, 'close': 50.0, 'reference': 50.0}
        bars[s]['2026-10-14'] = {'open': 48.0, 'close': 48.0, 'reference': 48.0}
    rets, unfilled = F.position_returns(symbols[:1], bars, {symbols[0]: [('2026-10-14', 50.0 / 48.0)]}, '2026-10-13', '2026-10-14')
    assert not unfilled
    assert rets[symbols[0]]['net_pct'] == pytest.approx(-F.R.cost_pct(50.0, 48.0, same_day=False))
