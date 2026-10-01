"""Point-in-time market evidence and the paper-entry safety gate."""
import math
from datetime import datetime, timedelta, timezone

TPE = timezone(timedelta(hours=8))
LEVELS = ('GREEN', 'YELLOW', 'RED')
RANK = {'GREEN': 0, 'YELLOW': 1, 'RED': 2}


def premarket_context(brief, now):
    """An outdated brief is unknown evidence, never evidence of a falling market."""
    if not isinstance(brief, dict) or brief.get('scan_date') != now.astimezone(TPE).date().isoformat():
        return 'UNKNOWN', 'premarket_missing_or_stale'
    try:
        generated = datetime.fromisoformat(str(brief['generated_at']))
        if generated.tzinfo is None or generated.astimezone(TPE).date() != now.astimezone(TPE).date():
            raise ValueError('stale_generated_at')
        score = float(brief['base_risk_score'])
        if not math.isfinite(score) or not 0 <= score <= 100:
            raise ValueError('invalid_score')
    except (KeyError, ValueError, TypeError):
        return 'UNKNOWN', 'premarket_invalid'
    return ('RED' if score >= 65 else 'GREEN' if score <= 35 else 'YELLOW'), 'valid'


def snapshot_risk(snapshot, now, *, source='shioaji', max_age=90, yellow_pct=-1.0, red_pct=-2.0):
    if not red_pct < yellow_pct <= 0:
        raise ValueError('invalid_index_risk_thresholds')
    get = snapshot.get if isinstance(snapshot, dict) else lambda key: getattr(snapshot, key, None)
    try:
        ts = get('ts')
        if ts is not None:
            ts = float(ts)
            divisor = 1e9 if abs(ts) >= 1e17 else 1e6 if abs(ts) >= 1e14 else 1e3 if abs(ts) >= 1e11 else 1
            clock = datetime.fromtimestamp(ts / divisor, timezone.utc)
            # Shioaji numeric ts encodes exchange-local clock time, like Kbars.
            # Attach Taipei once; other providers retain Unix epoch semantics.
            observed = (clock.replace(tzinfo=TPE) if source == 'shioaji'
                        else clock.astimezone(TPE))
        else:
            observed = datetime.fromisoformat(str(get('datetime')))
            if observed.tzinfo is None:
                # Shioaji emits exchange-local naive datetimes on some SDK versions.
                observed = observed.replace(tzinfo=TPE)
            observed = observed.astimezone(TPE)
        change = float(get('change_rate'))
        age = (now.astimezone(TPE) - observed).total_seconds()
        if not math.isfinite(change):
            raise ValueError('invalid_change')
        if observed.date() != now.astimezone(TPE).date() or not 0 <= age <= max_age:
            return dict(source=source, level='UNKNOWN', valid=False, data_health='STALE',
                        reason='index_quote_missing_or_stale', observed_at=observed.isoformat(),
                        age_seconds=round(age, 2))
        return dict(source=source, level='RED' if change <= red_pct else 'YELLOW' if change <= yellow_pct else 'GREEN',
                    valid=True, data_health='HEALTHY', observed_at=observed.isoformat(),
                    age_seconds=round(age, 2), change_pct=change, reason='index_snapshot')
    except (ValueError, TypeError, OverflowError, OSError):
        return dict(source=source, level='UNKNOWN', valid=False, data_health='UNAVAILABLE',
                    reason='index_quote_missing_or_stale')


def combine(base, live):
    """Compatibility helper; a fresh live reading supersedes the morning context."""
    return live if live in LEVELS else base if base in LEVELS else 'UNKNOWN'


class MarketGate:
    """Require two fresh confirmations for each step down from RED."""

    def __init__(self, confirmations=2):
        self.level = 'UNKNOWN'
        self.confirmations = max(2, int(confirmations))
        self._candidate = None
        self._count = 0
        self._last_confirmation_quote = None

    def update(self, brief, sources, now):
        premarket, premarket_reason = premarket_context(brief, now)
        usable = [risk for risk in sources.values() if risk.get('valid') and risk.get('level') in LEVELS]
        health = ('HEALTHY' if len(usable) == len(sources) and usable else
                  'DEGRADED' if usable else
                  'UNAVAILABLE' if sources else 'UNKNOWN')
        if not usable:
            self._candidate, self._count, self._last_confirmation_quote = None, 0, None
            effective, live = 'UNKNOWN', 'UNKNOWN'
            reason = 'market_data_unavailable'
            selected = {}
        else:
            live = max((risk['level'] for risk in usable), key=RANK.__getitem__)
            selected = max((risk for risk in usable if risk['level'] == live),
                           key=lambda risk: risk['observed_at'])
            if self.level == 'UNKNOWN':
                self.level = premarket if premarket in LEVELS else live
            if live == 'RED' or RANK[live] > RANK[self.level]:
                self.level, self._candidate, self._count, self._last_confirmation_quote = live, None, 0, None
            elif RANK[live] < RANK[self.level]:
                if self._candidate == live:
                    if selected['observed_at'] != self._last_confirmation_quote:
                        self._count += 1
                        self._last_confirmation_quote = selected['observed_at']
                else:
                    self._candidate, self._count = live, 1
                    self._last_confirmation_quote = selected['observed_at']
                if self._count >= self.confirmations:
                    self.level = LEVELS[RANK[self.level] - 1]
                    self._candidate, self._count, self._last_confirmation_quote = None, 0, None
            else:
                self._candidate, self._count, self._last_confirmation_quote = None, 0, None
            effective = self.level
            reason = 'market_risk_red' if effective == 'RED' else 'market_risk_pass'
        condition_reason = ('no_fresh_market_data' if not usable else
                            'fresh_live_red' if live == 'RED' else
                            'premarket_red_pending_confirmation' if effective == 'RED' else
                            'recent_risk_pending_confirmation' if effective != live else
                            'fresh_live_' + live.lower())
        data_reason = ('all_sources_fresh' if health == 'HEALTHY' else
                       'one_source_fresh' if health == 'DEGRADED' else
                       'market_data_unavailable')
        return dict(level=effective, market_risk=effective, live_risk=live,
                    market_condition_reason=condition_reason, data_reason=data_reason,
                    selected_source=selected.get('source'),
                    premarket_level=premarket, premarket_risk=premarket,
                    premarket_health='HEALTHY' if premarket_reason == 'valid' else
                    'STALE' if premarket_reason == 'premarket_missing_or_stale' else 'UNAVAILABLE',
                    premarket_reason=premarket_reason, data_health=health,
                    gate_action='BLOCK' if effective in ('RED', 'UNKNOWN') else 'PASS',
                    gate_reason=reason, source=','.join(sorted(risk['source'] for risk in usable)),
                    source_count=len(usable), observed_at=selected.get('observed_at'),
                    quote_at=selected.get('observed_at'), received_at=now.isoformat(),
                    age_seconds=selected.get('age_seconds'), valid=bool(usable),
                    sources={name: dict(status=risk.get('data_health', 'UNKNOWN'),
                                        quote_at=risk.get('observed_at'), age_seconds=risk.get('age_seconds'),
                                        usable=bool(risk.get('valid')))
                             for name, risk in sources.items()})
