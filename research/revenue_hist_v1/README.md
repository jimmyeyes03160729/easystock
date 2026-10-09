# REVENUE_HIST_V1 runner

Out-of-sample replication of the sealed REVENUE_DRIFT_V1 study on event months 2015-01..2021-12
(preregistration `docs/research_governance/preregistrations/REVENUE_HIST_V1.yaml`). The study imports
`research/revenue_v1/rev_study.py` unchanged and only rebinds its constants (period, databases, fold majorities).

Deploy from a `git archive` of the merge commit under `/home/ubuntu/easystock-research/revenue_hist_v1/code`, then
`HIST_CODE_COMMIT=<sha> nohup bash research/revenue_hist_v1/run.sh > run.out 2>&1 &`. Data go to new databases under
`/home/ubuntu/easystock-research/revenue_hist_v1/{data,daily}`; the production daily DB is never opened.
Outputs: `output/FINAL_LINES.txt` (includes PER_1M and REPLICATION lines), `output/REVENUE_DRIFT_DECISION.json`, `DONE`.
