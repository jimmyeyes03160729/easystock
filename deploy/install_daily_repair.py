"""Install only an explicitly hashed repair package, with recoverable backups."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import shutil

ALLOWED={'runway_v2/replay.py','market_data/dual_books.py','intraday_live.py',
    'daytrade_learning/runtime.py','daytrade_learning/research.py','daytrade_learning/a_signal_learning.py',
    'market_data/opening_observations.py','eight_methods/feed.py','vm_runtime/esun_marketdata/provider.js'}


def digest(path,normalized=False):
    b=path.read_bytes()
    return hashlib.sha256(b.replace(b'\r\n',b'\n') if normalized else b).hexdigest()


def install(stage,root,backup_root):
    stage=Path(stage);root=Path(root)
    manifest=json.loads((stage/'manifest.json').read_text())
    if set(manifest)!=ALLOWED:raise ValueError('unexpected_allowlist')
    # Validate every original and staged source before the first mutation.
    for name,meta in manifest.items():
        dst=root/name;src=stage/name
        if digest(src)!=meta['new_sha256']:raise ValueError('staged_hash_mismatch: '+name)
        expected=meta['original_normalized_sha256']
        if expected is None:
            if dst.exists():raise ValueError('new_target_exists: '+name)
        elif not dst.exists() or digest(dst,True)!=expected:
            raise ValueError('production_source_changed: '+name)
        if dst.is_symlink():raise ValueError('symlink_target: '+name)
    backup=Path(backup_root)/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup.mkdir(parents=True,mode=0o700)
    receipt={}
    for name,meta in manifest.items():
        dst=root/name;src=stage/name
        if dst.exists():
            original=backup/name;original.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(dst,original)
        dst.parent.mkdir(parents=True,exist_ok=True)
        temp=dst.with_suffix(dst.suffix+'.repair-tmp');shutil.copy2(src,temp)
        temp.chmod(0o644);temp.replace(dst)
        receipt[name]=dict(meta,installed_sha256=digest(dst))
    (backup/'receipt.json').write_text(json.dumps(receipt,indent=2))
    print(json.dumps({'backup':str(backup),'files':len(receipt)}))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage');p.add_argument('--root',default='/home/ubuntu/easystock')
    p.add_argument('--backup',default='/home/ubuntu/easystock-maintenance/daily-repair');a=p.parse_args()
    install(a.stage,a.root,a.backup)
