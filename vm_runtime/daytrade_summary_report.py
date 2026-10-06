"""Read-only intraday state parsing for the daily summary report.

All functions are intentionally side-effect free:
- they do not write to the paper ledger
- they do not modify model artifacts
- they do not place orders or log in to brokers
"""
import json
import os
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

TPE = timezone(timedelta(hours=8))

DEFAULT_UNIT = 'easystock-intraday.service'


def _runtime_status_path():
    return Path(os.environ.get('MODEL_RUNTIME_STATUS_PATH',
                               '/home/ubuntu/easystock-learning-data/models/runtime-model-status.json'))


def _latest_approved_path():
    return Path(os.environ.get('AI_PAPER_MODEL_PATH',
                               '/home/ubuntu/easystock-learning-data/models/latest-approved.json'))


def _learning_data_dir():
    return Path(os.environ.get('LEARNING_DATA_DIR', '/home/ubuntu/easystock-learning-data'))


# Intraday log markers printed by intraday_live.py
RE_MODEL_DECISION = re.compile(
    r'\[MODEL_DECISION\].*?'
    r'symbol=(?P<symbol>\S+).*?'
    r'evaluated=(?P<evaluated>\S+).*?'
    r'accepted=(?P<accepted>\S+).*?'
    r'probability=(?P<probability>\S+).*?'
    r'threshold=(?P<threshold>\S+).*?'
    r'reason=(?P<reason>\S+)'
)
RE_MARKET_RISK = re.compile(
    r'\[MARKET_RISK\]\s+'
    r'premarket=(?P<premarket>\S+)\s+'
    r'live=(?P<live>\S+)\s+'
    r'effective=(?P<effective>\S+)\s+'
    r'gate=(?P<gate>\S+)\s+'
    r'reason=(?P<reason>\S+)\s+'
    r'veto=(?P<veto>\S+)\s+'
    r'radar_candidates=(?P<radar_candidates>\S+)'
)
RE_MARKET_DATA = re.compile(
    r'\[MARKET_DATA\]\s+'
    r'shioaji=(?P<shioaji>\S+)\s+'
    r'esun=(?P<esun>\S+)\s+'
    r'premarket=(?P<premarket>\S+)'
)
RE_RADAR = re.compile(r'Instant-volume radar:\s+qualified=(?P<qualified>\d+)')


def journalctl_lines(day, unit=DEFAULT_UNIT):
    """Return log lines from journalctl for the unit on the given day.

    Failures (no journal, missing unit, timeout) return an empty list so the
    report can still be produced in degraded mode.
    """
    try:
        start = day + ' 00:00:00'
        end = (datetime.fromisoformat(day) + timedelta(days=1)).date().isoformat() + ' 00:00:00'
        result = subprocess.run(
            ['journalctl', '-u', unit, '--since', start, '--until', end,
             '--no-pager', '-o', 'cat'],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            return []
        return result.stdout.splitlines()
    except Exception:
        return []


def parse_model_decisions(lines):
    """Aggregate [MODEL_DECISION] lines from intraday logs.

    Returns:
        dict with evaluations, accepted_count, missing_feature_count,
        max_probability and max_probability_symbol.  probability=None is
        excluded from the max calculation.
    """
    evaluations = 0
    accepted_count = 0
    missing_feature_count = 0
    max_probability = None
    max_probability_symbol = None
    for line in lines:
        m = RE_MODEL_DECISION.search(line)
        if not m:
            continue
        if m.group('evaluated') != 'True':
            continue
        evaluations += 1
        if m.group('accepted') == 'True':
            accepted_count += 1
        reason = m.group('reason') or ''
        if 'missing' in reason:
            missing_feature_count += 1
        prob_str = m.group('probability')
        if prob_str in (None, '', 'None'):
            continue
        try:
            prob = float(prob_str)
        except ValueError:
            continue
        if not 0 <= prob <= 1:
            continue
        if max_probability is None or prob > max_probability:
            max_probability = prob
            max_probability_symbol = m.group('symbol')
    return {
        'evaluations': evaluations,
        'accepted_count': accepted_count,
        'missing_feature_count': missing_feature_count,
        'max_probability': max_probability,
        'max_probability_symbol': max_probability_symbol,
    }


def parse_market_risk(lines):
    """Return the last valid [MARKET_RISK] state, or None."""
    state = None
    for line in lines:
        m = RE_MARKET_RISK.search(line)
        if m:
            state = m.groupdict()
    return state


def parse_market_data(lines):
    """Return the last valid [MARKET_DATA] state, or None."""
    state = None
    for line in lines:
        m = RE_MARKET_DATA.search(line)
        if m:
            state = m.groupdict()
    return state


def parse_radar_peak(lines):
    """Return the peak qualified candidate count from radar logs."""
    peak = 0
    for line in lines:
        m = RE_RADAR.search(line)
        if m:
            try:
                peak = max(peak, int(m.group('qualified')))
            except ValueError:
                pass
    return peak


def load_runtime_model_status():
    """Read runtime-model-status.json if present."""
    try:
        data = json.loads(_runtime_status_path().read_text(encoding='utf-8'))
        if isinstance(data, dict):
            return data
    except (OSError, ValueError):
        pass
    return {}


def load_latest_approved():
    """Read latest-approved.json if present."""
    try:
        data = json.loads(_latest_approved_path().read_text(encoding='utf-8'))
        if isinstance(data, dict):
            return data
    except (OSError, ValueError):
        pass
    return {}


def model_state_for_report():
    """Combine runtime status and approved artifact into display fields.

    Threshold is taken from the runtime identity if available; otherwise it
    falls back to latest-approved.json.
    """
    runtime = load_runtime_model_status()
    runtime_identity = runtime.get('runtime') or {}
    approved = load_latest_approved()
    version = runtime_identity.get('version') or approved.get('version') or 'UNKNOWN'
    trained_through = runtime_identity.get('trained_through') or approved.get('trained_through') or 'UNKNOWN'
    profile = runtime_identity.get('profile') or approved.get('profile') or 'UNKNOWN'
    threshold = runtime_identity.get('threshold')
    if threshold is None:
        threshold = approved.get('threshold')
    return {
        'version': version,
        'trained_through': trained_through,
        'profile': profile,
        'threshold': threshold,
        'loaded_at': runtime_identity.get('loaded_at') or runtime.get('loaded_at'),
    }


def no_trade_reason(metrics, decisions, market_risk, radar_peak):
    """Explain why no simulated trades were closed today.

    Returns an empty string when trades_count > 0.
    """
    if metrics.get('trades_count', 0) > 0:
        return ''
    effective = (market_risk or {}).get('effective', 'UNKNOWN').upper()
    gate = (market_risk or {}).get('gate', 'UNKNOWN').upper()
    if effective == 'RED' or gate in ('BLOCK', 'VETO'):
        return 'Market Risk RED' if effective == 'RED' else f'Market Risk {gate}'
    if radar_peak == 0:
        return '無有效 Radar candidates'
    evaluations = decisions.get('evaluations', 0)
    accepted = decisions.get('accepted_count', 0)
    max_prob = decisions.get('max_probability')
    threshold = decisions.get('threshold')
    if evaluations == 0:
        return '未產生有效 AI 評估'
    if accepted == 0 and max_prob is not None and threshold is not None and max_prob < threshold:
        return f'AI 最高 {max_prob:.4f} < Threshold {threshold:.4f}'
    if accepted == 0:
        return '所有候選被 strategy veto'
    return '未成交'


def format_probability(value):
    """Format a probability for display, or '--' when absent."""
    if value is None:
        return '--'
    return f'{value:.4f}'


def format_threshold(value):
    """Format a threshold for display, or '--' when absent."""
    if value is None:
        return '--'
    return f'{value:.4f}'
