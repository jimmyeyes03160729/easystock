"""Rebound Phase 2 ranker study, preregistration REBOUND_P2_RANKER_V1.

Frozen in docs/research_governance/preregistrations/REBOUND_P2_RANKER_V1.yaml
before any model output was computed. Research only: no feed, no model file,
no production effect. Signals on or after the reserved confirmation start are
never loaded; neither are market bars on or after it.
"""
from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from math import isfinite
from pathlib import Path

from .collector import SETTINGS
from .market_daily import connect as market_connect, future_bars
from .official import dataset_path
from .schema import connect, database_path

PREREGISTRATION_ID = 'REBOUND_P2_RANKER_V1'
RESERVED_FROM = SETTINGS['reserved_confirmation_start']
HISTORICAL_START = '2023-01-03'
HORIZON = 10
COST_PCT = 0.6
TOP_K = 3
EMBARGO_SESSIONS = 15
POOL_KINDS = ('PENDING', 'NEAR_MISS', 'BOTTOM_ZONE')
FOLDS = (
    ('2024-01-01', '2024-06-30'),
    ('2024-07-01', '2024-12-31'),
    ('2025-01-01', '2025-06-30'),
    ('2025-07-01', '2025-12-31'),
    ('2026-01-01', '2026-10-06'),
)
VARIANTS = (
    ('RIDGE_RULE_ONLY', 'ridge', ('PENDING',)),
    ('RIDGE_WIDE_POOL', 'ridge', POOL_KINDS),
    ('HGB_RULE_ONLY', 'hgb', ('PENDING',)),
    ('HGB_WIDE_POOL', 'hgb', POOL_KINDS),
)
BOOTSTRAP = 2000


def simulate(bars: list[dict], target: float, invalid: float) -> float | None:
    """Gross % return of the bracket trade; bars are D1..D10 on the D0 price basis.

    Entry at D1 open (None when it is outside the bracket: no fill). From D2 an
    opening gap through a level exits at the open. Within a bar the stop has
    priority over the target. Otherwise exit at the D10 close.
    """
    if len(bars) < HORIZON:
        return None
    entry = bars[0]['open']
    if not invalid < entry < target:
        return None
    for n, bar in enumerate(bars[:HORIZON]):
        if n:
            if bar['open'] <= invalid or bar['open'] >= target:
                return (bar['open'] / entry - 1) * 100
        if bar['low'] <= invalid:
            return (invalid / entry - 1) * 100
        if bar['high'] >= target:
            return (target / entry - 1) * 100
    return (bars[HORIZON - 1]['close'] / entry - 1) * 100


def load_rows(db, market, *, reserved_from: str = RESERVED_FROM) -> tuple[list[dict], list[str], list[str]]:
    """Matured historical rows with a complete horizon strictly before reserved_from."""
    calendar = [r[0] for r in db.execute('SELECT day FROM trading_days WHERE day<? ORDER BY day', (reserved_from,))]
    position = {day: i for i, day in enumerate(calendar)}
    rows, names = [], None
    query = '''SELECT snapshot FROM candidates WHERE feature_schema_version=2 AND signal_date>=? AND signal_date<?
               AND candidate_kind IN (?,?,?) ORDER BY signal_date,symbol'''
    for (raw,) in db.execute(query, (HISTORICAL_START, reserved_from, *POOL_KINDS)):
        snap = json.loads(raw)
        day, i = snap['signal_date'], position.get(snap['signal_date'])
        if i is None or i + HORIZON >= len(calendar):
            continue  # horizon would reach the reserved partition: not loaded
        sessions = calendar[i + 1:i + 1 + HORIZON]
        bars = [b for b in future_bars(market, snap['symbol'], day, HORIZON) if b['time'] < reserved_from]
        if [b['time'] for b in bars] != sessions:
            continue  # suspension inside the horizon: excluded for every ranker
        evidence = snap['evidence']
        gross = simulate(bars, evidence['target_price'], evidence['invalid_price'])
        if names is None:
            names = sorted(snap['features'])
        if sorted(snap['features']) != names:
            raise ValueError(f'feature_schema_mismatch:{day}:{snap["symbol"]}')
        rows.append({
            'date': day, 'symbol': snap['symbol'], 'kind': snap['candidate_kind'],
            'x': [snap['features'][k] for k in names],
            'breakout': evidence.get('confirmation') == 'breakout', 'score': evidence.get('rule_score') or 0,
            'gross': gross, 'net': None if gross is None else gross - COST_PCT,
        })
    return rows, names or [], calendar


def _matrix(rows, kinds_onehot: bool):
    out = []
    for r in rows:
        x = [float('nan') if v is None else float(v) for v in r['x']]
        if kinds_onehot:
            x += [1.0 if r['kind'] == 'NEAR_MISS' else 0.0, 1.0 if r['kind'] == 'BOTTOM_ZONE' else 0.0]
        out.append(x)
    return out


def fit_predict(kind: str, train: list[dict], test: list[dict], wide: bool) -> list[float]:
    import numpy as np
    X, y = np.array(_matrix(train, wide)), np.array([r['net'] for r in train])
    T = np.array(_matrix(test, wide))
    if kind == 'ridge':
        from sklearn.linear_model import Ridge
        median = np.nanmedian(X, axis=0)
        median = np.where(np.isfinite(median), median, 0.0)
        def prep(A):
            missing = np.isnan(A).astype(float)
            A = np.where(np.isnan(A), median, A)
            return np.hstack([A, missing])
        Xp, Tp = prep(X), prep(T)
        mean, scale = Xp.mean(axis=0), Xp.std(axis=0)
        scale = np.where(scale > 0, scale, 1.0)
        model = Ridge(alpha=1.0).fit((Xp - mean) / scale, y)
        return model.predict((Tp - mean) / scale).tolist()
    from sklearn.ensemble import HistGradientBoostingRegressor
    model = HistGradientBoostingRegressor(max_iter=200, learning_rate=0.05, max_leaf_nodes=15,
                                          min_samples_leaf=100, l2_regularization=1.0, random_state=0)
    return model.fit(X, y).predict(T).tolist()


def pick(day_rows: list[dict], key, k: int = TOP_K) -> list[dict]:
    return sorted(day_rows, key=key)[:k]


def baseline_key(r):
    return (0 if r['breakout'] else 1, -r['score'], r['symbol'])


def metrics(trades: list[float]) -> dict:
    wins, losses = sum(t for t in trades if t > 0), -sum(t for t in trades if t < 0)
    return {'trades': len(trades), 'mean_net_pct': round(sum(trades) / len(trades), 4) if trades else None,
            'profit_factor': round(wins / losses, 4) if losses else None,
            'win_rate': round(sum(t > 0 for t in trades) / len(trades), 4) if trades else None}


def select(test: list[dict], preds: list[float] | None, k: int = TOP_K, abstain: bool = False) -> dict[str, list[float]]:
    """Net returns of executed picks per date (no fill when D1 opens outside the bracket)."""
    by_day = defaultdict(list)
    for i, r in enumerate(test):
        by_day[r['date']].append((r, preds[i] if preds is not None else None))
    out = {}
    for day, items in by_day.items():
        if preds is None:
            chosen = [r for r, _ in sorted(items, key=lambda x: baseline_key(x[0]))[:k]]
        else:
            ranked = sorted(items, key=lambda x: (-x[1], x[0]['symbol']))[:k]
            chosen = [r for r, p in ranked if not abstain or p > 0]
        out[day] = [r['net'] for r in chosen if r['net'] is not None]
    return out


def bootstrap_delta(model: dict, base: dict, seed: int = 0) -> dict:
    days = sorted(set(model) | set(base))
    rng = random.Random(seed)
    values = []
    for _ in range(BOOTSTRAP):
        sample = [rng.choice(days) for _ in days]
        m = [t for d in sample for t in model.get(d, [])]
        b = [t for d in sample for t in base.get(d, [])]
        if m and b:
            values.append(sum(m) / len(m) - sum(b) / len(b))
    values.sort()
    return {'p10': round(values[int(0.10 * len(values))], 4), 'p50': round(values[len(values) // 2], 4),
            'p90': round(values[int(0.90 * len(values))], 4), 'samples': len(values)}


def bootstrap_mean(by_day: dict, seed: int = 0) -> dict:
    """Date-block bootstrap of the pooled mean net return (used by later studies)."""
    days = sorted(by_day)
    rng = random.Random(seed)
    values = []
    for _ in range(BOOTSTRAP):
        trades = [t for d in (rng.choice(days) for _ in days) for t in by_day[d]]
        if trades:
            values.append(sum(trades) / len(trades))
    values.sort()
    if not values:
        return {'p10': float('-inf'), 'p50': None, 'p90': None, 'samples': 0}
    return {'p10': round(values[int(0.10 * len(values))], 4), 'p50': round(values[len(values) // 2], 4),
            'p90': round(values[int(0.90 * len(values))], 4), 'samples': len(values)}


def criteria(folds: list[dict], pooled: dict, boot: dict) -> dict:
    deltas = [f['delta_mean_net_pct'] for f in folds]
    result = {
        'A_pooled_delta_positive': pooled['delta_mean_net_pct'] is not None and pooled['delta_mean_net_pct'] > 0,
        'B_delta_positive_4_of_5': sum(d is not None and d > 0 for d in deltas) >= 4,
        'C_pooled_model_net_positive': (pooled['model']['mean_net_pct'] or 0) > 0,
        'D_pooled_profit_factor_ge_1_05': (pooled['model']['profit_factor'] or 0) >= 1.05,
        'E_model_net_positive_3_of_5': sum((f['model']['mean_net_pct'] or 0) > 0 for f in folds) >= 3,
        'F_min_100_trades_per_fold': all(f['model']['trades'] >= 100 for f in folds),
        'G_bootstrap_p10_delta_positive': boot['p10'] > 0,
    }
    result['ALL_PASS'] = all(result.values())
    return result


def evaluate(rows: list[dict], calendar: list[str], *, folds=FOLDS, variants=VARIANTS) -> dict:
    position = {d: i for i, d in enumerate(calendar)}
    report = {'preregistration_id': PREREGISTRATION_ID, 'reserved_from': RESERVED_FROM, 'cost_pct': COST_PCT,
              'top_k': TOP_K, 'rows_loaded': len(rows), 'variants': {}}
    base_by_fold = []
    for start, end in folds:
        test = [r for r in rows if r['kind'] == 'PENDING' and start <= r['date'] <= end]
        base_by_fold.append(select(test, None))
    for name, model_kind, kinds in variants:
        fold_reports, model_days, base_days, descriptive = [], {}, {}, defaultdict(dict)
        for (start, end), base in zip(folds, base_by_fold):
            first = next(i for i, d in enumerate(calendar) if d >= start)
            cutoff = calendar[max(0, first - EMBARGO_SESSIONS)]
            train = [r for r in rows if r['kind'] in kinds and r['date'] <= cutoff and r['net'] is not None]
            test = [r for r in rows if r['kind'] == 'PENDING' and start <= r['date'] <= end]
            preds = fit_predict(model_kind, train, test, len(kinds) > 1)
            if any(not isfinite(p) for p in preds):
                raise ValueError('nonfinite_prediction')
            chosen = select(test, preds)
            m = metrics([t for v in chosen.values() for t in v])
            b = metrics([t for v in base.values() for t in v])
            fold_reports.append({'test_start': start, 'test_end': end, 'train_rows': len(train),
                                 'train_cutoff': cutoff, 'test_rows': len(test), 'model': m, 'baseline': b,
                                 'delta_mean_net_pct': round(m['mean_net_pct'] - b['mean_net_pct'], 4)
                                 if m['mean_net_pct'] is not None and b['mean_net_pct'] is not None else None})
            model_days.update({(start, d): v for d, v in chosen.items()})
            base_days.update({(start, d): v for d, v in base.items()})
            for k in (1, 2, 5):
                descriptive[f'top_{k}'][start] = metrics([t for v in select(test, preds, k).values() for t in v])
            descriptive['top_3_abstain_nonpositive'][start] = metrics(
                [t for v in select(test, preds, abstain=True).values() for t in v])
        pm = metrics([t for v in model_days.values() for t in v])
        pb = metrics([t for v in base_days.values() for t in v])
        pooled = {'model': pm, 'baseline': pb,
                  'delta_mean_net_pct': round(pm['mean_net_pct'] - pb['mean_net_pct'], 4)
                  if pm['mean_net_pct'] is not None and pb['mean_net_pct'] is not None else None}
        boot = bootstrap_delta(model_days, base_days)
        report['variants'][name] = {'folds': fold_reports, 'pooled': pooled, 'bootstrap_delta': boot,
                                    'criteria': criteria(fold_reports, pooled, boot),
                                    'descriptive_only': descriptive}
    passing = [n for n, v in report['variants'].items() if v['criteria']['ALL_PASS']]
    simplicity = {name: i for i, (name, _, _) in enumerate(variants)}
    passing.sort(key=lambda n: (-report['variants'][n]['pooled']['delta_mean_net_pct'], simplicity[n]))
    report['decision'] = {'passing_variants': passing, 'selected_variant': passing[0] if passing else None,
                          'outcome': 'SHADOW_CANDIDATE' if passing else 'REJECTED', 'production_ready': False}
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=database_path().parent / 'phase2' / f'{PREREGISTRATION_ID}-result.json')
    args = parser.parse_args()
    with market_connect() as market, connect(dataset_path()) as db:
        rows, names, calendar = load_rows(db, market)
    report = evaluate(rows, calendar)
    report['feature_names'] = names
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding='utf-8')
    print(json.dumps(report['decision'], ensure_ascii=False))


if __name__ == '__main__':
    main()
