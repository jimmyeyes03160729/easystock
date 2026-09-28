"""Fail-open champion/challenger bookkeeping for paper models; never sends orders."""
import json, math, os, shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path
from .core import metrics
from .research import logistic_probabilities, save, train_candidate, promote_candidate

TPE=timezone(timedelta(hours=8))

def read(path,default=None):
    try:return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError,ValueError,TypeError):return {} if default is None else default

def jsonl(path):
    rows=[]
    try:
        with Path(path).open(encoding='utf-8') as source:
            for line in source:
                try:rows.append(json.loads(line))
                except ValueError:pass
    except OSError:pass
    return rows

def append_once(path,key,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    if any(row.get('date')==key for row in jsonl(path)):return False
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
    with os.fdopen(fd,'a',encoding='utf-8') as out:out.write(json.dumps(value,ensure_ascii=False,allow_nan=False)+'\n')
    return True

def profile_rows(data,day):
    rows=read(Path(data)/'labels'/(day+'.json'),[])
    if not isinstance(rows,list) or not rows:return None,[]
    latest=max(rows,key=lambda r:r.get('at','')).get('profile')
    return latest,[r for r in rows if r.get('profile')==latest and r.get('date')==day]

def evaluate(model,rows):
    probabilities=logistic_probabilities(model,rows);threshold=float(model['threshold'])
    selected=[r['net_return_pct'] for r,p in zip(rows,probabilities) if p>=threshold]
    result=metrics(selected);result.update(n_rows=len(rows),n_picks=result.pop('count'),
        brier=sum((p-int(r['net_return_pct']>0))**2 for r,p in zip(rows,probabilities))/len(rows) if rows else None)
    return result

def radar(rows):
    picked=[r['net_return_pct'] for r in rows if r.get('radar_selected')]
    result=metrics(picked);result.update(n_rows=len(rows),n_picks=result.pop('count'),brier=None);return result

def cumulative(logs):
    names=('frozen_baseline','rolling_model','radar_baseline','formal_candidate');out={}
    for name in names:
        parts=[row.get('lines',{}).get(name) for row in logs if row.get('lines',{}).get(name)]
        picks=sum(x['n_picks'] for x in parts);rows=sum(x['n_rows'] for x in parts)
        out[name]={'n_rows':rows,'n_picks':picks,
            'mean_net_return_pct':sum((x['mean_net_return_pct'] or 0)*x['n_picks'] for x in parts)/picks if picks else None,
            'win_rate':sum((x['win_rate'] or 0)*x['n_picks'] for x in parts)/picks if picks else None,
            'brier':sum((x['brier'] or 0)*x['n_rows'] for x in parts if x['brier'] is not None)/sum(x['n_rows'] for x in parts if x['brier'] is not None) if any(x['brier'] is not None for x in parts) else None}
    return out

def shadow(data,day,profile,rows,formal=None):
    models=Path(data)/'models';lines={'radar_baseline':radar(rows)};warnings=[]
    for name,path in (('frozen_baseline',models/'frozen-baseline.json'),('rolling_model',models/'latest-approved.json'),('formal_candidate',formal)):
        if not path or not Path(path).exists():continue
        model=read(path)
        if model.get('profile')!=profile:
            warnings.append({'type':'profile_mismatch','line':name});continue
        try:lines[name]=evaluate(model,rows)
        except Exception as exc:warnings.append({'type':'evaluation_error','line':name,'error':type(exc).__name__})
    entry={'date':day,'profile':profile,'evaluated_at':datetime.now(TPE).isoformat(),'lines':lines,'warnings':warnings}
    existing=jsonl(models/'shadow-log.jsonl')
    if append_once(models/'shadow-log.jsonl',day,entry):existing.append(entry)
    save(models/'shadow-summary.json',{'through':day,'lines':cumulative(existing),'warnings':warnings})
    return entry

def archive(models,path,prefix,day):
    path=Path(path)
    if not path.exists():return None
    target=models/'archive'/f'{prefix}-{day}.json';target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    if not target.exists():
        temp=target.with_suffix('.tmp');shutil.copy2(path,temp);temp.chmod(0o600);os.replace(temp,target)
    return target.relative_to(models).as_posix()

def freeze_once(models,promoted):
    path=models/'frozen-baseline.json'
    payload={**promoted,'status':'frozen_baseline','deployment_allowed':False,'frozen_at':datetime.now(TPE).isoformat()}
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w',encoding='utf-8') as out:out.write(json.dumps(payload,ensure_ascii=False,allow_nan=False))

def all_profile_dates(data,profile,through=None):
    result=[]
    for path in sorted((Path(data)/'labels').glob('*.json')):
        rows=read(path,[])
        if (through is None or path.stem<=through) and any(r.get('profile')==profile for r in rows):result.append(path.stem)
    return result

def profile_sample_count(data,profile,dates):
    return sum(len([r for r in read(Path(data)/'labels'/(d+'.json'),[]) if r.get('profile')==profile]) for d in dates)

def validation_summary(candidate):
    return [{'fold':index,'test_samples':f.get('test_samples'),'selected_count':(f.get('candidate') or {}).get('count'),
        'expected_value_pct':(f.get('candidate') or {}).get('mean_net_return_pct'),'brier':f.get('brier'),
        'test_from':f.get('test_from'),'test_through':f.get('test_through'),'candidate':f.get('candidate'),
        'radar_benchmark':f.get('radar_benchmark')} for index,f in enumerate(candidate.get('folds',[]),1)]

def promotion_gate(candidate):
    """Only a full, out-of-sample result may replace the rolling paper model."""
    folds=candidate.get('folds') or []
    rows=sum(int(f.get('test_samples') or 0) for f in folds)
    picks=sum(int((f.get('candidate') or {}).get('count') or 0) for f in folds)
    radar_picks=sum(int((f.get('radar_benchmark') or {}).get('count') or 0) for f in folds)
    def weighted(key, count_key):
        parts=[(float((f.get(key) or {})['mean_net_return_pct']),int((f.get(count_key) or {}).get('count') or 0)) for f in folds if (f.get(key) or {}).get('mean_net_return_pct') is not None]
        total=sum(n for _,n in parts);return sum(v*n for v,n in parts)/total if total else None
    mean=weighted('candidate','candidate');radar_mean=weighted('radar_benchmark','radar_benchmark')
    brier_parts=[(float(f['brier']),int(f.get('test_samples') or 0)) for f in folds if f.get('brier') is not None]
    brier_n=sum(n for _,n in brier_parts);brier=sum(v*n for v,n in brier_parts)/brier_n if brier_n else None
    reference_parts=[(float(f['constant_brier']),int(f.get('test_samples') or 0)) for f in folds if f.get('constant_brier') is not None]
    reference_n=sum(n for _,n in reference_parts);reference=sum(v*n for v,n in reference_parts)/reference_n if reference_n else None
    checks={'full_walk_forward':candidate.get('validation_mode')=='full_walk_forward','three_folds':len(folds)>=3,
        'minimum_test_rows':rows>=100,'minimum_picks':picks>=30,'positive_mean':mean is not None and mean>0,
        'radar_comparable':radar_picks>0,'beats_radar':radar_mean is not None and mean is not None and mean>radar_mean,
        'beats_constant_brier':brier is not None and reference is not None and brier<reference}
    return {'passed':all(checks.values()),'checks':checks,'n_rows':rows,'n_picks':picks,'radar_picks':radar_picks,
        'mean_net_return_pct':mean,'radar_mean_net_return_pct':radar_mean,'brier':brier,'constant_brier':reference}

def formal_cycle(data,day,profile,controls,shadow_entry):
    models=Path(data)/'models';state_path=models/'formal-state.json';state=read(state_path,{})
    if state.get('status')=='observing':
        if state.get('profile')!=profile:return {'status':'profile_mismatch'}
        dates=state.get('observed_dates',[])
        if shadow_entry.get('lines',{}).get('formal_candidate') and day not in dates:dates.append(day)
        state['observed_dates']=dates
        if len(dates)>=int(controls['forward_observe_days']):
            logs=[r for r in jsonl(models/'shadow-log.jsonl') if r.get('date') in dates]
            aggregate=cumulative(logs);formal=aggregate['formal_candidate'];radar_line=aggregate['radar_baseline']
            model=read(models/state['file']);reference=float(model.get('training_win_rate',.5));reference_brier=reference*(1-reference)
            checks={'minimum_picks':formal['n_picks']>=30,'positive_mean':(formal['mean_net_return_pct'] or -math.inf)>0,
                'beats_radar':(formal['mean_net_return_pct'] or -math.inf)>(radar_line['mean_net_return_pct'] or -math.inf),
                'beats_constant_brier':formal['brier'] is not None and formal['brier']<reference_brier}
            passed=all(checks.values());report={'date':day,'status':'passed' if passed else 'failed','checks':checks,'formal':formal,'radar':radar_line,'reference_brier':reference_brier}
            save(models/f'formal-report-{day}.json',report);state.update(status=report['status'],report=f'formal-report-{day}.json')
            if passed:
                baseline=models/'frozen-baseline.json';archive(models,baseline,'frozen-baseline',day)
                promoted={**model,'status':'frozen_baseline','deployment_allowed':False,'frozen_at':datetime.now(TPE).isoformat()};save(baseline,promoted)
                if controls.get('formal_candidate_for_live'):
                    archive(models,models/'latest-approved.json','approved',day);save(models/'latest-approved.json',{**model,'approved':True,'deployment_allowed':True,'status':'formal_approved_for_paper'})
        save(state_path,state);return state
    if state.get('status') in ('passed','failed') and state.get('profile')==profile:return state
    dates=all_profile_dates(data,profile,day);count=profile_sample_count(data,profile,dates)
    if len(dates)<101 or count<1000:return {'status':'not_eligible','dates':len(dates),'samples':count}
    candidate=train_candidate(data,controls,allow_paper_bootstrap=False)
    if candidate.get('status')!='candidate_only':return candidate
    candidate['training_win_rate']=sum(r['net_return_pct']>0 for d in dates for r in read(Path(data)/'labels'/(d+'.json'),[]) if r.get('profile')==profile)/count
    destination=models/f'formal-candidate-{day}.json';save(destination,candidate)
    state={'status':'observing','profile':profile,'file':destination.name,'created_at':day,'observed_dates':[]};save(state_path,state);return state

def run_close(data,day,controls):
    """Shadow first, then optional rolling promotion. Auxiliary failures are recorded and fail open."""
    controls={'model_retrain_every_days':5,'forward_observe_days':20,'formal_candidate_for_live':False,**(controls or {})}
    models=Path(data)/'models';models.mkdir(parents=True,exist_ok=True,mode=0o700)
    close_state=models/'close-results'/(day+'.json')
    previous=read(close_state,{})
    if previous.get('status')=='complete':
        try:append_once(models/'promotion-log.jsonl',day,previous['entry'])
        except Exception:pass
        return {'status':'already_processed','date':day,'entry':previous['entry']}
    if any(r.get('date')==day for r in jsonl(models/'promotion-log.jsonl')):
        return {'status':'already_processed','date':day}
    profile,rows=profile_rows(data,day)
    if not rows:return {'status':'blocked','date':day,'reason':'no_same_day_labels'}
    state=read(models/'formal-state.json',{});formal=models/state['file'] if state.get('status')=='observing' and state.get('profile')==profile else None
    errors=[]
    try:shadow_entry=shadow(data,day,profile,rows,formal)
    except Exception as exc:errors.append({'stage':'shadow','error':type(exc).__name__});shadow_entry={'lines':{}}
    latest=read(models/'latest-approved.json',{});dates=all_profile_dates(data,profile,day)
    due=[d for d in dates if d>str(latest.get('trained_through') or '')]
    action='skipped_not_due';result=latest;backup=None
    recovered=previous.get('status')=='processing' and latest.get('close_date')==day
    save(close_state,{'status':'processing','date':day,'profile':profile})
    if recovered:
        action='promoted';result=latest
    elif not latest or len(due)>=int(controls['model_retrain_every_days']):
        candidate=train_candidate(data,controls,allow_paper_bootstrap=True)
        if candidate.get('status')=='candidate_only':
            gate=promotion_gate(candidate)
            if not gate['passed']:
                action='blocked';result={**candidate,'status':'blocked','reason':'promotion_gate_not_met','promotion_gate':gate}
            elif latest:
                try:backup=archive(models,models/'latest-approved.json','approved',str(latest.get('trained_through') or day))
                except Exception as exc:
                    errors.append({'stage':'archive','error':type(exc).__name__});action='blocked';result={**candidate,'status':'backup_failed'}
            if action!='blocked':
                candidate['close_date']=day
                result=promote_candidate(data,candidate,write_log=False,archive_previous=False);action='promoted'
            if action=='promoted' and not (models/'frozen-baseline.json').exists():
                try:freeze_once(models,result)
                except FileExistsError:pass
                except Exception as exc:errors.append({'stage':'frozen_baseline','error':type(exc).__name__})
        else:action='blocked';result=candidate
    entry={'date':day,'action':action,'trained_through':result.get('trained_through'),'profile':profile,
        'sample_count':profile_sample_count(data,profile,dates),'validation':validation_summary(result),'backup_file':backup,
        'reason':result.get('reason'),'promotion_gate':result.get('promotion_gate'),'warnings':shadow_entry.get('warnings',[]),'errors':errors}
    try:entry['formal']=formal_cycle(data,day,profile,controls,shadow_entry)
    except Exception as exc:errors.append({'stage':'formal','error':type(exc).__name__})
    save(close_state,{'status':'complete','date':day,'entry':entry})
    try:append_once(models/'promotion-log.jsonl',day,entry)
    except Exception as exc:errors.append({'stage':'promotion_log','error':type(exc).__name__})
    return {**entry,'status':result.get('status',action)}
