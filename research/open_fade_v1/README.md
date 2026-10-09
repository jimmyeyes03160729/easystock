# OPEN_FADE_V1 runner (deployed copy lives on the VM)

Implements `docs/research_governance/preregistrations/OPEN_FADE_V1.yaml`: SHORT the top decile (by opening gap or by the
09:00-09:30 run versus the reference) at 09:30 and cover at 12:55, versus the unconditional short. Reuses the frozen
loaders of `research/passive_fill_v1` and `research/hv60_v1`; deploy under `/home/ubuntu/easystock-research/open_fade_v1`.
Archive days in the five test windows (<= 2026-08-27), excluding the exploration days (every 6th archive day).
