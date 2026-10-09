"""Five-level BidAsk archive: non-blocking record, day files, seal manifest, NAS-confirmed prune only."""
import gzip
import json
import queue
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from market_data import bidask_archive as A  # noqa: E402

TPE = timezone(timedelta(hours=8))


class Q:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def quote(sec=0):
    return Q(code='2330', datetime=datetime(2026, 10, 12, 9, 0, sec), bid_price=[1000, 999, 998, 997, 996],
             bid_volume=[5, 4, 3, 2, 1], ask_price=[1001, 1002, 1003, 1004, 1005], ask_volume=[1, 2, 3, 4, 5],
             diff_bid_vol=[0] * 5, diff_ask_vol=[1, 0, 0, 0, 0], simtrade=False, suspend=False)


def test_record_and_drain_write_one_row_per_quote(tmp_path):
    r = A.Recorder(tmp_path, now=lambda: datetime(2026, 10, 12, 9, 0, 1, tzinfo=TPE))
    for s in range(3):
        r.record('2330', quote(s))
    assert r.drain(None) == 3
    (f,) = (tmp_path / 'raw' / '2026-10-12').glob('bidask-*.jsonl.gz')
    rows = [json.loads(x) for x in gzip.open(f, 'rt')]
    assert len(rows) == 3 and rows[0]['bid_price'] == [1000, 999, 998, 997, 996] and rows[0]['ask_volume'][4] == 5
    assert rows[2]['ts'] == '2026-10-12T09:00:02'


def test_record_never_raises_or_blocks(tmp_path):
    r = A.Recorder(tmp_path)
    r.q = queue.Queue(maxsize=1)
    r.record('2330', quote())
    r.record('2330', quote())                         # full -> dropped, no exception
    r.record('2330', object())                        # odd object -> still no exception (queue full)
    assert r.dropped == 2 and r.errors == 0


def _day(tmp_path, day):
    r = A.Recorder(tmp_path, now=lambda: datetime.fromisoformat(day + 'T09:00:00+08:00'))
    r.record('2330', quote())
    r.drain(None)
    return tmp_path / 'raw' / day


def test_seal_writes_manifest_and_refuses_today(tmp_path):
    _day(tmp_path, '2026-10-12')
    out = A.seal(tmp_path, '2026-10-12', '2026-10-13')
    assert out['status'] == 'sealed' and out['rows'] == 1
    d = tmp_path / 'raw' / '2026-10-12'
    assert (d / 'COMPLETE').read_text().strip() == A.sha256(d / 'MANIFEST.json')
    assert A.seal(tmp_path, '2026-10-12', '2026-10-13')['status'] == 'already_sealed'
    try:
        A.seal(tmp_path, '2026-10-13', '2026-10-13')
        assert False
    except SystemExit:
        pass


def test_prune_only_old_sealed_days_with_matching_manifest(tmp_path):
    d = _day(tmp_path, '2026-10-12')
    A.seal(tmp_path, '2026-10-12', '2026-10-13')
    sha = A.sha256(d / 'MANIFEST.json')
    assert A.prune(tmp_path, '2026-10-12', sha, date(2026, 10, 16)) == 'too_recent'
    assert A.prune(tmp_path, '2026-10-12', 'x' * 64, date(2026, 10, 20)) == 'manifest_mismatch'
    assert d.exists()
    assert A.prune(tmp_path, '2026-10-12', sha, date(2026, 10, 17)) == 'pruned'
    assert not d.exists()
    _day(tmp_path, '2026-10-13')
    assert A.prune(tmp_path, '2026-10-13', sha, date(2026, 10, 30)) == 'not_sealed'
    assert A.prune(tmp_path, '../x', sha, date(2026, 10, 30)) in ('not_a_day_dir', 'too_recent')
