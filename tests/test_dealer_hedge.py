"""DEALER_HEDGE_V1: dealer column split, FinMind futures rows, futures gate and a planted-signal end-to-end run."""
import gzip
import json
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
for sub in ('research/dealer_hedge_v1', 'research/inst_flow_v1', 'research/revenue_v1', '.'):
    sys.path.insert(0, str(ROOT / sub))
import extract_dealer as X  # noqa: E402
import fetch_futures as FF  # noqa: E402
import dh_study as S  # noqa: E402

TWSE_FIELDS = ['證券代號', '證券名稱', '外陸資買進股數(不含外資自營商)', '外陸資賣出股數(不含外資自營商)', '外陸資買賣超股數(不含外資自營商)',
               '外資自營商買進股數', '外資自營商賣出股數', '外資自營商買賣超股數', '投信買進股數', '投信賣出股數', '投信買賣超股數',
               '自營商買賣超股數', '自營商買進股數(自行買賣)', '自營商賣出股數(自行買賣)', '自營商買賣超股數(自行買賣)',
               '自營商買進股數(避險)', '自營商賣出股數(避險)', '自營商買賣超股數(避險)', '三大法人買賣超股數']


def test_parse_twse_splits_dealer_and_checks_sum_and_layout():
    row = ['2303', '聯電', '50,902,128', '12,876,294', '38,025,834', '0', '0', '0', '7,292,000', '4,420,555', '2,871,445',
           '1,337,961', '1,858,800', '788,000', '1,070,800', '761,161', '494,000', '267,161', '42,235,240']
    bad = list(row)
    bad[0], bad[11] = '1101', '5'
    out = X.parse_twse({'stat': 'OK', 'fields': TWSE_FIELDS, 'data': [row, bad, ['0050'] + row[1:]]})
    assert out['2303'] == (1070800, 267161, 1337961, True)
    assert out['1101'][3] is False and '0050' not in out
    shifted = list(TWSE_FIELDS)
    shifted[17] = '其他'
    assert X.parse_twse({'stat': 'OK', 'fields': shifted, 'data': [row]}) is None
    assert X.parse_twse({'stat': '很抱歉，沒有符合條件的資料!'}) == {}


def test_parse_tpex_uses_proprietary_hedge_and_dealer_total_columns():
    row = ['006201', '元大富櫃50', '2,000', '6,000', '-4,000', '0', '0', '0', '2,000', '6,000', '-4,000', '0', '0', '0',
           '0', '0', '0', '4,090', '10,678', '-6,588', '4,090', '10,678', '-6,588', '-10,588']
    stock = ['1240'] + row[1:]
    stock[16] = '-12'
    out = X.parse_tpex({'tables': [{'data': [row, stock]}]})
    assert out == {'1240': (-12, -6588, -6588, False)}
    stock[22] = '-6,600'
    assert X.parse_tpex({'tables': [{'data': [stock]}]})['1240'] == (-12, -6588, -6600, True)


def test_extract_main_writes_rows_and_skips_days_after_cutoff(tmp_path, monkeypatch):
    raw = tmp_path / 'raw'
    raw.mkdir()
    row = ['2303', '聯電'] + ['0'] * 9 + ['30', '0', '0', '10', '0', '0', '20', '30']
    for day in ('2026-10-01', '2026-10-05'):
        (raw / ('twse_%s.json.gz' % day)).write_bytes(gzip.compress(json.dumps({'stat': 'OK', 'fields': TWSE_FIELDS, 'data': [row]}).encode()))
    monkeypatch.setattr(X, 'RAW', raw)
    monkeypatch.setattr(X, 'OUT_DB', tmp_path / 'dealer.sqlite')
    X.main()
    db = sqlite3.connect(tmp_path / 'dealer.sqlite')
    assert db.execute('SELECT symbol, day, self_net, hedge_net, dealer_net, consistent FROM dealer').fetchall() == [('2303', '2026-10-01', 10, 20, 30, 1)]


def test_futures_rows_keep_tx_three_investors_and_cutoff():
    payload = {'status': 200, 'data': [
        {'futures_id': 'TX', 'date': '2022-01-03', 'institutional_investors': '外資', 'long_open_interest_balance_volume': 50,
         'short_open_interest_balance_volume': 70, 'long_deal_volume': 5, 'short_deal_volume': 6},
        {'futures_id': 'TX', 'date': '2026-10-05', 'institutional_investors': '外資', 'long_open_interest_balance_volume': 1,
         'short_open_interest_balance_volume': 1, 'long_deal_volume': 1, 'short_deal_volume': 1},
        {'futures_id': 'MTX', 'date': '2022-01-03', 'institutional_investors': '外資', 'long_open_interest_balance_volume': 1,
         'short_open_interest_balance_volume': 1, 'long_deal_volume': 1, 'short_deal_volume': 1}]}
    assert FF.rows_of(payload) == [('2022-01-03', 'foreign', 50, 70, 5, 6)]
    with pytest.raises(ValueError):
        FF.rows_of({'status': 400, 'msg': 'Your level is free.'})


def test_gate_series_and_criteria():
    g = S.gate_series(np.array([0.0, 1, 2, 3, 4, 10, np.nan, 3]), lag=5)
    assert np.isnan(g[:5]).all() and g[5] == 10 and np.isnan(g[6]) and g[7] == 1
    ev = [{'fold': f, 'on': k % 2 == 0, 'universe': (0.5 if k % 2 == 0 else -0.5) + 0.01 * k} for f in S.R.FOLDS for k in range(10)]
    c, st = S.gate_criteria(ev)
    assert c == {'GA': True, 'GC': True, 'GD': True, 'GG': True} and S.gate_classify(c) == 'STRONG'
    assert st['on'] == st['off'] == 25 and st['diff_pct'] == pytest.approx(0.99)
    assert S.gate_classify({'GA': False, 'GC': False, 'GD': True, 'GG': True}) == 'NO_EDGE'
    assert S.gate_classify({'GA': True, 'GC': True, 'GD': True, 'GG': False}) == 'INSUFFICIENT'


def test_planted_hedge_signal_and_gate_end_to_end(tmp_path, monkeypatch):
    n_days, n_sym = 90, 150
    sessions = (['2024-01-%02d' % d for d in range(1, 32)] + ['2024-02-%02d' % d for d in range(1, 29)] + ['2024-03-%02d' % d for d in range(1, 32)])[:n_days]
    shape = (n_days, n_sym)
    good = np.arange(n_sym) < 20
    O = np.full(shape, 100.0)
    C = np.where(good[None, :], 102.0, 100.0) * np.ones(shape)
    REF = np.full(shape, 100.0)
    V = np.full(shape, 1e6, dtype=np.float32)
    A = np.full(shape, 1e8, dtype=np.float32)
    HN = np.where(good[None, :], 1e5, -1e4).astype(np.float32) * np.ones(shape, dtype=np.float32)
    HN[:, 20:] += np.random.default_rng(1).normal(0, 1e3, (n_days, n_sym - 20)).astype(np.float32)
    SN = np.random.default_rng(2).normal(0, 1e3, shape).astype(np.float32)
    fx = np.arange(n_days, dtype=float)
    symbols = ['%04d' % (1000 + j) for j in range(n_sym)]
    monkeypatch.setattr(S, 'load', lambda: (sessions, symbols, O, C, REF, V, A, HN, SN, np.zeros(shape), fx))
    monkeypatch.setattr(S, 'OUT', tmp_path)
    monkeypatch.setattr(S, 'ROOT', tmp_path)
    S.main()
    res = json.loads((tmp_path / 'DEALER_HEDGE_DECISION.json').read_text())['results']
    dt = res['DH5|DT']['series']
    assert dt[0]['date'] == sessions[19] and dt[0]['entry'] == sessions[20] and dt[0]['exit'] == sessions[20]
    assert all(m['excess'] > 1.0 for m in dt)
    assert abs(res['DS5|DT']['stats']['mean_excess_pct']) < 0.5
    gate = res['FX5_GATE|DT']
    assert gate['stats']['on'] == len(dt) and gate['stats']['off'] == 0 and gate['classification'] == 'INSUFFICIENT'
