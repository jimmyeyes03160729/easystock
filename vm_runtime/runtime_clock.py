"""Prospective lane clocks, independent of blocking scanner/Firebase work.

No synthetic catch-up timestamps: a late tick is recorded as late and existing
replay eligibility limits remain unchanged.
"""
from datetime import datetime,timezone,timedelta
import threading,time,json,os
from pathlib import Path
TPE=timezone(timedelta(hours=8))

class LaneClock:
    def __init__(self,step,*,interval=.5,now=None,health_path=None):
        self.step=step;self.interval=interval;self.now=now or (lambda:datetime.now(TPE))
        self.health_path=Path(health_path) if health_path else None
        self.stop_event=threading.Event();self.thread=None;self.error=None
        self.last_at=None;self.max_gap_seconds=0.;self.ticks=0;self._last_health=0.
    def tick(self):
        at=self.now()
        if self.last_at:
            gap=(at-self.last_at).total_seconds()
            if gap<0:raise RuntimeError('lane_clock_moved_backwards')
            self.max_gap_seconds=max(self.max_gap_seconds,gap)
            if gap>5:print('[LANE_CLOCK_GAP] seconds='+str(round(gap,3)),flush=True)
        self.last_at=at
        self.step(at);self.ticks+=1
        self.health()
    def health(self,force=False):
        if not self.health_path or not force and time.monotonic()-self._last_health<15:return
        self._last_health=time.monotonic()
        self.health_path.parent.mkdir(parents=True,exist_ok=True)
        tmp=self.health_path.with_suffix('.tmp')
        tmp.write_text(json.dumps({'checked_at':self.now().isoformat(),'last_clock_at':self.last_at.isoformat() if self.last_at else None,
            'max_gap_seconds':self.max_gap_seconds,'ticks':self.ticks,'error':self.error}),encoding='utf-8')
        tmp.replace(self.health_path)
    def _run(self):
        try:
            while not self.stop_event.is_set():
                self.tick()
                self.stop_event.wait(self.interval)
        except Exception as exc:
            self.error=type(exc).__name__
            print('[LANE_CLOCK_FAILED] '+self.error,flush=True)
            self.stop_event.set()
            try:self.health(force=True)
            except Exception:pass
    def start(self):
        if self.thread:raise RuntimeError('lane_clock_already_started')
        self.thread=threading.Thread(target=self._run,name='lane-clock',daemon=True);self.thread.start()
    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=10)
            if self.thread.is_alive():raise RuntimeError('lane_clock_shutdown_timeout')
