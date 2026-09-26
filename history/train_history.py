"""Resume cached offline training when the archive changes; never promote."""
from datetime import datetime
import fcntl
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import collector_core as core

DATA=Path('/home/ubuntu/easystock-history-expanded-data')
OUT=Path('/home/ubuntu/easystock-history-pilot-output')

def main():
    now=datetime.now(core.TPE)
    if 4<=now.hour<22:return 0  # Never compete with daytime operation.
    if shutil.disk_usage(DATA).free<5*1024**3:return 0
    with (DATA/'download.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return 1
        h=hashlib.sha256((DATA/'plan.json').read_bytes())
        for p in sorted((DATA/'raw').glob('*/*.json.gz')):
            s=p.stat();h.update(f'{p.name}:{p.parent.name}:{s.st_size}:{s.st_mtime_ns}'.encode())
        marker=OUT/'auto-trained.json'
        if marker.exists() and core.load(marker).get('fingerprint')==h.hexdigest():return 0
        result=subprocess.run([sys.executable,'/home/ubuntu/easystock-history-pilot-r1/pilot.py','--run'],timeout=5*3600)
        if result.returncode:return 1
        state=core.load(OUT/'status.json')
        if state.get('state')!='completed':return 1
        core.save(marker,{'fingerprint':h.hexdigest(),'trained_at':datetime.now(core.TPE).isoformat(),'model_applied':False})
        return 0

if __name__=='__main__':sys.exit(main())
