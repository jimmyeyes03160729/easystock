"""Owner summary only, using existing clients and opt-in policy. No trading DB writes."""
import hashlib
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from .report import output_directory, write_artifact


def notify(root, directory, report, db_path=None, senders=None):
    high=[r['fingerprint'] for r in report['findings'] if r['severity'] in ('CRITICAL','HIGH')]
    if not high:return {'status':'NO_HIGH_FINDINGS'}
    directory=output_directory(root,directory)
    directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    lock=directory/'notification.lock'
    try:fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    except FileExistsError:return {'status':'BUSY_OR_PREVIOUS_ATTEMPT_UNCERTAIN'}
    os.close(fd)
    try:
        path=Path(db_path or os.environ.get('EASYSTOCK_ADMIN_DB','/home/ubuntu/easystock-admin/state.sqlite'))
        with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as db:
            row=db.execute('SELECT line_summary,telegram_summary FROM notification_policy WHERE id=1').fetchone()
        if not row:return {'status':'POLICY_UNAVAILABLE'}
        state_file=directory/'notification-state.json'
        if state_file.is_symlink() or state_file.exists() and state_file.stat().st_size>1024*1024:raise ValueError('state')
        receipts=json.loads(state_file.read_text()) if state_file.exists() else {}
        key=hashlib.sha256(':'.join(sorted(high)).encode()).hexdigest()
        if senders is None:
            from trade_notifications import _line_send,_telegram_send
            senders={'line':lambda text:_line_send(text,key),'telegram':_telegram_send}
        outcomes={}
        text=f"Architecture Guardian {report['overall_status']}：Critical {report['counts']['critical']} / High {report['counts']['high']}。請至私人後台查看健檢報告。僅供審查，不修改設定或執行交易。"
        for channel,enabled in zip(('line','telegram'),row):
            identity=channel+':'+key
            if not enabled or identity in receipts:continue
            # Persist before external delivery; ambiguous results never cause duplicate retries.
            receipts[identity]='reserved';write_artifact(root,directory,'notification-state.json',receipts)
            try:status=senders[channel](text)
            except Exception:status='unknown'
            receipts[identity]=status if status in ('sent','failed','unknown','disabled') else 'unknown'
            outcomes[channel]=receipts[identity]
            write_artifact(root,directory,'notification-state.json',receipts)
        return {'status':'COMPLETED','channels':outcomes}
    except Exception:return {'status':'NOTIFICATION_UNAVAILABLE'}
    finally:lock.unlink(missing_ok=True)
