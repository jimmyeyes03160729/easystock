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


def simulate(sample, pack, costs):
    """Conservative, fixed-stop benchmark. Not the live trailing/technical exit policy."""
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
    stop=entry*(1-sample['policy']['stop_loss_pct']); take=entry*(1+sample['policy']['take_profit_pct'])
    if not 0<stop<entry<take:return None,'invalid_exit_policy'
    cursor=start; reason=None; exit_price=None
    while cursor<=end:
        b=bars.get(cursor)
        if not b or b['volume']<=0:return None,'missing_or_zero_volume_bar'
        if b['low']<=limit_down:return None,'possible_locked_exit'
        if cursor==end:exit_price=b['open'];reason='12:55';break
        if b['open']<=stop:exit_price=b['open'];reason='gap_stop';break
        if b['low']<=stop:exit_price=stop;reason='stop_or_ambiguous_bar';break
        if b['open']>=take:exit_price=take;reason='take';break
        if b['high']>=take:exit_price=take;reason='take';break
        cursor+=timedelta(minutes=1)
    if exit_price is None:return None,'unresolved'
    exit_price*=1-costs['slippage_bps']/10000
    qty=costs['shares']
    fees=max(costs['minimum_fee_twd'],entry*qty*costs['fee_rate'])+max(costs['minimum_fee_twd'],exit_price*qty*costs['fee_rate'])+exit_price*qty*costs['sell_tax_rate']
    net=((exit_price-entry)*qty-fees)/(entry*qty)*100
    version=hashlib.sha256(json.dumps({'costs':costs,'policy':sample['policy'],'features':FEATURES,'execution':'next-minute-fixed-stop-v2'},sort_keys=True).encode()).hexdigest()[:16]
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
            'Benchmark exits use fixed stop/take and 12:55; not live trailing or technical exits',
            'Minute-bar simulated fills are assumptions, not actual execution',
            'Same-bar stop/take uses stop first; missing or price-limit exits excluded and reported',
            'Signal averages are not portfolio profits; no daily improvement guarantee']}
    save(data/'labels'/(day+'.json'),labeled)
    if persist_report:save(data/'reports'/(day+'.json'),result)
    return result


def train_candidate(data):
    try:
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
        from sklearn.linear_model import LogisticRegression
    except ImportError:return {'status':'blocked','reason':'research scikit-learn environment not installed'}
    rows=[]
    for p in sorted((Path(data)/'labels').glob('*.json')):rows.extend(json.loads(p.read_text()))
    if not rows:return {'status':'blocked','reason':'no labeled snapshots'}
    # Different exit/risk/fee profiles must never be pooled silently.
    latest=max(rows,key=lambda r:r['at'])['profile'];rows=[r for r in rows if r['profile']==latest]
    dates=sorted({r['date'] for r in rows})
    if len(dates)<101 or len(rows)<1000:return {'status':'blocked','reason':'need 101 dates and 1000 samples in one profile','dates':len(dates),'samples':len(rows)}
    folds=[]; last_model=None
    for offset in (60,40,20):
        test_dates=set(dates[-offset:][:20]); first=dates.index(min(test_dates));fit_dates=set(dates[:first-1])
        fit=[r for r in rows if r['date'] in fit_dates];test=[r for r in rows if r['date'] in test_dates]
        y=[int(r['net_return_pct']>0) for r in fit]
        if not y or min(sum(y),len(y)-sum(y))<30:return {'status':'blocked','reason':'insufficient class balance'}
        model=make_pipeline(StandardScaler(),LogisticRegression(C=1,max_iter=2000,random_state=7))
        model.fit([r['features'] for r in fit],y)
        probs=model.predict_proba([r['features'] for r in test])[:,1]
        picks=[r['net_return_pct'] for r,p in zip(test,probs) if p>=.6]
        base=[r['net_return_pct'] for r in test if r['radar_selected']]
        folds.append({'train_through':max(fit_dates),'gap_date':dates[first-1],'test_from':min(test_dates),'test_through':max(test_dates),
            'candidate':metrics(picks),'radar_benchmark':metrics(base),
            'brier':sum((float(p)-int(r['net_return_pct']>0))**2 for r,p in zip(test,probs))/len(test)})
        last_model=model
    scaler,clf=last_model.steps[0][1],last_model.steps[1][1]
    result={'schema_version':SCHEMA_VERSION,'approved':False,'version':'research-'+dates[-1],'status':'candidate_only','deployment_allowed':False,'profile':latest,'folds':folds,'threshold':.6,
        'features':FEATURES,'mean':scaler.mean_.tolist(),'scale':scaler.scale_.tolist(),'coef':clf.coef_[0].tolist(),'intercept':float(clf.intercept_[0]),
        'trained_through':folds[-1]['train_through'],
        'benchmark':'same-exit radar selection; not the actual live portfolio',
        'required_before_deployment':['fixed untouched forward window','probability calibration','portfolio capital/drawdown simulation','live shadow comparison']}
    save(Path(data)/'models'/('candidate-'+dates[-1]+'.json'),result)
    return result
