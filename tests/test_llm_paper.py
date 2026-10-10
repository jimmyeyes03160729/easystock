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


def test_groups_consensus_majority_and_baselines():
    picks = {'openai': ['2001', '2002', '2003'], 'claude': ['2002', '2001', '2004'], 'gemini': ['2002', '2005']}
    g = L.build_groups(picks, UNIVERSE, '2026-10-13')
    assert g['consensus3'] == ['2002']
    assert g['majority2'] == ['2001', '2002']
    assert g['hot10'] == ['%04d' % (2019 - i) for i in range(10)]
    assert len(g['random5']) == 5 and all(UNIVERSE[s][1] >= L.MIN_AMOUNT for s in g['random5'])
    assert g['random5'] == L.build_groups(picks, UNIVERSE, '2026-10-13')['random5']     # fixed per day
    two = L.build_groups({'openai': ['2002'], 'claude': ['2002']}, UNIVERSE, '2026-10-13')
    assert two['consensus3'] == [] and two['majority2'] == ['2002'] and two['gemini'] == []


def bar(o, c, ref=None):
    return {'open': o, 'close': c, 'reference': ref or o}


def test_evaluate_holds_five_sessions_and_unfilled_limit_up_stays_cash():
    days = ['2026-10-13', '2026-10-14', '2026-10-15', '2026-10-16', '2026-10-19']
    bars = {'2001': {d: bar(100, 100 + 2 * i) for i, d in enumerate(days)},
            '2002': {days[0]: bar(110, 110, ref=100)}}                  # opens at the 10% limit: not fillable
    batch = {'day': days[0], 'groups': {'openai': ['2001', '2002']}}
    closed = lambda d: False  # noqa: E731
    e = L.evaluate(batch, days, bars, {}, closed)
    assert e['status'] == 'closed' and e['exit_day'] == '2026-10-19'
    g = e['groups']['openai']
    assert g['unfilled'] == ['2002'] and g['n_filled'] == 1
    assert 3.3 < g['net_pct'] < 3.8            # (+8% - costs) / 2 names
    assert g['day1_net_pct'] < 0               # flat day: only costs
    assert L.evaluate(batch, days[:3], bars, {}, closed)['status'] == 'holding'
    assert L.evaluate(batch, ['2026-10-08'], bars, {}, closed)['status'] == 'waiting_entry'
    assert L.evaluate(dict(batch, late=True), days, bars, {}, closed)['status'] == 'void_late'
    s = L.summarize([e])
    assert s['closed_batches'] == 1 and s['groups']['openai']['wins'] == 1
    assert s['groups']['claude']['batches'] == 0


def test_pick_freezes_once_and_records_failures(tmp_path, monkeypatch):
    import sqlite3
    db = tmp_path / 'daily.sqlite'
    con = sqlite3.connect(db)
    con.executescript("CREATE TABLE sessions(day, exchange, status); CREATE TABLE bars(symbol, day, close, amount);"
                      "INSERT INTO sessions VALUES('2026-10-12','TWSE','open');")
    con.executemany('INSERT INTO bars VALUES(?,?,?,?)', [(s, '2026-10-12', c, a) for s, (c, a) in UNIVERSE.items()])
    con.commit()
    con.close()
    monkeypatch.setattr(L, 'OUT_DIR', tmp_path)
    monkeypatch.setattr(L, 'DAILY_DB', str(db))
    reply = '{"picks": [{"symbol": "2001"}, {"symbol": "2002"}]}'
    monkeypatch.setattr(L, 'PROVIDERS', {'openai': (lambda p: (reply, {}), ('X',)),
                                         'claude': (lambda p: (reply, {}), ('X',)),
                                         'gemini': (lambda p: 1 / 0, ('X',))})
    monkeypatch.setattr(L, 'env', lambda *k, default='': 'k')
    now = datetime(2026, 10, 13, 8, 0, tzinfo=L.TPE)
    assert L.pick(now, clock=lambda: now.replace(minute=6)) == 0
    data = json.loads((tmp_path / 'picks_2026-10-13.json').read_text(encoding='utf-8'))
    assert data['prev_session'] == '2026-10-12' and not data['late']
    assert data['groups']['majority2'] == ['2001', '2002'] and data['groups']['consensus3'] == []
    assert data['replies']['gemini']['ok'] is False
    assert (tmp_path / 'picks.sha256').read_text().count('picks_2026-10-13.json') == 1
    assert L.pick(now) == 0                                                           # already frozen: untouched
    assert L.pick(datetime(2026, 10, 14, 9, 30, tzinfo=L.TPE)) == 1                   # too late
