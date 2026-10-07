"""Amendment 1: 2026-10-06 is carved out of the reserved future-confirmation partition."""
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
RESERVED = 'PHASE2C_FUTURE_CONFIRMATION_60D'


def load(path):
    return yaml.safe_load((GOV / path).read_text(encoding='utf-8'))


def test_registry_carves_out_the_inspected_day_and_keeps_the_rest_reserved():
    reg = DatasetRegistry(REGISTRY)
    reserved, excluded = reg.get(RESERVED), reg.get(EXCLUDED)
    assert reserved['canonical_status'] == 'RESERVED_UNTOUCHED'
    assert reserved['excluded_dates'] == ['2026-10-06']
    assert excluded['canonical_status'] == 'EXCLUDED_FROM_RESERVED_PARTITION'
    assert excluded['start_date'] == excluded['end_date'] == '2026-10-06'
    assert RESERVED in excluded['parent_dataset_ids']


def test_holdout_record_lists_the_same_exclusion_and_stays_pristine():
    h = load('holdouts/PHASE2C_FUTURE_60D_HOLDOUT.yaml')
    ex = h['partition_definition']['excluded_dates']
    assert [e['date'] for e in ex] == ['2026-10-06']
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
    assert event['governance']['pristine_after'] is False
    assert event['exposure_level'] != 'LEVEL_0_UNTOUCHED'


def test_governance_validators_accept_the_amendment():
    ok, results = validate_all_holdouts(REGISTRY, str(GOV / 'holdouts'))
    assert ok, results
    ok, results = validate_consumption(REGISTRY, str(GOV / 'oos_consumption'))
    assert ok, results
