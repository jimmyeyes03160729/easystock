"""Bounded asynchronous research journal. Never calls a broker or LINE."""
import json
import os
from pathlib import Path
import queue
import threading
from datetime import datetime, timezone, timedelta
import math

TPE = timezone(timedelta(hours=8))
DATA = Path(os.environ.get('LEARNING_DATA_DIR', '/home/ubuntu/easystock-learning-data'))


def clean(x):
    if isinstance(x, datetime):
        return x.isoformat()
    if isinstance(x, dict):
        return {str(k): clean(v) for k,v in x.items()}
    if isinstance(x, (list,tuple)):
        return [clean(v) for v in x]
    if isinstance(x, float) and not math.isfinite(x):
        return None
    if x is None or isinstance(x, (str,bool,int,float)):
        return x
    return str(x)


class Recorder:
    def __init__(self):
        self.enabled = os.environ.get('LEARNING_ENABLED', '1') == '1'
        self.queue = queue.Queue(maxsize=10000)
        self.lock = threading.Lock()
        self.last_sample = {}
        self.dropped = 0
        self.errors = 0
        self.thread = None
        if self.enabled:
            DATA.mkdir(parents=True,exist_ok=True,mode=0o700)
            self.thread = threading.Thread(target=self._work,daemon=True,name='research-journal')
            self.thread.start()

    def submit(self, kind, payload):
        if not self.enabled:
            return
        try:
            item = {'kind':kind, 'recorded_at':datetime.now(TPE).isoformat(), 'data':clean(payload)}
            self.queue.put_nowait(item)
        except queue.Full:
            self.dropped += 1
            if self.dropped == 1 or self.dropped % 100 == 0:
                print('[LEARNING] journal queue full; dropped=',self.dropped)
        except Exception:
            self.errors += 1

    def sample(self, symbol, current, ticks, metrics, metadata, top30, policy):
        if not self.enabled or not ticks:
            return
        bucket = int(current.timestamp() // 300)
        with self.lock:
            if self.last_sample.get(symbol) == bucket:
                return
            self.last_sample[symbol] = bucket
        rows = sorted((t for t in ticks if t[0] <= current.timestamp()), key=lambda t:t[0])
        if not rows:
            return
        last = rows[-1]
        old = [t for t in rows if t[0] <= current.timestamp()-300]
        old = old[-1] if old else None
        self.submit('sample', {
            'symbol':symbol, 'observed_at':current.isoformat(),
            'quote_at':datetime.fromtimestamp(last[0],TPE).isoformat(), 'price':last[3],
            'return_5m_pct':(last[3]/old[3]-1)*100 if old and old[3]>0 and current.timestamp()-old[0]<=330 else None,
            'metrics':{k:metrics.get(k) for k in ('surge_60s','buy_ratio_60s','classified_ratio_60s','amount_60s','history_seconds')},
            'radar_selected':bool(top30), 'policy':policy,
            'name':metadata.get('name',symbol),
        })

    def entry(self, event):
        p=event.get('position',{})
        self.submit('entry',{k:p.get(k) for k in ('symbol','name','trade_id','execution_kind','shares','entry_time','entry_price','entry_score','stop_price','take_profit_price','decision_mode','model_version','model_artifact_sha256','model_score','model_threshold')})

    def exit(self, event):
        p=event.get('trade',{})
        self.submit('exit',{k:p.get(k) for k in ('symbol','name','trade_id','execution_kind','shares','settlement','entry_time','entry_price','exit_time','exit_price','exit_reason','pnl_pct')})

    def close(self):
        if not self.thread:
            return
        self.submit('health',{'dropped':self.dropped,'errors':self.errors})
        try:
            self.queue.put(None,timeout=2)
            self.thread.join(timeout=5)
        except queue.Full:
            print('[LEARNING] shutdown queue not flushed')

    def _work(self):
        while True:
            item=self.queue.get()
            try:
                if item is None:
                    return
                day=item['recorded_at'][:10]
                path=DATA/('journal-'+day+'.jsonl')
                fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
                with os.fdopen(fd,'a',encoding='utf-8') as out:
                    out.write(json.dumps(item,ensure_ascii=False,allow_nan=False)+'\n')
            except Exception as exc:
                self.errors+=1
                if self.errors==1 or self.errors%100==0:
                    print('[LEARNING] journal write failed:',type(exc).__name__)
            finally:
                self.queue.task_done()
