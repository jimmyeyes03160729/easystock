#!/usr/bin/env python3
"""Isolated Shioaji history archive. Never writes live journals, labels or models."""
import argparse
from collections import Counter
from datetime import date, datetime, timedelta, timezone, time as clock
import fcntl
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import time

TPE = timezone(timedelta(hours=8))
DATA = Path('/home/ubuntu/easystock-history-data')
LIVE = Path('/home/ubuntu/easystock')
MB = 1024 * 1024
TICK_FIELDS = ('ts', 'close', 'volume', 'tick_type', 'bid_price', 'ask_price')
BAR_FIELDS = ('ts', 'Open', 'High', 'Low', 'Close', 'Volume', 'Amount')

class StopRun(Exception):
    pass

def raw_datetime(ns):
    # Observed SDK convention: naive Taiwan wall-clock encoded in nanoseconds.
    return datetime(1970, 1, 1) + timedelta(microseconds=int(ns) // 1000)

def native(x):
    if isinstance(x, dict): return {k: native(v) for k,v in x.items()}
    if isinstance(x, (list, tuple)): return [native(v) for v in x]
    if hasattr(x, 'tolist'): return native(x.tolist())
    if hasattr(x, 'item'): return native(x.item())
    return x

def save(path, value, compressed=False):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    payload = json.dumps(native(value), ensure_ascii=False, allow_nan=False).encode()
    if compressed: payload = gzip.compress(payload)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_bytes(payload); tmp.chmod(0o600); tmp.replace(path)

def load(path, compressed=False):
    payload = path.read_bytes()
    return json.loads(gzip.decompress(payload) if compressed else payload)

def validate(data, fields, day=None):
    if any(k not in data for k in fields): raise ValueError('missing_fields')
    n = len(data['ts'])
    if not n: raise ValueError('empty_data')
    if any(len(data[k]) != n for k in fields): raise ValueError('field_length_mismatch')
    ts = data['ts']
    if any(int(a) > int(b) for a,b in zip(ts, ts[1:])): raise ValueError('time_not_sorted')
    times = [raw_datetime(t) for t in ts]
    if day and any(t.date().isoformat() != day for t in times): raise ValueError('wrong_date')
    for k in fields:
        if k != 'ts' and any(not isinstance(v, (int,float)) or not math.isfinite(v) for v in data[k]):
            raise ValueError('invalid_numeric')
    prices = ('close',) if 'close' in fields else ('Open','High','Low','Close')
    if any(v <= 0 for k in prices for v in data[k]): raise ValueError('nonpositive_price')
    volume = 'volume' if 'volume' in fields else 'Volume'
    if any(v < 0 for v in data[volume]): raise ValueError('negative_volume')
    return times

def audit(ticks, bars, day):
    tt = validate(ticks, TICK_FIELDS, day); bt = validate(bars, BAR_FIELDS, day)
    if len(set(bars['ts'])) != len(bt): raise ValueError('duplicate_bar_timestamp')
    if any(t.second or t.microsecond for t in bt): raise ValueError('non_minute_bar')
    regular = [i for i,t in enumerate(tt) if clock(9) <= t.time() <= clock(13,30)]
    normal_bars = [i for i,t in enumerate(bt) if clock(9,1) <= t.time() <= clock(13,30)]
    if not regular or not normal_bars: raise ValueError('no_regular_session')
    expected = {datetime.fromisoformat(day)+timedelta(hours=9, minutes=i) for i in range(1,271)}
    present = {bt[i] for i in normal_bars}
    tv = sum(ticks['volume'][i] for i in regular)
    bv = sum(bars['Volume'][i] for i in normal_bars)
    return {
        'ticks': len(tt), 'regular_ticks': len(regular),
        'outside_session_ticks': len(tt)-len(regular),
        'raw_first': tt[0].isoformat(), 'raw_last': tt[-1].isoformat(),
        'regular_first': tt[regular[0]].isoformat(), 'regular_last': tt[regular[-1]].isoformat(),
        'bars': len(bt), 'regular_bars': len(normal_bars),
        'missing_bar_ends': [x.isoformat() for x in sorted(expected-present)],
        'classified_ratio': sum(ticks['tick_type'][i] in (1,2) for i in regular)/len(regular),
        'tick_volume': tv, 'bar_volume': bv,
        'tick_to_bar_volume_ratio': tv/bv if bv else None,
        'timestamp_convention': 'SDK naive Taiwan wall-clock; do not add 8 hours',
        'bar_timestamp': 'minute end; replay must only expose completed bars',
        'training_eligible': False,
        'reason': 'archive only; historical reference prices, universe and replay still required',
    }

class Session:
    def __init__(self, api, max_mb, reserve_mb):
        self.api=api; self.max_bytes=max_mb*MB; self.reserve=reserve_mb*MB
        self.start=int(api.usage().bytes); self.calls=0
    def request(self, method, **kwargs):
        now=datetime.now(TPE)
        if now.weekday()<5 and clock(8)<=now.time().replace(tzinfo=None)<clock(14):
            raise StopRun('trading_hours')
        if shutil.disk_usage(DATA).free < 2*1024*MB: raise StopRun('disk_below_2GB')
        usage=self.api.usage(); used=int(usage.bytes)-self.start
        # Allow room for one response; server response size is not known in advance.
        if int(usage.bytes)<self.start: raise StopRun('quota_reset_start_new_run')
        remaining = int(usage.remaining_bytes)
        use_remainder = os.getenv('EASYSTOCK_HISTORY_USE_REMAINDER') == '1' and now.weekday() >= 5
        if remaining <= 0: raise StopRun('quota_exhausted')
        if not use_remainder and remaining < self.reserve+20*MB: raise StopRun('quota_reserve')
        if used>=self.max_bytes: raise StopRun('run_budget')
        time.sleep(2)
        self.calls+=1
        return native(getattr(self.api,method)(**kwargs).dict())

def contract(api, symbol):
    for exchange in ('TSE','OTC'):
        try: return getattr(api.Contracts.Stocks,exchange)[symbol]
        except (KeyError,AttributeError,TypeError): pass
    raise ValueError('contract_missing')

def calendar(session, api, spec):
    end=date.fromisoformat(spec['end']); begin=end-timedelta(days=269)
    c=contract(api,'0050'); cursor=begin; days=set()
    while cursor<=end:
        last=min(end,cursor+timedelta(days=29))
        p=DATA/'calendar'/f'{cursor}_{last}.json.gz'
        if p.exists(): data=load(p,True)
        else:
            data=session.request('kbars',contract=c,start=str(cursor),end=str(last),timeout=30000)
            validate(data,BAR_FIELDS)
            save(p,data,True)
        times=validate(data,BAR_FIELDS)
        if any(not cursor<=t.date()<=last for t in times): raise ValueError('calendar_outside_range')
        days.update(t.date().isoformat() for t in times if t.weekday()<5 and clock(9,1)<=t.time()<=clock(13,30))
        cursor=last+timedelta(days=1)
    chosen=sorted(days)[-spec['days']:]
    if len(chosen)<spec['days']: raise ValueError('insufficient_observed_calendar_days')
    spec['dates']=chosen
    save(DATA/'plan.json',spec)
    return spec

def progress(spec):
    counts=Counter({k:0 for k in ('archived_stock_days','stock_days_with_missing_minutes','corrupt_stock_days','failed_stock_days')}); completed_days=[]; audits=[]
    for day in spec.get('dates',[]):
        count=0
        for symbol in spec['symbols']:
            p=DATA/'raw'/day/(symbol+'.json.gz'); failure=DATA/'failures'/day/(symbol+'.json')
            if p.exists():
                try:
                    pack=load(p,True)
                    if pack.get('symbol')!=symbol or pack.get('date')!=day: raise ValueError('identity')
                    a=audit(pack['ticks'],pack['kbars'],day)
                    count+=1; counts['archived_stock_days']+=1
                    if a['missing_bar_ends']: counts['stock_days_with_missing_minutes']+=1
                    audits.append({'symbol':symbol,'date':day,**a})
                except (ValueError,KeyError,TypeError,OSError,EOFError): counts['corrupt_stock_days']+=1
            elif failure.exists(): counts['failed_stock_days']+=1
        if count==len(spec['symbols']): completed_days.append(day)
    summary={'phase':'archive_only','target_dates':spec['days'], 'calendar_dates':len(spec.get('dates',[])),
      'symbols':spec['symbols'],'target_stock_days':len(spec['symbols'])*spec['days'],
      'fully_archived_dates':len(completed_days),**dict(counts),
      'training_days_added':0,'model_applied':False,
      'updated_at':datetime.now(TPE).isoformat(),
      'scope':'fixed pilot symbols, not historical full-market selection',
      'data_dir':str(DATA)}
    save(DATA/'progress.json',summary)
    # Small coverage report, no raw ticks in terminal.
    save(DATA/'coverage.json',audits)
    return summary

def main():
    os.umask(0o077)
    p=argparse.ArgumentParser(description=__doc__)
    mode=p.add_mutually_exclusive_group(required=True)
    mode.add_argument('--collect',action='store_true');mode.add_argument('--status',action='store_true')
    p.add_argument('--end');p.add_argument('--days',type=int,default=120)
    p.add_argument('--symbols',default='2317,2303,2409,3481,2884')
    p.add_argument('--max-pairs',type=int,default=5)
    p.add_argument('--max-mb',type=int,default=100)
    p.add_argument('--reserve-mb',type=int,default=100)
    p.add_argument('--retry-failed',action='store_true')
    args=p.parse_args()
    if not 101<=args.days<=180 or not 1<=args.max_pairs<=20 or not 20<=args.max_mb<=150 or args.reserve_mb<100:
        p.error('days 101..180; max-pairs 1..20; max-mb 20..150; reserve-mb >=100')
    DATA.mkdir(parents=True,exist_ok=True,mode=0o700)
    with (DATA/'download.lock').open('a') as lock:
        try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: raise SystemExit('Another archive job is running')
        plan=DATA/'plan.json'
        if args.status:
            if not plan.exists(): raise SystemExit('No archive plan yet')
            print(json.dumps(progress(load(plan)),ensure_ascii=False,indent=2));return
        now=datetime.now(TPE)
        if now.weekday()<5 and clock(8)<=now.time().replace(tzinfo=None)<clock(14):
            raise SystemExit('Run after 14:00 Taiwan time')
        symbols=list(dict.fromkeys(args.symbols.split(',')))
        if not 1<=len(symbols)<=55 or any(not re.fullmatch(r'\d{4}',s) for s in symbols):p.error('1..55 four-digit symbols')
        if plan.exists():
            spec=load(plan)
            if symbols!=spec['symbols'] or args.days!=spec['days'] or (args.end and args.end!=spec['end']):
                raise SystemExit('Plan frozen; use original symbols/days/end to resume')
        else:
            end=date.fromisoformat(args.end) if args.end else now.date()-timedelta(days=1)
            if end>=now.date():p.error('end must be before today')
            spec={'version':1,'end':str(end),'days':args.days,'symbols':symbols,'dates':[]}
            save(plan,spec)
        from dotenv import load_dotenv
        load_dotenv(LIVE/'.env');load_dotenv('/home/ubuntu/easystock-learning.env',override=True)
        key=os.getenv('SJ_API_KEY') or os.getenv('SHIOAJI_API_KEY')
        secret=os.getenv('SJ_SEC_KEY') or os.getenv('SJ_SECRET_KEY') or os.getenv('SHIOAJI_SECRET_KEY')
        if not key or not secret:raise SystemExit('Missing API configuration; do not print keys')
        import shioaji as sj
        api=sj.Shioaji(); stop='pair_limit_or_plan_complete';attempted=0
        try:
            api.login(api_key=key,secret_key=secret)
            session=Session(api,args.max_mb,args.reserve_mb)
            if not spec['dates']: spec=calendar(session,api,spec)
            for day in spec['dates']:
                for symbol in symbols:
                    dst=DATA/'raw'/day/(symbol+'.json.gz');failure=DATA/'failures'/day/(symbol+'.json')
                    if dst.exists() or (failure.exists() and not args.retry_failed):continue
                    if attempted>=args.max_pairs:raise StopRun('pair_limit')
                    attempted+=1
                    try:
                        c=contract(api,symbol)
                        # Cache each response immediately so interruption does not repeat ticks.
                        parts={}
                        for kind in ('ticks','kbars'):
                            cache=DATA/'parts'/day/(symbol+'-'+kind+'.json.gz')
                            if cache.exists():data=load(cache,True)
                            else:
                                options=({'date':day,'query_type':sj.constant.TicksQueryType.AllDay} if kind=='ticks' else {'start':day,'end':day})
                                data=session.request(kind,contract=c,timeout=30000,**options)
                                validate(data,TICK_FIELDS if kind=='ticks' else BAR_FIELDS,day)
                                save(cache,data,True)
                            parts[kind]=data
                        check=audit(parts['ticks'],parts['kbars'],day)
                        pack={'version':1,'symbol':symbol,'date':day,'source':'shioaji','audit':check,**parts}
                        save(dst,pack,True)
                        if failure.exists():failure.unlink()
                        for kind in parts:(DATA/'parts'/day/(symbol+'-'+kind+'.json.gz')).unlink()
                        print(json.dumps({'archived':symbol,'date':day,'regular_ticks':check['regular_ticks'],'regular_bars':check['regular_bars']},ensure_ascii=False),flush=True)
                    except StopRun:raise
                    except Exception as exc:
                        save(failure,{'symbol':symbol,'date':day,'error_type':type(exc).__name__})
                        print(json.dumps({'failed':symbol,'date':day,'error_type':type(exc).__name__}),flush=True)
                        # No API retry storm: inspect a failed response before continuing.
                        raise StopRun('pair_failed_inspect_before_retry')
        except StopRun as exc:stop=str(exc)
        except Exception as exc:stop='error_'+type(exc).__name__
        finally:
            try:api.logout()
            except Exception:pass
        result=progress(spec);result.update(stop_reason=stop,attempted_this_run=attempted)
        save(DATA/'progress.json',result)
        print('===== BACKFILL SUMMARY =====')
        print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
