"""Audit and replay frozen LaneSuite inputs. No broker, fake depth or notifications."""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import date, datetime, timedelta
import gzip
import hashlib
import heapq
import json
from pathlib import Path
import sqlite3
import tempfile

from .lanes import LaneSuite, SPECS, TPE, stamp, completed_bars
from .orderbook import get_tick_size
from .replay_journal import SCHEMA, fingerprint


def state_hash(state):
    return hashlib.sha256(json.dumps(state,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def digest_file(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024**2),b''):
            h.update(chunk)
    return h.hexdigest()


class Cache:
    def __init__(self, bars): self.bars=bars
    def rows5(self, symbol): return self.bars.get(symbol,[])


class EventStream:
    """Re-iterable compressed source: never load a whole day's callbacks into RAM."""
    def __init__(self, paths): self.paths=paths
    def __bool__(self): return bool(self.paths)
    def __iter__(self):
        for path in self.paths:
            with gzip.open(path,'rt',encoding='utf-8') as stream:
                for line in stream: yield json.loads(line)


def apply(suite, event):
    kind,d=event['kind'],event['data']
    if kind=='seed':
        suite.day=d['day']; suite.state=json.loads(json.dumps(d['state']))
        suite.prior_unresolved=bool(d['prior_unresolved'])
        suite.rows.clear(); suite.bars.clear(); suite.books.clear(); suite.tapes.clear()
        suite.last_feed_at=None
    elif kind=='tick':
        suite.on_tick(d['symbol'],d['price'],stamp(d['datetime']),d['tick_type'],d['volume'])
    elif kind=='bidask':
        suite.on_bidask(d['symbol'],d['quote'])
    elif kind=='radar':
        suite.on_radar_update(d['rows'],Cache(d['bars']),d['previous_closes'],stamp(d['now']),market=d['market'])
    elif kind=='release':
        suite.release_symbol(d['symbol'])
    elif kind=='clock':
        suite.advance(stamp(d['now']))
    else:
        raise ValueError('unknown input kind')


def replay_events(events, delay_ms=0):
    """Preserve accepted-input sequence; delayed quotes become available at clocks.

    Baseline uses exact recorded callbacks. Stress delays tick/book delivery only,
    retains original exchange timestamps and never refreshes stale quote ages.
    """
    with tempfile.TemporaryDirectory(prefix='b-lanes-replay-') as tmp:
        suite=LaneSuite(Path(tmp)/'offline.sqlite',sender=lambda *_:None,offline=True)
        suite.enabled=True
        pending=[]; mismatch=0; first_mismatch=None; ordinal=0
        try:
            for event in events:
                if delay_ms and event['kind'] in ('tick','bidask'):
                    ordinal+=1
                    at=stamp(event['received_at'])+timedelta(milliseconds=delay_ms)
                    heapq.heappush(pending,(at,ordinal,event))
                    continue
                if event['kind']=='clock' and delay_ms:
                    now=stamp(event['data']['now'])
                    while pending and pending[0][0]<=now:
                        apply(suite,heapq.heappop(pending)[2])
                apply(suite,event)
                if event['kind']=='clock' and not delay_ms:
                    if state_hash(suite.state)!=event['data']['state_hash']:
                        mismatch+=1
                        first_mismatch=first_mismatch or event['data']['now']
            return dict(state=json.loads(json.dumps(suite.state)),mismatched_clocks=mismatch,
                        first_mismatch=first_mismatch,pending_inputs=len(pending))
        finally:
            suite.worker.shutdown(wait=True)


def load_day(folder):
    raw_paths=[]; failures=[]; manifests=[]; clocks=[]; max_gap=0; lane_gaps=Counter(); counts=Counter(); unresolved=False
    last_received=None; first_market=None; max_bars=0; sectors=Counter(); observed={k:Counter() for k in SPECS}
    paths=sorted(Path(folder).glob('*.manifest.json'))
    if not paths: return [],{},['缺少新版完整輸入錄製']
    for path in paths:
        try:
            meta=json.loads(path.read_text(encoding='utf-8'))
            if meta['schema']!=SCHEMA: raise ValueError('錄製格式不符')
            if not meta.get('complete') or meta.get('dropped') or meta.get('errors'): raise ValueError('錄製未完整結束或有遺失')
            if meta['strategy_fingerprint']!=fingerprint(): raise ValueError('規則版本不同，不能混算')
            if Path(meta['file']).name!=meta['file']: raise ValueError('錄製檔路徑不符')
            raw=path.parent/meta['file']
            if digest_file(raw)!=meta['sha256']: raise ValueError('錄製檔雜湊不符')
            raw_paths.append(raw)
            seq=0
            with gzip.open(raw,'rt',encoding='utf-8') as stream:
                for line in stream:
                    e=json.loads(line); seq+=1
                    if e['seq']!=seq: raise ValueError('輸入序號不連續')
                    recv=stamp(e['received_at'])
                    if recv is None or recv.date().isoformat()!=path.parent.name: raise ValueError('取得時間或日期不符')
                    if last_received is not None and recv<last_received: raise ValueError('取得時間倒退')
                    last_received=recv
                    kind,d=e['kind'],e['data']; counts[kind]+=1
                    if kind=='seed' and d.get('prior_unresolved'): unresolved=True
                    if kind not in ('seed','clock','bidask','tick','radar','release'): raise ValueError('未知輸入種類')
                    if kind=='clock':
                        at=stamp(d['now'])
                        if at is None or at.date().isoformat()!=path.parent.name: raise ValueError('判斷日期不符')
                        if clocks:
                            gap=(at-clocks[-1]).total_seconds()
                            if gap<0: raise ValueError('判斷時間倒退')
                            max_gap=max(max_gap,gap)
                            for lane,spec in SPECS.items():
                                opening=at.replace(hour=9,minute=0,second=0,microsecond=0)
                                h,m,s=map(int,spec['end'].split(':'))
                                ending=at.replace(hour=h,minute=m,second=s,microsecond=0)
                                relevant=max(0,(min(at,ending)-max(clocks[-1],opening)).total_seconds())
                                lane_gaps[lane]=max(lane_gaps[lane],relevant)
                        clocks.append(at)
                    if kind=='radar':
                        at=stamp(d['now'])
                        if d['market'].get('valid'): first_market=first_market or at
                        sectors.update(str(r.get('sector')) for r in d['rows'] if r.get('sector') and r.get('previous_close'))
                        for bars in d['bars'].values():
                            if len(completed_bars(bars,at))!=len(bars): raise ValueError('五分K有未完成／未來資料')
                            max_bars=max(max_bars,len(bars))
                    if kind in ('tick','bidask'):
                        at=stamp(d.get('datetime') if kind=='tick' else d['quote']['datetime'])
                        if at is None: raise ValueError('行情时间不符')
                        for lane,spec in SPECS.items():
                            if spec['start']<=at.strftime('%H:%M:%S')<=spec['end']: observed[lane][kind]+=1
            if seq!=meta['written'] or seq!=meta['last_sequence']: raise ValueError('錄製筆數不符')
            manifests.append(meta)
        except (OSError,KeyError,ValueError,TypeError) as exc:
            failures.append(str(exc))
    if not counts['seed'] or not counts['clock']: failures.append('缺少初始狀態或判斷時間')
    if not counts['radar'] or first_market is None: failures.append('股票池或有效大盤資料不足')
    if unresolved: failures.append('前日未平倉，不能視為獨立乾淨回測')
    profile=dict(segments=len(paths),input_counts=dict(counts),first_clock=clocks[0].isoformat() if clocks else None,
                 last_clock=clocks[-1].isoformat() if clocks else None,max_clock_gap=max_gap,
                 max_clock_gap_by_lane=dict(lane_gaps),
                 max_completed_5m_bars=max_bars,manifests=manifests)
    eligibility={}
    for lane,spec in SPECS.items():
        reasons=list(dict.fromkeys(failures))
        if lane_gaps[lane]>30: reasons.append('該跑道時段判斷時鐘中斷超過30秒')
        if not clocks or clocks[0].strftime('%H:%M:%S')>'09:00:00' or clocks[-1].strftime('%H:%M:%S')<spec['end']:
            reasons.append('未涵蓋開盤至該跑道結束')
        if not observed[lane]['tick'] or not observed[lane]['bidask']: reasons.append('該時段缺逐筆或五檔')
        if lane=='B1' and not sectors: reasons.append('缺當時產業分類')
        if lane=='B2' and max_bars<20: reasons.append('缺20根完整五分K')
        if lane=='B3' and max_bars<3: reasons.append('缺3根完整五分K')
        eligibility[lane]=dict(eligible=not reasons,reasons=list(dict.fromkeys(reasons)))
    profile['eligibility']=eligibility
    return EventStream(raw_paths),profile,failures


def trade_metrics(trades, extra_ticks=0):
    trades=sorted(trades,key=lambda t:t['exit_time'])
    profits=[float(t['net_pnl'])-extra_ticks*t['shares']*(get_tick_size(t['entry_price'])+get_tick_size(t['exit_price'])) for t in trades]
    equity=peak=drawdown=0
    for p in profits:
        equity+=p; peak=max(peak,equity); drawdown=max(drawdown,peak-equity)
    return dict(trades=len(trades),win_rate=round(sum(p>0 for p in profits)/len(profits)*100,2) if profits else None,
                net_pnl=round(sum(profits),2) if profits else 0.0,max_realized_drawdown=round(drawdown,2),
                avg_net_pnl=round(sum(profits)/len(profits),2) if profits else None)


def normalized(state):
    return {k:{f:s.get(f) for f in ('positions','trades','entries','used')} for k,s in state.items()}


def live_state(db_path, day):
    if not db_path or not Path(db_path).exists(): return None
    with sqlite3.connect(Path(db_path).resolve().as_uri()+'?mode=ro',uri=True) as db:
        row=db.execute('SELECT state FROM sessions WHERE day=?',(day,)).fetchone()
    return json.loads(row[0]) if row else None


def inventory(history_roots, learning_root, book_root, since, until):
    days={}; totals=[]
    def add(day,key,count):
        try: date.fromisoformat(day)
        except ValueError: return
        if since<=day<=until: days.setdefault(day,{})[key]=days.setdefault(day,{}).get(key,0)+count
    for root in history_roots:
        path=Path(root)/'raw'; files=list(path.glob('*/*.json.gz'))
        totals.append(dict(source=str(path),files=len(files),days=len({p.parent.name for p in files})))
        for f in files: add(f.parent.name,'historical_tick_files',1)
    for folder in (Path(learning_root)/'bars').glob('*'):
        if folder.is_dir(): add(folder.name,'minute_bar_files',len(list(folder.glob('*.json'))))
    for f in Path(learning_root).glob('journal-*.jsonl'): add(f.stem.removeprefix('journal-'),'sample_journal_files',1)
    for f in (Path(learning_root)/'decision-ticks').glob('*/*.gz'): add(f.parent.name,'decision_tick_files',1)
    for f in (Path(book_root)/'raw').glob('*/*.jsonl.gz'): add(f.parent.name,'raw_five_level_files',1)
    return days,totals


def cache_key(folder, db_path, day):
    """Actual compressed-file hashes invalidate a cache even if metadata is unchanged."""
    paths=sorted(folder.glob('*.manifest.json'))
    if not paths: return None
    try:
        files=[]
        for p in paths:
            meta=json.loads(p.read_text(encoding='utf-8'))
            if Path(meta['file']).name!=meta['file']: return None
            files.append([p.name,digest_file(p),digest_file(folder/meta['file'])])
        live=live_state(db_path,day)
        return state_hash(dict(files=files,strategy=fingerprint(),live=normalized(live) if live else None))
    except (OSError,ValueError,KeyError,TypeError): return None


def build_report(record_root, history_roots=(), learning_root='', book_root='', db_path=None, since=None, until=None):
    until=until or datetime.now(TPE).date().isoformat()
    since=since or (date.fromisoformat(until)-timedelta(days=183)).isoformat()
    catalog,sources=inventory(history_roots,learning_root,book_root,since,until)
    for folder in Path(record_root).glob('*'):
        if folder.is_dir() and since<=folder.name<=until: catalog.setdefault(folder.name,{})
    daily=[]; aggregate={lane:{s:[] for s in ('baseline','delay500','delay1000','extra1tick')} for lane in SPECS}
    valid=Counter(); execution={k:Counter() for k in SPECS}
    cache_dir=Path(record_root).parent/'replay-cache'
    def collect(row):
        for lane in SPECS:
            entry=row['lanes'][lane]
            if entry['status'] in ('complete','pending'):
                execution[lane].update(entry.get('execution_checks',{}))
            if entry['status']!='complete': continue
            valid[lane]+=1
            for scenario,trades in entry['scenario_trades'].items():
                if entry['metrics'].get(scenario) is not None: aggregate[lane][scenario].extend(trades)
    for day,found in sorted(catalog.items()):
        key=cache_key(Path(record_root)/day,db_path,day)
        cached=cache_dir/(day+'.json')
        if key and cached.exists():
            try:
                payload=json.loads(cached.read_text(encoding='utf-8'))
                if payload['key']==key:
                    row=payload['row'];row['available']=found
                    daily.append(row);collect(row);continue
            except (OSError,ValueError,KeyError,TypeError): pass
        events,profile,failures=load_day(Path(record_root)/day)
        row=dict(day=day,available=found,profile={k:v for k,v in profile.items() if k!='manifests'},lanes={})
        if not events or failures:
            reasons=failures or ['缺少新版完整輸入錄製']
            if not found.get('raw_five_level_files'): reasons=list(reasons)+['沒有歷史完整五檔']
            for lane in SPECS: row['lanes'][lane]=dict(status='excluded',reasons=reasons,metrics=None)
            daily.append(row); continue
        baseline=replay_events(events)
        recorded=profile['manifests'][-1].get('final_state')
        archived=live_state(db_path,day)
        row['comparison']=dict(clock_mismatches=baseline['mismatched_clocks'],first_mismatch=baseline['first_mismatch'],
            recorded_final_match=normalized(recorded)==normalized(baseline['state']) if recorded else None,
            persisted_live_match=normalized(archived)==normalized(baseline['state']) if archived else None)
        if baseline['mismatched_clocks'] or row['comparison']['recorded_final_match'] is not True or row['comparison']['persisted_live_match'] is False:
            for lane in SPECS: row['lanes'][lane]=dict(status='excluded',reasons=['回放與錄製時狀態不一致'],metrics=None)
            daily.append(row); continue
        stressed={500:replay_events(events,500),1000:replay_events(events,1000)} if any(x['eligible'] for x in profile['eligibility'].values()) else {}
        for lane in SPECS:
            criteria=profile['eligibility'][lane]
            if not criteria['eligible']:
                row['lanes'][lane]=dict(status='excluded',reasons=criteria['reasons'],metrics=None); continue
            state=baseline['state'][lane]
            if state['positions']:
                row['lanes'][lane]=dict(status='pending',reasons=['時段結束後仍無足夠新鮮深度平倉'],metrics=None,
                    open_positions=len(state['positions']),execution_checks=state.get('execution_checks',{})); continue
            trade_sets={'baseline':state['trades'],'extra1tick':state['trades'],
                        'delay500':stressed[500]['state'][lane]['trades'],'delay1000':stressed[1000]['state'][lane]['trades']}
            metrics={}; scenario_pending={}
            for scenario,trades in trade_sets.items():
                if scenario.startswith('delay') and stressed[int(scenario[5:])]['state'][lane]['positions']:
                    scenario_pending[scenario]=True
                    metrics[scenario]=None
                    continue
                metrics[scenario]=trade_metrics(trades,1 if scenario=='extra1tick' else 0)
            row['lanes'][lane]=dict(status='complete',reasons=[],metrics=metrics,scenario_pending=scenario_pending,
                trades=state['trades'],scenario_trades=trade_sets,execution_checks=state.get('execution_checks',{}))
        daily.append(row)
        collect(row)
        if key:
            cache_dir.mkdir(parents=True,exist_ok=True)
            temp=cached.with_suffix('.tmp')
            temp.write_text(json.dumps(dict(key=key,row=row),ensure_ascii=False),encoding='utf-8')
            temp.chmod(0o600);temp.replace(cached)
    summary={}
    for lane in SPECS:
        s=dict(valid_days=valid[lane],excluded_days=sum(d['lanes'][lane]['status']=='excluded' for d in daily),
               pending_days=sum(d['lanes'][lane]['status']=='pending' for d in daily),scenarios={},execution_checks=dict(execution[lane]))
        s['execution_days']=sum(d['lanes'][lane]['status'] in ('complete','pending') for d in daily)
        for scenario,trades in aggregate[lane].items():
            scenario_days=sum(d['lanes'][lane]['status']=='complete' and d['lanes'][lane]['metrics'].get(scenario) is not None for d in daily)
            s['scenarios'][scenario]=dict(days=scenario_days,**trade_metrics(trades,1 if scenario=='extra1tick' else 0)) if scenario_days else dict(days=0,trades=0,win_rate=None,net_pnl=None,max_realized_drawdown=None,avg_net_pnl=None)
        checks=execution[lane]
        def rate(num,den): return round(checks[num]/checks[den]*100,2) if checks[den] else None
        s['execution_rates']=dict(stale_exit_pct=rate('stale_exit_checks','exit_quote_checks'),
            thin_exit_pct=rate('thin_exit_checks','exit_fill_checks'),thin_entry_pct=rate('thin_entry_checks','entry_fill_checks'))
        summary[lane]=s
    return dict(schema='b-lanes-replay-v1',generated_at=datetime.now(TPE).isoformat(),since=since,until=until,
                strategy_fingerprint=fingerprint(),source_inventory=sources,summary=summary,daily=daily,
                assumptions=['同一套LaneSuite規則；每條每日累計進場100萬元，獨立帳本。',
                    '基準以可見買一／賣一及深度估成交，已扣28折手續費與0.15%當沖稅，未模擬排隊或自身市場衝擊。',
                    '延遲情境只延後逐筆及五檔可用時間；一檔成本情境固定相同交易，雙邊各扣一個原價位跳動，並非重跑成交與停損路徑。',
                    '最大回撤以已實現淨損益計算，未納入盤中未實現損益。',
                    '延遲情境未平倉日期不列入該情境績效；比較必須同時查看各情境有效天數，不能把未平倉當成零損益。',
                    '正式績效只含完整、零掉筆、版本一致、狀態核對相符且已平倉日期；缺資料不當成零報酬。',
                    '來源範圍為當時訂閱股票池，不代表全市場；錄製無遺失亦不保證券商來源沒有漏行情。'])


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--record-root',default='/home/ubuntu/easystock-runway-v2/recordings')
    ap.add_argument('--history-root',action='append',default=[])
    ap.add_argument('--learning-root',default='/home/ubuntu/easystock-learning-data')
    ap.add_argument('--book-root',default='/home/ubuntu/easystock-orderbook')
    ap.add_argument('--live-db',default='/home/ubuntu/easystock-runway-v2/lanes.sqlite')
    ap.add_argument('--since'); ap.add_argument('--until')
    ap.add_argument('--output',default='/home/ubuntu/easystock-runway-v2/replay-latest.json')
    ap.add_argument('--publish',action='store_true')
    args=ap.parse_args()
    report=build_report(args.record_root,args.history_root,args.learning_root,args.book_root,args.live_db,args.since,args.until)
    out=Path(args.output); out.parent.mkdir(parents=True,exist_ok=True)
    temp=out.with_suffix('.tmp'); temp.write_text(json.dumps(report,ensure_ascii=False,allow_nan=False),encoding='utf-8'); temp.chmod(0o600); temp.replace(out)
    if args.publish:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).resolve().parents[1]/'.env')
        from firebase_store import FirebaseStore
        public={k:v for k,v in report.items() if k not in ('source_inventory','strategy_fingerprint')}
        for day in public['daily']:
            for lane in day['lanes'].values():
                lane.pop('trades',None);lane.pop('scenario_trades',None)
        FirebaseStore().root.child('public_feed').child('b_lanes_replay').set(public)
    print(json.dumps(dict(days=len(report['daily']),summary=report['summary']),ensure_ascii=False))


if __name__=='__main__': main()
