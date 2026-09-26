from datetime import datetime, timezone, timedelta
import threading
import time

from firebase_store import FirebaseStore


TPE = timezone(timedelta(hours=8))

STOCK_NAMES = {
    "2330": "台積電",
    "2317": "鴻海",
    "2454": "聯發科",
    "2303": "聯電",
}



_buffer = {}
_lock = threading.Lock()


def write_public_tick(
    symbol: str,
    name: str = "",
    price: float = 0,
    volume: int = 0,
):
    if not symbol:
        return

    data = {
        "symbol": symbol,
        "name": STOCK_NAMES.get(symbol, name or symbol),
        "price": price,
        "volume": volume,
        "updated_at":
            datetime.now(TPE).isoformat(timespec="seconds"),
    }

    with _lock:
        _buffer[symbol] = data


def flush_public_feed():
    global _buffer

    with _lock:
        if not _buffer:
            return

        payload = _buffer
        _buffer = {}

    try:
        FirebaseStore().root.child(
            "public_feed"
        ).update(payload)

    except Exception as exc:
        print(
            f"[PUBLIC FEED FLUSH ERROR] {exc}"
        )


def _worker():
    while True:
        time.sleep(3)

        try:
            flush_public_feed()
        except Exception as exc:
            print(
                f"[PUBLIC FEED WORKER ERROR] {exc}"
            )


_thread = threading.Thread(
    target=_worker,
    daemon=True,
)

_thread.start()
