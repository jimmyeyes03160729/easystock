"""Rebound market-filter study, preregistration REBOUND_P4_MARKET_FILTER_V1.

Frozen in docs/research_governance/preregistrations/REBOUND_P4_MARKET_FILTER_V1.yaml
before any 2022 rebound signal existed and before any filtered result was
computed. Homepage picks (rule-order top 3), BRACKET_H20 exit, traded only
when the D0 TAIEX close is above its 60-session mean. Research only.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from .market_daily import connect as market_connect
from .official import dataset_path
from .research import COST_PCT, FOLDS, RESERVED_FROM, bootstrap_mean, metrics
from .research_horizon import load_picks, simulate_exit
from .schema import connect, database_path
from .simulation import CORRECTION_ID, cost_sensitivity, missing_outcome_threshold, replay

PREREGISTRATION_ID = 'REBOUND_P4_MARKET_FILTER_V1'
UNSEEN_SLICE = ('2022-05-01', '2022-12-31')
EXPOSED_SLICE = ('2023-01-03', '2026-10-06')
MIN_UNSEEN_TRADES = 30


def market_on(pick: dict) -> bool:
    """D0 TAIEX close above its 60-session mean; unknown context means no trade."""
    bias = pick.get('taiex_bias_ma60_pct')
    return bias is not None and bias > 0


def trade(pick: dict) -> float | None:
    if pick['bars'] is None:
        return None
    gross = simulate_exit(pick['bars'], pick['target'], pick['invalid'], stop=True, take=True, horizon=20)
    return None if gross is None else gross - COST_PCT


def profit_factor_ok(m: dict, minimum: float = 1.05) -> bool:
    """metrics() reports no profit factor when there is no losing trade: that is infinite, not failing."""
    if not m['trades']:
        return False
    return m['profit_factor'] is None or m['profit_factor'] >= minimum


def summarize(picks: list[dict], filtered: bool) -> tuple[dict, dict]:
    by_day = defaultdict(list)
    status = Counter()
    for p in picks:
        if filtered and not market_on(p):
            continue
        by_day[p['date']]
        result = replay(p['bars'] or [], p['target'], p['invalid'], stop=True, take=True, horizon=20)
        status[result['status']] += 1
        net = None if result['gross'] is None else result['gross'] - COST_PCT
        if net is not None:
            by_day[p['date']].append(net)
    trades = [t for v in by_day.values() for t in v]
    return {**metrics(trades), 'status': dict(status), 'cost_sensitivity': cost_sensitivity(trades),
            'missing_outcome': missing_outcome_threshold(trades, status['UNRESOLVED_MISSING_BAR'])}, by_day


def evaluate(unseen: list[dict], exposed: list[dict], *, folds=FOLDS) -> dict:
    report = {'preregistration_id': PREREGISTRATION_ID, 'correction_id': CORRECTION_ID,
              'analysis_role': 'EXPOSED_HISTORY_CORRECTION_ONLY',
              'reserved_from': RESERVED_FROM, 'cost_pct': COST_PCT,
              'exit': 'BRACKET_H20', 'filter': 'taiex_bias_ma60_pct > 0'}
    s1, s1_days = summarize(unseen, True)
    s1_unfiltered, _ = summarize(unseen, False)
    s1_days_on = len({p['date'] for p in unseen if market_on(p)})
    report['unseen_2022'] = {'slice': UNSEEN_SLICE, 'filtered': s1, 'unfiltered_descriptive': s1_unfiltered,
                             'signal_days': len({p['date'] for p in unseen}), 'filter_on_days': s1_days_on,
                             'bootstrap_descriptive': bootstrap_mean(s1_days) if s1_days else None}
    s2, s2_days = summarize(exposed, True)
    folds_report = []
    for start, end in folds:
        part = [p for p in exposed if start <= p['date'] <= end]
        folds_report.append({'test_start': start, 'test_end': end, 'filtered': summarize(part, True)[0],
                             'unfiltered': summarize(part, False)[0]})
    report['exposed_2023_2026'] = {'slice': EXPOSED_SLICE, 'filtered': s2, 'folds_descriptive': folds_report,
                                   'bootstrap_descriptive': bootstrap_mean(s2_days) if s2_days else None}
    s2_ok = (s2['mean_net_pct'] or 0) > 0
    if s1['trades'] < MIN_UNSEEN_TRADES:
        stage1 = 'INSUFFICIENT_TRADES'
    elif (s1['mean_net_pct'] or 0) > 0 and profit_factor_ok(s1):
        stage1 = 'PASS'
    else:
        stage1 = 'FAIL'
    if stage1 == 'PASS' and s2_ok:
        outcome = 'CONFIRMATION_CANDIDATE'
    elif stage1 == 'INSUFFICIENT_TRADES' and s2_ok:
        outcome = 'INCONCLUSIVE_HOLDOUT_DECIDES'
    else:
        outcome = 'REJECTED'
    report['decision'] = {'stage1_unseen_2022': stage1, 'stage2_exposed_net_positive': s2_ok,
                          'outcome': 'DESCRIPTIVE_PASS' if outcome != 'REJECTED' else outcome,
                          'legacy_criteria_outcome': outcome, 'holdout_authorized': False, 'production_ready': False}
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=database_path().parent / 'corrections' / f'{PREREGISTRATION_ID}-{CORRECTION_ID}.json')
    args = parser.parse_args()
    with market_connect() as market, connect(dataset_path()) as db:
        unseen = load_picks(db, market, start=UNSEEN_SLICE[0], end=UNSEEN_SLICE[1])
        exposed = load_picks(db, market, start=EXPOSED_SLICE[0], end=EXPOSED_SLICE[1])
    report = evaluate(unseen, exposed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding='utf-8')
    print(json.dumps(report['decision'], ensure_ascii=False))


if __name__ == '__main__':
    main()
