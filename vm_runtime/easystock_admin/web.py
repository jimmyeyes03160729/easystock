import hmac
import os
import re
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlparse
from flask import Blueprint, jsonify, request, send_from_directory
from .store import Store, OWNER, Conflict, Denied, ProfileChange

SESSION = '__Host-easystock_admin'
CHALLENGE = '__Host-easystock_login'
STATIC = Path(__file__).parent / 'static'
_LINE_QUOTA_CACHE = {'at': 0.0, 'value': None}


def verify_google(credential, client_id):
    from google.oauth2 import id_token
    from google.auth.transport.requests import Request
    claims = id_token.verify_oauth2_token(credential, Request(), client_id)
    if claims.get('iss') not in ('accounts.google.com', 'https://accounts.google.com') or claims.get('aud') != client_id:
        raise ValueError('Invalid token issuer or audience')
    return claims


def register_admin(app, store=None, verifier=None):
    store = store or Store()
    verifier = verifier or verify_google
    bp = Blueprint('easystock_admin', __name__)

    def config():
        client = os.environ.get('ADMIN_GOOGLE_CLIENT_ID', '').strip()
        origin = os.environ.get('ADMIN_PUBLIC_ORIGIN', '').strip().rstrip('/')
        parsed = urlparse(origin)
        ready = bool(OWNER and re.fullmatch(r'[A-Za-z0-9._-]+\.apps\.googleusercontent\.com', client) and parsed.scheme == 'https' and parsed.netloc and parsed.path == '' and not parsed.query and not parsed.fragment and not parsed.username)
        return client, origin, ready

    def body():
        if not request.is_json or request.content_length is None or request.content_length > 16384:
            raise ValueError('請使用有效的設定表單。')
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise ValueError('設定格式不正確。')
        return data

    def origin_check():
        _, origin, ready = config()
        if not ready:
            raise Denied('管理員登入尚未完成設定。')
        if request.headers.get('Origin') != origin:
            raise Denied('請從管理後台操作。')

    def authenticated(write=False):
        token = request.cookies.get(SESSION, '')
        csrf = store.session(token)
        if write:
            origin_check()
            if not hmac.compare_digest(request.headers.get('X-CSRF-Token', ''), csrf):
                raise Denied('操作驗證已失效，請重新登入。')
        return token, csrf

    @bp.after_request
    def headers(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['Cross-Origin-Opener-Policy'] = 'same-origin-allow-popups'
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; script-src 'self' https://accounts.google.com/gsi/client; "
            "style-src 'self' 'unsafe-inline' https://accounts.google.com/gsi/style; frame-src https://accounts.google.com; "
            "connect-src 'self' https://accounts.google.com/gsi/; img-src 'self' data: https://*.googleusercontent.com; "
            "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
        )
        return response

    @bp.errorhandler(Denied)
    def denied(exc): return jsonify(error=str(exc)), 403
    @bp.errorhandler(Conflict)
    def conflict(exc): return jsonify(error=str(exc)), 409
    @bp.errorhandler(ProfileChange)
    def profile_change(exc): return jsonify(error=str(exc), code='profile_change_confirmation_required'), 409
    @bp.errorhandler(ValueError)
    def invalid(exc): return jsonify(error=str(exc)), 400
    @bp.errorhandler(sqlite3.Error)
    def unavailable(exc): return jsonify(error='設定儲存暫時無法使用，請稍後重試。'), 503

    @bp.get('/admin')
    @bp.get('/admin/')
    def page(): return send_from_directory(STATIC, 'index.html')

    @bp.get('/admin/assets/<name>')
    def assets(name):
        if name not in ('admin.js', 'admin.css', 'paper-trade.js', 'order.js'):
            return '', 404
        return send_from_directory(STATIC, name)

    @bp.get('/admin/config')
    def public_config():
        client, _, ready = config()
        return jsonify(ready=ready, client_id=client if ready else '')

    @bp.post('/admin/challenge')
    def challenge():
        origin_check()
        body()
        ticket, nonce = store.challenge()
        response = jsonify(nonce=nonce)
        response.set_cookie(CHALLENGE, ticket, max_age=300, secure=True, httponly=True, samesite='Strict', path='/')
        return response

    @bp.post('/admin/login')
    def login():
        origin_check()
        data = body()
        nonce = store.take_challenge(request.cookies.get(CHALLENGE, ''))
        credential = data.get('credential')
        if not isinstance(credential, str) or not 50 < len(credential) < 15000:
            raise Denied('Google登入憑證無效。')
        client, _, _ = config()
        try:
            claims = verifier(credential, client)
        except Exception:
            raise Denied('Google登入驗證失敗，請重新登入。') from None
        token, csrf = store.login(claims, nonce)
        response = jsonify(ok=True, csrf=csrf, email=OWNER)
        response.set_cookie(SESSION, token, max_age=8 * 3600, secure=True, httponly=True, samesite='Strict', path='/')
        response.delete_cookie(CHALLENGE, path='/', secure=True, httponly=True, samesite='Strict')
        return response

    @bp.get('/admin/session')
    def session():
        try:
            _, csrf = authenticated()
        except Denied:
            return jsonify(authenticated=False), 401
        return jsonify(authenticated=True, email=OWNER, csrf=csrf)

    @bp.post('/admin/logout')
    def logout():
        token, _ = authenticated(True)
        body()
        store.logout(token)
        response = jsonify(ok=True)
        response.delete_cookie(SESSION, path='/', secure=True, httponly=True, samesite='Strict')
        return response

    @bp.get('/admin/settings')
    def get_settings():
        authenticated()
        return jsonify(store.get())

    @bp.get('/admin/health')
    def get_health():
        authenticated()
        from .health import snapshot
        return jsonify(snapshot(store))

    @bp.get('/admin/model-log')
    def get_model_log():
        authenticated()
        from .health import model_promotion_log
        try:page=int(request.args.get('page','1'))
        except (TypeError,ValueError):page=1
        return jsonify(model_promotion_log(page=page,page_size=10))

    @bp.get('/admin/maintenance')
    def get_maintenance():
        authenticated()
        from .operations import status
        return jsonify(status())

    @bp.post('/admin/maintenance/<action>')
    def post_maintenance(action):
        authenticated(True)
        data = body()
        from .operations import execute
        return jsonify(execute(store, action, data.get('confirmation', '')))

    @bp.put('/admin/settings')
    def put_settings():
        authenticated(True)
        data = body()
        if set(data) != {'values', 'version'}:
            raise ValueError('設定欄位不正確。')
        return jsonify(store.update(data['values'], data['version']))

    @bp.get('/admin/pipeline-settings')
    def get_pipeline_settings():
        authenticated()
        return jsonify(store.get_pipeline_settings())

    @bp.put('/admin/pipeline-settings')
    def put_pipeline_settings():
        authenticated(True)
        data = body()
        if set(data) - {'confirm_profile_change'} != {'values', 'version'}:
            raise ValueError('訓練與資料計畫欄位不正確。')
        return jsonify(store.update_pipeline_settings(data['values'], data['version'],
                                                      data.get('confirm_profile_change', False)))

    @bp.get('/admin/paper-trade')
    def get_paper_trade():
        authenticated()
        return jsonify(store.get_paper_trade())

    @bp.post('/admin/paper-trade/start')
    def post_paper_trade_start():
        authenticated(True)
        data = body()
        if set(data) != {'daily_buy_limit'}:
            raise ValueError('請提供 daily_buy_limit 每日買進額度。')
        cap = data['daily_buy_limit']
        return jsonify(store.start_paper_trade(cap))

    @bp.post('/admin/paper-trade/toggle')
    def post_paper_trade_toggle():
        authenticated(True)
        body()
        return jsonify(store.toggle_paper_trade())

    @bp.get('/admin/notifications')
    def get_notifications():
        authenticated()
        from .notifications import state
        return jsonify(state(store))

    @bp.put('/admin/notifications')
    def put_notifications():
        authenticated(True)
        from .notifications import update
        return jsonify(update(store, body()))

    @bp.get('/admin/line-quota')
    def get_line_quota():
        authenticated()
        now = time.time()
        if _LINE_QUOTA_CACHE['value'] is not None and now - _LINE_QUOTA_CACHE['at'] < 600:
            return jsonify(_LINE_QUOTA_CACHE['value'])
        with store.tx() as db:
            store._limit(db, 'line-quota', 6)
        from .notifications import line_config
        import requests
        token, _ = line_config()
        if not token:
            return jsonify(error='LINE 憑證未設定。'), 503
        try:
            headers = {'Authorization': 'Bearer ' + token}
            quota = requests.get('https://api.line.me/v2/bot/message/quota', headers=headers, timeout=10)
            used = requests.get('https://api.line.me/v2/bot/message/quota/consumption', headers=headers, timeout=10)
            quota.raise_for_status()
            used.raise_for_status()
            q = quota.json()
            u = used.json()['totalUsage']
            limit = q.get('value') if q.get('type') == 'limited' else None
            result = {'used': u, 'limit': limit, 'remaining': max(0, limit - u) if limit is not None else None,
                      'checked_at': now}
            _LINE_QUOTA_CACHE.update(at=now, value=result)
            return jsonify(result)
        except (requests.RequestException, ValueError, KeyError, TypeError):
            return jsonify(error='LINE 用量暫時無法取得，請稍後重試。'), 503


    # --------------------------------------------------------
    # 永豐證券下單 API (包含完整例外捕捉與 JSON 格式錯誤處理)
    # --------------------------------------------------------
    from .order_service import order_service, validate_order, live_ordering_enabled
    ORDER_FIELDS = {'client_order_id', 'symbol', 'action', 'price', 'quantity', 'is_odd_lot', 'ca_passwd'}

    @bp.post('/admin/api/order/verify')
    def post_order_verify():
        # Re-logging in replaces the broker session, so this is a write action.
        authenticated(True)
        if body():
            raise ValueError('永豐金鑰只使用伺服器設定，不接受由網頁傳入。')
        try:
            return jsonify({'ok': True, 'account': order_service.login()})
        except Exception as e:
            return jsonify({'ok': False, 'message': str(e)}), 400

    @bp.post('/admin/api/order/quote')
    def post_order_quote():
        authenticated()
        try:
            data = request.get_json(silent=True) or {}
            symbol = data.get('symbol', '').strip()
            if not symbol:
                return jsonify({'ok': False, 'message': '請輸入股票代號'}), 400
            quote = order_service.get_quote(symbol)
            return jsonify({'ok': True, 'quote': quote})
        except Exception as e:
            return jsonify({'ok': False, 'message': str(e)}), 400

    @bp.post('/admin/api/order/place')
    def post_order_place():
        # This endpoint can call the broker.  It must use the same
        # Origin/CSRF protection as every state-changing admin action.
        authenticated(True)
        data = body()
        if set(data) != ORDER_FIELDS:
            raise ValueError('委託欄位不正確。')
        order = validate_order(data['symbol'], data['action'], data['price'],
                               data['quantity'], data['is_odd_lot'])
        ca_passwd = data['ca_passwd']
        if not isinstance(ca_passwd, str) or not 0 < len(ca_passwd) <= 128:
            raise ValueError('請輸入憑證密碼。')
        if not live_ordering_enabled():
            return jsonify({'ok': False, 'message': '真實下單入口目前已隔離，伺服器未啟用實單。'}), 403
        # Reserve before sending: a repeated click or retry cannot place a second order,
        # and an interrupted request stays visible as "submitting" for reconciliation.
        store.reserve_order(data['client_order_id'], order)
        try:
            res = order_service.place_order(ca_passwd=ca_passwd, **order)
        except Exception as e:
            store.finish_order(data['client_order_id'], 'failed', {'message': str(e)[:300]})
            return jsonify({'ok': False, 'message': str(e)}), 400
        store.finish_order(data['client_order_id'], 'submitted', res)
        return jsonify({'ok': True, 'trade': res})

    app.register_blueprint(bp)
    return store
