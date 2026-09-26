#!/usr/bin/env python3
"""Read-only VM inventory. Never prints credentials, environment values or keys."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(sys.argv[1] if len(sys.argv)>1 else '/home/ubuntu/easystock')
FILES = ['intraday_live.py','position_manager.py','market_risk.py','paper_account.py',
         'premarket_ai.py','daytrade_learning/model_runtime.py','daytrade_learning/features.py',
         'daytrade_learning/research.py','learning_eod.py','learning_cycle.py','learning_status.py']
UNITS = ['easystock-intraday.service','easystock-intraday.timer',
         'easystock-learning.service','easystock-learning-train.service',
         'easystock-research-cycle.timer']


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def command(args):
    p = subprocess.run(args,cwd=ROOT,capture_output=True,text=True,timeout=15)
    return {'returncode':p.returncode,'output':p.stdout.strip()}


def main():
    report = {'root':str(ROOT),'git':command(['git','rev-parse','HEAD']),
              'tracked_changes':command(['git','status','--short','--untracked-files=no']),
              'files':{},'services':{}}
    for name in FILES:
        live, source = digest(ROOT/name), digest(ROOT/'vm_runtime'/name)
        report['files'][name] = {'live_sha256':live,'repo_sha256':source,'same':live is not None and live==source}
    for unit in UNITS:
        report['services'][unit] = command(['systemctl','show',unit,'--property=ActiveState,SubState,FragmentPath,UnitFileState'])
    report['sensitive_file_presence'] = {name:(ROOT/name).is_file() for name in ('.env','client_secret.json')}
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__ == '__main__':
    main()
