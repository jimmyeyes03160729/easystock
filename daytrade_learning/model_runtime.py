"""Pinned, approved research model inference. Never auto-promotes a candidate."""
import json
import hashlib
import math
import os
from pathlib import Path
from .features import FEATURES, SCHEMA_VERSION, finite, vector

MODEL_RUNTIME_VERSION = 'approved-model-gate-v3'


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
    def __init__(self, path=None):
        self.artifact = None
        self.artifact_sha256 = None
        self.model_version = MODEL_RUNTIME_VERSION
        self.threshold = None
        self.reason = 'no_approved_model'
        path = path if path is not None else os.environ.get('AI_PAPER_MODEL_PATH')
        if not path:
            return
        try:
            raw = Path(path).read_bytes()
            a = json.loads(raw)
            if not isinstance(a, dict):
                raise ValueError('invalid_model_object')
            if a.get('deployment_allowed') is not True or a.get('approved') is not True:
                raise ValueError('model_not_approved')
            if a.get('schema_version') != SCHEMA_VERSION or a.get('features') != list(FEATURES):
                raise ValueError('feature_schema_mismatch')
            n = len(FEATURES)
            for key in ('mean', 'scale', 'coef'):
                if len(a[key]) != n:
                    raise ValueError('invalid_model_dimensions')
                a[key] = [finite(x) for x in a[key]]
            if any(x <= 0 for x in a['scale']):
                raise ValueError('invalid_model_scale')
            a['intercept'] = finite(a['intercept'])
            threshold = finite(a['threshold'])
            if not 0 <= threshold <= 1 or not a.get('version'):
                raise ValueError('invalid_model_metadata')
            self.artifact, self.threshold = a, threshold
            self.artifact_sha256 = hashlib.sha256(raw).hexdigest()
            self.model_version, self.reason = str(a['version']), 'approved_model_loaded'
        except (OSError, ValueError, TypeError, KeyError) as exc:
            self.reason = 'invalid_or_unapproved_model:' + type(exc).__name__

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
