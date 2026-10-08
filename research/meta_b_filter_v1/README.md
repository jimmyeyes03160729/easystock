# META_B_FILTER_V1 runner (Stage 1)

Implements `docs/research_governance/preregistrations/META_B_FILTER_V1.yaml` + `META_B_FILTER_V1_AMENDMENT_1.yaml`.
Runway A redesigned as a meta-label filter over the frozen runway B rule.

| file | role |
| --- | --- |
| `pinned/runway_v2/` | byte-identical `strategy/config/orderbook/manager/ledger.py` at 6aa1e5a; blob hashes checked at run time |
| `mb_common.py` | sys.path order, pinned radar thresholds, pin verification, module manifest |
| `mb_trade.py` | B's exit state machine (mirrors `PositionManagerV2.update_price`), QUOTE / TRADE fills, paper_execution costs |
| `mb_signal.py` | per-symbol pass (production radar each minute, B rule, level-1 checks, replay, own features) and the cross-symbol top-30 / pool features |
| `mb_run.py` | worker: archive days <= 2026-08-27, one symbol in memory at a time, `work/DAY.json.gz` |
| `mb_stats.py` | event-level re-entry rule, day-clustered excess t, threshold rule, B-constrained portfolio, criteria A-E/G |
| `mb_finalize.py` | expanding walk-forward (L2 logistic), `output/FINAL_LINES.txt`, `META_B_FILTER_V1_STAGE1.json`, bundle |

Run once on the VM from a git archive of the merged commit:

```
C=<merged commit>; D=/home/ubuntu/easystock-research/meta_b_filter_v1
git -C /home/ubuntu/easystock fetch -q origin && mkdir -p $D && git -C /home/ubuntu/easystock archive $C | tar -x -C $D
cd $D/research/meta_b_filter_v1 && MB_CODE_COMMIT=$C nohup ./run.sh > run.out 2>&1 &
```

Reads only archive days <= 2026-08-27 and the official daily DB filtered to <= 2026-10-02; never touches the
reserved partitions, the production checkout, live services or the repo. Afterwards the result is registered in the
trial and OOS-consumption ledgers by PR. Tests: `tests/test_meta_b_filter.py`.
