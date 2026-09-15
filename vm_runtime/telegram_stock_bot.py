"""Single group-only long poller. No broker login, private replies or message archive."""
import hashlib
import json
import os
from pathlib import Path
import re
import time
from urllib.parse import unquote,urlsplit
import requests
from easystock_admin.store import Store
from easystock_admin.notifications import telegram_config
from telegram_queries import bridge_secret,enabled


def api(method,data,files=None):
    if method not in ('getUpdates','getWebhookInfo','sendMessage','sendPhoto','answerCallbackQuery'):raise ValueError('Invalid method')
    token,_=telegram_config()
    if not token:raise RuntimeError('Telegram is not configured')
    kwargs={'data':data,'files':files} if files else {'json':data}
    try:
        response=requests.post('https://api.telegram.org/bot'+token+'/'+method,**kwargs,
                               timeout=(5,30 if method=='getUpdates' else 20),allow_redirects=False)
        result=response.json()
        if response.status_code!=200 or result.get('ok') is not True:raise RuntimeError('Telegram request rejected')
        return result.get('result')
    except Exception:
        # requests exceptions contain credential-bearing URLs.
        raise RuntimeError('Telegram request failed') from None


def keyboard(message):
    buttons=[]
    contents=message.get('contents') or {}
    for item in (contents.get('footer') or {}).get('contents',[]):
        action=item.get('action') or {}
        if action.get('type')=='message':
            query='q:'+str(action.get('text') or '')
            if len(query.encode())<=64:buttons.append({'text':str(action.get('label') or '查詢'),'callback_data':query})
        elif action.get('type')=='uri' and str(action.get('uri','')).startswith('https://'):
            buttons.append({'text':str(action.get('label') or '網站'),'url':action['uri']})
    return {'inline_keyboard':[buttons]} if buttons else None


def image_bytes(message):
    url=message.get('originalContentUrl') if message.get('type')=='image' else ((message.get('contents') or {}).get('hero') or {}).get('url')
    name=unquote(urlsplit(str(url or '')).path).rsplit('/',1)[-1]
    if not re.fullmatch(r'[A-Za-z0-9_.-]+\.png',name):raise ValueError('Invalid chart')
    root=Path(os.environ.get('LINE_CHART_DIR',str(Path(__file__).parent/'line_charts'))).resolve()
    path=(root/name).resolve()
    if path.parent!=root or path.is_symlink() or not 0<path.stat().st_size<=10*1024*1024:raise ValueError('Invalid chart')
    content=path.read_bytes()
    if not content.startswith(b'\x89PNG\r\n\x1a\n'):raise ValueError('Invalid chart')
    return content


def send_messages(store,group,messages,reply_id=None):
    sent=0
    for message in messages[:5]:
        if not enabled(store,group):break
        data={'chat_id':str(group)}
        if reply_id:data['reply_parameters']={'message_id':reply_id,'allow_sending_without_reply':True}
        if message.get('type')=='text':
            text=str(message.get('text') or '')
            for start in range(0,min(len(text),8192),4096):
                if not enabled(store,group):break
                api('sendMessage',{**data,'text':text[start:start+4096],'link_preview_options':{'is_disabled':True}});sent+=1
        elif message.get('type') in ('image','flex'):
            content=image_bytes(message)
            markup=keyboard(message)
            if markup:data['reply_markup']=markup
            if message.get('altText'):data['caption']=str(message['altText'])[:1024]
            data={key:json.dumps(value) if isinstance(value,dict) else value for key,value in data.items()}
            api('sendPhoto',data,files={'photo':('chart.png',content,'image/png')});sent+=1
    return sent


def handle_update(store,update):
    uid=update.get('update_id')
    if type(uid) is not int:return
    # Persist before side effects. A crash/ambiguous send is not blindly replayed.
    with store.tx() as db:
        row=db.execute("SELECT value FROM meta WHERE key='telegram_offset'").fetchone()
        if row and uid<int(row[0]):return
        db.execute("INSERT OR REPLACE INTO meta VALUES('telegram_offset',?)",(str(uid+1),))
    callback=update.get('callback_query')
    message=(callback.get('message') if isinstance(callback,dict) else update.get('message')) or {}
    chat=message.get('chat') or {}
    sender=(callback.get('from') if isinstance(callback,dict) else message.get('from')) or {}
    _,group=telegram_config()
    if chat.get('type') not in ('group','supergroup') or str(chat.get('id'))!=group or sender.get('is_bot') or not enabled(store,group):return
    if callback:
        text=callback.get('data','')
        if not isinstance(text,str) or not text.startswith('q:'):return
        text=text[2:]
        try:api('answerCallbackQuery',{'callback_query_id':callback['id']})
        except Exception:pass
    else:
        text=message.get('text','')
        if not isinstance(message.get('date'),(int,float)) or not -30<=time.time()-message['date']<=120:return
    if not isinstance(text,str) or not 0<len(text.strip())<=160:return
    try:
        response=requests.post('http://127.0.0.1:8088/internal/telegram-query',
            headers={'X-Telegram-Bridge':bridge_secret()},json={'group':group,'text':text.strip()},timeout=(3,100))
        if response.status_code not in (200,503):return
        messages=response.json().get('messages',[])
        sent=send_messages(store,group,messages,message.get('message_id'))
        print('[TELEGRAM QUERY] completed; messages=',sent,flush=True)
    except Exception:
        print('[TELEGRAM QUERY] failed; no automatic replay',flush=True)


def run():
    import fcntl
    store=Store()
    with (store.path.parent/'telegram-poller.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if api('getWebhookInfo',{}).get('url'):raise RuntimeError('Existing webhook conflicts with polling')
        print('[TELEGRAM QUERY] poller ready',flush=True)
        while True:
            try:
                with store.tx() as db:
                    row=db.execute("SELECT value FROM meta WHERE key='telegram_offset'").fetchone()
                updates=api('getUpdates',{'offset':int(row[0]) if row else 0,'timeout':20,'limit':20,'allowed_updates':['message','callback_query']})
                for update in updates or []:handle_update(store,update)
                with store.tx() as db:db.execute("INSERT OR REPLACE INTO meta VALUES('telegram_last_poll',?)",(str(time.time()),))
            except Exception:
                print('[TELEGRAM QUERY] poll unavailable; retry in 10 seconds',flush=True)
                time.sleep(10)


if __name__=='__main__':run()
