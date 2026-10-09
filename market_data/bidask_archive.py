"""Five-level BidAsk archive: record every live BidAsk quote, seal finished days, prune days already on the NAS.

Recording never blocks the quote callback: quotes go to a bounded queue drained by one daemon thread that appends
gzip members to ``<root>/raw/<day>/bidask-<pid>.jsonl.gz``. A full queue drops the quote and counts it, never raises.
``seal`` (after the session) writes ``MANIFEST.json`` (file sha256, rows, dropped counts) and ``COMPLETE``.
``prune`` deletes a sealed day only when the NAS presents the same manifest sha256 and the day is old enough.
Research only: no orders, no strategy decisions.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import queue
import shutil
import sys
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

TPE = timezone(timedelta(hours=8))
DEFAULT_ROOT = Path(os.environ.get('BIDASK_ARCHIVE_ROOT', '/home/ubuntu/easystock-orderbook'))
ENABLED = os.environ.get('BIDASK_ARCHIVE_ENABLED', '1').lower() in ('1', 'true', 'yes')
QUEUE_MAX = 50_000
FLUSH_ROWS = 2_000
PRUNE_MIN_AGE_DAYS = 5
DAY_LEN = 10


def _num_list(v):
    try:
        return [float(x) for x in (v or [])]
    except (TypeError, ValueError):
        return []


def quote_row(symbol: str, quote, received_at: datetime) -> dict:
    """Plain JSON row from a Shioaji BidAskSTKv1 (or dict) quote."""
    get = (lambda k: quote.get(k)) if isinstance(quote, dict) else (lambda k: getattr(quote, k, None))
    dt = get('datetime')
    return {
        'symbol': symbol,
        'ts': dt.isoformat() if isinstance(dt, datetime) else (str(dt) if dt is not None else None),
        'recv': received_at.isoformat(timespec='microseconds'),
        'bid_price': _num_list(get('bid_price')), 'bid_volume': _num_list(get('bid_volume')),
        'ask_price': _num_list(get('ask_price')), 'ask_volume': _num_list(get('ask_volume')),
        'diff_bid_vol': _num_list(get('diff_bid_vol')), 'diff_ask_vol': _num_list(get('diff_ask_vol')),
        'simtrade': bool(get('simtrade')) if get('simtrade') is not None else None,
        'suspend': bool(get('suspend')) if get('suspend') is not None else None,
    }


class Recorder:
    def __init__(self, root: Path | str = DEFAULT_ROOT, now=lambda: datetime.now(TPE)):
        self.root, self.now = Path(root), now
        self.q: queue.Queue = queue.Queue(maxsize=QUEUE_MAX)
        self.dropped = 0
        self.errors = 0
        self.written = 0
        self._thread = None

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name='bidask-archive', daemon=True)
            self._thread.start()
        return self

    def record(self, symbol: str, quote) -> None:
        """Callback-safe: never raises, never blocks."""
        try:
            self.q.put_nowait(quote_row(symbol, quote, self.now()))
        except queue.Full:
            self.dropped += 1
        except Exception:
            self.errors += 1

    def _path(self, day: str) -> Path:
        d = self.root / 'raw' / day
        d.mkdir(parents=True, exist_ok=True)
        return d / ('bidask-%d.jsonl.gz' % os.getpid())

    def _write(self, rows):
        by_day = {}
        for r in rows:
            by_day.setdefault(r['recv'][:DAY_LEN], []).append(r)
        for day, rs in by_day.items():
            data = ''.join(json.dumps(r, ensure_ascii=False, separators=(',', ':')) + '\n' for r in rs).encode()
            with open(self._path(day), 'ab') as f:
                f.write(gzip.compress(data))
            self.written += len(rs)
        self._status()

    def _status(self):
        try:
            day = self.now().date().isoformat()
            p = self.root / 'raw' / day
            p.mkdir(parents=True, exist_ok=True)
            tmp = p / ('.status-%d.tmp' % os.getpid())
            tmp.write_text(json.dumps({'pid': os.getpid(), 'written': self.written, 'dropped': self.dropped,
                                       'errors': self.errors, 'at': self.now().isoformat()}))
            tmp.replace(p / ('status-%d.json' % os.getpid()))
        except OSError:
            pass

    def drain(self, block_timeout: float | None = 1.0):
        rows = []
        try:
            rows.append(self.q.get(timeout=block_timeout) if block_timeout else self.q.get_nowait())
            while len(rows) < FLUSH_ROWS:
                rows.append(self.q.get_nowait())
        except queue.Empty:
            pass
        if rows:
            try:
                self._write(rows)
            except Exception:
                self.errors += len(rows)
        return len(rows)

    def _run(self):
        while True:
            self.drain(1.0)


_RECORDER: Recorder | None = None


def recorder() -> Recorder | None:
    global _RECORDER
    if not ENABLED:
        return None
    if _RECORDER is None:
        _RECORDER = Recorder().start()
    return _RECORDER


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def seal(root: Path, day: str, today: str) -> dict:
    """Write MANIFEST.json + COMPLETE for a finished day (refuses today before 14:00 is handled by the caller)."""
    if day >= today:
        raise SystemExit('refuse to seal today or a future day: ' + day)
    d = root / 'raw' / day
    if not d.is_dir() or (d / 'COMPLETE').exists():
        return {'day': day, 'status': 'missing' if not d.is_dir() else 'already_sealed'}
    files, rows = [], 0
    for p in sorted(d.glob('bidask-*.jsonl.gz')):
        n = sum(1 for _ in gzip.open(p, 'rt', encoding='utf-8'))
        rows += n
        files.append({'name': p.name, 'bytes': p.stat().st_size, 'sha256': sha256(p), 'rows': n})
    status = [json.loads(p.read_text()) for p in sorted(d.glob('status-*.json'))]
    manifest = {'day': day, 'files': files, 'rows': rows, 'writers': status,
                'dropped': sum(s.get('dropped', 0) for s in status), 'sealed_at': datetime.now(TPE).isoformat()}
    (d / 'MANIFEST.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=1))
    (d / 'COMPLETE').write_text(sha256(d / 'MANIFEST.json') + '\n')
    return {'day': day, 'status': 'sealed', 'rows': rows, 'files': len(files)}


def prune(root: Path, day: str, manifest_sha: str, today: date) -> str:
    """Delete one sealed day after the NAS confirmed the identical manifest; fail closed otherwise."""
    if len(day) != DAY_LEN or date.fromisoformat(day) > today - timedelta(days=PRUNE_MIN_AGE_DAYS):
        return 'too_recent'
    d = (root / 'raw' / day)
    if d.is_symlink() or not d.is_dir() or d.resolve().parent != (root / 'raw').resolve():
        return 'not_a_day_dir'
    complete = d / 'COMPLETE'
    if not complete.exists():
        return 'not_sealed'
    if complete.read_text().strip() != manifest_sha or sha256(d / 'MANIFEST.json') != manifest_sha:
        return 'manifest_mismatch'
    shutil.rmtree(d)
    return 'pruned'


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('action', choices=('seal', 'prune'))
    ap.add_argument('--root', default=str(DEFAULT_ROOT))
    ap.add_argument('--day')
    ap.add_argument('--manifest-sha')
    a = ap.parse_args(argv)
    root, today = Path(a.root), datetime.now(TPE).date()
    if a.action == 'seal':
        days = [a.day] if a.day else sorted(p.name for p in (root / 'raw').glob('????-??-??') if p.is_dir())
        out = [seal(root, d, today.isoformat()) for d in days if d < today.isoformat()]
    else:
        if not a.day or not a.manifest_sha:
            raise SystemExit('prune needs --day and --manifest-sha')
        out = [{'day': a.day, 'status': prune(root, a.day, a.manifest_sha, today)}]
    print(json.dumps(out, ensure_ascii=False))
    return 0 if all(o['status'] in ('sealed', 'already_sealed', 'pruned', 'missing') for o in out) else 1


if __name__ == '__main__':
    sys.exit(main())
