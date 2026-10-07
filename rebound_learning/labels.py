"""Future-bar outcomes, intentionally separate from candidate construction."""
from __future__ import annotations

import argparse
import json
import sqlite3

from .schema import connect, stable_json

HORIZONS=(1,3,5,10,20)


def label_candidate(snapshot: dict, future: list[dict], *, horizon: int = 10,
                    trading_days: list[str] | None = None) -> dict:
    """future contains trading-session bars ordered strictly after D0."""
    signal=snapshot['signal_date']
    if any(b['time']<=signal for b in future) or any(future[i]['time']>=future[i+1]['time'] for i in range(len(future)-1)):
        raise ValueError('label_nonmonotonic_or_future_source')
    target=snapshot['evidence']['target_price']
    invalid=snapshot['evidence']['invalid_price']
    if target is None or invalid is None:
        return {'label':None,'trainable':False,'reason':'no_bracket'}
    if trading_days is None: trading_days=[b['time'] for b in future]
    if any(day<=signal for day in trading_days) or trading_days!=sorted(set(trading_days)):
        raise ValueError('nonmonotonic_trading_calendar')
    if not trading_days:
        return {'label':None,'trainable':False,'reason':'awaiting_D1'}
    by_day={bar['time']:bar for bar in future}
    entry=by_day.get(trading_days[0])
    if entry is None:
        return {'label':None,'trainable':False,'reason':'missing_D1_bar'}
    price=float(entry['open'])
    if not invalid<price<target:
        return {'label':None,'trainable':False,'reason':'entry_outside_bracket',
                'entry_date':entry['time']}
    result={'entry_date':entry['time'],'entry_price':price,'label':None,
            'trainable':False,'reason':'awaiting_maturity','target_price':target,
            'invalid_price':invalid,'exit_date':None,'label_maturity_date':None,
            'days_to_target':None,'days_to_invalid':None}
    ordered=[by_day.get(day) for day in trading_days]
    for n in HORIZONS:
        part=ordered[:n] if len(ordered)>=n else []
        result[f'return_{n}d_pct']=round((part[-1]['close']/price-1)*100,6) if part and all(part) else None
    for n in (5,10):
        part=ordered[:n] if len(ordered)>=n else []
        if part and not all(part): part=[]
        result[f'MFE_{n}d_pct']=round((max(b['high'] for b in part)/price-1)*100,6) if part else None
        result[f'MAE_{n}d_pct']=round((min(b['low'] for b in part)/price-1)*100,6) if part else None
    if len(trading_days)<horizon:
        return result
    result['label_maturity_date']=trading_days[horizon-1]
    if not all(ordered[:horizon]):
        result['reason']='missing_horizon_bar'
        return result
    for n,b in enumerate(ordered[:horizon],start=1):
        hit_target=b['high']>=target
        hit_invalid=b['low']<=invalid
        if hit_target and result['days_to_target'] is None: result['days_to_target']=n
        if hit_invalid and result['days_to_invalid'] is None: result['days_to_invalid']=n
        if result['label'] is None and (hit_target or hit_invalid):
            result['label']='AMBIGUOUS' if hit_target and hit_invalid else 'SUCCESS' if hit_target else 'FAIL'
            result['exit_date']=b['time']
    if result['label'] is None:
        result['label']='TIMEOUT'; result['exit_date']=trading_days[horizon-1]
    result['reason']=None
    result['trainable']=result['label']!='AMBIGUOUS'
    return result


def update_labels(db: sqlite3.Connection, *, commit: bool = True,
                  load_future=None, skip_matured: bool = False) -> int:
    """load_future(symbol, signal_date) may supply bars already on the D0 basis."""
    count=0
    query='SELECT id FROM candidates'
    if skip_matured:
        # A matured, decided label cannot change without source data changing.
        query+=" WHERE label IS NULL OR json_extract(label,'$.label') IS NULL"
    for (key,) in db.execute(query+' ORDER BY signal_date,symbol').fetchall():
        item=db.execute('SELECT id,snapshot,label FROM candidates WHERE id=?',(key,)).fetchone()
        snapshot=json.loads(item['snapshot'])
        if load_future:
            future=load_future(snapshot['symbol'],snapshot['signal_date'])
        else:
            future=[json.loads(row['bar']) for row in db.execute('''SELECT bar FROM daily_bars
                WHERE symbol=? AND day>? ORDER BY day LIMIT 20''',
                (snapshot['symbol'],snapshot['signal_date']))]
        calendar=[row['day'] for row in db.execute('SELECT day FROM trading_days WHERE day>? ORDER BY day LIMIT 20',
                      (snapshot['signal_date'],))]
        new=label_candidate(snapshot,future,trading_days=calendar)
        old=json.loads(item['label']) if item['label'] else None
        if old != new:
            db.execute('UPDATE candidates SET label=? WHERE id=?',(stable_json(new),item['id']))
            count+=1
    if commit: db.commit()
    return count


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--dry-run',action='store_true')
    args=parser.parse_args()
    with connect() as db:
        if args.dry_run: db.execute('SAVEPOINT dry_run')
        count=update_labels(db,commit=not args.dry_run)
        if args.dry_run: db.execute('ROLLBACK TO dry_run')
    print(json.dumps({'labels_updated':count,'dry_run':args.dry_run}))


if __name__=='__main__': main()
