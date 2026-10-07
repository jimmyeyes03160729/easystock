"""Complete-bar construction from 1m kbars, mirroring ``intraday_live._aggregate``."""
from __future__ import annotations

from .timebase import SESSION_START_SEC, SESSION_END_SEC


def build_minute_bars(kbars: dict, day0_us: int, end_limit_us: int | None = None) -> dict:
    """1m bars keyed by start second-of-day.

    Archive ``ts`` is the bar END; start = end - 60s.  Only bars starting in
    [09:00, 13:30) are kept.  ``end_limit_us`` keeps only bars already complete at
    that instant (the causal view used for lookahead rebuilds).
    """
    out = {}
    for i, ns in enumerate(kbars['ts']):
        end = int(ns) // 1000
        if end_limit_us is not None and end > end_limit_us:
            continue
        start = (end - day0_us) // 1_000_000 - 60
        if SESSION_START_SEC <= start < SESSION_END_SEC:
            out[start] = (float(kbars['Open'][i]), float(kbars['High'][i]), float(kbars['Low'][i]),
                          float(kbars['Close'][i]), float(kbars['Volume'][i]), end)
    return out


def group_complete(bars: dict, minutes: int) -> list[dict]:
    """Complete ``minutes``-bars aligned to 09:00; a bucket with a missing minute is dropped."""
    keys: dict[int, list[int]] = {}
    for start in bars:
        keys.setdefault((start - SESSION_START_SEC) // (minutes * 60), []).append(start)
    rows = []
    for k in sorted(keys):
        s0 = SESSION_START_SEC + k * minutes * 60
        if any((s0 + 60 * j) not in bars for j in range(minutes)):
            continue
        chunk = [bars[s0 + 60 * j] for j in range(minutes)]
        rows.append({'open': chunk[0][0], 'high': max(x[1] for x in chunk), 'low': min(x[2] for x in chunk),
                     'close': chunk[-1][3], 'volume': sum(x[4] for x in chunk),
                     '_end_sec': s0 + minutes * 60, '_max1m_end_us': max(x[5] for x in chunk)})
    return rows


def strip(rows: list[dict]) -> list[dict]:
    """Rows as the strategy sees them (no audit-only underscore fields)."""
    return [{k: v for k, v in r.items() if not k.startswith('_')} for r in rows]


def causal_rows_match(kbars: dict, day0_us: int, decision_us: int, rows_used: list[dict], minutes: int) -> bool:
    """Rebuild from ONLY bars complete at ``decision_us``; must equal the rows that were used."""
    rebuilt = strip(group_complete(build_minute_bars(kbars, day0_us, decision_us), minutes))
    return rebuilt == rows_used
