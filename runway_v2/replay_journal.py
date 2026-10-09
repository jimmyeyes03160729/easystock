"""Bounded, asynchronous capture of the exact inputs accepted by LaneSuite."""
from collections import Counter
from datetime import datetime
import gzip
import hashlib
import json
import os
from pathlib import Path
import queue
import shutil
import threading
import time

SCHEMA = 'b-lanes-inputs-v1'


def fingerprint():
    from .config import FEE_RATE, TAX_RATE
    root = Path(__file__).parent
    h = hashlib.sha256()
    for name in ('lanes.py', 'orderbook.py'):
        h.update((root/name).read_bytes().replace(b'\r\n',b'\n'))
    h.update(json.dumps([FEE_RATE,TAX_RATE]).encode())
    return h.hexdigest()


def encode(value):
    return json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False,
                      default=lambda x: x.isoformat() if isinstance(x,datetime) else str(x))


class InputRecorder:
    def __init__(self, root, now=None, max_queue=10000, max_bytes=1024**3):
        from .lanes import TPE
        self.now = now or (lambda: datetime.now(TPE))
        self.started = self.now()
        self.folder = Path(root)/self.started.date().isoformat()
        self.folder.mkdir(parents=True,exist_ok=True)
        self.base = self.folder/(self.started.strftime('%H%M%S%f')+'-'+str(os.getpid()))
        self.path = self.base.with_suffix('.jsonl.gz')
        self.meta_path = self.base.with_suffix('.manifest.json')
        self.q = queue.Queue(maxsize=max_queue)
        self.seq = self.dropped = self.errors = self.written = self.bytes = 0
        self.counts = Counter()
        self.max_bytes = max_bytes
        self.closed = self.finished = False
        self.halted = False
        self.lock = threading.Lock()
        self.meta = dict(schema=SCHEMA, strategy_fingerprint=fingerprint(), file=self.path.name,
                         started_at=self.started.isoformat(), complete=False)
        self._write_meta()
        self.thread = threading.Thread(target=self._work,daemon=True,name='b-input-journal')
        self.thread.start()

    def record(self, kind, data):
        # LaneSuite calls this under its own lock; sequence records callback order,
        # not a retrospectively sorted exchange timestamp.
        with self.lock:
            if self.closed:
                return
            self.seq += 1
            if self.halted:
                self.dropped += 1
                return
            try:
                row = encode(dict(seq=self.seq,kind=kind,received_at=self.now().isoformat(),data=data))+'\n'
                self.q.put_nowait(row)
            except queue.Full:
                self.dropped += 1
            except Exception:
                self.errors += 1

    def close(self, final_state=None, timeout=5):
        with self.lock:
            if self.closed:
                return
            self.closed = True
            self.meta['ended_at'] = self.now().isoformat()
            self.meta['final_state'] = json.loads(encode(final_state)) if final_state is not None else None
        # The worker drains all queued inputs before sealing. A process kill leaves
        # the manifest incomplete; no partial file can masquerade as a full day.
        self.thread.join(timeout)

    def _write_meta(self):
        data = {**self.meta,'written':self.written,'dropped':self.dropped,'errors':self.errors,
                'last_sequence':self.seq,'kind_counts':dict(self.counts),'bytes':self.bytes}
        tmp = self.meta_path.with_suffix('.tmp')
        tmp.write_text(encode(data),encoding='utf-8')
        tmp.chmod(0o600)
        tmp.replace(self.meta_path)

    def _work(self):
        last_meta = time.monotonic()
        digest = hashlib.sha256()
        while not self.closed or not self.q.empty():
            batch = []
            try:
                batch.append(self.q.get(timeout=.2))
                while len(batch)<2000:
                    batch.append(self.q.get_nowait())
            except queue.Empty:
                pass
            if batch:
                try:
                    if self.halted:
                        raise OSError('recording halted')
                    blob = gzip.compress(''.join(batch).encode('utf-8'),compresslevel=3)
                    if self.bytes+len(blob)>self.max_bytes:
                        raise OSError('daily recording byte budget exceeded')
                    if shutil.disk_usage(self.folder).free<2*1024**3:
                        raise OSError('disk reserve reached')
                    with self.path.open('ab') as stream:
                        stream.write(blob)
                    self.path.chmod(0o600)
                    digest.update(blob)
                    self.bytes += len(blob)
                    self.written += len(batch)
                    self.counts.update(json.loads(line)['kind'] for line in batch)
                except Exception:
                    self.errors += len(batch)
                    self.halted = True
            if time.monotonic()-last_meta>5:
                try:
                    self._write_meta()
                except OSError:
                    self.errors += 1
                last_meta=time.monotonic()
        with self.lock:
            self.meta.update(complete=self.errors==0 and self.dropped==0 and self.written==self.seq,sha256=digest.hexdigest())
            try:
                self._write_meta()
                self.finished=True
            except OSError:
                self.errors += 1
