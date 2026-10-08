"""REVENUE_FORWARD_V1: deadline-evening logic, frozen universe, picks without post-cutoff prices, locked evaluation."""
import json
import math
import sqlite3
import sys
from argparse import Namespace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for sub in ('research/revenue_v1', '.'):
    sys.path.insert(0, str(ROOT / sub))
import rev_fwd as W  # noqa: E402

DAYS_BEFORE = ['2026-09-%02d' % d for d in (4, 7, 8, 9, 10, 11, 14, 15, 16, 17, 18, 21, 22, 23, 24, 25, 28, 29, 30)] + ['2026-10-01', '2026-10-02']


def test_deadline_evening_is_first_session_on_or_after_the_tenth():
    sessions = {'2026-10-07', '2026-10-08', '2026-10-12', '2026-10-13'}
    assert W.is_deadline_evening(sessions, '2026-10-12') is True      # 10th/11th are weekend, 9th is before the 10th
    assert W.is_deadline_evening(sessions, '2026-10-13') is False
    assert W.is_deadline_evening(sessions, '2026-10-08') is False     # before the 10th
    assert W.is_deadline_evening({'2026-11-09', '2026-11-10', '2026-11-11'}, '2026-11-10') is True
    assert W.is_deadline_evening({'2026-11-10', '2026-11-11'}, '2026-11-11') is False
    assert W.revenue_month_for('2026-10-12') == '2026-09' and W.revenue_month_for('2027-01-11') == '2026-12'


def make_daily(path):
    c = sqlite3.connect(path)
    c.execute('CREATE TABLE sessions (day TEXT, exchange TEXT, status TEXT)')
    c.execute('CREATE TABLE bars (symbol TEXT, day TEXT, close REAL, amount REAL)')
    for d in DAYS_BEFORE + ['2026-10-12']:
        c.execute("INSERT INTO sessions VALUES (?, 'TWSE', 'open')", (d,))
    for i in range(1, 41):
        for d in DAYS_BEFORE:
            c.execute('INSERT INTO bars VALUES (?,?,?,?)', ('%04d' % (1000 + i), d, 50.0, 1e8))
        c.execute('INSERT INTO bars VALUES (?,?,?,?)', ('%04d' % (1000 + i), '2026-10-12', 99999.0, 1.0))   # must never be read
    c.execute('INSERT INTO bars VALUES (?,?,?,?)', ('0050', '2026-10-02', 50.0, 1e8))                     # not a common stock
    c.commit()
    c.close()


def make_revenue(path):
    c = sqlite3.connect(path)
    c.execute('CREATE TABLE revenue (symbol TEXT, month TEXT, revenue REAL, last_year REAL)')
    c.execute('CREATE TABLE pages (page TEXT, month TEXT)')
    months = ['2025-%02d' % m for m in range(9, 13)] + ['2026-%02d' % m for m in range(1, 10)]
    for i in range(1, 41):
        for k, m in enumerate(months):
            g = 0.05 * ((k * 7 + i) % 5) if m != '2026-09' else 0.02 * i
            c.execute('INSERT INTO revenue VALUES (?,?,?,?)', ('%04d' % (1000 + i), m, 1000 * math.exp(g), 1000.0))
    c.commit()
    c.close()


def test_frozen_universe_and_picks_never_read_later_prices(tmp_path, monkeypatch):
    daily_db, rev_db = tmp_path / 'daily.sqlite', tmp_path / 'revenue.sqlite'
    make_daily(daily_db)
    make_revenue(rev_db)
    monkeypatch.setattr(W, 'DAILY_DB', str(daily_db))
    monkeypatch.setattr(W, 'FWD', tmp_path / 'forward')
    monkeypatch.setattr(W, 'UNIVERSE_FILE', tmp_path / 'forward' / 'universe_frozen.json')
    assert W.cmd_picks(Namespace(revenue_db=str(rev_db), today='2026-10-08', month=None, force=False)) == 0
    assert not (tmp_path / 'forward').exists() or not list((tmp_path / 'forward').glob('picks_*'))
    assert W.cmd_picks(Namespace(revenue_db=str(rev_db), today='2026-10-12', month=None, force=False)) == 0
    uni = json.loads((tmp_path / 'forward' / 'universe_frozen.json').read_text())
    assert uni['as_of'] == '2026-10-02' and len(uni['symbols']) == 40 and '0050' not in uni['symbols']
    picks = json.loads((tmp_path / 'forward' / 'picks_2026-09.json').read_text())
    assert picks['deadline_session'] == '2026-10-12'
    s2 = picks['signals']['S2_SUR']
    assert s2['n_scored'] == 40 and len(s2['top']) == 4 and s2['top'][0] == '1040'
    assert picks['signals']['S1_YOY']['top'][0] == '1040'
    monkeypatch.setattr(W, 'cmd_picks', lambda a: 99)
    assert W.cmd_due(Namespace(today='2026-10-13')) == 1


def test_evaluate_is_locked_without_authorization(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(W, 'ROOT', tmp_path)
    assert W.cmd_evaluate(Namespace(month='2026-09')) == 3
    assert 'EVAL_AUTHORIZED missing' in capsys.readouterr().out
