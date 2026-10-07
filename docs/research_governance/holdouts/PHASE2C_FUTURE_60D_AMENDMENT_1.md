# Amendment 1 — Phase 2C future 60-day partition (2026-10-07)

Holdout: `PHASE2C_FUTURE_60D`. Authorised by the owner on 2026-10-07 (incident option 2).

## Change

- **2026-10-06 is excluded from the 60-day count.** The partition becomes "the first 60 eligible trading days
  from 2026-10-05, skipping the documented exclusion list" (currently only 2026-10-06).
- The day is recorded as its own dataset `LIVE_LEARNING_20261006_EXCLUDED_DAY`
  (`canonical_status: EXCLUDED_FROM_RESERVED_PARTITION`, parent `PHASE2C_FUTURE_CONFIRMATION_60D`)
  and its exposure is recorded in `oos_consumption/PHASE2C_FUTURE_PARTITION_EXCLUDED_DAY_20261006.yaml`.
- Holdout record: `partition_definition.excluded_dates` and the eligibility criterion
  `date_not_in_documented_exclusion_list == true`. `FIRST_60_ELIGIBLE_TRADING_DAYS` is unchanged.

## Why this is not outcome-dependent skipping

The only reason for the exclusion is that the day's content was read (one sample price, two simulation label rows).
It was chosen before any result for the day or for the remaining days was known, and the rule is date-based.
The exclusion list may only grow through a documented content-access incident, never because of what a day looks like.

## Unchanged

- `PHASE2C_F01_FUTURE_CONFIRMATION_CONTRACT.yaml` and its hash (referenced by the Phase 2C trial) are not edited.
- `RESERVED_UNTOUCHED` status, the reservation event and all other reserved days.
- Safeguard: content reads of live data are limited to dates `<= 2026-10-02`; later dates only by name and count.
