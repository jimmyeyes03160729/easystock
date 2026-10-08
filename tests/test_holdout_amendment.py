"""Amendments 1 and 2: 2026-10-06 and 2026-10-05 are carved out of the reserved future-confirmation partition."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import yaml

from daytrade_learning.research_governance.validate_oos_consumption import (
    DatasetRegistry, validate_all as validate_consumption)
from daytrade_learning.research_governance.validate_pristine_holdout import validate_all_holdouts

GOV = ROOT / 'docs' / 'research_governance'
REGISTRY = str(GOV / 'DATASET_REGISTRY_v1.yaml')
EXCLUDED = 'LIVE_LEARNING_20261006_EXCLUDED_DAY'
EXCLUDED_2 = 'LIVE_LEARNING_20261005_EXCLUDED_DAY'
RESERVED = 'PHASE2C_FUTURE_CONFIRMATION_60D'


def load(path):
    return yaml.safe_load((GOV / path).read_text(encoding='utf-8'))


def test_registry_carves_out_the_inspected_day_and_keeps_the_rest_reserved():
    reg = DatasetRegistry(REGISTRY)
    reserved = reg.get(RESERVED)
    assert reserved['canonical_status'] == 'RESERVED_UNTOUCHED'
    assert sorted(reserved['excluded_dates']) == ['2026-10-05', '2026-10-06']
    for name, day in ((EXCLUDED, '2026-10-06'), (EXCLUDED_2, '2026-10-05')):
        excluded = reg.get(name)
        assert excluded['canonical_status'] == 'EXCLUDED_FROM_RESERVED_PARTITION'
        assert excluded['start_date'] == excluded['end_date'] == day
        assert RESERVED in excluded['parent_dataset_ids']


def test_holdout_record_lists_the_same_exclusion_and_stays_pristine():
    h = load('holdouts/PHASE2C_FUTURE_60D_HOLDOUT.yaml')
    ex = h['partition_definition']['excluded_dates']
    assert sorted(e['date'] for e in ex) == ['2026-10-05', '2026-10-06']
    assert {e['amendment'] for e in ex} == {'AMENDMENT_1_20261007', 'AMENDMENT_2_20261008'}
    assert all(e['outcome_dependent'] is False for e in ex)
    assert h['partition_definition']['selection_rule'] == 'FIRST_60_ELIGIBLE_TRADING_DAYS'
    assert h['lifecycle']['status'] == 'RESERVED_UNTOUCHED'
    assert 'date_not_in_documented_exclusion_list == true' in h['eligibility_preregistration']['criteria']


def test_exposure_is_recorded_against_the_excluded_day_only():
    ledger = load('oos_consumption/PHASE2C_FUTURE_PARTITION_EXCLUDED_DAY_20261006.yaml')
    (event,) = ledger['consumption_events']
    assert event['dataset_id'] == EXCLUDED
    assert event['slice']['start_date'] == event['slice']['end_date'] == '2026-10-06'
    assert event['exposure']['labels_seen'] is True and event['exposure']['performance_seen'] is True
    assert event['governance']['independent_confirmation_eligible_after'] is False
    assert event['exposure_level'] != 'LEVEL_0_UNTOUCHED'


def test_amendment_2_exposure_is_recorded_against_2026_10_05_only():
    ledger = load('oos_consumption/PHASE2C_FUTURE_PARTITION_EXCLUDED_DAY_20261005.yaml')
    (event,) = ledger['consumption_events']
    assert event['dataset_id'] == EXCLUDED_2
    assert event['slice']['start_date'] == event['slice']['end_date'] == '2026-10-05'
    assert event['exposure']['performance_seen'] is False and event['exposure']['labels_seen'] is False
    assert event['exposure']['aggregate_metrics_seen'] is True
    assert event['governance']['independent_confirmation_eligible_after'] is False


def test_governance_validators_accept_the_amendment():
    ok, results = validate_all_holdouts(REGISTRY, str(GOV / 'holdouts'))
    assert ok, results
    ok, results = validate_consumption(REGISTRY, str(GOV / 'oos_consumption'))
    assert ok, results


REBOUND_RESERVED = 'REBOUND_V2_FUTURE_CONFIRMATION_60D'
REBOUND_RANGE = 'REBOUND_V2_DAILY_20261013_20270416_EXCLUDED_RANGE'


def test_rebound_amendment_1_carves_out_the_revenue_forward_span():
    reg = DatasetRegistry(REGISTRY)
    reserved = reg.get(REBOUND_RESERVED)
    assert reserved['canonical_status'] == 'RESERVED_UNTOUCHED'
    days = reserved['excluded_dates']
    assert days[0] == '2026-10-13' and days[-1] == '2027-04-16' and len(days) == len(set(days)) == 134
    assert not {'2026-10-07', '2026-10-08', '2026-10-12'} & set(days)
    rng = reg.get(REBOUND_RANGE)
    assert rng['canonical_status'] == 'EXCLUDED_FROM_RESERVED_PARTITION'
    assert (rng['start_date'], rng['end_date']) == ('2026-10-13', '2027-04-16')
    assert REBOUND_RESERVED in rng['parent_dataset_ids']
    h = load('holdouts/REBOUND_V2_FUTURE_60D_HOLDOUT.yaml')
    ex = h['partition_definition']['excluded_dates']
    assert [e['date'] for e in ex] == days
    assert all(e['outcome_dependent'] is False and e['dataset_id'] == REBOUND_RANGE for e in ex)
    assert h['lifecycle']['status'] == 'RESERVED_UNTOUCHED'


def test_rebound_amendment_1_exposure_is_planned_not_realised():
    (event,) = load('oos_consumption/REBOUND_V2_FUTURE_PARTITION_EXCLUDED_RANGE_20261013.yaml')['consumption_events']
    assert event['dataset_id'] == REBOUND_RANGE and event['trial_id'] == 'TRIAL_REVENUE_FORWARD_V1'
    assert event['exposure']['performance_seen'] is False and event['consumed_at'] is None
    assert event['governance']['independent_confirmation_eligible_after'] is False
