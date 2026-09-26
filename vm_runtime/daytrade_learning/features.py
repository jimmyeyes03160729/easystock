"""Versioned feature contract shared by research and online inference."""
import math

SCHEMA_VERSION = 'daytrade-research-v1'
FEATURES = ('gain_pct', 'return_5m_pct', 'surge_60s', 'buy_ratio_60s', 'amount_60s')


def finite(value):
    if value is None or isinstance(value, bool):
        raise ValueError('missing_feature')
    value = float(value)
    if not math.isfinite(value):
        raise ValueError('nonfinite_feature')
    return value


def vector(row):
    return [finite(row[name]) for name in FEATURES]

# Historical prototype only; never accepted by the online model loader.
LEGACY_FEATURES = ('gain_pct', 'return_5m_pct', 'volume_ratio', 'vwap_distance_pct', 'market_gain_pct')
