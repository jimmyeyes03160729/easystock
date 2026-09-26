import json
import os

from datetime import datetime, timezone, timedelta

import firebase_admin

from firebase_admin import (
    credentials,
    db,
)

from dotenv import load_dotenv


load_dotenv()


TPE = timezone(
    timedelta(hours=8)
)


FIREBASE_DATABASE_URL = (
    os.getenv(
        "FIREBASE_DATABASE_URL",
        "https://easystock-c237a-default-rtdb.firebaseio.com",
    )
    .strip()
    .rstrip("/")
)


FIREBASE_ROOT_PATH = (
    os.getenv(
        "FIREBASE_ROOT_PATH",
        "market_data",
    )
    .strip("/")
)


FIREBASE_LIVE_PATH = (
    os.getenv(
        "FIREBASE_LIVE_PATH",
        "intraday_live",
    )
    .strip("/")
)


SERVICE_ACCOUNT_FILE = (
    os.getenv(
        "FIREBASE_SERVICE_ACCOUNT_FILE",
        ""
    )
    .strip()
)


SERVICE_ACCOUNT_JSON = (
    os.getenv(
        "FIREBASE_SERVICE_ACCOUNT_JSON",
        ""
    )
    .strip()
)


# =========================================================
# JSON / Firebase 安全格式
# =========================================================

def safe_value(value):

    if isinstance(
        value,
        datetime
    ):
        return value.isoformat(
            timespec="seconds"
        )

    if isinstance(
        value,
        dict
    ):
        return {
            str(k):
                safe_value(v)
            for k, v
            in value.items()
        }

    if isinstance(
        value,
        (list, tuple)
    ):
        return [
            safe_value(v)
            for v in value
        ]

    return value


# =========================================================
# Firebase
# =========================================================

class FirebaseStore:

    def __init__(self):

        self._initialize()

        self.root = db.reference(
            f"/{FIREBASE_ROOT_PATH}"
        )

        self.live = self.root.child(
            FIREBASE_LIVE_PATH
        )


    def _initialize(self):

        if firebase_admin._apps:
            return


        if SERVICE_ACCOUNT_FILE:

            if not os.path.exists(
                SERVICE_ACCOUNT_FILE
            ):

                raise RuntimeError(
                    "Firebase service account "
                    f"檔案不存在："
                    f"{SERVICE_ACCOUNT_FILE}"
                )


            cred = credentials.Certificate(
                SERVICE_ACCOUNT_FILE
            )


        elif SERVICE_ACCOUNT_JSON:

            try:

                payload = json.loads(
                    SERVICE_ACCOUNT_JSON
                )

            except json.JSONDecodeError as e:

                raise RuntimeError(
                    "FIREBASE_SERVICE_ACCOUNT_JSON "
                    "不是有效 JSON"
                ) from e


            cred = credentials.Certificate(
                payload
            )


        else:

            raise RuntimeError(
                "缺少 Firebase 憑證。\n"
                "請設定 "
                "FIREBASE_SERVICE_ACCOUNT_FILE "
                "或 "
                "FIREBASE_SERVICE_ACCOUNT_JSON"
            )


        firebase_admin.initialize_app(
            cred,
            {
                "databaseURL":
                    FIREBASE_DATABASE_URL
            }
        )


    # =====================================================
    # 現在時間
    # =====================================================

    def now(self):
        return datetime.now(
            TPE
        )


    # =====================================================
    # Session
    # =====================================================

    def session_name(
        self,
        now=None,
    ):

        now = (
            now
            or self.now()
        )

        clock = now.time()


        if clock < datetime.strptime(
            "09:00",
            "%H:%M"
        ).time():

            return "preopen"


        if clock < datetime.strptime(
            "12:30",
            "%H:%M"
        ).time():

            return "daytrade"


        if clock < datetime.strptime(
            "12:55",
            "%H:%M"
        ).time():

            return "no_new_entry"


        if clock < datetime.strptime(
            "13:00",
            "%H:%M"
        ).time():

            return "force_exit"


        return "closed"


    # =====================================================
    # 啟動當日資料
    # =====================================================

    def start_day(
        self,
        market_level=None,
    ):

        now = self.now()

        payload = {
            "version":
                "shioaji-live-v1",

            "source":
                "sinotrade_shioaji",

            "scan_date":
                now.date().isoformat(),

            "generated_at":
                now.isoformat(
                    timespec="seconds"
                ),

            "last_update_at":
                now.isoformat(
                    timespec="seconds"
                ),

            "session":
                self.session_name(
                    now
                ),

            "market_level":
                market_level,

            "config": {
                "timezone":
                    "Asia/Taipei",

                "entry_start":
                    "09:30",

                "entry_cutoff":
                    "12:30",

                "force_exit":
                    "12:55",

                "daytrade_end":
                    "13:00",
            },
        }


        from daytrade_learning.daily_state import prepare_rollover
        old = self.live.get() or {}
        clean_payload = safe_value(payload)
        # Validate before any mutation; never erase unreconciled old OPEN positions.
        prepare_rollover(old, clean_payload)
        if old and old.get("scan_date") != clean_payload["scan_date"]:
            # Archive first. A failed archive aborts startup rather than dropping history.
            archive_key = now.strftime("%Y%m%dT%H%M%S%f")
            self.root.child("intraday_archive").child(archive_key).set(old)
        def update_day(current):
            if (current or {}) != old:
                raise RuntimeError("Live state changed during startup; abort to preserve concurrent writes")
            return prepare_rollover(current, clean_payload)
        self.live.transaction(update_day)
        return payload


    # =====================================================
    # ENTRY
    # =====================================================

    def write_entry(
        self,
        event,
    ):

        position = (
            event["position"]
        )

        symbol = str(
            position["symbol"]
        )


        now = self.now()


        payload = {
            **position,

            "status":
                "OPEN",

            "last_update_at":
                now,

            "source":
                "shioaji_live",
        }


        self.live.child(
            "open_positions"
        ).child(
            symbol
        ).set(
            safe_value(
                payload
            )
        )


        self.live.update({
            "last_update_at":
                now.isoformat(
                    timespec="seconds"
                ),

            "session":
                self.session_name(
                    now
                ),
        })


    # =====================================================
    # Tick 更新目前價格
    # =====================================================

    def update_position(
        self,
        position,
    ):

        symbol = str(
            position["symbol"]
        )


        payload = {
            "status":
                "OPEN",

            "current_price":
                position.get(
                    "current_price"
                ),

            "highest_price":
                position.get(
                    "highest_price"
                ),

            "lowest_price":
                position.get(
                    "lowest_price"
                ),

            "stop_price":
                position.get(
                    "stop_price"
                ),

            "take_profit_price":
                position.get(
                    "take_profit_price"
                ),

            "trailing_stop":
                position.get(
                    "trailing_stop"
                ),

            "last_update_at":
                position.get(
                    "last_update_at"
                ),
        }


        # Price ticks must never create OPEN records: the paper BUY may still
        # be pending/skipped, or a delayed tick may arrive after EXIT.
        trade_id = position.get("trade_id")
        entry_time = safe_value(position.get("entry_time"))
        if not trade_id or not entry_time:
            raise ValueError("OPEN price update requires entry identity")
        clean_payload = safe_value(payload)
        def update_existing(current):
            if not isinstance(current, dict):
                return current
            if (current.get("status") != "OPEN"
                    or current.get("trade_id") != trade_id
                    or current.get("entry_time") != entry_time):
                return current
            return {**current, **clean_payload}
        self.live.child("open_positions").child(symbol).transaction(update_existing)


    # =====================================================
    # EXIT
    # =====================================================

    def write_exit(
        self,
        event,
    ):

        trade = event[
            "trade"
        ]

        symbol = str(
            trade["symbol"]
        )


        entry_time = trade.get(
            "entry_time"
        )


        if isinstance(
            entry_time,
            datetime
        ):

            stamp = (
                entry_time
                .strftime(
                    "%Y%m%d_%H%M%S"
                )
            )

        else:

            stamp = (
                self.now()
                .strftime(
                    "%Y%m%d_%H%M%S"
                )
            )


        trade_id = str(trade.get('trade_id') or f"{stamp}_{symbol}")


        payload = {
            **trade,

            "trade_id":
                trade_id,

            "status":
                "CLOSED",

            "source":
                "shioaji_live",
        }


        self.live.update({
            "open_positions/" + symbol: None,
            "closed_trades/" + trade_id: safe_value(payload),
        })

        now = self.now()


        self.live.update({
            "last_update_at":
                now.isoformat(
                    timespec="seconds"
                ),

            "session":
                self.session_name(
                    now
                ),
        })


    # =====================================================
    # Heartbeat
    # =====================================================

    def heartbeat(self):

        now = self.now()


        self.live.update({
            "last_update_at":
                now.isoformat(
                    timespec="seconds"
                ),

            "session":
                self.session_name(
                    now
                ),
        })


    # =====================================================
    # 讀取 OPEN
    # =====================================================

    def load_open_positions(self):

        data = (
            self.live
            .child(
                "open_positions"
            )
            .get()
            or {}
        )


        if not isinstance(
            data,
            dict
        ):

            return {}


        return data


    # =====================================================
    # Firebase 連線測試
    # =====================================================

    def test_connection(self):

        now = self.now()

        test_ref = (
            self.live
            .child(
                "_connection_test"
            )
        )


        test_ref.set({
            "ok":
                True,

            "time":
                now.isoformat(
                    timespec="seconds"
                ),
        })


        result = (
            test_ref.get()
        )


        test_ref.delete()


        return bool(
            result
            and result.get("ok")
        )
