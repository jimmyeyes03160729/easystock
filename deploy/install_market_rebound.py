"""Install a reviewed, hashed paper guard while the intraday engine is inactive."""
import argparse,hashlib,json,shutil,subprocess
from datetime import datetime,timezone
from pathlib import Path

NAMES={'intraday_live.py','vm_runtime/intraday_live.py','runway_v2/lanes.py','market_data/diagnostics.py','market_rebound.py'}
ROOT=Path('/home/ubuntu/easystock')
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def install(stage):
    state=subprocess.check_output(['systemctl','show','easystock-intraday.service','-p','ActiveState','--value'],text=True).strip()
    if state!='inactive':raise RuntimeError('Engine must be inactive; no restart during session')
    stage=Path(stage);manifest=json.loads((stage/'manifest.json').read_text())
    if set(manifest)!=NAMES:raise ValueError('unexpected_allowlist')
    dropin=stage/'zz-market-rebound.conf'
    if dropin.read_text()!='[Service]\nEnvironment=MARKET_REBOUND_MODE=1\n':raise ValueError('unexpected_dropin')
    for name,meta in manifest.items():
        p=ROOT/name
        if p.is_symlink() or (digest(p) if p.exists() else None)!=meta['old'] or digest(stage/name)!=meta['new']:
            raise ValueError('source_changed:'+name)
    backup=Path('/home/ubuntu/easystock-maintenance/market-rebound')/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup.mkdir(parents=True,mode=0o700)
    target=Path('/etc/systemd/system/easystock-intraday.service.d/zz-market-rebound.conf')
    if target.exists():shutil.copy2(target,backup/'previous-dropin.conf')
    for name,meta in manifest.items():
        p=ROOT/name
        if p.exists():
            old=backup/name;old.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,old)
        temp=p.with_suffix(p.suffix+'.rebound-tmp');shutil.copy2(stage/name,temp)
        temp.chmod(0o644);shutil.chown(temp,user='ubuntu',group='ubuntu');temp.replace(p)
        if digest(p)!=meta['new']:raise RuntimeError('installed_hash_mismatch')
    target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(dropin,target);target.chmod(0o644)
    (backup/'receipt.json').write_text(json.dumps(manifest,indent=2))
    shutil.chown(backup,user='ubuntu',group='ubuntu')
    subprocess.run(['systemctl','daemon-reload'],check=True)
    print(json.dumps({'backup':str(backup),'files':len(manifest),'engine_restarted':False}))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage');a=p.parse_args();install(a.stage)
