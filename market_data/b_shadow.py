"""Signal-only B comparison. No orders, account access, live saves or notifications."""
from collections import Counter, deque
from datetime import datetime, timedelta
import json
import math
from pathlib import Path
import zlib

from runway_v2.lanes import LaneSuite, SPECS, TPE, stamp


class JournalTail:
    """Follow complete CRC-checked gzip members; never reinterpret a partial member.

    An active journal is incident evidence, NOT a sealed replay or performance set.
    Starting from a bounded tail avoids reading a whole live day on the VM.
    """
    def __init__(self, path, tail_bytes=512 * 1024):
        self.path = Path(path)
        self.identity = self.path.stat().st_ino
        self.offset = max(0, self.path.stat().st_size - tail_bytes)
        self.buffer = b''
        self.started = self.offset == 0
        self.sequence = None
        self.errors = Counter()
        self.max_buffer = 16 * 1024 * 1024

    def poll(self):
        info = self.path.stat()
        if info.st_ino != self.identity or info.st_size < self.offset:
            raise ValueError('journal_rotated_or_truncated')
        with self.path.open('rb') as source:
            source.seek(self.offset)
            blob = source.read(4 * 1024 * 1024)
        self.offset += len(blob)
        self.buffer += blob
        if len(self.buffer) > self.max_buffer:
            raise ValueError('journal_buffer_limit')
        events = []
        while self.buffer:
            if not self.started:
                index = self.buffer.find(b'\x1f\x8b\x08')
                if index < 0:
                    self.buffer = self.buffer[-2:]
                    break
                self.buffer = self.buffer[index:]
            decoder = zlib.decompressobj(31)
            try:
                raw = decoder.decompress(self.buffer, 32 * 1024 * 1024)
                if decoder.unconsumed_tail:
                    raise ValueError('journal_member_expansion_limit')
            except zlib.error:
                if self.started:
                    raise ValueError('journal_member_corrupt')
                self.buffer = self.buffer[1:]
                continue
            if not decoder.eof:
                break
            self.buffer = decoder.unused_data
            self.started = True
            for line in raw.splitlines():
                event = json.loads(line)
                sequence = event['seq']
                if not isinstance(sequence, int) or isinstance(sequence, bool):
                    raise ValueError('invalid_journal_sequence')
                if self.sequence is not None and sequence != self.sequence + 1:
                    raise ValueError('journal_sequence_gap')
                self.sequence = sequence
                events.append(event)
        return events


class Cache:
    def __init__(self, bars):
        self.bars = bars

    def rows5(self, symbol):
        return self.bars.get(symbol, [])


def affordable_pool(rows, max_symbols=40):
    """Allocate data to affordable ordinary lots, NOT a looser strategy gate."""
    out = []
    for row in rows:
        symbol = str(row.get('symbol', ''))
        price = row.get('price')
        previous = row.get('previous_close')
        if (len(symbol) == 4 and symbol.isdigit() and not symbol.startswith('0')
                and isinstance(price, (int, float)) and not isinstance(price, bool)
                and math.isfinite(price) and 0 < price * 1000 <= 200000
                and isinstance(previous, (int, float)) and not isinstance(previous, bool)
                and math.isfinite(previous) and previous > 0
                and row.get('sector')):
            out.append(row)
    out.sort(key=lambda r: (-(r.get('amount_60s') or 0), str(r['symbol'])))
    return [str(r['symbol']) for r in out[:max_symbols]]


def esun_quote(payload, now):
    """Preserve source time/size. Partial levels and unknown units are not filled in."""
    if payload.get('provider') != 'esun' or payload.get('kind') != 'book':
        raise ValueError('wrong_source')
    symbol = payload.get('symbol')
    quote = payload.get('quote') or {}
    at = esun_stamp(quote.get('datetime'))
    received = esun_stamp(payload.get('received_at'))
    if (not at or not received or at.date() != now.date() or received > now
            or not 0 <= (now - at).total_seconds() <= 3
            or not 0 <= (now - received).total_seconds() <= 3):
        raise ValueError('stale_or_future_esun')
    lists = [quote.get(k) for k in ('bid_price', 'ask_price', 'bid_volume', 'ask_volume')]
    if not all(isinstance(xs, list) and len(xs) == 5 for xs in lists):
        raise ValueError('incomplete_esun_levels')
    for i, xs in enumerate(lists):
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                   and math.isfinite(v) and (v > 0 if i < 2 else v >= 0) for v in xs):
            raise ValueError('invalid_esun_values')
    bp, ap, _, _ = lists
    if (bp[0] >= ap[0] or any(bp[i] <= bp[i + 1] or ap[i] >= ap[i + 1] for i in range(4))
            or quote.get('simtrade') or quote.get('suspend')):
        raise ValueError('invalid_esun_book')
    return symbol, {**quote, 'datetime': at}


def esun_stamp(value):
    """Python 3.10-compatible explicit UTC parsing; never assume a naive zone."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value[:-1] + '+00:00' if value.endswith('Z') else value)
    except ValueError:
        return None
    return parsed.astimezone(TPE) if parsed.tzinfo is not None else None


class ShadowComparison:
    """Use the unchanged native signal function, never advance() or execution.

    OBI uses a within-provider ratio. Depth sizing stays blocked until the size
    unit contract is independently verified; no shadow positions or P&L exist.
    """
    def __init__(self, folder, symbols, now):
        self.symbols = set(symbols)
        self.suites = {}
        for name in ('shioaji_control', 'esun_shadow'):
            suite = LaneSuite(Path(folder) / (name + '.sqlite'), sender=lambda *_: None,
                              publisher=None, recorder=None, offline=True)
            suite.enabled = True
            suite._roll(now)
            self.suites[name] = suite
        self.acks = set()
        self.esun_connected = False
        self.source_states = {}
        self.source_clock_at = None
        self.last_source_receipt = None
        self.last_radar = None
        self.input_counts = Counter()
        self.rejects = {name: {lane: Counter() for lane in SPECS} for name in self.suites}
        self.signals = []
        self.evaluations = Counter()
        self.pairs = deque(maxlen=1000)
        self.pair_ids = set()
        self.latest_native_books = {}
        self.latest_esun_books = {}
        self.source_failed = False

    def ingest_source(self, event, now):
        received = stamp(event.get('received_at'))
        if not received or received > now or received.date() != now.date():
            raise ValueError('invalid_journal_receipt')
        self.last_source_receipt = max(received, self.last_source_receipt) if self.last_source_receipt else received
        kind, data = event['kind'], event['data']
        self.input_counts['shioaji_' + kind] += 1
        if kind == 'radar':
            at = stamp(data['now'])
            if not at or at > received or at.date() != now.date():
                raise ValueError('invalid_radar_clock')
            self.last_radar = data
            for suite in self.suites.values():
                suite.on_radar_update(data['rows'], Cache(data['bars']), data['previous_closes'],
                                      at, market=data['market'])
        elif kind == 'tick':
            at = stamp(data['datetime'])
            if not at or at > received or at.date() != now.date():
                self.input_counts['invalid_tick_time'] += 1
                return
            for suite in self.suites.values():
                suite.on_tick(data['symbol'], data['price'], at, data['tick_type'], data['volume'])
        elif kind == 'bidask':
            self.suites['shioaji_control'].on_bidask(data['symbol'], data['quote'])
            self.latest_native_books[data['symbol']] = data['quote']
            self._pair(data['symbol'])
        elif kind == 'clock':
            at = stamp(data['now'])
            if not at or at > received:
                raise ValueError('invalid_source_clock')
            self.source_clock_at = at
            self.source_states = data.get('subscription_states', {})
        elif kind == 'release':
            for suite in self.suites.values():
                suite.release_symbol(data['symbol'])

    def ingest_esun(self, payload, now):
        kind = payload.get('kind')
        self.input_counts['esun_' + str(kind)] += 1
        if kind == 'connected':
            self.esun_connected = True
        elif kind == 'ack':
            if payload.get('symbol') in self.symbols:
                self.acks.add(payload['symbol'])
                self.esun_connected = True
        elif kind in ('error', 'disconnected'):
            self.esun_connected = False
            self.acks.clear()
        elif kind == 'book':
            try:
                symbol, quote = esun_quote(payload, now)
            except ValueError as exc:
                self.input_counts[str(exc)] += 1
                return
            if symbol not in self.symbols or symbol not in self.acks or not self.esun_connected:
                self.input_counts['esun_without_ack'] += 1
                return
            self.suites['esun_shadow'].on_bidask(symbol, quote)
            self.latest_esun_books[symbol] = quote
            self._pair(symbol)

    def _pair(self, symbol):
        a, b = self.latest_native_books.get(symbol), self.latest_esun_books.get(symbol)
        if not a or not b:
            return
        ta, tb = stamp(a.get('datetime')), stamp(b.get('datetime'))
        if not ta or not tb or abs((ta - tb).total_seconds()) > .02:
            return
        key = (symbol, ta, tb)
        if key in self.pair_ids or len(self.pair_ids) >= 1000:
            return
        self.pair_ids.add(key)
        # Only exact, near-synchronous vectors support a sample unit comparison.
        keys = ('bid_price', 'ask_price', 'bid_volume', 'ask_volume')
        matching = all(a.get(k) == b.get(k) for k in keys)
        self.pairs.append({'symbol': symbol, 'native_at': ta.isoformat(),
                           'esun_at': tb.isoformat(), 'vectors_match': matching})

    def evaluate(self, now, measured=True):
        fresh_inputs = (not self.source_failed and self.last_source_receipt is not None
                        and 0 <= (now - self.last_source_receipt).total_seconds() <= 3)
        native_status_fresh = (self.source_clock_at is not None
                              and 0 <= (now - self.source_clock_at).total_seconds() <= 5)
        output = {}
        for name, suite in self.suites.items():
            suite._observation_statuses = {s: self.source_states.get(s, 'pending')
                if name == 'shioaji_control' else ('active' if self.esun_connected and s in self.acks
                                                  else 'failed') for s in self.symbols}
            for lane, spec in SPECS.items():
                if not spec['start'] <= now.strftime('%H:%M:%S') < spec['cutoff']:
                    output[name + ':' + lane] = {'window': 'outside_entry_window'}
                    continue
                reasons = Counter()
                ready = 0
                for symbol in sorted(self.symbols):
                    row = suite.rows.get(symbol)
                    signal = None
                    if not fresh_inputs:
                        reason = 'journal_clock_stale_or_failed'
                    elif name == 'shioaji_control' and not native_status_fresh:
                        reason = 'native_subscription_snapshot_stale'
                    elif (not row or not 0 <= now.timestamp() - row['observed_at'] <= 30):
                        reason = 'candidate_metadata_stale'
                    elif (not suite.market.get('valid') or not 0 <= now.timestamp() -
                          suite.market.get('observed_at', 0) <= 30 or suite.market.get('gate_action') == 'BLOCK'):
                        reason = '大盤風險資料不符'
                    else:
                        signal, reason = suite._signal(lane, symbol, now)
                        if signal and signal['direction'] == -1 and row.get('daytrade_short_allowed') is not True:
                            signal, reason = None, '未確認先賣後買資格'
                        if signal and signal['entry_price'] * 1000 > 200000:
                            signal, reason = None, 'whole_lot_over_200000'
                    if signal:
                        ready += 1
                        if measured:
                            self.signals.append({'at': now.isoformat(), 'arm': name, 'lane': lane,
                                'symbol': symbol, 'signal': signal, 'execution_allowed': False,
                                'paired_native_status_fresh': native_status_fresh,
                                'tick_source': 'shioaji', 'book_source': 'esun' if name == 'esun_shadow' else 'shioaji'})
                    else:
                        reasons[reason] += 1
                if measured:
                    self.rejects[name][lane].update(reasons)
                    self.evaluations[name + ':' + lane] += len(self.symbols)
                output[name + ':' + lane] = {'ready_signal_events': ready, 'rejects': dict(reasons),
                                             'paired_comparison_available': native_status_fresh and fresh_inputs}
        return output

    def close(self):
        for suite in self.suites.values():
            suite.worker.shutdown(wait=True)

    def coverage(self, now):
        """Raw same-pool availability, independent of market/strategy permission."""
        result = {}
        for name, suite in self.suites.items():
            ticks = books = joined = 0
            for symbol in self.symbols:
                tape = suite.tapes.get(symbol, [])
                tick = tape[-1] if tape and 0 <= (now - tape[-1][0]).total_seconds() <= 3 else None
                book = suite._book(symbol, now)
                ticks += tick is not None
                books += book is not None
                joined += bool(tick and book and abs((tick[0] - book['dt']).total_seconds()) <= 3)
            observed = suite.market.get('observed_at')
            result[name] = {'pool_symbols': len(self.symbols), 'fresh_tick_symbols': ticks,
                            'fresh_book_symbols': books, 'fresh_joined_symbols': joined,
                            'market_valid': bool(suite.market.get('valid')),
                            'market_gate_action': suite.market.get('gate_action'),
                            'market_age_seconds': now.timestamp() - observed if observed else None}
        return result

    def report(self):
        return {'mode': 'shadow_signal_only', 'signals': self.signals,
            'evaluations': dict(self.evaluations), 'input_counts': dict(self.input_counts),
            'rejects': {name: {lane: dict(c) for lane, c in lanes.items()} for name, lanes in self.rejects.items()},
            'unit_pair_samples': list(self.pairs), 'execution_allowed': False,
            'size_units_contract_verified': False, 'production_changed': False,
            'deployment_allowed': False, 'training_eligible': False}
