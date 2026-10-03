"""Read-only production preflight; only allowlisted summaries are emitted."""
import argparse
from contextlib import closing, redirect_stdout
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import sqlite3
import subprocess
import sys


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime',type=Path,default=Path('/home/ubuntu/easystock'))
    parser.add_argument('--firebase',action='store_true',help='Read existing premarket brief; never publish')
    args=parser.parse_args()
    sys.path.insert(0,str(args.runtime))
    today=datetime.now(timezone(timedelta(hours=8))).date().isoformat()
    report={'checked_date':today,'status':'READY_FOR_LIVE_VALIDATION','units':{}}
    properties='Id,ActiveState,SubState,UnitFileState,Result,ExecMainStatus,ExecMainStartTimestamp,LastTriggerUSec,NextElapseUSecRealtime'
    for kind in ('premarket','intraday','research-cycle','provider-health'):
        for suffix in ('service','timer'):
            unit='easystock-'+kind+'.'+suffix
            run=subprocess.run(['systemctl','show',unit,'--property='+properties],capture_output=True,text=True,timeout=15)
            report['units'][unit]=dict(line.split('=',1) for line in run.stdout.splitlines() if '=' in line)
    path=Path('/home/ubuntu/easystock-admin/state.sqlite')
    if path.is_file():
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
            report['ledger']={'integrity':db.execute('PRAGMA integrity_check').fetchone()[0],
                'rows':{table:db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]
                        for table in ('paper_trade_fills','paper_trade_logs','paper_trade_positions')}}
    from dotenv import dotenv_values
    settings=dotenv_values(args.runtime/'.env')
    report['safety_switches']={key: str(settings.get(key,'')).lower() in ('1','true','yes','on')
                             for key in ('LIVE_AUTO','ENABLE_LIVE_TRADING','ENABLE_REAL_ORDERS','LIVE_ORDERING_ENABLED')}
    report['admin_live_ordering_file_enabled'] = (
        report['safety_switches']['LIVE_ORDERING_ENABLED']
        and settings.get('LIVE_ORDERING_CONFIRMATION') == 'I_UNDERSTAND_LIVE_ORDERING')
    report['safety_switches_note']='File flags only; absence is not proof of service environment or broker state.'
    if args.firebase:
        try:
            import os
            for key,value in settings.items():
                if value is not None:
                    os.environ.setdefault(key,value)
            with redirect_stdout(io.StringIO()):
                from firebase_store import FirebaseStore
                from firebase_admin import db
                FirebaseStore()
                brief=db.reference('/market_data/premarket_brief').get() or {}
            from market_risk import premarket_context
            now=datetime.now(timezone(timedelta(hours=8)))
            level,reason=premarket_context(brief,now)
            report['premarket']={key:brief.get(key) for key in ('scan_date','generated_at','base_risk_score')}
            report['premarket'].update(level=level,freshness_reason=reason,read_only=True)
        except Exception as error:
            report['premarket']={'read_only':True,'error_type':type(error).__name__}
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
