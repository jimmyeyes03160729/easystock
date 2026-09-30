"""Small, private and bounded market-gate snapshot for next-day verification."""

import json
import math
from datetime import date, datetime

from .health import TPE, aggregate, atomic, data_dir, read_json, timestamp

SOURCES = ('shioaji', 'esun')
REASONS = ('market_risk_red', 'market_data_unavailable')
CONDITIONS = ('no_fresh_market_data', 'fresh_live_red',
              'premarket_red_pending_confirmation', 'recent_risk_pending_confirmation',
              'fresh_live_green', 'fresh_live_yellow')


def _date(value):
    try:
        return date.fromisoformat(value).isoformat()
    except (TypeError, ValueError):
        return None


def _count(value):
    return min(value, 1_000_000_000) if type(value) is int and value >= 0 else 0


def _source(value):
    item = value if isinstance(value, dict) else {}
    at = timestamp(item.get('quote_at'))
    seconds = item.get('age_seconds')
    return {
        'status': item.get('status') if item.get('status') in ('HEALTHY', 'STALE', 'UNAVAILABLE') else 'UNKNOWN',
        'quote_at': at.isoformat() if at else None,
        'age_seconds': seconds if type(seconds) in (int, float) and math.isfinite(seconds) and 0 <= seconds <= 1_000_000 else None,
        'usable': item.get('usable') is True,
    }


def save_gate(gate, *, now, premarket_date, model_ready, radar_candidate_count, block_counts):
    """Best effort: diagnostics never change the entry decision or stop the engine."""
    try:
        rows = gate.get('sources') or {}
        sources = {name: _source(rows.get(name)) for name in SOURCES}
        payload = {
            'checked_at': now.astimezone(TPE).isoformat(),
            'market_level': gate.get('level') if gate.get('level') in ('GREEN', 'YELLOW', 'RED', 'UNKNOWN') else 'UNKNOWN',
            'market_condition_reason': gate.get('market_condition_reason') if gate.get('market_condition_reason') in CONDITIONS else 'no_fresh_market_data',
            'data_health': gate.get('data_health') if gate.get('data_health') in ('HEALTHY', 'DEGRADED', 'UNAVAILABLE') else 'UNKNOWN',
            'gate_reason': gate.get('gate_reason') if gate.get('gate_reason') in (*REASONS, 'market_risk_pass') else 'market_data_unavailable',
            'selected_source': gate.get('selected_source') if gate.get('selected_source') in SOURCES else None,
            'premarket_date': _date(premarket_date),
            'premarket_level': gate.get('premarket_level') if gate.get('premarket_level') in ('GREEN', 'YELLOW', 'RED', 'UNKNOWN') else 'UNKNOWN',
            'premarket_reason': gate.get('premarket_reason') if gate.get('premarket_reason') in ('valid', 'premarket_missing_or_stale', 'premarket_invalid') else 'premarket_invalid',
            'model_ready': bool(model_ready),
            'radar_candidate_count': _count(radar_candidate_count),
            'entry_block_evaluations': {name: _count(block_counts.get(name)) for name in REASONS},
            'sources': sources,
        }
        atomic(data_dir() / 'market-gate.json', payload)
    except (OSError, TypeError, ValueError, AttributeError):
        pass


def read_gate():
    row = read_json(data_dir() / 'market-gate.json')
    checked = timestamp(row.get('checked_at'))
    if not checked:
        return {'status': 'not_observed'}
    now = datetime.now(TPE)
    raw_sources = row.get('sources') if isinstance(row.get('sources'), dict) else {}
    raw_counts = row.get('entry_block_evaluations') if isinstance(row.get('entry_block_evaluations'), dict) else {}
    return {'status': 'current' if 0 <= (now - checked).total_seconds() <= 180 else 'stale',
            'checked_at': checked.isoformat(),
            'market_level': row.get('market_level') if row.get('market_level') in ('GREEN', 'YELLOW', 'RED', 'UNKNOWN') else 'UNKNOWN',
            'market_condition_reason': row.get('market_condition_reason') if row.get('market_condition_reason') in CONDITIONS else 'no_fresh_market_data',
            'data_health': row.get('data_health') if row.get('data_health') in ('HEALTHY', 'DEGRADED', 'UNAVAILABLE') else 'UNKNOWN',
            'gate_reason': row.get('gate_reason') if row.get('gate_reason') in (*REASONS, 'market_risk_pass') else 'market_data_unavailable',
            'selected_source': row.get('selected_source') if row.get('selected_source') in SOURCES else None,
            'premarket_date': _date(row.get('premarket_date')),
            'premarket_level': row.get('premarket_level') if row.get('premarket_level') in ('GREEN', 'YELLOW', 'RED', 'UNKNOWN') else 'UNKNOWN',
            'premarket_reason': row.get('premarket_reason') if row.get('premarket_reason') in ('valid', 'premarket_missing_or_stale', 'premarket_invalid') else 'premarket_invalid',
            'model_ready': row.get('model_ready') is True,
            'radar_candidate_count': _count(row.get('radar_candidate_count')),
            'entry_block_evaluations': {name: _count(raw_counts.get(name)) for name in REASONS},
            'sources': {name: _source(raw_sources.get(name)) for name in SOURCES}}


if __name__ == '__main__':
    _, health = aggregate()
    providers = {name: {'status': health['providers'][name]['status'],
                        'age_seconds': health['providers'][name].get('age_seconds')}
                 for name in SOURCES}
    print(json.dumps({'market_gate': read_gate(), 'providers': providers}, ensure_ascii=False))
