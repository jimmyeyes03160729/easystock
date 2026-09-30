"""Publish a fixed public health summary; private evidence stays on the VM."""
import time
import math
from datetime import datetime
import requests
from .health import aggregate, atomic, data_dir, observe, read_json, timestamp, TPE, market_session


def probe_fugle(now, session):
    import os
    previous = read_json(data_dir() / 'fugle.json')
    last = timestamp(previous.get('checked_at'))
    cadence = 300 if session == 'OPEN' else 900
    if last and 0 <= (now - last).total_seconds() < cadence: return
    key = os.environ.get('FUGLE_API_KEY', '').strip()
    if not key: return
    start = time.monotonic()
    try:
        response = requests.get('https://api.fugle.tw/marketdata/v1.0/stock/intraday/quote/2330',
                                headers={'X-API-KEY': key}, timeout=10)
        response.raise_for_status()
        payload = response.json()
        value = float(payload.get('lastPrice') or payload.get('closePrice'))
        at = float(payload['lastUpdated']) / 1e6
        if payload.get('symbol') != '2330' or not math.isfinite(value) or not math.isfinite(at) or value <= 0 or at > now.timestamp() + 2: raise ValueError()
        observe('fugle', ok=True, quote_at=datetime.fromtimestamp(at, TPE).isoformat(),
                latency_ms=round((time.monotonic() - start) * 1000), connected=True)
    except (requests.RequestException, ValueError, TypeError, KeyError, OverflowError):
        observe('fugle', ok=False, error_code='request_failed')


def main():
    from firebase_store import FirebaseStore
    from firebase_admin import db
    data_dir().mkdir(parents=True, exist_ok=True, mode=0o700)
    now = datetime.now(TPE)
    session = market_session(now)
    start = time.monotonic()
    try:
        FirebaseStore()
        probe_fugle(now, session)
        db.reference('/market_data/active_release').get()
        observe('firebase', ok=True, latency_ms=round((time.monotonic() - start) * 1000))
        public, _ = aggregate(now=datetime.now(TPE), session=session)
        db.reference('/market_data/provider_health').set(public)
        observe('firebase', ok=True)
        atomic(data_dir() / 'public-health.json', public)
        print('[PROVIDER_HEALTH] published ' + session)
    except Exception:
        observe('firebase', ok=False, error_code='publish_failed')
        print('[PROVIDER_HEALTH] publish_failed')
        raise SystemExit(1) from None


if __name__ == '__main__': main()
