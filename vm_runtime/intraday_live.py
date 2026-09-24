#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Easystock - Shioaji Instant Volume Surge Radar Intraday Engine
========================================

正式用途：
    Oracle VM
        ↓
    Sinotrade Shioaji Tick
        ↓
    1m / 5m / 15m K棒
        ↓
    strategy_engine.evaluate_daytrade()
        ↓
    position_manager.PositionManager
        ↓
    LINE + Firebase
        ↓
    GitHub Pages /market_data/intraday_live

重要：
- 本程式「不下單」；目前是訊號 / 模擬部位追蹤。
- 09:30 開始允許新進場。
- 12:30 停止新進場。
- 12:55 強制出場。
- 13:00 當沖完全結束。
- 停損 / 停利 / trailing 以 Tick 本機判斷，不等待 Firebase。
- Firebase OPEN 價格更新預設最多每 5 秒一次，避免每 Tick 寫 DB。
- Universe 預設每 60 秒重算；瞬間爆量雷達預設每 3 秒更新一次。\n- 新 ENTRY 不再等待 5 分 K 收完：雷達一達標，立即用最新完成的 5m/15m 趨勢背景 + 即時爆量欄位評估。\n- 5 分 K 完成時仍保留策略重評，作為技術條件/持倉管理的補充。\n- 每天硬性最多 3 檔 ENTRY；VM 重啟後仍從 Firebase 延續計數。
- 舊 Fugle scan_intraday.py 不應再產生 DAYTRADE。

已依目前專案既有介面設計：
    strategy_engine.evaluate_daytrade(rows5, rows15, stock=None, market_level="YELLOW")
    position_manager.PositionManager(...)
    firebase_store.FirebaseStore()
    FirebaseStore.start_day()
    FirebaseStore.write_entry()
    FirebaseStore.update_position()
    FirebaseStore.write_exit()
    FirebaseStore.load_open_positions()
    FirebaseStore.heartbeat()

Shioaji：
- 已兼容使用者目前測試成功的 Shioaji 1.7.x 介面：
      api.contracts.get("2330")
      api.subscribe(contract, quote_type=sj.QuoteType.Tick)
      callback: def on_tick(tick)
"""

from __future__ import annotations

from position_manager import PaperWallet

import inspect
import math
import os
import requests

from line_group_manager import get_active_groups

import re
import signal
import sys
import threading
import time

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date, datetime, time as dtime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import shioaji as sj

from firebase_admin import db

from firebase_store import FirebaseStore
from public_feed import write_public_tick
from position_manager import PositionManager
from daytrade_learning.runtime import Recorder
from daytrade_learning.model_runtime import DaytradeModel, live_features
from easystock_admin.store import read_live_settings
from strategy_engine import evaluate_daytrade, clamp
from paper_trade_game import register_signal, close_signal


# =========================================================
# Time
# =========================================================

TPE = timezone(timedelta(hours=8))

ENTRY_START = dtime(9, 30)
ENTRY_CUTOFF = dtime(12, 30)
FORCE_EXIT_TIME = dtime(12, 55)
DAYTRADE_END = dtime(13, 0)

# Shioaji 台股 Kbars 的 1m timestamp 在先前實測為 right-edge，
# 所以歷史 warm-start 會減 1 分鐘取得 bar start。
HISTORICAL_KBAR_IS_RIGHT_EDGE = True


# =========================================================
# Environment
# =========================================================

def load_dotenv_simple(path: str | Path = ".env") -> None:
    """
    不強制依賴 python-dotenv。
    若已有環境變數，不覆蓋。
    """
    p = Path(path)

    if not p.exists():
        return

    try:
        for raw_line in p.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()

            if (
                not line
                or line.startswith("#")
                or "=" not in line
            ):
                continue

            key, value = line.split("=", 1)

            key = key.strip()
            value = value.strip().strip('"').strip("'")

            if key:
                os.environ.setdefault(key, value)

    except Exception as exc:
        print(
            f"[WARN] .env 讀取失敗："
            f"{type(exc).__name__}: {exc}"
        )


load_dotenv_simple()


def env_first(*names: str, default: str = "") -> str:
    for name in names:
        value = os.environ.get(name)

        if value is not None and str(value).strip():
            return str(value).strip()

    return default


SJ_API_KEY = env_first(
    "SJ_API_KEY",
    "SHIOAJI_API_KEY",
)

SJ_SECRET_KEY = env_first(
    "SJ_SECRET_KEY",
    "SHIOAJI_SECRET_KEY",
)

# LINE：同時相容先前 LINE_USER_ID 與新版 LINE_TARGET_ID。
LINE_TOKEN = env_first(
    "LINE_CHANNEL_ACCESS_TOKEN",
    "LINE_ACCESS_TOKEN",
    "LINE_TOKEN",
)

LINE_TARGET_ID = env_first(
    "LINE_TARGET_ID",
    "LINE_USER_ID",
    "LINE_GROUP_ID",
)


# =========================================================
# Runtime config
# =========================================================

MAX_SYMBOLS = max(
    1,
    int(
        os.environ.get(
            "LIVE_MAX_SYMBOLS",
            "30",
        )
    ),
)


# 瞬間爆量雷達：
# 1) 全市場 Scanner 多排行粗篩活動股。
# 2) 最多訂閱 170 檔 Tick（Shioaji 上限 200，保留安全餘裕）。
# 3) 盤中以 10s / 30s / 60s 成交速度與最近數分鐘基準比較。
# 4) 只把符合「瞬間爆量 + 主動買盤 + 價格動能」者列入 Top30。
RADAR_POOL_SIZE = max(
    30,
    min(
        180,
        int(
            os.environ.get(
                "LIVE_RADAR_POOL_SIZE",
                "170",
            )
        ),
    ),
)

UNIVERSE_SCAN_COUNT = max(
    30,
    min(
        200,
        int(
            os.environ.get(
                "LIVE_UNIVERSE_SCAN_COUNT",
                "100",
            )
        ),
    ),
)

UNIVERSE_REFRESH_SECONDS = max(
    30.0,
    float(
        os.environ.get(
            "LIVE_UNIVERSE_REFRESH_SECONDS",
            "60",
        )
    ),
)

RADAR_REFRESH_SECONDS = max(
    2.0,
    float(
        os.environ.get(
            "LIVE_RADAR_REFRESH_SECONDS",
            "3",
        )
    ),
)

# 瞬間爆量達標後的新 ENTRY 評估節奏。
# 不放在 Shioaji callback 裡，避免策略/Firebase/LINE 阻塞行情 callback。
# 預設跟雷達同為 3 秒級。
INSTANT_ENTRY_EVAL_SECONDS = max(
    2.0,
    float(
        os.environ.get(
            "LIVE_INSTANT_ENTRY_EVAL_SECONDS",
            "3",
        )
    ),
)

RADAR_TOP_N = max(
    1,
    min(
        30,
        int(
            os.environ.get(
                "LIVE_RADAR_TOP_N",
                str(MAX_SYMBOLS),
            )
        ),
    ),
)

RADAR_HISTORY_SECONDS = max(
    300,
    int(
        os.environ.get(
            "LIVE_RADAR_HISTORY_SECONDS",
            "420",
        )
    ),
)

RADAR_BASELINE_WINDOWS = max(
    2,
    min(
        6,
        int(
            os.environ.get(
                "LIVE_RADAR_BASELINE_WINDOWS",
                "4",
            )
        ),
    ),
)

RADAR_MIN_SURGE = max(
    1.0,
    float(
        os.environ.get(
            "LIVE_RADAR_MIN_SURGE",
            "1.8",
        )
    ),
)

RADAR_MIN_BUY_RATIO = max(
    0.50,
    min(
        0.95,
        float(
            os.environ.get(
                "LIVE_RADAR_MIN_BUY_RATIO",
                "0.55",
            )
        ),
    ),
)

RADAR_MIN_CLASSIFIED_RATIO = max(
    0.0,
    min(
        1.0,
        float(
            os.environ.get(
                "LIVE_RADAR_MIN_CLASSIFIED_RATIO",
                "0.50",
            )
        ),
    ),
)

RADAR_MIN_60S_VOLUME = max(
    1.0,
    float(
        os.environ.get(
            "LIVE_RADAR_MIN_60S_VOLUME",
            "20",
        )
    ),
)

RADAR_MIN_60S_AMOUNT = max(
    0.0,
    float(
        os.environ.get(
            "LIVE_RADAR_MIN_60S_AMOUNT",
            "3000000",
        )
    ),
)

RADAR_MIN_PRICE_CHANGE_60_PCT = float(
    os.environ.get(
        "LIVE_RADAR_MIN_PRICE_CHANGE_60_PCT",
        "0.05",
    )
)

RADAR_MAX_WARM_QUERIES = max(
    0,
    min(
        200,
        int(
            os.environ.get(
                "LIVE_RADAR_MAX_WARM_QUERIES",
                "120",
            )
        ),
    ),
)

# 使用者要求：每天最多只產生 3 檔當沖 ENTRY。
paper_wallet = PaperWallet()

MAX_DAILY_ENTRIES = 999

FIREBASE_PRICE_UPDATE_SECONDS = max(
    1.0,
    float(
        os.environ.get(
            "LIVE_FIREBASE_PRICE_UPDATE_SECONDS",
            "5",
        )
    ),
)

HEARTBEAT_SECONDS = max(
    5.0,
    float(
        os.environ.get(
            "LIVE_HEARTBEAT_SECONDS",
            "15",
        )
    ),
)

LOOP_SLEEP_SECONDS = max(
    0.1,
    float(
        os.environ.get(
            "LIVE_LOOP_SLEEP_SECONDS",
            "0.5",
        )
    ),
)

STOP_LOSS_PCT = float(
    os.environ.get(
        "LIVE_STOP_LOSS_PCT",
        "0.008",
    )
)

TAKE_PROFIT_PCT = float(
    os.environ.get(
        "LIVE_TAKE_PROFIT_PCT",
        "0.012",
    )
)

TRAILING_ACTIVATE_PCT = float(
    os.environ.get(
        "LIVE_TRAILING_ACTIVATE_PCT",
        "0.006",
    )
)

TRAILING_PULLBACK_PCT = float(
    os.environ.get(
        "LIVE_TRAILING_PULLBACK_PCT",
        "0.004",
    )
)

MIN_WARM_5M_BARS = int(
    os.environ.get(
        "LIVE_MIN_WARM_5M_BARS",
        "6",
    )
)

MIN_WARM_15M_BARS = int(
    os.environ.get(
        "LIVE_MIN_WARM_15M_BARS",
        "2",
    )
)


# =========================================================
# Generic helpers
# =========================================================

def now_tpe() -> datetime:
    return datetime.now(TPE)


def num(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None

        result = float(value)

        if not math.isfinite(result):
            return None

        return result

    except (TypeError, ValueError):
        return None


def as_datetime(value: Any) -> datetime | None:
    """
    將 Shioaji / pandas / numpy / datetime / ISO string 時間
    轉成台灣時區 (+08:00) aware datetime。

    Shioaji 1.7.x historical Kbars 的 `ts`
    是 Unix timestamp nanoseconds，例如：
        1779094860000000000
    """

    if value is None:
        return None

    # -----------------------------------------------------
    # Python datetime
    # -----------------------------------------------------
    if isinstance(value, datetime):
        dt = value

    else:
        dt = None

        # -------------------------------------------------
        # pandas.Timestamp
        # -------------------------------------------------
        to_pydatetime = getattr(
            value,
            "to_pydatetime",
            None,
        )

        if callable(to_pydatetime):
            try:
                dt = to_pydatetime()
            except Exception:
                dt = None

        # -------------------------------------------------
        # Shioaji integer Unix timestamp
        # ns / us / ms / seconds
        # -------------------------------------------------
        if dt is None:
            numeric = None

            try:
                if not isinstance(
                    value,
                    bool,
                ):
                    numeric = float(
                        value
                    )
            except (
                TypeError,
                ValueError,
                OverflowError,
            ):
                numeric = None

            if (
                numeric is not None
                and
                math.isfinite(
                    numeric
                )
                and
                abs(numeric) >= 1_000_000_000
            ):
                magnitude = abs(
                    numeric
                )

                if magnitude >= 1e17:
                    # nanoseconds
                    seconds = (
                        numeric
                        /
                        1_000_000_000
                    )

                elif magnitude >= 1e14:
                    # microseconds
                    seconds = (
                        numeric
                        /
                        1_000_000
                    )

                elif magnitude >= 1e11:
                    # milliseconds
                    seconds = (
                        numeric
                        /
                        1_000
                    )

                else:
                    # seconds
                    seconds = numeric

                try:
                    # Shioaji Kbars 的 raw integer `ts` 雖然長得像
                    # Unix ns，但官方範例將：
                    # 1779094860000000000 -> 2026-05-18 09:01:00
                    #
                    # 也就是「台灣本地鐘面時間」直接編碼在 epoch 數值裡；
                    # 不能用 fromtimestamp(..., tz=TPE)，否則會多加 +8 小時
                    # 變成 17:01，接著被日盤時間過濾掉。
                    #
                    # 正確做法：
                    # 先按 UTC 數值取出 09:01 的鐘面，
                    # 再把這個 naive clock attach 成 TPE。
                    dt = datetime.fromtimestamp(
                        seconds,
                        tz=timezone.utc,
                    ).replace(
                        tzinfo=None
                    ).replace(
                        tzinfo=TPE
                    )

                except (
                    OSError,
                    OverflowError,
                    ValueError,
                ):
                    dt = None

        # -------------------------------------------------
        # numpy.datetime64 / ISO string fallback
        # -------------------------------------------------
        if dt is None:
            value_text = str(
                value
            ).strip()

            if not value_text:
                return None

            if value_text.endswith(
                "Z"
            ):
                value_text = (
                    value_text[:-1]
                    +
                    "+00:00"
                )

            try:
                dt = datetime.fromisoformat(
                    value_text
                )
            except Exception:
                return None

    if dt.tzinfo is None:
        # Shioaji文字日期時間為台灣本地時間。
        return dt.replace(
            tzinfo=TPE
        )

    return dt.astimezone(
        TPE
    )

def floor_minute(dt: datetime, minutes: int) -> datetime:
    dt = dt.astimezone(TPE)

    minute = (
        dt.minute
        //
        minutes
        *
        minutes
    )

    return dt.replace(
        minute=minute,
        second=0,
        microsecond=0,
    )


def session_name(dt: datetime | None = None) -> str:
    dt = dt or now_tpe()
    t = dt.timetz().replace(tzinfo=None)

    if t < dtime(9, 0):
        return "preopen"

    if t < ENTRY_CUTOFF:
        return "daytrade"

    if t < FORCE_EXIT_TIME:
        return "no_new_entry"

    if t < DAYTRADE_END:
        return "force_exit"

    return "closed"


def in_entry_window(dt: datetime | None = None) -> bool:
    dt = dt or now_tpe()
    t = dt.timetz().replace(tzinfo=None)

    return (
        ENTRY_START
        <= t
        < ENTRY_CUTOFF
    )


def has_force_exit_started(dt: datetime | None = None) -> bool:
    dt = dt or now_tpe()
    t = dt.timetz().replace(tzinfo=None)

    return t >= FORCE_EXIT_TIME


def daytrade_closed(dt: datetime | None = None) -> bool:
    dt = dt or now_tpe()
    t = dt.timetz().replace(tzinfo=None)

    return t >= DAYTRADE_END


# =========================================================
# LINE adapter
# =========================================================

def _load_line_module() -> Any:
    try:
        import line_bot  # type: ignore
        return line_bot

    except Exception as exc:
        print(
            f"[WARN] line_bot import 失敗："
            f"{type(exc).__name__}: {exc}"
        )
        return None


LINE_MODULE = _load_line_module()


def push_line_text(text: str, entry_check=None, event=None) -> bool:
    # Compatibility name retained; fan out only entry/exit events to both channels.
    from trade_notifications import send_trade, event_identity
    return send_trade(text, _push_line_only, entry_check=entry_check, event_key=event_identity(event, text))


def _push_line_only(text: str, entry_check=None) -> bool:
    from line_policy import push_allowed
    groups = get_active_groups()
    registered_groups = bool(groups)
    groups = [gid for gid in groups if push_allowed(gid, 'trade')]
    if registered_groups and not groups:
        return False

    if groups:
        ok = False

        for gid in groups:
            try:
                if entry_check is not None and not entry_check():
                    print("[LINE] ENTRY skipped: latest quote no longer passes limits")
                    continue
                payload = {
                    "to": gid,
                    "messages": [
                        {
                            "type": "text",
                            "text": text,
                        }
                    ],
                }

                response = requests.post(
                    "https://api.line.me/v2/bot/message/push",
                    headers={
                        "Authorization": f"Bearer {LINE_TOKEN}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=10,
                )

                print(
                    f"[LINE GROUP] {gid} status={response.status_code}"
                )

                if response.status_code == 200:
                    ok = True

            except Exception as e:
                print("[LINE GROUP ERROR]", e)

        return ok

    """
    先嘗試專案既有 line_bot.py；
    找不到可呼叫函式時，再使用 LINE Messaging API HTTP fallback。
    """
    if not text.strip():
        return False
    if entry_check is not None and not entry_check():
        print("[LINE] ENTRY skipped: latest quote no longer passes limits")
        return False

    if not push_allowed(LINE_TARGET_ID, 'trade'):
        return False
    # Legacy generic adapters have no event category; use the guarded HTTP path.
    module = None

    if module is not None:
        # 盡量相容不同版本 line_bot.py
        candidates = [
            "push_message",
            "push_text",
            "send_message",
            "send_line_message",
            "line_push",
            "push_line_message",
        ]

        for name in candidates:
            fn = getattr(module, name, None)

            if not callable(fn):
                continue

            try:
                sig = inspect.signature(fn)
                params = list(sig.parameters.values())

                # 常見一參數：fn(text)
                if len(params) == 1:
                    result = fn(text)
                    return result is not False

                # 常見二參數：fn(target, text)
                if len(params) >= 2:
                    result = fn(LINE_TARGET_ID, text)
                    return result is not False

            except Exception as exc:
                print(
                    f"[WARN] line_bot.{name} 呼叫失敗："
                    f"{type(exc).__name__}: {exc}"
                )

    if not LINE_TOKEN or not LINE_TARGET_ID:
        print(
            "[WARN] LINE fallback 缺少 "
            "LINE_CHANNEL_ACCESS_TOKEN / LINE_TARGET_ID"
        )
        return False

    if entry_check is not None and not entry_check():
        return False
    try:

        response = requests.post(
            "https://api.line.me/v2/bot/message/push",
            headers={
                "Authorization": f"Bearer {LINE_TOKEN}",
                "Content-Type": "application/json",
            },
            json={
                "to": LINE_TARGET_ID,
                "messages": [
                    {
                        "type": "text",
                        "text": text,
                    }
                ],
            },
            timeout=10,
        )

        if response.status_code != 200:
            print(
                "[WARN] LINE push failed "
                f"status={response.status_code}"
            )
            return False

        print("[LINE] Push success")
        return True

    except Exception as exc:
        print(
            f"[WARN] LINE push error："
            f"{type(exc).__name__}: {exc}"
        )
        return False


def format_entry_message(
    event: dict,
    market_level: str,
) -> str:
    position = (
        event.get("position")
        if isinstance(event, dict)
        else None
    )

    data = position if isinstance(position, dict) else event

    if not isinstance(data, dict):
        data = {}

    symbol = str(data.get("symbol") or "")
    name = str(data.get("name") or symbol)

    score = (
        data.get("entry_score")
        or data.get("score")
    )

    change = num(
        data.get("change_pct")
        or data.get("price_change_pct")
        or data.get("price_change_60_pct")
    )

    change_text = (
        f"{change:+.2f}%"
        if change is not None
        else ""
    )

    return "\n".join([
        "⚡ 當沖吧！牛馬仔｜當沖 ENTRY",
        f"{symbol} {name} {change_text}".strip(),
        f"分數 {score}" if score is not None else "分數 --",
    ])


def format_exit_message(
    event: dict,
) -> str:
    trade = (
        event.get("trade")
        if isinstance(event, dict)
        else None
    )

    data = trade if isinstance(trade, dict) else event

    if not isinstance(data, dict):
        data = {}

    symbol = str(data.get("symbol") or "")
    name = str(data.get("name") or symbol)

    pnl = num(data.get("pnl_pct"))

    pnl_text = (
        f"{pnl:+.2f}%"
        if pnl is not None
        else "--"
    )

    return "\n".join([
        "✅ 當沖吧！牛馬仔｜當沖 EXIT",
        f"{symbol} {name}",
        pnl_text,
    ])



class Bar:
    def __init__(
        self,
        start: datetime,
        open: float,
        high: float,
        low: float,
        close: float,
        volume: float = 0.0,
    ):
        self.start = start
        self.open = float(open)
        self.high = float(high)
        self.low = float(low)
        self.close = float(close)
        self.volume = float(volume)


class LiveBarBook:
    """
    每檔股票保留 1m completed bars + current 1m。
    5m / 15m 由 completed 1m 聚合，避免 partial bar lookahead。
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()

        self.completed_1m: dict[
            str,
            list[Bar],
        ] = defaultdict(list)

        self.current_1m: dict[
            str,
            Bar,
        ] = {}

        self.last_completed_5m_key: dict[
            str,
            datetime,
        ] = {}

    def seed_1m(
        self,
        symbol: str,
        rows: list[Bar],
    ) -> None:
        with self._lock:
            dedup: dict[datetime, Bar] = {}

            for row in rows:
                dedup[row.start] = row

            self.completed_1m[symbol] = [
                dedup[key]
                for key in sorted(dedup)
            ]

    def on_tick(
        self,
        symbol: str,
        price: float,
        volume: float,
        tick_time: datetime,
    ) -> tuple[bool, datetime | None]:
        """
        Return:
            (five_minute_completed, completed_5m_start_key)
        """
        minute_start = floor_minute(
            tick_time,
            1,
        )

        with self._lock:
            current = self.current_1m.get(
                symbol
            )

            if current is None:
                self.current_1m[symbol] = Bar(
                    start=minute_start,
                    open=price,
                    high=price,
                    low=price,
                    close=price,
                    volume=max(
                        0.0,
                        volume,
                    ),
                )
                return False, None

            if minute_start == current.start:
                current.high = max(
                    current.high,
                    price,
                )
                current.low = min(
                    current.low,
                    price,
                )
                current.close = price
                current.volume += max(
                    0.0,
                    volume,
                )
                return False, None

            # 新分鐘來了，上一分鐘完成。
            self.completed_1m[
                symbol
            ].append(
                current
            )

            # 防止重連造成大量重複，僅保留合理長度。
            if (
                len(
                    self.completed_1m[
                        symbol
                    ]
                )
                > 500
            ):
                self.completed_1m[
                    symbol
                ] = self.completed_1m[
                    symbol
                ][-500:]

            self.current_1m[symbol] = Bar(
                start=minute_start,
                open=price,
                high=price,
                low=price,
                close=price,
                volume=max(
                    0.0,
                    volume,
                ),
            )

            # 上一完成 1m 屬於哪一個 5m bucket。
            key = floor_minute(
                current.start,
                5,
            )

            # 只有當剛完成的 1m 為 bucket 最後一分鐘時，
            # 才算整根 5m 完成：
            # 09:04 -> 09:00 bar 完成
            # 09:09 -> 09:05 bar 完成
            completed_5m = (
                current.start.minute % 5
                == 4
            )

            if completed_5m:
                previous = (
                    self.last_completed_5m_key
                    .get(symbol)
                )

                if previous == key:
                    return False, None

                self.last_completed_5m_key[
                    symbol
                ] = key

                return True, key

            return False, None

    def _aggregate(
        self,
        symbol: str,
        minutes: int,
    ) -> list[dict]:
        with self._lock:
            rows = list(
                self.completed_1m.get(
                    symbol,
                    [],
                )
            )

        if not rows:
            return []

        grouped: dict[
            datetime,
            list[Bar],
        ] = defaultdict(list)

        for bar in rows:
            key = floor_minute(
                bar.start,
                minutes,
            )
            grouped[key].append(
                bar
            )

        output: list[dict] = []

        for key in sorted(grouped):
            chunk = sorted(
                grouped[key],
                key=lambda x: x.start,
            )

            # 只使用完整 bucket：
            # 5m = 5 根 1m
            # 15m = 15 根 1m
            if len(chunk) < minutes:
                continue

            # 防止跨洞資料：首尾分鐘跨度要吻合。
            expected_last = (
                key
                + timedelta(
                    minutes=minutes - 1
                )
            )

            if chunk[-1].start != expected_last:
                continue

            output.append({
                "date":
                    key.isoformat(
                        timespec="seconds"
                    ),
                "open":
                    chunk[0].open,
                "high":
                    max(
                        x.high
                        for x in chunk
                    ),
                "low":
                    min(
                        x.low
                        for x in chunk
                    ),
                "close":
                    chunk[-1].close,
                "volume":
                    sum(
                        x.volume
                        for x in chunk
                    ),
            })

        return output

    def rows5(
        self,
        symbol: str,
    ) -> list[dict]:
        return self._aggregate(
            symbol,
            5,
        )

    def rows15(
        self,
        symbol: str,
    ) -> list[dict]:
        return self._aggregate(
            symbol,
            15,
        )


# =========================================================
# Position Manager adapter
# =========================================================

def build_position_manager() -> PositionManager:
    return PositionManager(
        stop_loss_pct=STOP_LOSS_PCT,
        take_profit_pct=TAKE_PROFIT_PCT,
        trailing_activate_pct=TRAILING_ACTIVATE_PCT,
        trailing_pullback_pct=TRAILING_PULLBACK_PCT,
        allow_reentry=False,
    )


def get_position_safe(
    manager: PositionManager,
    symbol: str,
) -> dict | None:
    fn = getattr(
        manager,
        "get_position",
        None,
    )

    if callable(fn):
        try:
            result = fn(symbol)

            if isinstance(result, dict):
                return result

        except Exception as exc:
            print(
                f"[WARN] get_position {symbol}: "
                f"{type(exc).__name__}: {exc}"
            )

    # fallback：有些版本直接用 positions dict
    positions = getattr(
        manager,
        "positions",
        None,
    )

    if isinstance(positions, dict):
        value = positions.get(symbol)

        if isinstance(value, dict):
            return value

    return None


def call_manager_on_tick(
    manager: PositionManager,
    symbol: str,
    price: float,
    tick_time: datetime,
) -> Any:
    """
    兼容 position_manager.py 不同版本 on_tick signature。
    """
    fn = getattr(
        manager,
        "on_tick",
        None,
    )

    if not callable(fn):
        return None

    try:
        sig = inspect.signature(fn)

        kwargs: dict[str, Any] = {}

        for name in sig.parameters:
            lowered = name.lower()

            if lowered in {
                "symbol",
                "code",
            }:
                kwargs[name] = symbol

            elif lowered in {
                "price",
                "current_price",
                "close",
            }:
                kwargs[name] = price

            elif lowered in {
                "tick_time",
                "time",
                "timestamp",
                "dt",
                "now",
            }:
                kwargs[name] = tick_time

        if kwargs:
            return fn(**kwargs)

    except TypeError:
        pass

    except Exception as exc:
        print(
            f"[WARN] manager.on_tick "
            f"{symbol}: "
            f"{type(exc).__name__}: {exc}"
        )
        return None

    # positional fallbacks
    attempts = [
        (symbol, price, tick_time),
        (symbol, price),
        (price, symbol, tick_time),
    ]

    for args in attempts:
        try:
            return fn(*args)

        except TypeError:
            continue

        except Exception as exc:
            print(
                f"[WARN] manager.on_tick "
                f"{symbol}: "
                f"{type(exc).__name__}: {exc}"
            )
            return None

    return None


def call_manager_strategy_result(
    manager: PositionManager,
    symbol: str,
    result: dict,
    price: float,
    dt: datetime,
) -> Any:
    fn = getattr(
        manager,
        "on_strategy_result",
        None,
    )

    if not callable(fn):
        return None

    try:
        sig = inspect.signature(fn)

        kwargs: dict[str, Any] = {}

        for name in sig.parameters:
            lowered = name.lower()

            if lowered in {
                "symbol",
                "code",
            }:
                kwargs[name] = symbol

            elif lowered in {
                "result",
                "strategy_result",
                "signal",
            }:
                kwargs[name] = result

            elif lowered in {
                "price",
                "current_price",
                "close",
            }:
                kwargs[name] = price

            elif lowered in {
                "time",
                "timestamp",
                "dt",
                "now",
                "strategy_time",
            }:
                kwargs[name] = dt

        if kwargs:
            return fn(**kwargs)

    except TypeError:
        pass

    except Exception as exc:
        print(
            f"[WARN] on_strategy_result "
            f"{symbol}: "
            f"{type(exc).__name__}: {exc}"
        )
        return None

    attempts = [
        (symbol, result, price, dt),
        (symbol, result, price),
        (symbol, result),
    ]

    for args in attempts:
        try:
            return fn(*args)

        except TypeError:
            continue

        except Exception as exc:
            print(
                f"[WARN] on_strategy_result "
                f"{symbol}: "
                f"{type(exc).__name__}: {exc}"
            )
            return None

    return None


def is_exit_event(value: Any) -> bool:
    if not isinstance(value, dict):
        return False

    if isinstance(
        value.get("trade"),
        dict,
    ):
        return True

    event_type = str(
        value.get("type")
        or value.get("event")
        or value.get("action")
        or ""
    ).upper()

    if event_type in {
        "EXIT",
        "CLOSE",
        "CLOSED",
    }:
        return True

    return (
        value.get("exit_price")
        is not None
        and value.get("entry_price")
        is not None
    )


# =========================================================
# Firebase adapter
# =========================================================

def firebase_heartbeat(
    store: FirebaseStore,
    market_level: str,
) -> None:
    fn = getattr(
        store,
        "heartbeat",
        None,
    )

    if not callable(fn):
        return

    payload = {
        "market_level":
            market_level,
        "session":
            session_name(),
        "source":
            "sinotrade_shioaji",
    }

    try:
        sig = inspect.signature(fn)

        kwargs: dict[str, Any] = {}

        for name in sig.parameters:
            lowered = name.lower()

            if lowered == "market_level":
                kwargs[name] = market_level

            elif lowered == "session":
                kwargs[name] = session_name()

            elif lowered in {
                "payload",
                "data",
                "extra",
            }:
                kwargs[name] = payload

        if kwargs:
            fn(**kwargs)
        else:
            fn()

    except TypeError:
        try:
            fn(
                market_level=market_level
            )
        except Exception:
            try:
                fn()
            except Exception:
                return

    except Exception as exc:
        print(
            f"[WARN] Firebase heartbeat: "
            f"{type(exc).__name__}: {exc}"
        )


def load_market_context() -> tuple[str, dict]:
    """
    FirebaseStore 初始化後 firebase_admin 已可用。
    優先用 premarket_brief.market_level，
    再 fallback intraday_picks.market_level。
    """
    brief: dict = {}

    try:
        value = db.reference(
            "/market_data/premarket_brief"
        ).get()

        if isinstance(value, dict):
            brief = value

    except Exception:
        brief = {}

    level = str(
        brief.get(
            "market_level"
        )
        or ""
    ).upper()

    if level not in {
        "GREEN",
        "YELLOW",
        "RED",
    }:
        try:
            legacy = db.reference(
                "/market_data/intraday_picks/market_level"
            ).get()

            level = str(
                legacy
                or "YELLOW"
            ).upper()

        except Exception:
            level = "YELLOW"

    if level not in {
        "GREEN",
        "YELLOW",
        "RED",
    }:
        level = "YELLOW"

    return level, brief


def load_candidates_from_firebase(
    max_symbols: int,
) -> list[dict]:
    """
    從 /market_data/summary 取得候選股票。
    先依 amount_rank_pct，再依 hot_rank。
    """
    raw = db.reference(
        "/market_data/summary"
    ).get()

    if isinstance(raw, dict):
        stocks = [
            x
            for x in raw.values()
            if isinstance(x, dict)
        ]

    elif isinstance(raw, list):
        stocks = [
            x
            for x in raw
            if isinstance(x, dict)
        ]

    else:
        stocks = []

    def score(stock: dict) -> tuple:
        amount = num(
            stock.get(
                "amount_rank_pct"
            )
        )

        hot = num(
            stock.get(
                "hot_rank"
            )
        )

        return (
            amount
            if amount is not None
            else -1.0,

            -hot
            if hot is not None
            else -999999.0,
        )

    ordered = sorted(
        stocks,
        key=score,
        reverse=True,
    )

    output: list[dict] = []
    seen: set[str] = set()

    for stock in ordered:
        symbol = str(
            stock.get("symbol")
            or stock.get("code")
            or ""
        ).strip()

        if (
            not symbol
            or symbol in seen
        ):
            continue

        price = num(
            stock.get("price")
        )

        # 沒價格也不是絕對不能訂閱，
        # 但 summary 裡完全沒 symbol / price 的資料通常不是股票列。
        if price is not None and price <= 0:
            continue

        seen.add(symbol)

        item = dict(stock)
        item["symbol"] = symbol
        item["name"] = str(
            stock.get("name")
            or symbol
        )

        output.append(item)

        if len(output) >= max_symbols:
            break

    return output


# =========================================================
# Shioaji / Kbars
# =========================================================

def get_contract(
    api: sj.Shioaji,
    symbol: str,
) -> Any:
    try:
        return api.contracts.get(
            symbol
        )

    except Exception:
        pass

    # fallback for older API layout
    try:
        stocks = getattr(
            api.Contracts,
            "Stocks",
        )

        for market_name in (
            "TSE",
            "OTC",
        ):
            market = getattr(
                stocks,
                market_name,
                None,
            )

            if market is None:
                continue

            try:
                return market[
                    symbol
                ]
            except Exception:
                continue

    except Exception:
        pass

    return None


def kbars_to_1m(
    payload: Any,
) -> list[Bar]:
    """
    將 Shioaji api.kbars(...) 結果轉為 Bar。
    支援 dict / namedtuple-like / pandas-friendly array 欄位。
    """
    if payload is None:
        return []

    def field(name: str) -> list:
        if isinstance(payload, dict):
            value = payload.get(name)

        else:
            value = getattr(
                payload,
                name,
                None,
            )

        if value is None:
            return []

        try:
            return list(value)
        except TypeError:
            return []

    ts = (
        field("ts")
        or field("datetime")
        or field("date")
    )

    opens = field("Open") or field("open")
    highs = field("High") or field("high")
    lows = field("Low") or field("low")
    closes = field("Close") or field("close")
    volumes = field("Volume") or field("volume")

    size = min(
        len(ts),
        len(opens),
        len(highs),
        len(lows),
        len(closes),
    )

    rows: list[Bar] = []

    for i in range(size):
        dt = as_datetime(
            ts[i]
        )

        o = num(
            opens[i]
        )
        h = num(
            highs[i]
        )
        l = num(
            lows[i]
        )
        c = num(
            closes[i]
        )

        v = (
            num(
                volumes[i]
            )
            if i < len(volumes)
            else 0.0
        )

        if (
            dt is None
            or o is None
            or h is None
            or l is None
            or c is None
        ):
            continue

        if HISTORICAL_KBAR_IS_RIGHT_EDGE:
            dt = (
                dt
                - timedelta(
                    minutes=1
                )
            )

        dt = dt.replace(
            second=0,
            microsecond=0,
        )

        # 僅保留正常日盤分鐘
        tt = dt.timetz().replace(
            tzinfo=None
        )

        if not (
            dtime(9, 0)
            <= tt
            <= dtime(13, 29)
        ):
            continue

        rows.append(
            Bar(
                start=dt,
                open=o,
                high=h,
                low=l,
                close=c,
                volume=max(
                    0.0,
                    v or 0.0,
                ),
            )
        )

    # dedupe
    dedup = {
        row.start: row
        for row in rows
    }

    return [
        dedup[key]
        for key in sorted(dedup)
    ]


def warm_symbol(
    api: sj.Shioaji,
    contract: Any,
    symbol: str,
    bars: LiveBarBook,
) -> int:
    today = now_tpe().date().isoformat()

    payload = api.kbars(
        contract=contract,
        start=today,
        end=today,
    )

    rows = kbars_to_1m(
        payload
    )

    # 若今天已經盤中，Shioaji 歷史資料可能含「尚未完成的最新分鐘」。
    # 只保留早於目前分鐘的 bar。
    current_minute = floor_minute(
        now_tpe(),
        1,
    )

    rows = [
        row
        for row in rows
        if row.start < current_minute
    ]

    bars.seed_1m(
        symbol,
        rows,
    )

    return len(rows)


# =========================================================
# Tick extraction
# =========================================================

def attr_first(
    obj: Any,
    *names: str,
) -> Any:
    for name in names:
        try:
            value = getattr(
                obj,
                name,
            )

            if value is not None:
                return value

        except Exception:
            pass

        if isinstance(obj, dict):
            if name in obj:
                return obj[name]

    return None


def tick_symbol(
    tick: Any,
) -> str:
    value = attr_first(
        tick,
        "code",
        "symbol",
        "stock_id",
    )

    return str(
        value
        or ""
    ).strip()


def tick_price(
    tick: Any,
) -> float | None:
    return num(
        attr_first(
            tick,
            "close",
            "price",
            "last_price",
        )
    )


def tick_volume(
    tick: Any,
) -> float:
    value = num(
        attr_first(
            tick,
            "volume",
            "qty",
            "quantity",
        )
    )

    return max(
        0.0,
        value or 0.0,
    )


def tick_type_value(
    tick: Any,
) -> int:
    """
    Shioaji stock Tick:
      1 = 外盤（主動買）
      2 = 內盤（主動賣）
      0 = 無法判定
    """
    value = attr_first(
        tick,
        "tick_type",
        "type",
    )

    if hasattr(value, "value"):
        try:
            value = value.value
        except Exception:
            pass

    try:
        integer = int(value)
        return integer if integer in {1, 2} else 0
    except Exception:
        pass

    lowered = str(value or "").strip().lower()

    if lowered in {
        "buy",
        "ask",
        "外盤",
    }:
        return 1

    if lowered in {
        "sell",
        "bid",
        "內盤",
    }:
        return 2

    return 0


def tick_amount(
    tick: Any,
    price: float,
    volume: float,
) -> float:
    value = num(
        attr_first(
            tick,
            "amount",
            "trade_amount",
        )
    )

    if value is not None and value >= 0:
        return float(value)

    # 整股 Tick volume 單位為「張」，1 張 = 1000 股。
    return max(
        0.0,
        float(price)
        * float(volume)
        * 1000.0,
    )


def tick_datetime(
    tick: Any,
) -> datetime:
    value = attr_first(
        tick,
        "datetime",
        "ts",
        "timestamp",
        "time",
    )

    dt = as_datetime(
        value
    )

    return dt or now_tpe()



# =========================================================
# Market activity universe + instant volume surge radar
# =========================================================

def scanner_item_to_dict(item: Any) -> dict:
    result = {}

    for key in (
        "date",
        "code",
        "name",
        "ts",
        "datetime",
        "open",
        "high",
        "low",
        "close",
        "price_range",
        "tick_type",
        "change_price",
        "change_type",
        "average_price",
        "volume",
        "total_volume",
        "amount",
        "total_amount",
        "yesterday_volume",
        "volume_ratio",
        "buy_price",
        "buy_volume",
        "sell_price",
        "sell_volume",
        "bid_orders",
        "bid_volumes",
        "ask_orders",
        "ask_volumes",
        "rank_value",
    ):
        result[key] = attr_first(
            item,
            key,
        )

    return result


def _scanner_rank(
    api: sj.Shioaji,
    scanner_name: str,
) -> list[Any]:
    scanner_type = getattr(
        sj.ScannerType,
        scanner_name,
        None,
    )

    if scanner_type is None:
        return []

    try:
        rows = api.scanners(
            scanner_type=scanner_type,
            ascending=True,
            count=UNIVERSE_SCAN_COUNT,
            timeout=30000,
        )
        return list(rows or [])

    except Exception as exc:
        print(
            f"[WARN] scanner {scanner_name}: "
            f"{type(exc).__name__}: {exc}"
        )
        return []


def scan_market_activity_universe(
    api: sj.Shioaji,
    limit: int = RADAR_POOL_SIZE,
) -> list[dict]:
    """
    從全市場多種排行抓出「此刻最活躍」股票，作為 Tick 雷達來源池。

    不是把累積成交量直接當 ENTRY；这里只負責粗篩，
    真正的候選由後續 10/30/60 秒瞬間爆量計算決定。
    """
    configs = (
        ("AmountRank", 0.30),
        ("VolumeRank", 0.25),
        ("TickCountRank", 0.25),
        ("ChangePercentRank", 0.10),
        ("DayRangeRank", 0.10),
    )

    merged: dict[str, dict] = {}

    for scanner_name, weight in configs:
        rows = _scanner_rank(
            api,
            scanner_name,
        )

        total = max(
            1,
            len(rows),
        )

        for rank, item in enumerate(
            rows,
            start=1,
        ):
            row = scanner_item_to_dict(
                item
            )

            symbol = str(
                row.get("code")
                or ""
            ).strip()

            if not re.fullmatch(
                r"\d{4}",
                symbol,
            ):
                continue

            # 當沖過濾：排除金融保險類股（28開頭），其振幅難以跨越當沖交易成本
            if symbol.startswith("28"):
                continue

            close = num(
                row.get("close")
            )

            if close is None or close <= 0:
                continue

            target = merged.setdefault(
                symbol,
                {
                    "symbol": symbol,
                    "name": str(
                        row.get("name")
                        or symbol
                    ).strip(),
                    "activity_score": 0.0,
                    "activity_sources": [],
                },
            )

            # 排名越前，分數越高。
            rank_score = (
                (total - rank + 1)
                / total
                * 100.0
            )

            target[
                "activity_score"
            ] += rank_score * weight

            target[
                "activity_sources"
            ].append(
                scanner_name
            )

            # 保存較新/完整的 Scanner metadata。
            for key in (
                "close",
                "average_price",
                "change_price",
                "total_volume",
                "total_amount",
                "volume_ratio",
                "bid_volumes",
                "ask_volumes",
            ):
                value = row.get(key)
                if value is not None:
                    target[key] = value

            target[
                scanner_name
                + "_rank"
            ] = rank

    rows = list(
        merged.values()
    )

    rows.sort(
        key=lambda row: (
            row.get("activity_score")
            or 0.0,
            num(row.get("total_amount"))
            or 0.0,
        ),
        reverse=True,
    )

    output = rows[
        :max(1, int(limit))
    ]

    for rank, row in enumerate(
        output,
        start=1,
    ):
        row[
            "activity_rank"
        ] = rank
        row[
            "activity_score"
        ] = round(
            float(
                row.get("activity_score")
                or 0.0
            ),
            2,
        )

    return output


def compute_volume_surge_metrics(
    events: list[tuple[float, float, int, float, float]],
    now_ts: float,
    day_average_price: float | None = None,
) -> dict | None:
    """
    events tuple:
      (timestamp, volume, tick_type, price, amount)

    比較最近60秒與前 RADAR_BASELINE_WINDOWS 個60秒區間。
    baseline 使用固定時間窗，沒有成交的區間也算0，
    因此可以抓到「原本安靜 → 突然爆量」。
    """
    if not events:
        return None

    cutoff = (
        now_ts
        - max(
            RADAR_HISTORY_SECONDS,
            60 * (
                RADAR_BASELINE_WINDOWS
                + 2
            ),
        )
    )

    rows = [
        event
        for event in events
        if event[0] >= cutoff
        and event[0] <= now_ts
    ]

    if not rows:
        return None

    earliest_ts = rows[0][0]

    # 至少要有120秒觀察史，避免剛加入 universe 就被誤判為爆量。
    history_seconds = max(
        0.0,
        now_ts - earliest_ts,
    )

    if history_seconds < 120.0:
        return None

    def in_window(
        seconds_from: float,
        seconds_to: float,
    ) -> list[tuple[float, float, int, float, float]]:
        start_ts = now_ts - seconds_from
        end_ts = now_ts - seconds_to
        return [
            row
            for row in rows
            if start_ts < row[0] <= end_ts
        ]

    recent60 = in_window(
        60.0,
        0.0,
    )
    recent30 = in_window(
        30.0,
        0.0,
    )
    recent10 = in_window(
        10.0,
        0.0,
    )

    if not recent60:
        return None

    def total_volume(
        subset: list[tuple[float, float, int, float, float]],
    ) -> float:
        return sum(
            max(0.0, row[1])
            for row in subset
        )

    def total_amount(
        subset: list[tuple[float, float, int, float, float]],
    ) -> float:
        return sum(
            max(0.0, row[4])
            for row in subset
        )

    volume60 = total_volume(
        recent60
    )
    volume30 = total_volume(
        recent30
    )
    volume10 = total_volume(
        recent10
    )
    amount60 = total_amount(
        recent60
    )

    baseline_volumes = []

    for index in range(
        RADAR_BASELINE_WINDOWS
    ):
        # 第一個 baseline = 60~120 秒前。
        seconds_to = 60.0 * (
            index + 1
        )
        seconds_from = 60.0 * (
            index + 2
        )

        baseline_volumes.append(
            total_volume(
                in_window(
                    seconds_from,
                    seconds_to,
                )
            )
        )

    baseline60 = (
        sum(baseline_volumes)
        / max(
            1,
            len(baseline_volumes),
        )
    )

    # 避免除0；若過去幾分鐘真的非常安靜，突然放量會自然得到高 surge。
    denominator = max(
        1.0,
        baseline60,
    )

    surge60 = (
        volume60
        / denominator
    )

    expected10 = max(
        1.0,
        baseline60 / 6.0,
    )

    acceleration10 = (
        volume10
        / expected10
    )

    buy_volume = sum(
        max(0.0, row[1])
        for row in recent60
        if row[2] == 1
    )

    sell_volume = sum(
        max(0.0, row[1])
        for row in recent60
        if row[2] == 2
    )

    classified_volume = (
        buy_volume
        + sell_volume
    )

    buy_ratio = (
        buy_volume
        / classified_volume
        if classified_volume > 0
        else 0.0
    )

    classified_ratio = (
        classified_volume
        / volume60
        if volume60 > 0
        else 0.0
    )

    first_price = num(
        recent60[0][3]
    )
    last_price = num(
        recent60[-1][3]
    )

    price_change_60_pct = 0.0

    if (
        first_price is not None
        and first_price > 0
        and last_price is not None
    ):
        price_change_60_pct = (
            last_price
            / first_price
            - 1.0
        ) * 100.0

    first10_price = (
        num(recent10[0][3])
        if recent10
        else last_price
    )

    price_change_10_pct = 0.0

    if (
        first10_price is not None
        and first10_price > 0
        and last_price is not None
    ):
        price_change_10_pct = (
            last_price
            / first10_price
            - 1.0
        ) * 100.0

    price_vs_avg_pct = None

    if (
        day_average_price is not None
        and day_average_price > 0
        and last_price is not None
    ):
        price_vs_avg_pct = (
            last_price
            / day_average_price
            - 1.0
        ) * 100.0

    return {
        "volume_10s": round(volume10, 2),
        "volume_30s": round(volume30, 2),
        "volume_60s": round(volume60, 2),
        "amount_60s": round(amount60, 2),
        "baseline_volume_60s": round(baseline60, 2),
        "surge_60s": round(surge60, 3),
        "acceleration_10s": round(acceleration10, 3),
        "buy_volume_60s": round(buy_volume, 2),
        "sell_volume_60s": round(sell_volume, 2),
        "buy_ratio_60s": round(buy_ratio, 4),
        "classified_ratio_60s": round(classified_ratio, 4),
        "price": last_price,
        "price_change_60_pct": round(price_change_60_pct, 4),
        "price_change_10_pct": round(price_change_10_pct, 4),
        "price_vs_avg_pct": (
            round(price_vs_avg_pct, 4)
            if price_vs_avg_pct is not None
            else None
        ),
        "tick_count_60s": len(recent60),
        "history_seconds": round(history_seconds, 1),
    }


def score_volume_surge(
    metrics: dict,
) -> float:
    surge = float(
        metrics.get("surge_60s")
        or 0.0
    )
    accel = float(
        metrics.get("acceleration_10s")
        or 0.0
    )
    buy_ratio = float(
        metrics.get("buy_ratio_60s")
        or 0.0
    )
    momentum = float(
        metrics.get("price_change_60_pct")
        or 0.0
    )
    amount = float(
        metrics.get("amount_60s")
        or 0.0
    )

    surge_score = clamp(
        (surge - 1.0)
        / 4.0
        * 100.0,
        0.0,
        100.0,
    )

    accel_score = clamp(
        (accel - 1.0)
        / 4.0
        * 100.0,
        0.0,
        100.0,
    )

    buy_score = clamp(
        (buy_ratio - 0.50)
        / 0.30
        * 100.0,
        0.0,
        100.0,
    )

    momentum_score = clamp(
        momentum
        / 1.5
        * 100.0,
        0.0,
        100.0,
    )

    # 3百萬~6千萬/分鐘粗略映射 0~100。
    amount_score = clamp(
        (
            math.log10(
                max(
                    1.0,
                    amount
                    / 3_000_000.0,
                )
            )
            / math.log10(20.0)
            * 100.0
        ),
        0.0,
        100.0,
    )

    return round(
        surge_score * 0.35
        + accel_score * 0.15
        + buy_score * 0.25
        + momentum_score * 0.15
        + amount_score * 0.10,
        2,
    )


def qualifies_volume_surge(
    metrics: dict,
) -> bool:
    return bool(
        float(metrics.get("volume_60s") or 0.0)
        >= RADAR_MIN_60S_VOLUME
        and float(metrics.get("amount_60s") or 0.0)
        >= RADAR_MIN_60S_AMOUNT
        and float(metrics.get("surge_60s") or 0.0)
        >= RADAR_MIN_SURGE
        and float(metrics.get("buy_ratio_60s") or 0.0)
        >= RADAR_MIN_BUY_RATIO
        and float(metrics.get("classified_ratio_60s") or 0.0)
        >= RADAR_MIN_CLASSIFIED_RATIO
        and float(metrics.get("price_change_60_pct") or 0.0)
        >= RADAR_MIN_PRICE_CHANGE_60_PCT
    )


# =========================================================
# Main engine
# =========================================================

class IntradayLiveEngine:

    def __init__(self) -> None:
        if not SJ_API_KEY:
            raise RuntimeError(
                "缺少 SJ_API_KEY"
            )

        if not SJ_SECRET_KEY:
            raise RuntimeError(
                "缺少 SJ_SECRET_KEY"
            )

        self.store = FirebaseStore()

        self.manager = (
            build_position_manager()
        )

        self.api = sj.Shioaji()

        self.bars = LiveBarBook()

        self.market_level = "YELLOW"
        self.premarket_brief: dict = {}

        self.candidates: dict[
            str,
            dict,
        ] = {}

        self.contracts: dict[
            str,
            Any,
        ] = {}

        self.last_prices: dict[
            str,
            float,
        ] = {}

        self.last_firebase_write: dict[
            str,
            float,
        ] = defaultdict(
            lambda: 0.0
        )

        self.last_strategy_key: dict[
            str,
            datetime,
        ] = {}

        self.entry_symbols: set[
            str
        ] = set()

        # 瞬間爆量雷達來源池（最多170檔）與 Top30。
        self.radar_universe_symbols: set[
            str
        ] = set()

        # 保留 scanner_top_symbols 名稱，讓 ENTRY 邏輯相容；
        # V5 中它代表「瞬間爆量 Top30」，不是累積成交量排行。
        self.scanner_top_symbols: set[
            str
        ] = set()

        self.radar_ticks: dict[
            str,
            deque,
        ] = defaultdict(deque)

        self.radar_metrics: dict[
            str,
            dict,
        ] = {}

        self._last_universe_refresh = 0.0
        self._last_radar_refresh = 0.0

        # 每檔瞬間爆量 ENTRY 評估 cooldown。
        # 讓未通過策略者能在同一根 5m 內隨即時量價變化重新評估，
        # 又避免 0.5 秒主迴圈重複轟炸策略。
        self._last_instant_entry_eval: dict[str, float] = defaultdict(
            lambda: 0.0
        )

        self._cutoff_pruned = False
        self._entry_limit_logged = False

        self._warmed_symbols: set[str] = set()
        self._warm_query_count = 0

        self.running = True

        self._lock = threading.RLock()

        self._last_heartbeat = 0.0
        self._force_exit_done = False
        self.learning = Recorder()
        self.silent_symbols = set()
        # EASYSTOCK_VALIDATED_MODEL_GATE_V2
        self.daytrade_model = DaytradeModel()
        self._previous_closes = {}
        self._previous_close_retry = {}

    # -----------------------------------------------------
    # Boot
    # -----------------------------------------------------

    def login(self) -> None:
        print("[BOOT] Shioaji login...")

        self.api.login(
            api_key=SJ_API_KEY,
            secret_key=SJ_SECRET_KEY,
        )

        print("✅ Shioaji login success")

    def init_firebase(self) -> None:
        self.market_level, self.premarket_brief = (
            load_market_context()
        )

        payload = self.store.start_day(
            market_level=self.market_level
        )

        print(
            "✅ Firebase intraday_live ready "
            f"session={payload.get('session')} "
            f"market={self.market_level}"
        )

        # 寫入正式盤中掃描設定，網站 / Firebase 可直接看到來源。
        try:
            db.reference(
                "/market_data/intraday_live/config"
            ).update({
                "candidate_mode":
                    "shioaji_instant_volume_surge",
                "universe_scanners":
                    "Amount,Volume,TickCount,ChangePercent,DayRange",
                "radar_pool_size":
                    RADAR_POOL_SIZE,
                "radar_top_n":
                    RADAR_TOP_N,
                "universe_refresh_seconds":
                    UNIVERSE_REFRESH_SECONDS,
                "radar_refresh_seconds":
                    RADAR_REFRESH_SECONDS,
                "radar_min_surge":
                    RADAR_MIN_SURGE,
                "radar_min_buy_ratio":
                    RADAR_MIN_BUY_RATIO,
                "radar_min_60s_volume":
                    RADAR_MIN_60S_VOLUME,
                "radar_min_60s_amount":
                    RADAR_MIN_60S_AMOUNT,
                "radar_min_price_change_60_pct":
                    RADAR_MIN_PRICE_CHANGE_60_PCT,
                "max_daily_entries":
                    MAX_DAILY_ENTRIES,
                "entry_start":
                    "09:30",
                "entry_cutoff":
                    "12:30",
                "force_exit":
                    "12:55",
                "daytrade_end":
                    "13:00",
            })
        except Exception as exc:
            print(
                "[WARN] Firebase config update: "
                f"{type(exc).__name__}: {exc}"
            )

        # 重啟保護：
        # 已 CLOSED + 仍 OPEN 的股票全部算進「今日已 ENTRY」。
        for node_name in (
            "closed_trades",
            "open_positions",
        ):
            try:
                value = db.reference(
                    "/market_data/intraday_live/"
                    + node_name
                ).get()

                rows = []

                if isinstance(
                    value,
                    dict,
                ):
                    rows = [
                        x
                        for x in value.values()
                        if isinstance(
                            x,
                            dict,
                        )
                    ]

                elif isinstance(
                    value,
                    list,
                ):
                    rows = [
                        x
                        for x in value
                        if isinstance(
                            x,
                            dict,
                        )
                    ]

                for row in rows:
                    from daytrade_learning.daily_state import on_day
                    if not on_day(row, now_tpe().date().isoformat()):
                        continue
                    symbol = str(
                        row.get("symbol")
                        or ""
                    ).strip()

                    if symbol:
                        self.entry_symbols.add(
                            symbol
                        )
                        self.manager.traded_symbols.add(symbol)
                        if node_name == "open_positions":
                            restored = dict(row)
                            for key in ("entry_time", "last_update_at"):
                                if restored.get(key):
                                    restored[key] = as_datetime(restored[key])
                            if restored.get("entry_time") is None:
                                raise RuntimeError("Cannot restore OPEN entry time")
                            self.manager.positions[symbol] = restored

            except Exception as exc:
                raise RuntimeError("Cannot restore daily state: " + node_name) from exc

        if self.entry_symbols:
            print(
                "ℹ️ 今日已 ENTRY："
                f"{len(self.entry_symbols)}/"
                f"{MAX_DAILY_ENTRIES} "
                + ", ".join(
                    sorted(
                        self.entry_symbols
                    )
                )
            )

    def load_candidates(self) -> None:
        """
        相容方法：載入市場活動粗篩 pool。
        正式 run() 使用 refresh_universe_pool()。
        """
        rows = scan_market_activity_universe(
            self.api,
            limit=RADAR_POOL_SIZE,
        )

        self.candidates = {
            str(row["symbol"]): row
            for row in rows
        }

        self.radar_universe_symbols = set(
            self.candidates
        )

        print(
            "✅ Market activity universe: "
            f"{len(self.candidates)} stocks"
        )

    def prepare_contracts(self) -> None:
        for symbol in list(
            self.candidates
        ):
            contract = get_contract(
                self.api,
                symbol,
            )

            if contract is None:
                print(
                    f"[WARN] contract not found: "
                    f"{symbol}"
                )
                continue

            self.contracts[
                symbol
            ] = contract

        if not self.contracts:
            raise RuntimeError(
                "Shioaji 無可用股票 contract"
            )

        print(
            f"✅ Contracts ready: "
            f"{len(self.contracts)}"
        )

    def warm_start(self) -> None:
        print("[BOOT] Warm-start historical 1m Kbars...")

        for index, (
            symbol,
            contract,
        ) in enumerate(
            self.contracts.items(),
            start=1,
        ):
            try:
                count = warm_symbol(
                    api=self.api,
                    contract=contract,
                    symbol=symbol,
                    bars=self.bars,
                )

                rows5 = self.bars.rows5(
                    symbol
                )

                rows15 = self.bars.rows15(
                    symbol
                )

                print(
                    f"[WARM {index}/"
                    f"{len(self.contracts)}] "
                    f"{symbol} "
                    f"1m={count} "
                    f"5m={len(rows5)} "
                    f"15m={len(rows15)}"
                )

            except Exception as exc:
                print(
                    f"[WARN] warm {symbol}: "
                    f"{type(exc).__name__}: "
                    f"{exc}"
                )

    # -----------------------------------------------------
    # Subscribe
    # -----------------------------------------------------

    def install_callback(self) -> None:
        # 重要：全系統只註冊一個 callback，
        # 不在每檔 subscribe_stock 裡重複定義。
        self.api.on_tick_stk_v1()(
            self.on_tick
        )

    def subscribe_all(self) -> None:
        print("[BOOT] Subscribe Shioaji Tick...")

        for index, (
            symbol,
            contract,
        ) in enumerate(
            self.contracts.items(),
            start=1,
        ):
            try:
                self.api.subscribe(
                    contract,
                    quote_type=sj.QuoteType.Tick,
                )

                print(
                    f"[SUB {index}/"
                    f"{len(self.contracts)}] "
                    f"{symbol}"
                )

                time.sleep(0.05)

            except Exception as exc:
                print(
                    f"[WARN] subscribe {symbol}: "
                    f"{type(exc).__name__}: "
                    f"{exc}"
                )

        print("✅ Shioaji subscriptions requested")

    def _is_open_position(
        self,
        symbol: str,
    ) -> bool:
        position = get_position_safe(
            self.manager,
            symbol,
        )

        return bool(
            isinstance(position, dict)
            and str(
                position.get("status")
                or ""
            ).upper()
            == "OPEN"
        )

    def _subscribe_universe_symbol(
        self,
        row: dict,
    ) -> bool:
        symbol = str(
            row.get("symbol")
            or ""
        ).strip()

        if not symbol:
            return False

        with self._lock:
            if symbol in self.contracts:
                self.candidates[symbol] = row
                return True

        contract = get_contract(
            self.api,
            symbol,
        )

        if contract is None:
            print(
                f"[WARN] universe contract not found: {symbol}"
            )
            return False

        try:
            self.api.subscribe(
                contract,
                quote_type=sj.QuoteType.Tick,
            )

            with self._lock:
                self.contracts[symbol] = contract
                self.candidates[symbol] = row

            return True

        except Exception as exc:
            print(
                f"[WARN] universe subscribe {symbol}: "
                f"{type(exc).__name__}: {exc}"
            )
            return False

    def _unsubscribe_universe_symbol(
        self,
        symbol: str,
    ) -> None:
        # OPEN position 即使掉出雷達池仍保留 Tick。
        if self._is_open_position(symbol):
            return

        contract = self.contracts.get(
            symbol
        )

        if contract is not None:
            try:
                self.api.unsubscribe(
                    contract,
                    quote_type=sj.QuoteType.Tick,
                )
            except Exception:
                pass

        with self._lock:
            self.contracts.pop(symbol, None)
            self.candidates.pop(symbol, None)
            self.radar_ticks.pop(symbol, None)
            self.radar_metrics.pop(symbol, None)
            self.scanner_top_symbols.discard(symbol)

    def _write_universe_meta(
        self,
        rows: list[dict],
    ) -> None:
        try:
            preview = {}

            for row in rows[:30]:
                symbol = str(
                    row.get("symbol")
                    or ""
                )
                if not symbol:
                    continue

                preview[symbol] = {
                    "symbol": symbol,
                    "name": row.get("name"),
                    "activity_rank": row.get("activity_rank"),
                    "activity_score": row.get("activity_score"),
                    "sources": row.get("activity_sources"),
                    "total_amount": num(row.get("total_amount")),
                    "total_volume": num(row.get("total_volume")),
                    "volume_ratio": num(row.get("volume_ratio")),
                }

            db.reference(
                "/market_data/intraday_live/universe_preview"
            ).set(preview)

            db.reference(
                "/market_data/intraday_live/universe_meta"
            ).set({
                "source": "shioaji_multi_scanner",
                "pool_limit": RADAR_POOL_SIZE,
                "actual_subscriptions": len(self.contracts),
                "refresh_seconds": UNIVERSE_REFRESH_SECONDS,
                "updated_at": now_tpe().isoformat(timespec="seconds"),
            })

        except Exception as exc:
            print(
                "[WARN] universe Firebase: "
                f"{type(exc).__name__}: {exc}"
            )

    def refresh_universe_pool(
        self,
        *,
        force: bool = False,
    ) -> None:
        current = now_tpe()
        tt = current.timetz().replace(
            tzinfo=None
        )

        if not (
            dtime(9, 0)
            <= tt
            < ENTRY_CUTOFF
        ):
            return

        now_mono = time.monotonic()

        if (
            not force
            and now_mono - self._last_universe_refresh
            < UNIVERSE_REFRESH_SECONDS
        ):
            return

        self._last_universe_refresh = now_mono

        rows = scan_market_activity_universe(
            self.api,
            limit=RADAR_POOL_SIZE,
        )

        if not rows:
            print(
                "[WARN] market activity universe empty"
            )
            return

        new_map = {
            str(row["symbol"]): row
            for row in rows
        }
        new_symbols = set(new_map)
        old_symbols = set(
            self.radar_universe_symbols
        )

        # 先取消掉榜者，確保訂閱數永遠留在安全上限內。
        for symbol in sorted(
            old_symbols - new_symbols
        ):
            self._unsubscribe_universe_symbol(
                symbol
            )

        # 更新仍在 pool 的 metadata。
        with self._lock:
            for symbol in (
                new_symbols & old_symbols
            ):
                self.candidates[symbol] = new_map[symbol]

        added_count = 0

        for symbol in sorted(
            new_symbols - old_symbols
        ):
            if self._subscribe_universe_symbol(
                new_map[symbol]
            ):
                added_count += 1

            time.sleep(0.01)

        # 實際 universe 只記錄訂閱成功者。
        self.radar_universe_symbols = {
            symbol
            for symbol in new_symbols
            if symbol in self.contracts
        }

        self._write_universe_meta(
            rows
        )

        print(
            "🌐 Market universe refreshed: "
            f"{len(self.radar_universe_symbols)} subscribed "
            f"added={added_count}"
        )

        preview = " | ".join(
            f"#{row.get('activity_rank')} "
            f"{row.get('symbol')} "
            f"{row.get('activity_score')}"
            for row in rows[:5]
        )

        if preview:
            print("   " + preview)

    def record_radar_tick(
        self,
        symbol: str,
        dt: datetime,
        price: float,
        volume: float,
        tick_type: int,
        amount: float,
    ) -> None:
        ts = dt.timestamp()

        with self._lock:
            bucket = self.radar_ticks[symbol]
            bucket.append((
                ts,
                float(volume),
                int(tick_type),
                float(price),
                float(amount),
            ))

            cutoff = (
                ts - RADAR_HISTORY_SECONDS
            )

            while (
                bucket
                and bucket[0][0] < cutoff
            ):
                bucket.popleft()

    def _ensure_strategy_history(
        self,
        symbol: str,
    ) -> None:
        if (
            len(self.bars.rows5(symbol))
            >= MIN_WARM_5M_BARS
            and len(self.bars.rows15(symbol))
            >= MIN_WARM_15M_BARS
        ):
            return

        if symbol in self._warmed_symbols:
            return

        if (
            self._warm_query_count
            >= RADAR_MAX_WARM_QUERIES
        ):
            return

        contract = self.contracts.get(
            symbol
        )

        if contract is None:
            return

        self._warmed_symbols.add(symbol)
        self._warm_query_count += 1

        try:
            count = warm_symbol(
                api=self.api,
                contract=contract,
                symbol=symbol,
                bars=self.bars,
            )

            print(
                f"[WARM RADAR] {symbol} "
                f"1m={count} "
                f"query={self._warm_query_count}/"
                f"{RADAR_MAX_WARM_QUERIES}"
            )

        except Exception as exc:
            print(
                f"[WARN] warm radar {symbol}: "
                f"{type(exc).__name__}: {exc}"
            )

    def _write_radar_top30(
        self,
        rows: list[dict],
    ) -> None:
        try:
            payload = {}

            for row in rows:
                symbol = str(
                    row.get("symbol")
                    or ""
                )
                if not symbol:
                    continue

                payload[symbol] = {
                    key: row.get(key)
                    for key in (
                        "symbol",
                        "name",
                        "radar_rank",
                        "surge_score",
                        "surge_60s",
                        "acceleration_10s",
                        "volume_10s",
                        "volume_30s",
                        "volume_60s",
                        "baseline_volume_60s",
                        "amount_60s",
                        "buy_ratio_60s",
                        "classified_ratio_60s",
                        "price",
                        "price_change_10_pct",
                        "price_change_60_pct",
                        "price_vs_avg_pct",
                        "tick_count_60s",
                    )
                }
                payload[symbol][
                    "updated_at"
                ] = now_tpe().isoformat(
                    timespec="seconds"
                )

            db.reference(
                "/market_data/intraday_live/radar_top30"
            ).set(payload)

            db.reference(
                "/market_data/intraday_live/radar_meta"
            ).set({
                "mode": "instant_volume_surge",
                "top_n": RADAR_TOP_N,
                "actual_count": len(payload),
                "pool_subscriptions": len(self.radar_universe_symbols),
                "refresh_seconds": RADAR_REFRESH_SECONDS,
                "min_surge": RADAR_MIN_SURGE,
                "min_buy_ratio": RADAR_MIN_BUY_RATIO,
                "min_volume_60s": RADAR_MIN_60S_VOLUME,
                "min_amount_60s": RADAR_MIN_60S_AMOUNT,
                "updated_at": now_tpe().isoformat(timespec="seconds"),
            })

        except Exception as exc:
            print(
                "[WARN] radar Firebase: "
                f"{type(exc).__name__}: {exc}"
            )

    def refresh_volume_radar(
        self,
        *,
        force: bool = False,
    ) -> None:
        current = now_tpe()
        tt = current.timetz().replace(
            tzinfo=None
        )

        if not (
            dtime(9, 0)
            <= tt
            < ENTRY_CUTOFF
        ):
            return

        now_mono = time.monotonic()

        if (
            not force
            and now_mono - self._last_radar_refresh
            < RADAR_REFRESH_SECONDS
        ):
            return

        self._last_radar_refresh = now_mono
        now_ts = current.timestamp()
        qualified = []

        with self._lock:
            symbols = list(
                self.radar_universe_symbols
            )

            # copy buffers to keep calculation outside callback mutation.
            snapshots = {
                symbol: list(
                    self.radar_ticks.get(symbol, [])
                )
                for symbol in symbols
            }
            metadata = {
                symbol: dict(
                    self.candidates.get(symbol, {})
                )
                for symbol in symbols
            }

        for symbol in symbols:
            stock = metadata.get(
                symbol,
                {}
            )

            avg_price = num(
                stock.get("average_price")
            )

            metrics = compute_volume_surge_metrics(
                snapshots.get(symbol, []),
                now_ts,
                day_average_price=avg_price,
            )

            if metrics is None:
                continue

            self.radar_metrics[symbol] = metrics

            if not qualifies_volume_surge(
                metrics
            ):
                continue

            row = dict(stock)
            row.update(metrics)
            row["symbol"] = symbol
            row["name"] = str(
                stock.get("name")
                or symbol
            ).strip()
            row["surge_score"] = score_volume_surge(
                metrics
            )

            qualified.append(row)

        qualified.sort(
            key=lambda row: (
                row.get("surge_score")
                or 0.0,
                row.get("surge_60s")
                or 0.0,
                row.get("amount_60s")
                or 0.0,
            ),
            reverse=True,
        )

        top_rows = qualified[:RADAR_TOP_N]

        for rank, row in enumerate(
            top_rows,
            start=1,
        ):
            row["radar_rank"] = rank

        new_top = {
            str(row["symbol"])
            for row in top_rows
        }
        old_top = set(
            self.scanner_top_symbols
        )

        with self._lock:
            for row in top_rows:
                symbol = str(row["symbol"])
                # 將即時雷達欄位合併給 strategy / ENTRY reason。
                self.candidates[symbol] = row

            self.scanner_top_symbols = new_top

        # Research records all observed pool members, not only today's winners.
        for symbol in symbols:
            try:
                self.learning.sample(
                    symbol, current, snapshots.get(symbol, []),
                    self.radar_metrics.get(symbol, {}), metadata.get(symbol, {}),
                    symbol in new_top,
                    {"stop_loss_pct": self.manager.stop_loss_pct,
                     "take_profit_pct": self.manager.take_profit_pct,
                     "entry_cutoff": "12:30", "force_exit": "12:55",
                     "source_version": "vm-v5.1-research2",
                     "entry_filters": read_live_settings()},
                )
            except Exception as exc:
                print("[LEARNING] sample skipped:", type(exc).__name__)

        # 接近 ENTRY 時間後，新加入 Top30 且 K棒不足才查一次歷史 Kbars。
        if tt >= dtime(9, 25):
            for symbol in sorted(
                new_top - old_top
            ):
                self._ensure_strategy_history(
                    symbol
                )

        # 秒級 ENTRY：雷達一完成就立刻跑策略，不再等待下一根 5m K。
        # 放在 radar Firebase write 之前，避免 DB 網路延遲拖慢 LINE ENTRY。
        self.evaluate_instant_entry_candidates(
            top_rows,
            strategy_time=current,
            now_mono=now_mono,
        )

        self._write_radar_top30(
            top_rows
        )

        if new_top != old_top or force:
            print(
                "⚡ Instant-volume radar: "
                f"qualified={len(qualified)} "
                f"Top={len(top_rows)}"
            )

            preview = " | ".join(
                f"#{row.get('radar_rank')} "
                f"{row.get('symbol')} "
                f"surge={row.get('surge_60s')}x "
                f"buy={float(row.get('buy_ratio_60s') or 0)*100:.0f}% "
                f"score={row.get('surge_score')}"
                for row in top_rows[:5]
            )

            if preview:
                print("   " + preview)

    def evaluate_instant_entry_candidates(
        self,
        top_rows: list[dict],
        *,
        strategy_time: datetime,
        now_mono: float,
    ) -> None:
        """Evaluate new entries immediately after the surge radar refresh.

        The instant surge is the trigger. 5m/15m completed bars remain the
        trend/quality confirmation background. This avoids waiting until the
        next 5-minute boundary while keeping the original strategy vetoes and
        daily max-entry protection.
        """
        if not in_entry_window(strategy_time):
            return

        for row in top_rows:
            symbol = str(row.get("symbol") or "").strip()
            if not symbol:
                continue

            if self._is_open_position(symbol):
                continue

            with self._lock:
                if symbol in self.entry_symbols:
                    continue

                if len(self.entry_symbols) >= MAX_DAILY_ENTRIES:
                    return

            previous = self._last_instant_entry_eval.get(symbol, 0.0)
            if (
                now_mono - previous
                < INSTANT_ENTRY_EVAL_SECONDS
            ):
                continue

            # Reserve only the evaluation timestamp here; actual ENTRY
            # reservation remains inside evaluate_symbol().
            self._last_instant_entry_eval[symbol] = now_mono

            # A newly-entered radar symbol may not have enough historical
            # 5m/15m context yet. Warm it once before evaluation.
            self._ensure_strategy_history(symbol)

            try:
                self.evaluate_symbol(
                    symbol=symbol,
                    strategy_time=strategy_time,
                )
            except Exception as exc:
                print(
                    f"[INSTANT ENTRY ERROR] {symbol}: "
                    f"{type(exc).__name__}: {exc}"
                )

    def prune_non_open_after_cutoff(
        self,
    ) -> None:
        if self._cutoff_pruned:
            return

        self._cutoff_pruned = True

        print(
            "[TIME] 12:30 stop new ENTRY; "
            "unsubscribe non-open radar pool"
        )

        for symbol in list(
            self.contracts
        ):
            if not self._is_open_position(
                symbol
            ):
                self._unsubscribe_universe_symbol(
                    symbol
                )

        self.radar_universe_symbols.clear()
        self.scanner_top_symbols.clear()

    # -----------------------------------------------------
    # Strategy
    # -----------------------------------------------------

    def fresh_entry_quote(self, symbol, allow_lookup=False):
        """Actual previous completed close, not scanner percent aliases or contract reference."""
        current = now_tpe()
        today = current.date().isoformat()
        cached = self._previous_closes.get(symbol)
        if not cached or cached[0] != today:
            if not allow_lookup or time.monotonic() < self._previous_close_retry.get(symbol, 0):
                return None
            self._previous_close_retry[symbol] = time.monotonic() + 300
            contract = self.contracts.get(symbol)
            if contract is None:
                return None
            try:
                payload = self.api.kbars(
                    contract=contract,
                    start=(current.date()-timedelta(days=15)).isoformat(),
                    end=(current.date()-timedelta(days=1)).isoformat(),
                    timeout=10000,
                )
                rows = [r for r in kbars_to_1m(payload) if r.start.date() < current.date()]
                if not rows or rows[-1].start.time() != dtime(13, 29):
                    return None
                previous = float(rows[-1].close)
                if not math.isfinite(previous) or previous <= 0:
                    return None
                cached = (today, previous)
                self._previous_closes[symbol] = cached
            except Exception as exc:
                print("[ENTRY FILTER] previous close unavailable:", symbol, type(exc).__name__)
                return None
        current = now_tpe()
        if not in_entry_window(current):
            return None
        with self._lock:
            ticks = list(self.radar_ticks.get(symbol, []))
        valid = [t for t in ticks if 0 <= current.timestamp()-t[0] <= 30]
        if not valid:
            return None
        latest = max(valid, key=lambda t:t[0])
        price = float(latest[3])
        try:
            settings = read_live_settings()
            lo, hi, cap = (settings[k] for k in ("min_price", "max_price", "max_gain_pct"))
            if not all(math.isfinite(v) for v in (price,lo,hi,cap)) or not 0 < lo <= hi or not 0 <= cap <= 100:
                return None
            if not lo <= price <= hi or (price/cached[1]-1)*100 > cap + 1e-9:
                return None
        except Exception as exc:
            print("[ENTRY FILTER] settings unavailable:", type(exc).__name__)
            return None
        return price, current

    def evaluate_symbol(
        self,
        symbol: str,
        strategy_time: datetime,
    ) -> None:
        # 12:30 後仍可評估 OPEN position 的技術出場，
        # 但絕不開新倉。
        rows5 = self.bars.rows5(
            symbol
        )

        rows15 = self.bars.rows15(
            symbol
        )

        if (
            len(rows5)
            < MIN_WARM_5M_BARS
            or
            len(rows15)
            < MIN_WARM_15M_BARS
        ):
            print(
                f"[SKIP] {symbol} "
                f"bars不足 "
                f"5m={len(rows5)} "
                f"15m={len(rows15)}"
            )
            return

        result = evaluate_daytrade(
            rows5,
            rows15,
            stock=self.candidates.get(
                symbol
            ),
            market_level=self.market_level,
        )

        # 秒級 ENTRY 時，事件價格應優先使用最新 Tick，
        # 不要沿用上一根已完成 5m K 的 close。
        price = self.last_prices.get(
            symbol
        )

        if price is None:
            price = num(
                result.get("price")
            )

        if price is None:
            return

        score = result.get(
            "daytrade_score"
        )

        eligible = bool(
            result.get(
                "eligible"
            )
        )

        vetoes = (
            result.get("vetoes")
            or []
        )

        reasons = (
            result.get("reasons")
            or result.get(
                "daytrade_reasons"
            )
            or []
        )

        print(
            f"[STRATEGY] "
            f"{strategy_time.strftime('%H:%M:%S')} "
            f"{symbol} "
            f"price={price:.2f} "
            f"score={score} "
            f"eligible={eligible} "
            f"veto={','.join(map(str, vetoes)) or '-'}"
        )

        position = get_position_safe(
            self.manager,
            symbol,
        )

        # -------------------------------------------------
        # 已有 OPEN：技術出場檢查
        # -------------------------------------------------

        if (
            isinstance(position, dict)
            and
            str(
                position.get("status")
                or ""
            ).upper()
            == "OPEN"
        ):
            event = call_manager_strategy_result(
                manager=self.manager,
                symbol=symbol,
                result=result,
                price=price,
                dt=strategy_time,
            )

            if is_exit_event(event):
                self.handle_exit_event(
                    symbol,
                    event,
                )

            return

        # -------------------------------------------------
        # 新 ENTRY
        # -------------------------------------------------

        if not in_entry_window(
            strategy_time
        ):
            return

        if not eligible:
            return

        if symbol not in self.scanner_top_symbols:
            return
        checked = self.fresh_entry_quote(symbol, allow_lookup=True)
        if checked is None:
            return
        price, strategy_time = checked

        # EASYSTOCK_VALIDATED_MODEL_GATE_V2
        stock = self.candidates.get(symbol, {})
        previous_close = self._previous_closes.get(symbol, (None, None))[1]
        with self._lock:
            model_ticks = list(self.radar_ticks.get(symbol, []))
        feature_row = live_features(
            price=price,
            previous_close=previous_close,
            now_ts=strategy_time.timestamp(),
            ticks=model_ticks,
            radar=stock,
        ) if previous_close else None
        model_decision = self.daytrade_model.evaluate(feature_row or {})
        model_reason = None
        if model_decision.get("active") and model_decision.get("evaluated"):
            model_probability = float(model_decision["probability"])
            print(
                f"[MODEL] {symbol} p={model_probability:.3f} "
                f"threshold={float(model_decision['threshold']):.3f} "
                f"version={model_decision.get('model_version')} "
                f"approved={model_decision.get('approved')}"
            )
            if not model_decision.get("approved"):
                return
            model_reason = (
                f"量化模型 {model_probability * 100:.0f}% "
                f"({model_decision.get('model_version')})"
            )

        # 硬性限制：一天最多 5 檔。
        # 用 lock 先 reservation，避免多個 Tick callback 同時通過而超過3檔。
        reserved = False

        with self._lock:
            if symbol in self.entry_symbols:
                return

            if (
                len(
                    self.entry_symbols
                )
                >=
                MAX_DAILY_ENTRIES
            ):
                if not self._entry_limit_logged:
                    print(
                        "🛑 今日 ENTRY 已達上限 "
                        f"{MAX_DAILY_ENTRIES} 檔，"
                        "不再新增股票。"
                    )
                    self._entry_limit_logged = True

                return

            self.entry_symbols.add(
                symbol
            )

            reserved = True

        stock = self.candidates.get(
            symbol,
            {},
        )

        name = str(
            stock.get("name")
            or symbol
        )

        # 把「瞬間爆量」資訊附加到 ENTRY reasons。
        buy_pct = (
            float(
                stock.get("buy_ratio_60s")
                or 0.0
            )
            * 100.0
        )

        scanner_reason = (
            "瞬間爆量"
            f"#{stock.get('radar_rank', '--')} "
            f"60s={stock.get('surge_60s', '--')}x "
            f"主動買{buy_pct:.0f}% "
            f"60s漲幅{float(stock.get('price_change_60_pct') or 0):+.2f}%"
        )

        entry_reasons = list(
            reasons
            if isinstance(
                reasons,
                list,
            )
            else [
                str(
                    reasons
                )
            ]
        )

        entry_reasons.insert(
            0,
            scanner_reason,
        )

        if model_reason:
            entry_reasons.insert(1, model_reason)

        checked = self.fresh_entry_quote(symbol)
        if checked is None:
            with self._lock:
                self.entry_symbols.discard(symbol)
            return
        price, strategy_time = checked
        try:
            event = self.manager.open_position(
                symbol=symbol,
                name=name,
                price=price,
                entry_time=strategy_time,
                score=score,
                reasons=entry_reasons,
                vwap=result.get("vwap"),
            )

        except Exception as exc:
            if reserved:
                with self._lock:
                    self.entry_symbols.discard(
                        symbol
                    )

            print(
                f"[ERROR] open_position "
                f"{symbol}: "
                f"{type(exc).__name__}: {exc}"
            )
            return

        if event is None:
            if reserved:
                with self._lock:
                    self.entry_symbols.discard(
                        symbol
                    )
            return

        self.learning.entry(event)

        # ==========================
        # 雙軌架構：前台與實盤門檻檢核
        # ==========================
        def _check_live_gate(sym, pr):
            try:
                st = read_live_settings()
                lo, hi, cap = (st[k] for k in ("min_price", "max_price", "max_gain_pct"))
                prev_c = self._previous_closes.get(sym, (None, None))[1]
                gain_pct = ((pr / prev_c - 1) * 100) if prev_c else 0.0
                if pr < lo:
                    return False, f"股價 {pr:.2f} 元低於最低門檻 ({lo:g} 元)"
                if pr > hi:
                    return False, f"股價 {pr:.2f} 元高於最高門檻 ({hi:g} 元)"
                if gain_pct > cap + 1e-9:
                    return False, f"即時漲幅 {gain_pct:.1f}% 超過上限 ({cap:g}%)"
                return True, "符合條件"
            except Exception as _ge:
                return True, f"檢核例外放行: {_ge}"

        passed_gate, gate_reason = _check_live_gate(symbol, price)
        if not passed_gate:
            with self._lock:
                self.silent_symbols.add(symbol)
            try:
                from easystock_admin.store import log_paper_trade_event
                log_paper_trade_event(symbol, name, price, "略過", f"[後台條件限制] {gate_reason}")
            except Exception as _log_e:
                pass
            print(f"ℹ️ [GATE 略過] {symbol} {name} {price:.2f} 僅供 AI 學習復盤，不推播/不模擬下單：{gate_reason}")
            return

        try:
            self.store.write_entry(
                event
            )

        except Exception as exc:
            print(
                f"[ERROR] Firebase ENTRY "
                f"{symbol}: "
                f"{type(exc).__name__}: {exc}"
            )

        # ==========================
        # Paper Trade Game ENTRY
        # ==========================
        try:
            register_signal(
                symbol=symbol,
                name=name,
                price=price,
                trade_id=str(
                    event.get("trade_id", "")
                ),
            )
            try:
                paper_wallet.try_buy(symbol=symbol, name=name, price=price)
            except Exception as _p_err:
                print(f"[PaperWallet Error] ENTRY: {_p_err}")

        except Exception as exc:
            print(
                f"[ERROR] PAPER GAME ENTRY "
                f"{symbol}: "
                f"{type(exc).__name__}: {exc}"
            )


        push_line_text(
            format_entry_message(
                event,
                self.market_level,
            ),
            entry_check=lambda: self.fresh_entry_quote(symbol) is not None,
            event=event,
        )

        print(
            f"✅ ENTRY {symbol} "
            f"{price:.2f} "
            f"score={score} "
            f"daily={len(self.entry_symbols)}/"
            f"{MAX_DAILY_ENTRIES}"
        )

    # -----------------------------------------------------
    # Tick position management
    # -----------------------------------------------------

    def handle_exit_event(
        self,
        symbol: str,
        event: dict,
    ) -> None:
        self.learning.exit(event)

        if symbol in self.silent_symbols:
            with self._lock:
                self.silent_symbols.discard(symbol)
            print(f"ℹ️ [GATE 靜音平倉] {symbol} 已完成 AI 復盤記錄，略過實盤平倉推播")
            return

        try:
            self.store.write_exit(
                event
            )

        except Exception as exc:
            print(
                f"[ERROR] Firebase EXIT "
                f"{symbol}: "
                f"{type(exc).__name__}: {exc}"
            )

        # ==========================
        # Paper Trade Game EXIT
        # ==========================
        try:
            exit_price = float(
                event.get(
                    "exit_price",
                    0
                )
            )

            trade = (
                event.get("trade")
                if isinstance(
                    event.get("trade"),
                    dict
                )
                else {}
            )

            reason = str(
                trade.get(
                    "exit_reason",
                    ""
                )
                or event.get(
                    "exit_reason",
                    ""
                )
                or ""
            )

            if exit_price > 0:
                close_signal(
                    symbol=symbol,
                    exit_price=exit_price,
                    reason=reason,
                )
                try:
                    paper_wallet.close_and_settle(symbol=symbol, exit_price=exit_price, exit_reason=reason)
                except Exception as _p_err:
                    print(f"[PaperWallet Error] EXIT: {_p_err}")

        except Exception as exc:
            print(
                f"[ERROR] PAPER GAME EXIT "
                f"{symbol}: "
                f"{type(exc).__name__}: {exc}"
            )


        push_line_text(
            format_exit_message(
                event
            ),
            event=event,
        )

        print(
            f"✅ EXIT {symbol}"
        )

    def local_tick_exit_fallback(
        self,
        symbol: str,
        price: float,
        tick_time: datetime,
    ) -> dict | None:
        """
        若現有 position_manager.py 的 on_tick 介面不同或不回傳 event，
        這裡只做安全 fallback：
        fixed stop / take profit / trailing / force exit。

        正常情況優先使用 manager.on_tick。
        """
        position = get_position_safe(
            self.manager,
            symbol,
        )

        if not isinstance(
            position,
            dict,
        ):
            return None

        if str(
            position.get("status")
            or ""
        ).upper() != "OPEN":
            return None

        entry = num(
            position.get("entry_price")
        )

        if entry is None or entry <= 0:
            return None

        highest = num(
            position.get("highest_price")
        )

        highest = max(
            highest or entry,
            price,
        )

        # 儘量讓 dashboard 看得到最新最高價。
        position[
            "current_price"
        ] = price

        position[
            "highest_price"
        ] = highest

        fixed_stop = num(
            position.get("stop_price")
        )

        if fixed_stop is None:
            fixed_stop = (
                entry
                *
                (
                    1
                    -
                    STOP_LOSS_PCT
                )
            )
            position[
                "stop_price"
            ] = fixed_stop

        take_profit = num(
            position.get(
                "take_profit_price"
            )
            or position.get(
                "take_profit"
            )
        )

        if take_profit is None:
            take_profit = (
                entry
                *
                (
                    1
                    +
                    TAKE_PROFIT_PCT
                )
            )
            position[
                "take_profit_price"
            ] = take_profit

        trailing_stop = num(
            position.get(
                "trailing_stop"
            )
        )

        gain_pct = (
            highest
            /
            entry
            -
            1
        )

        if gain_pct >= TRAILING_ACTIVATE_PCT:
            candidate_trail = (
                highest
                *
                (
                    1
                    -
                    TRAILING_PULLBACK_PCT
                )
            )

            if (
                trailing_stop is None
                or candidate_trail
                > trailing_stop
            ):
                trailing_stop = (
                    candidate_trail
                )
                position[
                    "trailing_stop"
                ] = trailing_stop

        reason = None

        if has_force_exit_started(
            tick_time
        ):
            reason = "12:55 強制出場"

        elif price <= fixed_stop:
            reason = "固定停損"

        elif price >= take_profit:
            reason = "固定停利"

        elif (
            trailing_stop is not None
            and
            price <= trailing_stop
        ):
            reason = "移動停利"

        if reason is None:
            return None

        try:
            return self.manager.close_position(
                symbol=symbol,
                exit_price=price,
                exit_time=tick_time,
                reason=reason,
            )

        except Exception as exc:
            print(
                f"[ERROR] fallback close "
                f"{symbol}: "
                f"{type(exc).__name__}: {exc}"
            )
            return None

    def update_open_to_firebase(
        self,
        symbol: str,
    ) -> None:
        now_mono = time.monotonic()

        if (
            now_mono
            -
            self.last_firebase_write[
                symbol
            ]
            <
            FIREBASE_PRICE_UPDATE_SECONDS
        ):
            return

        position = get_position_safe(
            self.manager,
            symbol,
        )

        if not isinstance(
            position,
            dict,
        ):
            return

        if str(
            position.get("status")
            or ""
        ).upper() != "OPEN":
            return

        try:
            self.store.update_position(
                position
            )

            self.last_firebase_write[
                symbol
            ] = now_mono

        except Exception as exc:
            print(
                f"[WARN] Firebase OPEN update "
                f"{symbol}: "
                f"{type(exc).__name__}: {exc}"
            )

    # -----------------------------------------------------
    # Shioaji callback
    # -----------------------------------------------------

    def on_tick(
        self,
        tick: Any,
    ) -> None:
        if not self.running:
            return

        try:
            symbol = tick_symbol(
                tick
            )

            if (
                not symbol
                or symbol
                not in self.contracts
            ):
                return

            price = tick_price(
                tick
            )

            if (
                price is None
                or price <= 0
            ):
                return

            volume = tick_volume(
                tick
            )

            dt = tick_datetime(
                tick
            )

            current_tick_type = tick_type_value(
                tick
            )

            current_amount = tick_amount(
                tick,
                price=price,
                volume=volume,
            )

            # ---------------------------------------------
            # Public realtime feed
            # ---------------------------------------------
            try:
                contract = self.contracts.get(symbol)

                write_public_tick(
                    symbol=symbol,
                    name=(
                        getattr(contract, "name", None)
                        or symbol
                    ),
                    price=price,
                    volume=volume,
                )
            except Exception as exc:
                print(
                    f"[PUBLIC FEED ERROR] "
                    f"{symbol}: {exc}"
                )

            self.record_radar_tick(
                symbol=symbol,
                dt=dt,
                price=price,
                volume=volume,
                tick_type=current_tick_type,
                amount=current_amount,
            )

            self.last_prices[
                symbol
            ] = price

            # ---------------------------------------------
            # 1) Position Tick 管理
            # ---------------------------------------------

            before = get_position_safe(
                self.manager,
                symbol,
            )

            had_open = bool(
                isinstance(
                    before,
                    dict,
                )
                and
                str(
                    before.get("status")
                    or ""
                ).upper()
                == "OPEN"
            )

            event = call_manager_on_tick(
                manager=self.manager,
                symbol=symbol,
                price=price,
                tick_time=dt,
            )

            if is_exit_event(
                event
            ):
                self.handle_exit_event(
                    symbol,
                    event,
                )

            elif had_open:
                # 若 manager.on_tick 沒回 exit event，
                # 再做安全 fallback。
                after = get_position_safe(
                    self.manager,
                    symbol,
                )

                still_open = bool(
                    isinstance(
                        after,
                        dict,
                    )
                    and
                    str(
                        after.get("status")
                        or ""
                    ).upper()
                    == "OPEN"
                )

                if still_open:
                    fallback_event = (
                        self.local_tick_exit_fallback(
                            symbol=symbol,
                            price=price,
                            tick_time=dt,
                        )
                    )

                    if is_exit_event(
                        fallback_event
                    ):
                        self.handle_exit_event(
                            symbol,
                            fallback_event,
                        )

            self.update_open_to_firebase(
                symbol
            )

            # ---------------------------------------------
            # 2) K棒
            # ---------------------------------------------

            completed_5m, key = (
                self.bars.on_tick(
                    symbol=symbol,
                    price=price,
                    volume=volume,
                    tick_time=dt,
                )
            )

            if (
                completed_5m
                and key is not None
            ):
                previous = (
                    self.last_strategy_key
                    .get(symbol)
                )

                if previous != key:
                    self.last_strategy_key[
                        symbol
                    ] = key

                    # 只對 OPEN position 或「瞬間爆量 Top30」跑策略。
                    if (
                        symbol in self.scanner_top_symbols
                        or self._is_open_position(symbol)
                    ):
                        self.evaluate_symbol(
                            symbol=symbol,
                            strategy_time=dt,
                        )

        except Exception as exc:
            # callback 絕不能因單一 tick 例外整個死掉。
            print(
                f"[TICK ERROR] "
                f"{type(exc).__name__}: "
                f"{exc}"
            )

    # -----------------------------------------------------
    # Force exit
    # -----------------------------------------------------

    def force_exit_all(
        self,
        reason: str = "12:55 強制出場",
    ) -> None:
        if self._force_exit_done:
            return

        self._force_exit_done = True

        for symbol in self.contracts:
            position = get_position_safe(
                self.manager,
                symbol,
            )

            if not isinstance(
                position,
                dict,
            ):
                continue

            if str(
                position.get("status")
                or ""
            ).upper() != "OPEN":
                continue

            price = (
                self.last_prices.get(
                    symbol
                )
                or num(
                    position.get(
                        "current_price"
                    )
                )
                or num(
                    position.get(
                        "entry_price"
                    )
                )
            )

            if price is None:
                print(
                    f"[WARN] force exit "
                    f"{symbol}: no price"
                )
                continue

            try:
                event = (
                    self.manager.close_position(
                        symbol=symbol,
                        exit_price=price,
                        exit_time=now_tpe(),
                        reason=reason,
                    )
                )

                if is_exit_event(
                    event
                ):
                    self.handle_exit_event(
                        symbol,
                        event,
                    )

            except Exception as exc:
                print(
                    f"[ERROR] force exit "
                    f"{symbol}: "
                    f"{type(exc).__name__}: "
                    f"{exc}"
                )

    # -----------------------------------------------------
    # Main loop / shutdown
    # -----------------------------------------------------

    def heartbeat_if_due(
        self,
    ) -> None:
        now_mono = time.monotonic()

        if (
            now_mono
            -
            self._last_heartbeat
            <
            HEARTBEAT_SECONDS
        ):
            return

        firebase_heartbeat(
            self.store,
            self.market_level,
        )

        self._last_heartbeat = (
            now_mono
        )

    def shutdown(
        self,
        reason: str,
    ) -> None:
        if not self.running:
            return

        print(
            f"[SHUTDOWN] {reason}"
        )

        self.running = False

        # 若在 12:55 後 shutdown，保證不留 OPEN。
        if has_force_exit_started():
            self.force_exit_all(
                reason=(
                    "系統結束前強制出場"
                )
            )

        # 最後 heartbeat
        firebase_heartbeat(
            self.store,
            self.market_level,
        )

        # unsubscribe
        for (
            symbol,
            contract,
        ) in self.contracts.items():
            try:
                self.api.unsubscribe(
                    contract,
                    quote_type=sj.QuoteType.Tick,
                )
            except Exception:
                pass

        try:
            self.api.logout()
        except Exception:
            pass

        self.learning.close()
        print("✅ Intraday Live stopped")

    def run(self) -> None:
        print("======================================")
        print("Easystock Shioaji Intraday Live V5")
        print("Instant Volume Surge Radar / Max 3")
        print("======================================")
        print(
            "UNIVERSE 09:00~12:30 | "
            "ENTRY 09:30 | "
            "CUTOFF 12:30 | "
            "FORCE EXIT 12:55 | "
            "END 13:00"
        )
        print(
            "All-market scanners → "
            f"Tick pool {RADAR_POOL_SIZE} → "
            f"Instant surge Top {RADAR_TOP_N}"
        )
        print(
            "Radar: 10s/30s/60s volume + "
            "60s baseline + tick_type buy pressure"
        )
        print(
            "Daily ENTRY hard limit: "
            f"{MAX_DAILY_ENTRIES}"
        )
        print()

        if daytrade_closed():
            print(
                "目前已超過 13:00，"
                "今天不啟動新當沖行情。"
            )

            self.learning.close()
            return

        self.init_firebase()
        self.login()
        self.install_callback()
        # Re-subscribe restored OPEN symbols even after the 12:30 scanner cutoff.
        for symbol, position in list(self.manager.positions.items()):
            if not self._subscribe_universe_symbol({"symbol": symbol, "name": position.get("name", symbol)}):
                raise RuntimeError("Cannot subscribe restored OPEN position")

        current = now_tpe()
        current_t = current.timetz().replace(
            tzinfo=None
        )

        if (
            dtime(9, 0)
            <= current_t
            < ENTRY_CUTOFF
        ):
            self.refresh_universe_pool(
                force=True
            )
        else:
            print(
                "⏳ 等待 09:00 開盤後建立 "
                "市場活動 Tick pool..."
            )

        print()
        print("✅ 行情雷達運行中...")
        print(
            f"市場燈號：{self.market_level}"
        )
        print(
            "Universe 更新："
            f"{UNIVERSE_REFRESH_SECONDS:.0f}s"
        )
        print(
            "瞬間爆量雷達更新："
            f"{RADAR_REFRESH_SECONDS:.0f}s"
        )
        print(
            "瞬間 ENTRY 評估："
            f"{INSTANT_ENTRY_EVAL_SECONDS:.0f}s"
        )
        print(
            "條件："
            f"surge≥{RADAR_MIN_SURGE:.2f}x / "
            f"主動買≥{RADAR_MIN_BUY_RATIO*100:.0f}% / "
            f"60s量≥{RADAR_MIN_60S_VOLUME:.0f} / "
            f"60s額≥{RADAR_MIN_60S_AMOUNT:,.0f}"
        )

        try:
            while self.running:
                current = now_tpe()
                tt = current.timetz().replace(
                    tzinfo=None
                )

                self.heartbeat_if_due()

                if (
                    dtime(9, 0)
                    <= tt
                    < ENTRY_CUTOFF
                ):
                    self.refresh_universe_pool()
                    self.refresh_volume_radar()

                if (
                    tt >= ENTRY_CUTOFF
                    and not self._cutoff_pruned
                ):
                    self.prune_non_open_after_cutoff()

                if (
                    has_force_exit_started(current)
                    and not self._force_exit_done
                ):
                    print(
                        "[TIME] 12:55 force exit all"
                    )
                    self.force_exit_all()

                if daytrade_closed(current):
                    print(
                        "[TIME] 13:00 daytrade closed"
                    )
                    break

                time.sleep(
                    LOOP_SLEEP_SECONDS
                )

        finally:
            self.shutdown(
                "normal end"
            )


# =========================================================
# Process signals
# =========================================================

_ENGINE: IntradayLiveEngine | None = None


def _signal_handler(
    signum: int,
    frame: Any,
) -> None:
    del frame

    global _ENGINE

    if _ENGINE is not None:
        _ENGINE.shutdown(
            f"signal {signum}"
        )

    raise SystemExit(0)


signal.signal(
    signal.SIGINT,
    _signal_handler,
)

signal.signal(
    signal.SIGTERM,
    _signal_handler,
)


# =========================================================
# Entry
# =========================================================

def main() -> None:
    global _ENGINE

    # 開盤日自動檢核（排除週末、國定假日與台北市颱風停班）
    try:
        from market_calendar import is_market_open
        is_open, reason, _ = is_market_open()
        if not is_open and os.environ.get("FORCE_INTRADAY_LIVE", "0") != "1":
            print(f"🛑 [MARKET CLOSED] 今日台股未開盤 ({reason})，當沖即時引擎不啟動。")
            return
    except Exception as _cal_err:
        print(f"⚠️ [CALENDAR WARN] 開盤日檢查例外: {_cal_err}，以預設排程繼續。")

    engine = IntradayLiveEngine()
    _ENGINE = engine

    engine.run()


if __name__ == "__main__":
    main()
