# REVENUE_DRIFT_V1 runner

`fetch_revenue.py` downloads the MOPS t21sc03 tables (months 2020-01..2026-08); `rev_study.py` is the frozen study
(preregistration `REVENUE_DRIFT_V1.yaml`). `rev_robust.py` is a post-hoc, disclosed copy of the study with two
feasibility stresses (excluding entries that open >= 1.09 x reference, env `SLIP_BPS` extra slippage per leg); it
does not change the sealed classification. Deploy under `/home/ubuntu/easystock-research/revenue_v1`.
