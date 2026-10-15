"""Immutable closing-eight universe for next-session B1 shadow comparison."""
from datetime import datetime,timedelta
import hashlib
import json
from pathlib import Path
import re
from eight_methods.rules import TPE,stamp,number,CLOSING

TRIAL='B1_CLOSING_EIGHT_POOL_V1'
MAX_SYMBOLS=10


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,allow_nan=False,indent=2),encoding='utf-8');temp.replace(path)


def observe(feed,root,now):
    if feed.get('version')!=CLOSING or feed.get('day')!=now.date().isoformat() or not '13:00:00'<=now.strftime('%H:%M:%S')<'13:25:00':return
    if stamp(feed['updated_at'])>now:return
    write(Path(root)/'observations'/(feed['day']+'.json'),feed)


def next_session(day):
    from market_calendar import is_market_open
    base=datetime.fromisoformat(day).date()
    for n in range(1,15):
        candidate=(base+timedelta(days=n)).isoformat()
        if is_market_open(candidate)[0]:return candidate
    raise ValueError('next_session_unknown')


def select(feed):
    if feed.get('version')!=CLOSING or feed.get('ruleset')!='TW_CLOSING_RULES_V1':return []
    observed=stamp(feed['updated_at'])
    if not '13:00:00'<=observed.strftime('%H:%M:%S')<'13:25:00':return []
    selected={}
    for r in feed.get('rows',[]):
        try:
            symbol=r['symbol'];at=stamp(r['quote_at'])
            conditions=r.get('conditions',[])
            if not re.fullmatch(r'[1-9]\d{3}',symbol) or r.get('phase')!='observing' or r.get('complete') is not True:continue
            if len(conditions)!=8 or {c['id'] for c in conditions}!=set(range(1,9)) or any(c['state']!='pass' for c in conditions):continue
            if at.date()!=observed.date() or not 0<=(observed-at).total_seconds()<=30:continue
            if not number(r.get('price'),True) or r['price']*1000>200000 or not number(r.get('day_volume'),True):continue
            selected[symbol]={k:r.get(k) for k in ('symbol','name','price','quote_at','day_volume','turnover_pct','market_cap','quantity_check','shares_source','shares_asof')}
        except (KeyError,ValueError,TypeError):continue
    # Frozen ranking: cumulative shares descending, code ascending. No outcomes.
    return sorted(selected.values(),key=lambda r:(-r['day_volume'],r['symbol']))[:MAX_SYMBOLS]


def freeze(root,day,target,now):
    root=Path(root)
    if now.date().isoformat()!=day or now.strftime('%H:%M:%S')<'13:25:00':raise ValueError('freeze_before_cutoff_or_wrong_day')
    path=root/'pools'/(target+'.json')
    if path.exists():return load(root,target)  # No after-the-fact pool replacement.
    from market_calendar import is_market_open
    if not is_market_open(day)[0]:raise ValueError('source_not_trading_session')
    if target<=day or next_session(day)!=target:raise ValueError('not_next_trading_session')
    observed=root/'observations'/(day+'.json')
    feed=json.loads(observed.read_text(encoding='utf-8')) if observed.exists() else {}
    if feed and (feed.get('day')!=day or stamp(feed['updated_at'])>now):raise ValueError('invalid_observation_day')
    rows=select(feed)
    from eight_methods.feed import summarize
    assessment=summarize(feed)
    empty_status='EMPTY_DATA_INSUFFICIENT' if not feed or not assessment['observed'] or assessment['insufficient'] else 'EMPTY_NO_MATCH'
    reason='' if rows else ('13:25前沒有有效尾盤觀察資料；不補選' if not feed else
                            f"資料不足 {assessment['insufficient']}/{assessment['observed']} 檔；完整判定 {assessment['complete']} 檔，沒有適用B1單筆額度且八項全過的候選；不補選" if assessment['insufficient'] else
                            '完整判定後沒有八項全過且適用B1單筆額度的候選；不補選')
    value={'schema_version':1,'trial':TRIAL,'source_day':day,'target_day':target,
        'frozen_at':now.isoformat(),'observation_at':feed.get('updated_at'),
        'source_snapshot_sha256':digest(feed),'ruleset':'TW_CLOSING_RULES_V1',
        'ranking':'day_volume_shares_desc_then_symbol','max_symbols':MAX_SYMBOLS,
        'rows':rows,'symbols':[r['symbol'] for r in rows],'status':'READY' if rows else empty_status,'assessment':assessment,
        'reason':reason,'production_effect':'B1_SHADOW_ONLY'}
    value['receipt_sha256']=digest(value);write(path,value)
    return value


def load(root,target):
    path=Path(root)/'pools'/(target+'.json')
    if not path.exists():return {'status':'MISSING','symbols':[],'reason':'缺少前一交易日凍結尾盤名單'}
    x=json.loads(path.read_text(encoding='utf-8'));receipt=x.pop('receipt_sha256',None)
    if digest(x)!=receipt or x.get('trial')!=TRIAL or x.get('target_day')!=target or len(x.get('symbols',[]))>MAX_SYMBOLS:raise ValueError('invalid_pool_receipt')
    if not x['source_day']<target or stamp(x['frozen_at']).date().isoformat()!=x['source_day']:raise ValueError('pool_not_frozen_previous_session')
    symbols=x.get('symbols',[])
    if len(set(symbols))!=len(symbols) or any(not re.fullmatch(r'[1-9]\d{3}',s) for s in symbols):raise ValueError('invalid_pool_symbols')
    if stamp(x['frozen_at']).strftime('%H:%M:%S')<'13:25:00':raise ValueError('pool_frozen_before_cutoff')
    x['receipt_sha256']=receipt;return x


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--root',default='/home/ubuntu/easystock-b1-closing');a=p.parse_args()
    now=datetime.now(TPE);day=now.date().isoformat();print(json.dumps(freeze(a.root,day,next_session(day),now),ensure_ascii=False))
