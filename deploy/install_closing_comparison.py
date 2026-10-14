"""Hash-guarded recoverable install; engine must be inactive before code sync."""
import argparse
from datetime import datetime,timezone
import hashlib,json,shutil,subprocess
from pathlib import Path

ROOT=Path('/home/ubuntu/easystock')
CODE={'intraday_live.py','vm_runtime/intraday_live.py','runway_v2/lanes.py','runway_v2/replay.py',
      'runway_v2/closing_pool.py','runway_v2/closing_experiment.py','runway_v2/closing_audit.py',
      'eight_methods/feed.py','eight_methods/closing_inputs.py','eight_methods/company_shares.py',
      'vm_runtime/esun_marketdata/provider.js','vm_runtime/esun_marketdata/equity_snapshot.js'}
UNITS={f'deploy/easystock-{name}.{kind}' for name in ('company-shares','b1-closing-freeze','b1-closing-audit') for kind in ('service','timer')}
DROPIN='deploy/zz-b1-closing-shadow.conf'
ALLOWED=CODE|UNITS|{DROPIN}

def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def target(name):
    if name in UNITS:return Path('/etc/systemd/system')/Path(name).name
    if name==DROPIN:return Path('/etc/systemd/system/easystock-intraday.service.d')/Path(name).name
    return ROOT/name

def install(stage):
    if subprocess.run(['systemctl','is-active','--quiet','easystock-intraday.service']).returncode==0:
        raise RuntimeError('intraday_engine_must_be_inactive')
    stage=Path(stage);manifest=json.loads((stage/'manifest.json').read_text(encoding='utf-8'))
    if set(manifest)!=ALLOWED:raise ValueError('unexpected_allowlist')
    for name,meta in manifest.items():
        src,dst=stage/name,target(name)
        if digest(src)!=meta['new_sha256']:raise ValueError('staged_hash_changed:'+name)
        if dst.is_symlink():raise ValueError('symlink_target:'+name)
        actual=digest(dst) if dst.exists() else None
        if actual!=meta['original_sha256']:raise ValueError('production_source_changed:'+name)
    backup=Path('/home/ubuntu/easystock-maintenance/closing-comparison')/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup.mkdir(parents=True,mode=0o700);receipt={}
    for name,meta in manifest.items():
        dst=target(name)
        if dst.exists():
            original=backup/name;original.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(dst,original)
        dst.parent.mkdir(parents=True,exist_ok=True);tmp=dst.with_suffix(dst.suffix+'.install-tmp')
        shutil.copy2(stage/name,tmp);tmp.chmod(0o644);tmp.replace(dst)
        if name in CODE:shutil.chown(dst,user='ubuntu',group='ubuntu')
        receipt[name]={**meta,'target':str(dst),'installed_sha256':digest(dst)}
    (backup/'receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    shutil.chown(backup,user='ubuntu',group='ubuntu');shutil.chown(backup/'receipt.json',user='ubuntu',group='ubuntu')
    subprocess.run(['systemctl','daemon-reload'],check=True)
    subprocess.run(['systemctl','enable','--now',*[f'easystock-{n}.timer' for n in ('company-shares','b1-closing-freeze','b1-closing-audit')]],check=True)
    print(json.dumps({'backup':str(backup),'files':len(receipt),'engine_restarted':False}))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage');a=p.parse_args();install(a.stage)
