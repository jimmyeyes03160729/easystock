#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import json, os, time
from pathlib import Path
from typing import Any
import requests
LINE_REPLY_URL='https://api.line.me/v2/bot/message/reply'
LINE_PUSH_URL='https://api.line.me/v2/bot/message/push'
LOG_PATH=Path(os.environ.get('LINE_HUB_LOG_PATH','/dev/shm/easystock_line_last_push.json'))
def _env_first(*names):
    for name in names:
        value=str(os.environ.get(name) or '').strip()
        if value:return value
    return ''
def access_token(): return _env_first('LINE_CHANNEL_ACCESS_TOKEN','LINE_ACCESS_TOKEN','LINE_TOKEN')
def default_target(): return _env_first('LINE_TARGET_ID','LINE_USER_ID','LINE_GROUP_ID')
def _headers():
    token=access_token()
    if not token: raise RuntimeError('LINE_CHANNEL_ACCESS_TOKEN / LINE_ACCESS_TOKEN 未設定')
    return {'Authorization':f'Bearer {token}','Content-Type':'application/json'}
def _write_log(kind,ok,detail=''):
    try:
        LOG_PATH.parent.mkdir(parents=True,exist_ok=True)
        LOG_PATH.write_text(json.dumps({'kind':kind,'ok':bool(ok),'detail':detail[:500],'epoch':time.time()},ensure_ascii=False),encoding='utf-8')
    except Exception: pass
def reply_messages(reply_token,messages):
    if not reply_token or not messages:return False
    r=requests.post(LINE_REPLY_URL,headers=_headers(),json={'replyToken':reply_token,'messages':messages[:5]},timeout=20)
    ok=r.status_code<300; _write_log('reply',ok,f'HTTP {r.status_code}')
    if not ok: raise RuntimeError(f'LINE reply HTTP {r.status_code}: {r.text[:500]}')
    return True
def push_messages(messages,target=None,category='other'):
    target=str(target or default_target()).strip()
    from line_policy import push_allowed
    if not push_allowed(target,category):return False
    if not target: raise RuntimeError('LINE_TARGET_ID / LINE_USER_ID / LINE_GROUP_ID 未設定')
    if not messages:return False
    r=requests.post(LINE_PUSH_URL,headers=_headers(),json={'to':target,'messages':messages[:5]},timeout=20)
    ok=r.status_code<300; _write_log('push',ok,f'HTTP {r.status_code}')
    if not ok: print(f'[WARN] LINE push failed HTTP {r.status_code}: {r.text[:300]}')
    return ok
def push_text(*args:Any):
    if len(args)==1: target=None; text=args[0]
    elif len(args)>=2: target=args[0]; text=args[1]
    else:return False
    text=str(text or '').strip()
    if not text:return False
    return push_messages([{'type':'text','text':text[:5000]}],target=str(target or '').strip() or None)
push_message=push_text
send_message=push_text
send_line_message=push_text
line_push=push_text
push_line_message=push_text
