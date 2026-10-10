"""LLM 紙上測試：回覆解析、組別（交集/多數/對照組）、進出場與漲停留現金、晚凍結作廢。"""
import json
from datetime import datetime

from llm_paper import run as L

UNIVERSE = {'%04d' % (2000 + i): (20.0 + i, (i + 1) * 20_000_000) for i in range(20)}


def test_parse_reads_json_drops_unknown_and_caps_at_five():
    text = '說明\n```json\n{"picks": [{"symbol": "2001"}, {"symbol": "9999"}, {"symbol": "2001"}, ' \
           + ', '.join('{"symbol": "%04d"}' % (2002 + i) for i in range(6)) + ']}\n```'
    valid, invalid = L.parse_symbols(text, UNIVERSE)
    assert valid == ['2001', '2002', '2003', '2004', '2005']
    assert invalid == ['9999']
    assert L.parse_symbols('看好 2010 與 2011，還有 123456', UNIVERSE) == (['2010', '2011'], [])
    assert L.parse_symbols('', UNIVERSE) == ([], [])
    closed = '{"picks": [], "reason": "2026-10-10 是國慶日，休市"}'
    assert L.parse_symbols(closed, UNIVERSE | {'2026': (30.0, 1e8)}) == ([], [])     # a year is not a pick


def test_groups_consensus_majority_and_baselines():
    three = ('openai', 'claude', 'gemini')
    picks = {'openai': ['2001', '2002', '2003'], 'claude': ['2002', '2001', '2004'], 'gemini': ['2002', '2005']}
    g = L.build_groups(picks, UNIVERSE, '2026-10-13', three)
    assert g['consensus'] == ['2002']
    assert g['majority2'] == ['2001', '2002']
    assert g['hot10'] == ['%04d' % (2019 - i) for i in range(10)]
    assert len(g['random5']) == 5 and all(UNIVERSE[s][1] >= L.MIN_AMOUNT for s in g['random5'])
    assert g['random5'] == L.build_groups(picks, UNIVERSE, '2026-10-13', three)['random5']     # fixed per day
    failed = L.build_groups({'openai': ['2002'], 'claude': ['2002']}, UNIVERSE, '2026-10-13', three)
    assert failed['consensus'] == [] and failed['majority2'] == ['2002'] and failed['gemini'] == []
    two = L.build_groups({'openai': ['2001', '2002'], 'claude': ['2002', '2003']}, UNIVERSE, '2026-10-13', ('openai', 'claude'))
    assert two['consensus'] == ['2002'] and 'majority2' not in two and 'gemini' not in two


def test_default_providers_are_chatgpt_and_claude():
    assert L.MODELS == ('openai', 'claude')
    assert L.GROUPS == ('p200_openai', 'p200_claude', 'p200_consensus', 'p200_hot10', 'p200_random5')


def bar(o, c, ref=None):
    return {'open': o, 'close': c, 'reference': ref or o}


def test_evaluate_holds_five_sessions_and_unfilled_limit_up_stays_cash():
    days = ['2026-10-13', '2026-10-14', '2026-10-15', '2026-10-16', '2026-10-19']
    bars = {'2001': {d: bar(100, 100 + 2 * i) for i, d in enumerate(days)},
            '2002': {days[0]: bar(110, 110, ref=100)}}                  # opens at the 10% limit: not fillable
    batch = {'day': days[0], 'groups': {'p200_openai': ['2001', '2002']}}
    closed = lambda d: False  # noqa: E731
    e = L.evaluate(batch, days, bars, {}, closed)
    assert e['status'] == 'closed' and e['exit_day'] == '2026-10-19'
    g = e['groups']['p200_openai']
    assert g['unfilled'] == ['2002'] and g['n_filled'] == 1
    assert 3.3 < g['net_pct'] < 3.8            # (+8% - costs) / 2 names
    assert g['day1_net_pct'] < 0               # flat day: only costs
    assert L.evaluate(batch, days[:3], bars, {}, closed)['status'] == 'holding'
    assert L.evaluate(batch, ['2026-10-08'], bars, {}, closed)['status'] == 'waiting_entry'
    assert L.evaluate(dict(batch, late=True), days, bars, {}, closed)['status'] == 'void_late'
    s = L.summarize([e])
    assert s['closed_batches'] == 1 and s['groups']['p200_openai']['wins'] == 1
    assert s['groups']['p200_claude']['batches'] == 0


SESSIONS20 = ['2026-09-%02d' % d for d in (14, 15, 16, 17, 18, 21, 22, 23, 24, 25, 26, 29, 30)] +     ['2026-10-%02d' % d for d in (1, 2, 5, 6, 7, 8, 12)]


def daily_db(path, extra=()):
    """20 sessions; UNIVERSE stocks flat at their price, plus extra (symbol, close, amount, n_sessions) rows."""
    import sqlite3
    con = sqlite3.connect(path)
    con.executescript("CREATE TABLE sessions(day, exchange, status); CREATE TABLE ex_rights(symbol, day, previous_close, reference);"
                      "CREATE TABLE bars(symbol, day, exchange, close, amount);")
    con.executemany("INSERT INTO sessions VALUES(?, 'TWSE', 'open')", [(d,) for d in SESSIONS20])
    rows = [(s, d, 'TWSE', c, a) for s, (c, a) in UNIVERSE.items() for d in SESSIONS20]
    rows += [(s, d, 'TPEx', c, a) for s, c, a, n in extra for d in SESSIONS20[-n:]]
    con.executemany('INSERT INTO bars VALUES(?,?,?,?,?)', rows)
    con.commit()
    con.close()


def test_pick_freezes_once_and_records_failures(tmp_path, monkeypatch):
    db = tmp_path / 'daily.sqlite'
    daily_db(db, [('2050', 350.0, 900_000_000, 20)])                                 # liquid but above 200
    monkeypatch.setattr(L, 'OUT_DIR', tmp_path)
    monkeypatch.setattr(L, 'VARIANTS', tuple(L.ALL_VARIANTS.values()))           # both prompts
    monkeypatch.setattr(L, 'DAILY_DB', str(db))
    monkeypatch.setattr(L.C, 'disposition_symbols', lambda day: {'2019'})
    monkeypatch.setattr(L.C, 'load_names', lambda path: {'2003': '測試三'})
    reply = '{"picks": [{"symbol": "2001"}, {"symbol": "2002"}]}'
    calls = []

    def fake(p):
        calls.append(p)
        return reply if 'candidates' not in p and '"fields"' not in p else '{"picks": [{"symbol": "2050"}, {"symbol": "2003"}]}', {}
    monkeypatch.setattr(L, 'PROVIDERS', {'openai': (fake, ('X',)),
                                         'claude': (fake, ('X',)),
                                         'gemini': (lambda p: 1 / 0, ('X',))})
    monkeypatch.setattr(L, 'env', lambda *k, default='': 'k')
    now = datetime(2026, 10, 13, 8, 0, tzinfo=L.TPE)
    assert L.pick(now, clock=lambda: now.replace(minute=6)) == 0
    data = json.loads((tmp_path / 'picks_2026-10-13.json').read_text(encoding='utf-8'))
    assert data['prev_session'] == '2026-10-12' and not data['late'] and data['status_source_ok']
    assert len(calls) == 4                                                            # 2 prompts x 2 models
    assert data['groups']['consensus'] == ['2001', '2002'] and 'gemini' not in data['replies']
    assert data['groups']['p200_consensus'] == ['2003'] and data['invalid']['p200_openai'] == ['2050']
    cand = {r['symbol'] for r in data['candidates']['p200']}
    assert '2050' not in cand and '2019' not in cand and '2000' not in cand            # >200, disposed, avg 20M
    assert data['groups']['hot10'][0] == '2050' and set(data['groups']['p200_hot10']) <= cand
    assert '"測試三"' in data['prompts']['p200'] and '2026-10-13' in data['prompts']['p200']
    assert (tmp_path / 'picks.sha256').read_text().count('picks_2026-10-13.json') == 1
    assert L.pick(now) == 0                                                           # already frozen: untouched
    assert L.pick(datetime(2026, 10, 14, 9, 30, tzinfo=L.TPE)) == 1                   # too late


def test_candidates_filter_and_adjust_for_ex_rights(tmp_path):
    import sqlite3
    db = tmp_path / 'daily.sqlite'
    daily_db(db, [('3001', 100.0, 80_000_000, 19), ('3002', 50.0, 60_000_000, 20)])
    con = sqlite3.connect(db)
    con.execute("UPDATE bars SET close = 45.0 WHERE symbol = '3002' AND day >= '2026-10-07'")   # 5.0 cash dividend on 10-07
    con.execute("INSERT INTO ex_rights VALUES('3002', '2026-10-07', 50.0, 45.0)")
    con.commit()
    con.close()
    rows = L.C.build(str(db), '2026-10-12', '2026-10-13', 200.0, {}, set(), 't')
    by = {r['symbol']: r for r in rows}
    assert '3001' not in by                                    # only 19 sessions
    r = by['3002']
    assert r['exchange'] == 'TPEX' and r['return_5d_pct'] == 0.0 and r['ma20'] == 45.0   # dividend is not a loss
    assert rows[0]['avg_amount_20d'] >= rows[-1]['avg_amount_20d']
    assert all(x['trading_status'] == '正常' for x in rows)
    unknown = L.C.build(str(db), '2026-10-12', '2026-10-13', 200.0, {}, None, 't')
    assert {x['trading_status'] for x in unknown} == {'未知'}
    table = json.loads(L.C.as_prompt_json(rows))
    assert table['fields'][0] == 'symbol' and len(table['rows']) == len(rows)
    assert table['common']['history_sessions'] == 20 and table['common']['price_date'] == '2026-10-12'


def test_disposition_periods_cover_the_entry_day():
    assert L.C.roc_dates('115/10/08～115/10/15') == ['2026-10-08', '2026-10-15']
    assert L.C.roc_dates('1151008~1151019') == ['2026-10-08', '2026-10-19']

    class Resp:
        def __init__(self, rows):
            self.rows = rows

        def raise_for_status(self):
            pass

        def json(self):
            return self.rows

    def get(url, timeout):
        if 'twse' in url:
            return Resp([{'Code': '1709', 'DispositionPeriod': '115/10/08～115/10/15'},
                         {'Code': '1111', 'DispositionPeriod': '115/09/01～115/09/05'}])
        return Resp([{'SecuritiesCompanyCode': '3441', 'DispositionPeriod': '1151008~1151019'}])
    assert L.C.disposition_symbols('2026-10-13', get) == {'1709', '3441'}

    def broken(url, timeout):
        raise L.C.requests.ConnectionError()
    assert L.C.disposition_symbols('2026-10-13', broken) is None


def test_prompt_files_render():
    for _, path, _ in L.ALL_VARIANTS.values():
        text = path.read_text(encoding='utf-8').format(date='2026-10-12', time='08:00', prev_session='2026-10-08',
                                                       entry_session='2026-10-12', cutoff_time='2026-10-12 08:00',
                                                       candidates_json='{"fields":[],"rows":[]}')
        assert '2026-10-12' in text and '2026-10-08' in text and '{"picks"' in text and '{date}' not in text and '{{' not in text


def test_names_come_from_exchange_quote_apis(tmp_path):
    class Resp:
        def __init__(self, rows):
            self.rows = rows

        def raise_for_status(self):
            pass

        def json(self):
            return self.rows

    def get(url, timeout):
        if 'twse' in url:
            return Resp([{'Code': '2303', 'Name': '聯電'}])
        raise L.C.requests.ConnectionError()                      # TPEx down: keep what we have
    assert L.C.load_names(tmp_path / 'missing.sqlite', get) == {'2303': '聯電'}
