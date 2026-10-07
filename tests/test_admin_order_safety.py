"""Admin broker endpoints and cost-profile confirmation."""
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from easystock_admin.order_service import order_service, validate_order

OWNER = 'owner@example.test'
ORIGIN = 'https://admin.example.com'
CLIENT = '123456-test.apps.googleusercontent.com'
INITIAL = {'min_price': 20, 'max_price': 100, 'max_gain_pct': 5, 'max_recommendations': 30}
LIVE = {'LIVE_ORDERING_ENABLED': '1', 'LIVE_ORDERING_CONFIRMATION': 'I_UNDERSTAND_LIVE_ORDERING'}


def order(**kw):
    return {'client_order_id': '0123456789abcdef-0001', 'symbol': '2330', 'action': 'BUY',
            'price': 100, 'quantity': 1, 'is_odd_lot': False, 'ca_passwd': 'secret-pw', **kw}


class ValidateOrderTests(unittest.TestCase):
    def test_accepts_tick_aligned_limit_order(self):
        self.assertEqual(validate_order('2330', 'SELL', 1015, 500, True),
                         {'symbol': '2330', 'action': 'SELL', 'price': 1015.0, 'quantity': 500, 'is_odd_lot': True})

    def test_rejects_unclear_or_unsafe_orders(self):
        for args in [('2330', 'B', 100, 1, False),           # typo no longer becomes SELL
                     ('2330', 'buy', 100, 1, False),
                     ('2330', 'BUY', 100.3, 1, False),       # 100-500 tick is 0.5
                     ('2330', 'BUY', -1, 1, False),
                     ('2330', 'BUY', True, 1, False),
                     ('2330', 'BUY', 100, 0, False),
                     ('2330', 'BUY', 100, 500, False),       # above 499 lots
                     ('2330', 'BUY', 100, 1000, True),       # odd lot is below 1,000 shares
                     ('2330', 'BUY', 100, 1, 'yes'),
                     ('../x', 'BUY', 100, 1, False),
                     ('2330', 'BUY', 600, 2, False)]:         # 1.2M above the 1M notional cap
            with self.subTest(args=args), self.assertRaises(ValueError):
                validate_order(*args)


class AdminOrderWebTests(unittest.TestCase):
    def setUp(self):
        from flask import Flask
        self.patches = [patch.dict(os.environ, {'ADMIN_GOOGLE_CLIENT_ID': CLIENT, 'ADMIN_PUBLIC_ORIGIN': ORIGIN}),
                        patch('easystock_admin.store.OWNER', OWNER), patch('easystock_admin.web.OWNER', OWNER)]
        for p in self.patches:
            p.start()
        from easystock_admin.store import Store
        from easystock_admin.web import register_admin
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = Path(self.tmp.name) / 'db'
        self.store = Store(self.db, INITIAL)
        self.nonce = ''
        app = Flask(__name__)
        register_admin(app, self.store, lambda credential, client: {
            'email': OWNER, 'email_verified': True, 'sub': 'owner', 'nonce': self.nonce})
        self.client = app.test_client()
        self.nonce = self.post('challenge', {}).json['nonce']
        self.csrf = self.post('login', {'credential': 'x' * 60}).json['csrf']

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def post(self, path, data, csrf=None, method='post'):
        return getattr(self.client, method)('/admin/' + path, base_url=ORIGIN, json=data,
            headers={'Origin': ORIGIN, **({'X-CSRF-Token': csrf} if csrf else {})})

    def rows(self, sql):
        with sqlite3.connect(self.db) as db:
            return db.execute(sql).fetchall()

    def test_verify_needs_csrf_rejects_browser_keys_and_masks_identity(self):
        self.assertEqual(self.post('api/order/verify', {}).status_code, 403)
        self.assertEqual(self.post('api/order/verify', {'api_key': 'k', 'secret_key': 's'}, self.csrf).status_code, 400)
        order_service.account_info = {'person_name': 'Owner', 'person_id': 'A123456789',
                                      'account_id': '9876543', 'broker_id': '9A95'}
        with patch.object(order_service, 'login', side_effect=order_service.public_account):
            response = self.post('api/order/verify', {}, self.csrf)
        self.assertEqual(response.json['account'], {'person_name': 'Owner', 'broker_id': '9A95', 'account_id': '***6543'})
        self.assertNotIn('A123456789', response.get_data(as_text=True))

    def test_place_is_reserved_once_and_audited_without_password(self):
        with patch.dict(os.environ, LIVE), \
                patch.object(order_service, 'place_order', return_value={'order_id': 'X1', 'status': 'Submitted'}) as place:
            first = self.post('api/order/place', order(), self.csrf)
            again = self.post('api/order/place', order(), self.csrf)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(again.status_code, 409)
        place.assert_called_once_with(ca_passwd='secret-pw', symbol='2330', action='BUY',
                                      price=100.0, quantity=1, is_odd_lot=False)
        self.assertEqual(self.rows('SELECT status FROM order_requests'), [('submitted',)])
        self.assertEqual([r[0] for r in self.rows("SELECT action FROM audit WHERE action LIKE 'order_%' ORDER BY id")],
                         ['order_submit', 'order_result'])
        self.assertNotIn('secret-pw', json.dumps(self.rows('SELECT * FROM audit') + self.rows('SELECT * FROM order_requests')))

    def test_failed_or_disabled_or_malformed_orders(self):
        with patch.dict(os.environ, LIVE), patch.object(order_service, 'place_order', side_effect=RuntimeError('broker down')):
            self.assertEqual(self.post('api/order/place', order(), self.csrf).status_code, 400)
        self.assertEqual(self.rows('SELECT status FROM order_requests'), [('failed',)])
        with patch.object(order_service, 'place_order') as place:
            self.assertEqual(self.post('api/order/place', order(client_order_id='0123456789abcdef-0002'), self.csrf).status_code, 403)
            with patch.dict(os.environ, LIVE):
                self.assertEqual(self.post('api/order/place', order(ca_path='/etc/passwd'), self.csrf).status_code, 400)
                self.assertEqual(self.post('api/order/place', order(action='B'), self.csrf).status_code, 400)
            place.assert_not_called()

    def test_cost_profile_change_requires_confirmation(self):
        current = self.client.get('/admin/pipeline-settings', base_url=ORIGIN).json
        values = dict(current['values'], fee_rate=.001)
        refused = self.post('pipeline-settings', {'values': values, 'version': current['version']}, self.csrf, 'put')
        self.assertEqual((refused.status_code, refused.json['code']), (409, 'profile_change_confirmation_required'))
        saved = self.post('pipeline-settings', {'values': values, 'version': current['version'],
                                                'confirm_profile_change': True}, self.csrf, 'put')
        self.assertEqual(saved.status_code, 200)
        other = dict(saved.json['values'], holdout_days=21)          # not a cost field
        self.assertEqual(self.post('pipeline-settings', {'values': other, 'version': saved.json['version']},
                                   self.csrf, 'put').status_code, 200)
        audit = json.loads(self.rows("SELECT body FROM audit WHERE action='pipeline_settings' ORDER BY id")[0][0])
        self.assertEqual(audit['profile_changed'], ['fee_rate'])

    def test_manual_order_and_holdings_require_google_owner_session(self):
        routes = [('api/order/verify', {}), ('api/order/quote', {'symbol': '2330'}),
                  ('api/order/place', order()), ('api/live-console/sell-verify', {})]
        with patch.object(order_service, 'login') as login, \
                patch.object(order_service, 'get_quote') as quote, \
                patch.object(order_service, 'place_order') as place, \
                patch.object(order_service, 'broker_snapshot') as holdings:
            with self.store.tx() as db:
                db.execute("UPDATE session_owners SET email='other@example.test'")
            for path, payload in routes:
                self.assertEqual(self.post(path, payload, self.csrf).status_code, 403)
            self.assertEqual(self.client.get('/admin/api/live-console', base_url=ORIGIN).status_code, 403)
            self.client.delete_cookie('__Host-easystock_admin', domain='admin.example.com')
            for path, payload in routes:
                self.assertEqual(self.post(path, payload, self.csrf).status_code, 401)
            self.assertEqual(self.client.get('/admin/api/live-console', base_url=ORIGIN).status_code, 401)
            for call in (login, quote, place, holdings):
                call.assert_not_called()


if __name__ == '__main__':
    unittest.main()
