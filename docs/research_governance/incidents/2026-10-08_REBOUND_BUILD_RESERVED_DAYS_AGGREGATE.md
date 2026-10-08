# Incident record — reserved intraday sessions inside rebound whole-period aggregates (2026-10-08)

- Holdout: `PHASE2C_FUTURE_60D` (dataset `PHASE2C_FUTURE_CONFIRMATION_60D`, first 60 eligible trading days from
  2026-10-05; 2026-10-06 already excluded by Amendment 1)
- Recorded: 2026-10-08 (append-only; holdout, registry and reservation records are intentionally unchanged)
- Decision status: **RESOLVED — owner chose option 1 (carve-out of 2026-10-05) on 2026-10-08**; see
  `holdouts/PHASE2C_FUTURE_60D_AMENDMENT_2.md`, the registry dataset `LIVE_LEARNING_20261005_EXCLUDED_DAY` and
  `oos_consumption/PHASE2C_FUTURE_PARTITION_EXCLUDED_DAY_20261005.yaml`

## What happened

Two numbers the assistant read while building and checking rebound Dataset v2 were computed over periods that
include 2026-10-05 (and the already excluded 2026-10-06):

| read | content seen | reserved-day share |
| --- | --- | --- |
| Dataset v2 build and audit totals (official TWSE/TPEx daily lineage) | whole-period candidate counts per kind, total bars and sessions, "last session 2026-10-06" | 2 of 1,153 sessions |
| v1/v2 overlap check on `rebound/dataset.sqlite` (v1 replays the Shioaji minute archive, the lineage of the reserved partition) | count of v1 rule candidates with no date cutoff (152) and eight 2024 examples | unknown, at most a few of 152 |

No per-day price, label, return or candidate for 2026-10-05 was viewed. Labels for those signals cannot exist yet
(10-session horizon). The rebound nightly job (v1) has also been replaying archive days >= 2026-10-05 and writing
their counts to its audit file; the assistant has not read those reports since 2026-10-05.

## Assessment

The information about 2026-10-05 is diluted to near zero and touches no daytrade hypothesis. It is nevertheless
"row counts / activity statistics" over the reserved day, which the holdout policy lists as prohibited.

## Options (owner to choose)

1. **Carve out 2026-10-05** (recommended): Amendment 2 adds 2026-10-05 to the exclusion list, exactly like
   Amendment 1; the 60-day count starts at the next eligible day. Not outcome-dependent: the reason is the access.
2. **Accept as immaterial**: keep the reservation unchanged and rely on this note.
3. **Invalidate and re-reserve** the whole partition. Strictest; unnecessary for this exposure level.

## Changes already made (no owner decision needed)

- The rebound v1 nightly job now audits only signals before 2026-10-05 and prints only admin metadata
  (`v1_blinded_from` in `rebound_learning/settings.json`).
- The rebound v2 nightly job audits only signals before its own reserved start (2026-10-07) and prints only
  admin metadata.
