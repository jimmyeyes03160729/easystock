"""Recoverable, allowlisted code sync. Never enables the dual strategy gate.

Run on VM with --source an agent-created private bundle. Only the read-only
E.SUN collector is restarted; the intraday engine must already be inactive.
"""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT=Path('/home/ubuntu/easystock')
BASES={
 'intraday_live.py':'32be04d7e7dad06197d6014a2f17838918fd55af',
 'vm_runtime/intraday_live.py':'32be04d7e7dad06197d6014a2f17838918fd55af',
 'runway_v2/lanes.py':'89139fc6d524d5107cc9f24f9fd74ad99702cb76',
 'runway_v2/replay.py':'544329afd7fb2b870dab1c3bc653656143232fb4',
 'vm_runtime/esun_marketdata/provider.js':'3a37190e0ade76d23d387d9b5fa93d44789c2f42',
 'market_data/dual_books.py':None,
 'vm_runtime/esun_marketdata/books.js':None,
}


def main(source,expected_receipt=None):
    if subprocess.run(['systemctl','is-active','--quiet','easystock-intraday.service']).returncode==0:
        raise ValueError('intraday_must_be_inactive')
    expected=None
    if expected_receipt:
        if not expected_receipt.resolve().is_relative_to(Path('/home/ubuntu/easystock-maintenance/dual-books')):
            raise ValueError('invalid_receipt_path')
        expected=json.loads(expected_receipt.read_text(encoding='utf-8'))['code_sha256']
        if set(expected)!=set(BASES):raise ValueError('invalid_receipt_targets')
    prepared=[];collector_changed=False
    for name,base in BASES.items():
        src=source/Path(name).name;dst=ROOT/name
        if not src.is_file() or src.is_symlink():raise ValueError('missing_bundle_file')
        if not dst.resolve().is_relative_to(ROOT.resolve()) or dst.is_symlink():raise ValueError('unsafe_destination')
        digest=hashlib.sha256(src.read_bytes()).hexdigest()
        if dst.exists():
            current_sha=hashlib.sha256(dst.read_bytes()).hexdigest()
            if expected:
                if current_sha!=expected[name]:raise ValueError('destination_not_expected_receipt:'+name)
            else:
                blob=subprocess.check_output(['git','hash-object',str(dst)],cwd=ROOT,text=True).strip()
                if blob!=base:raise ValueError('destination_not_expected_base:'+name)
            if name in ('vm_runtime/esun_marketdata/provider.js','vm_runtime/esun_marketdata/books.js') and current_sha!=digest:
                collector_changed=True
        elif base is not None:raise ValueError('missing_destination:'+name)
        elif name=='vm_runtime/esun_marketdata/books.js':collector_changed=True
        prepared.append((name,src,dst,digest))
    backup=Path('/home/ubuntu/easystock-maintenance/dual-books')/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup.mkdir(parents=True,exist_ok=False)
    installed=[]
    try:
        for name,src,dst,digest in prepared:
            if dst.exists():
                saved=backup/name;saved.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(dst,saved)
            fd,temporary=tempfile.mkstemp(prefix=dst.name+'.dual-',dir=dst.parent)
            with os.fdopen(fd,'wb') as f:f.write(src.read_bytes())
            os.chmod(temporary,0o644);os.replace(temporary,dst);installed.append((name,dst))
            assert hashlib.sha256(dst.read_bytes()).hexdigest()==digest
        subprocess.run(['node','--check',str(ROOT/'vm_runtime/esun_marketdata/provider.js')],check=True)
        subprocess.run(['node','--check',str(ROOT/'vm_runtime/esun_marketdata/books.js')],check=True)
        if collector_changed:subprocess.run(['sudo','systemctl','restart','easystock-esun-marketdata.service'],check=True)
    except Exception:
        # Restore only overwritten allowlisted targets. New inert modules remain
        # recoverable rather than deleting anything during automatic rollback.
        for name,dst in reversed(installed):
            saved=backup/name
            if saved.exists():shutil.copy2(saved,dst)
        if collector_changed:subprocess.run(['sudo','systemctl','restart','easystock-esun-marketdata.service'],check=False)
        raise
    receipt=dict(backup=str(backup),code_sha256={n:h for n,_s,_d,h in prepared},
        collector_restarted=collector_changed,intraday_started=False,dual_mode_enabled=False,
        live_gate_passed=False,git_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip())
    (backup/'receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    print(json.dumps(receipt),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True)
    p.add_argument('--expected-receipt',type=Path)
    a=p.parse_args();main(a.source.resolve(),a.expected_receipt)
