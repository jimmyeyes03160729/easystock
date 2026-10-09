"""INST_FLOW_V1: page parsers, vectorised costs vs paper_execution, signal windows, ranking and event schedule."""
import json
import math
import sys
from decimal import Decimal
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
for sub in ('research/inst_flow_v1', 'research/revenue_v1', '.'):
    sys.path.insert(0, str(ROOT / sub))
import fetch_inst as F  # noqa: E402
import ifl_study as S  # noqa: E402
import paper_execution as pe  # noqa: E402


def test_parse_twse_sums_foreign_with_foreign_dealers_and_checks_the_total():
    row = ['2330', '台積電', '51,756,480', '21,974,607', '29,781,873', '10', '0', '10', '4,072,000', '101,333',
           '3,970,667', '1,195,594', '0', '0', '0', '0', '0', '0', '34,948,144']
    bad = list(row)
    bad[0], bad[18] = '1101', '1'
    etf = ['0050'] + row[1:]
    out = F.parse_twse({'stat': 'OK', 'data': [row, bad, etf]})
    assert out['2330'] == (29781883, 3970667, 1195594, 34948144, True)
    assert out['1101'][4] is False and '0050' not in out
    assert F.parse_twse({'stat': '很抱歉，沒有符合條件的資料!'}) == {}


def test_parse_tpex_uses_total_columns():
    row = ['1240', '茂生農經'] + ['0'] * 22
    row[10], row[13], row[22], row[23] = '100', '-30', '-20', '50'
    out = F.parse_tpex({'tables': [{'data': [row, ['006201', 'ETF'] + ['0'] * 22]}]})
    assert out == {'1240': (100, -30, -20, 50, True)}
    assert F.parse_tpex({'tables': [{'data': []}]}) == {} and F.parse_tpex({}) == {}


def test_vectorised_cost_matches_paper_execution():
    rng = np.random.default_rng(7)
    entry = rng.uniform(8, 900, 400).round(2)
    exit_ = (entry * rng.uniform(0.9, 1.1, 400)).round(2)
    for same_day in (True, False):
        vec = S.cost_pct_vec(entry, exit_, same_day)
        for e, x, v in zip(entry, exit_, vec):
            ea, xa = Decimal(str(e)) * 1000, Decimal(str(x)) * 1000
            ref = float((pe.fee(ea) + pe.fee(xa) + pe.tax(xa, same_day=same_day)) / ea * 100)
            assert v == pytest.approx(ref, abs=1e-6)


def test_rolling_sum_needs_all_rows_and_ratio_uses_volume():
    m = np.arange(1.0, 9.0).reshape(8, 1)
    r = S.rolling_sum(m, 5)
    assert np.isnan(r[:4]).all() and r[4, 0] == 15 and r[7, 0] == 4 + 5 + 6 + 7 + 8
    m2 = m.copy()
    m2[5, 0] = np.nan
    r2 = S.rolling_sum(m2, 5)
    assert r2[4, 0] == 15 and np.isnan(r2[5:8, 0]).all()
    net, vol = np.full((6, 2), 10.0), np.full((6, 2), 100.0)
    vol[:, 1] = 0.0
    sig = S.ratio_signal(net, vol)
    assert sig[4, 0] == pytest.approx(0.1) and np.isnan(sig[4, 1]) and np.isnan(sig[3, 0])


def test_ranked_orders_descending_with_column_tiebreak_and_masks():
    scores = np.array([0.5, 0.9, 0.9, np.nan, 0.1, 0.7])
    mask = np.array([True, True, True, True, True, False])
    assert list(S.ranked(scores, mask)) == [1, 2, 0, 4]


def test_event_days_start_after_liquidity_history_and_do_not_overlap():
    assert S.event_days(60, 1)[:2] == [19, 20] and S.event_days(60, 1)[-1] == 58
    assert S.event_days(100, 20) == [19, 39, 59, 79]
    assert all(b - a == 5 for a, b in zip(S.event_days(60, 5), S.event_days(60, 5)[1:]))


def test_planted_signal_shows_up_with_next_session_timing(tmp_path, monkeypatch):
    n_days, n_sym = 90, 150
    sessions = ['2024-01-%02d' % d for d in range(1, 32)] + ['2024-02-%02d' % d for d in range(1, 29)] + ['2024-03-%02d' % d for d in range(1, 32)]
    sessions = sessions[:n_days]
    shape = (n_days, n_sym)
    O = np.full(shape, 100.0)
    good = np.arange(n_sym) < 20
    C = np.where(good[None, :], 102.0, 100.0) * np.ones(shape)
    REF = np.full(shape, 100.0)
    V = np.full(shape, 1e6, dtype=np.float32)
    A = np.full(shape, 1e8, dtype=np.float32)
    FN = np.random.default_rng(2).normal(0, 1e3, shape).astype(np.float32)
    TN = np.where(good[None, :], 1e5, -1e4).astype(np.float32) * np.ones(shape, dtype=np.float32)
    TN[:, 20:] += np.random.default_rng(1).normal(0, 1e3, (n_days, n_sym - 20)).astype(np.float32)
    symbols = ['%04d' % (1000 + j) for j in range(n_sym)]
    monkeypatch.setattr(S, 'load', lambda: (sessions, symbols, O, C, REF, V, A, FN, TN, np.zeros(shape)))
    monkeypatch.setattr(S, 'OUT', tmp_path)
    monkeypatch.setattr(S, 'ROOT', tmp_path)
    S.main()
    res = json.loads((tmp_path / 'INST_FLOW_DECISION.json').read_text())['results']
    dt = res['IT5|DT']['series']
    assert dt[0]['date'] == sessions[19] and dt[0]['entry'] == sessions[20] and dt[0]['exit'] == sessions[20]
    assert all(m['top'] == pytest.approx(2.0 - float(S.cost_pct_vec(np.array([100.0]), np.array([102.0]), True)[0])) for m in dt)
    assert all(m['excess'] > 1.0 for m in dt)
    assert abs(res["FI5|DT"]["stats"]["mean_excess_pct"]) < 0.5
