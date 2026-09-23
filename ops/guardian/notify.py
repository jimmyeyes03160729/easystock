import json
import fcntl
import urllib.request
from common import STATE, now, read_json, write_json

def send(text, key):
    conf = read_json('/etc/easystock-guardian/config.json',{})
    if not conf.get('telegram_enabled'):
        return False
    with (STATE/'notifications.lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        return _send_locked(text,key)

def _send_locked(text,key):
    sent = read_json(STATE/'notifications.json',{})
    if key in sent:
        return True
    outbox=read_json(STATE/'notification-outbox.json',{})
    outbox[key]=text[:3500]
    write_json(STATE/'notification-outbox.json',outbox)
    from dotenv import dotenv_values
    config = dotenv_values('/home/ubuntu/easystock-telegram.env')
    payload = {'chat_id':config['TELEGRAM_GROUP_ID'],'text':text[:3500],'disable_web_page_preview':True}
    request = urllib.request.Request('https://api.telegram.org/bot'+config['TELEGRAM_BOT_TOKEN']+'/sendMessage',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
    try:
        result = json.load(urllib.request.urlopen(request,timeout=15))
        if not result.get('ok'):
            return False
    except Exception:
        # Never put token-containing URLs in logs.
        return False
    sent[key] = now().isoformat()
    if len(sent)>500:
        sent = dict(list(sent.items())[-500:])
    write_json(STATE/'notifications.json',sent)
    outbox.pop(key,None)
    write_json(STATE/'notification-outbox.json',outbox)
    return True

def retry_pending():
    pending=read_json(STATE/'notification-outbox.json',{})
    for key,text in list(pending.items())[:2]:
        send(text,key)
