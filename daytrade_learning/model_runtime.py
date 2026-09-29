"""Validated paper-trading model inference using the latest daily promotion."""
import json
import hashlib
import math
import os
import tempfile
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from .features import FEATURES, SCHEMA_VERSION, finite, vector

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None

MODEL_RUNTIME_VERSION = 'approved-model-gate-v3'
TPE = timezone(timedelta(hours=8))

RUNTIME_STATUS_FILE = 'runtime-model-status.json'
DEFAULT_LEARNING_DATA = '/home/ubuntu/easystock-learning-data'
RUNTIME_CLOCK_SKEW_TOLERANCE_SECONDS = 30
RUNTIME_HEARTBEAT_TTL_MARGIN_SECONDS = 60
RUNTIME_DEFAULT_STALE_TTL_SECONDS = 90
RUNTIME_MAX_STALE_TTL_SECONDS = 900
RUNTIME_MAX_HEARTBEAT_SECONDS = 300


def live_features(*, price, previous_close, now_ts, ticks=None, radar=None):
    radar = radar or {}
    try:
        price, previous_close, now_ts = map(finite, (price, previous_close, now_ts))
        if min(price, previous_close) <= 0:
            return None
        rows = sorted((t for t in (ticks or []) if finite(t[0]) <= now_ts), key=lambda t: t[0])
        if not rows or not 0 <= now_ts - rows[-1][0] <= 30:
            return None
        old = [t for t in rows if t[0] <= now_ts - 300]
        if not old or now_ts - old[-1][0] > 330 or finite(old[-1][3]) <= 0:
            return None
        # Recompute radar inputs at the caller; absent values are never zero-filled.
        row = dict(gain_pct=(price / previous_close - 1) * 100,
                   return_5m_pct=(price / finite(old[-1][3]) - 1) * 100,
                   surge_60s=radar.get('surge_60s'), buy_ratio_60s=radar.get('buy_ratio_60s'),
                   amount_60s=radar.get('amount_60s'))
        vector(row)
        if finite(radar.get('history_seconds')) < 300 or finite(radar.get('classified_ratio_60s')) < .5:
            return None
        if not 0 <= row['buy_ratio_60s'] <= 1:
            return None
        return row
    except (KeyError, IndexError, TypeError, ValueError, OverflowError):
        return None


class DaytradeModel:
    @staticmethod
    def age_in_weekdays(trained_through):
        trained=date.fromisoformat(str(trained_through)[:10]); today=datetime.now(TPE).date()
        return sum((trained+timedelta(days=offset)).weekday()<5 for offset in range(1,(today-trained).days+1))

    @staticmethod
    def _validate_artifact(a):
        """Return (identity, None) for a structurally valid approved artifact,
        or (None, error_reason) if it cannot be loaded by DaytradeModel.
        Excludes runtime age policy so that health can evaluate the artifact
        identity independently of whether it is fresh enough to trade."""
        if not isinstance(a, dict):
            return None, 'approved_not_an_object'
        required = (
            'approved', 'deployment_allowed', 'schema_version', 'features',
            'mean', 'scale', 'coef', 'intercept', 'threshold', 'version',
            'trained_through', 'profile',
        )
        for key in required:
            if key not in a:
                return None, 'approved_required_field_missing:' + key
        if a.get('deployment_allowed') is not True or a.get('approved') is not True:
            return None, 'approved_not_deployable'
        if a.get('schema_version') != SCHEMA_VERSION:
            return None, 'approved_schema_invalid'
        if not isinstance(a.get('features'), list) or a.get('features') != list(FEATURES):
            return None, 'approved_features_invalid'
        n = len(FEATURES)
        for key in ('mean', 'scale', 'coef'):
            if key not in a or not isinstance(a[key], list) or len(a[key]) != n:
                return None, 'approved_dimensions_invalid'
            for x in a[key]:
                if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(float(x)):
                    return None, 'approved_numeric_invalid'
        if any(float(x) <= 0 for x in a['scale']):
            return None, 'approved_scale_invalid'
        try:
            intercept = finite(a['intercept'])
            threshold = finite(a['threshold'])
        except (TypeError, ValueError):
            return None, 'approved_numeric_invalid'
        if not 0 <= threshold <= 1:
            return None, 'approved_threshold_invalid'
        if not a.get('version'):
            return None, 'approved_version_missing'
        if not a.get('trained_through'):
            return None, 'approved_trained_through_missing'
        try:
            date.fromisoformat(str(a['trained_through'])[:10])
        except ValueError:
            return None, 'approved_trained_through_invalid'
        profile = a.get('profile')
        if profile is None or not str(profile).strip():
            return None, 'approved_profile_missing'
        identity = {
            'version': str(a['version']),
            'trained_through': str(a['trained_through']),
            'profile': str(profile),
            'schema_version': str(a['schema_version']),
            'intercept': intercept,
            'threshold': threshold,
        }
        return identity, None

    def __init__(self, path=None):
        self.artifact = None
        self.artifact_sha256 = None
        self.artifact_path = None
        self.model_version = MODEL_RUNTIME_VERSION
        self.schema_version = None
        self.trained_through = None
        self.profile = None
        self.loaded_at = None
        self.threshold = None
        self.reason = 'no_approved_model'
        path = path if path is not None else os.environ.get('AI_PAPER_MODEL_PATH')
        if path is None:
            path = resolve_approved_model_path()
        if not path:
            return
        try:
            raw = Path(path).read_bytes()
            a = json.loads(raw)
            identity, error = self._validate_artifact(a)
            if error:
                raise ValueError(error)
            maximum=int(os.environ.get('LIVE_MODEL_MAX_AGE_TRADING_DAYS','10'))
            age=self.age_in_weekdays(a.get('trained_through'))
            if maximum < 1 or age>maximum:
                self.reason=f'stale_model:{age}_weekdays'
                return
            self.artifact, self.threshold = a, identity['threshold']
            self.artifact_sha256 = hashlib.sha256(raw).hexdigest()
            self.artifact_path = str(Path(path).resolve())
            self.model_version = identity['version']
            self.schema_version = identity['schema_version']
            self.trained_through = identity['trained_through']
            self.profile = identity['profile']
            self.loaded_at = datetime.now(TPE).isoformat()
            self.reason = 'approved_model_loaded'
        except (OSError, ValueError, TypeError, KeyError) as exc:
            self.reason = 'invalid_or_unapproved_model:' + type(exc).__name__

    def identity(self):
        return {
            'version': self.model_version,
            'trained_through': self.trained_through,
            'profile': self.profile,
            'schema_version': self.schema_version,
            'loaded_at': self.loaded_at,
            'artifact_path': self.artifact_path,
            'artifact_sha256': self.artifact_sha256,
            'load_reason': self.reason,
        }

    def evaluate(self, features):
        result = dict(active=self.artifact is not None, evaluated=False,
                      approved=self.artifact is not None, accepted=False, probability=None,
                      threshold=self.threshold, model_version=self.model_version, reason=self.reason)
        result['artifact_sha256'] = self.artifact_sha256
        if self.artifact is None:
            return result
        try:
            a = self.artifact
            values = vector(features or {})
            z = a['intercept'] + sum((x-m)/s*c for x,m,s,c in zip(values,a['mean'],a['scale'],a['coef']))
            if not math.isfinite(z):
                raise ValueError('nonfinite_score')
            probability = 1/(1+math.exp(-z)) if z >= 0 else math.exp(z)/(1+math.exp(z))
            result.update(evaluated=True, probability=probability,
                          accepted=probability >= self.threshold, reason='evaluated')
        except (KeyError, ValueError, TypeError, OverflowError):
            result['reason'] = 'missing_or_invalid_features'
        return result

    def predict(self, features):
        return self.evaluate(features)['probability']

    def run(self, features):
        return self.evaluate(features)


def resolve_approved_model_path(learning_data_dir=None):
    """Resolve the single approved-model path used by runtime and health."""
    env_path = os.environ.get('AI_PAPER_MODEL_PATH')
    if env_path:
        return Path(env_path)
    data_dir = (
        learning_data_dir
        or os.environ.get('LEARNING_DATA_DIR')
        or os.environ.get('EASYSTOCK_LEARNING_DATA')
        or DEFAULT_LEARNING_DATA
    )
    return Path(data_dir) / 'models' / 'latest-approved.json'


def _default_models_dir():
    return resolve_approved_model_path().parent


def resolve_runtime_status_path(models_dir=None):
    """Return the runtime status path consistent with the active model path."""
    if models_dir is None:
        models_dir = _default_models_dir()
    return Path(models_dir) / RUNTIME_STATUS_FILE


def runtime_model_status_path(models_dir=None):
    """Deprecated alias kept for compatibility."""
    return resolve_runtime_status_path(models_dir=models_dir)


def _effective_stale_ttl(requested_seconds):
    """Ensure stale TTL is safely larger than the heartbeat interval."""
    try:
        requested = float(requested_seconds)
        if not math.isfinite(requested) or requested <= 0:
            requested = RUNTIME_DEFAULT_STALE_TTL_SECONDS
    except (TypeError, ValueError):
        requested = RUNTIME_DEFAULT_STALE_TTL_SECONDS
    requested = min(requested, RUNTIME_MAX_STALE_TTL_SECONDS)
    try:
        heartbeat = float(os.environ.get('LIVE_HEARTBEAT_SECONDS', '15'))
        if not math.isfinite(heartbeat) or heartbeat < 5 or heartbeat > RUNTIME_MAX_HEARTBEAT_SECONDS:
            heartbeat = 15.0
    except (TypeError, ValueError, OverflowError):
        heartbeat = 15.0
    minimum = int(heartbeat + RUNTIME_HEARTBEAT_TTL_MARGIN_SECONDS)
    return min(max(int(requested), minimum), RUNTIME_MAX_STALE_TTL_SECONDS)


_LOCAL_STATUS_LOCK = threading.RLock()


@contextmanager
def _status_lock(path):
    """Serialize status read/check/write across Linux processes and threads."""
    path = Path(path)
    lock_path = path.with_name(path.name + '.lock')
    with _LOCAL_STATUS_LOCK:
        lock_file = None
        try:
            if fcntl is not None:
                lock_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                lock_file = lock_path.open('a+', encoding='utf-8')
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            if lock_file is not None:
                try:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                finally:
                    lock_file.close()


def _atomic_write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    raw = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode('utf-8')
    temp = None
    try:
        fd, temp = tempfile.mkstemp(dir=path.parent, suffix='.tmp')
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        temp_path = Path(temp)
        try:
            temp_path.chmod(0o600)
        except OSError:
            pass
        os.replace(temp_path, path)
        try:
            path.chmod(0o600)
        except OSError:
            pass
        if os.name != 'nt':
            try:
                dir_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
            except OSError:
                pass
    finally:
        if temp is not None:
            try:
                Path(temp).unlink(missing_ok=True)
            except OSError:
                pass


def _redact_runtime_identity(runtime_identity):
    """Return a copy safe for Admin API responses without leaking server paths."""
    if not isinstance(runtime_identity, dict):
        return runtime_identity
    safe = dict(runtime_identity)
    artifact_path = safe.pop('artifact_path', None)
    if artifact_path:
        safe['artifact_name'] = Path(artifact_path).name
    return safe


def _new_instance_id():
    return uuid.uuid4().hex


def write_runtime_model_status(runtime_identity, entry_mode=None, pid=None,
                               instance_id=None, process_started_at=None, path=None):
    """Persist the identity of the model actually loaded by the running process."""
    path = Path(path) if path is not None else resolve_runtime_status_path()
    if instance_id is None:
        instance_id = _new_instance_id()
    if process_started_at is None:
        process_started_at = datetime.now(TPE).isoformat()
    payload = {
        'reported_at': datetime.now(TPE).isoformat(),
        'loaded_at': runtime_identity.get('loaded_at'),
        'pid': pid,
        'instance_id': instance_id,
        'process_started_at': process_started_at,
        'entry_mode': entry_mode,
        'runtime': runtime_identity,
    }
    with _status_lock(path):
        current = None
        try:
            current = json.loads(path.read_text(encoding='utf-8'))
        except (FileNotFoundError, OSError, ValueError):
            pass
        if isinstance(current, dict):
            current_id = current.get('instance_id')
            current_started = _parse_process_started_at(current.get('process_started_at'))
            candidate_started = _parse_process_started_at(process_started_at)
            if current_id and current_started and candidate_started:
                if current_started > candidate_started or (
                    current_started == candidate_started and str(current_id) >= str(instance_id)
                ):
                    return None
        _atomic_write_json(path, payload)
        return instance_id


def refresh_runtime_model_status(path=None, reported_at=None, instance_id=None, process_started_at=None):
    """Keep the runtime status alive without rewriting the loaded identity.

    If the status file is owned by a newer instance, this writer yields and
    returns False so an old process cannot overwrite a newer one.
    """
    path = Path(path) if path is not None else resolve_runtime_status_path()
    with _status_lock(path):
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return False
        if not isinstance(data, dict):
            return False
        current_id = data.get('instance_id')
        current_started = _parse_process_started_at(data.get('process_started_at'))
        our_started = _parse_process_started_at(process_started_at)
        if instance_id and current_id != instance_id:
            if current_started is None or our_started is None:
                return False
            if current_started > our_started or (
                current_started == our_started and str(current_id) >= str(instance_id)
            ):
                return False
        data['reported_at'] = reported_at or datetime.now(TPE).isoformat()
        _atomic_write_json(path, data)
        return True


def _parse_process_started_at(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=TPE)
    except (TypeError, ValueError):
        return None


def _parse_reported_at(reported_at, now):
    """Return ('valid', datetime) or ('missing', None) or ('invalid', None) or ('future', None)."""
    if reported_at is None or reported_at == '':
        return 'missing', None
    try:
        dt = datetime.fromisoformat(str(reported_at))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TPE)
        skew = (dt - now).total_seconds()
        if skew > RUNTIME_CLOCK_SKEW_TOLERANCE_SECONDS:
            return 'future', None
        return 'valid', dt
    except (ValueError, TypeError):
        return 'invalid', None


def model_runtime_consistency(learning_data_dir=None, max_stale_seconds=90, now=None):
    """
    Compare the model identity reported by the running intraday process with the
    current latest-approved artifact.  SHA256 is the ground-truth identity; version,
    trained_through and profile are human-readable diagnostics.
    """
    now = now or datetime.now(TPE)
    approved_path = resolve_approved_model_path(learning_data_dir=learning_data_dir)
    models_dir = approved_path.parent
    runtime_path = resolve_runtime_status_path(models_dir=models_dir)

    result = {
        'status': 'OK',
        'runtime': None,
        'runtime_status': None,
        'approved': None,
        'match': False,
        'reason': None,
        'details': {},
    }

    runtime = None
    runtime_error = None
    try:
        runtime = json.loads(runtime_path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        runtime_error = 'runtime_status_missing'
    except (OSError, ValueError):
        runtime_error = 'runtime_status_unreadable'

    runtime_identity = None
    reported_at = None
    if isinstance(runtime, dict):
        runtime_identity = runtime.get('runtime')
        reported_at = runtime.get('reported_at')
        if not isinstance(runtime_identity, dict):
            runtime_error = runtime_error or 'runtime_identity_missing'
        elif not runtime_identity.get('artifact_sha256'):
            runtime_error = runtime_error or 'runtime_model_not_loaded'
    else:
        runtime_error = runtime_error or 'runtime_status_invalid'

    approved_identity = None
    approved_error = None
    try:
        raw = approved_path.read_bytes()
        approved = json.loads(raw)
        identity, error = DaytradeModel._validate_artifact(approved)
        if error:
            approved_error = error
        else:
            approved_identity = {
                'version': identity['version'],
                'trained_through': identity['trained_through'],
                'profile': identity['profile'],
                'schema_version': identity['schema_version'],
                'artifact_sha256': hashlib.sha256(raw).hexdigest(),
            }
    except FileNotFoundError:
        approved_error = 'approved_artifact_missing'
    except (OSError, ValueError):
        approved_error = 'approved_artifact_invalid'

    reported_state, reported_dt = _parse_reported_at(reported_at, now)
    stale = False
    if reported_state == 'valid':
        effective_ttl = _effective_stale_ttl(max_stale_seconds)
        if (now - reported_dt).total_seconds() > effective_ttl:
            stale = True

    result['runtime'] = _redact_runtime_identity(runtime_identity)
    if isinstance(runtime, dict):
        result['runtime_status'] = {
            'entry_mode': runtime.get('entry_mode'),
            'pid': runtime.get('pid'),
            'instance_id': runtime.get('instance_id'),
            'process_started_at': runtime.get('process_started_at'),
            'reported_at': runtime.get('reported_at'),
        }
    if approved_identity is not None:
        result['approved'] = approved_identity
    else:
        result['approved'] = {'error': approved_error, 'artifact_name': approved_path.name}

    if runtime_error == 'runtime_status_missing':
        result.update(status='RUNTIME_UNKNOWN', reason='runtime_status_missing', match=False)
        return result
    if runtime_error:
        result.update(status='RUNTIME_UNKNOWN', reason=runtime_error, match=False)
        return result
    if reported_state == 'missing':
        result.update(status='RUNTIME_UNKNOWN', reason='runtime_reported_at_missing', match=False)
        return result
    if reported_state == 'invalid':
        result.update(status='RUNTIME_UNKNOWN', reason='runtime_reported_at_invalid', match=False)
        return result
    if reported_state == 'future':
        result.update(status='RUNTIME_UNKNOWN', reason='runtime_reported_at_in_future', match=False)
        return result
    if stale:
        result.update(status='RUNTIME_STALE', reason='runtime_status_stale', match=False)
        return result
    if approved_error == 'approved_artifact_missing':
        result.update(status='APPROVED_MISSING', reason='approved_artifact_missing', match=False)
        return result
    if approved_error:
        result.update(status='APPROVED_INVALID', reason=approved_error, match=False)
        return result

    rt_sha = runtime_identity.get('artifact_sha256')
    ap_sha = approved_identity['artifact_sha256']
    details = {
        'sha_match': rt_sha == ap_sha,
        'profile_match': runtime_identity.get('profile') == approved_identity.get('profile'),
        'version_match': (
            runtime_identity.get('version') == approved_identity.get('version') and
            runtime_identity.get('schema_version') == approved_identity.get('schema_version')
        ),
        'schema_match': runtime_identity.get('schema_version') == approved_identity.get('schema_version'),
        'trained_through_match': runtime_identity.get('trained_through') == approved_identity.get('trained_through'),
    }
    result['details'] = details

    if rt_sha != ap_sha:
        result.update(status='MISMATCH', reason='runtime_artifact_hash_differs', match=False)
        return result

    # SHA matches: runtime model is the approved artifact. Metadata diagnostics are advisory.
    result.update(status='OK', reason='runtime_artifact_hash_matches', match=True)
    return result
