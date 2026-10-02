"""Replay Shioaji daily archives with a strict D0 cutoff, never future bars."""
from __future__ import annotations

import argparse
import gzip
import json
import sys
from bisect import bisect_right
from collections import defaultdict
from datetime import datetime, timedelta, time
from pathlib import Path

from .collector import collect
from . import STRATEGY_VERSION, FEATURE_SCHEMA_VERSION
from .schema import connect, save_bar, save_candidate

DEFAULT_SOURCE=Path('/home/ubuntu/easystock-history-expanded-data')


def archive_to_daily(path: Path) -> tuple[str,dict]:
    """Aggregate one audited minute-K archive, preserving native volume units."""
    with gzip.open(path,'rt',encoding='utf-8') as stream:
        raw=json.load(stream)
    symbol=str(raw['symbol']); day=str(raw['date'])
    if path.parent.name!=day or path.stem.removesuffix('.json')!=symbol:
        raise ValueError(f'archive_identity_mismatch:{path}')
    data=raw['kbars']; fields=('ts','Open','High','Low','Close','Volume','Amount')
    if any(key not in data for key in fields): raise ValueError(f'archive_missing_columns:{path}')
    count=len(data['ts'])
    if not count or any(len(data[key])!=count for key in fields): raise ValueError(f'archive_length_mismatch:{path}')
    # The archived SDK timestamps encode naive Taiwan wall-clock in nanoseconds
    # (see history/collector_core.py:raw_datetime). fromtimestamp(+08) is wrong.
    times=[datetime(1970,1,1)+timedelta(microseconds=int(ts)//1000) for ts in data['ts']]
    if any(t.date().isoformat()!=day for t in times) or any(times[i]>=times[i+1] for i in range(len(times)-1)):
        raise ValueError(f'archive_nonmonotonic_or_wrong_day:{path}')
    normal=[i for i,t in enumerate(times) if time(9,1)<=t.time()<=time(13,30)]
    if not normal: raise ValueError(f'archive_no_regular_session:{path}')
    opens,highs,lows,closes=([float(data[key][i]) for i in normal] for key in ('Open','High','Low','Close'))
    bar={'time':day,'open':opens[0],'high':max(highs),'low':min(lows),
         'close':closes[-1],
         'volume':sum(float(data['Volume'][i]) for i in normal),
         'amount':sum(float(data['Amount'][i]) for i in normal)}
    if (bar['low']<=0 or bar['high']<max(bar['open'],bar['close'],bar['low'])
            or bar['low']>min(bar['open'],bar['close']) or bar['amount']<0 or bar['volume']<0):
        raise ValueError(f'archive_invalid_ohlc:{path}')
    return symbol,bar


def selected_days(source: Path, start: str | None, end: str | None,
                  limit_days: int | None) -> list[str]:
    plan=json.loads((source/'plan.json').read_text(encoding='utf-8'))
    days=[day for day in plan['dates'] if (start is None or day>=start) and (end is None or day<=end)]
    if limit_days is not None: days=days[-limit_days:]
    return days


def load_archives(source: Path, days: list[str]) -> dict[str,list[dict]]:
    if not days:return {}
    plan=json.loads((source/'plan.json').read_text(encoding='utf-8'))
    calendar=plan['dates']
    first=max(0,bisect_right(calendar,days[0])-253)
    last=min(len(calendar),bisect_right(calendar,days[-1])+20)
    need=set(calendar[first:last])
    histories=defaultdict(list)
    for n,day in enumerate(sorted(need),start=1):
        for path in sorted((source/'raw'/day).glob('*.json.gz')):
            symbol,bar=archive_to_daily(path)
            histories[symbol].append(bar)
        if n%50==0:print(f'[rebound] archives {n}/{len(need)} sessions',file=sys.stderr,flush=True)
    return dict(histories)


def run(db, histories: dict[str,list[dict]], days: list[str], *,
        source: str='shioaji_archive', trading_days: list[str] | None = None,
        expected_symbols: int | None = None) -> dict:
    """A symbol's extractor is passed only its prefix ending at D0."""
    indexed={symbol:{bar['time']:i for i,bar in enumerate(bars)} for symbol,bars in histories.items()}
    calendar=trading_days or sorted({bar['time'] for bars in histories.values() for bar in bars})
    db.executemany('INSERT OR IGNORE INTO trading_days(day) VALUES(?)',((day,) for day in calendar))
    for symbol,bars in histories.items():
        for bar in bars: save_bar(db,symbol,bar)
    scanned=0; saved=0; reused=0
    for n,day in enumerate(days,start=1):
        todays=[(symbol,bars,indexed[symbol][day]) for symbol,bars in sorted(histories.items()) if day in indexed[symbol]]
        amounts=sorted((bars[i]['amount'] for _,bars,i in todays),reverse=True)
        # Archive coverage can grow between runs, changing cross-sectional
        # ranks. Existing PIT snapshots and their labels remain immutable.
        frozen={row[0] for row in db.execute('''SELECT symbol FROM candidates
            WHERE strategy_version=? AND feature_schema_version=? AND signal_date=?''',
            (STRATEGY_VERSION,FEATURE_SCHEMA_VERSION,day))}
        for symbol,bars,i in todays:
            if symbol in frozen:
                reused+=1
                continue
            prefix=bars[max(0,i-251):i+1]
            rank=(amounts.index(bars[i]['amount'])+1)/len(amounts) if amounts else None
            row=collect(symbol,prefix,day,amount_rank=rank)
            if row:
                save_candidate(db,row); saved+=1
        db.execute('''INSERT INTO scan_days(day,symbols_scanned,symbols_expected,source) VALUES(?,?,?,?)
            ON CONFLICT(day) DO UPDATE SET symbols_scanned=excluded.symbols_scanned,
            symbols_expected=excluded.symbols_expected''',
            (day,len(todays),expected_symbols or len(histories),source))
        scanned+=len(todays)
        db.commit()
        if n%20==0:print(f'[rebound] candidates {n}/{len(days)} sessions',file=sys.stderr,flush=True)
    return {'trading_days_scanned':len(days),'symbols_scanned':len(histories),
            'stock_days_scanned':scanned,'candidate_events':saved,
            'candidate_snapshots_reused':reused}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',type=Path,default=DEFAULT_SOURCE)
    parser.add_argument('--from',dest='start')
    parser.add_argument('--to',dest='end')
    parser.add_argument('--limit-days',type=int)
    parser.add_argument('--dry-run',action='store_true')
    args=parser.parse_args()
    if args.limit_days is not None and args.limit_days<1: parser.error('--limit-days must be positive')
    days=selected_days(args.source,args.start,args.end,args.limit_days)
    if not days: parser.error('no trading days in requested range')
    histories=load_archives(args.source,days)
    plan=json.loads((args.source/'plan.json').read_text(encoding='utf-8'))
    with connect(Path(':memory:') if args.dry_run else None) as db:
        result=run(db,histories,days,trading_days=plan['dates'],expected_symbols=len(plan['symbols']))
        result.update(start=days[0],end=days[-1],dry_run=args.dry_run)
    print(json.dumps(result,sort_keys=True))


if __name__=='__main__':main()
