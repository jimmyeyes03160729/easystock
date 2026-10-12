# Independent recovery v3: exploratory results, 2026-10-13

Offline implementation only. The user's subsequent 2026-10-13 request authorizes
committing and pushing the research branch. No model promotion, live wiring, or
production VM deployment is authorized. See `A_INDEPENDENT_RECOVERY_V3_PROTOCOL.md`
for the frozen hypotheses, assumptions and risk rules.

## Scope and reproducibility

- 17 dates, 6,148 minute packs; latest 16 available dates before 2026-10-12
  split into eight descriptive and eight REUSED historical dates. October 12
  influenced the design and is diagnostic, not validation.
- Final run uses a complete minute-only snapshot. Radar recordings could not
  complete original-hash validation under VM disk contention; partial recordings
  are excluded. All signal radar states are `not_loaded`, not a negative finding.
- Snapshot SHA-256:
  `2f5cf87b402616d24833e14e910feff41d70fb4779673d3db6f36dd92769261b`.
- Outputs: `a-independent-v3-results/{protocol,summary}.json` and 17 daily JSON
  files; executed audit notebook `a-independent-v3.ipynb` with HTML preview.
  Protocol hashes match the final seven source files. All scenarios reproduce
  the preceding minute-only run's financial results after metadata correction.

## Later eight reused dates, TWD after modeled fees and tax

One adverse tick per side; minute prices proxy execution. Low-first and
high-first are scenarios, not bounds or executable account returns.

| Arm | Low-first trades | Low-first net | High-first net | Worst low-first daily drawdown |
|---|---:|---:|---:|---:|
| Direct | 30 | +34,323 | +17,007 | 12,171 |
| Pullback | 20 | +30,893 | +14,474 | 15,243 |
| Union | 30 | +34,439 | +17,123 | 12,171 |
| Legacy eligibility matched control | 24 | -17,711 | -28,989 | 11,512 |

The control adds old eligibility only; it is NOT the actual old-system replay.
Arms overlap; do not add their trades or returns. No untouched holdout exists.

All two-adverse-tick scenarios admit zero trades under the frozen 0.6% estimated
cost ceiling and 30% whole-lot allocation. Returns are unavailable for comparison,
not zero-risk success. Do not loosen this ceiling after seeing outcomes.

## October 12 diagnostic

303 usable symbols produced 302 direct and 50 pullback signal events (not unique
stocks). One-tick low-first direct/union: four trades, -13,626 TWD; pullback:
five trades, -12,158 TWD; matched eligibility control: five trades, -6,449 TWD.

3605 was independently detected at 09:30:03, proxy price 169, old score 65.
Its estimated one-lot one-tick round-trip cost was 0.818879%, above the frozen
0.6% ceiling. It was cost-blocked, not missing a pattern. Removing old gates
alone therefore does not guarantee profitable capital allocation on this date.

## Verification and decision

- 63 focused v2/v3 tests passed. Cover causal data, independent ranking,
  metadata failures, execution guards, costs, capacity, liquidation, hashes,
  no overwrites and no live integration.
- Notebook independently recomputed 482 scenario trade fee/tax/P&L records and
  checked signal/decision coverage, timing, whole lots and budget. These are
  scenario records, not 482 actual trades. No notebook execution errors.
- Broader Windows suite: 943 passed, four skipped, one deselected and one
  unrelated failure. The model identity fixture's 2026-09-28 training date is
  stale as of 2026-10-13; production freshness protection was not weakened.
- Missing forward market state, actual eligibility, executable depth and
  callbacks remain deployment blockers. Historical profits support further
  research, not a confirmed regularity or live trading recommendation.
