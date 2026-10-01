"""Small deterministic range fixture shared by research-only tests."""
from datetime import date,timedelta


def bars(count=162):
    out=[]; day=date(2026,1,1)
    for i in range(count):
        while day.weekday()>=5: day+=timedelta(days=1)
        close=10+5*(1-abs((i%40)-20)/20)
        opening=close
        if i==161: close=10.5;opening=10.05
        out.append({'time':day.isoformat(),'open':opening,'high':close+.1,
                    'low':min(close,opening)-.1,'close':close,
                    'volume':1000+i,'amount':10_000_000+i})
        day+=timedelta(days=1)
    return out


def verified_stock(day):
    return {'name':'測試製造','price':10.5,'amount':10_000_000,'updated_at':day,
            'rev_yoy':5,'eps':2,'operating_margin':10,'debt_ratio':30,
            'revenue_period':day[:4]+f'{max(1,int(day[5:7])-1):02d}',
            'field_meta':{k:{'source':'official-api','as_of':day,
                             'published_at':f'{day}T12:00:00+08:00'}
                          for k in ('rev_yoy','eps','operating_margin','debt_ratio')}}
