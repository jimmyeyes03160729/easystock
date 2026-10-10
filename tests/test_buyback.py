"""BUYBACK_V1: MOPS table parsing, entry timing, month-clustered t, criteria and a planted-effect end-to-end check."""
import json
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
for sub in ('research/buyback_v1', 'research/inst_flow_v1', 'research/revenue_v1', '.'):
    sys.path.insert(0, str(ROOT / sub))
import bb_study as B  # noqa: E402
import fetch_buyback as F  # noqa: E402

ROW = ('<tr><td>1</td><td>1101</td><td>台泥</td><td>107/02/02</td><td>3</td><td>47,291,021,000</td><td>6,000,000</td><td>26.53</td>'
       '<td>56.63</td><td>107/02/05</td><td>107/04/03</td><td>Y</td><td>0</td><td>x</td></tr>')


def test_parse_keeps_only_announcement_time_columns():
    html = ('<table><tr><td>序號</td><td>公司代號</td></tr>' + ROW + ROW.replace('1101', '0050') +
            ROW.replace('107/02/05', '').replace('<td>56.63</td>', '<td>56.63</td>') + '</table>')
    rows = F.parse(html)
    assert rows == [('1101', '台泥', '2018-02-02', '3', 47291021000.0, 6000000.0, 26.53, 56.63, '2018-02-05', '2018-04-03')]
    assert F.iso('99/12/31') == '2010-12-31' and F.iso('bad') is None


def test_entry_is_the_first_session_after_the_period_start():
    sessions = ['2024-03-07', '2024-03-08', '2024-03-11', '2024-03-12']
    assert B.entry_index(sessions, '2024-03-07') == 1          # start day itself is not tradable: next session
    assert B.entry_index(sessions, '2024-03-09') == 2          # weekend start rolls to Monday
    assert B.entry_index(sessions, '2024-03-12') == 4          # beyond the last session


def test_cluster_t_widens_with_month_clustering():
    xs = [2.0, 2.0, 2.0, 0.0, 0.0, 0.0]
    independent = B.cluster_t(xs, list(range(6)))
    clustered = B.cluster_t(xs, ["a", "a", "a", "b", "b", "b"])
    assert independent > clustered > 0
    assert B.cluster_t([1.0], ['a']) is None


def ev(year, net, excess, month='2024-01'):
    return {'year': year, 'month': month if month else '%d-01' % year, 'net': net, 'excess': excess}


def test_criteria_counted_years_and_classification():
    good = [ev(y, 5.0 + (i % 3) * 0.5, 4.0 + (i % 3) * 0.5, '%d-%02d' % (y, i % 12 + 1)) for y in (2022, 2023, 2024) for i in range(30)]
    c, st = B.summarize(good)
    assert all(c.values()) and B.classify(c) == 'STRONG' and st['events'] == 90
    thin = [ev(2024, 5.0, 4.0, '2024-%02d' % (i % 12 + 1)) for i in range(70)]
    c, _ = B.summarize(thin)
    assert c['G'] is False and B.classify(c) == 'INSUFFICIENT'
    neg = [ev(y, -3.0 + (i % 3) * 0.1, -0.5 + (i % 3) * 0.1, '%d-%02d' % (y, i % 12 + 1)) for y in (2022, 2023, 2024) for i in range(30)]
    c, _ = B.summarize(neg)
    assert B.classify(c) == 'NO_EDGE'
    assert B.summarize([]) is None


def test_planted_effect_end_to_end(tmp_path, monkeypatch):
    days, d = [], date(2024, 1, 1)
    while len(days) < 200:
        if d.weekday() < 5:
            days.append(d.isoformat())
        d += timedelta(days=1)
    n_days, n_sym = len(days), 150
    shape = (n_days, n_sym)
    O, C, REF = (np.full(shape, 100.0) for _ in range(3))
    A = np.full(shape, 1e8, dtype=np.float32)
    V = np.full(shape, 1e6, dtype=np.float32)
    Z = np.zeros(shape, dtype=np.float32)
    for k in range(30):
        C[41 + k:, k] = 108.0          # entry session index 41 + k, price jumps to 108 from entry
    symbols = ['%04d' % (1000 + j) for j in range(n_sym)]
    monkeypatch.setattr(B.IFL, 'load', lambda: (days, symbols, O, C, REF, V, A, Z, Z, np.zeros(shape)))
    db = tmp_path / 'data'
    db.mkdir()
    con = sqlite3.connect(db / 'buyback.sqlite')
    con.execute('CREATE TABLE programs (symbol TEXT, name TEXT, board_date TEXT, purpose TEXT, cap_amount REAL, planned_shares REAL, price_min REAL, price_max REAL, start_date TEXT, end_date TEXT, market TEXT)')
    for k in range(30):
        con.execute('INSERT INTO programs VALUES (?,?,?,?,?,?,?,?,?,?,?)', (symbols[k], 'x', days[40 + k], '3', 1.0, 1.0, 1.0, 2.0, days[40 + k], days[60 + k], 'sii'))
    con.commit()
    con.close()
    monkeypatch.setattr(B, 'DB', db / 'buyback.sqlite')
    monkeypatch.setattr(B, 'OUT', tmp_path / 'out')
    B.main()
    res = json.loads((tmp_path / 'out' / 'BUYBACK_DECISION.json').read_text())['results']['3|LIQ50|H20']
    st = res['stats']
    assert st['events'] == 30 and res['events'][0]['entry'] == days[41] and res['events'][0]['exit'] == days[60]
    assert st['mean_excess_pct'] == pytest.approx(6.5, abs=0.5) and st['mean_net_pct'] > 7
    assert res['classification'] == 'INSUFFICIENT'      # a single year of data cannot satisfy the frozen G rule
