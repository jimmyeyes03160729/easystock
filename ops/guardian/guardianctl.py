#!/usr/bin/env python3
import json
import subprocess
import sys
from common import ROOT, STATE, PYTHON, read_json, write_json

command=sys.argv[1] if len(sys.argv)>1 else 'status'
if command=='status':
    for name in ('health','worker-state','api-budget','installation-smoke','recovery-exercise'):
        print(name,json.dumps(read_json(STATE/(name+'.json'),{}),ensure_ascii=False,indent=2))
elif command in ('pause','resume'):
    path='/etc/easystock-guardian/config.json'
    config=read_json(path);config['enabled']=command=='resume';write_json(path,config)
    print('Automatic recovery', 'enabled' if config['enabled'] else 'paused; monitoring continues. An in-flight recovery is allowed to finish safely.')
elif command=='test':
    for script in ('test_guardian.py','test_open_price_update.py'):
        subprocess.run([PYTHON,str(ROOT/script)],check=True)
elif command=='check':
    subprocess.run(['systemctl','start','easystock-guardian.service'],check=True)
else:
    raise SystemExit('Usage: guardianctl.py status|pause|resume|test|check')
