# Rebound research dataset

The frozen production rule is `range-rebound-0.3` in `range_rebound.py`.
This package does not publish `rebound_feed`, train a model, or place orders.
It stores research rows in the private VM directory
`/home/ubuntu/easystock-learning-data/rebound/dataset.sqlite`.

Candidate snapshots contain only data available at the D0 close. Labels are
stored in a separate column after future market sessions occur. Missing
historical filing publication timestamps result in `PENDING`, never a
fabricated `PASSED`. Historical E.SUN real-time context is never backfilled.

```bash
python3 -m rebound_learning.backfill --limit-days 20 --dry-run
python3 -m rebound_learning.backfill --from 2023-09-04 --to 2026-09-30
python3 -m rebound_learning.labels
python3 -m rebound_learning.audit
```

The audit exits nonzero on critical issues. For complete definitions and
limitations, see `docs/REBOUND_AI_DATASET.md`.
