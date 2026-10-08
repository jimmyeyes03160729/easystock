# Incident record — runway B backtests computed results on reserved intraday sessions (2026-10-08)

- Holdout: `PHASE2C_FUTURE_60D` (dataset `PHASE2C_FUTURE_CONFIRMATION_60D`, first 60 eligible trading days from
  2026-10-05; 2026-10-05 and 2026-10-06 already excluded by Amendments 2 and 1)
- Recorded: 2026-10-08 (append-only; holdout, registry and reservation records are intentionally unchanged)
- Decision status: **RESOLVED — owner chose option 1 (carve-out of 2026-10-07/08 plus no research reads of days >= 2026-10-05) on 2026-10-08**; see
  `holdouts/PHASE2C_FUTURE_60D_AMENDMENT_3.md`, the registry dataset `LIVE_LEARNING_20261007_08_EXCLUDED_DAYS` and
  `oos_consumption/PHASE2C_FUTURE_PARTITION_EXCLUDED_DAYS_20261007_08.yaml`

## What happened

The runway B lane (`runway_v2/`, merged in PR #51 at 2026-10-08 19:31) was developed by another agent with
backtests that compute trade results on reserved sessions:

| source | dates | evidence |
| --- | --- | --- |
| `runway_v2/backtest.py` `run_10_days_backtest` default dates | 2026-09-22 .. 2026-10-08 (incl. 10-05, 10-06, **10-07, 10-08**) | committed code |
| `runway_v2/grid_search.py` `dates_10d` (parameter grid) | same ten dates | committed code |
| `runway_v2/optimize_study.py` `DATES_1M` (six exit/size configurations) | 2026-09-11 .. 2026-10-08 | committed code; VM output `runway_v2_1m_results.json` written 2026-10-08 19:09, its `dates` list contains 10-05..10-08 |
| `run_6m_study.py` (VM only, not in git) | archive days 2026-04-01 .. 2026-10-08 | VM output `runway_v2_6m_results.json` written 2026-10-08 22:08 |

The committed defaults in `runway_v2/config.py` match configurations from these studies, so the reserved days
2026-10-07 and 2026-10-08 influenced parameter selection, not only observation. The policy treats AI access to
outcomes as exposure (`PRISTINE_HOLDOUT_POLICY.md` section 5).

What this assistant read: the source code above, file names and modification times, and only the `dates` key of
the two VM result files. No B result, trade, PnL or summary from any date was read.

## Assessment

- 2026-10-07 and 2026-10-08 are exposed for intraday LONG momentum/breakout outcomes with parameter selection
  influenced. That is stronger than the 10-05/10-06 incidents (activity counts, a single price).
- Ongoing risk: the B lane keeps producing results on reserved days in two ways. (a) Its live paper ledger and the
  13:50 summary report daily results; runway A's live paper ledger already did this before the holdout was created,
  so live paper reporting is treated as operational, not research. (b) Further backtests or parameter studies over
  archive days >= 2026-10-05 would be research reads and would expose every later reserved day for this family.

## Options (owner to choose)

1. **Carve out 2026-10-07 and 2026-10-08** (recommended): Amendment 3 adds both days to the exclusion list, like
   Amendments 1 and 2; the 60-day count starts at the next eligible day (2026-10-12 if the calendar holds).
   Together with: research backtests of any lane read only days <= 2026-10-02 until the partition is consumed
   (live paper operation of A and B continues unchanged). Not outcome-dependent: the reason is the access.
2. **Invalidate the partition** and re-reserve a new one starting after a date the owner fixes. Needed if the B lane
   must keep backtesting on recent days.
3. **Accept as immaterial**: not recommended; two full sessions with parameter selection is not diluted.

## Consequence for open trials

- `TRIAL_EA_META_B_FILTER_V1` Stage 2 is blocked until option 1 (with the backtest restriction) or option 2 is
  recorded. Stage 1 does not touch the partition.
- `TRIAL_EA_HV60_V1` and the other event-audit trials read only days <= 2026-10-02 and are unaffected.
