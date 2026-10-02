from copy import deepcopy
from datetime import date,datetime,timedelta
import gzip
import json

import pytest

from rebound_learning.backfill import archive_to_daily,run
from rebound_learning.labels import update_labels
from rebound_learning.schema import connect,save_candidate,stable_json
from rebound_learning_fixture import bars


def test_archive_minute_k_aggregates_as_daily(tmp_path):
    source=tmp_path/'2026-09-29'/'2330.json.gz';source.parent.mkdir()
    ts=[int((datetime(2026,9,29,h,minute)-datetime(1970,1,1)).total_seconds()*1e9)
        for h,minute in ((9,1),(9,2),(14,30))]
    obj={'symbol':'2330','date':'2026-09-29','kbars':{
        'ts':ts,'Open':[100,101,200],'High':[102,103,210],'Low':[99,100,190],
        'Close':[101,102,205],'Volume':[1000,2000,5000],'Amount':[100000,200000,1000000]}}
    with gzip.open(source,'wt',encoding='utf-8') as output:json.dump(obj,output)
    symbol,bar=archive_to_daily(source)
    assert symbol=='2330'
    assert (bar['open'],bar['high'],bar['low'],bar['close'])==(100,103,99,102)
    assert bar['volume']==3000 and bar['amount']==300000


def test_backfill_idempotent_future_independent_and_version_isolated(tmp_path):
    source=bars();day=source[-1]['time']
    future={'time':(date.fromisoformat(day)+timedelta(days=1)).isoformat(),
            'open':10.5,'high':11,'low':10,'close':10.8,'volume':100,'amount':10_000_000}
    path=tmp_path/'db.sqlite'
    with connect(path) as db:
        run(db,{'2330':source+[future]},[day])
        first=db.execute('SELECT snapshot FROM candidates').fetchone()[0]
        run(db,{'2330':source+[future]},[day])
        assert db.execute('SELECT COUNT(*) FROM candidates').fetchone()[0]==1
        assert db.execute('SELECT COUNT(*) FROM scan_days').fetchone()[0]==1
        snapshot=json.loads(first)
        variant={**snapshot,'strategy_version':'range-rebound-0.4'}
        save_candidate(db,variant)
        assert db.execute('SELECT COUNT(DISTINCT strategy_version) FROM candidates').fetchone()[0]==2
    changed=deepcopy(future);changed.update(high=20,low=8,close=12)
    with connect(tmp_path/'other.sqlite') as db:
        run(db,{'2330':source+[changed]},[day])
        assert db.execute('SELECT snapshot FROM candidates').fetchone()[0]==first


def test_labels_are_stored_separately_from_candidate_snapshot(tmp_path):
    source=bars();day=source[-1]['time']; future=[]; next_day=date.fromisoformat(day)+timedelta(days=1)
    while len(future)<20:
        if next_day.weekday()<5:
            future.append({'time':next_day.isoformat(),'open':10.5,'high':10.6,'low':10.4,
                           'close':10.5,'volume':100,'amount':10_000_000})
        next_day+=timedelta(days=1)
    with connect(tmp_path/'db.sqlite') as db:
        run(db,{'2330':source+future},[day])
        before=db.execute('SELECT snapshot FROM candidates').fetchone()[0]
        assert update_labels(db)==1
        after=db.execute('SELECT snapshot,label FROM candidates').fetchone()
        assert before==after['snapshot'] and after['label']
        assert update_labels(db)==0


def test_snapshot_correction_is_not_silent(tmp_path):
    source=bars();day=source[-1]['time']
    with connect(tmp_path/'db.sqlite') as db:
        run(db,{'2330':source},[day])
        changed=deepcopy(source);changed[-1]['amount']+=1
        with pytest.raises(ValueError,match='bar_changed'):
            run(db,{'2330':changed},[day])


def test_expanding_archive_coverage_preserves_snapshot_and_label(tmp_path):
    source=bars();day=source[-1]['time']
    extra=deepcopy(source)
    for bar in extra:
        bar['amount']*=2
    with connect(tmp_path/'db.sqlite') as db:
        run(db,{'2330':source},[day])
        before=db.execute('SELECT id,snapshot FROM candidates').fetchone()
        db.execute('UPDATE candidates SET label=? WHERE id=?', ('{"sentinel":true}',before['id']))
        db.commit()
        result=run(db,{'2330':source,'2615':extra},[day])
        after=db.execute('SELECT snapshot,label FROM candidates WHERE id=?',(before['id'],)).fetchone()
        assert after['snapshot']==before['snapshot']
        assert after['label']=='{"sentinel":true}'
        assert result['candidate_snapshots_reused']==1
        assert result['candidate_events']==1
        assert db.execute('SELECT symbols_scanned FROM scan_days WHERE day=?',(day,)).fetchone()[0]==2
        changed=json.loads(before['snapshot'])
        changed['features']['amount_rank']=0.5
        with pytest.raises(ValueError,match='candidate_snapshot_changed'):
            save_candidate(db,changed)
