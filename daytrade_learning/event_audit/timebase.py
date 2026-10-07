"""Frozen time conventions, universe and chronological test windows."""
from __future__ import annotations

from datetime import datetime, timedelta

EPOCH = datetime(1970, 1, 1)
HARD_CUTOFF = '2026-10-02'

SESSION_START_SEC = 9 * 3600            # 09:00
SESSION_END_SEC = 13 * 3600 + 30 * 60   # 13:30
ENTRY_START_SEC = 9 * 3600 + 30 * 60    # 09:30
ENTRY_END_SEC = 12 * 3600 + 30 * 60     # 12:30 (exclusive)
FORCE_EXIT_SEC = 12 * 3600 + 55 * 60    # 12:55

CORE_UNIVERSE = tuple(
    '1101 1301 1303 1312 1314 1326 1409 1605 1802 2002 2301 2303 2313 2317 2324 2327 '
    '2330 2337 2344 2356 2408 2409 2426 2449 2481 2489 2492 2609 2610 2615 2618 2634 '
    '3037 3189 3231 3481 4958 6116 6505 6770 8039 8150'.split())

# frozen five chronological test windows (entry_edge_audit WFA schedule)
FOLD_WINDOWS = (
    (1, '2024-12-25', '2025-04-30'),
    (2, '2025-05-02', '2025-08-29'),
    (3, '2025-09-01', '2025-12-26'),
    (4, '2025-12-29', '2026-05-05'),
    (5, '2026-05-06', '2026-08-27'),
)
DISCOVERY_END = '2024-12-24'


def ns_to_naive(ns) -> datetime:
    """The only legal conversion of an archive nanosecond timestamp."""
    return EPOCH + timedelta(microseconds=int(ns) // 1000)


def day0_us(day: str) -> int:
    return (datetime.fromisoformat(day) - EPOCH).days * 86400_000_000


def iso_from_us(us: int) -> str:
    return (EPOCH + timedelta(microseconds=us)).isoformat()


def second_of_day(us: int) -> int:
    return (us // 1_000_000) % 86400


def fold_for_date(day: str) -> int:
    """1-5 test windows, 0 discovery period, -1 after the frozen schedule."""
    for fid, a, b in FOLD_WINDOWS:
        if a <= day <= b:
            return fid
    return 0 if day <= DISCOVERY_END else -1
