"""Offline A signal learning, including signals skipped by the paper wallet.

Only explicitly selected observed dates are read. No broker, promotion, orders,
reserved historical partitions or online decision imports.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3

TPE = timezone(timedelta(hours=8))
START = '2026-10-14'
SCHEMA = 'a-signal-context-research-v1'
BASE = ('gain_pct','return_5m_pct','surge_60s','buy_ratio_60s','amount_60s')
PATTERN = ('body_ratio','upper_wick_ratio','lower_wick_ratio','close_position',
           'pre_return_5m_pct','pre_range_5m_pct','volume_ratio_5m','vwap_distance_pct')
MARKET = ('taiex_return_5m_pct','otc_return_5m_pct')
FEATURES = BASE + PATTERN + MARKET


def stamp(value):
    at = datetime.fromisoformat(value.replace('Z','+00:00'))
    if at.tzinfo is None:
        raise ValueError('timezone_required')
    return at.astimezone(TPE)


def number(value):
    return (isinstance(value,(int,float)) and not isinstance(value,bool)
            and math.isfinite(value))


def checked_day(day):
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',day):
        raise ValueError('invalid_day')
    datetime.strptime(day,'%Y-%m-%d')
    if not START <= day <= datetime.now(TPE).date().isoformat():
        raise ValueError('outside_observed_learning_window')
    return day


def pattern_features(pack, entry):
    """Retrospective bar reconstruction: completed bars only, never exit paths."""
    at=stamp(entry); rows=[]
    for r in pack.get('bars',[]):
        t=stamp(r['at'])
        if t.date()!=at.date() or t+timedelta(minutes=1)>at:
            continue
        if not all(number(r.get(k)) for k in ('open','high','low','close','volume')):
            continue
        if min(r[k] for k in ('open','high','low','close'))<=0 or r['volume']<0:
            continue
        if r['low']>min(r['open'],r['close']) or r['high']<max(r['open'],r['close']):
            continue
        rows.append((t,r))
    rows.sort(key=lambda r:r[0])
    if len({t for t,_ in rows})!=len(rows):
        return {},'duplicate_bars'
    if len(rows)<10 or (at-(rows[-1][0]+timedelta(minutes=1))).total_seconds()>90:
        return {},'missing_or_stale_completed_bars'
    if any((b[0]-a[0]).total_seconds()!=60 for a,b in zip(rows[-10:],rows[-9:])):
        return {},'gap_in_last_ten_minutes'
    last=rows[-1][1]; recent=[r for _,r in rows[-5:]]; prior=[r for _,r in rows[-10:-5]]
    width=last['high']-last['low']; volumes=sum(r['volume'] for _,r in rows)
    prior_volume=sum(r['volume'] for r in prior)
    vwap=sum((r['high']+r['low']+r['close'])/3*r['volume'] for _,r in rows)/volumes if volumes>0 else None
    f=dict(body_ratio=abs(last['close']-last['open'])/width if width>0 else 0,
           upper_wick_ratio=(last['high']-max(last['open'],last['close']))/width if width>0 else 0,
           lower_wick_ratio=(min(last['open'],last['close'])-last['low'])/width if width>0 else 0,
           close_position=(last['close']-last['low'])/width if width>0 else .5,
           pre_return_5m_pct=(last['close']/recent[0]['open']-1)*100,
           pre_range_5m_pct=(max(r['high'] for r in recent)-min(r['low'] for r in recent))/recent[0]['open']*100,
           volume_ratio_5m=sum(r['volume'] for r in recent)/prior_volume if prior_volume>0 else None,
           vwap_distance_pct=(last['close']/vwap-1)*100 if vwap else None)
    return f,None


def market_features(snapshots, entry):
    at=stamp(entry); result={}; times={}
    for key in ('taiex','otc'):
        quotes=[]
        for snap in snapshots:
            try:
                received=stamp(snap['received_at']);q=snap.get('indices',{}).get(key,{})
                qt=stamp(q['quote_at']); qr=stamp(q['received_at'])
                if qt.date()==at.date() and qt<=qr<=received<=at and number(q.get('price')) and q['price']>0:
                    quotes.append((qt,q['price'],received))
            except (KeyError,TypeError,ValueError):
                continue
        current=max(quotes,default=None,key=lambda q:q[0])
        value=None
        if current and 0<=(at-current[0]).total_seconds()<=90:
            boundary=current[0]-timedelta(minutes=5)
            old=max((q for q in quotes if q[0]<=boundary and (boundary-q[0]).total_seconds()<=90),default=None,key=lambda q:q[0])
            if old:
                value=(current[1]/old[1]-1)*100
                times[key]=[old[0].isoformat(),current[0].isoformat(),current[2].isoformat()]
        result[key+'_return_5m_pct']=value
    return result,times


def make_rows(trades, packs, snapshots, day):
    checked_day(day); rows=[]; excluded=Counter(); seen=set()
    for trade in trades:
        key=trade.get('episode_id') or trade.get('research_trade_id')
        if not key or key in seen:
            excluded['missing_or_duplicate_episode']+=1;continue
        seen.add(key)
        try:
            entry,exit=stamp(trade['entry_time']),stamp(trade['exit_time'])
            if entry.date().isoformat()!=day or exit.date()!=entry.date() or exit<entry or trade.get('status')!='CLOSED':
                raise ValueError('invalid_outcome')
        except (KeyError,ValueError,TypeError):
            excluded['unclosed_or_invalid_outcome']+=1;continue
        label=trade.get('research_net_after_spread_pct')
        if not number(label):
            excluded['missing_cost_and_spread_label']+=1;continue
        features={k:(trade.get('entry_features') or {}).get(k) for k in BASE}
        pattern,reason=pattern_features(packs.get(trade['symbol'],{}),trade['entry_time'])
        market,times=market_features(snapshots,trade['entry_time']);features.update(pattern);features.update(market)
        missing=[k for k in FEATURES if not number(features.get(k))]
        rows.append(dict(id=key,day=day,symbol=trade['symbol'],name=trade.get('name'),
            entry_time=trade['entry_time'],exit_time=trade['exit_time'],features=features,
            missing_features=missing,pattern_issue=reason,market_quote_times=times,
            net_return_pct=label,profitable=label>0,paper_execution=trade.get('paper_execution'),
            paper_skip_reason=trade.get('paper_skip_reason'),exit_reason=trade.get('exit_reason'),
            mfe_pct=trade.get('mfe_pct'),mae_pct=trade.get('mae_pct'),
            label_cost_basis=trade.get('research_cost_basis'),exit_mode=trade.get('exit_mode'),
            policy_version=(trade.get('entry_gate_evidence') or {}).get('research_policy_version'),
            online_features=(trade.get('entry_gate_evidence') or {}).get('a_context_features'),
            online_captured_at=(trade.get('entry_gate_evidence') or {}).get('a_context_captured_at'),
            bar_basis='retrospective_completed_minute_bars_not_verified_live_availability'))
    return rows,dict(excluded)


def summarize(rows,excluded):
    groups={}
    for label,values in [('all',rows),('paper_filled',[r for r in rows if r['paper_execution']=='FILLED']),
                         ('paper_skipped',[r for r in rows if r['paper_execution']=='SKIPPED'])]:
        groups[label]=dict(count=len(values),wins=sum(r['profitable'] for r in values),
            mean_net_after_spread_pct=sum(r['net_return_pct'] for r in values)/len(values) if values else None)
    comparison={}
    for f in FEATURES:
        comparison[f]={}
        for name,won in [('profitable',True),('nonprofitable',False)]:
            v=[r['features'][f] for r in rows if r['profitable']==won and number(r['features'].get(f))]
            comparison[f][name]={'count':len(v),'mean':sum(v)/len(v) if v else None}
    return dict(schema=SCHEMA,groups=groups,excluded=excluded,feature_comparison=comparison,
        complete_feature_rows=sum(not r['missing_features'] for r in rows),
        missing_features=dict(Counter(k for r in rows for k in r['missing_features'])),
        skip_reasons=dict(Counter(r['paper_skip_reason'] for r in rows if r['paper_skip_reason'])),
        status='DESCRIPTIVE_ONLY',production_changed=False,
        limitations=['Observed accepted A signals only; no rejected-signal outcomes are fabricated.',
            'Completed minute bars are retrospective reconstructions, not verified live feature availability.',
            'Research cost/spread outcomes are proxy fills, not account profits.',
            'Winner/loser averages are exploratory, not independent confirmation or causal effects.',
            'Missing outcomes and missing market context are not zero or a loss.'])


def candidate_status(rows):
    """Freeze eligibility now. No same-day or random split, no auto promotion."""
    days=sorted({r['day'] for r in rows}); complete=[r for r in rows if not r['missing_features']]
    result=dict(schema=SCHEMA,status='BLOCKED',deployment_allowed=False,approved=False,
        reason='collect_versioned_online_features_and_forward_validation_first',
        observed_dates=len(days),complete_samples=len(complete),
        required_dates=101,required_samples=1000,required_per_class=30,
        validation='three chronological 20-day windows; one full embargo day; overlapping outcomes purged',
        threshold=.6,features=list(FEATURES),prospective_start='2026-10-15',
        required_before_training=['versioned entry policy','online feature parity including market timestamps',
            'enough independent dates and balanced outcomes','frozen forward validation protocol'],
        exclusions=['paper fill flag and skip reason','exit price and reason','MFE and MAE','future bars'])
    online=[r for r in rows if r['day']>='2026-10-15' and r.get('policy_version')
            and r.get('online_captured_at') and stamp(r['online_captured_at'])<=stamp(r['entry_time'])
            and isinstance(r.get('online_features'),dict)
            and all(number(r['online_features'].get(k)) for k in FEATURES)]
    if not online:return result
    profile=max(online,key=lambda r:r['entry_time'])['policy_version']
    online=[r for r in online if r['policy_version']==profile]
    days=sorted({r['day'] for r in online})
    result.update(eligible_online_samples=len(online),eligible_online_dates=len(days),policy_version=profile)
    if len(days)<101 or len(online)<1000:return result
    from .research import fit_logistic,logistic_probabilities
    folds=[];last_model=None
    for offset in (60,40,20):
        test_days=set(days[-offset:][:20]);start=days.index(min(test_days));train_days=set(days[:start-1])
        fit=[dict(r,features=[r['online_features'][k] for k in FEATURES]) for r in online if r['day'] in train_days]
        test=[dict(r,features=[r['online_features'][k] for k in FEATURES]) for r in online if r['day'] in test_days]
        positives=sum(r['net_return_pct']>0 for r in fit)
        if min(positives,len(fit)-positives)<30:return dict(result,reason='insufficient_training_class_balance')
        model=fit_logistic(fit,feature_count=len(FEATURES));probs=logistic_probabilities(model,test)
        selected=[r for r,p in zip(test,probs) if p>=.6]
        prior=positives/len(fit)
        brier=sum((p-int(r['net_return_pct']>0))**2 for r,p in zip(test,probs))/len(test)
        constant=sum((prior-int(r['net_return_pct']>0))**2 for r in test)/len(test)
        folds.append(dict(train_through=max(train_days),embargo_date=days[start-1],test_from=min(test_days),test_through=max(test_days),
            test_samples=len(test),selected=len(selected),brier=brier,training_prior_brier=constant,
            selected_mean_net_pct=sum(r['net_return_pct'] for r in selected)/len(selected) if selected else None,
            all_signal_mean_net_pct=sum(r['net_return_pct'] for r in test)/len(test)))
        last_model=model
    return dict(result,status='CANDIDATE_ONLY',reason='chronological_validation_complete_not_approved',folds=folds,
        model=last_model,trained_through=folds[-1]['train_through'],
        requirements_before_promotion=['untouched forward window','capital and drawdown simulation','live shadow comparison'])


def capture_online(cache,symbol,entry,base,manager,market_directory):
    """Small read-only capture; caller keeps failures separate from entry rules."""
    pack={'bars':[dict(r,at=r['date']) for r in cache._aggregate(symbol,1)]}
    pattern,_=pattern_features(pack,entry)
    path=Path(market_directory)/'dataset'/(stamp(entry).date().isoformat()+'.jsonl')
    snapshots=[]
    if path.exists():
        with path.open(encoding='utf-8') as f:
            for line in f:
                try:snapshots.append(json.loads(line))
                except ValueError:continue
    market,times=market_features(snapshots,entry)
    policy={k:getattr(manager,k,None) for k in ('exit_mode','stop_loss_pct','take_profit_pct',
        'trailing_activate_pct','trailing_pullback_pct','breakeven_activate_pct','breakeven_floor_pct')}
    root=Path(__file__).resolve().parents[1]
    source_hashes={name:hashlib.sha256((root/name).read_bytes()).hexdigest()
                   for name in ('intraday_live.py','strategy_engine.py','position_manager.py')}
    version=hashlib.sha256(json.dumps([policy,source_hashes],sort_keys=True).encode()).hexdigest()
    return {'a_context_features':dict({k:base.get(k) for k in BASE},**pattern,**market),
            'a_context_captured_at':datetime.now(TPE).isoformat(),
            'a_context_market_times':times,'research_policy_version':version}


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,allow_nan=False,indent=2),encoding='utf-8');temp.replace(path)


def build(data,market,out,day):
    day=checked_day(day);data=Path(data);market=Path(market);out=Path(out)
    with sqlite3.connect((data/'research.sqlite').resolve().as_uri()+'?mode=ro',uri=True) as db:
        trades=[json.loads(r[0]) for r in db.execute('SELECT payload FROM research_trades WHERE day=?',(day,))]
    packs={};sources=[]
    for symbol in sorted({r['symbol'] for r in trades}):
        if not re.fullmatch(r'\d{4,6}',symbol):continue
        p=data/'bars'/day/(symbol+'.json')
        if p.exists():
            packs[symbol]=json.loads(p.read_text(encoding='utf-8'));sources.append(p)
    path=market/'dataset'/(day+'.jsonl'); snapshots=[]
    if path.exists():
        with path.open(encoding='utf-8') as f:
            for line in f:
                snapshots.append(json.loads(line))
        sources.append(path)
    rows,excluded=make_rows(trades,packs,snapshots,day)
    dataset=dict(schema=SCHEMA,day=day,rows=rows,source_hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
        outcome_source=str(data/'research.sqlite'),outcome_query='SELECT payload FROM research_trades WHERE day=?',
        outcome_query_day=day,outcome_snapshot_sha256=hashlib.sha256(json.dumps(trades,sort_keys=True).encode()).hexdigest())
    write(out/'datasets'/(day+'.json'),dataset)
    history=[]
    for p in sorted((out/'datasets').glob('????-??-??.json')):
        if START<=p.stem<=day:
            payload=json.loads(p.read_text(encoding='utf-8'))
            if payload.get('schema')==SCHEMA and payload.get('day')==p.stem:
                history.extend(payload['rows'])
    report=summarize(rows,excluded);report.update(day=day,candidate=candidate_status(history))
    write(out/'reports'/(day+'.json'),report);write(out/'latest.json',report)
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--date',default=datetime.now(TPE).date().isoformat())
    p.add_argument('--data',default='/home/ubuntu/easystock-learning-data')
    p.add_argument('--market',default='/home/ubuntu/easystock-market-data')
    p.add_argument('--out',default='/home/ubuntu/easystock-a-signal-learning')
    a=p.parse_args();r=build(a.data,a.market,a.out,a.date)
    print(json.dumps({k:r[k] for k in ('day','groups','complete_feature_rows','missing_features','candidate')},ensure_ascii=False))


if __name__=='__main__':main()
