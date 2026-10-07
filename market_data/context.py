"""Read local standardized context. No network, credentials or model changes."""
from datetime import datetime
from .health import data_dir, read_json, timestamp, TPE


def esun_index_snapshot(now=None):
    now = now or datetime.now(TPE)
    context = read_json(data_dir() / 'context.json')
    worker = read_json(data_dir() / 'esun.json')
    checked = timestamp(worker.get('checked_at'))
    if not checked or not 0 <= (now - checked).total_seconds() <= 120: return None
    if not worker.get('connected') or not worker.get('authenticated') or not worker.get('parser_ok'): return None
    quote = (context.get('indices') or {}).get('taiex') or {}
    if quote.get('symbol') != 'IX0001' or quote.get('source') != 'esun': return None
    return {'symbol': 'IX0001', 'datetime': quote.get('quote_at'), 'change_rate': quote.get('change_pct')}


def diagnostics(now=None):
    """Separate diagnostics projection: existing Market Risk snapshot is unchanged."""
    from .health import market_session
    import math
    now = now or datetime.now(TPE)
    context = read_json(data_dir() / 'context.json')
    generated = timestamp(context.get('generated_at'))
    current = bool(generated and 0 <= (now-generated).total_seconds() <= 120 and
                   generated.date() == now.date() and market_session(now) == 'OPEN')
    def project(raw, fields, timed=False):
        raw = raw if isinstance(raw, dict) else {}
        result = {}
        for key in fields:
            v = raw.get(key)
            if v is None or isinstance(v, bool) or isinstance(v, (int,float)) and math.isfinite(v):
                result[key] = v
            elif isinstance(v,str) and len(v) <= 200:
                result[key] = v
            elif key in ('leaders','laggards','markets') and isinstance(v,list):
                result[key] = [s for s in v if isinstance(s,str) and len(s)<=32][:5]
        at = timestamp(raw.get('quote_at'))
        row_current = current and (not timed or at and at.date() == now.date() and 0 <= (now-at).total_seconds() <= 90)
        if not row_current:
            result = {k: (v if k in ('source','symbol','name','key','quote_at','received_at','type','basis','scope','score_definition') else None) for k,v in result.items()}
            result.update(status='UNKNOWN', fresh=False, valid=False)
        return result
    common = ('source','symbol','quote_at','received_at','age_seconds','fresh','valid','status')
    breadth = project(context.get('breadth'), common + ('scope','markets','returned_count','valid_count','coverage','advancers','decliners','unchanged','advance_decline_ratio','advance_pct','decline_pct','breadth_score'), timed=True)
    raw_breadth = context.get('breadth') if isinstance(context.get('breadth'),dict) else {}
    for key in ('api_status','api_returned_count'):
        raw = raw_breadth.get(key) if isinstance(raw_breadth.get(key),dict) else {}
        breadth[key] = {market:raw.get(market) for market in ('TSE','OTC') if raw.get(market) in ('available','unavailable') or isinstance(raw.get(market),int)}
    sectors = context.get('sectors') if isinstance(context.get('sectors'),dict) else {}
    rows = sectors.get('rows') if isinstance(sectors.get('rows'),list) else []
    sectors = {**project(sectors, ('status','score_definition')), 'rows': [project(r, common + ('key','name','return_day','return_1m','return_5m','return_15m','relative_to_taiex','relative_to_otc','rank','rank_transition','strength_score'), timed=True) for r in rows[:5]]}
    if not any(r.get('valid') for r in sectors['rows']): sectors['status'] = 'UNKNOWN'
    elif not all(r.get('valid') for r in sectors['rows']): sectors['status'] = 'DEGRADED'
    rotation = project(context.get('rotation'), common + ('type','basis','rotation_state','leaders','laggards'), timed=True)
    if not rotation.get('valid'): rotation['rotation_state'] = 'UNKNOWN'
    return {'source':'esun','generated_at':context.get('generated_at') if generated else None,
            'current':current,'breadth':breadth,'sectors':sectors,'rotation':rotation}
