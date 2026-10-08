import json

from rebound_learning.audit import build_audit
from rebound_learning.backfill import run
from rebound_learning.schema import connect,stable_json
from rebound_learning_fixture import bars


def test_valid_dataset_audit_and_missing_coverage(tmp_path):
    source=bars();day=source[-1]['time']
    with connect(tmp_path/'db.sqlite') as db:
        run(db,{'2330':source},[day])
        report=build_audit(db)
    assert report['data_quality']['critical_count']==0
    assert report['total_rows']==1 and report['candidate_kinds']['PENDING']==1
    assert report['coverage']['financial_pit_candidate_ratio']==0
    assert report['coverage']['historical_market_context_ratio']==0
    assert 'historical_financial_point_in_time_unavailable' in report['data_quality']['warnings']
    assert report['missing_feature_rate']['amount_rank']==0


def test_invalid_ohlc_and_future_timestamp_are_critical(tmp_path):
    source=bars();day=source[-1]['time']
    with connect(tmp_path/'db.sqlite') as db:
        run(db,{'2330':source},[day])
        row=db.execute('SELECT id,snapshot FROM candidates').fetchone()
        snapshot=json.loads(row['snapshot']);snapshot['signal_available_at']='2027-01-01T13:30:00+08:00'
        db.execute('UPDATE candidates SET snapshot=? WHERE id=?',(stable_json(snapshot),row['id']))
        bar=db.execute('SELECT bar FROM daily_bars WHERE symbol=? AND day=?',('2330',day)).fetchone()[0]
        bad=json.loads(bar);bad['high']=bad['low']-1
        db.execute('UPDATE daily_bars SET bar=? WHERE symbol=? AND day=?',(stable_json(bad),'2330',day))
        report=build_audit(db)
    assert report['data_quality']['critical_count']>=2
    assert any('bad_ohlc' in x for x in report['data_quality']['critical_examples'])
    assert report['data_quality']['future_leakage_violations']>=1


def test_duplicate_identity_detected_by_database_guard(tmp_path):
    source=bars();day=source[-1]['time']
    with connect(tmp_path/'db.sqlite') as db:
        run(db,{'2330':source},[day])
        row=db.execute('SELECT * FROM candidates').fetchone()
        try:
            db.execute('INSERT INTO candidates VALUES (?,?,?,?,?,?,?,?)',tuple(row))
        except Exception as exc:
            assert 'UNIQUE' in str(exc)
        else:
            raise AssertionError('database accepted a duplicate ID')


def test_before_bound_hides_reserved_scan_metadata(tmp_path):
    source=bars();day=source[-1]['time']
    with connect(tmp_path/'db.sqlite') as db:
        run(db,{'2330':source},[day])
        full=build_audit(db)
        blinded=build_audit(db,before=day)
    assert full['scan_last_date']==day and full['trading_days_scanned']==1
    assert blinded['scan_last_date'] is None and blinded['trading_days_scanned']==0
    assert blinded['stock_days_scanned']==0 and blinded['symbols_scanned']==0
    assert blinded['coverage']['kline_bar_count']<full['coverage']['kline_bar_count']
