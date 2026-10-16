"""Read-only inventory for chart integration; never reads secrets or account files."""
import json,subprocess
from pathlib import Path
home=Path('/home/ubuntu')
print('Data directories:',[p.name for p in home.iterdir() if p.is_dir() and 'easystock' in p.name])
for pattern in ['easystock-intraday*','easystock-research*','easystock-history*','easystock-market*']:
    print(subprocess.run(['systemctl','list-units','--all','--no-pager','--no-legend',pattern],capture_output=True,text=True).stdout)
for root in [home/'easystock',home/'easystock-learning-data',home/'easystock-market-data',home/'easystock-history-expanded-data']:
    print('ROOT',root,'exists',root.exists())
    if not root.exists():continue
    print('Directories:',[p.name for p in root.iterdir() if p.is_dir() and not p.name.startswith('.')][:30])
    found=[]
    for pattern in ['**/bars/2026-10-16/3231.json','**/bars/2026-10-16/2344.json','**/*2026-10-16*','**/*tick*']:
        for p in root.glob(pattern):
            if any(part in {'.git','.venv','node_modules','__pycache__'} for part in p.parts):continue
            found.append(str(p))
            if len(found)>=18:break
        if len(found)>=18:break
    print('Market cache paths:',found)
    for p in [root/'bars/2026-10-16/3231.json',root/'data/bars/2026-10-16/3231.json']:
        if p.exists():
            d=json.loads(p.read_text());bars=d.get('bars',[])
            print('BAR SCHEMA',p,list(d),len(bars),'first',bars[0] if bars else None,'last',bars[-1] if bars else None)
for p in [home/'easystock/intraday_live.py',home/'easystock/daytrade_learning/collector.py']:
    if p.exists():
        lines=p.read_text().splitlines()
        print('RUNTIME SOURCE',p)
        for i,line in enumerate(lines):
            if any(s in line for s in ['DATA_DIR','data_dir','Collector(','record_tick','save_bar','write_tick','bars/','recorder','collector=']):print(i+1,line.strip()[:180])

import hashlib
runtime=home/'easystock/intraday_live.py'
canonical=home/'easystock/vm_runtime/intraday_live.py'
print('Engine hashes',hashlib.sha256(runtime.read_bytes()).hexdigest(),hashlib.sha256(canonical.read_bytes()).hexdigest())
cache=home/'easystock-learning-data/bars/2026-10-16'
print('CACHE STOCK FILES',len(list(cache.glob('*.json'))))
for symbol in ['3231','5498','2344','8150']:
 p=cache/(symbol+'.json')
 if p.exists():
  d=json.loads(p.read_text());r=d.get('bars',[]);print('CACHE',symbol,'bars',len(r),'keys',list(d),'first',r[0] if r else None,'last',r[-1] if r else None)
