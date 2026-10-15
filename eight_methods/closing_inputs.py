"""Join pre-decision equity snapshot and official share counts for eight checks."""
from datetime import timedelta
import json
from pathlib import Path
from .rules import stamp,number


def read_json(path):
    try:return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError,ValueError,TypeError):return {}


def enrich(rows,snapshot_path,shares_path,now,*,snapshot=None,shares=None):
    try:
        snapshot=read_json(snapshot_path) if snapshot is None else snapshot
        received=stamp(snapshot['generated_at'])
        if snapshot.get('schema_version')!=1 or snapshot.get('day')!=now.date().isoformat() or not 0<=(now-received).total_seconds()<=90:
            return ['缺當日有效尾盤行情快照']
    except (OSError,ValueError,KeyError,TypeError):return ['缺尾盤行情快照']
    try:shares=read_json(shares_path).get('rows',{}) if shares is None else shares
    except (OSError,ValueError,TypeError):shares={}
    for symbol,q in snapshot.get('rows',{}).items():
        try:
            at,available=stamp(q['quote_at']),stamp(q['received_at'])
            if at.date()!=now.date() or not at<=available<=now:continue
            # Full-market REST projection reuses the existing breadth poll.
            # Missing Tick history remains insufficient for the corresponding rules.
            r=rows.setdefault(symbol,{'symbol':symbol,'name':q.get('name',symbol),'quotes':[]})
            if r.get('quote_at') and at<stamp(r['quote_at']):continue
            r.update({k:q.get(k) for k in ('price','quote_at','day_high','day_volume','exchange','quantity_check','volume_scale')})
            meta=shares.get(symbol,{})
            issued=meta.get('issued_common_shares');day=meta.get('asof_day')
            if (meta.get('exchange')==q.get('exchange') and number(issued,True) and
                stamp(meta['received_at'])<=now and day<=now.date().isoformat() and
                (now.date()-stamp(day+'T00:00:00+08:00').date()).days<=7 and
                0<=(now-stamp(meta['received_at'])).total_seconds()<=3*86400):
                r.update(market_cap=q['price']*issued,cap_currency='TWD',issued_common_shares=issued,
                         shares_source=meta['source'],shares_asof=day)
                if number(q.get('day_volume')):
                    r['turnover_pct']=q['day_volume']/issued*100
        except (KeyError,ValueError,TypeError):continue
    return [] if shares else ['缺可靠發行普通股數；換手率與市值不放行']


def merge_current_indices(rows,context,now):
    """Latest existing context for closing strength; opening boundary history is untouched."""
    for key,symbol in [('taiex','IX0001'),('otc','IX0043')]:
        try:
            q=context['indices'][key]
            at,received=stamp(q['quote_at']),stamp(q['received_at'])
            if not at<=received<=now or not 0<=(now-at).total_seconds()<=30 or not number(q.get('price'),True):continue
            r=rows.setdefault(symbol,{'symbol':symbol,'name':key,'quotes':[]})
            if not r.get('quote_at') or at>=stamp(r['quote_at']):
                r.update(price=q['price'],quote_at=q['quote_at'])
        except (KeyError,ValueError,TypeError):continue
