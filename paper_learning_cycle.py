"""After-close feedback and a single, explicit paper-model training/deployment path.

Labels are 15-minute executable-quote markouts (not actual fills or realized P&L).
Rejected buys keep those labels. No model-generated Python is ever executed.
"""
import argparse
from bisect import bisect_left
from datetime import datetime, timedelta
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import sys
from urllib.request import Request, urlopen
from paper_legacy.decisions import Decisions,TPE
from paper_legacy.features import REQUIRED_FEATURES

DATA=Path(os.getenv('LEARNING_DATA_DIR','/home/ubuntu/easystock-learning-data'))
ARCHIVE=Path('/home/ubuntu/easystock-history-expanded-data')
PILOT=Path('/home/ubuntu/easystock-history-pilot-output/runs')
LABEL_POLICY='quote-15m-cost0.6-v1'

def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(value,ensure_ascii=False,allow_nan=False),encoding='utf-8')
    tmp.chmod(0o600);tmp.replace(path)

def read(path,default=None):
    try:return json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:return default

def finite(v):return not isinstance(v,bool) and isinstance(v,(int,float)) and math.isfinite(v)

def quote_label(ticks,at):
    """Same first-subsequent-quote policy as historical pilot, no cherry-picked quote."""
    wall=at.astimezone(TPE).replace(tzinfo=None)
    ns=int((wall-datetime(1970,1,1)).total_seconds()*1e9)
    def first(target):
        i=bisect_left(ticks['ts'],target)
        if i>=len(ticks['ts']) or ticks['ts'][i]>target+30*10**9:return None
        bid,ask=ticks['bid_price'][i],ticks['ask_price'][i]
        if not finite(bid) or not finite(ask) or not 0<bid<=ask or (ask/bid-1)*100>1:return None
        return i
    i=first(ns+10**9)
    if i is None:return None
    j=first(ticks['ts'][i]+15*60*10**9)
    if j is None:return None
    return {'net_markout_pct':(ticks['bid_price'][j]/ticks['ask_price'][i]-1)*100-0.6,
        'entry_ask':ticks['ask_price'][i],'exit_bid':ticks['bid_price'][j],
        'entry_ns':ticks['ts'][i],'exit_ns':ticks['ts'][j],'label_policy':LABEL_POLICY}

def decision_rows(day):
    book=Decisions()
    with book.connect() as c:
        c.row_factory=sqlite3.Row
        rows=[dict(r) for r in c.execute('SELECT * FROM decisions WHERE day=? ORDER BY observed_at,symbol',(day,))]
    for r in rows:
        for k in ('features','model','context'):r[k]=json.loads(r[k])
    return rows

def collect(day,network=False):
    rows=decision_rows(day);cache={};errors={};api=None
    try:
        for symbol in sorted({r['symbol'] for r in rows}):
            archive=ARCHIVE/'raw'/day/(symbol+'.json.gz')
            target=DATA/'decision-ticks'/day/(symbol+'.json.gz')
            try:
                if archive.exists():t=json.loads(gzip.decompress(archive.read_bytes()))['ticks']
                elif target.exists():t=json.loads(gzip.decompress(target.read_bytes()))
                elif network:
                    if api is None:
                        import shioaji as sj
                        api=sj.Shioaji();api.login(api_key=os.getenv('SJ_API_KEY') or os.getenv('SHIOAJI_API_KEY'),secret_key=os.getenv('SJ_SECRET_KEY') or os.getenv('SHIOAJI_SECRET_KEY'))
                    if api.usage().remaining_bytes < 120*1024**2:raise RuntimeError('quota_reserve')
                    from history.collector_core import contract,native,validate,TICK_FIELDS
                    t=native(api.ticks(contract(api,symbol),date=day,timeout=30000).dict())
                    validate(t,TICK_FIELDS,day)
                    target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
                    tmp=target.with_suffix('.tmp');tmp.write_bytes(gzip.compress(json.dumps(t).encode()));tmp.chmod(0o600);tmp.replace(target)
                else:raise RuntimeError('tick_archive_missing')
                from history.collector_core import validate,TICK_FIELDS
                validate(t,TICK_FIELDS,day);cache[symbol]=t
            except Exception as e:errors[symbol]=type(e).__name__+':'+str(e)[:60] if isinstance(e,RuntimeError) else type(e).__name__
        labeled=[];unresolved=[];until={}
        for r in rows:
            if not all(finite(r['features'].get(k)) for k in REQUIRED_FEATURES):
                unresolved.append({'id':r['id'],'reason':'incomplete_features'});continue
            at=datetime.fromisoformat(r['observed_at'])
            # Fixed windows: overlapping retries cannot count as independent training samples.
            if at <= until.get(r['symbol'],at-timedelta(seconds=1)):continue
            until[r['symbol']]=at+timedelta(minutes=16,seconds=1)
            label=quote_label(cache[r['symbol']],at) if r['symbol'] in cache else None
            if label:labeled.append({**r,**label,'date':day,'weight':1.0})
            else:unresolved.append({'id':r['id'],'symbol':r['symbol'],'reason':'future_quote_missing'})
        result={'date':day,'observations':len(rows),'rows':labeled,'unresolved':unresolved,'errors':errors,'policy':LABEL_POLICY}
        save(DATA/'paper-labels'/(day+'.json'),result)
        return result
    finally:
        if api is not None:api.logout()

def obj(properties):return {'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}
STR={'type':'string'}
SCHEMA=obj({'samples':{'type':'array','items':obj({'id':STR,'failure_type':{'type':'string','enum':['NONE','PATTERN_FAILURE','TIMING_ERROR','NOISE_EXTRINSIC','DATA_QUALITY']},'suggested_weight':{'type':'number'},'reason':STR})},
    'feature_proposals':{'type':'array','items':obj({'feature':{'type':'string','enum':list(REQUIRED_FEATURES)},'operator':{'type':'string','enum':['gt','lt']},'threshold':{'type':'number'},'reason':STR})},'summary':STR})

def review(dataset):
    day=dataset['date'];dest=DATA/'paper-feedback'/(day+'.json')
    existing=read(dest)
    if existing and existing.get('status')=='complete':return existing
    rows=dataset['rows']
    if not rows:return {'status':'waiting_labels','weights':{}}
    # Deterministic mix of winners/losers and executed/rejected observations.
    groups={}
    for r in rows:groups.setdefault((r['net_markout_pct']>0,'"status": "bought"' in r['execution']),[]).append(r)
    selected=[r for key in sorted(groups) for r in sorted(groups[key],key=lambda r:r['id'])[:6]]
    budget=read(DATA/'paper-feedback'/(day+'-budget.json'),{'attempts':0})
    if budget['attempts']>=2:return {'status':'attempt_limit','weights':{}}
    key=os.getenv('OPENAI_API_KEY')
    if not key:return {'status':'missing_api_key','weights':{}}
    budget['attempts']+=1;save(DATA/'paper-feedback'/(day+'-budget.json'),budget)
    evidence=[{k:r[k] for k in ('id','symbol','observed_at','features','context','net_markout_pct','execution')} for r in selected]
    body={'model':os.getenv('OPENAI_REVIEW_MODEL','gpt-5.6-luna'),'store':False,'reasoning':{'effort':'low'},'max_output_tokens':5000,
        'instructions':'你是量化研究的資料品質裁判。用繁體中文依JSON證據輸出。保留原始損益標籤。虧損、急跌或買不起本身不是刪除或降權理由。沒有大盤數值時不能斷言外部雜訊。suggested_weight只能0.5到1。資料足夠通常1。特徵建議只可用列出的既有數值特徵與比較運算，為待驗證假設。不得產生Python程式碼。',
        'input':json.dumps(evidence,ensure_ascii=False),'text':{'format':{'type':'json_schema','name':'paper_learning_feedback','strict':True,'schema':SCHEMA}}}
    req=Request('https://api.openai.com/v1/responses',data=json.dumps(body).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
    try:
        with urlopen(req,timeout=100) as response:raw=json.load(response)
        if raw.get('status')!='completed':raise ValueError('incomplete_output')
        value=json.loads(''.join(c.get('text','') for item in raw.get('output',[]) if item.get('type')=='message' for c in item.get('content',[]) if c.get('type')=='output_text'))
        indexed={r['id']:r for r in selected};weights={};seen=set()
        for s in value['samples']:
            if s['id'] not in indexed or s['id'] in seen or not finite(s['suggested_weight']) or not .5<=s['suggested_weight']<=1:raise ValueError('invalid_sample_feedback')
            seen.add(s['id'])
            # A model opinion cannot erase hard-market losses. Only objectively incomplete
            # context allows bounded reduction, and raw targets always remain unchanged.
            missing=not indexed[s['id']]['context'].get('bars5') or not indexed[s['id']]['context'].get('bars15')
            weights[s['id']]=s['suggested_weight'] if s['failure_type']=='DATA_QUALITY' and missing else 1.0
        if seen!=set(indexed):raise ValueError('missing_sample_feedback')
        for p in value['feature_proposals']:
            if p['feature'] not in REQUIRED_FEATURES or p['operator'] not in ('gt','lt') or not finite(p['threshold']):raise ValueError('invalid_feature_proposal')
        result={'status':'complete','date':day,'weights':weights,'review':value,'reviewed_at':datetime.now(TPE).isoformat(),'proposals_applied':False}
        save(dest,result);return result
    except Exception as e:
        result={'status':'failed','error_type':type(e).__name__,'weights':{}};save(dest,result);return result

def train():
    import numpy as np
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.linear_model import LogisticRegression
    sources=sorted(PILOT.glob('*/samples.jsonl'),key=lambda p:p.stat().st_mtime)
    if not sources:raise RuntimeError('historical_samples_missing')
    source=sources[-1];historical=[]
    with source.open() as stream:
        for line in stream:
            r=json.loads(line)
            if all(finite(r.get('features',{}).get(k)) for k in REQUIRED_FEATURES) and finite(r.get('net_markout_pct')):
                historical.append({**r,'weight':1.0})
    forward=[]
    for path in sorted((DATA/'paper-labels').glob('*.json')):
        feedback=read(DATA/'paper-feedback'/path.name,{}) or {}
        weights=feedback.get('weights',{})
        for r in read(path,{}).get('rows',[]):
            if r.get('label_policy')==LABEL_POLICY:forward.append({**r,'weight':float(weights.get(r['id'],1.0))})
    # Forward observations supersede archived grid rows on the same symbol/date.
    covered={(r['date'],r['symbol']) for r in forward}
    rows=[r for r in historical if (r['date'],r['symbol']) not in covered]+forward
    dates=sorted({r['date'] for r in rows});n=max(5,math.ceil(len(dates)*.2))
    if len(dates)<26:raise RuntimeError('insufficient_dates')
    fit=[r for r in rows if r['date']<dates[-n-1]];test=[r for r in rows if r['date']>=dates[-n]]
    def fit_model(data,use_weights):
        x=np.array([[r['features'][k] for k in REQUIRED_FEATURES] for r in data]);y=np.array([r['net_markout_pct']>0 for r in data],dtype=int)
        if len(data)<200 or min(sum(y),len(y)-sum(y))<20:raise RuntimeError('insufficient_classes')
        m=make_pipeline(StandardScaler(),LogisticRegression(C=1,max_iter=2000,random_state=7))
        m.fit(x,y,logisticregression__sample_weight=[r['weight'] if use_weights else 1.0 for r in data]);return m
    # Evaluation never uses LLM feedback obtained after the evaluation boundary.
    evaluation=fit_model(fit,False);pred=evaluation.predict_proba([[r['features'][k] for k in REQUIRED_FEATURES] for r in test])[:,1]
    final=fit_model(rows,True);scaler,clf=final.steps[0][1],final.steps[1][1]
    signature=hashlib.sha256(json.dumps([(r.get('id',str(r.get('observed_ns'))),r['date'],r['symbol'],r['weight'],r['net_markout_pct']) for r in rows]).encode()).hexdigest()[:12]
    artifact={'version':'paper-adaptive-'+dates[-1]+'-'+signature,'deployment_allowed':False,'paper_only':True,'label_policy':LABEL_POLICY,
        'features':list(REQUIRED_FEATURES),'mean':scaler.mean_.tolist(),'scale':scaler.scale_.tolist(),'coef':clf.coef_[0].tolist(),'intercept':float(clf.intercept_[0]),
        'config':{'max_gain_pct':5,'max_spread_pct':1},'threshold':.04,'trained_through':dates[-1],'train_samples':len(rows),'forward_samples':len(forward),
        'feedback_weighted_samples':sum(r['weight']<1 for r in forward),'historical_source':str(source),
        'validation':{'test_samples':len(test),'test_from':dates[-n],'gap_date':dates[-n-1],
            'brier':float(np.mean((pred-np.array([r['net_markout_pct']>0 for r in test]))**2)),
            'note':'Historical diagnostic, not independent prospective validation; threshold retained from current experiment.'}}
    version=DATA/'paper-models'/(artifact['version']+'.json');save(version,artifact)
    save(DATA/'paper-active.json',artifact)
    status={k:artifact[k] for k in ('version','trained_through','train_samples','forward_samples','feedback_weighted_samples','validation')}
    # The current live engine does not consume this eleven-feature artifact.
    status.update(status='historical_diagnostic_only',path=str(DATA/'paper-active.json'),updated_at=datetime.now(TPE).isoformat())
    save(DATA/'paper-training-status.json',status);return status

def main():
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent/'.env');load_dotenv('/home/ubuntu/easystock-dual-review.env')
    parser=argparse.ArgumentParser();parser.add_argument('phase',choices=['collect','review','train']);parser.add_argument('--date',default=datetime.now(TPE).date().isoformat());parser.add_argument('--network',action='store_true');args=parser.parse_args()
    day=datetime.strptime(args.date,'%Y-%m-%d').date().isoformat()
    import fcntl
    DATA.mkdir(parents=True,exist_ok=True)
    with (DATA/'paper-cycle.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if args.phase=='train':result=train()
        elif args.phase=='collect':
            if args.network and not (datetime.now(TPE).hour>=13):raise RuntimeError('collection_only_after_close')
            result=collect(day,args.network)
        else:result=review(read(DATA/'paper-labels'/(day+'.json'),{'date':day,'rows':[]}))
        print(json.dumps({k:v for k,v in result.items() if k not in ('rows','review','weights')},ensure_ascii=False))

if __name__=='__main__':main()
