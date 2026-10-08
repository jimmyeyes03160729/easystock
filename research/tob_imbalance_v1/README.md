# TOB_IMBALANCE_V1 runner (deployed copy lives on the VM)

Implements `docs/research_governance/preregistrations/TOB_IMBALANCE_V1.yaml`: does best-bid / best-ask displayed-size
imbalance at a 5-minute clock grid predict the forward mid return, and does the move clear taker costs. Reuses the
frozen loaders of `research/passive_fill_v1` and `research/hv60_v1` (deploy next to them under
`/home/ubuntu/easystock-research/tob_imbalance_v1`). Only archive days in the five test windows (<= 2026-08-27).
