"""Read-only, all-minute-pack independent entry research. No SDK or live writes."""
from __future__ import annotations

import argparse
from bisect import bisect_right
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

TPE = timezone(timedelta(hours=8))


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_day(root, day, helpers):
    quality = Counter(); stocks = {}; sources = []
    for path in sorted((root / day).glob('*.json')):
        if len(path.stem) != 4 or not path.stem.isdigit() or path.stem.startswith('0'):
            quality['not_ordinary_stock_code'] += 1; continue
        try:
            raw = path.read_bytes(); pack = json.loads(raw); rows = pack['bars']
            reference = pack.get('previous_close') or {}
            if (pack['date'] != day or pack.get('symbol', path.stem) != path.stem
                    or not reference.get('date') or reference['date'] >= day
                    or not isinstance(reference.get('price'), (float, int))
                    or not math.isfinite(reference['price']) or reference['price'] <= 0):
                quality['missing_or_invalid_historical_reference'] += 1; continue
            start = datetime.fromisoformat(day).replace(hour=9, tzinfo=TPE)
            stamps = [datetime.fromisoformat(r['at']) for r in rows]
            if (len(rows) != 270 or any(s.tzinfo is None or s.utcoffset() != timedelta(hours=8)
                    or s != start + timedelta(minutes=i) for i, s in enumerate(stamps))):
                raise ValueError('incomplete_or_invalid_timestamps')
            for r in rows:
                o, h, l, c, v = [float(r[k]) for k in ('open', 'high', 'low', 'close', 'volume')]
                if (not all(math.isfinite(x) for x in (o, h, l, c, v))
                        or not 0 < l <= min(o, c) <= max(o, c) <= h or v < 0):
                    raise ValueError('invalid_ohlcv')
                r.update(open=o, high=h, low=l, close=c, volume=v)
            stocks[path.stem] = dict(previous=reference['price'], pack=pack,
                minutes=dict(zip(stamps, rows)), b5=helpers.group_bars(rows, 5),
                b15=helpers.group_bars(rows, 15))
            sources.append(dict(symbol=path.stem, minute_sha256=hashlib.sha256(raw).hexdigest(),
                                previous_close_date=reference['date']))
        except (ValueError, KeyError, TypeError, OSError):
            quality['invalid_minute_pack'] += 1
    return stocks, quality, sources


class RecordedRadar:
    """Verified callback evidence only. Missing radar never rejects research signals."""
    def __init__(self, root, day, helpers):
        self.frames = []; self.times = []; self.sources = []; self.quality = Counter()
        self.missing_status = 'not_loaded' if root is None else 'not_recorded'
        if root is None:
            return
        for path in sorted((root / day).glob('*.manifest.json')):
            try:
                meta = json.loads(path.read_text(encoding='utf-8'))
                if not meta.get('complete') or meta.get('dropped') or meta.get('errors'):
                    self.quality['incomplete_recording_not_used'] += 1; continue
                name = meta['file']
                if Path(name).name != name:
                    raise ValueError('unsafe_recording_path')
                raw_path = path.parent / name
                digest = hashlib.sha256()
                with raw_path.open('rb') as source:
                    for chunk in iter(lambda:source.read(1024*1024), b''):
                        digest.update(chunk)
                sha = digest.hexdigest()
                if sha != meta['sha256']:
                    raise ValueError('recording_hash_mismatch')
                frames = []
                with gzip.open(raw_path, 'rb') as recording:
                    for line in recording:
                        if b'"kind":"radar"' not in line and b'"kind": "radar"' not in line:
                            continue
                        item = json.loads(line)
                        if item.get('kind') != 'radar':
                            continue
                        data = item['data']; at = datetime.fromisoformat(data['now'])
                        if at.tzinfo is None or at.astimezone(TPE).date().isoformat() != day:
                            raise ValueError('invalid_recording_time')
                        qualified = [r for r in data['rows'] if helpers['qualifies_volume_surge'](r)]
                        qualified.sort(key=lambda r: (helpers['score_volume_surge'](r),
                            r.get('surge_60s') or 0, r.get('amount_60s') or 0, str(r['symbol'])), reverse=True)
                        admitted = {str(r['symbol']) for r in qualified[:30]}
                        frames.append((at, {str(r['symbol']):r for r in data['rows']}, admitted))
                self.frames.extend(frames)
                self.sources.append(dict(file=name, sha256=sha, radar_frames=len(frames),
                    original_file=meta.get('original_file',name),
                    original_sha256=meta.get('original_sha256',sha),
                    projection=meta.get('projection','original')))
            except (ValueError, KeyError, TypeError, OSError, EOFError):
                self.quality['invalid_recording_not_used'] += 1
        self.frames.sort(key=lambda f:f[0]); self.times = [f[0] for f in self.frames]

    def evidence(self, symbol, now):
        index = bisect_right(self.times, now) - 1
        if index < 0:
            return {'legacy_radar_status':self.missing_status}, {}
        at, rows, admitted = self.frames[index]
        if (now - at).total_seconds() > 30:
            return {'legacy_radar_status':'stale_recorded_snapshot'}, {}
        row = rows.get(symbol)
        return dict(legacy_radar_status='in_recorded_radar' if row else 'not_in_recorded_radar',
                    legacy_radar_eligible=symbol in admitted, legacy_radar_at=at.isoformat()), row or {}


def signals_for_day(stocks, day, core, common, policy, radar, evaluate):
    signals = []; quality = Counter()
    for minute in range(9 * 60 + 30, 12 * 60 + 30, 5):
        now = datetime.fromisoformat(day).replace(hour=minute // 60, minute=minute % 60, second=3, tzinfo=TPE)
        for symbol, stock in sorted(stocks.items()):
            b5, ends5 = stock['b5']; b15, ends15 = stock['b15']
            rows5 = b5[:bisect_right(ends5, now)]
            patterns, reason = core.entry_patterns(rows5, now, stock['previous'], policy)
            if not patterns:
                quality[reason] += 1; continue
            recorded, radar_row = radar.evidence(symbol, now)
            price = rows5[-1]['close']
            legacy = dict(legacy_rule_score=None, legacy_rule_eligible=None,
                          legacy_hard_vetoes=[], legacy_score_context='unknown')
            try:
                result = evaluate(rows5, b15[:bisect_right(ends15, now)],
                    stock=dict(radar_row, price=price, previous_close=stock['previous']),
                    market_level='GREEN', market_regime='NORMAL')
                legacy = dict(legacy_rule_score=result.get('daytrade_score'),
                    legacy_rule_eligible=result.get('eligible'),
                    legacy_hard_vetoes=result.get('hard_vetoes') or [],
                    legacy_score_context='recorded_radar_assumed_market' if radar_row else 'minute_only_assumed_market')
            except Exception as exc:
                quality['legacy_score_unavailable_kept_signal'] += 1
                legacy['legacy_score_context'] = 'unavailable:' + type(exc).__name__
            for pattern in patterns.values():
                signals.append(dict(pattern, **legacy, **recorded, symbol=symbol, at=now.isoformat(),
                    id=f"{day}:{symbol}:{now.strftime('%H:%M:%S')}:{pattern['pattern']}",
                    execution_at=common.execution_time(now).isoformat(), price=price, previous=stock['previous']))
    return signals, quality


def simulate(stocks, signals, day, arm, ticks, path, core, common, policy):
    if arm not in core.ARMS or path not in ('low-first', 'high-first'):
        raise ValueError('invalid_scenario')
    book = common.Portfolio('allocation_only', ticks, policy)
    orders = defaultdict(list); skips = Counter(); fills = {}; decisions = []
    def decision(signal, status, reason=None):
        decisions.append(dict(signal_id=signal['id'], status=status, reason=reason))
    for signal in signals:
        if not core.selected_for_arm(signal, arm):
            if arm == 'union_score68_control':
                skips['legacy_rule_control_rejected'] += 1
                decision(signal, 'skipped', 'legacy_rule_control_rejected')
            else:
                decision(signal, 'not_selected', 'other_pattern')
            continue
        if common.screening_cost(signal['price'], ticks) > policy.max_roundtrip_pct:
            skips['signal_insufficient_net_cost_room'] += 1
            decision(signal, 'skipped', 'signal_insufficient_net_cost_room'); continue
        orders[common.aware(signal['execution_at'])].append(signal)
    for minute in range(9 * 60 + 31, 13 * 60 + 30):
        now = datetime.fromisoformat(day).replace(hour=minute // 60, minute=minute % 60, tzinfo=TPE)
        for symbol in list(book.positions):
            row = stocks[symbol]['minutes'].get(now)
            if not row or row['volume'] <= 0:
                skips['no_trading_minute_for_exit'] += 1; continue
            if now.hour * 60 + now.minute > 12 * 60 + 55:
                skips['delayed_liquidation_trading_minute'] += 1
            book.tick(symbol, row['open'], now)
            if symbol in book.positions and now.minute % 5 == 0:
                rows, ends = stocks[symbol]['b5']
                reason = common.technical_reason(rows[:bisect_right(ends, now)], now, False)
                if reason:
                    book.close(symbol, row['open'], now, reason)
        for signal in sorted(orders[now], key=core.priority):
            symbol = signal['symbol']
            if symbol in book.traded:
                skips['same_stock_or_duplicate_pattern'] += 1
                decision(signal, 'skipped', 'same_stock_or_duplicate_pattern'); continue
            row = stocks[symbol]['minutes'].get(now)
            if not row or row['volume'] <= 0:
                skips['no_execution_trade_price_proxy'] += 1
                decision(signal, 'skipped', 'no_execution_trade_price_proxy'); continue
            reason = core.execution_guard(signal, row['open'], ticks, policy)
            if reason is None:
                reason = book.open(signal, row['open'], now)
                if reason is None:
                    fills[symbol] = signal
                    book.positions[symbol]['signal_id'] = signal['id']
                    decision(signal, 'hypothetical_fill')
            if reason:
                skips[reason] += 1
                decision(signal, 'skipped', reason)
        prices = {s:stocks[s]['minutes'][now]['open'] for s in book.positions
                  if now in stocks[s]['minutes'] and stocks[s]['minutes'][now]['volume'] > 0}
        book.mark(prices)
        for phase in range(1, 4):
            for symbol in list(book.positions):
                row = stocks[symbol]['minutes'].get(now)
                if not row or row['volume'] <= 0:
                    continue
                points = [row['open'], row['low'], row['high'], row['close']] if path == 'low-first' else [
                          row['open'], row['high'], row['low'], row['close']]
                book.segment(symbol, points[phase-1], points[phase], now + timedelta(seconds=phase*15))
                prices[symbol] = points[phase]
            book.mark(prices)
    for trade in book.trades:
        signal = fills[trade['symbol']]
        trade.update(pattern=signal['pattern'], legacy_rule_score=signal['legacy_rule_score'],
            legacy_rule_eligible=signal['legacy_rule_eligible'],
            legacy_radar_status=signal.get('legacy_radar_status', 'not_recorded'))
    return dict(book.summary(), arm=arm, day=day, path=path, skips=dict(skips), decisions=decisions)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--core-file', type=Path)
    parser.add_argument('--common-file', type=Path)
    parser.add_argument('--helpers-file', type=Path)
    parser.add_argument('--bars', type=Path, required=True)
    parser.add_argument('--recordings', type=Path)
    parser.add_argument('--diagnostic-day', default='2026-10-12')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    output = args.output.resolve()
    forbidden = [args.repo.resolve(), args.bars.resolve()]
    if args.recordings:
        forbidden.append(args.recordings.resolve())
    if output.exists() or any(output == p or p in output.parents for p in forbidden):
        parser.error('output_must_be_new_and_outside_source_or_production')
    sys.path.insert(0, str(args.repo))
    common_file = args.common_file or args.repo / 'daytrade_learning/a_recovery_v2.py'
    core_file = args.core_file or args.repo / 'daytrade_learning/a_independent_recovery_v3.py'
    helpers_file = args.helpers_file or args.repo / 'deploy/backtest_a_recovery_v2.py'
    common = load_module('daytrade_learning.a_recovery_v2', common_file)
    core = load_module('daytrade_learning.a_independent_recovery_v3', core_file)
    helpers = load_module('isolated_common_replay_helpers', helpers_file)
    from strategy_engine import evaluate_daytrade, MAX_ROUNDTRIP_COST_PCT
    policy = core.Policy()
    historical = sorted(p.name for p in args.bars.iterdir() if p.is_dir()
                        and len(p.name) == 10 and p.name < args.diagnostic_day)[-16:]
    days = historical + ([args.diagnostic_day] if (args.bars / args.diagnostic_day).is_dir() else [])
    pivot = len(historical) // 2
    output.mkdir(mode=0o700, parents=True)
    files = dict(core=core_file, common=common_file, runner=Path(__file__), helpers=helpers_file,
                 old_rules=args.repo/'strategy_engine.py', costs=args.repo/'paper_execution.py',
                 old_radar=args.repo/'intraday_live.py')
    protocol = dict(policy=core.asdict(policy), profile_hash=policy.fingerprint(),
        source_sha256={k:hashlib.sha256(p.read_bytes()).hexdigest() for k,p in files.items()},
        days=days, legacy_max_roundtrip_cost_pct=MAX_ROUNDTRIP_COST_PCT,
        recordings_configured=args.recordings is not None,
        scope='independent_entry_all_complete_minute_packs',
        assumptions=['retrospective_universe', 'market_gate_pass_assumed', 'eligibility_and_depth_assumed',
            'minute_open_trade_price_proxy', 'all_evaluation_dates_reused_not_untouched',
            'minute_paths_are_scenarios_not_bounds'], deployment_allowed=False, live_data_written=False)
    (output/'protocol.json').write_text(json.dumps(protocol, indent=2), encoding='utf-8')
    reports = []
    for i, day in enumerate(days):
        stocks, quality, sources = load_day(args.bars, day, helpers)
        radar = RecordedRadar(args.recordings, day, helpers.radar_helpers(args.repo))
        signals, checks = signals_for_day(stocks, day, core, common, policy, radar, evaluate_daytrade)
        quality.update(checks); quality.update(radar.quality)
        split = 'diagnostic' if day == args.diagnostic_day else 'descriptive' if i < pivot else 'reused_history'
        results = []
        for ticks in (1, 2):
            for path in ('low-first', 'high-first'):
                for arm in core.ARMS:
                    result = simulate(stocks, signals, day, arm, ticks, path, core, common, policy)
                    result['split'] = split; results.append(result)
                    reports.append({k:v for k,v in result.items() if k not in ('trades', 'decisions')})
        report = dict(day=day, split=split, usable_symbols=len(stocks), signals=signals,
            unique_signal_symbols=len({s['symbol'] for s in signals}), quality=dict(quality),
            sources=sources, radar_sources=radar.sources, results=results)
        (output/(day+'.json')).write_text(json.dumps(report, ensure_ascii=False, allow_nan=False), encoding='utf-8')
        print('DAY_RESULT '+json.dumps(dict(day=day, split=split, usable_symbols=len(stocks),
            pattern_counts=dict(Counter(s['pattern'] for s in signals)),
            old_rule_eligible_signals=sum(s['legacy_rule_eligible'] is True for s in signals),
            summary=[{k:r[k] for k in ('arm','closed_count','net_pnl','max_drawdown_twd')}
                     for r in results if r['ticks']==1 and r['path']=='low-first'])), flush=True)
    summary = dict(profile_hash=policy.fingerprint(), reports=reports, days=len(days), live_data_written=False,
        deployment_gate=dict(deployment_allowed=False, reasons=['reused_dates_not_independent_validation',
            'missing_complete_forward_market_eligibility_depth_and_callbacks']))
    (output/'summary.json').write_text(json.dumps(summary, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    print('FINISHED '+json.dumps(dict(days=len(days), output=str(output), deployment_allowed=False)), flush=True)


if __name__ == '__main__':
    main()
