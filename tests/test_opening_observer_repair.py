from datetime import datetime,timedelta
import json
import pytest
from market_data.opening_observations import merge_indices,TPE
from daytrade_learning.runtime import Recorder


def test_index_snapshot_keeps_exchange_and_receipt_times(tmp_path):
    now=datetime(2026,10,14,9,15,tzinfo=TPE)
    p=tmp_path/'indices.jsonl';p.write_text(json.dumps({'received_at':now.isoformat(),'indices':{
        'taiex':{'quote_at':(now-timedelta(seconds=1)).isoformat(),'price':100},
        'otc':{'quote_at':(now+timedelta(seconds=1)).isoformat(),'price':200}}})+'\n')
    rows={};assert merge_indices(rows,p,now)==[]
    assert rows['IX0001']['quotes'][0]['available_at']==now.isoformat()
    assert 'IX0043' not in rows


def test_boundary_capture_uses_last_trade_before_boundary_once(monkeypatch,tmp_path):
    import daytrade_learning.runtime as runtime
    monkeypatch.setattr(runtime,'DATA',tmp_path);monkeypatch.setenv('LEARNING_ENABLED','1')
    r=Recorder();now=datetime(2026,10,14,9,5,tzinfo=TPE)+timedelta(milliseconds=100)
    ticks=[((now-timedelta(seconds=1)).timestamp(),1,1,100),(now.timestamp(),1,1,999)]
    try:
        for _ in range(2):r.sample('2330',now,ticks,{}, {'name':'test'},True,{})
    finally:r.close()
    rows=[json.loads(l) for l in (tmp_path/'journal-2026-10-14.jsonl').read_text().splitlines()]
    boundary=[r for r in rows if r['kind']=='opening_boundary']
    assert len(boundary)==1 and boundary[0]['data']['price']==100
    assert boundary[0]['data']['quote_at']<boundary[0]['data']['boundary_at']
