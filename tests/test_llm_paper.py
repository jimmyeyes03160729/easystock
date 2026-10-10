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


def test_pick_freezes_once_and_records_failures(tmp_path, monkeypatch):
    import sqlite3
    db = tmp_path / 'daily.sqlite'
    con = sqlite3.connect(db)
    con.executescript("CREATE TABLE sessions(day, exchange, status); CREATE TABLE bars(symbol, day, close, amount);"
                      "INSERT INTO sessions VALUES('2026-10-12','TWSE','open');")
    con.executemany('INSERT INTO bars VALUES(?,?,?,?)', [(s, '2026-10-12', c, a) for s, (c, a) in UNIVERSE.items()]
                    + [('2050', '2026-10-12', 350.0, 900_000_000)])                  # liquid but above 200
    con.commit()
    con.close()
    monkeypatch.setattr(L, 'OUT_DIR', tmp_path)
    monkeypatch.setattr(L, 'VARIANTS', tuple(L.ALL_VARIANTS.values()))           # both prompts
    monkeypatch.setattr(L, 'DAILY_DB', str(db))
    reply = '{"picks": [{"symbol": "2001"}, {"symbol": "2002"}]}'
    calls = []

    def fake(p):
        calls.append(p)
        return reply if '200 元' not in p else '{"picks": [{"symbol": "2050"}, {"symbol": "2003"}]}', {}
    monkeypatch.setattr(L, 'PROVIDERS', {'openai': (fake, ('X',)),
                                         'claude': (fake, ('X',)),
                                         'gemini': (lambda p: 1 / 0, ('X',))})
    monkeypatch.setattr(L, 'env', lambda *k, default='': 'k')
    now = datetime(2026, 10, 13, 8, 0, tzinfo=L.TPE)
    assert L.pick(now, clock=lambda: now.replace(minute=6)) == 0
    data = json.loads((tmp_path / 'picks_2026-10-13.json').read_text(encoding='utf-8'))
    assert data['prev_session'] == '2026-10-12' and not data['late']
    assert len(calls) == 4                                                            # 2 prompts x 2 models
    assert data['groups']['consensus'] == ['2001', '2002'] and 'gemini' not in data['replies']
    assert data['groups']['p200_consensus'] == ['2003'] and data['invalid']['p200_openai'] == ['2050']
    assert data['groups']['hot10'][0] == '2050' and '2050' not in data['groups']['p200_hot10']
    assert set(data['prompts']) == {'main', 'p200'}
    assert (tmp_path / 'picks.sha256').read_text().count('picks_2026-10-13.json') == 1
    assert L.pick(now) == 0                                                           # already frozen: untouched
    assert L.pick(datetime(2026, 10, 14, 9, 30, tzinfo=L.TPE)) == 1                   # too late


def test_prompt_files_render():
    for _, path, _ in L.ALL_VARIANTS.values():
        text = path.read_text(encoding='utf-8').format(date='2026-10-12', time='08:00', prev_session='2026-10-08')
        assert '2026-10-12' in text and '2026-10-08' in text and '{"picks"' in text and '{date}' not in text and '{{' not in text
