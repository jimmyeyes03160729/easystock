# A recovery research v2 — pre-registered, offline only

This experiment implements the user's 2026-10-12 requested test version. It is
not imported by intraday_live, PositionManager, paper_account or Firebase. No
live configuration, models, account records or services may be changed by it.

## Frozen hypotheses (before inspecting multi-day outcomes)

1. Allocate at most 30% of the daily BUY-notional allowance per symbol, in whole
   1,000-share lots. SELL does not replenish the allowance. Release at most two
   lifetime stock slots before 10:00, four before 11:00, and five thereafter.
   A lot exceeding its allocation is explicitly skipped, not converted to odd
   lots. This necessarily excludes some high-priced stocks; it is a testable
   tradeoff, not an assertion that these parameters are optimal.
2. Independently select a low-open/VWAP-reclaim/pullback/confirmation pattern.
   Require an actual below-reference open, a completed reclaim, a later bullish
   pullback that holds its contemporaneous VWAP, then a completed close above
   the pullback high on >=1.15 times the preceding context's average volume.
   The last two bars must be the pullback and confirmation;
   discard unfinished, prior-day and future bars. Keep the existing >=68 rule
   gate, hard vetoes, radar, user limits and fresh-tick requirements. Do not
   chase more than one tick above the confirming bar's high or >1% above VWAP.
   Screen estimated round-trip costs <=0.6% for one lot. These are frozen
   research assumptions, not learned parameters.
3. Compare the original hybrid exit with a structural trend exit. Preserve the
   original 1.8% hard stop, 4.5% take profit and 12:55 liquidation. The structural
   alternative activates only after the observed price reaches +1.5% of the
   paid entry price. Before activation, preserve the original technical exits.
   After activation it requires two completed closes below their contemporaneous VWAP,
   or a completed close below the preceding two completed bar lows. It does not
   apply the original uniform breakeven/trailing exit; this may give back profit
   and must be evaluated through marked-to-market drawdown, not just net P&L.

## Experiment matrix

- `baseline`: original >=68 rules, old allocation (remaining daily allowance),
  original hybrid exits.
- `allocation_only`: original rules/exits, capped allocation/slot release.
  Preserve exactly the baseline radar ranking to avoid an entry-ranking confound.
- `recovery_allocation`: independent recovery entry, capped allocation, hybrid
  exits.
- `recovery_structural`: same entry/allocation, structural exits.
- Both one- and two-adverse-ticks-per-side execution assumptions, and both
  O-L-H-C and O-H-L-C minute paths. These are sensitivity scenarios, not bounds.

Signals use a fixed one-minute clock at second 3; execution uses the next full
minute after a two-second decision buffer. No trade may use that execution
bar's high/low to select, fund or size the entry. Entry costs are fixed 28%
discount of 0.1425% per side, minimum TWD20, sell tax 0.15%; adverse ticks are
included in prices exactly once. Technical decisions use completed bars only.

## Data and validation contract

Use the same archived stock universe, timestamps, references, costs and daily
allowance for all four arms. Select the latest 16 available historical days
strictly before 2026-10-12 from the intersection of daily minute packs and the
expanded Shioaji archive. Split chronologically (first half descriptive, second
half untouched historical evaluation). 2026-10-12 is a separate diagnostic day;
it influenced the design and must never be relabeled as an independent holdout.

The archive is a fixed retrospectively selected universe, not a reconstruction
of historical scanners. Historical market health/SDK permission/order-book
depth are not fully recorded: allow-pass/eligible/depth assumptions must be
explicit for the price-path experiment. Missing references or invalid archives
are excluded with counters. Recompute the collector's pure collection audit and
reconcile every recorded collection field. The collector unconditionally writes
`audit.training_eligible=false` with the reason that reference prices, universe
and replay are still required. Preserve that status and disclose it in each
source record; it does not by itself reject an exploratory price-path run.
Unknown training-exclusion reasons or inconsistent collection audits fail closed.
This does not authorize training or promotion of those archives.
Market-category labels, when available, are based
on a declared stock/ETF proxy and are not the TAIEX index or a signal feature.

No deployment is permitted from this exploratory archive experiment alone.
Require a separate, complete point-in-time forward sample including eligibility,
executable quotes/depth, risk and callback times, representative market types,
positive net results in both slippage cases, and no worse drawdown vs baseline.
Do not choose whichever arm/path/date range makes 10/12 profitable. No automatic
training, model promotion, Git push or VM deployment is part of this runner.

## Implementation audit corrections

After the preliminary run, preserve baseline ranking in `allocation_only`,
recheck the lower VWAP bound at next-minute execution, retain open liabilities
when a quote is missing, and record all strategy/runner/production source hashes.
These are comparability/accounting guards, not parameter tuning. Preliminary
outputs are superseded; rerun the unchanged frozen hypothesis matrix separately.
The first added training-status check incorrectly excluded all archives. Source
inspection of `history/collector_core.py:audit` showed its false flag is
unconditional, not a price-data quality failure. Correct the consumer contract,
recompute the collection audit, preserve the false training status and keep
deployment prohibited. All-zero runs from that incorrect check are invalid.
