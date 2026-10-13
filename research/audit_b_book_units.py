"""Offline provider-size evidence; no login, subscriptions, strategy or orders.

Exact exchange-microsecond and complete-price-vector matches only. Observations
are evidence for these records, not a universal API unit guarantee.
"""
import argparse
from collections import Counter
from datetime import datetime,timezone
from decimal import Decimal
import gzip
import hashlib
import json
from pathlib import Path
import time


def micros(value):
    at=datetime.fromisoformat(value.replace('Z','+00:00'))
    if at.tzinfo is None: raise ValueError('missing_timezone')
    epoch=datetime(1970,1,1,tzinfo=timezone.utc)
    delta=at.astimezone(timezone.utc)-epoch
    return (delta.days*86400+delta.seconds)*1000000+delta.microseconds


def vector(quote,keys):
    result=[]
    for key in keys:
        values=quote[key]
        if len(values)!=5: raise ValueError('partial_book')
        result.extend(Decimal(str(v)) for v in values)
    return tuple(result)


def main(native,esun_files,output):
    if output.exists():raise ValueError('refuse_existing_output')
    indexed={};esun_count=0;hashes={}
    for file in esun_files:
        raw=file.read_bytes();hashes[file.name+'@'+file.parent.name]=hashlib.sha256(raw).hexdigest()
        for line in raw.splitlines():
            x=json.loads(line)
            if x.get('provider')!='esun' or x.get('kind')!='book':continue
            q=x['quote'];key=(x['symbol'],x['exchange_time_us'])
            try:pv=vector(q,('bid_price','ask_price'));sizes=vector(q,('bid_volume','ask_volume'))
            except (KeyError,ValueError):continue
            if min(pv)<=0 or min(sizes)<0:continue
            indexed[key]=(pv,sizes);esun_count+=1
    if not indexed:raise ValueError('no_esun_books')
    first=min(k[1] for k in indexed);last=max(k[1] for k in indexed)
    counts=Counter();symbols=Counter();examples=[];matches=set();started=time.monotonic()
    initial=native.stat();prefix=hashlib.sha256();last_clock=None
    with gzip.open(native,'rb') as f:
        for line in f:
            prefix.update(line);counts['journal_prefix_lines']+=1
            if b'"kind":"clock"' in line:
                x=json.loads(line);last_clock=micros(x['data']['now'])
                if last_clock>last+1000000:break
            if b'"kind":"bidask"' not in line:continue
            counts['native_book_prefix_events']+=1
            x=json.loads(line);d=x['data'];q=d['quote'];at=micros(q['datetime'])
            if not first<=at<=last:continue
            counts['native_books_in_window']+=1;key=(d['symbol'],at)
            if key not in indexed:continue
            if key in matches:continue
            matches.add(key);counts['exact_time_pairs']+=1
            pv,sizes=indexed[key]
            if vector(q,('bid_price','ask_price'))!=pv:
                counts['exact_time_price_mismatch']+=1;continue
            ns=vector(q,('bid_volume','ask_volume'))
            informative=[(a,b) for a,b in zip(sizes,ns) if b>0]
            if len(informative)<8:
                counts['uninformative_pairs']+=1;continue
            equal=all(a==b for a,b in zip(sizes,ns))
            shares=all(a==b*1000 for a,b in zip(sizes,ns))
            label='same_native_lot_scale' if equal else 'esun_share_scale' if shares else 'size_mismatch'
            counts[label]+=1;symbols[(d['symbol'],label)]+=1
            if len(examples)<20:
                examples.append(dict(symbol=d['symbol'],exchange_time_us=at,scale=label,
                    esun_sizes=[float(a) for a in sizes],native_sizes=[float(a) for a in ns]))
            if time.monotonic()-started>120:raise ValueError('audit_time_budget')
    final=native.stat()
    if (initial.st_size,initial.st_mtime_ns)!=(final.st_size,final.st_mtime_ns):raise ValueError('native_file_changed')
    report=dict(mode='offline_exact_timestamp_unit_evidence',esun_books=esun_count,indexed=len(indexed),
        counts=dict(counts),symbols=[dict(symbol=k[0],scale=k[1],pairs=n) for k,n in sorted(symbols.items())],
        examples=examples,window_microseconds=[first,last],esun_sha256=hashes,
        native_file=native.name,native_file_bytes=initial.st_size,native_prefix_sha256=prefix.hexdigest(),
        prefix_not_full_journal=True,last_clock_us=last_clock,
        caveat='Exact matches only establish scale of observed standard-stock records; no universal quantity contract or live consumer validation.',
        production_changed=False,execution_allowed=False)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ['esun_books','indexed','counts','symbols','caveat']}),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--native',type=Path,required=True)
    p.add_argument('--esun',type=Path,nargs='+',required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();main(a.native,a.esun,a.output)
