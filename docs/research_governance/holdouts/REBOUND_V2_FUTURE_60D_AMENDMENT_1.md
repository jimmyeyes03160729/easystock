# Amendment 1 — Rebound future 60-session partition (2026-10-08)

Holdout: `REBOUND_V2_FUTURE_60D`. Authorised by the owner on 2026-10-08 (option 1: carve out, do not invalidate).

## Change

- **Every weekday from 2026-10-13 to 2027-04-16 is excluded from the 60-session count.** The partition becomes
  "the first 60 eligible sessions from 2026-10-07, skipping the documented exclusion list": 2026-10-07, 2026-10-08 and
  2026-10-12 stay reserved, the count resumes after 2027-04-16.
- The span is recorded as the dataset `REBOUND_V2_DAILY_20261013_20270416_EXCLUDED_RANGE`
  (`canonical_status: EXCLUDED_FROM_RESERVED_PARTITION`, parent `REBOUND_V2_FUTURE_CONFIRMATION_60D`); the holdout
  record lists the dates in `partition_definition.excluded_dates` and the registry lists them on the reserved dataset.
- The planned exposure is recorded in `oos_consumption/REBOUND_V2_FUTURE_PARTITION_EXCLUDED_RANGE_20261013.yaml`.

## Why

`REVENUE_FORWARD_V1` (forward paper confirmation of `REVENUE_DRIFT_V1`, six monthly events on revenue months
2026-09..2027-02) must read daily open and close prices of its picked and scored stocks from the first entry session
(2026-10-13) until the last 20-session exit (about 2027-04-09). The reservation of `REBOUND_V2_FUTURE_60D` forbids
ohlcv values and returns for its sessions, so those sessions cannot stay pristine for rebound confirmation.

## Why this is not outcome-dependent skipping

The exclusion is a fixed calendar span set before any of those prices is read, chosen because a different preregistered
hypothesis needs them, not because of what the days look like. Weekdays are listed without consulting the trading
calendar (holidays are harmless). The exclusion list may only grow through a documented access need or incident.

## Unchanged

- `RESERVED_UNTOUCHED` status of the holdout and of 2026-10-07, 2026-10-08, 2026-10-12.
- Rebound code keeps blinding everything on or after `reserved_confirmation_start` (2026-10-07) - a superset of the
  governance reservation, so no rebound code change is required now. Whoever next preregisters a rebound confirmation
  must read the effective window from the holdout record (about 57 sessions after 2027-04-16).
- Phase 2C (intraday ticks, `PHASE2C_FUTURE_60D`) is a different dataset family and is untouched.

## Effect

`research/revenue_v1/EVAL_AUTHORIZED` may be created on the VM once this amendment is merged; until then
`rev_fwd.py evaluate` refuses to read prices.
