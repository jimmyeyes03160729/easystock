"""Publish a fixed public health summary from VM and scheduled evidence."""
import time
from datetime import datetime
from .fugle_pipeline import evaluate, unavailable
from .health import aggregate, atomic, data_dir, observe, TPE, market_session


def main():
    from firebase_store import FirebaseStore
    from firebase_admin import db
    data_dir().mkdir(parents=True, exist_ok=True, mode=0o700)
    now = datetime.now(TPE)
    session = market_session(now)
    start = time.monotonic()
    try:
        FirebaseStore()
        try:
            from market_calendar import is_market_open
            evidence = db.reference('/market_data/provider_evidence/fugle').get()
            picks = db.reference('/market_data/intraday_picks').get()
            fugle = evaluate(evidence, picks, now, is_market_open)
        except Exception:
            fugle = unavailable(now)
        atomic(data_dir() / 'fugle.json', fugle)
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
