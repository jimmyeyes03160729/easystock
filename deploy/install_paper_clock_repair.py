"""Source-only, hash-guarded off-hours repair. No broker calls or ledger migration."""
import argparse,hashlib,json,shutil,sqlite3,subprocess
from datetime import datetime,timezone,timedelta
from pathlib import Path
ROOT=Path('/home/ubuntu/easystock')
BASE={'intraday_live.py','position_manager.py','paper_ledger.py','paper_account.py','paper_entry_policy.py','runtime_clock.py','easystock_admin/store.py'}
ALLOWED=BASE|{'vm_runtime/'+n for n in BASE}|{'market_data/a_candidates.py'}
def digest(p):return hashlib.sha256(p.read_bytes().replace(b'\r\n',b'\n')).hexdigest() if p.exists() else None
def fills(path):
    with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True) as c:
        return {t:hashlib.sha256(json.dumps(c.execute('SELECT * FROM '+t+' ORDER BY rowid').fetchall(),default=str).encode()).hexdigest()
            for t in ('paper_trade_fills','paper_trade_positions','paper_trade_logs','paper_trade_settings','order_requests')}
def install(stage):
    stage=Path(stage);m=json.loads((stage/'manifest.json').read_text())
    if set(m)!=ALLOWED:raise ValueError('invalid_allowlist')
    at=datetime.now(timezone(timedelta(hours=8))).strftime('%H:%M')
    if '09:00'<=at<'13:30':raise RuntimeError('off_hours_only')
    if subprocess.run(['systemctl','is-active','--quiet','easystock-intraday.service']).returncode==0:raise RuntimeError('engine_must_be_inactive')
    for n,v in m.items():
        if (ROOT/n).is_symlink() or digest(ROOT/n) not in v['allowed_old'] or digest(stage/n)!=v['new']:raise ValueError('source_drift:'+n)
    db=Path('/home/ubuntu/easystock-admin/state.sqlite');before=fills(db)
    backup=Path('/home/ubuntu/easystock-maintenance/paper-clock-repair')/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup.mkdir(parents=True,mode=0o700)
    with sqlite3.connect(db.resolve().as_uri()+'?mode=ro',uri=True) as c,sqlite3.connect(backup/'state.sqlite') as dst:c.backup(dst)
    (backup/'state.sqlite').chmod(0o600)
    for n in sorted(m):
        dst=ROOT/n
        if dst.exists():
            save=backup/n;save.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(dst,save)
        dst.parent.mkdir(parents=True,exist_ok=True)
        temp=dst.with_suffix('.repair-tmp');shutil.copy2(stage/n,temp);temp.chmod(0o644);shutil.chown(temp,user='ubuntu',group='ubuntu');temp.replace(dst)
    subprocess.run([str(ROOT/'.venv/bin/python'),'-m','py_compile',*[str(ROOT/n) for n in sorted(m)]],check=True)
    after=fills(db)
    receipt={'before':before,'after':after,'ledgers_unchanged':before==after,'files':{n:digest(ROOT/n) for n in m},'engine_restarted':False,'broker_calls':0}
    (backup/'receipt.json').write_text(json.dumps(receipt,indent=2))
    if before!=after:raise RuntimeError('ledger_changed')
    print(json.dumps({'backup':str(backup),'files':len(m),'ledgers_unchanged':True,'engine_restarted':False,'broker_calls':0}))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage');a=p.parse_args();install(a.stage)
