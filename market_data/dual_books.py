"""Provider-aware B books with explicit quantity contracts and source epochs."""
from datetime import datetime
from decimal import Decimal
from collections import deque
import json
import math
from pathlib import Path
import threading

from .health import atomic, data_dir, timestamp, TPE


class DualBooks:
    def __init__(self, native, suite, directory=None, esun_size_unit=None):
        self.native, self.suite = native, suite
        self.directory = Path(directory) if directory else data_dir()
        if esun_size_unit not in (None, 'lots', 'shares'):
            raise ValueError('invalid_esun_size_unit')
        # Caller must supply an independently verified provider contract, not a guess.
        self.unit = esun_size_unit
        self.lock = threading.RLock()
        self.epoch = None
        self.esun = {}
        self.native_books = {}
        self.selected = {}
        self.last_clock = None
        self.esun_states = {}
        self.counters = {}
        self.requested = []
        self.native_history = {}
        self.verified_units = {}
        self.unit_samples = {}
        self.unit_blocked = set()
        self.diagnostic_written_at = None

    def _count(self, reason):
        self.counters[reason]=self.counters.get(reason,0)+1

    def select(self, symbols, pinned, now):
        with self.suite.lock,self.lock:
            return self._select(symbols,pinned,now)

    def _write_request(self, symbols, pinned, now):
        try:
            atomic(self.directory/'b-books-request.json', dict(schema_version=1,
                   generated_at=now.isoformat(), symbols=symbols, pinned=sorted(pinned)))
            return True
        except OSError:
            self.counters['ipc_write_failed']=self.counters.get('ipc_write_failed',0)+1
            return False

    def _select(self, symbols, pinned, now):
        symbols = list(dict.fromkeys(sorted(pinned)+list(symbols)))[:160]
        self.requested = symbols
        if not self._write_request(symbols,pinned,now):
            self.esun.clear();self.esun_states.clear();self.last_clock=None
        # Native reservations retain pending/cancelling accounting and held symbols.
        # Rotate the scarce calibration slots away from verified, non-held names.
        # Pinned exits always retain native backup, including on a global outage.
        unverified=[s for s in symbols if s not in self.verified_units]
        missing=[s for s in symbols if s in self.verified_units and s not in self.esun and s not in pinned]
        calibration=list(dict.fromkeys(unverified+missing))
        self.native.select_books(calibration if self.esun_states and calibration else symbols, pinned)

    def native_quote(self, symbol, quote, now):
        with self.suite.lock, self.lock:
            if self.native.status(symbol, 'BidAsk') != 'active': return
            validated = self._validate(quote, now, 'lots')
            if validated:
                self.native_books[symbol] = validated
                history=self.native_history.setdefault(symbol,deque(maxlen=300))
                if not history or validated['datetime']>history[-1]['datetime']:history.append(validated)
                self._route(symbol, now)

    def _validate(self, quote, now, unit):
        get = quote.get if isinstance(quote, dict) else lambda k:getattr(quote,k,None)
        at = get('datetime')
        if isinstance(at,str): at=timestamp(at)
        if isinstance(at,datetime) and at.tzinfo is None: at=at.replace(tzinfo=TPE)
        if not isinstance(at,datetime) or at.date()!=now.date() or not 0 <= (now-at).total_seconds() <= 3:
            return None
        if get('simtrade') or get('suspend'): return None
        arrays=[]
        for i,key in enumerate(('bid_price','ask_price','bid_volume','ask_volume')):
            try: values=list(get(key))
            except (TypeError,ValueError): return None
            if len(values)!=5 or not all(isinstance(v,(int,float,Decimal)) and not isinstance(v,bool)
                and math.isfinite(v) and (v>0 if i<2 else v>=0) for v in values): return None
            arrays.append([float(v) for v in values])
        bp,ap,bv,av=arrays
        if bp[0]>=ap[0] or any(bp[i]<=bp[i+1] or ap[i]>=ap[i+1] for i in range(4)): return None
        if unit=='shares': bv=[v/1000 for v in bv];av=[v/1000 for v in av]
        if unit not in ('lots','shares'): return None
        return dict(datetime=at,bid_price=bp,ask_price=ap,bid_volume=bv,ask_volume=av,
                    simtrade=False,suspend=False,size_units='lots')

    def poll(self, now):
        with self.suite.lock, self.lock:
            pinned={s for lane in self.suite.state.values() for s in lane['positions']}
            # Renew IPC even after the radar cutoff so held exits never lose books.
            try:
                if not self._write_request(self.requested,pinned,now):raise ValueError('ipc_write_failed')
                path=self.directory/'esun-books.json'
                if path.stat().st_size>512*1024: raise ValueError('oversized')
                payload=json.loads(path.read_text(encoding='utf-8'))
                at=timestamp(payload.get('generated_at'))
                if payload.get('schema_version')!=1 or payload.get('provider')!='esun' or not at or not 0 <= (now-at).total_seconds() <= 2:
                    raise ValueError('stale')
                if payload.get('connected') is not True or not isinstance(payload.get('epoch'),str) or not payload['epoch']: raise ValueError('disconnected')
                if payload['epoch']!=self.epoch:
                    self.esun.clear();self.epoch=payload['epoch']
                    self.verified_units.clear();self.unit_samples.clear();self.unit_blocked.clear()
                self.esun_states=payload.get('states',{})
                current={}
                for symbol,quote in payload.get('books',{}).items():
                    if symbol not in set(self.requested)|pinned:continue
                    if self.esun_states.get(symbol)!='active': continue
                    received=timestamp(quote.get('received_at'))
                    if not received or not 0 <= (now-received).total_seconds() <= 3: continue
                    raw_valid=self._validate(quote,now,'lots')
                    if raw_valid:self._verify_symbol_unit(symbol,raw_valid,now)
                    else:self._count('invalid_esun_book')
                    unit=None if symbol in self.unit_blocked else self.unit or self.verified_units.get(symbol)
                    valid=self._validate(quote,now,unit)
                    if valid: current[symbol]=valid
                self.esun=current;self.last_clock=at
            except (OSError,ValueError,TypeError,AttributeError,KeyError) as exc:
                reason=str(exc) if isinstance(exc,ValueError) and str(exc) in ('stale','disconnected','oversized','ipc_write_failed') else type(exc).__name__
                self._count('poll_failure_'+reason)
                self.esun.clear();self.esun_states.clear();self.last_clock=None
                self.verified_units.clear();self.unit_samples.clear();self.unit_blocked.clear()
            for symbol in set(self.selected)|set(self.esun)|set(self.native_books): self._route(symbol,now)
            if self.diagnostic_written_at is None or (now-self.diagnostic_written_at).total_seconds()>=1:
                try:
                    atomic(self.directory/'b-books-diagnostics.json',dict(self.snapshot(),generated_at=now.isoformat()))
                    self.diagnostic_written_at=now
                except OSError:self._count('diagnostic_write_failed')

    def _verify_symbol_unit(self, symbol, raw, now):
        if symbol in self.unit_blocked:return
        if self.native.status(symbol,'BidAsk')!='active':return
        match=next((q for q in reversed(self.native_history.get(symbol,()))
            if q['datetime']==raw['datetime'] and 0 <= (now-q['datetime']).total_seconds() <= 3),None)
        if not match:
            self._count('unit_no_native_timestamp_match');return
        if any(match[k]!=raw[k] for k in ('bid_price','ask_price')):
            self._count('unit_price_mismatch');return
        native=match['bid_volume']+match['ask_volume'];esun=raw['bid_volume']+raw['ask_volume']
        if sum(v>0 for v in native)<8:
            self._count('unit_insufficient_positive_levels');return
        lots=all(a==b for a,b in zip(esun,native))
        shares=all(a==b*1000 for a,b in zip(esun,native))
        unit='lots' if lots else 'shares' if shares else None
        if unit is None or (symbol in self.verified_units and self.verified_units[symbol]!=unit):
            self.verified_units.pop(symbol,None);self.unit_samples.pop(symbol,None)
            self.unit_blocked.add(symbol)
            self.counters['unit_conflict']=self.counters.get('unit_conflict',0)+1
            return
        samples=self.unit_samples.setdefault(symbol,{})
        if raw['datetime'] not in samples:self._count('unit_distinct_pairs')
        samples[raw['datetime']]=unit
        if len(set(samples.values()))!=1:
            self.verified_units.pop(symbol,None);self.unit_samples.pop(symbol,None);self.unit_blocked.add(symbol);return
        if len(samples)>=3:self.verified_units[symbol]=unit
        # Bounded distinct exchange-time evidence, never count repeated poll copies.
        if len(samples)>3:del samples[min(samples)]

    def _route(self, symbol, now):
        quote=self.esun.get(symbol);source='esun'
        worker_fresh=self.last_clock is not None and 0 <= (now-self.last_clock).total_seconds() <= 2
        if not worker_fresh or quote is None or self._validate(quote,now,'lots') is None:
            quote=self.native_books.get(symbol);source='shioaji'
            if self.native.status(symbol,'BidAsk')!='active' or quote is None or self._validate(quote,now,'lots') is None:
                quote=None;source=None
        identity=(source,self.epoch if source=='esun' else None)
        if self.selected.get(symbol)!=identity:
            # Never mix five-second OBI history across providers or reconnect epochs.
            self.suite.reset_books(symbol, 'provider_or_epoch_changed', identity[0], identity[1])
            self.selected[symbol]=identity
        if quote:
            self.suite.on_bidask(symbol,{**quote,'source':source,'source_epoch':identity[1]})

    def status(self, symbol):
        with self.lock:
            source=self.selected.get(symbol,(None,None))[0]
            if source=='esun': return 'active'
            if source=='shioaji': return self.native.status(symbol,'BidAsk')
            if self.unit is None and symbol not in self.verified_units and self.esun_states.get(symbol)=='active': return 'unit_unverified'
            return self.native.status(symbol,'BidAsk')

    def snapshot(self):
        with self.lock:
            return dict(mode='dual',esun_global_size_verified=self.unit is not None,
                requested_count=len(self.requested),worker_quote_at=self.last_clock.isoformat() if self.last_clock else None,
                calibration_pairs_by_symbol={symbol:len(samples) for symbol,samples in self.unit_samples.items()},
                verified_symbols=dict(self.verified_units),unit_events=dict(self.counters),
                unit_blocked_symbols=sorted(self.unit_blocked),
                esun_selected=sum(x[0]=='esun' for x in self.selected.values()),
                shioaji_selected=sum(x[0]=='shioaji' for x in self.selected.values()),
                esun_state_counts={state:list(self.esun_states.values()).count(state) for state in set(self.esun_states.values())})
