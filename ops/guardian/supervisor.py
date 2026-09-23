import ast
import datetime as dt
import fcntl
import json
import re
import subprocess
import sys
import time
from common import ROOT, STATE, PYTHON, APP, SERVICE, now, classify, read_json, write_json, digest
from notify import send, retry_pending

def snapshot():
    try:
        run = subprocess.run([PYTHON,str(ROOT/'live.py'),'snapshot'],capture_output=True,text=True,timeout=35)
        if run.returncode:
            raise RuntimeError('Production health adapter failed')
        return json.loads(run.stdout)
    except Exception as exc:
        return {'read_error':type(exc).__name__}

def calendar():
    cal=read_json(STATE/f'calendar-{now().year}.json')
    if cal:
        conf=read_json('/etc/easystock-guardian/config.json',{})
        cal['closed']=sorted(set(cal['closed'])|set(conf.get('extra_closed_dates',[])))
    return cal

def clean_logs():
    raw = subprocess.run(['journalctl','-u',SERVICE,'--since','-15 minutes','--no-pager','-n','100','-o','cat'],capture_output=True,text=True,timeout=10).stdout
    lines = []
    # Only runtime exception categories, stack frames and service lifecycle lines.
    for line in raw.splitlines():
        if not re.search(r'Traceback|File "/home/ubuntu/easystock/|(?:RuntimeError|ValueError|SyntaxError|NameError|TypeError):|Main process exited|Failed with result|Started Easystock',line):
            continue
        line = re.sub(r'(?:sk-[\w-]+|Bearer\s+\S+|https?://\S+)', '[REDACTED]',line)
        line = re.sub(r'(?i)(token|secret|password|api_key|authorization)\s*[=:]\s*[^ ,;]+',r'\1=[REDACTED]',line)
        lines.append(line[:300])
    return '\n'.join(lines)[-5000:]

def publish(payload):
    try:
        run = subprocess.run([PYTHON,str(ROOT/'live.py'),'publish'],input=json.dumps(payload),capture_output=True,text=True,timeout=20)
        return run.returncode == 0
    except subprocess.TimeoutExpired:
        return False

def tick():
    retry_pending()
    conf = read_json('/etc/easystock-guardian/config.json')
    stamp = now()
    s = snapshot()
    cal = calendar()
    errors = classify(s,stamp,cal)
    scheduled = bool(cal and stamp.weekday()<5 and stamp.date().isoformat() not in cal.get('closed',[]) and '08:40'<=stamp.strftime('%H:%M')<='14:30')
    health = {'checked_at':stamp.isoformat(),'version':1,'issues':errors,'service':s.get('service_active','unknown'),
              'status':'degraded' if errors else ('healthy' if scheduled else 'outside_session'),'intraday_date':s.get('scan_date'),
              'automatic_repair':'bounded_runbooks','calendar_year':cal.get('year') if cal else None}
    write_json(STATE/'health.json', {**health,'snapshot':s})
    data = read_json(STATE/'monitor.json',{'incidents':{},'jobs_by_day':{}})
    key = stamp.date().isoformat()+':'+','.join(errors)
    if errors:
        incident = data['incidents'].setdefault(key,{'id':stamp.strftime('%Y%m%d%H%M%S'),'first_seen':stamp.isoformat(),'count':0,'status':'observing','issues':errors})
        incident['count']+=1;incident['last_seen']=stamp.isoformat();incident['healthy_count']=0
        if incident['count'] >= 2:
            incident['status'] = 'detected' if incident['status']=='observing' else incident['status']
            send('【當沖守護】偵測到異常\n'+', '.join(errors)+'\n正在核對服務、資料時間與模擬帳本。',incident['id']+':detected')
            day = stamp.date().isoformat()
            pending = read_json(STATE/'worker-state.json',{})
            worker_active = subprocess.run(['systemctl','is-active','--quiet','easystock-guardian-worker.service']).returncode==0
            if (conf.get('enabled') and not worker_active and not incident.get('job_started')
                    and data['jobs_by_day'].get(day,0) < conf['max_jobs_per_day']):
                job = {'id':incident['id'],'incident_key':key,'created_at':stamp.isoformat(),'issues':errors,'snapshot':s,'logs':clean_logs()}
                write_json(STATE/'pending.json',job)
                subprocess.run(['systemctl','start','--no-block','easystock-guardian-worker.service'],check=True,timeout=10)
                incident['job_started']=True;incident['status']='diagnosing'
                data['jobs_by_day'][day]=data['jobs_by_day'].get(day,0)+1
            elif data['jobs_by_day'].get(day,0) >= conf['max_jobs_per_day'] and not incident.get('job_started'):
                incident['status']='daily_limit'
                send('【當沖守護】已達今天自動診斷次數上限，保留異常現場，等待人工處理。',incident['id']+':limit')
    # Require three actual in-session healthy checks; a market close is not a repair.
    for old_key, inc in data['incidents'].items():
        if old_key==key and errors:continue
        if inc.get('status') in ('observing','resolved','expired'):continue
        in_session = '08:58'<=stamp.strftime('%H:%M')<'13:00'
        worker = read_json(STATE/'worker-state.json',{})
        confirmed = (not errors and not s.get('read_error') and in_session
                     and s.get('scan_date')==stamp.date().isoformat()
                     and worker.get('id')==inc['id'] and worker.get('status')=='awaiting_verification')
        if confirmed:
            inc['healthy_count']=inc.get('healthy_count',0)+1
            if inc['healthy_count']>=3:
                inc['status']='resolved'
                send('【當沖守護】修復驗證通過：連續 3 次確認今日快照更新、服務正常、模擬帳本一致。',inc['id']+':resolved')
        else:
            inc['healthy_count']=0
        if not old_key.startswith(stamp.date().isoformat()) and inc.get('status')!='resolved':
            inc['status']='expired'
    # Bound stored history, without dropping pending/active incidents.
    data['incidents']=dict(list(data['incidents'].items())[-100:])
    data['jobs_by_day']=dict(list(data['jobs_by_day'].items())[-32:])
    write_json(STATE/'monitor.json',data)
    worker=read_json(STATE/'worker-state.json',{})
    health['last_repair_status']=worker.get('status','none')
    health['last_repair_at']=worker.get('finished_at')
    if not publish(health):
        send('【當沖守護】健康狀態無法發布至 Firebase；外部監測可能隨後報警。',stamp.strftime('%Y%m%d%H')+':publish-failed')
    print(json.dumps(health,ensure_ascii=False))

if __name__=='__main__':
    STATE.mkdir(parents=True,exist_ok=True)
    with (STATE/'monitor.lock').open('w') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise SystemExit(0)
        tick()
