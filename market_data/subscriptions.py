"""Shared Tick/BidAsk quota; asynchronous broker ACKs own slot lifecycle."""
from collections import Counter
import re
import threading
import time


class QuoteSubscriptions:
    def __init__(self, send, limit=190, tick_limit=170, book_limit=20,
                 hold_seconds=60, retry_seconds=30, clock=time.monotonic):
        self.send, self.clock = send, clock
        self.limit, self.tick_limit, self.book_limit = limit, tick_limit, book_limit
        self.hold_seconds, self.retry_seconds = hold_seconds, retry_seconds
        self.records = {}
        self.lock = threading.RLock()
        self.counters = Counter()

    def reserved(self):
        return sum(r['state'] != 'failed' for r in self.records.values())

    def request(self, symbol, kind):
        key, now = (symbol, kind), self.clock()
        with self.lock:
            r = self.records.get(key)
            if r and r.get('cancel_requested'):
                return False
            if r and r['state'] in ('pending', 'active'):
                return True
            if r and (r['state'] == 'cancelling' or now < r['retry_at']):
                return False
            kind_limit = self.tick_limit if kind == 'Tick' else self.book_limit
            count = sum(k[1] == kind and v['state'] != 'failed' for k, v in self.records.items())
            if self.reserved() >= self.limit or count >= kind_limit:
                self.counters['quota_wait'] += 1
                return False
            # Reserve BEFORE send: callback may run synchronously or on another thread.
            self.records[key] = dict(state='pending', since=now, retry_at=0)
        try:
            self.send(symbol, kind, True)
        except Exception:
            # A transport exception does not prove the broker rejected the request.
            self.counters['send_uncertain'] += 1
            return False
        return self.status(symbol, kind) in ('pending', 'active')

    def cancel(self, symbol, kind):
        key, now = (symbol, kind), self.clock()
        with self.lock:
            r = self.records.get(key)
            if not r:
                return
            if r['state'] == 'failed':
                del self.records[key]
                return
            if r['state'] == 'pending':
                # Subscribe and unsubscribe ACKs share a topic without an action ID.
                # Serialize them so a late subscribe ACK cannot free a cancel slot.
                r['cancel_requested'] = True
                return
            if r['state'] == 'cancelling' and now < r['retry_at']:
                return
            r.update(state='cancelling', retry_at=now + self.retry_seconds)
        try:
            self.send(symbol, kind, False)
        except Exception:
            self.counters['cancel_uncertain'] += 1

    def confirm_data(self, symbol, kind):
        cancel = False
        with self.lock:
            r = self.records.get((symbol, kind))
            if r and r['state'] == 'pending':
                r['state'] = 'active'
                cancel = r.get('cancel_requested', False)
        if cancel:
            self.cancel(symbol, kind)

    def event(self, response_code, event_code, info, event=''):
        info = str(info)
        topic = re.search(r'(TIC|QUO)/v1/STK/\*/(?:TSE|OTC)/(\d+)', info)
        if not topic:
            return
        key = (topic[2], 'Tick' if topic[1] == 'TIC' else 'BidAsk')
        cancel = False
        with self.lock:
            r = self.records.get(key)
            if not r:
                return
            absent = 'Subscription Not Found' in info
            embedded_error = "Response code: '400'" in info
            ok = str(response_code) == '200' and not embedded_error and 'Max Num Subscriptions' not in info
            if r['state'] == 'cancelling':
                if ok or absent:
                    del self.records[key]
                else:
                    self.counters['cancel_rejected'] += 1
            elif r['state'] == 'pending':
                if ok:
                    r['state'] = 'active'
                    cancel = r.get('cancel_requested', False)
                else:
                    r.update(state='failed', retry_at=self.clock() + self.retry_seconds)
                    self.counters['subscribe_rejected'] += 1
                    if r.get('cancel_requested'):
                        del self.records[key]
        if cancel:
            self.cancel(*key)

    def status(self, symbol, kind):
        with self.lock:
            return self.records.get((symbol, kind), {}).get('state', 'unselected')

    def retry_cancellations(self):
        with self.lock:
            pending = [key for key, r in self.records.items() if r['state'] == 'cancelling']
        for symbol, kind in pending:
            self.cancel(symbol, kind)

    def select_books(self, ranked_symbols, pinned=()):
        """Keep open positions and stable candidates; never free unconfirmed slots."""
        now, pinned = self.clock(), set(pinned)
        ranked_symbols = list(dict.fromkeys(ranked_symbols))
        with self.lock:
            held = [s for (s, k), r in self.records.items()
                    if k == 'BidAsk' and r['state'] in ('pending', 'active')
                    and s in ranked_symbols and now - r['since'] < self.hold_seconds]
            desired = list(dict.fromkeys(sorted(pinned) + held + ranked_symbols))[:max(self.book_limit, len(pinned))]
            existing = [s for s, k in self.records if k == 'BidAsk']
        for s in existing:
            if s not in desired:
                self.cancel(s, 'BidAsk')
        for s in desired:
            self.request(s, 'BidAsk')
        return desired

    def snapshot(self):
        with self.lock:
            counts = Counter(k + '_' + r['state'] for (_, k), r in self.records.items())
            return dict(limit=self.limit, tick_limit=self.tick_limit, book_limit=self.book_limit,
                        reserved=self.reserved(), counts=dict(counts), events=dict(self.counters))
