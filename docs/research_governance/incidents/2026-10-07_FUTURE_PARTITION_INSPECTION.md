# Incident record — inspection of the reserved future-confirmation partition (2026-10-07)

- Holdout: `PHASE2C_FUTURE_60D` (dataset `PHASE2C_FUTURE_CONFIRMATION_60D`, first 60 eligible trading days from 2026-10-05)
- Recorded: 2026-10-07 (append-only; the existing holdout, registry and reservation records are intentionally unchanged)
- Decision status: **RESOLVED — owner chose option 2 (carve-out of 2026-10-06) on 2026-10-07**; see
  `holdouts/PHASE2C_FUTURE_60D_AMENDMENT_1.md`, the registry dataset `LIVE_LEARNING_20261006_EXCLUDED_DAY` and
  `oos_consumption/PHASE2C_FUTURE_PARTITION_EXCLUDED_DAY_20261006.yaml`

## What happened

While auditing which live-pipeline files exist for later shadow evaluation, the assistant read content from the
live learning-data directory on the VM (`/home/ubuntu/easystock-learning-data`) for dates inside the reserved partition:

| read | date | content seen |
| --- | --- | --- |
| `journal-2026-10-06.jsonl`, first 900 characters | 2026-10-06 | one sample record: symbol 3189, 09:00:07, price 1105.0, no outcome |
| `journal-2026-10-06.jsonl` record-type counts; line counts of the 10-06 and 10-07 journals | 2026-10-06 / 10-07 | counts only (sample/health), no prices beyond the record above |
| `labels/2026-10-06.json`, first 600 characters | 2026-10-06 | two simulation label rows; one shows a net return of about -1.50% (symbol 6116), the second is truncated |
| directory listings / file counts of `bars/`, `labels/`, history archive | 10-05 .. 10-07 | names and counts only (metadata) |

No other content from 2026-10-05 or later was read. Every research audit in this session (H2, H3, H4, source-primitive
batch, base-rate) filtered archive days to `<= 2026-10-02` and read nothing later.

## Assessment

- Information content is tiny (one price, one loss figure) and nothing was used to choose, tune or reject any hypothesis.
- It is nevertheless an outcome-bearing read of the reserved partition: the holdout contract prohibits querying
  labels / returns / pnl / OHLCV values (`prohibited_queries`), and the record claims `performance_seen: false`.
- The governance validators cannot represent this honestly while the partition stays reserved: an OOS-consumption event
  against a dataset whose registry status is `RESERVED_UNTOUCHED` must be LEVEL_0, and the holdout validator forbids
  `performance_seen: true` while the lifecycle state is pristine. Recording the exposure formally therefore requires
  changing the holdout/dataset status, which is an owner decision rather than a bookkeeping edit.

## Options (owner to choose)

1. **Invalidate and re-reserve**: move `PHASE2C_FUTURE_60D` to `INVALIDATED`, change the registry status, record a
   consumption event for 2026-10-06, and reserve a new 60-day partition starting with the first eligible day after the
   decision (the 2026-10-05..07 days are then no longer part of a pristine confirmation set). Strictest; costs about three days.
2. **Accept with a documented carve-out**: amend the contract so that 2026-10-06 is excluded from the 60-day count
   (not outcome-dependent: the reason is a read, not a result), and keep the remaining days reserved.
3. **Accept as immaterial**: keep the reservation unchanged and rely on this note. Weakest; the records then disagree
   with this incident.

## Safeguard going forward

Content reads of live learning data (`journal-*`, `labels/`, `bars/`, `decision-ticks/`, archive day directories) are
limited to dates `<= 2026-10-02`; later dates are inspected by file name and count only.
