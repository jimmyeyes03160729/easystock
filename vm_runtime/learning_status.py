#!/usr/bin/env python3
"""Read-only research/system inspection; publish only a small public summary with --publish."""
import argparse
from collections import Counter
from datetime import datetime,timedelta,timezone
import hashlib,json,os
from pathlib import Path
import subprocess
TPE=timezone(timedelta(hours=8));ROOT=Path(__file__).resolve().parent
DATA=Path(os.getenv('LEARNING_DATA_DIR','/home/ubuntu/easystock-learning-data'))
UNITS=('easystock-intraday.service','easystock-learning.service','easystock-learning-train.service')

def read(path,default,errors):
    try:return json.loads(path.read_text())
    except FileNotFoundError:return default
    except (ValueError,OSError):errors.append(path.name);return default

def states():
    result={}
    for unit in UNITS:
        try:
            out=subprocess.run(['systemctl','show',unit,'-p','ActiveState','-p','SubState','-p','ExecMainStatus'],capture_output=True,text=True,timeout=5,check=True).stdout
            fields=dict(line.split('=',1) for line in out.splitlines() if '=' in line)
            result[unit]=fields
        except Exception:result[unit]={'ActiveState':'unknown'}
    return result

def compute(data,now,service_states,engine_hash,known_hashes):
    errors=[];today=now.date().isoformat();reports=[];labels=[];collection_days=set();observed=set();sample_count=0;last_sample=None
    for p in sorted((data/'reports').glob('*.json')):
        row=read(p,{},errors)
        if isinstance(row,dict) and row.get('date'):reports.append(row)
    for p in sorted(data.glob('journal-*.jsonl')):
        has_samples=False
        try:
            with p.open() as f:
                for line in f:
                    try:row=json.loads(line)
                    except ValueError:errors.append(p.name);continue
                    if row.get('kind')!='sample':continue
                    d=row.get('data',{});at=d.get('observed_at','');date=at[:10]
                    if date!=p.stem.removeprefix('journal-'):continue
                    has_samples=True
                    if date==today:
                        sample_count+=1;observed.add(str(d.get('symbol','')))
                        if last_sample is None or at>last_sample:last_sample=at
            if has_samples:collection_days.add(p.stem.removeprefix('journal-'))
        except OSError:errors.append(p.name)
    # Deduplicate by the same identity used by the research builder.
    unique={}
    for p in sorted((data/'labels').glob('*.json')):
        rows=read(p,[],errors)
        if not isinstance(rows,list):errors.append(p.name);continue
        for row in rows:
            if isinstance(row,dict) and row.get('symbol') and row.get('at') and row.get('date')==p.stem and row.get('profile'):
                unique[(row['symbol'],row['at'],row['profile'])]=row
    labels=list(unique.values());recent=max(labels,key=lambda x:x['at']) if labels else {}
    profile=recent.get('profile');same=[x for x in labels if x['profile']==profile]
    today_labels=[x for x in labels if x['date']==today]
    report=next((x for x in reports if x['date']==today),{});c=report.get('collection',{})
    last_report=max(reports,key=lambda x:x['date']) if reports else {}
    phase='idle'
    if any(x.get('SubState')=='auto-restart' or x.get('ActiveState')=='failed' for x in service_states.values()):phase='failed'
    elif any(x.get('ActiveState')=='unknown' for x in service_states.values()):phase='unknown'
    elif service_states.get(UNITS[2],{}).get('ActiveState') in ('active','activating'):phase='training'
    elif service_states.get(UNITS[1],{}).get('ActiveState') in ('active','activating'):phase='reviewing'
    elif service_states.get(UNITS[0],{}).get('ActiveState') in ('active','activating'):
        try:age=(now-datetime.fromisoformat(last_sample)).total_seconds()
        except (TypeError,ValueError):age=999999
        phase='collecting' if 0<=age<=420 else 'unknown'
    training=read(data/'training-status.json',{},errors)
    return {'schema_version':1,'updated_at':now.isoformat(),'phase':phase,'data_errors':sorted(set(errors)),
      'today':{'date':today,'sample_count':sample_count,'observed_stocks':len(observed-{''}),
               'learned_stocks':len({x['symbol'] for x in today_labels}),'labeled_count':len(today_labels),
               'requested':c.get('requested'),'downloaded':c.get('downloaded'),
               'report_status':report.get('status'),'ai_status':report.get('ai',{}).get('status')},
      'totals':{'collection_days':len(collection_days),'learning_days':len({x['date'] for x in labels}),
                'training_days':len({x['date'] for x in same}),'training_samples':len(same)},
      'training':{k:training.get(k) for k in ('status','reason','dates','samples','deployment_allowed','trained_through')},
      'model_application':{'status':'not_applied' if engine_hash in known_hashes else 'unknown','basis':'reviewed_engine_hash'},
      'last_report':{'date':last_report.get('date'),'status':last_report.get('status')}}

def main():
    p=argparse.ArgumentParser();p.add_argument('--publish',action='store_true');args=p.parse_args()
    known=read(ROOT/'learning_status_engine_hashes.json',[],[])
    engine_hash=hashlib.sha256((ROOT/'intraday_live.py').read_bytes()).hexdigest()
    result=compute(DATA,datetime.now(TPE),states(),engine_hash,known)
    from firebase_store import FirebaseStore
    store=FirebaseStore()
    o=store.root.child('intraday_picks').get() or {}
    result['overnight']={k:o.get(k) for k in ('scan_date','generated_at','session','scanned_symbols','candidate_symbols','market_level','daily_source_date')}
    candidates=o.get('overnight_candidates',o.get('overnight',[]))
    result['overnight'].update(candidate_count=len(candidates) if isinstance(candidates,list) else None,enabled=o.get('legacy_overnight_enabled'))
    if args.publish:store.root.child('daytrade_learning_status').set(result)
    else:print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
