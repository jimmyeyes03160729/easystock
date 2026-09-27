"""Narrow, audited bridge to the root-owned maintenance runner."""
import json
import os
import subprocess
from pathlib import Path
from .store import Denied

RUNNER = Path(os.environ.get('EASYSTOCK_ADMIN_ACTION_RUNNER', '/usr/local/sbin/easystock-admin-action'))
CONFIRMATIONS = {'restart-intraday': 'RESTART_INTRADAY', 'sync-vm': 'SYNC_VM'}

def _run(action, timeout=12):
    if not RUNNER.is_file(): return {'available': False, 'detail': '維護控制尚未安裝；僅能查看健檢，不能執行 VM 操作。'}
    try: completed = subprocess.run(['sudo', '-n', str(RUNNER), action], text=True, capture_output=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired): return {'available': False, 'detail': '維護控制暫時無法使用。'}
    try: result = json.loads(completed.stdout)
    except (TypeError, json.JSONDecodeError): return {'available': False, 'detail': '維護控制回應格式異常。'}
    if not isinstance(result, dict): return {'available': False, 'detail': '維護控制回應格式異常。'}
    result['available'] = completed.returncode == 0
    return result

def status(): return _run('status')

def execute(store, action, confirmation):
    if action not in CONFIRMATIONS or confirmation != CONFIRMATIONS[action]: raise Denied('確認文字不正確，操作未執行。')
    with store.tx() as db:
        store._limit(db, 'maintenance-' + action, 1)
        store._audit(db, 'google', 'maintenance_request', {'action': action})
    return _run(action)
