"""Bounded cross-provider signal-only trial using a read-only live journal tail."""
import argparse
from collections import Counter
from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time


def parse(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[1])
    p.add_argument('--module-file', type=Path)
    p.add_argument('--journal', type=Path, required=True)
    p.add_argument('--bridge', type=Path, required=True)
    p.add_argument('--node', default='/usr/bin/node')
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--seconds', type=int, default=90)
    p.add_argument('--warmup', type=int, default=15)
    args = p.parse_args(argv)
    output = args.output.resolve()
    protected = [args.repo.resolve(), args.journal.resolve().parent,
                 Path('/home/ubuntu/easystock-admin'), Path('/home/ubuntu/easystock-market-data'),
                 Path('/home/ubuntu/easystock-runway-v2')]
    if (output.exists() or any(output == q or q in output.parents for q in protected)
            or not 30 <= args.seconds <= 90 or not 5 <= args.warmup < args.seconds):
        p.error('new_private_output_and_bounded_duration_required')
    return args


def main(argv=None):
    args = parse(argv)
    sys.path.insert(0, str(args.repo.resolve()))
    source = args.module_file or args.repo / 'market_data/b_shadow.py'
    spec = importlib.util.spec_from_file_location('isolated_b_shadow', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    now = datetime.now(module.TPE)
    tail = module.JournalTail(args.journal)
    initial = tail.poll()
    now = datetime.now(module.TPE)
    radar = next((e['data'] for e in reversed(initial) if e['kind'] == 'radar'), None)
    # Wait only for genuine new metadata; do not refresh a stale radar timestamp.
    seed_deadline = time.monotonic() + 15
    while (not radar or not 0 <= (now - module.stamp(radar['now'])).total_seconds() <= 30) and time.monotonic() < seed_deadline:
        time.sleep(.2)
        extra = tail.poll()
        initial.extend(extra)
        if len(initial) > 30000:
            raise ValueError('initial_event_budget')
        radar = next((e['data'] for e in reversed(extra) if e['kind'] == 'radar'), radar)
        now = datetime.now(module.TPE)
    if not radar or not 0 <= (now - module.stamp(radar['now'])).total_seconds() <= 30:
        raise ValueError('no_fresh_source_radar')
    symbols = module.affordable_pool(radar['rows'])
    if not symbols:
        raise ValueError('no_affordable_symbols')
    args.output.mkdir(mode=0o700, parents=True)
    study = module.ShadowComparison(args.output, symbols, now)
    messages = queue.Queue(maxsize=10000)
    child = None
    reader = None
    counters = Counter()
    protocol = {'mode': 'shadow_signal_only', 'started_at': now.isoformat(), 'symbols': symbols,
        'book_source': 'esun', 'tick_source': 'shioaji_live_journal', 'warmup_seconds': args.warmup,
        'maximum_run_seconds': args.seconds, 'journal_file': args.journal.name,
        'live_journal_incomplete_not_backtest': True, 'execution_allowed': False,
        'size_units_contract_verified': False, 'production_changed': False, 'training_eligible': False,
        'source_sha256': {k: hashlib.sha256(p.read_bytes()).hexdigest() for k, p in {
            'driver': Path(__file__), 'module': source, 'bridge': args.bridge,
            'probe': args.bridge.parent / 'probe_esun_b_books.cjs',
            'native_lanes': args.repo / 'runway_v2/lanes.py'}.items()}}
    (args.output / 'protocol.json').write_text(json.dumps(protocol, indent=2), encoding='utf-8')
    def capture():
        for line in child.stdout:
            try:
                message = json.loads(line)
                if not isinstance(message, dict):
                    raise ValueError()
                messages.put_nowait(message)
            except queue.Full:
                counters['bridge_queue_overflow'] += 1
            except ValueError:
                counters['bridge_invalid_json'] += 1
    snapshots = []
    stopped = None
    bridge_report = None
    wall_started = time.monotonic()
    try:
        for event in initial:
            study.ingest_source(event, datetime.now(module.TPE))
        command = [args.node, str(args.bridge), '--seconds', str(args.seconds),
                   '--symbols', ','.join(symbols)]
        child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                 text=True, encoding='utf-8')
        reader = threading.Thread(target=capture, daemon=True)
        reader.start()
        next_clock = next_status = wall_started
        with (args.output / 'events.jsonl').open('w', encoding='utf-8') as log:
            while time.monotonic() - wall_started < args.seconds:
                now = datetime.now(module.TPE)
                try:
                    for event in tail.poll():
                        study.ingest_source(event, datetime.now(module.TPE))
                except (ValueError, OSError):
                    study.source_failed = True
                    stopped = 'journal_source_failed'
                    break
                while True:
                    try:
                        message = messages.get_nowait()
                    except queue.Empty:
                        break
                    if message.get('kind') == 'finished':
                        bridge_report = message.get('report')
                    else:
                        handled_at = datetime.now(module.TPE)
                        study.ingest_esun(message, handled_at)
                    # No credential/SDK payload is projected by the bridge.
                    log.write(json.dumps({'observed_at': datetime.now(module.TPE).isoformat(), **message}, ensure_ascii=False) + '\n')
                if counters['bridge_queue_overflow'] or counters['bridge_invalid_json']:
                    stopped = 'bridge_capture_gap'
                    break
                if child.poll() is not None:
                    stopped = 'bridge_finished_before_driver'
                    break
                wall_now = time.monotonic()
                if wall_now >= next_clock:
                    now = datetime.now(module.TPE)
                    measured = wall_now - wall_started >= args.warmup
                    result = study.evaluate(now, measured)
                    coverage = study.coverage(now)
                    record = {'at': now.isoformat(), 'measured': measured, 'arms': result, 'coverage': coverage}
                    snapshots.append(record)
                    log.write(json.dumps({'kind': 'shadow_clock', **record}, ensure_ascii=False) + '\n')
                    next_clock = wall_now + 1
                    if wall_now >= next_status:
                        print('SHADOW_STATUS ' + json.dumps({'at': now.isoformat(), 'symbols': len(symbols),
                            'acks': len(study.acks), 'source_clock_at': study.source_clock_at.isoformat() if study.source_clock_at else None,
                            'source_clock_age_seconds': (now - study.source_clock_at).total_seconds() if study.source_clock_at else None,
                            'journal_fresh': study.last_source_receipt is not None
                            and (now - study.last_source_receipt).total_seconds() <= 3,
                            'arms': result, 'coverage': coverage},
                            ensure_ascii=False), flush=True)
                        next_status = wall_now + 15
                time.sleep(.1)
    finally:
        if child and child.poll() is None:
            # Only our own bounded Node child; never restart or terminate live workers.
            try:
                child.wait(timeout=20)
            except subprocess.TimeoutExpired:
                child.terminate()
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=5)
                stopped = stopped or 'own_bridge_cleanup_timeout'
        if reader:
            reader.join(timeout=3)
        while not messages.empty():
            message = messages.get_nowait()
            if message.get('kind') == 'finished':
                bridge_report = message.get('report')
        study.close()
    report = {**study.report(), 'started_at': protocol['started_at'],
        'ended_at': datetime.now(module.TPE).isoformat(), 'symbols': symbols,
        'stop_reason': stopped, 'bridge_report': bridge_report, 'capture_counters': dict(counters),
        'measured_clocks': sum(r['measured'] for r in snapshots), 'snapshots': snapshots,
        'journal_tail_sequence': tail.sequence,
        'last_source_clock_at': study.source_clock_at.isoformat() if study.source_clock_at else None,
        'last_journal_receipt_at': study.last_source_receipt.isoformat() if study.last_source_receipt else None,
        'caveats': ['no_fills_or_portfolio_performance', 'size_units_unverified',
                    'active_journal_prefix_not_sealed_replay', 'B1_closed_if_started_after_0910',
                    'control_warm_history_and_esun_warmup_are_not_opening_session_equivalent']}
    (args.output / 'results.json').write_text(json.dumps(report, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    print('SHADOW_FINISHED ' + json.dumps({'output': str(args.output), 'signals': len(study.signals),
        'measured_clocks': report['measured_clocks'], 'execution_allowed': False, 'stop_reason': stopped}), flush=True)
    return 0 if stopped is None else 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, OSError) as exc:
        # Do not print raw provider exceptions, env data or credentials.
        code = str(exc) if str(exc) in {'no_fresh_source_radar', 'no_affordable_symbols',
            'initial_event_budget', 'invalid_journal_receipt', 'invalid_radar_clock',
            'invalid_source_clock'} else type(exc).__name__
        print('SHADOW_FAILED ' + code, file=sys.stderr)
        raise SystemExit(2)
