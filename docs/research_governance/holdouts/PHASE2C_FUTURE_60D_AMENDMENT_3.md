# Amendment 3 — Phase 2C future 60-day partition (2026-10-08)

Holdout: `PHASE2C_FUTURE_60D`. Authorised by the owner on 2026-10-08 (incident option 1,
`incidents/2026-10-08_RUNWAY_B_RESERVED_DAYS_BACKTEST.md`).

## Change

- **2026-10-07 and 2026-10-08 are excluded from the 60-day count.** The exclusion list is now 2026-10-05 through
  2026-10-08; the partition remains "the first 60 eligible trading days from 2026-10-05, skipping the documented
  exclusion list", so its first counted day is the first eligible session after 2026-10-08 (2026-10-12 if the
  calendar holds).
- The two days are recorded as one dataset `LIVE_LEARNING_20261007_08_EXCLUDED_DAYS`
  (`canonical_status: EXCLUDED_FROM_RESERVED_PARTITION`, parent `PHASE2C_FUTURE_CONFIRMATION_60D`)
  and their exposure in `oos_consumption/PHASE2C_FUTURE_PARTITION_EXCLUDED_DAYS_20261007_08.yaml`.
- Holdout record: `partition_definition.excluded_dates` gains both days with `amendment: AMENDMENT_3_20261008`.

## Why this is not outcome-dependent skipping

The reason is the access: runway B's backtests, its parameter grid and its one-month study computed trade results on
both days, and B's committed parameters came from those studies. The choice is date-based and made before any result
of the remaining partition is known; no one has evaluated a partition hypothesis.

## Condition attached by the owner (part of option 1)

Research backtests, parameter searches and studies of any lane (runway A, runway B, event audits) read only days
<= 2026-10-02 until this partition is consumed or released. Live paper operation of runway A and runway B, their
ledgers and the 13:50 summary continue unchanged and are treated as operational, as before the holdout existed.
A research read of any day >= 2026-10-12 inside the partition is a new incident.

## Unchanged

- `PHASE2C_F01_FUTURE_CONFIRMATION_CONTRACT.yaml`, `expected_start_date`, `RESERVED_UNTOUCHED` status, the
  reservation event and every other reserved day.
