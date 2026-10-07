from datetime import date, datetime, timedelta, timezone
import json

from rebound_learning.collector import collect, collect_v2
from rebound_learning.features import market_context, near_miss_diagnostics
from rebound_learning.market_daily import (_store_session, adjustment_factor, connect as market_connect,
                                           future_bars, load_histories, parse_ex_rights, parse_tpex,
                                           parse_tpex_index, parse_twse)
from rebound_learning.official import run, label, audit, scaled
from rebound_learning.schema import connect
from rebound_learning_fixture import bars

DAY = '2023-09-04'


def twse_payload():
    stock = ['證券代號', '證券名稱', '成交股數', '成交筆數', '成交金額', '開盤價', '最高價', '最低價', '收盤價',
             '漲跌(+/-)', '漲跌價差', '最後揭示買價', '最後揭示買量', '最後揭示賣價', '最後揭示賣量', '本益比']
    return {'stat': 'OK', 'date': '20230904', 'tables': [
        {'fields': ['指數', '收盤指數', '漲跌(+/-)', '漲跌點數', '漲跌百分比(%)', '特殊處理註記'],
         'data': [['發行量加權股價指數', '16,700.13', '<p style =\'color:red\'>+</p>', '82.11', '0.49', '']]},
        {'fields': stock, 'data': [
            ['0050', 'ETF', '1', '1', '100', '125.90', '126.80', '125.60', '126.75', '<p style= color:red>+</p>', '0.85', '', '', '', '', ''],
            ['2330', '台積電', '20,000,000', '9', '10,960,000,000', '546.00', '550.00', '545.00', '548.00', '<p style= color:red>+</p>', '3.00', '', '', '', '', ''],
            ['2881', '富邦金', '1,000', '1', '61,700', '61.70', '62.00', '61.50', '61.80', '<p>X</p>', '0.00', '', '', '', '', ''],
            ['2067', '無成交', '0', '0', '0', '--', '--', '--', '--', '<p> </p>', '0.00', '', '', '', '', ''],
        ]}]}


def test_twse_parser_filters_etf_no_trade_and_keeps_reference():
    stocks, indices = parse_twse(twse_payload(), DAY)
    assert indices == {'TAIEX': 16700.13}
    by = {b['symbol']: b for b in stocks}
    assert set(by) == {'2330', '2881'}
    assert by['2330']['reference'] == 545.0 and by['2330']['amount'] == 10_960_000_000
    assert by['2881']['reference'] is None  # "X": ex-rights reference comes from TWT49U
    assert parse_twse({**twse_payload(), 'date': '20230905'}, DAY) == ([], {})
    assert parse_twse({'stat': '很抱歉，沒有符合條件的資料!'}, DAY) == ([], {})


def test_tpex_parser_next_reference_and_index():
    fields = ['代號', '名稱', '收盤', '漲跌', '開盤', '最高', '最低', '均價', '成交股數', '成交金額(元)', '成交筆數',
              '最後買價', '最後買量(千股)', '最後賣價', '最後賣量(千股)', '發行股數', '次日 參考價', '次日 漲停價', '次日 跌停價']
    payload = {'stat': 'ok', 'date': '20230904', 'tables': [{'fields': fields, 'data': [
        ['006201', 'ETF', '18.39', '-0.03', '18.44', '18.44', '18.30', '', '8,019', '147,308', '', '', '', '', '', '', '18.39', '', ''],
        ['8069', '元太', '200.00', '1.00', '199.0', '201.0', '198.0', '', '1,000', '200,000', '', '', '', '', '', '', '196.50', '', ''],
        ['2067', '嘉鋼', ' ---', '--- ', '---', '---', '---', '', '0', '0', '', '', '', '', '', '', '13.50', '', ''],
    ]}]}
    stocks, nxt = parse_tpex(payload, DAY)
    assert [b['symbol'] for b in stocks] == ['8069']
    assert nxt == {'8069': 196.5, '2067': 13.5}
    assert parse_tpex_index({'tables': [{'data': [['紡織纖維', '106.71'], ['櫃買指數', '221.14']]}]}) == 221.14


def test_ex_rights_parser_and_factor():
    payload = {'stat': 'OK', 'fields': ['資料日期', '股票代號', '股票名稱', '除權息前收盤價', '除權息參考價'],
               'data': [['112年09月04日', '2881', '富邦金', '64.80', '61.71'], ['112年09月04日', '00878', 'ETF', '20', '19']]}
    assert parse_ex_rights(payload) == [{'symbol': '2881', 'day': '2023-09-04', 'previous_close': 64.8, 'reference': 61.71}]
    assert adjustment_factor(100, 100.02) == 1.0
    assert adjustment_factor(100, 95) == 0.95
    assert adjustment_factor(None, 95) == 1.0


def test_today_is_never_recorded_closed_before_publication():
    db = market_connect(':memory:')
    # _store_session compares against the Taiwan calendar date, not the runner's local (UTC on CI) date
    today = datetime.now(timezone(timedelta(hours=8))).date().isoformat()
    _store_session(db, today, 'TWSE', [], {})
    assert db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0] == 0
    _store_session(db, '2023-09-02', 'TWSE', [], {})
    assert db.execute("SELECT status FROM sessions").fetchone()[0] == 'closed'


def _market_with(series, symbol='2330', exchange='TWSE', dividend_at=None):
    db = market_connect(':memory:')
    for i, bar in enumerate(series):
        factor = 0.95 if dividend_at is not None and i >= dividend_at else 1.0
        scaled_bar = {k: round(bar[k] * factor, 4) for k in ('open', 'high', 'low', 'close')}
        db.execute('INSERT INTO bars VALUES (?,?,?,?,?,?,?,?,?,?)',
                   (symbol, bar['time'], exchange, scaled_bar['open'], scaled_bar['high'], scaled_bar['low'],
                    scaled_bar['close'], bar['volume'], bar['amount'], 0.0))
        db.execute("INSERT OR IGNORE INTO sessions VALUES (?, 'TWSE', 'open', 1, 'x')", (bar['time'],))
        db.execute("INSERT OR IGNORE INTO indices VALUES (?, 'TAIEX', ?)", (bar['time'], 16000 + i))
        db.execute("INSERT OR IGNORE INTO indices VALUES (?, 'TPEX', ?)", (bar['time'], 200 + i / 10))
    if dividend_at is not None:
        previous = series[dividend_at - 1]['close']
        db.execute('INSERT INTO ex_rights VALUES (?,?,?,?)',
                   (symbol, series[dividend_at]['time'], previous, round(previous * 0.95, 4)))
    db.commit()
    return db


def test_dividend_adjustment_uses_only_events_up_to_each_day():
    source = bars(180)
    market = _market_with(source, dividend_at=170)
    _, _, raw = next(load_histories(market, ['2330']))
    assert raw[170]['adj_factor'] == 0.95 and raw[170]['adj_status'] == 'event'
    series, cums = scaled(raw)
    # Before the event the scaled prefix equals raw prices (C=1): no future leak.
    assert all(abs(series[j]['close'] - source[j]['close']) < 1e-9 for j in range(170))
    # After the event, scaling by C_k restores continuity with pre-event prices.
    assert abs(series[175]['close'] * cums[175] - raw[175]['close']) < 1e-6
    assert abs(series[175]['close'] - source[175]['close']) < 1e-3
    # Labels from D0=165 see post-dividend bars on the D0 price basis.
    future = future_bars(market, '2330', source[165]['time'])
    assert future[0]['time'] == source[166]['time']
    assert abs(future[5]['close'] - source[171]['close']) < 1e-3


def test_market_context_has_no_lookahead():
    days = [f'2026-01-{d:02d}' for d in range(1, 30)]
    closes = {'TAIEX': {d: 100 + i for i, d in enumerate(days)}, 'TPEX': {}}
    full = market_context(days, closes, {})
    partial = market_context(days[:22], closes, {})
    assert full[days[21]] == partial[days[21]]
    assert full[days[21]]['taiex_return_1d_pct'] == round((121 / 120 - 1) * 100, 6)
    assert full[days[21]]['tpex_return_5d_pct'] is None and full[days[21]]['taiex_bias_ma60_pct'] is None


def test_v1_near_miss_shape_is_unchanged():
    source = bars()
    tolerance = {'distance_to_support': 0.01, 'range_position': 0.03, 'net_rr': 0.10}
    result = near_miss_diagnostics(source, source[-1]['time'], tolerance=tolerance)
    assert result is None or 'failed_rules' not in result
    assert collect('2330', source, source[-1]['time'])['feature_schema_version'] == 1


def test_collect_v2_adds_context_and_actual_price_basis():
    source = bars()
    context = {'taiex_return_5d_pct': 1.0, 'breadth_up_ratio': 0.6}
    row = collect_v2('2330', source, source[-1]['time'], exchange='TWSE', context=context, price_basis=2.0)
    v1 = collect('2330', source, source[-1]['time'])
    assert row['candidate_kind'] == 'PENDING' and row['feature_schema_version'] == 2
    assert row['features']['breadth_up_ratio'] == 0.6 and row['features']['is_otc'] == 0
    assert row['features']['stock_vs_market_5d_pct'] == round(row['features']['return_5d_pct'] - 1.0, 6)
    assert row['evidence']['target_price'] == round(v1['evidence']['target_price'] * 2, 6)
    assert row['market_context_source'] == 'official_daily_pit'


def test_official_run_is_idempotent_resumable_and_labels(tmp_path, monkeypatch):
    monkeypatch.setenv('EASYSTOCK_REBOUND_DATA_DIR', str(tmp_path))
    source = bars()
    extra = [{'time': (date.fromisoformat(source[-1]['time']) + timedelta(days=d)).isoformat(),
              'open': 10.6, 'high': 20, 'low': 10.4, 'close': 15, 'volume': 1, 'amount': 10_000_000}
             for d in range(3, 3 + 20) if (date.fromisoformat(source[-1]['time']) + timedelta(days=d)).weekday() < 5]
    market = _market_with(source + extra)
    day = source[-1]['time']
    with connect(tmp_path / 'v2.sqlite') as db:
        first = run(market, db, day, day, progress=False)
        assert first['candidate_events'] == 1 and first['kinds'] == {'PENDING': 1}
        assert run(market, db, day, day, progress=False)['candidate_events'] == 0  # resumable
        db.execute('DELETE FROM v2_progress')
        assert run(market, db, day, day, progress=False)['candidate_snapshots_reused'] == 1
        assert label(market, db) == 1
        outcome = json.loads(db.execute('SELECT label FROM candidates').fetchone()[0])
        assert outcome['label'] == 'SUCCESS' and outcome['entry_price'] == 10.6
        assert label(market, db) == 0  # matured labels are skipped
        report = audit(market, db, write=False)
        assert report['data_quality']['critical_count'] == 0
        assert report['coverage']['historical_market_context_ratio'] == 1.0
