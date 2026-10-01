"""Preview by default. --send is used only by the existing scheduled report service."""
import argparse
import fcntl
import hashlib
import json
import time as time_module
from pathlib import Path
import uuid
from datetime import datetime,time


def _record_line_delivery(store, key, status):
    """Make the legacy 13:30 summary visible in the admin delivery ledger."""
    if store is None:
        return
    try:
        with store.tx() as db:
            db.execute(
                'INSERT OR REPLACE INTO notification_receipts(key,channel,status,created) VALUES(?,?,?,?)',
                (key, 'line', status, time_module.time()),
            )
    except Exception as exc:
        # Delivery must not be turned into a failure merely because the audit
        # ledger is temporarily unavailable.
        print(f'[WARN] notification receipt unavailable: {type(exc).__name__}')


def main():
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent/'.env')
    from daytrade_learning.runtime import DATA,TPE
    from daytrade_learning.research import journal,save
    from line_hub_service import latest_daytrade_text
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--send',action='store_true')
    args=parser.parse_args()
    now=datetime.now(TPE);day=now.date().isoformat()
    if args.send and (now.weekday()>=5 or not time(13,25)<=now.time().replace(tzinfo=None)<=time(20,30)):
        print('Outside scheduled summary window; skipped');return
    DATA.mkdir(parents=True,exist_ok=True,mode=0o700)
    with open(DATA/'summary.lock','a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        obs,_=journal(DATA/('journal-'+day+'.jsonl'))
        if args.send and not any(r.get('kind')=='sample' for r in obs):
            print('No observed same-day trading activity; skipped');return
        text=latest_daytrade_text()
        if not text:print('No current-day report');return
        if not args.send:print(text);return
        import requests
        from line_bot import access_token, default_target
        from line_group_manager import get_active_groups
        from easystock_admin.store import Store
        try:
            store = Store()
        except Exception as exc:
            # The notification itself must not be lost because the optional
            # admin audit database is unavailable.
            print(f'[WARN] admin notification ledger unavailable: {type(exc).__name__}')
            store = None
        targets = set(get_active_groups())
        user_tgt = default_target()
        if user_tgt:
            targets.add(user_tgt)
        if not targets:
            print('No active LINE targets');return
        token=access_token()
        if not token:raise RuntimeError('LINE token missing')
        failures=0;sent=0
        for gid in sorted(targets):
            tag=hashlib.sha256(gid.encode()).hexdigest()[:20]
            path=DATA/'summary-delivery'/(day+'-'+tag+'.json')
            record=json.loads(path.read_text()) if path.exists() else {'text':text,'retry_key':str(uuid.uuid4()),'sent':False}
            if record['sent']:continue
            # Freeze original body and retry key before making the first request.
            save(path,record)
            if len(record['text'])>4900:
                failures+=1;continue
            try:
                response=requests.post('https://api.line.me/v2/bot/message/push',headers={
                    'Authorization':'Bearer '+token,'Content-Type':'application/json','X-Line-Retry-Key':record['retry_key']},
                    json={'to':gid,'messages':[{'type':'text','text':record['text']}]},timeout=20)
                accepted=200<=response.status_code<300 or (response.status_code==409 and bool(response.headers.get('x-line-accepted-request-id')))
                if accepted:
                    record['sent']=True;save(path,record);sent+=1
                    _record_line_delivery(store, 'summary:' + day + ':' + tag, 'sent')
                else:
                    failures+=1
                    _record_line_delivery(store, 'summary:' + day + ':' + tag, 'failed')
                    print(f"[WARN] LINE push to {gid[:8]} failed HTTP {response.status_code}: {response.text[:200]}")
            except requests.RequestException as exc:
                failures+=1
                _record_line_delivery(store, 'summary:' + day + ':' + tag, 'unknown')
                print(f"[ERROR] LINE push to {gid[:8]} exception: {exc}")
        print(f'Summary requests accepted: {sent}; failed: {failures}')
        if failures and not sent:raise SystemExit(1)


if __name__=='__main__':main()
