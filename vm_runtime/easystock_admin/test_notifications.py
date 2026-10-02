import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from contextlib import closing
from unittest.mock import Mock, patch

from easystock_admin.store import Store, Conflict
from easystock_admin import notifications as n
from trade_notifications import send_trade, send_daily_summary, event_identity
from daytrade_summary_push import build_daily_summary

TOKEN = '123456:' + 'x' * 35
LINE_USER = 'U' + '1' * 32


class NotificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / 'state.sqlite', {'min_price': 1, 'max_price': 100, 'max_gain_pct': 5})
        self.env = patch.dict(os.environ, {
            'LINE_CHANNEL_ACCESS_TOKEN': 'line-test-token', 'LINE_USER_ID': LINE_USER,
            'TELEGRAM_BOT_TOKEN': TOKEN, 'TELEGRAM_CHAT_ID': '1234567',
            'TELEGRAM_CONFIG_FILE': str(Path(self.tmp.name) / 'absent'),
            'LINE_CONFIG_FILE': str(Path(self.tmp.name) / 'absent-line'),
        }, clear=False)
        self.env.start()
        self.http = patch('trade_notifications.requests.post', side_effect=self.response)
        self.post = self.http.start()

    def tearDown(self):
        self.http.stop(); self.env.stop(); self.tmp.cleanup()

    @staticmethod
    def response(url, **kwargs):
        return Mock(status_code=200, headers={}, json=lambda: {'ok': True})

    def set_policy(self, **values):
        current = n.policy(self.store)
        body = {key: values.get(key, current[key]) for key in n.POLICY_FIELDS}
        return n.update(self.store, {**body, 'version': current['version']})

    def calls(self, platform):
        needle = 'api.line.me' if platform == 'line' else 'api.telegram.org'
        return [call for call in self.post.call_args_list if needle in call.args[0]]

    def test_line_entry_exit_on_without_groups_and_exactly_once(self):
        self.set_policy(line_trade=True)
        self.assertTrue(send_trade('entry', event_key='entry:1', store=self.store))
        self.assertFalse(send_trade('entry', event_key='entry:1', store=self.store))
        self.assertTrue(send_trade('exit', event_key='exit:1', store=self.store))
        self.assertEqual(len(self.calls('line')), 2)
        self.assertFalse(self.store.path.read_bytes().find(b'line_conversations') >= 0)

    def test_line_trade_off_sends_nothing(self):
        send_trade('entry', event_key='off', store=self.store)
        self.assertEqual(len(self.calls('line')), 0)

    def test_telegram_positive_personal_entry_exit(self):
        self.set_policy(telegram_trade=True)
        send_trade('entry', event_key='te', store=self.store)
        send_trade('exit', event_key='tx', store=self.store)
        self.assertEqual(len(self.calls('telegram')), 2)
        self.assertEqual(self.calls('telegram')[0].kwargs['json']['chat_id'], '1234567')

    def test_negative_or_group_only_telegram_is_not_configured(self):
        with patch.dict(os.environ, {'TELEGRAM_CHAT_ID': '-1001234567'}, clear=False):
            self.assertEqual(n.telegram_config(), ('', ''))
        with patch.dict(os.environ, {'TELEGRAM_CHAT_ID': '', 'TELEGRAM_USER_ID': '', 'TELEGRAM_GROUP_ID': '-1001234567'}, clear=False):
            self.assertEqual(n.telegram_config(), ('', ''))

    def test_channels_and_four_switches_are_independent(self):
        self.set_policy(line_trade=True, telegram_summary=True)
        send_trade('entry', event_key='independent', store=self.store)
        send_daily_summary('summary', day='2026-10-01', store=self.store)
        self.assertEqual(len(self.calls('line')), 1)
        self.assertEqual(len(self.calls('telegram')), 1)

    def test_summary_on_once_and_off_never(self):
        self.set_policy(line_summary=True, telegram_summary=True)
        self.assertTrue(send_daily_summary('summary', day='2026-10-01', store=self.store))
        self.assertFalse(send_daily_summary('summary', day='2026-10-01', store=self.store))
        self.assertEqual(len(self.calls('line')), 1); self.assertEqual(len(self.calls('telegram')), 1)
        self.set_policy(line_summary=False, telegram_summary=False)
        send_daily_summary('next', day='2026-10-02', store=self.store)
        self.assertEqual(self.post.call_count, 2)

    def test_line_has_retry_key_and_no_secret_in_state(self):
        self.set_policy(line_trade=True)
        send_trade('entry', event_key='retry', store=self.store)
        self.assertIn('X-Line-Retry-Key', self.calls('line')[0].kwargs['headers'])
        state = str(n.state(self.store))
        self.assertNotIn('line-test-token', state); self.assertNotIn(LINE_USER, state); self.assertNotIn(TOKEN, state)

    def test_event_identity_distinguishes_entry_and_exit(self):
        event = {'type': 'ENTRY', 'position': {'symbol': '2330', 'entry_time': '2026-10-01T09:30:00+08:00'}}
        self.assertNotEqual(event_identity(event, 'same'), event_identity({'type': 'EXIT', 'trade': event['position']}, 'same'))

    def test_policy_conflict_and_safe_defaults(self):
        self.assertFalse(any(n.policy(self.store)[key] for key in n.POLICY_FIELDS))
        self.set_policy(line_trade=True)
        with self.assertRaises(Conflict):
            n.update(self.store, {'line_trade': False, 'line_summary': False, 'telegram_trade': False, 'telegram_summary': False, 'version': 1})

    def test_summary_reads_canonical_paper_log_including_zero_trades(self):
        self.store.start_paper_trade(100000)
        with closing(sqlite3.connect(self.store.path)) as db, db:
            db.execute("UPDATE paper_trade_settings SET start_date='2026-10-01'")
        text = build_daily_summary(self.store.path, '2026-10-01')
        self.assertIn('今日模擬當沖 0 筆', text); self.assertIn('100,000.00', text)

    def test_retired_runtime_paths_and_messaging_side_effects_are_absent(self):
        root = Path(__file__).resolve().parents[1]
        repo = root.parent if root.name == 'vm_runtime' else root
        for name in ('telegram_queries.py', 'telegram_stock_bot.py', 'line_group_manager.py',
                     'stock_command_service.py', 'line_card_renderer.py'):
            self.assertFalse((root / name).exists(), name)
        premarket = (repo / 'vm_runtime/premarket_ai.py').read_text(encoding='utf-8')
        self.assertNotIn('send_daily_summary', premarket)
        self.assertNotIn('push_line_text', premarket)
        guardian = (repo / 'ops/guardian/notify.py').read_text(encoding='utf-8')
        self.assertNotIn('api.telegram.org', guardian)
        self.assertNotIn('api.line.me', guardian)


if __name__ == '__main__':
    unittest.main()
