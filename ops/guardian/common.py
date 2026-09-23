"""Small, deterministic health and recovery policy; no agent-selected shell commands."""
import datetime as dt
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

TPE = ZoneInfo('Asia/Taipei')
ROOT = Path('/opt/easystock-guardian')
STATE = Path('/var/lib/easystock-guardian')
JOBS = Path('/var/lib/easystock-codex/jobs')
APP = Path('/home/ubuntu/easystock')
PYTHON = str(APP / '.venv/bin/python3')
SERVICE = 'easystock-intraday.service'

def now():
    return dt.datetime.now(TPE)

def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        return default

def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    tmp.replace(path)

def digest(data):
    return hashlib.sha256(data).hexdigest()

def age(value, stamp):
    try:
        parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            return None
        return (stamp - parsed).total_seconds()
    except (TypeError, ValueError, AttributeError):
        return None

def classify(s, stamp, calendar):
    day = stamp.date().isoformat()
    clock = stamp.strftime('%H:%M')
    if stamp.weekday() >= 5:
        return []
    if not calendar or calendar.get('year') != stamp.year:
        return ['calendar_unavailable']
    if day in calendar.get('closed', []):
        return []
    if not '08:40' <= clock <= '14:30':
        return []
    if s.get('read_error'):
        return ['health_read_failed']
    errors = []
    if s.get('syntax_errors'):
        errors.append('source_syntax_error')
    if s.get('ledger_mismatch'):
        errors.append('ledger_mismatch')
    if s.get('ghost_symbols'):
        errors.append('unfilled_ghost_records')
    if clock < '08:58':
        return errors
    if clock < '13:00':
        if s.get('service_active') != 'active':
            errors.append('service_not_running')
        elapsed = age(s.get('last_update_at'), stamp)
        if s.get('scan_date') != day or elapsed is None or elapsed > 120 or elapsed < -60:
            errors.append('snapshot_stale')
        if '09:05' <= clock < '12:30':
            quote_age = age(s.get('radar_at'), stamp)
            if quote_age is None or quote_age > 180 or quote_age < -60:
                errors.append('quotes_stale')
    elif clock >= '13:05':
        if s.get('scan_date') != day:
            errors.append('session_missing')
        elif s.get('session') != 'closed':
            errors.append('session_not_closed')
        if s.get('ledger_positions'):
            errors.append('unsettled_positions')
    return sorted(set(errors))

def permitted_actions(s, stamp, calendar):
    """These are capabilities enforced outside Codex, not prompt promises."""
    if classify(s, stamp, calendar) == ['calendar_unavailable'] or s.get('read_error') or s.get('orders_enabled'):
        return ['investigate']
    if not calendar or stamp.weekday() >= 5 or stamp.date().isoformat() in calendar.get('closed', []):
        return ['investigate']
    actions = ['investigate']
    empty = not s.get('ledger_positions') and not s.get('valid_remote_positions')
    stopped = (s.get('service_active') not in ('active', 'activating', 'deactivating')
               or s.get('service_substate') == 'auto-restart')
    if empty and stopped and s.get('ghost_symbols') and not s.get('ledger_mismatch'):
        actions.append('quarantine_unfilled_ghosts')
    if empty and stopped and s.get('restorable_syntax_error'):
        actions.append('restore_known_good_adapter')
    if (empty and not s.get('remote_positions') and not s.get('ledger_mismatch')
            and not s.get('syntax_errors') and not s.get('orders_enabled')
            and '08:55' <= stamp.strftime('%H:%M') < '12:30'):
        actions.append('restart_intraday')
    return actions
