import hmac
import os
import re
import sqlite3
from pathlib import Path
from urllib.parse import urlparse
from flask import Blueprint, jsonify, request, send_from_directory
from .store import Store, OWNER, Conflict, Denied

SESSION='__Host-easystock_admin'
CHALLENGE='__Host-easystock_login'
STATIC=Path(__file__).parent/'static'


def verify_google(credential,client_id):
    from google.oauth2 import id_token
    from google.auth.transport.requests import Request
    claims=id_token.verify_oauth2_token(credential,Request(),client_id)
    if claims.get('iss') not in ('accounts.google.com','https://accounts.google.com') or claims.get('aud')!=client_id:
        raise ValueError('Invalid token issuer or audience')
    return claims


def register_admin(app,store=None,verifier=None):
    store=store or Store()
    verifier=verifier or verify_google
    bp=Blueprint('easystock_admin',__name__)

    def config():
        client=os.environ.get('ADMIN_GOOGLE_CLIENT_ID','').strip()
        origin=os.environ.get('ADMIN_PUBLIC_ORIGIN','').strip().rstrip('/')
        parsed=urlparse(origin)
        ready=bool(OWNER and re.fullmatch(r'[A-Za-z0-9._-]+\.apps\.googleusercontent\.com',client) and parsed.scheme=='https' and parsed.netloc and parsed.path=='' and not parsed.query and not parsed.fragment and not parsed.username)
        return client,origin,ready

    def body():
        if not request.is_json or request.content_length is None or request.content_length>16384:
            raise ValueError('請使用有效的設定表單。')
        data=request.get_json(silent=True)
        if not isinstance(data,dict):raise ValueError('設定格式不正確。')
        return data

    def origin_check():
        _,origin,ready=config()
        if not ready:raise Denied('管理員登入尚未完成設定。')
        if request.headers.get('Origin')!=origin:raise Denied('請從管理後台操作。')

    def authenticated(write=False):
        token=request.cookies.get(SESSION,'')
        csrf=store.session(token)
        if write:
            origin_check()
            if not hmac.compare_digest(request.headers.get('X-CSRF-Token',''),csrf):raise Denied('操作驗證已失效，請重新登入。')
        return token,csrf

    @bp.after_request
    def headers(response):
        response.headers['Cache-Control']='no-store'
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['X-Frame-Options']='DENY'
        response.headers['Referrer-Policy']='strict-origin-when-cross-origin'
        response.headers['Cross-Origin-Opener-Policy']='same-origin-allow-popups'
        response.headers['Content-Security-Policy']=("default-src 'self'; script-src 'self' https://accounts.google.com/gsi/client; "
            "style-src 'self' 'unsafe-inline' https://accounts.google.com/gsi/style; frame-src https://accounts.google.com; "
            "connect-src 'self' https://accounts.google.com/gsi/; img-src 'self' data: https://*.googleusercontent.com; "
            "base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
        return response

    @bp.errorhandler(Denied)
    def denied(exc):return jsonify(error=str(exc)),403
    @bp.errorhandler(Conflict)
    def conflict(exc):return jsonify(error=str(exc)),409
    @bp.errorhandler(ValueError)
    def invalid(exc):return jsonify(error=str(exc)),400
    @bp.errorhandler(sqlite3.Error)
    def unavailable(exc):return jsonify(error='設定儲存暫時無法使用，請稍後重試。'),503

    @bp.get('/admin')
    @bp.get('/admin/')
    def page():return send_from_directory(STATIC,'index.html')

    @bp.get('/admin/assets/<name>')
    def assets(name):
        if name not in ('admin.js','admin.css'):return '',404
        return send_from_directory(STATIC,name)

    @bp.get('/admin/config')
    def public_config():
        client,_,ready=config()
        return jsonify(ready=ready,client_id=client if ready else '')

    @bp.post('/admin/challenge')
    def challenge():
        origin_check();body()
        ticket,nonce=store.challenge()
        response=jsonify(nonce=nonce)
        response.set_cookie(CHALLENGE,ticket,max_age=300,secure=True,httponly=True,samesite='Strict',path='/')
        return response

    @bp.post('/admin/login')
    def login():
        origin_check();data=body()
        nonce=store.take_challenge(request.cookies.get(CHALLENGE,''))
        credential=data.get('credential')
        if not isinstance(credential,str) or not 50<len(credential)<15000:raise Denied('Google登入憑證無效。')
        client,_,_=config()
        try:claims=verifier(credential,client)
        except Exception:raise Denied('Google登入驗證失敗，請重新登入。') from None
        token,csrf=store.login(claims,nonce)
        response=jsonify(ok=True,csrf=csrf,email=OWNER)
        response.set_cookie(SESSION,token,max_age=8*3600,secure=True,httponly=True,samesite='Strict',path='/')
        response.delete_cookie(CHALLENGE,path='/',secure=True,httponly=True,samesite='Strict')
        return response

    @bp.get('/admin/session')
    def session():
        try:_,csrf=authenticated()
        except Denied:return jsonify(authenticated=False),401
        return jsonify(authenticated=True,email=OWNER,csrf=csrf,line_linked=store.linked())

    @bp.post('/admin/logout')
    def logout():
        token,_=authenticated(True);body();store.logout(token)
        response=jsonify(ok=True)
        response.delete_cookie(SESSION,path='/',secure=True,httponly=True,samesite='Strict')
        return response

    @bp.get('/admin/settings')
    def get_settings():authenticated();return jsonify(store.get())

    @bp.put('/admin/settings')
    def put_settings():
        authenticated(True);data=body()
        if set(data)!= {'values','version'}:raise ValueError('設定欄位不正確。')
        return jsonify(store.update(data['values'],data['version']))

    @bp.post('/admin/line-bind')
    def bind():authenticated(True);body();return jsonify(code=store.bind_code(),expires_in=300)

    @bp.get('/admin/line-policy')
    def get_line_policy():
        authenticated()
        from .conversations import state
        return jsonify(state(store))

    @bp.get('/admin/line-usage')
    def get_line_usage():
        authenticated()
        with store.tx() as db:store._limit(db,'line-usage',6)
        from line_bot import access_token
        import requests
        token=access_token()
        if not token:return jsonify(error='LINE 憑證未設定。'),503
        try:
            headers={'Authorization':'Bearer '+token}
            quota=requests.get('https://api.line.me/v2/bot/message/quota',headers=headers,timeout=10)
            used=requests.get('https://api.line.me/v2/bot/message/quota/consumption',headers=headers,timeout=10)
            quota.raise_for_status();used.raise_for_status()
            q=quota.json();u=used.json()['totalUsage']
            limit=q.get('value') if q.get('type')=='limited' else None
            return jsonify(used=u,limit=limit,remaining=max(0,limit-u) if limit is not None else None)
        except (requests.RequestException,ValueError,KeyError,TypeError):
            return jsonify(error='LINE 用量暫時無法取得，請稍後重試。'),503

    @bp.put('/admin/line-policy')
    def put_line_policy():
        authenticated(True)
        from .conversations import update
        return jsonify(update(store,body()))

    @bp.put('/admin/line-conversations/<key>')
    def put_line_conversation(key):
        authenticated(True)
        from .conversations import update_conversation
        return jsonify(update_conversation(store,key,body()))

    @bp.post('/admin/line-unlink')
    def unlink():authenticated(True);body();store.unlink();return jsonify(ok=True)

    app.register_blueprint(bp)
    return store
