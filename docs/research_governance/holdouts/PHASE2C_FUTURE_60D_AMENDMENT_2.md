# Amendment 2 — Phase 2C future 60-day partition (2026-10-08)

Holdout: `PHASE2C_FUTURE_60D`. Authorised by the owner on 2026-10-08 (incident option 1,
`incidents/2026-10-08_REBOUND_BUILD_RESERVED_DAYS_AGGREGATE.md`).

## Change

- **2026-10-05 is excluded from the 60-day count.** The exclusion list is now 2026-10-05 and 2026-10-06; the
  partition remains "the first 60 eligible trading days from 2026-10-05, skipping the documented exclusion list",
  so its first counted day is the first eligible session after 2026-10-06.
- The day is recorded as its own dataset `LIVE_LEARNING_20261005_EXCLUDED_DAY`
  (`canonical_status: EXCLUDED_FROM_RESERVED_PARTITION`, parent `PHASE2C_FUTURE_CONFIRMATION_60D`)
  and its exposure in `oos_consumption/PHASE2C_FUTURE_PARTITION_EXCLUDED_DAY_20261005.yaml`.
- Holdout record: `partition_definition.excluded_dates` gains 2026-10-05 with `amendment: AMENDMENT_2_20261008`.

## Why this is not outcome-dependent skipping

The only reason is that the day entered whole-period aggregate counts the assistant read while building rebound
Dataset v2 (candidate counts per kind, bar counts) and an undated v1 rule-candidate count. No price, label, return or
candidate of the day was viewed, and the choice is date-based and made before any result of the partition is known.

## Unchanged

- `PHASE2C_F01_FUTURE_CONFIRMATION_CONTRACT.yaml`, `expected_start_date`, `RESERVED_UNTOUCHED` status, the
  reservation event and every other reserved day.
- Safeguards: rebound v1 nightly output and audit are blinded from 2026-10-05, rebound v2 from 2026-10-07.
