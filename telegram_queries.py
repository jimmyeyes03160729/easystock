"""Authenticated loopback bridge to LINE's existing parser, charts and broker session."""
import hashlib
import hmac
from easystock_admin.notifications import telegram_config

HELP = '''📊 EasyStock Telegram 看盤查詢
#台積電 / #2330 / #大盤：即時查價
P台積電 / P2330 / P大盤：分時走勢與五檔
K台積電 / K2330 / K大盤：日 K 線圖
T台積電 / T2330 / T大盤：三大法人
D台積電 / D2330：股利與殖利率
當沖 / 早報：查閱最新摘要
指令：顯示本說明
圖卡按鈕可即時切換。支援 1 對 1 私聊與已核准群組。'''


def bridge_secret():
    token, _ = telegram_config()
    return hmac.new(token.encode(), b'easystock-telegram-query-bridge-v1', hashlib.sha256).hexdigest() if token else ''


def enabled(store, group, is_private=False):
    token, target = telegram_config()
    if not token:
        return False
    if is_private:
        return store.is_private_replies_enabled() if hasattr(store, 'is_private_replies_enabled') else True
    if str(group) != target:
        return False
    with store.tx() as db:
        return bool(db.execute('SELECT replies FROM telegram_policy WHERE id=1').fetchone()[0])


def register_bridge(app, store, parse, handle):
    from flask import request, jsonify
    from easystock_admin.store import Denied

    @app.post('/internal/telegram-query')
    def telegram_query():
        secret = bridge_secret()
        if request.remote_addr not in ('127.0.0.1', '::1') or not secret or not hmac.compare_digest(request.headers.get('X-Telegram-Bridge', ''), secret):
            return '', 403
        if not request.is_json or not request.content_length or request.content_length > 4096:
            return '', 400
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or not ({'group', 'text'} <= set(data)) or not isinstance(data.get('text'), str) or len(data['text']) > 160:
            return '', 400
        is_private = bool(data.get('is_private', False))
        if not enabled(store, data['group'], is_private=is_private):
            return jsonify(messages=[])
        cmd = parse(data['text'])
        if cmd is None:
            return jsonify(messages=[])
        try:
            with store.tx() as db:
                store._limit(db, 'telegram-query', 15)
        except Denied:
            return jsonify(messages=[]), 429
        try:
            if cmd.kind in ('HELP', 'NOTIFY_INFO', 'UPDATE'):
                messages = [{'type': 'text', 'text': HELP}]
            else:
                messages = handle(cmd)
            # Legacy services may embed upstream exception details; never forward them.
            safe = []
            for message in messages or []:
                if not isinstance(message, dict):
                    continue
                if message.get('type') == 'text' and any(term in str(message.get('text', '')) for term in ('查詢失敗', 'Traceback', 'LINE_BOT_PUBLIC_BASE_URL')):
                    message = {'type': 'text', 'text': '資料來源暫時無法使用，請稍後再試。'}
                safe.append(message)
            return jsonify(messages=safe[:5] if enabled(store, data['group'], is_private=is_private) else [])
        except Exception:
            return jsonify(messages=[{'type': 'text', 'text': '查詢暫時無法完成，請稍後再試。'}]), 503
