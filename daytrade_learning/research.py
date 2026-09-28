"""Date-isolated post-close research. Historical outcomes never become input features."""
import hashlib
import json
import math
import os
from pathlib import Path
from datetime import datetime, timedelta, time, timezone
from collections import Counter
from .core import gemini_review, metrics

TPE=timezone(timedelta(hours=8))
from .features import FEATURES, SCHEMA_VERSION, vector


def dt(x):
    if isinstance(x,datetime):
        return x.replace(tzinfo=TPE) if x.tzinfo is None else x.astimezone(TPE)
    if isinstance(x,(int,float)) or str(x).isdigit():
        # Shioaji historical ns encode LOCAL clock (same convention as VM converter).
        n=int(x)
        divisor=10**9 if abs(n)>=10**17 else 10**6 if abs(n)>=10**14 else 1000 if abs(n)>=10**11 else 1
        return datetime.fromtimestamp(n/divisor,timezone.utc).replace(tzinfo=TPE)
    return dt(datetime.fromisoformat(str(x).replace('Z','+00:00')))


def finite(x):
    if isinstance(x,bool) or x is None:
        raise ValueError('missing_number')
    v=float(x)
    if not math.isfinite(v):raise ValueError('nonfinite')
    return v


def save(path, value):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,allow_nan=False),encoding='utf-8')
    temp.chmod(0o600); os.replace(temp,path)


def promote_candidate(data, candidate, *, promoted_at=None, write_log=True, archive_previous=True):
    """Atomically make a successfully trained candidate the next-session model."""
    if not isinstance(candidate, dict) or candidate.get('status') != 'candidate_only':
        return candidate
    model_dir=Path(data)/'models'; latest=model_dir/'latest-approved.json'
    when=datetime.fromisoformat(promoted_at) if promoted_at else datetime.now(TPE)
    if when.tzinfo is None:when=when.replace(tzinfo=TPE)
    previous_version=None; backup_name=None
    if latest.exists() and archive_previous:
        raw=latest.read_bytes()
        try:previous_version=json.loads(raw).get('version')
        except (ValueError,TypeError,AttributeError):previous_version=None
        archive=model_dir/'archive';archive.mkdir(parents=True,exist_ok=True,mode=0o700)
        stamp=when.astimezone(TPE).strftime('%Y-%m-%d_%H%M%S_%f')
        backup=archive/f'latest-approved-{stamp}.json'
        temp=backup.with_suffix('.json.tmp');temp.write_bytes(raw);temp.chmod(0o600);os.replace(temp,backup)
        backup_name=backup.relative_to(model_dir).as_posix()
    promoted = dict(candidate)
    promoted.update(
        approved=True,
        deployment_allowed=True,
        status='auto_approved_for_paper',
        promotion_policy='daily_paper_auto_promote',
        promoted_at=when.isoformat(),
    )
    save(latest, promoted)
    validation=[]
    for index,fold in enumerate(promoted.get('folds') or [],1):
        candidate_metrics=fold.get('candidate') or {}
        validation.append({
            'fold':index,
            'test_samples':fold.get('test_samples'),
            'selected_count':candidate_metrics.get('count'),
            'expected_value_pct':candidate_metrics.get('mean_net_return_pct'),
            'brier':fold.get('brier'),
            'test_from':fold.get('test_from'),'test_through':fold.get('test_through'),
        })
    log_entry={
        'promoted_at':promoted['promoted_at'],'promoted_model':promoted.get('version'),
        'previous_model':previous_version,'backup_file':backup_name,
        'trained_through':promoted.get('trained_through'),'validation_mode':promoted.get('validation_mode'),
        'validation':validation,
    }
    if write_log:
        log_path=model_dir/'promotion-log.jsonl';log_path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        fd=os.open(log_path,os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
        with os.fdopen(fd,'a',encoding='utf-8') as out:
            out.write(json.dumps(log_entry,ensure_ascii=False,allow_nan=False)+'\n')
    return promoted


def fit_logistic(rows, iterations=800, learning_rate=.12):
    """Small deterministic logistic trainer; keeps the VM dependency-free."""
    xs=[[finite(v) for v in r['features']] for r in rows]
    ys=[int(r['net_return_pct']>0) for r in rows]
    n=len(xs); width=len(FEATURES)
    mean=[sum(x[j] for x in xs)/n for j in range(width)]
    scale=[max((sum((x[j]-mean[j])**2 for x in xs)/n)**.5,1e-9) for j in range(width)]
    standardized=[[(x[j]-mean[j])/scale[j] for j in range(width)] for x in xs]
    prior=min(max(sum(ys)/n,1e-6),1-1e-6)
    intercept=math.log(prior/(1-prior)); coef=[0.0]*width
    for step in range(iterations):
        grad=[0.0]*width; grad_intercept=0.0
        for x,y in zip(standardized,ys):
            z=max(-35.0,min(35.0,intercept+sum(c*v for c,v in zip(coef,x))))
            error=1/(1+math.exp(-z))-y
            grad_intercept+=error
            for j,v in enumerate(x):grad[j]+=error*v
        rate=learning_rate/(1+step/400)
        intercept-=rate*grad_intercept/n
        for j in range(width):coef[j]-=rate*(grad[j]/n+coef[j]/n)
    return {'mean':mean,'scale':scale,'coef':coef,'intercept':intercept}


def logistic_probabilities(model, rows):
    probabilities=[]
    for row in rows:
        values=[finite(v) for v in row['features']]
        z=model['intercept']+sum((x-m)/s*c for x,m,s,c in zip(values,model['mean'],model['scale'],model['coef']))
        z=max(-35.0,min(35.0,z));probabilities.append(1/(1+math.exp(-z)))
    return probabilities


def journal(path):
    rows=[]; corrupt=0
    if Path(path).exists():
        with open(path,encoding='utf-8') as f:
            for line in f:
                try:rows.append(json.loads(line))
                except (ValueError,TypeError):corrupt+=1
    return rows,corrupt


def normalize_bars(payload, day):
    def field(k):
        v=payload.get(k) if isinstance(payload,dict) else getattr(payload,k,None)
        return list(v) if v is not None else []
    cols=[field(k) for k in ('ts','Open','High','Low','Close','Volume')]
    if len({len(c) for c in cols})!=1:raise ValueError('bar_columns_mismatch')
    result={}
    for values in zip(*cols):
        end=dt(values[0]); start=end-timedelta(minutes=1)
        if start.time()<time(9) or start.time()>time(13,29):continue
        o,h,l,c,v=map(finite,values[1:])
        if not 0<l<=min(o,c)<=max(o,c)<=h or v<0:raise ValueError('bad_ohlcv')
        row={'at':start.isoformat(),'open':o,'high':h,'low':l,'close':c,'volume':v}
        if row['at'] in result and result[row['at']]!=row:raise ValueError('conflicting_bar')
        result[row['at']]=row
    rows=sorted(result.values(),key=lambda r:r['at'])
    previous=[r for r in rows if r['at'][:10]<day]
    prev=None
    if previous:
        last=previous[-1]
        # A partial previous trading day is not treated as yesterday's close.
        if dt(last['at']).time()==time(13,29):
            prev={'price':last['close'],'date':last['at'][:10]}
    return {'date':day,'previous_close':prev,'bars':[r for r in rows if r['at'][:10]==day]}


# Only our own validation codes may enter a report; never serialize SDK error messages.
COLLECTION_REASONS={'contract_missing','no_today_bars','bar_columns_mismatch',
                    'missing_number','nonfinite','bad_ohlcv','conflicting_bar'}


def collection_error(exc,stage,attempts):
    name=type(exc).__name__
    retryable=isinstance(exc,(TimeoutError,ConnectionError)) or name in {
        'Timeout','ReadTimeout','ConnectTimeout','TimeoutException','ConnectionError'}
    reason=str(exc) if isinstance(exc,ValueError) and str(exc) in COLLECTION_REASONS else (
        'transient_connection_error' if retryable else 'validation_error' if isinstance(exc,ValueError)
        else 'operation_failed')
    return {'error_type':name,'reason':reason,'stage':stage,'attempts':attempts,'retryable':retryable}


def collect(api, data, day, observations, max_symbols=500):
    import time as clock
    symbols=sorted({str(r['data'].get('symbol','')) for r in observations if r.get('kind') in ('sample','entry','exit')})
    symbols=[s for s in symbols if len(s)==4 and s.isdigit()]
    scanned=set(symbols)
    import shioaji as sj
    scanner_errors=[];scanner_details=[]
    for name in ('ChangePercentRank','DayRangeRank','AmountRank'):
        for attempt in (1,2):
            try:
                rows=api.scanners(scanner_type=getattr(sj.ScannerType,name),date=day,count=200,ascending=True,timeout=30000)
                for r in rows:
                    code=str(getattr(r,'code',''))
                    if str(getattr(r,'date',''))==day and len(code)==4 and code.isdigit():
                        stocks=getattr(getattr(api,'Contracts',None),'Stocks',None)
                        if stocks:
                            in_contracts=False
                            for ex in ('TSE','OTC'):
                                try:
                                    if code in getattr(stocks,ex):
                                        in_contracts=True;break
                                except Exception:pass
                            if not in_contracts:continue
                        scanned.add(code)
                break
            except Exception as exc:
                detail=collection_error(exc,'scanner',attempt)
                if attempt<2 and detail['retryable']:clock.sleep(1);continue
                scanner_errors.append(detail['error_type']);scanner_details.append(dict(detail,scanner=name));break
    wanted=(symbols+sorted(scanned-set(symbols)))[:max_symbols]
    failed={};details={};complete=[];cached=0
    start=(datetime.fromisoformat(day).date()-timedelta(days=15)).isoformat()
    cache=Path(data)/'bars'/day
    for symbol in wanted:
        target=cache/(symbol+'.json')
        if target.exists():
            try:
                existing=json.loads(target.read_text())
                if existing.get('date')==day and existing.get('bars') and existing['bars'][-1]['at'][11:16]=='13:29':
                    complete.append(symbol);cached+=1;continue
            except (ValueError,TypeError,KeyError,AttributeError):pass
        for attempt in (1,2):
            stage='contract'
            try:
                contract=None
                for exchange in ('TSE','OTC'):
                    try:contract=getattr(api.Contracts.Stocks,exchange)[symbol]
                    except (KeyError,AttributeError,TypeError):continue
                    if contract is not None:break
                if contract is None:raise ValueError('contract_missing')
                stage='kbars'
                raw=api.kbars(contract,start=start,end=day,timeout=15000)
                stage='normalize'
                result=normalize_bars(raw,day)
                if not result['bars']:raise ValueError('no_today_bars')
                result.update(symbol=symbol,downloaded_at=datetime.now(TPE).isoformat())
                if str(getattr(contract,'update_date',''))[:10]==day:
                    for key in ('limit_up','limit_down'):
                        try:result[key]=finite(getattr(contract,key))
                        except Exception:pass
                stage='save'
                save(target,result);complete.append(symbol);break
            except OSError as exc:
                # A disk failure is not a missing stock. Abort instead of hiding it as partial data.
                if stage=='save':raise
                detail=collection_error(exc,stage,attempt)
                if attempt<2 and detail['retryable']:clock.sleep(1);continue
                failed[symbol]=detail['error_type'];details[symbol]=detail;break
            except Exception as exc:
                detail=collection_error(exc,stage,attempt)
                if attempt<2 and detail['retryable']:clock.sleep(1);continue
                failed[symbol]=detail['error_type'];details[symbol]=detail;break
    return {'requested':len(wanted),'downloaded':len(complete),'failed':failed,'scanner_errors':scanner_errors,
            'failure_details':details,'scanner_error_details':scanner_details,'cached':cached,
            'status':'partial' if failed or scanner_errors else 'complete','max_attempts_per_operation':2,
            'omitted_by_cap':max(0,len(scanned)-len(wanted)),'scope':'observed pool plus 3 post-close top-200 rankings; not full market'}


def price_exit_policy(policy):
    policy=policy or {};mode=str(policy.get('exit_mode','hybrid'))
    if mode not in ('fixed','trailing','hybrid'):raise ValueError('invalid_exit_mode')
    return {'stop_loss_pct':finite(policy['stop_loss_pct']),'take_profit_pct':finite(policy['take_profit_pct']),'exit_mode':mode,
        'trailing_activate_pct':finite(policy.get('trailing_activate_pct',.006)),'trailing_pullback_pct':finite(policy.get('trailing_pullback_pct',.004)),
        'breakeven_activate_pct':finite(policy.get('breakeven_activate_pct',.006)),'breakeven_floor_pct':finite(policy.get('breakeven_floor_pct',.0035))}

def simulate(sample, pack, costs):
    """Conservative minute-bar reconstruction of the live price exit policy."""
    at=dt(sample['observed_at']); day=at.date().isoformat()
    if not time(9,30)<=at.time()<time(12,30):return None,'outside_entry_window'
    quote=dt(sample['quote_at'])
    if quote.date()!=at.date() or not 0<=(at-quote).total_seconds()<=30:return None,'stale_quote'
    prev=pack.get('previous_close')
    if not prev or not 0<(at.date()-datetime.fromisoformat(prev['date']).date()).days<=15:return None,'missing_previous_close'
    if pack.get('date')!=day:return None,'wrong_bar_date'
    price=finite(sample['price']); previous=finite(prev['price'])
    if min(price,previous)<=0:return None,'invalid_price'
    m=sample['metrics']
    try:
        x=vector(dict(gain_pct=(price/previous-1)*100, return_5m_pct=sample['return_5m_pct'], surge_60s=m['surge_60s'], buy_ratio_60s=m['buy_ratio_60s'], amount_60s=m['amount_60s']))
    except (KeyError,ValueError,TypeError):return None,'missing_features'
    if finite(m.get('history_seconds',0))<300 or finite(m.get('classified_ratio_60s',0))<.5:return None,'insufficient_tick_history'
    # Fixed constraints saved BEFORE observing outcomes. Research follows latest user limits once configured.
    limits=sample['policy'].get('entry_filters') or costs['filters']
    if price<limits['min_price'] or price>limits['max_price'] or x[0]>limits['max_gain_pct']+1e-9:return None,'user_filter'
    limit_up=pack.get('limit_up'); limit_down=pack.get('limit_down')
    if not limit_up or not limit_down:return None,'missing_price_limits'
    # Wait at least 2 seconds, then enter at next FULL minute's open.
    start=(at+timedelta(seconds=2)).replace(second=0,microsecond=0)+timedelta(minutes=1)
    end=at.replace(hour=12,minute=55,second=0,microsecond=0)
    bars={dt(b['at']):b for b in pack['bars']}
    first=bars.get(start)
    if not first or first['volume']<=0:return None,'no_entry_bar'
    entry=first['open']*(1+costs['slippage_bps']/10000)
    if entry>=limit_up or entry<=limit_down:return None,'entry_at_limit'
    # Recheck limits at simulated fill too.
    if not limits['min_price']<=entry<=limits['max_price'] or (entry/previous-1)*100>limits['max_gain_pct']+1e-9:return None,'fill_filter'
    policy=price_exit_policy(sample.get('policy'))
    stop=entry*(1-policy['stop_loss_pct']); take=entry*(1+policy['take_profit_pct'])
    if not 0<stop<entry<take:return None,'invalid_exit_policy'
    cursor=start; reason=None; exit_price=None; highest=entry; trailing_stop=None
    while cursor<=end:
        b=bars.get(cursor)
        if not b or b['volume']<=0:return None,'missing_or_zero_volume_bar'
        if b['low']<=limit_down:return None,'possible_locked_exit'
        if cursor==end:exit_price=b['open'];reason='12:55強制出場';break
        if b['open']<=stop:exit_price=b['open'];reason='gap_stop';break
        if b['low']<=stop:exit_price=stop;reason='stop_or_ambiguous_bar';break
        breakeven=entry*(1+policy['breakeven_floor_pct'])
        if highest>=entry*(1+policy['breakeven_activate_pct']) and b['low']<=breakeven:exit_price=breakeven;reason='動態保本出場';break
        if policy['exit_mode'] in ('fixed','hybrid') and b['high']>=take:exit_price=take;reason='固定停利';break
        if policy['exit_mode'] in ('trailing','hybrid') and trailing_stop is not None and b['low']<=trailing_stop:exit_price=trailing_stop;reason='移動停利';break
        highest=max(highest,b['high'])
        if policy['exit_mode'] in ('trailing','hybrid') and highest>=entry*(1+policy['trailing_activate_pct']):trailing_stop=max(trailing_stop or 0,highest*(1-policy['trailing_pullback_pct']))
        cursor+=timedelta(minutes=1)
    if exit_price is None:return None,'unresolved'
    exit_price*=1-costs['slippage_bps']/10000
    qty=costs['shares']
    fees=max(costs['minimum_fee_twd'],entry*qty*costs['fee_rate'])+max(costs['minimum_fee_twd'],exit_price*qty*costs['fee_rate'])+exit_price*qty*costs['sell_tax_rate']
    net=((exit_price-entry)*qty-fees)/(entry*qty)*100
    version=hashlib.sha256(json.dumps({'costs':costs,'policy':policy,'features':FEATURES,'execution':'next-minute-live-price-exit-v3'},sort_keys=True).encode()).hexdigest()[:16]
    return {'symbol':sample['symbol'],'date':day,'at':at.isoformat(),'exit_at':cursor.isoformat(),'features':x,
            'net_return_pct':net,'radar_selected':sample['radar_selected'],'entry_price':entry,'exit_price':exit_price,
            'cost_twd':fees,'reason':reason,'profile':version,'kind':'simulation'},None


def discover(packs):
    events=[]
    for symbol,pack in packs.items():
        bars={dt(b['at']):b for b in pack['bars']}
        last=None
        for t,b in sorted(bars.items()):
            previous=[bars.get(t-timedelta(minutes=i)) for i in range(6)]
            if any(x is None for x in previous):continue
            gain=(b['close']/previous[-1]['close']-1)*100
            if gain>=2 and (last is None or (t-last).total_seconds()>=300):
                events.append({'symbol':symbol,'at':t.isoformat(),'gain_5m_pct':round(gain,3)})
                last=t
    return {'threshold_5m_pct':2,'count':len(events),'top':sorted(events,key=lambda x:x['gain_5m_pct'],reverse=True)[:30]}


def build(data, day, costs, persist_report=True):
    data=Path(data);obs,corrupt=journal(data/('journal-'+day+'.jsonl'))
    packs={p.stem:json.loads(p.read_text()) for p in (data/'bars'/day).glob('*.json')}
    missing=Counter(); labeled=[];seen=set(); next_free={}
    samples=sorted((r['data'] for r in obs if r.get('kind')=='sample'),key=lambda s:s['observed_at'])
    # One non-overlapping simulated opportunity per symbol at a time; same algorithm for controls.
    for s in samples:
        key=(s['symbol'],s['observed_at'])
        if key in seen:continue
        seen.add(key)
        if dt(s['observed_at'])<next_free.get(s['symbol'],datetime.min.replace(tzinfo=TPE)):
            missing['overlapping_signal']+=1;continue
        p=packs.get(s['symbol'])
        if not p:missing['no_historical_data']+=1;continue
        try:row,why=simulate(s,p,costs)
        except Exception:row,why=None,'invalid_record'
        if row:
            labeled.append(row);next_free[s['symbol']]=dt(row['exit_at'])+timedelta(minutes=1)
        else:missing[why]+=1
    actual=[r['data'] for r in obs if r.get('kind')=='exit']
    result={'version':'research2','date':day,'status':'ready' if samples else 'no_live_samples',
        'sample_count':len(seen),'bars_symbols':len(packs),'labeled_count':len(labeled),
        'excluded':dict(missing),'corrupt_journal_lines':corrupt,
        'journal_health':[r['data'] for r in obs if r.get('kind')=='health'],
        'surges':discover(packs),'simulation':metrics([r['net_return_pct'] for r in labeled]),
        'existing_signal_tracking':{'closed_count':len(actual),'gross':metrics([finite(r['pnl_pct']) for r in actual if r.get('pnl_pct') is not None])},
        'cost_assumptions':costs,
        'limitations':['Only observed pool has point-in-time samples; post-close additional movers have no fabricated samples',
            'Labels share the live stop, take, breakeven, trailing and 12:55 price exits; minute bars cannot reconstruct tick order or technical exits',
            'Minute-bar simulated fills are assumptions, not actual execution',
            'Same-bar reconstruction is conservative: stop before profit exits; missing or price-limit exits excluded and reported',
            'Signal averages are not portfolio profits; no daily improvement guarantee']}
    save(data/'labels'/(day+'.json'),labeled)
    if persist_report:save(data/'reports'/(day+'.json'),result)
    return result


def train_candidate(data, controls=None, *, allow_paper_bootstrap=False):
    controls = controls or {}
    min_dates = int(controls.get('min_training_dates', 101))
    min_samples = int(controls.get('min_training_samples', 1000))
    min_class = int(controls.get('min_class_samples', 30))
    holdout = int(controls.get('holdout_days', 20))
    threshold = float(controls.get('model_threshold', .6))
    rows=[]
    for p in sorted((Path(data)/'labels').glob('*.json')):rows.extend(json.loads(p.read_text()))
    if not rows:return {'status':'blocked','reason':'no labeled snapshots'}
    # Different exit/risk/fee profiles must never be pooled silently.
    latest=max(rows,key=lambda r:r['at'])['profile'];rows=[r for r in rows if r['profile']==latest]
    dates=sorted({r['date'] for r in rows})
    full_validation = len(dates)>=min_dates and len(rows)>=min_samples
    folds=[]
    if full_validation:
        for offset in (holdout*3,holdout*2,holdout):
            test_dates=set(dates[-offset:][:holdout]); first=dates.index(min(test_dates));fit_dates=set(dates[:first-1])
            fit=[r for r in rows if r['date'] in fit_dates];test=[r for r in rows if r['date'] in test_dates]
            y=[int(r['net_return_pct']>0) for r in fit]
            if not y or min(sum(y),len(y)-sum(y))<min_class:return {'status':'blocked','reason':'insufficient class balance','required_per_class':min_class}
            model=fit_logistic(fit)
            probs=logistic_probabilities(model,test)
            test_y=[int(r['net_return_pct']>0) for r in test]
            picks=[r['net_return_pct'] for r,p in zip(test,probs) if p>=threshold]
            base=[r['net_return_pct'] for r in test if r['radar_selected']]
            folds.append({'train_through':max(fit_dates),'gap_date':dates[first-1],'test_from':min(test_dates),'test_through':max(test_dates),
                'test_samples':len(test),
                'candidate':metrics(picks),'radar_benchmark':metrics(base),
                'brier':sum((float(p)-truth)**2 for truth,p in zip(test_y,probs))/len(test),
                'constant_brier':(sum(test_y)/len(test))*(1-sum(test_y)/len(test))})
    else:
        bootstrap_min=max(200,min_class*2)
        if not allow_paper_bootstrap or len(rows)<bootstrap_min:
            return {'status':'blocked','reason':'training data threshold not met','dates':len(dates),'samples':len(rows),'required_dates':min_dates,'required_samples':min_samples}
        ordered=sorted(rows,key=lambda r:r['at']); cut=max(min_class*2,int(len(ordered)*.8))
        fit,test=ordered[:cut-1],ordered[cut:]
        y=[int(r['net_return_pct']>0) for r in fit]
        test_y=[int(r['net_return_pct']>0) for r in test]
        validation_min=max(5,min_class//3)
        if (not test or min(sum(y),len(y)-sum(y))<min_class
                or min(sum(test_y),len(test_y)-sum(test_y))<validation_min):
            return {'status':'blocked','reason':'insufficient bootstrap class balance','required_per_class':min_class}
        model=fit_logistic(fit)
        probs=logistic_probabilities(model,test)
        picks=[r['net_return_pct'] for r,p in zip(test,probs) if p>=threshold]
        base=[r['net_return_pct'] for r in test if r['radar_selected']]
        folds.append({'train_through':fit[-1]['at'],'gap_date':ordered[cut-1]['at'],'test_from':test[0]['at'],'test_through':test[-1]['at'],
            'test_samples':len(test),
            'candidate':metrics(picks),'radar_benchmark':metrics(base),
            'brier':sum((float(p)-truth)**2 for truth,p in zip(test_y,probs))/len(test),
            'constant_brier':(sum(test_y)/len(test))*(1-sum(test_y)/len(test))})
    # Validation remains strictly time-separated. After it completes, refit the
    # paper-trading artifact on every labeled row available through this close,
    # so tomorrow uses today's newest information rather than a holdout-era fit.
    final_y=[int(r['net_return_pct']>0) for r in rows]
    if min(sum(final_y),len(final_y)-sum(final_y))<min_class:
        return {'status':'blocked','reason':'insufficient class balance','required_per_class':min_class}
    final_model=fit_logistic(rows)
    result={'schema_version':SCHEMA_VERSION,'approved':False,'version':'research-'+dates[-1],'status':'candidate_only','deployment_allowed':False,'profile':latest,'folds':folds,'threshold':threshold,
        'features':FEATURES,'mean':final_model['mean'],'scale':final_model['scale'],'coef':final_model['coef'],'intercept':final_model['intercept'],
        'trained_through':dates[-1], 'validation_mode':'full_walk_forward' if full_validation else 'paper_bootstrap_time_split',
        'benchmark':'same-exit radar selection; not the actual live portfolio',
        'required_before_deployment':['fixed untouched forward window','probability calibration','portfolio capital/drawdown simulation','live shadow comparison']}
    save(Path(data)/'models'/('candidate-'+dates[-1]+'.json'),result)
    return result
