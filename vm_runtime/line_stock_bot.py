#!/usr/bin/env python3
"""EasyStock Admin plus a signature-verified, deliberately silent LINE webhook."""
import base64
import hashlib
import hmac
import os
from flask import Flask, abort, request
from easystock_admin.web import register_admin

app = Flask(__name__)
ADMIN_STORE = register_admin(app)


def verify_signature(body, signature):
    secret = os.environ.get('LINE_CHANNEL_SECRET', '').strip()
    if not secret:
        return False
    expected = base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()
    return hmac.compare_digest(expected, signature or '')


@app.get('/healthz')
def healthz():
    return {'ok': True, 'service': 'easystock-admin-line-webhook', 'commands': False}


@app.post('/callback')
def callback():
    body = request.get_data(cache=False)
    if not verify_signature(body, request.headers.get('X-Line-Signature', '')):
        abort(400)
    # LINE text/follow/postback events are intentionally no-op. Never query stocks,
    # render cards, register groups, or reply.
    return 'OK', 200


if __name__ == '__main__':
    app.run(host=os.environ.get('LINE_BOT_HOST', '127.0.0.1'), port=int(os.environ.get('LINE_BOT_PORT', '8080')))
