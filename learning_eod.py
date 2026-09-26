#!/usr/bin/env python3
"""Post-close collector/review. Default is offline; explicit flags enable external APIs."""
import argparse
import fcntl
import json
import os
from pathlib import Path
from datetime import datetime, time


def main():
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent/'.env')
    from daytrade_learning.runtime import DATA,TPE
    from daytrade_learning.research import journal, collect, build, save, train_candidate, finite
    from daytrade_learning.core import gemini_review
    from daytrade_learning.eod_support import review_once, read_report, report_status
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--date',default=datetime.now(TPE).date().isoformat())
    parser.add_argument('--collect',action='store_true')
    parser.add_argument('--gemini',action='store_true')
    parser.add_argument('--train',action='store_true')
    parser.add_argument('--publish',action='store_true')
    parser.add_argument('--retry-ai',action='store_true',help='Explicitly reset failed AI attempt budget for this input')
    args=parser.parse_args()
    if args.train and (args.collect or args.gemini or args.publish):
        parser.error('--train must run separately; use learning_cycle.py for the full pipeline')
    day=datetime.strptime(args.date,'%Y-%m-%d').date().isoformat()
    now=datetime.now(TPE)
    if args.collect and (day!=now.date().isoformat() or not time(13,35)<=now.time().replace(tzinfo=None)<=time(20,30)):
        raise SystemExit('Collection only allowed for today between 13:35 and 20:30 Asia/Taipei')
    DATA.mkdir(parents=True,exist_ok=True,mode=0o700)
    with open(DATA/'eod.lock','a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise SystemExit('Research job already running')
        if args.train:
            result=train_candidate(DATA)
            save(DATA/'training-status.json',result)
            print(json.dumps({k:v for k,v in result.items() if k not in ('coef','mean','scale')},ensure_ascii=False))
            return
        settings=json.loads((Path(__file__).parent/'daytrade_learning/settings.json').read_text())
        for key in ('fee_rate','minimum_fee_twd','sell_tax_rate','slippage_bps','shares'):
            settings[key]=finite(settings[key])
            if settings[key]<0:raise ValueError('Negative cost settings')
        if settings['shares']<=0 or settings['slippage_bps']>=1000:raise ValueError('Invalid research cost settings')
        lo,hi,cap=[finite(settings['filters'][k]) for k in ('min_price','max_price','max_gain_pct')]
        if not 0<lo<=hi or not 0<=cap<=100:raise ValueError('Invalid research price filters')
        observations,bad=journal(DATA/('journal-'+day+'.jsonl'))
        if not any(r.get('kind')=='sample' and r.get('data',{}).get('observed_at','')[:10]==day for r in observations):
            print(json.dumps({'status':'skipped','date':day,'reason':'No same-day live samples; holiday, not installed yet, or missing feed'},ensure_ascii=False))
            return
        previous=read_report(DATA/'reports'/(day+'.json'))
        collected=None
        if args.collect:
            import shioaji as sj
            api=sj.Shioaji()
            try:
                key=os.getenv('SJ_API_KEY') or os.getenv('SHIOAJI_API_KEY')
                secret=os.getenv('SJ_SECRET_KEY') or os.getenv('SHIOAJI_SECRET_KEY')
                if not key or not secret:raise RuntimeError('Shioaji environment credentials missing')
                api.login(api_key=key,secret_key=secret)
                collected=collect(api,DATA,day,observations)
            finally:
                try:api.logout()
                except Exception:pass
        result=build(DATA,day,settings,persist_report=False)
        if collected is not None:result['collection']=collected
        elif previous.get('collection'):result['collection']=previous['collection']
        if args.gemini and result['bars_symbols']:
            result['ai'],result['ai_cache']=review_once(
                DATA,day,result,previous,gemini_review,reset=args.retry_ai)
        elif previous.get('ai'):
            # Keep the historical review separately; do not present it as a review of changed inputs.
            result['previous_ai']=previous['ai']
        result['status']=report_status(result)
        save(DATA/'reports'/(day+'.json'),result)
        if args.publish:
            from firebase_store import FirebaseStore
            store=FirebaseStore()
            public={k:result[k] for k in ('version','date','status','sample_count','bars_symbols','labeled_count','surges','simulation','limitations')}
            if 'ai' in result:public['ai']=result['ai']
            public['collection']=result.get('collection',{})
            # Date-specific child only; no intraday_live overwrite and no rule changes.
            store.root.child('daytrade_research').child(day).set(public)
        print(json.dumps({'date':day,'status':result['status'],'samples':result['sample_count'],'labeled':result['labeled_count'],'bars_symbols':result['bars_symbols'],'ai_status':result.get('ai',{}).get('status','not_requested')},ensure_ascii=False))
        if collected is not None and not collected['downloaded']:
            raise SystemExit('No usable collected symbols; report saved; investigation required')
        if result['status']=='partial':
            print('Partial result saved. See collection.failure_details and ai status. No whole-service retry for partial results.')


if __name__=='__main__':main()
