"""Reuse received index snapshots for opening observations, without new API calls."""
from datetime import datetime,timezone,timedelta
import json
import math
from pathlib import Path

TPE=timezone(timedelta(hours=8))


def merge_indices(rows,path,now):
    path=Path(path)
    paths=[p for p in (path,path.parent.parent/'opening-index-boundaries'/path.name) if p.exists()]
    if not paths:return ['缺少玉山指數歷史快照']
    aliases={'taiex':('IX0001','加權指數'),'otc':('IX0043','櫃買指數')}
    failures=0
    for source in paths:
        with source.open(encoding='utf-8') as f:
            for line in f:
                try:
                    snapshot=json.loads(line)
                    available=datetime.fromisoformat(snapshot['received_at'])
                    if available.tzinfo is None:raise ValueError('timezone required')
                    available=available.astimezone(TPE)
                    if available.date()!=now.date() or available>now:continue
                    for key,(symbol,name) in aliases.items():
                        q=snapshot.get('indices',{}).get(key)
                        if not q:continue
                        at=datetime.fromisoformat(q['quote_at'])
                        if at.tzinfo is None:raise ValueError('timezone required')
                        at=at.astimezone(TPE)
                        price=q['price']
                        if not isinstance(price,(int,float)) or isinstance(price,bool) or not math.isfinite(price) or price<=0:continue
                        if at.date()!=now.date() or at>available:continue
                        r=rows.setdefault(symbol,{'symbol':symbol,'name':name,'quotes':[]})
                        r['quotes'].append({'price':price,'quote_at':q['quote_at'],'available_at':snapshot['received_at']})
                        if 'quote_at' not in r or at>=datetime.fromisoformat(r['quote_at']).astimezone(TPE):
                            r.update(price=price,quote_at=q['quote_at'])
                except (ValueError,KeyError,TypeError):failures+=1
    return [f'指數快照無效列 {failures}'] if failures else []
