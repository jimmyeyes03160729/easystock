# REVENUE_EARLY_V1 collector (Part B)

Implements the collector of `docs/research_governance/preregistrations/REVENUE_EARLY_V1.yaml`.

- `rev_snapshot.py`: on calendar days 1-15, fetches the MOPS t21sc03 pages (sii/otc, kind 0/1) of revenue month M-1,
  keeps each raw page under `data/raw/M/` and records the first compile date (出表日期) at which each company's row
  appears in `data/announcements.sqlite` (`first_seen`, `snapshots`). Failed fetches and pages without a compile
  date are recorded, never retried silently. Reads no price.
- `run_snapshot.sh`: cron wrapper with a lock.

Deployed copy on the VM: `/home/ubuntu/easystock-research/revenue_early_v1` (git archive of a merged commit), cron:

```
10 21 * * * bash /home/ubuntu/easystock-research/revenue_early_v1/research/revenue_early_v1/run_snapshot.sh >> /home/ubuntu/easystock-research/revenue_early_v1/snapshot_cron.log 2>&1
```

Evaluation events start with revenue month 2026-10 (filings from 2026-11-01). Snapshots of 2026-09 taken in October
2026 are a live test of the collector only. Picks and the Part A / evaluation code follow in a later PR.
Tests: `tests/test_revenue_early_snapshot.py`.
