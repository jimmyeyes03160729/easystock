"""Fixed A-H economic criteria and classification (frozen before any outcome is read)."""
from __future__ import annotations

MIN_FOLD_EVENTS = 30
MIN_GROSS_BPS = 30.0


def criteria(gross_bps, net_bps, quote_bps, fold_gross, fold_net, fold_quote, fold_counts) -> dict:
    """``fold_*`` are per-fold 15m mean bps (None when a fold has no valid events)."""
    pos = lambda xs: sum(1 for x in xs if x is not None and x > 0)
    return {
        'A_aggregate_gross_gt_0': gross_bps is not None and gross_bps > 0,
        'B_gross_pos_ge_4_of_5_folds': pos(fold_gross) >= 4,
        'C_aggregate_net_gt_0': net_bps is not None and net_bps > 0,
        'D_net_pos_ge_4_of_5_folds': pos(fold_net) >= 4,
        'E_aggregate_quote_gt_0': quote_bps is not None and quote_bps > 0,
        'F_quote_pos_ge_3_of_5_folds': pos(fold_quote) >= 3,
        'G_each_fold_ge_30_events': min(fold_counts) >= MIN_FOLD_EVENTS,
        'H_aggregate_gross_ge_30bps': gross_bps is not None and gross_bps >= MIN_GROSS_BPS,
    }


def classify(c: dict) -> str:
    """Rule order: G false -> INSUFFICIENT; A false -> NO_EDGE; all true -> STRONG;
    B or H false -> WEAK_OR_UNSTABLE; otherwise (A,B,H true, a cost criterion false) -> COST_BLOCKED."""
    if not c['G_each_fold_ge_30_events']:
        return 'INSUFFICIENT_EVENTS'
    if not c['A_aggregate_gross_gt_0']:
        return 'NO_ENTRY_EDGE'
    if all(c.values()):
        return 'STRONG_ENTRY_CANDIDATE'
    if not c['B_gross_pos_ge_4_of_5_folds'] or not c['H_aggregate_gross_ge_30bps']:
        return 'WEAK_OR_UNSTABLE'
    return 'GROSS_EDGE_COST_BLOCKED'
