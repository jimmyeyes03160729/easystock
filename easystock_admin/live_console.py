"""Owner console state and audit. Separate from Paper/Research; no execution engine."""
import json
import re
import secrets
import time
from datetime import datetime
from .store import Conflict, Denied, digest


def live_ordering_enabled():
    # Schema migration / Paper Store initialization must not initialize a broker SDK.
    from .order_service import live_ordering_enabled as enabled
    return enabled()


def initialize(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS live_trade_positions(symbol TEXT PRIMARY KEY,body TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS live_trade_orders(client_order_id TEXT PRIMARY KEY,body TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS live_trade_deals(deal_id TEXT PRIMARY KEY,body TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS live_trade_events(id INTEGER PRIMARY KEY,at REAL NOT NULL,owner TEXT NOT NULL,action TEXT NOT NULL,body TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS live_console_state(id INTEGER PRIMARY KEY CHECK(id=1),mode TEXT NOT NULL,kill INTEGER NOT NULL,snapshot TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS live_sell_tickets(ticket TEXT PRIMARY KEY,owner TEXT NOT NULL,session TEXT NOT NULL,expires REAL NOT NULL,body TEXT NOT NULL);
    INSERT OR IGNORE INTO live_console_state VALUES(1,'OFF',0,'{}');
    ''')


class LiveConsole:
    def __init__(self, store, broker, owner):
        self.store, self.broker, self.owner = store, broker, owner

    def audit(self, action, values, db=None):
        # Explicit fields only, never browser bodies / SDK exceptions / credentials.
        event = {k: values.get(k) for k in ('symbol', 'quantity', 'client_order_id', 'result', 'mode', 'kill')}
        if db is None:
            with self.store.tx() as connection:
                self.audit(action, event, connection)
            return
        db.execute('INSERT INTO live_trade_events(at,owner,action,body) VALUES(?,?,?,?)',
                   (time.time(), self.owner, action, json.dumps(event)))
        self.store._audit(db, self.owner, action, event)

    def refresh(self):
        try:
            data = self.broker.broker_snapshot()
        except Exception:
            data = {'connected':False,'authenticated':False,'complete':False,'positions':[],
                    'orders':[],'deals':[],'error_code':'broker_sync_unavailable'}
        with self.store.tx() as db:
            fingerprint = data.get('account_fingerprint')
            pinned = db.execute("SELECT value FROM meta WHERE key='live_broker_account'").fetchone()
            if data.get('complete') and isinstance(fingerprint,str) and len(fingerprint)==24:
                if pinned and pinned[0] != fingerprint:
                    data.update(complete=False, error_code='broker_account_mismatch')
                    for row in data.get('positions',[]): row['available_to_sell'] = None
                elif not pinned:
                    db.execute("INSERT INTO meta VALUES('live_broker_account',?)", (fingerprint,))
            else:
                data['complete'] = False
            # Compare, never overwrite expected positions/deals from an unrelated account.
            local_positions = sorted((r[0], json.loads(r[1]).get('quantity')) for r in db.execute('SELECT symbol,body FROM live_trade_positions'))
            broker_positions = sorted((r['symbol'], r['quantity']) for r in data.get('positions', []) if r['quantity'])
            local_orders = {r[0]: json.loads(r[1]) for r in db.execute('SELECT client_order_id,body FROM live_trade_orders')}
            known_ids = {r.get('broker_order_id') for r in local_orders.values()}
            unmatched_orders = any(r['order_id'] not in known_ids for r in data.get('orders', []))
            broker_orders = {r['order_id']:r for r in data.get('orders', [])}
            order_mismatch = False
            for local in local_orders.values():
                remote = broker_orders.get(local.get('broker_order_id'), {})
                expected_qty = local.get('quantity', 0) * (1 if local.get('is_odd_lot') else 1000)
                if (local.get('symbol'), local.get('action'), expected_qty, local.get('price'),
                    str(local.get('status')).lower(), local.get('filled_qty', 0)) != (
                    remote.get('symbol'), remote.get('side'), remote.get('qty'), remote.get('price'),
                    str(remote.get('status')).lower(), remote.get('filled_qty')):
                    order_mismatch = True
            local_deal_rows = {r[0]:json.loads(r[1]) for r in db.execute('SELECT deal_id,body FROM live_trade_deals')}
            local_deals = set(local_deal_rows)
            broker_deals = {r['deal_id'] for r in data.get('deals', [])}
            deal_fields = ('symbol','side','qty','price','deal_time')
            deal_mismatch = any(tuple(local_deal_rows.get(r['deal_id'],{}).get(k) for k in deal_fields) != tuple(r.get(k) for k in deal_fields) for r in data.get('deals',[]))
            unresolved = any(r.get('status') in ('submitting', 'unknown') or r.get('broker_order_id') not in {b['order_id'] for b in data.get('orders', [])} for r in local_orders.values())
            data['reconciled'] = bool(data.get('complete') and local_positions == broker_positions and not unmatched_orders and not order_mismatch and local_deals == broker_deals and not deal_mismatch and not unresolved)
            for row in data.get('orders', []):
                row['client_order_id'] = next((k for k,v in local_orders.items() if v.get('broker_order_id') == row['order_id']), None)
            db.execute('UPDATE live_console_state SET snapshot=? WHERE id=1', (json.dumps(data),))
        return self.state()

    def state(self):
        with self.store.tx() as db:
            mode, kill, raw = db.execute('SELECT mode,kill,snapshot FROM live_console_state WHERE id=1').fetchone()
        data = json.loads(raw)
        try:
            age = time.time() - datetime.fromisoformat(data['updated_at']).timestamp()
            fresh = 0 <= age <= 30
        except (KeyError, ValueError, TypeError):
            fresh = False
        ready = bool(fresh and data.get('connected') and data.get('authenticated') and data.get('reconciled'))
        allowed = live_ordering_enabled() and ready and not kill
        return {'mode': mode, 'kill_switch': bool(kill), 'live_auto_enabled': mode == 'LIVE AUTO' and allowed,
                'auto_state': 'AUTO PAUSED' if not ready or kill or (mode == 'LIVE AUTO' and not allowed) else ('READY (skeleton only)' if mode == 'LIVE AUTO' else 'OFF'),
                'reconciliation': 'OK' if ready else 'RECONCILIATION REQUIRED', 'broker_fresh': fresh,
                'activation_allowed': allowed, 'ordering_guard': live_ordering_enabled(),
                'execution_engine': False, 'broker': data}

    def change(self, data):
        if set(data) == {'mode'} and data['mode'] in ('OFF', 'SHADOW', 'PAPER', 'LIVE AUTO'):
            if data['mode'] == 'LIVE AUTO' and not self.state()['activation_allowed']:
                raise Denied('LIVE AUTO guard／同步／對帳未通過。')
            with self.store.tx() as db:
                db.execute('UPDATE live_console_state SET mode=? WHERE id=1', (data['mode'],))
                self.audit('live_mode', {**data, 'result': 'saved'}, db)
        elif set(data) == {'kill'} and isinstance(data['kill'], bool):
            with self.store.tx() as db:
                db.execute('UPDATE live_console_state SET kill=? WHERE id=1', (int(data['kill']),))
                self.audit('live_kill_switch', {**data, 'result': 'new_auto_orders_blocked' if data['kill'] else 'released'}, db)
        else:
            raise ValueError('實盤控制欄位不正確。')
        return self.state()

    def authorize_auto(self):
        """Skeleton guard only. Does not place orders or bind Research/Paper strategies."""
        if not self.state()['live_auto_enabled']:
            raise Denied('新 AUTO 委託已阻擋。')

    def sell_check(self, order):
        state = self.refresh()
        rows = state['broker'].get('positions', [])
        row = next((p for p in rows if p['symbol'] == order['symbol']), {})
        shares = order['quantity'] * (1 if order['is_odd_lot'] else 1000)
        available = row.get('available_to_sell')
        if not state['broker_fresh'] or not state['broker'].get('complete') or available is None or shares > available:
            raise Denied('券商可賣數量不足或尚未確認；請重新同步。')
        return available, {**state['broker'].get('account', {}), 'fingerprint':state['broker'].get('account_fingerprint')}

    def verify_sell(self, data, session):
        from .order_service import validate_order
        if set(data) != {'client_order_id','symbol','action','price','quantity','is_odd_lot'} or data['action'] != 'SELL':
            raise ValueError('只接受明確 SELL 驗證。')
        order = validate_order(data['symbol'], data['action'], data['price'], data['quantity'], data['is_odd_lot'])
        if not re.fullmatch(r'[A-Za-z0-9-]{16,64}', str(data['client_order_id'])):
            raise ValueError('委託識別碼不正確。')
        self.broker.login()  # Existing server-side broker re-auth, never supplied browser keys.
        quote = self.broker.get_quote(order['symbol'])
        self.check_quote(quote)
        available, account = self.sell_check(order)
        ticket = secrets.token_urlsafe(32)
        ticket_body = {**order, 'client_order_id': data['client_order_id'], 'account': account}
        with self.store.tx() as db:
            db.execute('DELETE FROM live_sell_tickets WHERE expires<?', (time.time(),))
            db.execute('INSERT INTO live_sell_tickets VALUES(?,?,?,?,?)', (digest(ticket), self.owner, digest(session), time.time()+60, json.dumps(ticket_body)))
            self.audit('live_sell_verify', {**ticket_body, 'result': 'verified'}, db)
        return {'verification_id': ticket, 'expires_in': 60, 'available_to_sell': available,
                'account': account, 'quote': quote, 'notional': order['price'] * order['quantity'] * (1 if order['is_odd_lot'] else 1000)}

    @staticmethod
    def check_quote(quote):
        quote_at = quote.get('quote_at')
        try:
            age = time.time() - datetime.fromisoformat(quote_at).timestamp()
        except (TypeError, ValueError):
            age = float('inf')
        if not 0 <= age <= 30:
            raise Denied('行情時間無法確認，禁止賣出。')

    @staticmethod
    def reserved_shares(db, symbol):
        reserved = 0
        for (raw,) in db.execute("SELECT request FROM order_requests WHERE status IN ('submitting','submitted','failed')"):
            prior = json.loads(raw)
            if prior['symbol'] == symbol and prior['action'] == 'SELL':
                reserved += prior['quantity'] * (1 if prior['is_odd_lot'] else 1000)
        return reserved

    def before_submit(self, order):
        self.check_quote(self.broker.get_quote(order['symbol']))
        available, _ = self.sell_check(order)
        with self.store.tx() as db:
            if self.reserved_shares(db, order['symbol']) > available:
                raise Denied('最新券商額度不足以涵蓋已保留 SELL，禁止送出。')

    def reserve_live(self, client_id, order):
        def guard(db):
            db.execute('INSERT INTO live_trade_orders VALUES(?,?)', (client_id, json.dumps({**order,'status':'submitting'})))
            self.audit('live_order_submit', {**order,'client_order_id':client_id,'result':'reserved'}, db)
        return guard

    def reservation_guard(self, data, order, session):
        available, account = self.sell_check(order)  # Fresh backend truth again immediately before reserve.
        if data.get('confirm_sell') != 'SELL' or data.get('confirm_account') != account.get('account_id'):
            raise Denied('需要再次確認 SELL 與遮罩帳戶。')
        def guard(db):
            row = db.execute('SELECT owner,session,expires,body FROM live_sell_tickets WHERE ticket=?', (digest(str(data.get('sell_verification_id',''))),)).fetchone()
            expected = {**order, 'client_order_id': data['client_order_id'], 'account': account}
            if not row or row[0] != self.owner or row[1] != digest(session) or row[2] < time.time() or json.loads(row[3]) != expected:
                raise Denied('賣出驗證已過期或委託已變更。')
            # Serialize cross-worker reservations. Conservatively retain unknown/submitted reservations;
            # ambiguous broker outcome must never allow a second sell or a retry.
            reserved = self.reserved_shares(db, order['symbol'])
            shares = order['quantity'] * (1 if order['is_odd_lot'] else 1000)
            if shares + reserved > available:
                raise Denied('已保留委託後可賣數量不足。')
            db.execute('DELETE FROM live_sell_tickets WHERE ticket=?', (digest(data['sell_verification_id']),))
            db.execute('INSERT INTO live_trade_orders VALUES(?,?)', (data['client_order_id'], json.dumps({**order,'status':'submitting'})))
            self.audit('live_sell_submit', {**expected, 'result': 'reserved'}, db)
        return guard

    def result(self, client_id, order, result, status):
        from .broker_read import identity
        body = {**order, 'status': status, 'broker_order_id': identity(result['order_id']) if result.get('order_id') else None}
        with self.store.tx() as db:
            db.execute('INSERT OR REPLACE INTO live_trade_orders VALUES(?,?)', (client_id,json.dumps(body)))
            self.audit('live_order_result', {**order, 'client_order_id': client_id, 'result': status}, db)
