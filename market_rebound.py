"""Prospective paper-only rebound guard. All inputs must precede the decision."""
from collections import deque
from datetime import datetime
import math
import threading

VERSION='MARKET_REBOUND_V1'

def finite(x):return isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x)

def clock(x):
    try:
        d=datetime.fromisoformat(x.replace('Z','+00:00'))
        return d if d.tzinfo else None
    except (ValueError,TypeError,AttributeError):return None

class ReboundGuard:
    def __init__(self):
        self.lock=threading.RLock()
        self.day=None;self.indices={k:deque() for k in ('taiex','otc')};self.snapshots=deque()
        self.cooldown_until=0;self.peak=None;self.allowed=False

    def update(self,base,context,equity,worker,now):
        with self.lock:return self._update(base,context,equity,worker,now)

    def _update(self,base,context,equity,worker,now):
        day=now.date().isoformat();ts=now.timestamp()
        if self.day!=day:
            self.day=day;self.indices={k:deque() for k in ('taiex','otc')};self.snapshots.clear()
            self.cooldown_until=0;self.peak=None;self.allowed=False
        result=dict(base,base_gate_action=base.get('gate_action'),base_market_level=base.get('level'),
                    rebound_version=VERSION,rebound_mode=False,rebound_state='OBSERVING',rebound_metrics={})
        def blocked(reason):
            self.allowed=False;self.peak=None
            return dict(result,level='RED',market_risk='RED',gate_action='BLOCK',gate_reason=reason,
                        rebound_state=reason,entry_valid_until=ts)
        checked=clock(worker.get('checked_at'))
        if not checked or not 0<=(now-checked).total_seconds()<=10 or not all(worker.get(k) for k in ('connected','authenticated','parser_ok')):
            return blocked('rebound_data_unavailable')
        index_expiry=ts+3
        for key in self.indices:
            q=context.get('indices',{}).get(key,{})
            at=clock(q.get('quote_at'));p=q.get('price')
            if not at or at.date()!=now.date() or not 0<=(now-at).total_seconds()<=10 or not finite(p) or p<=0:
                return blocked('rebound_index_stale')
            rows=self.indices[key]
            index_expiry=min(index_expiry,at.timestamp()+10)
            if not rows or at.timestamp()>rows[-1][0]:rows.append((at.timestamp(),p))
            while rows and rows[0][0]<ts-1200:rows.popleft()
        def before(rows,target,tolerance=10):
            return next((p for t,p in reversed(rows) if 0<=target-t<=tolerance),None)
        fast=[];slow=[];rising=[]
        for rows in self.indices.values():
            price=rows[-1][1];previous=before(rows,ts-30)
            fast.append(previous is not None and (price/previous-1)*100<=-.15)
            boundary=int(ts//60)*60
            closes=[before(rows,boundary-i*60) for i in (3,2,1,0)]
            complete=all(p is not None for p in closes)
            slow.append(complete and all(a>b for a,b in zip(closes,closes[1:])) and (closes[-1]/closes[0]-1)*100<=-.10)
            rising.append(complete and all(a<b for a,b in zip(closes,closes[1:])) and (closes[-1]/closes[0]-1)*100>=.25)
        price=self.indices['taiex'][-1][1]
        retreat=self.allowed and self.peak is not None and (price/self.peak-1)*100<=-.12
        if any(fast) or any(slow) or retreat:
            self.cooldown_until=ts+180
            return blocked('rebound_fast_drop' if any(fast) else 'rebound_slow_decline' if any(slow) else 'rebound_pullback')
        if ts<self.cooldown_until:return blocked('rebound_cooldown')
        # Normal non-red gates retain their strategy conditions. Falling overrides
        # apply above to every lane, including on otherwise GREEN sessions.
        if base.get('gate_action')=='PASS' and base.get('valid'):
            self.allowed=False;self.peak=None
            return dict(result,entry_valid_until=min(index_expiry,(clock(base['quote_at']).timestamp()+90)))
        base_at=clock(base.get('quote_at'))
        if not base.get('valid') or not base_at or not 0<=(now-base_at).total_seconds()<=90 or base.get('gate_reason')!='market_risk_red':return blocked('rebound_base_unavailable')
        at=clock(equity.get('generated_at'))
        if not at or equity.get('day')!=day or not 0<=(now-at).total_seconds()<=90:return blocked('rebound_snapshot_stale')
        good={}
        receipts=[]
        for symbol,q in equity.get('rows',{}).items():
            qt=clock(q.get('quote_at'));received=clock(q.get('received_at'))
            if (qt and received and qt.date()==now.date() and qt<=received<=now and
                0<=(now-qt).total_seconds()<=90 and finite(q.get('price')) and q['price']>0 and
                finite(q.get('day_volume')) and q['day_volume']>=0):
                good[symbol]=(q['price'],q['day_volume']);receipts.append(received.timestamp())
        # Poll receipts, not regenerated output timestamps, identify a new sample.
        sample_at=min(receipts) if receipts else 0
        if len(good)>=500 and (not self.snapshots or sample_at>self.snapshots[-1][0]):self.snapshots.append((sample_at,good))
        while self.snapshots and self.snapshots[0][0]<ts-1200:self.snapshots.popleft()
        if not self.snapshots:return blocked('rebound_volume_warmup')
        latest,stocks=self.snapshots[-1]
        def snapshot_before(target):return next((r for r in reversed(self.snapshots) if 0<=target-r[0]<=75),None)
        previous=snapshot_before(latest-180);older=snapshot_before(latest-360)
        if not previous or not older:return blocked('rebound_volume_warmup')
        common=set(stocks)&set(previous[1])&set(older[1])
        coverage=len(common)/max(len(stocks),len(previous[1]),len(older[1]),1)
        if len(common)<500 or coverage<.8:return blocked('rebound_breadth_incomplete')
        if any(stocks[s][1]<previous[1][s][1] or previous[1][s][1]<older[1][s][1] for s in common):return blocked('rebound_volume_reset')
        recent=sum(stocks[s][1]-previous[1][s][1] for s in common)/(latest-previous[0])
        baseline=sum(previous[1][s][1]-older[1][s][1] for s in common)/(previous[0]-older[0])
        ratio=recent/baseline if baseline>0 else 0
        breadth=sum(stocks[s][0]>previous[1][s][0] for s in common)/len(common)
        result['rebound_metrics']={'volume_rate_ratio':ratio,'rising_stock_fraction':breadth,'cohort':len(common),'coverage':coverage,'snapshot_at':latest}
        if not all(rising) or ratio<1.3 or breadth<.55:return blocked('rebound_conditions_not_met')
        self.allowed=True;self.peak=max(self.peak or price,price)
        return dict(result,level='YELLOW',market_risk='YELLOW',gate_action='PASS',gate_reason='market_rebound_limited',
                    rebound_mode=True,rebound_state='LIMITED_PASS',fade_detected=False,market_regime='REBOUND',
                    entry_valid_until=index_expiry,max_entry_notional=100000,max_positions=1)
