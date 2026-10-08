# HV60_V1 runner (deployed copy lives on the VM)

Implements `docs/research_governance/preregistrations/HV60_V1.yaml` + `HV60_V1_AMENDMENT_1.yaml`.
Deployed at `/home/ubuntu/easystock-research/hv60_v1` (outside the repo) with `pkg/daytrade_learning/{event_audit,knowledge_v1}`
copied from `main`, and run by cron at 23:30 Taiwan time:

```
30 23 * * * /home/ubuntu/easystock-research/hv60_v1/run_if_ready.sh >> /home/ubuntu/easystock-research/hv60_v1/cron.log 2>&1
```

- `gate.py` checks file existence only and passes when >= 80% of pool stock-days in the five test windows are archived.
- When it passes, two niced workers run (`hv60_run.py`), then `hv60_finalize.py` writes `output/FINAL_LINES.txt`,
  `output/HV60_DECISION.json` and a bundle, and `DONE` stops further runs.
- Reads only archive days <= 2026-10-02 and the official daily DB filtered to the same cutoff; never touches the
  reserved future-confirmation partition, the repo or live services.
- After it finishes, the results must be registered in the trial / OOS-consumption ledgers (manual PR).
