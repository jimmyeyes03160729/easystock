"""Guarded source-only repair; preserves immutable evidence and does not call brokers."""
import hashlib,json,shutil,subprocess,sys
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path('/home/ubuntu/easystock')
NAMES={'eight_methods/feed.py','eight_methods/closing_inputs.py','runway_v2/closing_pool.py','vm_runtime/esun_marketdata/provider.js'}
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def evidence():
    root=Path('/home/ubuntu/easystock-b1-closing')
    return {str(p):digest(p) for folder in ('observations','pools') for p in sorted((root/folder).glob('*.json'))}
def install(stage):
    stage=Path(stage);manifest=json.loads((stage/'manifest.json').read_text())
    if set(manifest)!=NAMES:raise ValueError('invalid_allowlist')
    if subprocess.run(['systemctl','is-active','--quiet','easystock-intraday.service']).returncode==0:
        raise RuntimeError('engine_must_be_inactive')
    for name,m in manifest.items():
        if (ROOT/name).is_symlink() or digest(ROOT/name)!=m['old'] or digest(stage/name)!=m['new']:
            raise ValueError('source_hash_changed:'+name)
    before=evidence()
    backup=Path('/home/ubuntu/easystock-maintenance/closing-freshness')/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup.mkdir(parents=True,mode=0o700)
    for name in NAMES:
        dst=ROOT/name;save=backup/name;save.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(dst,save)
        temp=dst.with_suffix(dst.suffix+'.freshness-tmp');shutil.copy2(stage/name,temp)
        temp.chmod(0o644);shutil.chown(temp,user='ubuntu',group='ubuntu');temp.replace(dst)
    subprocess.run([str(ROOT/'.venv/bin/python'),'-m','py_compile',*[str(ROOT/n) for n in NAMES if n.endswith('.py')]],check=True)
    subprocess.run(['node','--check',str(ROOT/'vm_runtime/esun_marketdata/provider.js')],check=True)
    subprocess.run(['systemctl','restart','easystock-esun-marketdata.service'],check=True)
    after=evidence()
    receipt={'files':manifest,'before':before,'after':after,'evidence_unchanged':before==after,'broker_orders':0}
    (backup/'receipt.json').write_text(json.dumps(receipt,indent=2))
    if before!=after:raise RuntimeError('immutable_evidence_changed')
    print(json.dumps({'backup':str(backup),'files':len(NAMES),'evidence_unchanged':True}))
if __name__=='__main__':install(sys.argv[1])
