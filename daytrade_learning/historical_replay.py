"""Fail-closed, point-in-time reconstruction from isolated Shioaji archives.

No broker session, Firebase client, live journal, paper ledger or production
model is opened by the replay path. TWSE historical TWT84U is the authoritative
source of that day's reference and limit prices. Missing references are rejected.
"""
import argparse
from bisect import bisect_right
from collections import Counter
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from .features import FEATURES, SCHEMA_VERSION
from .model_runtime import live_features
from .research import profile_hash, save, simulate, train_candidate
from .champion import promotion_gate

TPE = timezone(timedelta(hours=8))
DEFAULT_ARCHIVE = Path('/home/ubuntu/easystock-history-expanded-data/raw')
DEFAULT_OUTPUT = Path('/home/ubuntu/easystock-learning-data/replay-current-profile')
OFFICIAL_URL = 'https://www.twse.com.tw/exchangeReport/TWT84U?date={date}&response=json'
REPLAY_VERSION = 'current-profile-replay-v1'
POLICY_KEYS = ('stop_loss_pct', 'take_profit_pct', 'exit_mode', 'trailing_activate_pct',
               'trailing_pullback_pct', 'breakeven_activate_pct', 'breakeven_floor_pct')


def guard_day(day, through):
    parsed = datetime.strptime(day, '%Y-%m-%d').date().isoformat()
    if parsed > through:
        raise ValueError('source_after_cutoff')
    return parsed


def price(value):
    try:
        result = float(str(value).replace(',', '').strip())
        return result if 0 < result < 1_000_000 else None
    except (TypeError, ValueError):
        return None


def roc_date(value):
    try:
        y, m, d = [int(x) for x in str(value).split('.')]
        return datetime(y + 1911, m, d).date().isoformat()
    except (TypeError, ValueError):
        return None


class Archive:
    def __init__(self, root, through):
        self.root = Path(root)
        self.through = through

    def days(self, start):
        return sorted(p.name for p in self.root.iterdir()
                      if p.is_dir() and len(p.name) == 10 and start <= p.name <= self.through)

    def files(self, day, symbols=None):
        guard_day(day, self.through)
        directory = self.root / day
        return sorted(p for p in directory.glob('*.json.gz')
                      if p.stem.endswith('.json') and (symbols is None or p.name[:-8] in symbols))

    def read(self, path, day):
        guard_day(day, self.through)
        if path.parent != self.root / day or not path.name.endswith('.json.gz'):
            raise ValueError('archive_path_out_of_scope')
        raw = path.read_bytes()
        payload = json.loads(gzip.decompress(raw))
        if payload.get('date') != day or payload.get('symbol') != path.name[:-8]:
            raise ValueError('archive_identity_mismatch')
        for name, fields in (('ticks', ('ts', 'close', 'volume', 'tick_type')),
                             ('kbars', ('ts', 'Open', 'High', 'Low', 'Close', 'Volume'))):
            block = payload.get(name)
            if not isinstance(block, dict) or not block.get('ts'):
                raise ValueError('missing_' + name)
            n = len(block['ts'])
            if any(len(block.get(field, [])) != n for field in fields):
                raise ValueError('invalid_' + name + '_columns')
            if any(a > b for a, b in zip(block['ts'], block['ts'][1:])):
                raise ValueError('unsorted_' + name)
        return payload, hashlib.sha256(raw).hexdigest()


class References:
    def __init__(self, cache, through, fetch=None):
        self.cache = Path(cache)
        self.through = through
        self.fetch = fetch or self._fetch

    @staticmethod
    def _fetch(day):
        request = Request(OFFICIAL_URL.format(date=day.replace('-', '')),
                          headers={'User-Agent': 'EasyStock historical research/1.0'})
        for attempt in range(3):
            try:
                with urlopen(request, timeout=25) as response:
                    if response.status != 200:
                        raise ValueError('official_http_error')
                    raw = response.read(2_000_001)
                    if len(raw) > 2_000_000:
                        raise ValueError('official_response_too_large')
                    return raw
            except (HTTPError, URLError, TimeoutError):
                if attempt == 2:
                    raise
                time.sleep(1 + attempt * 2)

    def get(self, day, *, persist=True):
        guard_day(day, self.through)
        target = self.cache / (day + '.json')
        raw = target.read_bytes() if target.exists() else self.fetch(day)
        data = json.loads(raw)
        if data.get('stat') != 'OK' or str(data.get('date')) != day.replace('-', ''):
            raise ValueError('official_date_or_status_mismatch')
        fields = data.get('fields') or []
        if len(fields) < 10 or fields[0] != '證券代號' or fields[2] != '漲停價' or fields[4] != '跌停價':
            raise ValueError('official_schema_mismatch')
        # TWT84U's first auction reference is for the queried day.
        rows = {}
        for row in data.get('data') or []:
            if not isinstance(row, list) or len(row) < 10:
                continue
            symbol = str(row[0]).strip()
            reference, up, down = price(row[3]), price(row[2]), price(row[4])
            last_trade = roc_date(row[9])
            if len(symbol) == 4 and symbol.isdigit() and reference and up and down and last_trade:
                if down < reference < up and last_trade < day:
                    rows[symbol] = {'reference': reference, 'limit_up': up,
                                    'limit_down': down, 'last_trade_date': last_trade}
        if not rows:
            raise ValueError('official_no_valid_stocks')
        if persist and not target.exists():
            self.cache.mkdir(parents=True, exist_ok=True, mode=0o700)
            save(target, data)
        canonical = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
        return rows, hashlib.sha256(canonical).hexdigest()


def pack_bars(payload, reference, day):
    b = payload['kbars']
    rows = []
    for i, raw in enumerate(b['ts']):
        # Shioaji archive nanoseconds encode Taiwan wall-clock as naive UTC.
        end = datetime.fromtimestamp(int(raw) / 1e9, timezone.utc).replace(tzinfo=TPE)
        if end.date().isoformat() != day:
            raise ValueError('future_or_wrong_day_bar')
        start = end - timedelta(minutes=1)
        if not (9 <= start.hour <= 13):
            continue
        o, h, l, c, v = (float(b[k][i]) for k in ('Open', 'High', 'Low', 'Close', 'Volume'))
        if not 0 < l <= min(o, c) <= max(o, c) <= h or v < 0:
            raise ValueError('bad_ohlcv')
        rows.append({'at': start.isoformat(), 'open': o, 'high': h, 'low': l,
                     'close': c, 'volume': v})
    return {'date': day,
            'previous_close': {'date': reference['last_trade_date'], 'price': reference['reference']},
            'limit_up': reference['limit_up'], 'limit_down': reference['limit_down'],
            'bars': rows}


def prepared_ticks(payload, day):
    t = payload['ticks']
    # Convert the SDK's encoded wall-clock to actual UTC epoch exactly once.
    seconds = [int(n) / 1e9 - 8 * 3600 for n in t['ts']]
    if any(datetime.fromtimestamp(s, TPE).date().isoformat() != day for s in seconds):
        raise ValueError('future_or_wrong_day_tick')
    events = [(s, float(v), int(kind), float(px), float(v) * float(px) * 1000)
              for s, v, kind, px in zip(seconds, t['volume'], t['tick_type'], t['close'])]
    return seconds, events


def canonical_policy(journal_file, day):
    """Use an actually recorded runtime policy, never infer it from a hash."""
    policy = None
    with Path(journal_file).open(encoding='utf-8') as source:
        for line in source:
            item = json.loads(line)
            if item.get('kind') != 'sample':
                continue
            sample = item.get('data') or {}
            if str(sample.get('observed_at', ''))[:10] != day:
                continue
            candidate = sample.get('policy')
            if not isinstance(candidate, dict) or any(k not in candidate for k in ('stop_loss_pct', 'take_profit_pct', 'entry_filters')):
                continue
            if policy is not None and any(policy.get(k) != candidate.get(k) for k in POLICY_KEYS + ('entry_filters',)):
                raise ValueError('mixed_runtime_policies')
            policy = candidate
    if policy is None:
        raise ValueError('no_observed_runtime_policy')
    return policy


def costs_from_runtime():
    root = Path(__file__).resolve().parent
    settings = json.loads((root / 'settings.json').read_text(encoding='utf-8'))
    try:
        from easystock_admin.store import read_pipeline_settings
        pipeline = read_pipeline_settings()
        for key in ('fee_rate', 'minimum_fee_twd', 'sell_tax_rate', 'slippage_bps', 'shares'):
            settings[key] = pipeline[key]
    except (ImportError, OSError):
        pass
    for key in ('fee_rate', 'minimum_fee_twd', 'sell_tax_rate', 'slippage_bps', 'shares'):
        settings[key] = float(settings[key])
    return settings


def sample_at(payload, day, cutoff, reference, policy, tick_cache=None):
    # Import the production radar functions; never maintain a second algorithm.
    from intraday_live import compute_volume_surge_metrics, qualifies_volume_surge, score_volume_surge
    seconds, events = tick_cache if tick_cache is not None else prepared_ticks(payload, day)
    last = bisect_right(seconds, cutoff.timestamp()) - 1
    if last < 0:
        return None
    past = events[:last + 1]
    radar = compute_volume_surge_metrics(past, cutoff.timestamp())
    if not radar:
        return None
    point = past[-1]
    features = live_features(price=point[3], previous_close=reference['reference'],
                             now_ts=cutoff.timestamp(), ticks=past, radar=radar)
    if features is None:
        return None
    return {'symbol': payload['symbol'], 'observed_at': cutoff.isoformat(),
            'quote_at': datetime.fromtimestamp(point[0], TPE).isoformat(),
            'price': point[3],
            'return_5m_pct': features['return_5m_pct'], 'metrics': radar,
            'radar_selected': False, 'policy': policy, '_features': features,
            '_radar_pass': qualifies_volume_surge(radar),
            '_radar_score': score_volume_surge(radar)}


def replay_day(archive, references, day, costs, policy, expected_profile, symbols=None,
               *, persist=False, output=None, commit='unknown'):
    from .research import dt
    refs, reference_sha = references.get(day, persist=persist)
    rejects = Counter()
    packs = {}
    sources = {}
    for path in archive.files(day, symbols):
        symbol = path.name[:-8]
        ref = refs.get(symbol)
        if not ref:
            rejects['missing_official_twse_reference'] += 1
            continue
        try:
            payload, source_sha = archive.read(path, day)
            packs[symbol] = (payload, pack_bars(payload, ref, day), ref, prepared_ticks(payload, day))
            sources[symbol] = (path, source_sha)
        except (OSError, EOFError, ValueError, KeyError, TypeError) as exc:
            rejects['bad_archive:' + type(exc).__name__] += 1
    rows = []
    next_free = {}
    # Same five-minute cadence as Recorder.sample. The exact live scheduler
    # microsecond is unavailable historically and is recorded as an approximation.
    for minute in range(9 * 60 + 30, 12 * 60 + 30, 5):
        cutoff = datetime.fromisoformat(day).replace(
            hour=minute // 60, minute=minute % 60, second=3, tzinfo=TPE)
        samples = {}
        for symbol, (payload, pack, ref, tick_cache) in packs.items():
            try:
                sample = sample_at(payload, day, cutoff, ref, policy, tick_cache)
                if sample:
                    samples[symbol] = sample
                else:
                    rejects['no_valid_point_in_time_feature'] += 1
            except (OSError, ValueError, TypeError, KeyError) as exc:
                rejects['sample_error:' + type(exc).__name__] += 1
        eligible = sorted((s for s in samples.values() if s['_radar_pass']),
                          key=lambda s: (s['_radar_score'], s['metrics']['surge_60s'],
                                         s['metrics']['amount_60s']), reverse=True)[:30]
        top = {s['symbol'] for s in eligible}
        for symbol, sample in samples.items():
            if cutoff < next_free.get(symbol, datetime.min.replace(tzinfo=TPE)):
                rejects['overlapping_signal'] += 1
                continue
            sample['radar_selected'] = symbol in top
            sample.pop('_features'); sample.pop('_radar_pass'); sample.pop('_radar_score')
            try:
                row, reason = simulate(sample, packs[symbol][1], costs)
            except (KeyError, ValueError, TypeError, OverflowError):
                row, reason = None, 'invalid_simulation'
            if not row:
                rejects[reason or 'unresolved'] += 1
                continue
            if row['profile'] != expected_profile:
                raise ValueError('replay_profile_mismatch')
            source, source_sha = sources[symbol]
            row.update(sample_at=sample['observed_at'],
                       feature_cutoff_at=sample['observed_at'],
                       entry_at=((dt(sample['observed_at']) + timedelta(seconds=2)).replace(
                           second=0, microsecond=0) + timedelta(minutes=1)).isoformat(),
                       source_file=source.relative_to(archive.root).as_posix(),
                       source_sha256=source_sha, reference_sha256=reference_sha,
                       feature_schema_version=SCHEMA_VERSION, replay_version=REPLAY_VERSION,
                       code_commit_sha=commit, cost_profile_hash=expected_profile,
                       outcome_source='archived_shioaji_minute_bars',
                       universe_scope='fixed_archived_universe_twse_only',
                       sample_schedule='five_minute_bucket_plus_three_seconds')
            rows.append(row)
            next_free[symbol] = dt(row['exit_at']) + timedelta(minutes=1)
    report = {'date': day, 'profile': expected_profile, 'archive_files': len(archive.files(day, symbols)),
              'usable_symbols': len(packs), 'samples': len(rows), 'positive': sum(r['net_return_pct'] > 0 for r in rows),
              'negative': sum(r['net_return_pct'] <= 0 for r in rows), 'rejects': dict(rejects),
              'reference_sha256': reference_sha, 'replay_version': REPLAY_VERSION, 'code_commit_sha': commit}
    if persist:
        save(output / 'labels' / (day + '.json'), rows)
        save(output / 'reports' / (day + '.json'), report)
    return report, rows


def merge_live(replay, live, profile):
    """One row per 5-minute symbol bucket; observed live wins conflicts."""
    def key(row):
        when = datetime.fromisoformat(row.get('sample_at') or row['at'])
        return row['symbol'], row['date'], when.hour * 12 + when.minute // 5, row['profile']
    merged = {key(r): r for r in replay if r.get('profile') == profile}
    for row in live:
        if row.get('profile') == profile:
            merged[key(row)] = row
    return sorted(merged.values(), key=lambda r: (r['at'], r['symbol']))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--from', dest='start', required=True)
    parser.add_argument('--through', required=True)
    parser.add_argument('--archive', type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--live-data', type=Path, default=Path('/home/ubuntu/easystock-learning-data'))
    parser.add_argument('--policy-day', default='2026-10-02')
    parser.add_argument('--expected-profile', required=True)
    parser.add_argument('--audit-only', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--date')
    parser.add_argument('--symbols')
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--train', action='store_true')
    args = parser.parse_args(argv)
    start, through = (datetime.strptime(x, '%Y-%m-%d').date().isoformat()
                      for x in (args.start, args.through))
    if start > through or args.policy_day > through or (args.date and not start <= args.date <= through):
        parser.error('invalid_date_or_cutoff')
    archive = Archive(args.archive, through)
    dates = [args.date] if args.date else archive.days(start)
    if args.audit_only:
        counts = [len(archive.files(day)) for day in dates]
        print(json.dumps({'mode': 'audit-only', 'range': [dates[0], dates[-1]] if dates else [],
                          'trading_dates': len(dates), 'stock_days': sum(counts),
                          'min_stocks': min(counts) if counts else 0,
                          'max_stocks': max(counts) if counts else 0,
                          'reference_source': 'TWSE TWT84U historical daily; TPEX excluded',
                          'labels_written': False}, ensure_ascii=False))
        return
    policy = canonical_policy(args.live_data / ('journal-' + args.policy_day + '.jsonl'), args.policy_day)
    costs = costs_from_runtime()
    actual_profile = profile_hash(costs, policy)
    if actual_profile != args.expected_profile:
        raise SystemExit('profile_mismatch: canonical costs/policy do not match requested profile')
    references = References(args.output / 'references', through)
    symbols = set(args.symbols.split(',')) if args.symbols else None
    commit = os.environ.get('EASYSTOCK_CODE_COMMIT', 'uncommitted')
    summaries = []
    failed_dates = []
    start_clock = time.monotonic()
    for index, day in enumerate(dates, 1):
        previous = args.output / 'reports' / (day + '.json')
        label_path = args.output / 'labels' / (day + '.json')
        if args.resume and not args.dry_run and previous.exists() and label_path.exists():
            report = json.loads(previous.read_text(encoding='utf-8'))
            if report.get('profile') != actual_profile or report.get('replay_version') != REPLAY_VERSION:
                raise SystemExit('incompatible_replay_checkpoint')
            summaries.append(report)
            continue
        try:
            report, _ = replay_day(archive, references, day, costs, policy, actual_profile, symbols,
                                   persist=not args.dry_run, output=args.output, commit=commit)
            summaries.append(report)
        except (OSError, EOFError, ValueError, KeyError, TypeError) as exc:
            failed_dates.append(day)
            if not args.dry_run:
                save(args.output / 'rejects' / (day + '.json'),
                     {'date': day, 'reason': type(exc).__name__, 'detail': str(exc)[:100]})
            print(json.dumps({'date': day, 'error': type(exc).__name__}, ensure_ascii=False), flush=True)
        elapsed = max(.001, time.monotonic() - start_clock)
        print(json.dumps({'processed': index, 'total': len(dates), 'date': day,
                          'samples': summaries[-1]['samples'] if summaries and summaries[-1]['date'] == day else 0,
                          'days_per_minute': round(index * 60 / elapsed, 2)}, ensure_ascii=False), flush=True)
    valid = [r for r in summaries if r.get('samples', 0)]
    summary = {'profile': actual_profile, 'trading_dates': len(valid),
               'valid_samples': sum(r['samples'] for r in valid),
               'positive': sum(r['positive'] for r in valid),
               'negative': sum(r['negative'] for r in valid),
               'rejected': dict(sum((Counter(r['rejects']) for r in summaries), Counter())),
               'date_range': [valid[0]['date'], valid[-1]['date']] if valid else [],
               'scope': 'fixed archived universe, TWSE only; no historical scanner or provider health'}
    if not args.dry_run:
        save(args.output / 'audit.json', summary)
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    if not args.train or args.dry_run:
        return
    if failed_dates or len(summaries) != len(dates):
        raise SystemExit('replay_days_failed_before_training')
    if summary['trading_dates'] < 101 or summary['valid_samples'] < 1000:
        raise SystemExit('full_walk_forward_dataset_gate_not_met')
    corpus = args.output / 'corpus' / (start + '_through_' + through + '_' + actual_profile)
    existing = {p.stem for p in (corpus / 'labels').glob('*.json')}
    if existing - set(dates):
        raise SystemExit('stale_corpus_dates_refuse_training')
    for day in dates:
        replay_file = args.output / 'labels' / (day + '.json')
        if not replay_file.exists():
            continue
        replay = json.loads(replay_file.read_text(encoding='utf-8'))
        live_file = args.live_data / 'labels' / (day + '.json')
        live = json.loads(live_file.read_text(encoding='utf-8')) if live_file.exists() else []
        save(corpus / 'labels' / (day + '.json'), merge_live(replay, live, actual_profile))
    from easystock_admin.store import read_pipeline_settings
    controls = read_pipeline_settings()
    if float(controls.get('model_threshold', .6)) != .6:
        raise SystemExit('unexpected_threshold')
    candidate = train_candidate(corpus, controls, allow_paper_bootstrap=False)
    gate = promotion_gate(candidate) if candidate.get('status') == 'candidate_only' else None
    outcome = {'candidate_status': candidate.get('status'),
               'validation_mode': candidate.get('validation_mode'),
               'trained_through': candidate.get('trained_through'),
               'folds': candidate.get('folds', []), 'promotion_gate': gate,
               'production_latest_approved_untouched': True}
    save(args.output / 'evaluation.json', outcome)
    print(json.dumps(outcome, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
