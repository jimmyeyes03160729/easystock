"""Close-of-D0 features and independent research-only threshold diagnostics."""
from __future__ import annotations

from math import isfinite
from statistics import mean

from range_rebound import (MAX_ABOVE_SUPPORT, MAX_RANGE_POSITION, MIN_NET_RR,
                           MIN_RANGE, _clusters, MIN_TOUCH_GAP, MIN_TOUCH_SPAN)


def _pct(a, b):
    return round((a / b - 1) * 100, 6) if b else None


def _ma(values, n):
    return mean(values[-n:]) if len(values) >= n else None


def extract(bars: list[dict], signal_date: str, technical: dict,
            *, amount_rank: float | None = None) -> dict:
    """Accept only a D0-ending prefix; never silently consume or slice future bars."""
    if not bars or bars[-1]['time'] != signal_date or any(b['time'] > signal_date for b in bars):
        raise ValueError('feature_future_or_missing_signal_bar')
    closes = [float(b['close']) for b in bars]
    volumes = [float(b['volume']) if b.get('volume') is not None else None for b in bars]
    last = bars[-1]
    opening, high, low, close = (float(last[k]) for k in ('open', 'high', 'low', 'close'))
    ma20, ma60 = _ma(closes, 20), _ma(closes, 60)
    old20, old60 = (_ma(closes[:-5], n) for n in (20, 60))
    def ret(n):
        return _pct(close, closes[-n-1]) if len(closes) > n else None
    def volratio(n):
        history = volumes[-n-1:-1]
        return round(volumes[-1] / mean(history), 6) if len(history) == n and volumes[-1] is not None and all(v is not None and v > 0 for v in history) else None
    support = technical.get('support')
    resistance = technical.get('resistance')
    support_mid = mean(support) if support else None
    resistance_mid = mean(resistance) if resistance else None
    span = high - low
    recent=bars[-252:]
    atr=mean(max(b['high']-b['low'],abs(b['high']-recent[i-1]['close']),
                 abs(b['low']-recent[i-1]['close'])) for i,b in enumerate(recent[-20:],start=len(recent)-20)) if len(recent)>=21 else None
    pivot_indices=[]
    if support_mid and atr:
        tolerance=min(.04,max(.02,atr/close))
        for i in range(3,len(recent)-3):
            neighbours=recent[i-3:i]+recent[i+1:i+4]
            if (all(recent[i]['low']<=x['low'] for x in neighbours)
                    and any(recent[i]['low']<x['low'] for x in neighbours)
                    and abs(recent[i]['low']/support_mid-1)<=tolerance):
                if not pivot_indices or i-pivot_indices[-1]>=7:pivot_indices.append(i)
    features = {
        'distance_to_support_pct': _pct(close, support_mid) if support_mid else None,
        'distance_to_resistance_pct': _pct(resistance_mid, close) if resistance_mid else None,
        'range_position': round((close - support_mid) / (resistance_mid - support_mid), 6) if support_mid and resistance_mid and resistance_mid > support_mid else None,
        'support_touches': technical.get('touches'),
        'resistance_touches': technical.get('pressureTouches'),
        'support_span_days': technical.get('support_span_days',pivot_indices[-1]-pivot_indices[0] if len(pivot_indices)>=2 else None),
        'support_age_days': technical.get('support_age_days',len(recent)-1-pivot_indices[-1] if pivot_indices else None),
        'net_rr': technical.get('netRR'),
        'raw_rr': technical.get('rr'),
        'atr_pct': technical.get('atr_pct',atr/close*100 if atr else None),
        'bias_ma20_pct': _pct(close, ma20) if ma20 else None,
        'bias_ma60_pct': _pct(close, ma60) if ma60 else None,
        'ma20_slope': _pct(ma20, old20) if ma20 and old20 else None,
        'ma60_slope': _pct(ma60, old60) if ma60 and old60 else None,
        'return_3d_pct': ret(3), 'return_5d_pct': ret(5), 'return_20d_pct': ret(20),
        'daily_change_pct': ret(1),
        'candle_body_pct': round((close - opening) / opening * 100, 6),
        'upper_shadow_pct': round((high - max(close, opening)) / opening * 100, 6),
        'lower_shadow_pct': round((min(close, opening) - low) / opening * 100, 6),
        'close_position': round((close - low) / span, 6) if span > 0 else None,
        'volume_ratio_5d': volratio(5), 'volume_ratio_20d': volratio(20),
        'amount': last.get('amount'), 'amount_rank': amount_rank,
    }
    if any(isinstance(v, float) and not isfinite(v) for v in features.values()):
        raise ValueError('nonfinite_feature')
    return features


def near_miss_diagnostics(bars: list[dict], signal_date: str, *,
                          tolerance: dict) -> dict | None:
    """Strictly one nearby numeric rejection; other failed gates never qualify.

    This never modifies or replaces production evaluate_technical().
    """
    if len(bars) < 90 or bars[-1]['time'] != signal_date:
        return None
    recent = bars[-252:]
    p = float(recent[-1]['close'])
    for i, bar in enumerate(recent):
        try:
            vals = [float(bar[k]) for k in ('open', 'high', 'low', 'close')]
            if min(vals) <= 0 or vals[1] < max(vals[0], vals[2], vals[3]) or vals[2] > min(vals[0], vals[3]): return None
            if i and (bar['time'] <= recent[i-1]['time'] or abs(vals[0] / float(recent[i-1]['close']) - 1) > .12): return None
        except (KeyError, ValueError, TypeError): return None
    atr = mean(max(b['high']-b['low'], abs(b['high']-recent[i-1]['close']),
                   abs(b['low']-recent[i-1]['close'])) for i,b in enumerate(recent[-20:], start=len(recent)-20))
    tol = min(.04, max(.02, atr/p))
    lows, highs = [], []
    for i in range(3,len(recent)-3):
        neighbours=recent[i-3:i]+recent[i+1:i+4]
        if all(recent[i]['low']<=b['low'] for b in neighbours) and any(recent[i]['low']<b['low'] for b in neighbours): lows.append({'i':i,'v':recent[i]['low']})
        if all(recent[i]['high']>=b['high'] for b in neighbours) and any(recent[i]['high']>b['high'] for b in neighbours): highs.append({'i':i,'v':recent[i]['high']})
    supports=[s for s in _clusters(lows,tol) if s['last']>=len(recent)-100 and p>=s['price']*(1-tol) and p<=s['price']*(1+MAX_ABOVE_SUPPORT+tolerance['distance_to_support'])]
    resistances=[r for r in _clusters(highs,tol) if r['price']>p and r['last']>=len(recent)-120]
    for support in sorted(supports,key=lambda s:-s['price']):
        resistance=next((r for r in sorted(resistances,key=lambda r:r['price']) if r['price']/support['price']>=1+MIN_RANGE),None)
        if not resistance: continue
        floor=support['price']*(1-tol); ceiling=support['price']*(1+tol)
        if any(b['close']<floor*.98 for b in recent[support['last']+1:]): continue
        if not any(floor*.98<=b['low']<=ceiling for b in recent[-8:]): continue
        confirmed=any(recent[i]['close']>recent[i-1]['high'] and recent[i]['close']>recent[i]['open'] and all(x['close']>=recent[i-1]['high'] for x in recent[i:]) for i in range(len(recent)-3,len(recent)))
        last,prev,third=recent[-1],recent[-2],recent[-3]
        early=last['close']>prev['close']>third['close'] and last['close']>last['open'] and last['high']>last['low'] and (last['close']-last['low'])/(last['high']-last['low'])>=.65
        if last['low']<min(b['low'] for b in recent[-6:-1])*.995 or not (confirmed or early): continue
        target=resistance['price']*(1-tol)
        invalid=floor-max(atr*.5,p*.01)
        risk=p-invalid; reward=target-p; cost=p*.006
        net_rr=(reward-cost)/(risk+cost) if risk+cost>0 else -1
        pos=(p-support['price'])/(resistance['price']-support['price'])
        distance=p/support['price']-1
        failures=[]
        if distance>MAX_ABOVE_SUPPORT: failures.append(('distance_to_support',distance-MAX_ABOVE_SUPPORT,tolerance['distance_to_support']))
        if pos>MAX_RANGE_POSITION: failures.append(('range_position',pos-MAX_RANGE_POSITION,tolerance['range_position']))
        if risk<=0 or reward<=cost: continue
        if net_rr<MIN_NET_RR: failures.append(('net_rr',MIN_NET_RR-net_rr,tolerance['net_rr']))
        if len(failures)!=1 or failures[0][1]>failures[0][2] or target<=p or invalid>=p: continue
        name,distance_to_threshold,_=failures[0]
        return {'eligible':False,'failed_rule':name,'failed_stage':'technical_numeric',
                'distance_to_threshold':round(distance_to_threshold,6),
                'eligible_checks':3,'rejected_checks':1,
                'support':[floor,ceiling], 'resistance':[target,resistance['price']*(1+tol)],
                'invalid':invalid,'target':target,'rr':reward/risk,'netRR':net_rr,
                'touches':support['touches'],'pressureTouches':resistance['touches'],
                'support_span_days':support['last']-next((j for j in range(support['last']+1) if abs(recent[j]['low']/support['price']-1)<=tol),support['last']),
                'support_age_days':len(recent)-1-support['last'],'atr_pct':atr/p*100,
                'confirmation':'breakout' if confirmed else 'early'}
    return None
