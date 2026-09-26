"""Post-close sample -> labels -> candidate pipeline; never promotes a model."""
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime


def main():
    from dotenv import load_dotenv
    root = Path(__file__).resolve().parent
    load_dotenv(root/'.env')
    from daytrade_learning.runtime import TPE, DATA
    from daytrade_learning.research import journal
    day = datetime.now(TPE).date().isoformat()
    observations, _ = journal(DATA/('journal-'+day+'.jsonl'))
    if not any(r.get('kind') == 'sample' and r.get('data',{}).get('observed_at','')[:10] == day for r in observations):
        print(json.dumps({'status':'skipped','date':day,'reason':'no_same_day_samples'}))
        return
    subprocess.run([sys.executable,str(root/'learning_eod.py'),'--date',day,'--collect','--publish'],check=True)
    subprocess.run([sys.executable,str(root/'learning_eod.py'),'--date',day,'--train'],check=True)


if __name__ == '__main__':
    main()
