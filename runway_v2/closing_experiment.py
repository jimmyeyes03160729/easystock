"""Two independent B1 paper arms sharing existing native quotes, never orders."""
from pathlib import Path
import json
import threading
from functools import wraps
from .lanes import LaneSuite,TPE
from .replay_journal import InputRecorder
from .closing_pool import load,MAX_SYMBOLS,TRIAL,write

def synchronized(fn):
    @wraps(fn)
    def call(self,*args,**kwargs):
        with self.lock:return fn(self,*args,**kwargs)
    return call

class ClosingExperiment:
    def __init__(self,root,status,now,record=True,book_limit=20):
        self.lock=threading.RLock();self.book_limit=book_limit
        self.root=Path(root);self.day=now.date().isoformat();self.pool=load(self.root,self.day)
        self.control=None;self.last_persist=0;self.closed=False
        self.arms={};self.recorders={}
        for name,symbols in [('control',[]),('closing',[])]:
            recorder=InputRecorder(self.root/(name+'-recordings')) if record else None
            suite=LaneSuite(self.root/(name+'.sqlite'),sender=lambda *_:None,recorder=recorder,
                active_lanes=('B1',),entry_symbols=symbols)
            suite.register_subscription_status(status);suite.advance(now)
            self.arms[name]=suite;self.recorders[name]=recorder
        p=self.root/'controls'/(self.day+'.json')
        if p.exists():
            self.control=json.loads(p.read_text(encoding='utf-8'))
            self.arms['control'].set_entry_universe(self.control['symbols'])
            if self.pool.get('status')=='READY':self.arms['closing'].set_entry_universe(self.pool['symbols'])

    @synchronized
    def select(self,ranked,pinned,now):
        if self.closed or self.pool.get('status')!='READY':return list(ranked),set(pinned)|self.held()
        if '09:00:00'<=now.strftime('%H:%M:%S')<'09:10:00' and self.control is None and ranked:
            count=len(self.pool.get('symbols',[])) or MAX_SYMBOLS
            if len(set(ranked))<count:return list(ranked),set(pinned)|self.held()
            self.control={'day':self.day,'frozen_at':now.isoformat(),'symbols':list(dict.fromkeys(ranked))[:count],
                          'ranking':'existing_B1_rank_first_observed_after_0900','max_symbols':MAX_SYMBOLS}
            write(self.root/'controls'/(self.day+'.json'),self.control)
            self.arms['control'].set_entry_universe(self.control['symbols'])
            self.arms['closing'].set_entry_universe(self.pool['symbols'])
        held=set(pinned)|self.held()
        if now.strftime('%H:%M:%S')>='09:10:00':return list(ranked),held
        # Interleave arms; occupied positions retain priority and quota is shared.
        watch=[]
        for i in range(MAX_SYMBOLS):
            for group in [list(self.control['symbols']) if self.control else [],list(self.pool.get('symbols',[]))]:
                if i<len(group) and group[i] not in watch:watch.append(group[i])
        slots=max(0,self.book_limit-len(held));observed=[s for s in watch if s not in held][:slots]
        pinned=held|set(observed)
        return list(dict.fromkeys(watch+list(ranked))),pinned

    @synchronized
    def held(self):
        held=set()
        for arm in self.arms.values():
            with arm.lock:held.update(arm.state['B1']['positions'])
        return held

    @synchronized
    def required_ticks(self,now):
        if self.closed:return self.held()
        symbols=self.held()
        if now.strftime('%H:%M:%S')<'09:10:00':
            symbols.update(self.pool.get('symbols',[]))
            if self.control:symbols.update(self.control['symbols'])
        return symbols

    @synchronized
    def on_tick(self,symbol,price,at,tick_type,volume):
        if self.closed:return
        for arm in self.arms.values():
            # Both arms retain the same pre-decision input history. Entry filters
            # are applied only when the two universes are frozen together.
            arm.on_tick(symbol,price,at,tick_type,volume)

    @synchronized
    def on_bidask(self,symbol,quote):
        if self.closed:return
        for arm in self.arms.values():
            arm.on_bidask(symbol,quote)

    @synchronized
    def radar(self,rows,cache,previous,now,market):
        if self.closed:return
        for arm in self.arms.values():arm.on_radar_update(rows,cache,previous,now,market)

    @synchronized
    def advance(self,now):
        if self.closed:return
        for arm in self.arms.values():arm.advance(now)
        if now.timestamp()-self.last_persist>=5:
            snapshots={k:a.export_snapshot(now)['lanes']['B1'] for k,a in self.arms.items()}
            result={'trial':TRIAL,'day':self.day,'updated_at':now.isoformat(),'pool':self.pool,
                    'control':self.control,'arms':snapshots,'mode':'independent_shadow_paper',
                    'comparison_status':('EXCLUDED_NO_VALID_CLOSING_POOL' if self.pool.get('status')!='READY' else
                        'EXCLUDED_CONTROL_NOT_FROZEN' if self.control is None else 'PROSPECTIVE_QUOTES_NOT_VERIFIED_PERFORMANCE'),
                    'capital_per_arm':1000000,'book_budget_per_arm_max':10,
                    'source':'shared_existing_Shioaji_native_tick_and_bidask'}
            write(self.root/'reports'/(self.day+'.json'),result);write(self.root/'latest.json',result)
            self.last_persist=now.timestamp()
        if now.strftime('%H:%M:%S')>='09:10:00' and not self.held():self.close()

    @synchronized
    def close(self):
        if self.closed:return
        self.closed=True
        for arm in self.arms.values():
            arm.close_recording();arm.worker.shutdown(wait=True)
