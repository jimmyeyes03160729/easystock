# A recommendations and opening recovery

The live `research-2026-10-08` paper artifact selected zero of 1,096 validation
rows at threshold 0.60. On 2026-10-12 all 6,289 evaluated live samples were below
that threshold; the maximum was 0.2592. This is evidence of an ineffective
selection configuration, not evidence that reducing the threshold is profitable.

For the user's requested A revision, explicitly configure the existing `rules`
paper mode for the next session. Eligible rule setups require score >=68, at
least two reasons and no hard veto. The model score is advisory in this mode;
the separate `model` mode continues to require the approved model gate and
never silently falls back to rules. Fees, trade eligibility, fresh executable
quotes, time limits, user limits, daily amount limits and exits remain enforced.
Existing period balances and historical transactions are not reset.

An opening-recovery pattern now contributes the same 0.15 pattern component
as a breakout when completed same-day bars show a below-reference open,
a VWAP reclaim, three non-decreasing lows, a bullish close above the previous
bar's high, classified buying ratio >=0.52 and volume ratio >=1.15. These fixed
research parameters are not optimized on today's realized returns. Hard VWAP,
short-low, market-red/FADE and cost vetoes still apply. All recommendations use
observations available at the evaluation timestamp. No retrospective fills or
profits are published for 2026-10-12.

The homepage separates up to five current A candidates from actual paper fills.
Candidates show rule score, model score (not a calibrated win probability),
reasons, and waiting conditions. Backend and frontend reject stale, cross-day
and future quotes. The backend writes a new `a_candidates` projection through
the existing live Firebase snapshot. It also fixes rejection diagnostics to use
the real FirebaseStore `live` reference, rather than a nonexistent `db` member.
The UI now reflects the real 09:30 start instead of displaying 09:15.

Direct paper model promotion additionally requires at least five selected
validation samples, complete finite selected-return metrics and positive mean
net return. A zero-pick or negative-mean model cannot overwrite the previous
artifact or write a promotion receipt. Full champion promotion retains its
existing stricter walk-forward gate.

Validation consists of synthetic causal pattern cases, risk-veto regressions,
no-fill watchlist behavior, replay/SDK metadata regression, promotion/archive
tests, stale-data/HTML-escaping UI tests and runtime safety tests. This changes
the paper strategy; its future realized performance has not been established.
