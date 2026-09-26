"""Deterministic entry risk, with dated premarket data and fresh index quotes."""
import math
from datetime import datetime, timezone, timedelta

TPE = timezone(timedelta(hours=8))


def premarket_context(brief, now):
    if not isinstance(brief, dict) or brief.get('scan_date') != now.astimezone(TPE).date().isoformat():
        return 'RED', 'premarket_missing_or_stale'
    try:
        score = float(brief['base_risk_score'])
        if not math.isfinite(score) or not 0 <= score <= 100:
            raise ValueError('invalid_score')
    except (KeyError, ValueError, TypeError):
        return 'RED', 'premarket_base_score_missing'
    return ('RED' if score >= 65 else 'GREEN' if score <= 35 else 'YELLOW'), 'valid'


def snapshot_risk(snapshot, now, *, max_age=90, yellow_pct=-1.0, red_pct=-2.0):
    if not red_pct < yellow_pct <= 0:
        raise ValueError('invalid_index_risk_thresholds')
    get = snapshot.get if isinstance(snapshot, dict) else lambda k: getattr(snapshot,k,None)
    try:
        ts = get('ts')
        if ts is not None:
            ts = float(ts)
            divisor = 1e9 if abs(ts) >= 1e17 else 1e6 if abs(ts) >= 1e14 else 1e3 if abs(ts) >= 1e11 else 1
            at = datetime.fromtimestamp(ts/divisor, timezone.utc).astimezone(TPE)
        else:
            at = datetime.fromisoformat(str(get('datetime')))
            if at.tzinfo is None:
                at = at.replace(tzinfo=TPE)
        change = float(get('change_rate'))
        age = (now-at).total_seconds()
        if not math.isfinite(change) or at.astimezone(TPE).date() != now.astimezone(TPE).date() or not 0 <= age <= max_age:
            raise ValueError('stale_index_quote')
        return dict(level='RED' if change <= red_pct else 'YELLOW' if change <= yellow_pct else 'GREEN',
                    valid=True, observed_at=at.isoformat(), change_pct=change, reason='index_snapshot')
    except (ValueError, TypeError, OverflowError, OSError):
        return dict(level='RED', valid=False, reason='index_quote_missing_or_stale')


def combine(base, live):
    rank = {'GREEN':0, 'YELLOW':1, 'RED':2}
    return max((base, live), key=lambda x: rank.get(x,2))
