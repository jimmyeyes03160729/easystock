"""Rebound exit-horizon study, preregistration REBOUND_P3_HORIZON_V1.

Frozen in docs/research_governance/preregistrations/REBOUND_P3_HORIZON_V1.yaml
before any 20-session or 5-session outcome of these exits was computed.
Same picks as the homepage (rule-order top 3 per day); only the exit changes.
Research only: no feed, no model, no production effect. Signals and bars on
or after the reserved confirmation start are never loaded.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from .market_daily import connect as market_connect, future_bars
from .official import dataset_path
from .research import (COST_PCT, FOLDS, HISTORICAL_START, RESERVED_FROM, TOP_K, baseline_key,
                       bootstrap_mean, metrics)
from .schema import connect, database_path
from .simulation import CORRECTION_ID, cost_sensitivity, missing_outcome_threshold, replay, session_bars

PREREGISTRATION_ID = 'REBOUND_P3_HORIZON_V1'
MAX_HORIZON = 20
# name: (stop, target, horizon)
EXITS = (
    ('BRACKET_H20', True, True, 20),
    ('STOP_ONLY_H20', True, False, 20),
    ('TIME_H20', False, False, 20),
    ('TIME_H5', False, False, 5),
)


def simulate_exit(bars: list[dict | None], target: float, invalid: float, *, stop: bool, take: bool,
                  horizon: int) -> float | None:
    """Gross % return; bars are D1..D20 on the D0 price basis.

    Same fill rule for every exit: no trade when the D1 open is not strictly
    inside (invalid, target). From D2 an opening gap through an active level
    exits at the open; within a bar the stop has priority; else horizon close.
    """
    return replay(bars, target, invalid, stop=stop, take=take, horizon=horizon)['gross']


def load_picks(db, market, *, reserved_from: str = RESERVED_FROM, start: str | None = None,
               end: str | None = None) -> list[dict]:
    """D0 rule-order top 3 with mature calendars and missing bars left in place.

    start/end (signal dates, inclusive) default to the whole historical range.
    """
    calendar = [r[0] for r in db.execute('SELECT day FROM trading_days WHERE day<? ORDER BY day', (reserved_from,))]
    position = {day: i for i, day in enumerate(calendar)}
    by_day = defaultdict(list)
    query = '''SELECT snapshot FROM candidates WHERE feature_schema_version=2 AND candidate_kind='PENDING'
               AND signal_date>=? AND signal_date<? ORDER BY signal_date,symbol'''
    for (raw,) in db.execute(query, (start or HISTORICAL_START, reserved_from)):
        snap = json.loads(raw)
        if end and snap['signal_date'] > end:
            continue
        i = position.get(snap['signal_date'])
        if i is None or i + MAX_HORIZON >= len(calendar):
            continue  # horizon would reach the reserved partition: not loaded
        evidence = snap['evidence']
        by_day[snap['signal_date']].append({
            'date': snap['signal_date'], 'symbol': snap['symbol'],
            'breakout': evidence.get('confirmation') == 'breakout', 'score': evidence.get('rule_score') or 0,
            'target': evidence['target_price'], 'invalid': evidence['invalid_price'],
            'taiex_bias_ma60_pct': snap['features'].get('taiex_bias_ma60_pct'),
            'sessions': calendar[i + 1:i + 1 + MAX_HORIZON]})
    picks = []
    for day in sorted(by_day):
        # Rank before inspecting future availability; no replacement of unfilled slots.
        for row in sorted(by_day[day], key=baseline_key)[:TOP_K]:
            row['bars'] = session_bars(market, row['symbol'], day, row.pop('sessions'), before=reserved_from)
            picks.append(row)
    return picks


def evaluate(picks: list[dict], *, folds=FOLDS, exits=EXITS) -> dict:
    report = {'preregistration_id': PREREGISTRATION_ID, 'correction_id': CORRECTION_ID,
              'analysis_role': 'EXPOSED_HISTORY_CORRECTION_ONLY',
              'reserved_from': RESERVED_FROM, 'cost_pct': COST_PCT,
              'top_k': TOP_K, 'picks_loaded': len(picks), 'exits': {}}
    for name, stop, take, horizon in exits:
        fold_reports, by_day, status = [], {}, Counter()
        for start, end in folds:
            trades, days, fold_status = [], defaultdict(list), Counter()
            for p in picks:
                if not start <= p['date'] <= end:
                    continue
                days[(start, p['date'])]  # retain signal dates without resolved trades
                result = replay(p['bars'] or [], p['target'], p['invalid'], stop=stop, take=take, horizon=horizon)
                fold_status[result['status']] += 1
                gross = result['gross']
                if gross is not None:
                    trades.append(gross - COST_PCT)
                    days[(start, p['date'])].append(gross - COST_PCT)
            status.update(fold_status)
            fold_reports.append({'test_start': start, 'test_end': end, 'status': dict(fold_status), **metrics(trades)})
            by_day.update(days)
        pooled = metrics([t for v in by_day.values() for t in v])
        boot = bootstrap_mean(by_day)
        crit = {
            'A_pooled_net_positive': (pooled['mean_net_pct'] or 0) > 0,
            'B_pooled_profit_factor_ge_1_05': (pooled['profit_factor'] or 0) >= 1.05,
            'C_net_positive_4_of_5': sum((f['mean_net_pct'] or 0) > 0 for f in fold_reports) >= 4,
            'D_bootstrap_p10_positive': boot['p10'] > 0,
            'E_min_100_trades_per_fold': all(f['trades'] >= 100 for f in fold_reports),
        }
        crit['ALL_PASS'] = all(crit.values())
        net_trades = [t for v in by_day.values() for t in v]
        report['exits'][name] = {'folds': fold_reports, 'pooled': pooled, 'bootstrap_mean': boot, 'criteria': crit,
                                'status': dict(status), 'cost_sensitivity': cost_sensitivity(net_trades),
                                'missing_outcome': missing_outcome_threshold(net_trades, status['UNRESOLVED_MISSING_BAR'])}
    order = {name: i for i, (name, *_rest) in enumerate(exits)}
    passing = sorted((n for n, v in report['exits'].items() if v['criteria']['ALL_PASS']),
                     key=lambda n: (-report['exits'][n]['pooled']['mean_net_pct'], order[n]))
    report['decision'] = {'passing_exits': passing, 'selected_exit': passing[0] if passing else None,
                          'outcome': 'DESCRIPTIVE_PASS' if passing else 'REJECTED',
                          'holdout_authorized': False, 'production_ready': False}
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=database_path().parent / 'corrections' / f'{PREREGISTRATION_ID}-{CORRECTION_ID}.json')
    args = parser.parse_args()
    with market_connect() as market, connect(dataset_path()) as db:
        picks = load_picks(db, market)
    report = evaluate(picks)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding='utf-8')
    print(json.dumps(report['decision'], ensure_ascii=False))


if __name__ == '__main__':
    main()
