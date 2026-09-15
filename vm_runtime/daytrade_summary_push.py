"""Preview by default. --send is used only by the existing scheduled report service."""
import argparse
import fcntl
import hashlib
import json
from pathlib import Path
import uuid
from datetime import datetime,time


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
    if args.send and (now.weekday()>=5 or not time(13,35)<=now.time().replace(tzinfo=None)<=time(20,30)):
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
        from line_bot import access_token
        from line_group_manager import get_active_groups
        from line_policy import push_allowed
        groups=[gid for gid in get_active_groups() if push_allowed(gid,'other')]
        if not groups:print('No active LINE groups');return
        token=access_token()
        if not token:raise RuntimeError('LINE token missing')
        failures=0;sent=0
        for gid in sorted(set(groups)):
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
                else:failures+=1
            except requests.RequestException:failures+=1
        print(f'Summary requests accepted: {sent}; failed: {failures}')
        if failures:raise SystemExit(1)


if __name__=='__main__':main()
