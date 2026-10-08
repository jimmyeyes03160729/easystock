"""Blinded eligible-day counter for the Phase 2C future holdout (metadata only, Amendment 1 exclusion)."""
import datetime
import gzip
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from daytrade_learning.research_governance.holdout_day_counter import (
    archive_checks, count_eligible_days, load_holdout, trading_days)

OK = {'partition_exists': True, 'ingestion_success': True, 'schema_valid': True, 'checksum_valid': True}


def test_trading_days_skip_weekends_and_closures():
    days = trading_days(datetime.date(2026, 10, 5), datetime.date(2026, 10, 12), {'2026-10-09'})
    assert days == ['2026-10-05', '2026-10-06', '2026-10-07', '2026-10-08', '2026-10-12']


def test_documented_exclusion_is_skipped_and_counting_continues():
    days = ['2026-10-05', '2026-10-06', '2026-10-07', '2026-10-08']
    res = count_eligible_days(days, {d: OK for d in days}, ['2026-10-06'], '2026-10-05', target=3)
    assert res['collected_eligible_trading_days'] == ['2026-10-05', '2026-10-07', '2026-10-08']
    assert res['skipped'] == [{'day': '2026-10-06', 'reasons': ['documented_exclusion']}]
    assert res['complete'] and res['holdout_end_date'] == '2026-10-08'


def test_failed_metadata_check_skips_the_day_with_reasons():
    days = ['2026-10-05', '2026-10-07']
    checks = {'2026-10-05': dict(OK, checksum_valid=False), '2026-10-07': OK}
    res = count_eligible_days(days, checks, [], '2026-10-05', target=60)
    assert res['collected_eligible_trading_days'] == ['2026-10-07']
    assert res['skipped'] == [{'day': '2026-10-05', 'reasons': ['checksum_valid']}]
    assert not res['complete'] and res['holdout_end_date'] is None


def test_missing_check_record_is_not_eligible_and_days_before_start_ignored():
    res = count_eligible_days(['2026-10-02', '2026-10-05'], {}, [], '2026-10-05')
    assert res['eligible_days_collected'] == 0
    assert res['skipped'] == [{'day': '2026-10-05', 'reasons': list(OK)}]


def test_counting_stops_at_target():
    days = ['2026-10-%02d' % d for d in range(5, 20)]
    res = count_eligible_days(days, {d: OK for d in days}, [], '2026-10-05', target=4)
    assert res['collected_eligible_trading_days'] == days[:4]


def test_real_holdout_record_carries_the_amendment_exclusions():
    h = load_holdout(ROOT / 'docs/research_governance/holdouts/PHASE2C_FUTURE_60D_HOLDOUT.yaml')
    assert h['start_date'] == '2026-10-05' and h['target'] == 60
    assert {'2026-10-06', '2026-10-05'} <= set(h['excluded_dates'])     # Amendments 1 and 2


def test_both_amendment_days_are_skipped_before_counting():
    days = ['2026-10-05', '2026-10-06', '2026-10-07', '2026-10-08']
    res = count_eligible_days(days, {d: OK for d in days}, ['2026-10-06', '2026-10-05'], '2026-10-05', target=2)
    assert res['collected_eligible_trading_days'] == ['2026-10-07', '2026-10-08']
    assert [s['day'] for s in res['skipped']] == ['2026-10-05', '2026-10-06']


def test_archive_checks_use_file_metadata_only(tmp_path):
    day = tmp_path / '2026-10-07'
    day.mkdir()
    for s in ('2330', '1101'):
        with gzip.open(day / (s + '.json.gz'), 'wb') as f:
            f.write(b'{}')
    assert archive_checks(day, expected_files=2) == OK
    assert archive_checks(day, expected_files=3)['ingestion_success'] is False
    (day / 'broken.json.gz').write_bytes(b'not gzip')
    c = archive_checks(day, expected_files=2)
    assert c['schema_valid'] is False and c['checksum_valid'] is False
    assert archive_checks(tmp_path / 'missing', 1)['partition_exists'] is False
