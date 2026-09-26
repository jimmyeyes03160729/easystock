#!/usr/bin/env python3
"""Read-only VM evidence summary. No broker, Firebase, AI calls or service changes.

Print only allowlisted settings, aggregate paper results, model metadata and log
categories. Never print credentials, raw logs, model weights or individual fills.
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import sqlite3
import subprocess

TPE = timezone(timedelta(hours=8))
SAFE = {'LIVE_ENTRY_MODE','LEARNING_ENABLED','AI_PAPER_MODE','AI_PAPER_MODEL_PATH',
        'LEARNING_DATA_DIR','EASYSTOCK_ADMIN_DB','LIVE_EXIT_MODE','LIVE_MAX_DAILY_ENTRIES',
        'FORCE_INTRADAY_LIVE','FORCE_PREMARKET_AI'}
UNITS = ['intraday','premarket','learning','learning-train','research-cycle',
         'paper-train','paper-feedback','learning-status','guardian','guardian-worker']


def command(args):
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=45)
        return r.returncode, r.stdout
    except (OSError, subprocess.TimeoutExpired):
        return -1, ''


def env_values(path):
    try:
        from dotenv import dotenv_values
        values = dotenv_values(path, interpolate=False)
    except ImportError:
        values = {}
        try:
            for line in path.read_text().splitlines():
                key, sep, value = line.removeprefix('export ').partition('=')
                if sep and key.strip() in SAFE:
                    values[key.strip()] = value.strip().strip('\"\'')
        except OSError:
            pass
    return {k:v for k,v in values.items() if k in SAFE and v is not None}


def fingerprint(path):
    try:
        raw = path.read_bytes()
        return {'sha256':hashlib.sha256(raw).hexdigest(), 'bytes':len(raw),
                'mtime':datetime.fromtimestamp(path.stat().st_mtime,TPE).isoformat()}
    except OSError:
        return {'missing':True}


def model_metadata(path):
    try:
        if path.stat().st_size > 2_000_000:
            return {'path':str(path),'skipped':'over_2MB'}
        obj = json.loads(path.read_text())
        if not isinstance(obj,dict):
            return None
        result = {'path':str(path), **fingerprint(path), 'metadata':{}}
        # Keep section-qualified names: a validation date is not a training date.
        fields = {'version','model_version','schema_version','status','state','approved',
                  'deployment_allowed','model_applied','trained_through','train_through',
                  'created_at','updated_at','threshold','samples','train_samples',
                  'forward_samples','dates','test_from','test_through'}
        for section in ('','training','model','model_application','validation','collection'):
            source = obj if not section else obj.get(section,{})
            if not isinstance(source,dict):
                continue
            for key in fields:
                v = source.get(key)
                if isinstance(v,(str,int,float,bool)) or v is None and key in source:
                    result['metadata'][(section+'.' if section else '')+key] = v
            if isinstance(source.get('features'),list):
                result['metadata'][(section+'.' if section else '')+'feature_count'] = len(source['features'])
        return result if result['metadata'] else None
    except (OSError,ValueError):
        return {'path':str(path),'unreadable':True}


def log_summary(unit, since):
    code, raw = command(['journalctl','-u',unit,'--since',since,'--no-pager','-o','json','-n','15000'])
    days = defaultdict(Counter)
    versions = defaultdict(set)
    frames = defaultdict(Counter)
    first = last = None
    for line in raw.splitlines():
        try:
            row=json.loads(line); msg=row.get('MESSAGE','')
            if not isinstance(msg,str):continue
            at=datetime.fromtimestamp(int(row['__REALTIME_TIMESTAMP'])/1e6,TPE).isoformat()
        except (ValueError,KeyError,TypeError):continue
        first=min(first or at,at);last=max(last or at,at);day=at[:10]
        for label, pattern in {
            'traceback':r'Traceback \(most recent call last\)',
            'process_failed':r'Main process exited|Failed with result',
            'started':r'Started .*|Shioaji login success',
            'normal_stop':r'Intraday Live stopped|13:00 daytrade closed',
            'market_closed':r'\[MARKET CLOSED\]',
            'calendar_error':r'\[CALENDAR ERROR\]',
            'model_evaluation_log':r'\[MODEL\]',
            'model_boot_log':r'\[MODEL_BOOT\]',
            'rules_decision_log':r'\[ENTRY_DECISION\] mode=rules',
            'model_decision_log':r'\[ENTRY_DECISION\] mode=model',
            'entry_log':r'ENTRY .*score=|\[ENTRY\]',
            'learning_error':r'\[LEARNING\].*(?:error|failed|full|not flushed)',
        }.items():
            if re.search(pattern,msg,re.I):days[day][label]+=1
        for name in re.findall(r'\b(?:ImportError|SyntaxError|NameError|TypeError|ValueError|RuntimeError|OperationalError|ConnectionError|TimeoutError)\b',msg):
            days[day][name]+=1
        versions[day].update(re.findall(r'\b(?:paper-adaptive|quote-markout|research|gate-v\d|approved-model-gate)[A-Za-z0-9_.-]*',msg))
        for filename,number in re.findall(r'File "(/(?:home/ubuntu/easystock[^"\n]*|opt/easystock-guardian)/[^"\n]+\.py)", line (\d+)',msg):
            frames[day][filename+':'+number]+=1
    return {'returncode':code,'first_retained':first,'last_retained':last,
            'tail_limit':15000,'note':'Counts are log matches, not trade counts; missing retained logs cannot prove no execution.',
            'by_day':dict(days),'versions_by_day':{d:sorted(v) for d,v in versions.items() if v},
            'traceback_locations_by_day':dict(frames)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',default='/home/ubuntu/easystock')
    parser.add_argument('--since',default='2026-09-10')
    args=parser.parse_args();root=Path(args.root).resolve()
    datetime.strptime(args.since,'%Y-%m-%d')
    result={'generated_at':datetime.now(TPE).isoformat(),'root':str(root),'since':args.since}
    result['git']={key:command(['git','-C',str(root),*cmd])[1].strip() for key,cmd in
                   [('head',['rev-parse','HEAD']),('branch',['branch','--show-current']),('tracked_changes',['diff','--name-only','HEAD'])]}
    files=['intraday_live.py','position_manager.py','daytrade_learning/model_runtime.py',
           'daytrade_learning/model_status.py','learning_status.py','learning_cycle.py']
    result['runtime_files']={f:fingerprint(root/f) for f in files}
    env=env_values(root/'.env');result['service_settings']={};result['units']={}
    env_paths=set()
    for name in UNITS:
        unit='easystock-'+name+'.service'
        properties=['ActiveState','SubState','Result','ExecMainStatus','Restart','NRestarts',
                    'FragmentPath','EnvironmentFiles','ExecStart','Environment']
        rc,out=command(['systemctl','show','--no-pager',unit,*['-p'+p for p in properties]])
        data=dict(line.split('=',1) for line in out.splitlines() if '=' in line)
        effective=dict(env)
        inline=data.pop('Environment','')
        try:
            for item in shlex.split(inline):
                key,sep,value=item.partition('=')
                if sep and key in SAFE:effective[key]=value
        except ValueError:pass
        for p in re.findall(r'(/[^\s;()]+)',data.pop('EnvironmentFiles','')):
            env_paths.add(p);effective.update(env_values(Path(p)))
        start=data.pop('ExecStart','')
        data['script_paths']=re.findall(r'/[^\s;{}]+\.py\b',start)
        data['research_flags']=re.findall(r'--(?:collect|train|publish|gemini|retry-ai)\b',start)
        data['query_returncode']=rc
        result['units'][unit]=data;result['service_settings'][unit]=effective
        rc,timer=command(['systemctl','show','--no-pager','easystock-'+name+'.timer',
                          '-pActiveState','-pUnitFileState','-pNextElapseUSecRealtime','-pTimersCalendar'])
        result['units']['easystock-'+name+'.timer']=dict(line.split('=',1) for line in timer.splitlines() if '=' in line)
    result['environment_files_examined']=sorted(env_paths)
    active=result['service_settings']['easystock-intraday.service']
    model_path=active.get('AI_PAPER_MODEL_PATH')
    if model_path:
        p=Path(model_path);result['configured_model']=model_metadata(p if p.is_absolute() else root/p)
    data=Path(active.get('LEARNING_DATA_DIR','/home/ubuntu/easystock-learning-data'))
    result['daily_journals']=[]
    for path in sorted(data.glob('journal-*.jsonl')):
        if path.name[8:18]<args.since:continue
        counts=Counter();versions=set();bad=0;bytes_read=0
        try:
            with path.open() as f:
                for line in f:
                    bytes_read+=len(line)
                    if bytes_read>50_000_000:break
                    try:
                        row=json.loads(line);counts[str(row.get('kind','unknown'))]+=1
                        v=row.get('data',{}).get('model_version')
                        if isinstance(v,str):versions.add(v)
                    except (ValueError,TypeError,AttributeError):bad+=1
            result['daily_journals'].append({'date':path.name[8:18],'counts':dict(counts),'corrupt_lines':bad,
                                              'model_versions':sorted(versions),'truncated':bytes_read>50_000_000})
        except OSError:result['daily_journals'].append({'path':str(path),'unreadable':True})
    roots=[p for p in root.parent.glob('easystock*') if p.is_dir()
           and re.search(r'learning|history|paper|model',p.name) and 'venv' not in p.name]
    roots=list(dict.fromkeys([data,*roots]));found=[];visited=0
    for base in roots:
        for directory,dirs,names in os.walk(base):
            depth=len(Path(directory).relative_to(base).parts)
            dirs[:]=[d for d in dirs if not d.startswith('.') and d not in {'node_modules','bars','kbars','archive','raw','__pycache__'} and depth<5]
            for name in names:
                visited+=1
                if visited>20000:break
                if name.endswith('.json') and re.search(r'model|candidate|training|status|report',name,re.I):
                    p=Path(directory)/name
                    try:found.append((p.stat().st_mtime,p))
                    except OSError:pass
            if visited>20000:break
        if visited>20000:break
    result['model_and_training_files']=[m for _,p in sorted(found,reverse=True)[:100] if (m:=model_metadata(p))]
    result['metadata_scan']={'roots':[str(p) for p in roots],'file_limit':20000,'truncated':visited>20000,
                             'note':'mtime and version-name dates do not prove deployment dates; weights omitted.'}
    dbpath=Path(active.get('EASYSTOCK_ADMIN_DB','/home/ubuntu/easystock-admin/state.sqlite'))
    try:
        con=sqlite3.connect(dbpath.resolve().as_uri()+'?mode=ro',uri=True,timeout=5)
        con.execute('PRAGMA query_only=ON')
        tables={r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        result['paper_database']={'tables':sorted(t for t in tables if t.startswith('paper_'))}
        if 'paper_trade_positions' in tables:
            result['paper_database']['position_columns']=[r[1] for r in con.execute('PRAGMA table_info(paper_trade_positions)')]
            result['paper_database']['open_count']=con.execute('SELECT COUNT(*) FROM paper_trade_positions').fetchone()[0]
        if 'paper_trade_logs' in tables:
            cols={r[1] for r in con.execute('PRAGMA table_info(paper_trade_logs)')}
            fields=[k for k in ('date','net_pnl','costs','trades_count') if k in cols]
            if 'date' in fields:
                result['paper_database']['daily_results']=[dict(zip(fields,r)) for r in con.execute(
                    'SELECT '+','.join(fields)+' FROM paper_trade_logs WHERE date>=? ORDER BY date',(args.since,))]
        con.close()
    except (OSError,sqlite3.Error):result['paper_database']={'unavailable_or_schema_error':True}
    result['guardian_files']={f:{'installed':fingerprint(Path('/opt/easystock-guardian')/f),
                                    'repo':fingerprint(root/'ops/guardian'/f)} for f in ('live.py','common.py')}
    result['logs']={f'easystock-{name}.service':log_summary(f'easystock-{name}.service',args.since)
                    for name in ('intraday','learning','learning-train','paper-train','guardian')}
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
