"""Read-only correction runner for an isolated, bounded historical snapshot."""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import random
import sqlite3

from . import research, research_filter, research_horizon
from .simulation import CORRECTION_ID, replay


def block_bootstrap(by_day: dict[str, list[float]], calendar: list[str], ranges: tuple,
                    length: int, *, samples: int = 2000, seed: int = 0,
                    comparison: dict[str, list[float]] | None = None) -> dict:
    """Moving blocks within each fold; preserve adjacent session dependence.

    Noncircular blocks; end blocks are sampled with the same probability as
    interior blocks. Calendar days without trades remain empty slots. The last
    drawn block is truncated to preserve each fold's original session count.
    """
    if length < 1:
        raise ValueError('invalid_block_length')
    groups = [[d for d in calendar if start <= d <= end] for start, end in ranges]
    rng, values = random.Random(seed), []
    for _ in range(samples):
        total, count, other_total, other_count = 0.0, 0, 0.0, 0
        for days in groups:
            if not days:
                continue
            width = min(length, len(days))
            sampled = []
            while len(sampled) < len(days):
                start = rng.randrange(len(days) - width + 1)
                sampled.extend(days[start:start + width])
            for day in sampled[:len(days)]:
                trades = by_day.get(day, [])
                total += sum(trades)
                count += len(trades)
                if comparison is not None:
                    other = comparison.get(day, [])
                    other_total += sum(other)
                    other_count += len(other)
        if count and (comparison is None or other_count):
            values.append(total / count - (other_total / other_count if comparison is not None else 0))
    values.sort()
    return {'block_sessions': length, 'calendar_sessions': sum(map(len, groups)),
            'samples': len(values), 'seed': seed, 'descriptive_only': True,
            **{key: round(values[min(int(q * len(values)), len(values) - 1)], 6) if values else None
               for key, q in (('p10', 0.1), ('p50', 0.5), ('p90', 0.9))}}


def exit_days(picks, stop, take, horizon):
    by_day = defaultdict(list)
    for p in picks:
        outcome = replay(p['bars'], p['target'], p['invalid'], stop=stop, take=take, horizon=horizon)
        by_day[p['date']]
        if outcome['gross'] is not None:
            by_day[p['date']].append(outcome['gross'] - research.COST_PCT)
    return by_day


def read_only(path):
    db = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA query_only=ON')
    return db


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads((args.data / 'manifest.json').read_text(encoding='utf-8'))
    if manifest['before'] != research.RESERVED_FROM or manifest['labels_read'] is not False:
        raise ValueError('invalid_historical_manifest')
    with read_only(args.data / 'dataset-v2.sqlite') as db, read_only(args.data / 'market-daily.sqlite') as market:
        calendar = [r[0] for r in db.execute('SELECT day FROM trading_days WHERE day<? ORDER BY day',
                                           (research.RESERVED_FROM,))]
        print('Loading P2 historical candidate rows', flush=True)
        rows, names, _ = research.load_rows(db, market)
        print(f'Evaluating P2: {len(rows)} rows', flush=True)
        day_returns = {}
        p2 = research.evaluate(rows, calendar, day_returns=day_returns)
        p2['feature_names'] = names
        print('Loading P3/P4 historical picks', flush=True)
        all_picks = research_horizon.load_picks(db, market, start='2022-05-01')
        picks = [p for p in all_picks if p['date'] >= research.HISTORICAL_START]
        p3 = research_horizon.evaluate(picks)
        unseen = [p for p in all_picks if research_filter.UNSEEN_SLICE[0] <= p['date'] <= research_filter.UNSEEN_SLICE[1]]
        p4 = research_filter.evaluate(unseen, picks)
    # Bootstrap is diagnostic and cannot authorize holdout use.
    for name, stop, take, horizon in research_horizon.EXITS:
        by_day = exit_days(picks, stop, take, horizon)
        p3['exits'][name]['moving_block_bootstrap'] = {
            str(length): block_bootstrap(by_day, calendar, research.FOLDS, length) for length in (10, 20)}
    base = research.select([r for r in rows if r['kind'] == 'PENDING'], None)
    p2['baseline_moving_block_bootstrap'] = {
        str(length): block_bootstrap(base, calendar, research.FOLDS, length) for length in (10, 20)}
    for name, daily in day_returns.items():
        p2['variants'][name]['moving_block_bootstrap_delta'] = {
            str(length): block_bootstrap(daily['model'], calendar, research.FOLDS, length,
                                        comparison=daily['baseline']) for length in (10, 20)}
    for key, part, ranges in (
        ('unseen_2022', unseen, (research_filter.UNSEEN_SLICE,)),
        ('exposed_2023_2026', picks, (research_filter.EXPOSED_SLICE,)),
    ):
        by_day = exit_days([p for p in part if research_filter.market_on(p)], True, True, 20)
        p4[key]['moving_block_bootstrap'] = {
            str(length): block_bootstrap(by_day, calendar, ranges, length) for length in (10, 20)}
    report = {'correction_id': CORRECTION_ID, 'input_manifest': manifest,
              'analysis_role': 'EXPOSED_HISTORY_CORRECTION_ONLY', 'holdout_read': False,
              'P2': p2, 'P3': p3, 'P4': p4}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True, allow_nan=False), encoding='utf-8')
    print(json.dumps({key: report[key]['decision'] for key in ('P2', 'P3', 'P4')}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
