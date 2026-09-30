"""Read-only, allowlisted health signals for the private admin dashboard."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from daytrade_learning.model_runtime import model_runtime_consistency
from .release import identity as release_identity


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


def _timestamp(value) -> str | None:
    try:
        return datetime.fromtimestamp(float(value), timezone.utc).isoformat()
    except (TypeError, ValueError, OSError, OverflowError):
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
    """Report the actual Taiwan exchange calendar before applying clock windows."""
    now = datetime.now(ZoneInfo('Asia/Taipei'))
    stamp = now.strftime('%Y-%m-%d %H:%M:%S')
    try:
        from market_calendar import is_market_open
        opened, reason, _ = is_market_open(now.date())
    except Exception:
        return _signal('market_session', '當沖時段', 'warning', f'台北時間 {stamp} · 無法確認交易日曆；當沖引擎會保持停止。')
    if not opened:
        return _signal('market_session', '當沖時段', 'idle', f'台北時間 {stamp} · 今日休市（{reason}）；等待下一個開盤日。')
    minute = now.hour * 60 + now.minute
    if 8 * 60 + 45 <= minute < 9 * 60:
        return _signal('market_session', '當沖時段', 'warning', f'台北時間 {stamp} · 盤前準備中，尚未開放進場。')
    if 9 * 60 <= minute < 13 * 60 + 30:
        return _signal('market_session', '當沖時段', 'ok', f'台北時間 {stamp} · 盤中；即時推薦與既有風控依服務狀態執行。')
    return _signal('market_session', '當沖時段', 'idle', f'台北時間 {stamp} · 已收盤；當沖服務不會建立新進場。')


def _worker_signal(key: str, label: str, value: object, timer: object = None, next_at: object = None) -> dict:
    state = str(value or 'unknown').lower()
    if state == 'active':
        return _signal(key, label, 'ok', '目前正在執行。')
    if state in ('failed', 'activating', 'deactivating'):
        return _signal(key, label, 'error' if state == 'failed' else 'warning', '服務狀態：' + state + '。')
    if state == 'inactive':
        if str(timer).lower() == 'active':
            suffix = f'下次：{next_at}。' if next_at else '正在等待下次排程。'
            return _signal(key, label, 'idle', '排程已啟用，目前未執行；' + suffix)
        return _signal(key, label, 'warning', '目前未執行，而且自動排程未啟用。')
    return _signal(key, label, 'idle', '尚未取得 VM 執行狀態。')


def _release_signal() -> dict:
    release = release_identity()
    if release['identified']:
        detail = (
            f"部署版本 {release['release_id']}；來源 commit "
            f"{release['source_commit']}。"
        )
        state = 'ok'
    else:
        detail = '尚未取得可核對的部署版本與來源 commit；不能確認目前執行的是哪一版。'
        state = 'warning'
    return _signal('deployment_release', '部署版本', state, detail, metrics=release)


def snapshot(store) -> dict:
    """Return safe status summaries only; no secrets, paths, commands or actions."""
    learning = _root('EASYSTOCK_LEARNING_DATA', '/home/ubuntu/easystock-learning-data')
    history = _root('EASYSTOCK_HISTORY_DATA', '/home/ubuntu/easystock-history-expanded-data')
    training_path = learning / 'training-status.json'
    history_path = history / 'progress.json'
    training, training_error = _read_json(training_path)
    progress, history_error = _read_json(history_path)

    settings = store.get()
    paper_trade = store.get_paper_trade().get('settings', {})
    market_session = _market_session()
    signals = [
        market_session,
        _release_signal(),
        _signal('admin_store', '後台設定資料庫', 'ok', '可讀取目前設定版本。', _timestamp(settings.get('updated_at')), {'setting_version': settings.get('version')}),
        _signal(
            'paper_trade', '模擬買進',
            'ok' if paper_trade.get('status') == 'running' else 'idle',
            '模擬買進已啟用；非交易時段不會執行，會等待下一個交易時段。' if paper_trade.get('status') == 'running' else '模擬買進目前已暫停；不會等待開盤或建立模擬買進。',
            _timestamp(paper_trade.get('updated_at')),
            {'initial_capital': paper_trade.get('initial_capital'), 'current_capital': paper_trade.get('current_capital')},
        ),
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
            _worker_signal('training_worker', '歷史訓練工作', workers.get('history_train'), workers.get('history_train_timer'), workers.get('history_train_next')),
            _worker_signal('daily_learning_worker', '每日訓練工作', workers.get('learning'), workers.get('learning_timer'), workers.get('learning_next')),
            _worker_signal('download_worker', '歷史資料抓取工作', workers.get('history_download'), workers.get('history_download_timer'), workers.get('history_download_next')),
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
        state = 'ok' if status in ('ok', 'completed', 'experimental_candidate', 'auto_approved_for_paper') else 'warning' if status in ('blocked', 'skipped', 'pending') else 'error'
        detail = {
            'experimental_candidate': '候選模型已完成；尚未套用到即時交易。',
            'auto_approved_for_paper': '每日訓練完成，最新模型已自動核准供下一個交易日使用。',
            'blocked': '資料或驗證門檻尚未達成，未建立候選模型。',
            'skipped': '本次流程略過，請查看資料收集狀態。',
        }.get(status, '已讀取最近一次訓練結果。')
        signals.append(_signal('daily_training', '每日訓練流程', state, detail, _updated_at(training_path), {
            'samples': _first_count(training, 'sample_count', 'samples'),
            'labeled': _first_count(training, 'labeled_count', 'labeled'),
        }))

    model_dir = learning / 'models'
    models = list(model_dir.glob('candidate-*.json')) if model_dir.is_dir() else []
    newest = max(models, key=lambda item: item.stat().st_mtime) if models else None
    approved_path = model_dir / 'latest-approved.json'
    approved, _ = _read_json(approved_path)
    if approved and approved.get('approved') is True and approved.get('deployment_allowed') is True:
        detail = '最新模型已自動核准，將於下一個交易日啟動時載入；不需人工審核。'
        metrics = {'candidate_count': len(models), 'model_version': approved.get('version'), 'trained_through': approved.get('trained_through')}
        signals.append(_signal('candidate_model', '候選模型', 'ok', detail, _updated_at(approved_path), metrics))
    else:
        detail = '已建立候選模型，等待自動核准流程完成。' if newest else '尚無候選模型；資料達到啟動門檻後會自動建立並核准。'
        signals.append(_signal('candidate_model', '候選模型', 'idle', detail, _updated_at(newest) if newest else None, {'candidate_count': len(models)}))

    shadow_path = model_dir / 'shadow-summary.json'
    shadow_summary, _ = _read_json(shadow_path)
    mismatches = [item for item in (shadow_summary or {}).get('warnings', []) if item.get('type') == 'profile_mismatch']
    if mismatches:
        names = '、'.join(str(item.get('line') or '未知模型') for item in mismatches)
        current_profile = (shadow_summary or {}).get('profile') or '未提供'
        signals.append(_signal(
            'model_profile', '模型參數一致性', 'warning',
            f'目前研究 profile={current_profile}；{names} 使用不同 profile，該線已停止比較，請勿混合解讀。',
            _updated_at(shadow_path),
            {'current_profile': current_profile, 'mismatched_lines': names},
        ))
    elif shadow_summary:
        signals.append(_signal('model_profile', '模型參數一致性', 'ok', '今日影子評估的模型與交易參數一致。', _updated_at(shadow_path)))

    if progress is None:
        signals.append(_signal('history_collection', '歷史資料補抓', 'idle' if history_error == 'not_started' else 'error', '尚未產生歷史資料進度。' if history_error == 'not_started' else '無法讀取歷史資料進度。'))
    else:
        stop_reason = str(progress.get('stop_reason', ''))
        state = 'error' if stop_reason.startswith('error') or stop_reason == 'credentials_missing' else 'warning' if stop_reason == 'quota_exhausted' else 'idle' if stop_reason == 'outside_window' else 'ok'
        if stop_reason in ('pair_limit','pair_limit_or_plan_complete'):
            detail = '本輪已達設定的處理上限，已保存進度；系統會在下一次排程自動接續。'
        else:
            detail = '目前不在抓取時段，等待下一次排程。' if stop_reason == 'outside_window' else '目前停止原因：' + (stop_reason or '持續處理中')
        signals.append(_signal('history_collection', '歷史資料補抓', state, detail, _updated_at(history_path), {
            'completed_stock_days': _positive_int(progress.get('archived_stock_days')),
            'target_stock_days': _positive_int(progress.get('target_stock_days')),
            'failed_stock_days': _positive_int(progress.get('failed_stock_days')),
        }))

    try:
        consistency = model_runtime_consistency(
            learning_data_dir=str(learning),
            max_stale_seconds=int(os.environ.get('MODEL_RUNTIME_STALE_SECONDS', '90')),
        )
    except Exception as exc:
        consistency = {
            'status': 'RUNTIME_UNKNOWN',
            'runtime': None,
            'approved': None,
            'match': False,
            'reason': 'model_runtime_consistency_check_failed',
            'error': f'{type(exc).__name__}: {exc}',
        }
    status_to_state = {
        'OK': 'ok',
        'MISMATCH': 'warning',
        'RUNTIME_UNKNOWN': 'error',
        'RUNTIME_STALE': 'error',
        'APPROVED_MISSING': 'error',
        'APPROVED_INVALID': 'error',
    }
    state = status_to_state.get(consistency['status'], 'error')
    if consistency['status'] == 'RUNTIME_STALE' and market_session['state'] == 'idle':
        # The intraday process normally exits after the trading session.  Its
        # last successful model load remains useful evidence, but a stale
        # heartbeat after hours is not a runtime failure.
        state = 'warning'
    runtime = consistency.get('runtime') or {}
    runtime_status = consistency.get('runtime_status') or {}
    approved = consistency.get('approved') or {}
    if consistency['status'] == 'OK':
        detail = '盤中 process 實際載入的模型與 latest-approved artifact 一致。'
    elif consistency['status'] == 'RUNTIME_UNKNOWN':
        detail = '無法確認盤中 process 目前載入的模型；可能是尚未啟動、狀態遺失或模型載入失敗。'
        if runtime.get('load_reason'):
            detail += ' 載入原因：' + str(runtime['load_reason']) + '。'
    elif consistency['status'] == 'RUNTIME_STALE':
        detail = (
            '目前非盤中時段；最後一次盤中服務回報已過期，'
            '不能視為目前 process 正在執行，但可查看最後載入的模型。'
        )
    elif consistency['status'] == 'APPROVED_MISSING':
        detail = 'latest-approved.json 不存在；無法比對。'
    elif consistency['status'] == 'APPROVED_INVALID':
        detail = f'latest-approved.json 無法解析或不符合 schema：{consistency.get("reason")}'
    else:
        detail = '盤中 process 使用的模型與 latest-approved artifact 不一致；此為預期監控結果，不會自動重載。'
    signals.append(_signal(
        'model_runtime_consistency',
        '盤中模型狀態',
        state,
        detail,
        metrics={
            'consistency_status': consistency['status'],
            'match': bool(consistency.get('match')),
            'reason': consistency.get('reason'),
            'runtime_version': runtime.get('version'),
            'runtime_profile': runtime.get('profile'),
            'runtime_trained_through': runtime.get('trained_through'),
            'runtime_loaded_at': runtime.get('loaded_at'),
            'runtime_load_reason': runtime.get('load_reason'),
            'runtime_entry_mode': runtime_status.get('entry_mode'),
            'runtime_artifact_name': runtime.get('artifact_name'),
            'runtime_sha256_short': (runtime.get('artifact_sha256') or '')[:12],
            'approved_version': approved.get('version'),
            'approved_profile': approved.get('profile'),
            'approved_trained_through': approved.get('trained_through'),
            'approved_sha256_short': (approved.get('artifact_sha256') or '')[:12],
        },
    ))

    return {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'signals': signals,
        'model_runtime_consistency': consistency,
        'provider_health': provider_diagnostics(),
    }


def provider_diagnostics():
    from market_data.health import aggregate
    return aggregate()[1]


def model_promotion_log(page: int = 1, page_size: int = 10) -> dict:
    """Return one newest-first page without loading the whole audit file."""
    page=max(1,min(int(page),10000));page_size=max(1,min(int(page_size),50))
    learning=_root('EASYSTOCK_LEARNING_DATA','/home/ubuntu/easystock-learning-data')
    path=learning/'models'/'promotion-log.jsonl'
    if not path.exists():return {'entries':[],'page':page,'page_size':page_size,'has_previous':page>1,'has_more':False}
    needed=page*page_size+1;raw_rows=[]
    try:
        with open(path,'rb') as source:
            source.seek(0,2);position=source.tell();remainder=b''
            while position>0 and len(raw_rows)<needed:
                size=min(65536,position);position-=size;source.seek(position)
                parts=(source.read(size)+remainder).split(b'\n');remainder=parts[0]
                for raw in reversed(parts[1:]):
                    if raw.strip():raw_rows.append(raw)
                    if len(raw_rows)>=needed:break
            if position==0 and remainder.strip() and len(raw_rows)<needed:raw_rows.append(remainder)
    except OSError:
        return {'entries':[],'page':page,'page_size':page_size,'has_previous':page>1,'has_more':False,'unavailable':True}
    rows=[]
    for raw in raw_rows:
        if len(raw)>65536:continue
        try:source=json.loads(raw)
        except (ValueError,TypeError):continue
        if not isinstance(source,dict):continue
        validations=[]
        for item in source.get('validation') or []:
            if not isinstance(item,dict):continue
            validations.append({key:item.get(key) for key in (
                'fold','test_samples','selected_count','expected_value_pct','brier','test_from','test_through')})
        rows.append({
            'promoted_at':source.get('promoted_at') or source.get('date'),
            'promoted_model':source.get('promoted_model') or (('滾動模型 · '+str(source.get('action'))) if source.get('action') else None),
            'previous_model':source.get('previous_model'),'backup_file':source.get('backup_file'),
            'trained_through':source.get('trained_through'),'validation_mode':source.get('validation_mode'),
            'validation':validations,'action':source.get('action'),'profile':source.get('profile'),
            'sample_count':source.get('sample_count'),'warnings':source.get('warnings') or [],
        })
    start=(page-1)*page_size;entries=rows[start:start+page_size]
    return {'entries':entries,'page':page,'page_size':page_size,'has_previous':page>1,'has_more':len(rows)>start+page_size}
