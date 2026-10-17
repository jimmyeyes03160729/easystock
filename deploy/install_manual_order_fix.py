"""Recoverable source sync and graceful web-worker reload. Never calls a broker."""
import argparse,hashlib,json,shutil,sqlite3,subprocess
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path('/home/ubuntu/easystock')
NAMES={p+n for p in ('easystock_admin/',)
       for n in ('order_service.py','web.py','live_console.py','static/order.js')}
DB=Path('/home/ubuntu/easystock-admin/state.sqlite')
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def order_state(db):
    rows=db.execute('SELECT * FROM order_requests ORDER BY client_order_id').fetchall()
    return {'rows':len(rows),'sha256':hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest()}

def install(stage):
    stage=Path(stage);manifest=json.loads((stage/'manifest.json').read_text())
    if set(manifest)!=NAMES:raise ValueError('unexpected_allowlist')
    for name,meta in manifest.items():
        p=ROOT/name
        if p.is_symlink() or digest(p)!=meta['old'] or digest(stage/name)!=meta['new']:
            raise ValueError('production_source_changed:'+name)
    with sqlite3.connect(DB.resolve().as_uri()+'?mode=ro',uri=True) as db:
        if db.execute("SELECT count(*) FROM order_requests WHERE status='submitting'").fetchone()[0]:
            raise RuntimeError('An order is in progress; do not reload its worker')
        before=order_state(db)
        backup=Path('/home/ubuntu/easystock-maintenance/manual-order-fix')/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        backup.mkdir(parents=True,mode=0o700)
        with sqlite3.connect(backup/'admin-state.sqlite') as target:db.backup(target)
    (backup/'admin-state.sqlite').chmod(0o600)
    for name in manifest:
        dst=ROOT/name;old=backup/name;old.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(dst,old)
        temp=dst.with_suffix(dst.suffix+'.order-fix-tmp');shutil.copy2(stage/name,temp)
        temp.chmod(0o644);shutil.chown(temp,user='ubuntu',group='ubuntu');temp.replace(dst)
    subprocess.run(['/home/ubuntu/easystock/.venv/bin/python','-m','py_compile',
        *[str(ROOT/n) for n in sorted(NAMES) if n.endswith('.py')]],check=True)
    subprocess.run(['systemctl','kill','--kill-who=main','--signal=HUP','easystock-line-stock-bot.service'],check=True)
    with sqlite3.connect(DB.resolve().as_uri()+'?mode=ro',uri=True) as db:after=order_state(db)
    receipt={'files':manifest,'order_requests_before':before,'order_requests_after':after,
             'orders_unchanged':before==after,'reload':'graceful_HUP','broker_calls':0}
    (backup/'receipt.json').write_text(json.dumps(receipt,indent=2))
    print(json.dumps({'backup':str(backup),'files':len(manifest),'orders_unchanged':before==after,'broker_calls':0}))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage');a=p.parse_args();install(a.stage)
