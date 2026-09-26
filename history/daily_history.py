#!/usr/bin/env python3
"""Resumable after-hours Shioaji archive; no orders or model promotion."""
from contextlib import ExitStack
from datetime import date, datetime, time as clock, timedelta
import fcntl
import json
import os
from pathlib import Path
import shutil
import sys
import time

import collector_core as core

DATA = Path(os.getenv('EASYSTOCK_HISTORY_DATA','/home/ubuntu/easystock-history-expanded-data'))
OLDDATA = Path('/home/ubuntu/easystock-history-data')
FLOOR = date(2020,3,2)  # Shioaji's documented stock/index history boundary.
REQUESTED = '2010-01-01'
RESERVE_MB = 120


def allowed(now=None):
    now = now or datetime.now(core.TPE)
    return clock(14) <= now.time().replace(tzinfo=None) < clock(22)


def eligible_failure(record, now):
    return not record.get('review_required',False) and record.get('retry_after',0) <= now


def next_window(plan):
    cursor = date.fromisoformat(plan.get('calendar_before',min(plan['dates'])))-timedelta(days=1)
    if cursor < FLOOR: return None
    return max(FLOOR,cursor-timedelta(days=29)),cursor


def validate_plan(plan):
    symbols=plan.get('symbols',[]);dates=plan.get('dates',[])
    import re
    if not symbols or len(symbols)>core.MAX_HISTORY_SYMBOLS or len(set(symbols))!=len(symbols) or any(not re.fullmatch(r'\d{4}',s) for s in symbols):
        raise ValueError('invalid_symbols')
    if not dates or dates!=sorted(set(dates)):raise ValueError('invalid_dates')
    if any(date.fromisoformat(d)<FLOOR for d in dates):raise ValueError('invalid_history_boundary')
    return plan


def read_failure(day,symbol):
    path=DATA/'retry-state'/day/(symbol+'.json')
    return core.load(path) if path.exists() else {}


def summarize(plan,reason,usage=None):
    # Previously archived files were audited by the old collector. The offline
    # trainer independently validates each frozen source before using it.
    pairs={(p.parent.name,p.name.removesuffix('.json.gz')) for p in (DATA/'raw').glob('*/*.json.gz')}
    valid={(d,s) for d in plan['dates'] for s in plan['symbols']}
    retries=[core.load(p) for p in (DATA/'retry-state').glob('*/*.json')]
    unresolved=[r for r in retries if (r['date'],r['symbol']) not in pairs]
    legacy={(p.parent.name,p.stem) for p in (DATA/'failures').glob('*/*.json')}
    gaps=(legacy | {(r['date'],r['symbol']) for r in unresolved})-pairs
    status={'phase':'archive_only','archived_stock_days':len(pairs & valid),
        'target_stock_days':len(valid),'failed_stock_days':len(gaps & valid),
        'review_required_stock_days':sum(bool(r.get('review_required')) for r in unresolved),
        'calendar_dates':len(plan['dates']),'target_dates':len(plan['dates']),
        'stop_reason':reason,'requested_start':REQUESTED,'available_start':str(FLOOR),
        'planned_start':min(plan['dates']),'planned_end':max(plan['dates']),
        'calendar_complete':plan.get('calendar_before')==str(FLOOR),
        'coverage_complete':False,'unavailable_before':str(FLOOR),
        'schedule':'每日 14:00–22:00（Asia/Taipei）','model_applied':False,
        'symbol_count':len(plan['symbols']),
        'scope':f"Frozen current {len(plan['symbols'])}-stock pool, not whole-market history; pre-listing and missing data remain gaps.",
        'updated_at':datetime.now(core.TPE).isoformat()}
    if usage is not None:
        status['remaining_mb']=round(int(usage.remaining_bytes)/core.MB,1)
    core.save(DATA/'progress.json',status)
    return status


class Session:
    def __init__(self,api):self.api=api
    def check(self):
        if not allowed():raise core.StopRun('outside_window')
        if (DATA/'auto-stop.request').exists():raise core.StopRun('user_stopped')
        if shutil.disk_usage(DATA).free < 5*1024**3:raise core.StopRun('disk_reserve')
        usage=self.api.usage()
        if int(usage.remaining_bytes) < RESERVE_MB*core.MB:raise core.StopRun('quota_reserve')
        return usage
    def request(self,method,**kwargs):
        self.check();time.sleep(3)
        return core.native(getattr(self.api,method)(**kwargs,timeout=30000).dict())


def collect_pair(session,api,symbol,day,ticks_query):
    c=core.contract(api,symbol)
    result={}
    for kind,fields in [('ticks',core.TICK_FIELDS),('kbars',core.BAR_FIELDS)]:
        cache=DATA/'parts'/day/(symbol+'-'+kind+'.json.gz')
        if cache.exists():data=core.load(cache,True)
        else:
            args={'date':day,'query_type':ticks_query} if kind=='ticks' else {'start':day,'end':day}
            data=session.request(kind,contract=c,**args)
            # An empty response can mean quota exhaustion, not a holiday.
            if not data.get('ts'):session.check()
            core.validate(data,fields,day)
            core.save(cache,data,True)
        core.validate(data,fields,day)
        result[kind]=data
    audit=core.audit(result['ticks'],result['kbars'],day)
    core.save(DATA/'raw'/day/(symbol+'.json.gz'),
        {'version':1,'source':'shioaji','symbol':symbol,'date':day,'audit':audit,**result},True)
    # Parts are redundant only after the complete archive is atomically replaced.
    for kind in result:(DATA/'parts'/day/(symbol+'-'+kind+'.json.gz')).unlink(missing_ok=True)


def extend_calendar(session,api,plan):
    window=next_window(plan)
    if window is None:return False
    start,end=window
    cache=DATA/'calendar-long'/f'{start}_{end}.json.gz'
    if cache.exists():bars=core.load(cache,True)
    else:
        bars=session.request('kbars',contract=core.contract(api,'0050'),start=str(start),end=str(end))
        if not bars.get('ts'):session.check()
        core.validate(bars,core.BAR_FIELDS)
        core.save(cache,bars,True)
    times=core.validate(bars,core.BAR_FIELDS)
    if any(not start<=t.date()<=end for t in times):raise ValueError('calendar_outside_range')
    dates={t.date().isoformat() for t in times if t.weekday()<5 and clock(9,1)<=t.time()<=clock(13,30)}
    if not dates:raise ValueError('empty_calendar_requires_review')
    plan['dates']=sorted(set(plan['dates'])|dates)
    plan.update(days=len(plan['dates']),calendar_before=str(start),requested_start=REQUESTED,available_start=str(FLOOR),version=2)
    core.save(DATA/'plan.json',plan)
    return True


def run():
    os.umask(0o077)
    if not allowed():print('Outside 14:00–22:00 Taipei; waiting for next timer');return 0
    DATA.mkdir(parents=True,exist_ok=True,mode=0o700)
    core.DATA=DATA
    with ExitStack() as stack:
        # Mutually exclusive with both legacy runners and the offline trainer.
        for path in [DATA/'auto.lock',DATA/'download.lock',OLDDATA/'auto.lock',OLDDATA/'download.lock']:
            path.parent.mkdir(parents=True,exist_ok=True)
            lock=stack.enter_context(path.open('a'))
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:print('Another archive/training job is active');return 1
        plan=validate_plan(core.load(DATA/'plan.json'))
        if (DATA/'auto-stop.request').exists():summarize(plan,'user_stopped');return 0
        from dotenv import load_dotenv
        load_dotenv('/home/ubuntu/easystock/.env')
        load_dotenv('/home/ubuntu/easystock-learning.env',override=True)
        key=os.getenv('SJ_API_KEY') or os.getenv('SHIOAJI_API_KEY')
        secret=os.getenv('SJ_SEC_KEY') or os.getenv('SJ_SECRET_KEY') or os.getenv('SHIOAJI_SECRET_KEY')
        if not key or not secret:summarize(plan,'credentials_missing');return 1
        import shioaji as sj
        api=sj.Shioaji();reason='retry_pending';exitcode=0
        try:
            api.login(api_key=key,secret_key=secret)
            session=Session(api);failures=0;processed=0
            summarize(plan,'downloading',session.check())
            while True:
                for day in reversed(plan['dates']):
                    for symbol in plan['symbols']:
                        if (DATA/'raw'/day/(symbol+'.json.gz')).exists():continue
                        previous=read_failure(day,symbol)
                        if not eligible_failure(previous,time.time()):continue
                        try:
                            collect_pair(session,api,symbol,day,sj.constant.TicksQueryType.AllDay)
                            processed+=1;failures=0
                        except core.StopRun:raise
                        except Exception as exc:
                            session.check()
                            attempts=previous.get('attempts',0)+1
                            data_error=isinstance(exc,(ValueError,KeyError,TypeError,EOFError))
                            core.save(DATA/'retry-state'/day/(symbol+'.json'),{'symbol':symbol,'date':day,
                                'attempts':attempts,'retry_after':time.time()+86400*min(7,2**min(attempts-1,3)),
                                'review_required':data_error and attempts>=3,
                                'error_type':type(exc).__name__})
                            failures+=1
                            if failures>=3:raise core.StopRun('transient_error')
                        if processed%10==0:summarize(plan,'downloading',session.check())
                # Never stop at 6,600: progressively add older observed market dates.
                if not extend_calendar(session,api,plan):
                    reason='available_range_scanned_with_gaps';break
                summarize(plan,'downloading',session.check())
        except core.StopRun as exc:
            reason=str(exc);exitcode=1 if reason=='transient_error' else 0
        except Exception as exc:
            reason='error_'+type(exc).__name__;exitcode=1
        finally:
            try:api.logout()
            except Exception:pass
            summarize(plan,reason)
        print('History batch:',reason)
        return exitcode


if __name__=='__main__':sys.exit(run())
