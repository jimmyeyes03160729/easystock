import json
import sqlite3
from datetime import datetime
import pytest
from eight_methods import rules as R, feed as F

def now(clock):
    return R.stamp('2026-10-13T' + clock + '+08:00')

def quotes(pattern):
    price, out = 100, []
    for clock, d in zip(['09:05:00', '09:10:00', '09:15:00'], pattern):
        price += 1 if d == 'U' else -1
        out.append({'price': price, 'quote_at': now(clock).isoformat()})
    return out

@pytest.mark.parametrize('method,pattern', list(enumerate(['UUU','UUD','UDD','DUU','DDU','DDD','DUD','UDU'], 1)))
def test_reference_number_and_three_raw_comparisons(method, pattern):
    r = R.opening(100, quotes(pattern), now('09:15:00'))
    assert r['method'] == method and ''.join(r['directions']) == pattern
    assert r['prices'][0] == 100

def test_opening_time_boundary_flat_missing_stale_future():
    q = quotes('UUU')
    assert R.opening(100, q, now('09:14:59'))['status'] == 'pending'
    assert R.opening(100, q, now('09:15:00'))['method'] == 1
    assert R.opening(None, q, now('09:15:00'))['method'] is None
    assert R.opening(100, q[:2], now('09:15:00'))['method'] is None
    q[2]['price'] = q[1]['price']
    assert R.opening(100, q, now('09:15:00'))['reason'] == '平盤，未分類'
    for at in ['09:14:29','09:15:01']:
        q = quotes('UUU');q[2]['quote_at'] = now(at).isoformat()
        assert R.opening(100, q, now('09:15:30'))['method'] is None
    q = quotes('UUU');q[2]['available_at'] = now('09:15:01').isoformat()
    assert R.opening(100, q, now('09:15:00'))['method'] is None

def complete_row():
    return {'price': 104, 'previous_close':100, 'quote_at':now('13:10:00').isoformat(),
            'day_volume':200, 'past_volumes':[100]*5, 'past_closes':list(range(40,101)),
            'turnover_pct':5, 'market_cap':10e9, 'cap_currency':'TWD', 'benchmark_gain_pct':1, 'day_high':105}

def test_all_eight_conditions_pass_fail_and_insufficient():
    row = complete_row()
    result = R.closing(row, now('13:10:00'))
    assert result['passed'] == 8 and result['complete']
    fields = [('price',110),('day_volume',50),('turnover_pct',1),('market_cap',1e9),
              ('past_volumes',[100]*4+[300]),('past_closes',[200]*61),('benchmark_gain_pct',5),('day_high',120)]
    for i, (field, value) in enumerate(fields):
        assert R.closing(dict(row, **{field:value}), now('13:10:00'))['conditions'][i]['state'] == 'fail'
        missing = dict(row);missing.pop(field)
        assert R.closing(missing, now('13:10:00'))['conditions'][i]['state'] == 'insufficient'
    assert R.closing(dict(row,cap_currency='CNY'),now('13:10:00'))['conditions'][3]['state']=='insufficient'
    assert R.RULESETS['CN_ORIGINAL_V1']['turnover'] == [5,10]
    with pytest.raises(ValueError): R.closing(row,now('13:10:00'),'CN_ORIGINAL_V1')

@pytest.mark.parametrize('clock,phase', [('12:59:59','waiting'),('13:00:00','observing'),('13:24:59','observing'),('13:25:00','auction'),('13:29:59','auction'),('13:30:00','ended')])
def test_closing_session_boundaries(clock,phase):
    r=R.closing(dict(complete_row(),quote_at=now(clock).isoformat()), now(clock))
    assert r['phase']==phase
    assert r['passed']==(8 if phase=='observing' else 0)

@pytest.mark.parametrize('clock', ['13:09:29','13:10:01','12:59:00'])
def test_closing_stale_future_quotes(clock):
    result=R.closing(dict(complete_row(),quote_at=now(clock).isoformat()),now('13:10:00'))
    assert result['passed']==0 and not result['complete']

def test_real_journal_adapter_and_read_only_daily(tmp_path):
    journal=tmp_path/'journal.jsonl'
    records=[{'kind':'sample','recorded_at':q['quote_at'],'data':dict(q,symbol='2330',name='台積電',observed_at=q['quote_at'])} for q in quotes('UUU')]
    records.append({'kind':'sample','recorded_at':now('13:10:01').isoformat(),'data':dict(complete_row(),symbol='9999',observed_at=now('13:10:01').isoformat())})
    journal.write_text('\n'.join(json.dumps(r) for r in records)+'\ninvalid\n',encoding='utf-8')
    rows,diagnostics=F.read_journal(journal,now('13:10:00'))
    assert list(rows)==['2330'] and diagnostics
    path=tmp_path/'daily.sqlite';db=sqlite3.connect(path)
    db.executescript('CREATE TABLE bars(symbol,day,close,volume,exchange);CREATE TABLE sessions(day,exchange,status);')
    db.execute('INSERT INTO bars VALUES(?,?,?,?,?)',('2330','2026-10-12',100,500,'TWSE'))
    db.execute('INSERT INTO sessions VALUES(?,?,?)',('2026-10-12','TWSE','open'));db.commit();db.close()
    before=path.read_bytes(); assert not F.enrich_daily(rows,path,now('13:10:00'));assert path.read_bytes()==before
    feeds=F.build(rows,now('13:10:00'))
    assert set(feeds)=={'opening_eight','closing_eight'}
    assert feeds['opening_eight']['rows'][0]['method']==1
    assert len(feeds['opening_eight']['markets'])==2
    assert feeds['closing_eight']['rows'][0]['passed']==0  # stale quote
