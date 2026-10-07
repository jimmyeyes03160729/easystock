# Current-profile historical replay

`python -m daytrade_learning.historical_replay` reconstructs point-in-time
five-minute samples from the archived Shioaji tick and minute-bar snapshots.
It uses the production radar, five model features, and `research.simulate`.
The daily TWSE TWT84U historical report provides that day's auction reference
and up/down limits; a missing or mismatched official report excludes the day.

Research files are isolated under
`/home/ubuntu/easystock-learning-data/replay-current-profile` by default.
The command never writes production labels, paper results, or approved models.
It does not log in to a broker, submit orders, or promote a model.

First check archive coverage:

```sh
python -m daytrade_learning.historical_replay --from 2026-03-20 --through 2026-10-02 --expected-profile 72a58274c3f1ff77 --audit-only
```

Then run a single-day smoke test with `--date 2026-10-02 --symbols 2330
--dry-run`, followed by the same command without `--dry-run` to save isolated
evidence. A full replay adds `--resume`; `--train` runs the existing full
walk-forward trainer and promotion gate but saves only an isolated candidate
and evaluation. A successful gate is **not** automatic production promotion.

The replay uses the actual recorded 2026-10-02 live policy and current cost
settings. It refuses a profile mismatch. This only reconstructs the fixed
archived universe, not the historical scanner's changing universe. The first
version is TWSE-only: TPEX symbols without a TWSE reference are excluded and
counted. The exact historical scheduler microseconds and same-bar tick exit
order are unavailable; sampling at five-minute bucket +3 seconds and
conservative minute-bar exits are explicit approximations. Archive dates,
source hashes, official reference hashes, cutoffs, rejects and code version
are retained so audit can reproduce the result. These labels are not proof of
live profitability or a substitute for forward validation.

## Evaluating the opt-in cost rules

`--cost-aware-breakeven` and `--max-roundtrip-cost-pct N` apply the opt-in live
rules (`LIVE_COST_AWARE_BREAKEVEN`, `LIVE_MAX_ROUNDTRIP_COST_PCT`) on top of the
recorded policy. They form a different profile, so first print its hash and
replay into a separate output directory:

```sh
python -m daytrade_learning.historical_replay --from 2026-03-20 --through 2026-10-02 --expected-profile x --cost-aware-breakeven --max-roundtrip-cost-pct 0.6 --print-profile
python -m daytrade_learning.historical_replay --from 2026-03-20 --through 2026-10-02 --expected-profile <printed hash> --cost-aware-breakeven --max-roundtrip-cost-pct 0.6 --output /home/ubuntu/easystock-learning-data/replay-cost-rules --resume
```

Compare its `audit.json` and label returns with the current-profile replay.
With both rules disabled the profile hash is unchanged. Enabling them on the
VM starts a new label profile: training uses only the latest profile, so the
currently approved model's validation no longer describes live exits.
