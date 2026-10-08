# PASSIVE_FILL_V1 runner (deployed copy lives on the VM)

Implements `docs/research_governance/preregistrations/PASSIVE_FILL_V1.yaml`: unconditional LONG round trips on a
fixed 15-minute grid, taker execution vs posting at the touch (60s / 300s, with fallback or skip), QUEUE and STRICT
fill models. `pf_fill.py` is pure and unit-tested (`tests/test_passive_fill.py`).

Deployed at `/home/ubuntu/easystock-research/passive_fill_v1`, next to `hv60_v1` (it reuses the frozen
`hv60_common` pool / archive / official-daily helpers and `hv60_v1/pkg`). Run once with `run.sh`; results land in
`output/FINAL_LINES.txt`, `output/PASSIVE_FILL_DECISION.json` and a bundle. Reads only test-window days
(<= 2026-08-27); never touches reserved future partitions, the repo or live services.
