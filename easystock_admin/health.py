"""Read-only, allowlisted health signals for the private admin dashboard."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


MAX_STATUS_BYTES = 1024 * 1024


def _root(name: str, fallback: str) -> Path:
    return Path(os.environ.get(name, fallback))


def _read_json(path: Path) -> tuple[dict | None, str | None]:
    try:
        if path.stat().st_size > MAX_STATUS_BYTES:
            return None, 'status_file_too_large'
        value = json.loads(path.read_text(encoding='utf-8'))
        return (value, None) if isinstance(value, dict) else (None, 'status_not_an_object')
    except FileNotFoundError:
        return None, 'not_started'
    except (OSError, ValueError, UnicodeError):
        return None, 'status_unreadable'


def _updated_at(path: Path) -> str | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
    except OSError:
        return None


def _signal(key: str, label: str, state: str, detail: str, updated_at: str | None = None, metrics: dict | None = None) -> dict:
    return {
        'key': key,
        'label': label,
        'state': state,
        'detail': detail,
        'updated_at': updated_at,
        'metrics': metrics or {},
    }


def _positive_int(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _first_count(value: dict, *keys: str):
    for key in keys:
        count = _positive_int(value.get(key))
        if count is not None:
            return count
    return None


def _market_session() -> dict:
    """A clock status, deliberately not a trading-calendar assertion."""
    now = datetime.now(ZoneInfo('Asia/Taipei'))
    stamp = now.strftime('%Y-%m-%d %H:%M:%S')
    if now.weekday() >= 5:
        return _signal('market_session', '當沖時段', 'idle', f'台北時間 {stamp} · 非平日；當沖服務不應自動進場。')
    minute = now.hour * 60 + now.minute
    if 8 * 60 + 45 <= minute < 9 * 60:
        return _signal('market_session', '當沖時段', 'warning', f'台北時間 {stamp} · 盤前準備中，尚未開放進場。')
    if 9 * 60 <= minute < 13 * 60 + 30:
        return _signal('market_session', '當沖時段', 'ok', f'台北時間 {stamp} · 盤中；即時推薦與既有風控依服務狀態執行。')
    return _signal('market_session', '當沖時段', 'idle', f'台北時間 {stamp} · 已收盤；當沖服務不會建立新進場。')


def _worker_signal(key: str, label: str, value: object) -> dict:
    state = str(value or 'unknown').lower()
    if state == 'active':
        return _signal(key, label, 'ok', '目前正在執行。')
    if state in ('failed', 'activating', 'deactivating'):
        return _signal(key, label, 'error' if state == 'failed' else 'warning', '服務狀態：' + state + '。')
    if state == 'inactive':
        return _signal(key, label, 'idle', '目前沒有執行；請搭配最近更新時間判斷是否已完成。')
    return _signal(key, label, 'idle', '尚未取得 VM 執行狀態。')


def snapshot(store) -> dict:
    """Return safe status summaries only; no secrets, paths, commands or actions."""
    learning = _root('EASYSTOCK_LEARNING_DATA', '/home/ubuntu/easystock-learning-data')
    history = _root('EASYSTOCK_HISTORY_DATA', '/home/ubuntu/easystock-history-expanded-data')
    training_path = learning / 'training-status.json'
    history_path = history / 'progress.json'
    training, training_error = _read_json(training_path)
    progress, history_error = _read_json(history_path)

    settings = store.get()
    signals = [
        _market_session(),
        _signal('admin_store', '後台設定資料庫', 'ok', '可讀取目前設定版本。', settings.get('updated_at'), {'setting_version': settings.get('version')}),
        _signal(
            'market_credentials', '行情資料憑證',
            'ok' if (os.environ.get('SJ_API_KEY') or os.environ.get('SHIOAJI_API_KEY')) and (os.environ.get('SJ_SECRET_KEY') or os.environ.get('SHIOAJI_SECRET_KEY') or os.environ.get('SJ_SEC_KEY')) else 'error',
            '憑證已設定。' if (os.environ.get('SJ_API_KEY') or os.environ.get('SHIOAJI_API_KEY')) and (os.environ.get('SJ_SECRET_KEY') or os.environ.get('SHIOAJI_SECRET_KEY') or os.environ.get('SJ_SEC_KEY')) else '缺少行情資料憑證；收集工作無法執行。',
        ),
        _signal(
            'firebase', 'Firebase 發布設定',
            'ok' if os.environ.get('FIREBASE_DATABASE_URL') else 'warning',
            '發布端點已設定。' if os.environ.get('FIREBASE_DATABASE_URL') else '未設定發布端點；後台僅顯示本機狀態。',
        ),
    ]

    # The root-owned runner only exposes a fixed allowlist of unit states.
    # If it is not installed yet, health remains read-only and reports that
    # limitation instead of pretending that a worker is active.
    try:
        from .operations import status as maintenance_status
        workers = maintenance_status()
    except Exception:
        workers = {'available': False}
    if workers.get('available'):
        signals.extend([
            _worker_signal('training_worker', '歷史訓練工作', workers.get('history_train')),
            _worker_signal('daily_learning_worker', '每日訓練工作', workers.get('learning')),
            _worker_signal('download_worker', '歷史資料抓取工作', workers.get('history_download')),
        ])
    else:
        signals.extend([
            _signal('training_worker', '歷史訓練工作', 'idle', 'VM 執行狀態尚未連線；下方仍顯示最近一次訓練紀錄。'),
            _signal('daily_learning_worker', '每日訓練工作', 'idle', 'VM 執行狀態尚未連線；下方仍顯示最近一次訓練紀錄。'),
            _signal('download_worker', '歷史資料抓取工作', 'idle', 'VM 執行狀態尚未連線；下方仍顯示資料進度檔。'),
        ])

    if training is None:
        signals.append(_signal('daily_training', '每日訓練流程', 'idle' if training_error == 'not_started' else 'error', '尚未產生訓練紀錄。' if training_error == 'not_started' else '無法讀取訓練狀態。'))
    else:
        status = str(training.get('status', '')).lower()
        state = 'ok' if status in ('ok', 'completed', 'experimental_candidate') else 'warning' if status in ('blocked', 'skipped', 'pending') else 'error'
        detail = {
            'experimental_candidate': '候選模型已完成；尚未套用到即時交易。',
            'blocked': '資料或驗證門檻尚未達成，未建立候選模型。',
            'skipped': '本次流程略過，請查看資料收集狀態。',
        }.get(status, '已讀取最近一次訓練結果。')
        signals.append(_signal('daily_training', '每日訓練流程', state, detail, _updated_at(training_path), {
            'samples': _first_count(training, 'sample_count', 'samples'),
            'labeled': _first_count(training, 'labeled_count', 'labeled'),
        }))

    models = list((learning / 'models').glob('candidate-*.json')) if (learning / 'models').is_dir() else []
    newest = max(models, key=lambda item: item.stat().st_mtime) if models else None
    signals.append(_signal('candidate_model', '候選模型', 'ok' if newest else 'idle', '已建立候選模型，仍需人工核准才可套用。' if newest else '尚無候選模型；系統不會自動套用模型。', _updated_at(newest) if newest else None, {'candidate_count': len(models)}))

    if progress is None:
        signals.append(_signal('history_collection', '歷史資料補抓', 'idle' if history_error == 'not_started' else 'error', '尚未產生歷史資料進度。' if history_error == 'not_started' else '無法讀取歷史資料進度。'))
    else:
        stop_reason = str(progress.get('stop_reason', ''))
        state = 'error' if stop_reason.startswith('error') or stop_reason == 'credentials_missing' else 'warning' if stop_reason in ('quota_exhausted', 'pair_limit', 'outside_window') else 'ok'
        signals.append(_signal('history_collection', '歷史資料補抓', state, '目前停止原因：' + (stop_reason or '持續處理中'), _updated_at(history_path), {
            'completed_stock_days': _positive_int(progress.get('archived_stock_days')),
            'target_stock_days': _positive_int(progress.get('target_stock_days')),
            'failed_stock_days': _positive_int(progress.get('failed_stock_days')),
        }))

    return {'generated_at': datetime.now(timezone.utc).isoformat(), 'signals': signals}
