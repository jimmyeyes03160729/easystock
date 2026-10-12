"""Read-only multi-day archive experiment; never imports intraday_live/SDK/wallet."""
from __future__ import annotations
import argparse
import ast
from bisect import bisect_right
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone, time as clock
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

TPE = timezone(timedelta(hours=8))


def load_strategy(path):
    spec = importlib.util.spec_from_file_location('isolated_a_recovery_v2', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def radar_helpers(repo):
    from strategy_engine import num, clamp
    scope = dict(num=num, clamp=clamp, math=math, RADAR_HISTORY_SECONDS=360,
        RADAR_BASELINE_WINDOWS=4, RADAR_MIN_60S_VOLUME=10, RADAR_MIN_60S_AMOUNT=1500000,
        RADAR_MIN_SURGE=1.4, RADAR_MIN_BUY_RATIO=.52, RADAR_MIN_CLASSIFIED_RATIO=.35,
        RADAR_MIN_PRICE_CHANGE_60_PCT=-.10)
    source = (repo / 'intraday_live.py').read_text(encoding='utf-8')
    names = {'compute_volume_surge_metrics', 'qualifies_volume_surge', 'score_volume_surge'}
    nodes = [n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name in names]
    if {n.name for n in nodes} != names:
        raise ValueError('radar_source_not_found')
    exec(compile(ast.Module(body=nodes, type_ignores=[]), '<production-pure-radar>', 'exec'), scope)
    return scope


def archive_auditor(repo):
    """Execute only the collector's pure validators, never its broker/session path."""
    source = (repo / 'history/collector_core.py').read_text(encoding='utf-8')
    names = {'raw_datetime', 'validate', 'audit'}
    nodes = [n for n in ast.parse(source).body if
             (isinstance(n, ast.FunctionDef) and n.name in names) or
             (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and
              t.id in {'TICK_FIELDS', 'BAR_FIELDS'} for t in n.targets))]
    scope = dict(datetime=datetime, timedelta=timedelta, clock=clock, math=math)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), '<pure-archive-audit>', 'exec'), scope)
    return scope['audit']


def validate_exploration_archive(payload, day, auditor):
    computed = auditor(payload['ticks'], payload['kbars'], day)
    recorded = payload.get('audit')
    if not isinstance(recorded, dict):
        raise ValueError('missing_collection_audit')
    if recorded.get('training_eligible') is False:
        if recorded.get('reason') != computed['reason']:
            raise ValueError('unknown_training_exclusion')
    elif recorded.get('training_eligible') is not True:
        raise ValueError('unknown_training_status')
    if any(recorded.get(k) != v for k, v in computed.items()
           if k not in {'training_eligible', 'reason'}):
        raise ValueError('collection_audit_mismatch')
    return recorded['training_eligible']


def group_bars(rows, size):
    groups = defaultdict(list)
    for r in rows:
        stamp = datetime.fromisoformat(r['at'])
        groups[stamp.replace(minute=stamp.minute // size * size, second=0, microsecond=0)].append(r)
    result = []
    for stamp, values in sorted(groups.items()):
        values.sort(key=lambda r: r['at'])
        if len(values) != size or any(datetime.fromisoformat(r['at']) != stamp + timedelta(minutes=i)
                                       for i, r in enumerate(values)):
            continue
        result.append(dict(date=stamp.isoformat(), open=values[0]['open'], close=values[-1]['close'],
            high=max(r['high'] for r in values), low=min(r['low'] for r in values),
            volume=sum(r['volume'] for r in values)))
    return result, [datetime.fromisoformat(r['date']) + timedelta(minutes=size) for r in result]


def load_day(archive, bars_root, day, auditor):
    from daytrade_learning.historical_replay import prepared_ticks
    quality = Counter(); data = {}; sources = []
    for path in archive.files(day):
        symbol = path.name[:-8]; pack_path = bars_root / day / (symbol + '.json')
        if not pack_path.exists():
            quality['missing_minute_pack'] += 1; continue
        pack_raw = pack_path.read_bytes(); pack = json.loads(pack_raw)
        prev = pack.get('previous_close') or {}
        if not (prev.get('date') and prev['date'] < day and isinstance(prev.get('price'), (float, int))
                and math.isfinite(prev['price']) and prev['price'] > 0):
            quality['missing_historical_previous_close'] += 1; continue
        try:
            payload, sha = archive.read(path, day)
            training_eligible = validate_exploration_archive(payload, day, auditor)
            seconds, events = prepared_ticks(payload, day)
            rows = pack['bars']; stamps = [datetime.fromisoformat(r['at']) for r in rows]
            if (pack['date'] != day or not rows or stamps != sorted(set(stamps))
                    or any(t.date().isoformat() != day or t.tzinfo is None for t in stamps)):
                raise ValueError('minute_identity')
            for r in rows:
                o, h, l, c, v = [float(r[k]) for k in ('open', 'high', 'low', 'close', 'volume')]
                if not all(math.isfinite(x) for x in (o, h, l, c, v)) or not 0 < l <= min(o, c) <= max(o, c) <= h or v < 0:
                    raise ValueError('bad_minute_bar')
            if stamps[-1].strftime('%H:%M') != '13:29':
                raise ValueError('incomplete_day')
            volume = [0.]; amount = [0.]
            for event in events:
                volume.append(volume[-1] + max(0, event[1]))
                amount.append(amount[-1] + max(0, event[4]))
            data[symbol] = dict(pack=pack, seconds=seconds, events=events, cumulative_volume=volume,
                cumulative_amount=amount, previous=prev['price'], b5=group_bars(rows, 5), b15=group_bars(rows, 15),
                minutes={t: r for t, r in zip(stamps, rows)})
            sources.append(dict(symbol=symbol, archive_sha256=sha,
                                minute_sha256=hashlib.sha256(pack_raw).hexdigest(),
                                archive_training_eligible=training_eligible))
            if not training_eligible:
                quality['archive_not_training_eligible_exploration_only'] += 1
        except (ValueError, KeyError, TypeError, OSError):
            quality['invalid_archive_or_minute_pack'] += 1
    return data, quality, sources


def signals_for_day(data, day, helpers, module, policy):
    from strategy_engine import evaluate_daytrade
    signals = []; quality = Counter()
    for minute in range(9 * 60 + 30, 12 * 60 + 30):
        now = datetime.fromisoformat(day).replace(hour=minute // 60, minute=minute % 60, second=3, tzinfo=TPE)
        now_ts = now.timestamp(); ranked = []
        for symbol, stock in data.items():
            end = bisect_right(stock['seconds'], now_ts)
            if end == 0 or now_ts - stock['seconds'][end - 1] > 3:
                quality['no_fresh_tick_at_fixed_clock'] += 1; continue
            start = bisect_right(stock['seconds'], now_ts - 360)
            volume = stock['cumulative_volume'][end]
            average = stock['cumulative_amount'][end] / volume / 1000 if volume else None
            metrics = helpers['compute_volume_surge_metrics'](stock['events'][start:end], now_ts, average)
            if metrics and helpers['qualifies_volume_surge'](metrics):
                ranked.append(dict(metrics, symbol=symbol, radar_score=helpers['score_volume_surge'](metrics)))
        ranked.sort(key=lambda r: (r['radar_score'], r['surge_60s'], r['amount_60s'], r['symbol']), reverse=True)
        for rank, row in enumerate(ranked[:30]):
            symbol = row['symbol']; stock = data[symbol]
            b5, end5 = stock['b5']; b15, end15 = stock['b15']
            rows5 = b5[:bisect_right(end5, now)]; rows15 = b15[:bisect_right(end15, now)]
            if len(rows5) < 6 or len(rows15) < 2:
                quality['insufficient_completed_bars'] += 1; continue
            price = row['price']; previous = stock['previous']
            if not 1 <= price <= 2000 or (price / previous - 1) * 100 > 8:
                continue
            result = evaluate_daytrade(rows5, rows15, stock=dict(row, previous_close=previous),
                                      market_level='GREEN', market_regime='NORMAL')
            if not result.get('eligible'):
                continue
            recovery, reason = module.recovery_setup(rows5, now, previous, price, policy)
            signals.append(dict(symbol=symbol, at=now.isoformat(), execution_at=module.execution_time(now),
                price=price, previous=previous, score=result['daytrade_score'], rank=rank,
                recovery=recovery, recovery_reason=reason,
                confirming_high=rows5[-1]['high'], vwap=result.get('vwap')))
    return signals, quality


def simulate(data, signals, day, arm, ticks, path, module, policy):
    portfolio = module.Portfolio(arm, ticks, policy); quality = Counter(); orders = defaultdict(list)
    for signal in signals:
        if arm.startswith('recovery'):
            if not signal['recovery']:
                quality[signal['recovery_reason']] += 1; continue
            if module.screening_cost(signal['price'], ticks) > policy.max_roundtrip_pct:
                quality['insufficient_net_cost_room'] += 1; continue
        orders[signal['execution_at']].append(signal)
    for minute in range(9 * 60 + 31, 13 * 60):
        now = datetime.fromisoformat(day).replace(hour=minute // 60, minute=minute % 60, tzinfo=TPE)
        for symbol in list(portfolio.positions):
            row = data[symbol]['minutes'].get(now)
            if row is None or not row['volume']:
                quality['missing_execution_minute'] += 1; continue
            portfolio.tick(symbol, row['open'], now)
            if symbol in portfolio.positions and now.minute % 5 == 0:
                b5, ends = data[symbol]['b5']
                reason = module.technical_reason(b5[:bisect_right(ends, now)], now,
                                                 arm == 'recovery_structural' and portfolio.positions[symbol]['trend_active'])
                if reason:
                    portfolio.close(symbol, row['open'], now, reason)
        queue = sorted(orders[now], key=lambda r: (r['rank'], r['symbol'])) if arm in ('baseline', 'allocation_only') else sorted(
            orders[now], key=lambda r: (-r['score'], r['rank'], r['symbol']))
        for signal in queue:
            symbol = signal['symbol']; row = data[symbol]['minutes'].get(now)
            if symbol in portfolio.traded:
                continue
            if row is None or not row['volume']:
                quality['no_causal_minute_execution'] += 1; continue
            price = row['open']
            if not 1 <= price <= 2000 or (price / signal['previous'] - 1) * 100 > 8:
                quality['execution_price_outside_user_limits'] += 1; continue
            if arm.startswith('recovery') and (price > signal['confirming_high'] + float(module.tick_size(signal['confirming_high']))
                    or not signal['vwap'] or price < signal['vwap'] or price > signal['vwap'] * (1 + policy.max_chase_pct)
                    or module.screening_cost(price, ticks) > policy.max_roundtrip_pct):
                quality['execution_moved_outside_recovery_limits'] += 1; continue
            reason = portfolio.open(signal, price, now)
            if reason:
                quality[reason] += 1
        for symbol in list(portfolio.positions):
            row = data[symbol]['minutes'].get(now)
            if row is None or not row['volume']:
                continue
            points = (row['open'], row['low'], row['high'], row['close']) if path == 'low-first' else (
                row['open'], row['high'], row['low'], row['close'])
            for i in range(1, 4):
                portfolio.segment(symbol, points[i - 1], points[i], now + timedelta(seconds=i * 15))
        portfolio.mark({s: d['minutes'][now]['close'] for s, d in data.items() if now in d['minutes']})
    return dict(portfolio.summary(), day=day, path=path, skips=dict(quality))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--strategy-file', type=Path)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--bars', type=Path, required=True)
    parser.add_argument('--diagnostic-day', default='2026-10-12')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error('output_must_be_new_isolated_directory')
    output = args.output.resolve()
    for forbidden in (args.repo.resolve(), args.archive.resolve(), args.bars.resolve()):
        if output == forbidden or forbidden in output.parents:
            parser.error('output_inside_source_or_production_tree')
    sys.path.insert(0, str(args.repo))
    from daytrade_learning.historical_replay import Archive
    strategy_file = args.strategy_file or args.repo / 'daytrade_learning/a_recovery_v2.py'
    module = load_strategy(strategy_file); policy = module.Policy()
    archive = Archive(args.archive, args.diagnostic_day); helpers = radar_helpers(args.repo)
    auditor = archive_auditor(args.repo)
    available = sorted(p.name for p in args.bars.iterdir() if p.is_dir() and p.name < args.diagnostic_day
                       and (args.archive / p.name).is_dir())
    days = available[-16:]; pivot = len(days) // 2
    if (args.bars / args.diagnostic_day).is_dir() and (args.archive / args.diagnostic_day).is_dir():
        days.append(args.diagnostic_day)
    output.mkdir(parents=True, mode=0o700)
    (output / 'protocol.json').write_text(json.dumps(dict(policy=asdict_policy(module, policy),
        profile_hash=policy.fingerprint(), historical_days=days[:len(available[-16:])],
        strategy_sha256=hashlib.sha256(strategy_file.read_bytes()).hexdigest(),
        runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        production_source_sha256={name: hashlib.sha256((args.repo / name).read_bytes()).hexdigest()
            for name in ('strategy_engine.py', 'intraday_live.py', 'paper_execution.py',
                         'daytrade_learning/historical_replay.py')},
        collector_sha256=hashlib.sha256((args.repo / 'history/collector_core.py').read_bytes()).hexdigest(),
        scope='fixed_archived_universe_minute_execution_not_live_replay',
        assumptions=['market_gate_pass_assumed', 'daytrade_eligibility_assumed', 'counterparty_depth_assumed',
                     'one_minute_signal_clock', 'two_minute_paths_are_scenarios_not_bounds'],
        live_data_written=False, deployment_allowed=False), indent=2), encoding='utf-8')
    reports = []
    for index, day in enumerate(days):
        data, quality, sources = load_day(archive, args.bars, day, auditor)
        signals, checks = signals_for_day(data, day, helpers, module, policy); quality.update(checks)
        split = 'diagnostic' if day == args.diagnostic_day else 'descriptive' if index < pivot else 'holdout'
        proxy = data.get('2330'); category = 'proxy_unavailable'
        if proxy:
            rows = proxy['pack']['bars']; low_open = rows[0]['open'] < proxy['previous']
            up = rows[-1]['close'] > rows[0]['open']
            category = 'stock_proxy_low_open_up' if low_open and up else 'stock_proxy_low_open_not_up' if low_open else 'stock_proxy_other'
        results = []
        for ticks in (1, 2):
            for path in ('low-first', 'high-first'):
                for arm in module.ARMS:
                    result = simulate(data, signals, day, arm, ticks, path, module, policy)
                    result.update(split=split, proxy_category=category)
                    results.append(result); reports.append({k: v for k, v in result.items() if k != 'trades'})
        report = dict(day=day, split=split, usable_symbols=len(data), repeated_signals=len(signals),
            unique_signal_symbols=len({s['symbol'] for s in signals}), quality=dict(quality), sources=sources, results=results)
        (output / (day + '.json')).write_text(json.dumps(report, ensure_ascii=False, allow_nan=False), encoding='utf-8')
        print('DAY_RESULT ' + json.dumps(dict(day=day, split=split, usable_symbols=len(data),
            signals=len(signals), summary=[{k: r[k] for k in ('arm', 'ticks', 'closed_count', 'net_pnl', 'max_drawdown_twd')}
                                         for r in results if r['ticks'] == 1 and r['path'] == 'low-first'])), flush=True)
    summary = dict(profile_hash=policy.fingerprint(), days=len(days), reports=reports,
                   deployment_gate=module.deployment_gate(reports), live_data_written=False)
    (output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    aggregates = []
    for split in ('descriptive', 'holdout', 'diagnostic'):
        for arm in module.ARMS:
            for ticks in (1, 2):
                rows = [r for r in reports if r['split'] == split and r['arm'] == arm and r['ticks'] == ticks and r['path'] == 'low-first']
                aggregates.append(dict(split=split, arm=arm, ticks=ticks, days=len(rows),
                    closed_count=sum(r['closed_count'] for r in rows), net_pnl=round(sum(r['net_pnl'] for r in rows), 2),
                    worst_day_drawdown=max((r['max_drawdown_twd'] for r in rows), default=None)))
    print('RESULT_JSON ' + json.dumps(dict(days=len(days), profile_hash=policy.fingerprint(), aggregates=aggregates,
        deployment_gate=summary['deployment_gate'], output=str(output), live_data_written=False)), flush=True)


def asdict_policy(module, policy):
    return module.asdict(policy)


if __name__ == '__main__':
    main()
