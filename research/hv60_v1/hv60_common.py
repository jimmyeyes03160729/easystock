"""HV60_V1 shared helpers (frozen preregistration + Amendment 1). Research only."""
import gzip, json, sqlite3, sys
from bisect import bisect_right
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'pkg'))
sys.path.insert(0, '/home/ubuntu/easystock')       # strategy_engine / paper_execution, read-only imports
from daytrade_learning.event_audit import timebase as TB  # noqa: E402

CUTOFF = TB.HARD_CUTOFF
EXP = Path('/home/ubuntu/easystock-history-expanded-data/raw')
HIST = Path('/home/ubuntu/easystock-history-data/raw')
DAILY_DB = '/home/ubuntu/easystock-learning-data/rebound/market-daily.sqlite'
OUT = ROOT / 'output'
WORK = ROOT / 'work'
GATE_START, GATE_END, GATE_MIN = '2024-12-25', '2026-08-27', 0.80
POOL_DAY = '2026-10-02'
TIER_MIN = 0.030
ENTRY_START, ENTRY_END = 9 * 3600 + 30 * 60, 11 * 3600 + 55 * 60
HORIZON_US = 60 * 60 * 1_000_000


def archive_days():
    days = set()
    for root in (EXP, HIST):
        if root.exists():
            days |= {p.name for p in root.iterdir() if p.is_dir() and len(p.name) == 10 and p.name <= CUTOFF}
    return sorted(days)


def pool():
    return sorted(f.name[:-8] for f in (EXP / POOL_DAY).glob('*.json.gz'))


def day_files(day, symbols):
    out = {}
    for root in (HIST, EXP):          # expanded archive wins on duplicates
        p = root / day
        if p.exists():
            for s in symbols:
                f = p / (s + '.json.gz')
                if f.exists():
                    out[s] = f
    return out


def coverage():
    syms = pool()
    days = [d for d in archive_days() if GATE_START <= d <= GATE_END]
    have = sum(len(day_files(d, syms)) for d in days)
    return have / (len(days) * len(syms)) if days and syms else 0.0, len(days), len(syms)


class Daily:
    """Official daily bars / references, strictly day <= CUTOFF, previous sessions only for the tier."""

    def __init__(self, symbols):
        want = set(symbols)
        c = sqlite3.connect('file:%s?mode=ro' % DAILY_DB, uri=True)
        self.bars = {}
        for s, d, h, l, cl, ref, ex in c.execute(
                'SELECT symbol, day, high, low, close, reference, exchange FROM bars WHERE day <= ? ORDER BY symbol, day', (CUTOFF,)):
            if s in want:
                self.bars.setdefault(s, []).append((d, h, l, cl, ref, ex))
        self.tpex = {}
        for s, d, ref in c.execute('SELECT symbol, day, reference FROM tpex_next_reference WHERE day <= ? ORDER BY symbol, day', (CUTOFF,)):
            if s in want:
                self.tpex.setdefault(s, []).append((d, ref))
        c.close()
        self.days = {s: [r[0] for r in rows] for s, rows in self.bars.items()}
        self.tdays = {s: [r[0] for r in rows] for s, rows in self.tpex.items()}

    def trailing_range(self, sym, day):
        rows = self.bars.get(sym)
        if not rows:
            return None
        k = bisect_right(self.days[sym], day) - 1
        if k >= 0 and rows[k][0] == day:
            k -= 1                     # strictly before the decision day
        prev = rows[max(0, k - 19):k + 1]
        if len(prev) < 20 or any(r[3] is None or r[3] <= 0 for r in prev):
            return None
        return sum((r[1] - r[2]) / r[3] for r in prev) / 20.0

    def reference(self, sym, day):
        rows = self.bars.get(sym) or []
        k = bisect_right(self.days.get(sym, []), day) - 1
        if k >= 0 and rows[k][0] == day and rows[k][5] == 'TWSE' and rows[k][4]:
            return rows[k][4]
        t = self.tpex.get(sym)
        if t:
            j = bisect_right(self.tdays[sym], day) - 1
            if j >= 0 and t[j][0] == day:
                j -= 1                 # value published on the previous session
            if j >= 0 and t[j][1]:
                return t[j][1]
        return None


def load_ticks(path, day, d0):
    d = json.loads(gzip.decompress(path.read_bytes()))
    if d.get('date') != day or d.get('symbol') != path.name[:-8]:
        raise ValueError('archive_identity_mismatch')
    t = d['ticks']
    n = len(t['ts'])
    bid = t.get('bid_price') or [0.0] * n
    ask = t.get('ask_price') or [0.0] * n
    tus, tp, tb, ta = [], [], [], []
    for i, ns in enumerate(t['ts']):
        us = int(ns) // 1000
        sec = (us - d0) // 1_000_000
        if 32400 <= sec < 48600:
            tus.append(us)
            tp.append(float(t['close'][i]))
            tb.append(float(bid[i]))
            ta.append(float(ask[i]))
    return d['kbars'], tus, tp, tb, ta


def log(obj):
    print(json.dumps(obj, ensure_ascii=False), flush=True)


def now():
    return datetime.now().isoformat(timespec='seconds')
