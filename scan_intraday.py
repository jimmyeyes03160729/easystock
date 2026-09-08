#!/usr/bin/env python3
"""
Easystock / Mohren Quant Matrix
Legacy Fugle Overnight Scanner

新版架構：

1. 當沖 DAYTRADE
   Oracle VM + Sinotrade Shioaji
   Firebase:
       /market_data/intraday_live

2. 隔日衝 OVERNIGHT
   GitHub Actions + Fugle
   Firebase:
       /market_data/intraday_picks

這支程式不再負責正式當沖。

安全原則：
- 不輸出 API key
- 不寫入 LINE token
- 不覆蓋 intraday_live
- daytrade 固定為 []
"""

from __future__ import annotations

import json
import math
import os
import statistics
import time

from datetime import (
    datetime,
    timedelta,
    timezone,
)

from typing import Any

import firebase_admin

from firebase_admin import (
    credentials,
    db,
)

import requests


# =========================================================
# 基本設定
# =========================================================

MODEL_VERSION = "2.0-overnight-only"

TPE = timezone(
    timedelta(hours=8)
)


# =========================================================
# Firebase
# =========================================================

FIREBASE_DATABASE_URL = (
    os.environ.get(
        "FIREBASE_DATABASE_URL",
        ""
    )
    .strip()
    .rstrip("/")
)


FIREBASE_SERVICE_ACCOUNT_JSON = (
    os.environ.get(
        "FIREBASE_SERVICE_ACCOUNT_JSON",
        ""
    )
    .strip()
)


FIREBASE_SERVICE_ACCOUNT_FILE = (
    os.environ.get(
        "FIREBASE_SERVICE_ACCOUNT_FILE",
        ""
    )
    .strip()
)


FIREBASE_ROOT_PATH = (
    os.environ.get(
        "FIREBASE_ROOT_PATH",
        "market_data"
    )
    .strip("/")
    or "market_data"
)


# =========================================================
# Fugle
# =========================================================

FUGLE_API_KEY = (
    os.environ.get(
        "FUGLE_API_KEY",
        ""
    )
    .strip()
)


FUGLE_BASE = (
    "https://api.fugle.tw/"
    "marketdata/v1.0/stock"
)


HTTP_TIMEOUT = float(
    os.environ.get(
        "HTTP_TIMEOUT",
        "12"
    )
)


MIN_INTERVAL = max(
    0.0,
    float(
        os.environ.get(
            "FUGLE_MIN_INTERVAL_SECONDS",
            "1.10"
        )
    )
)


# =========================================================
# Scanner
# =========================================================

SCAN_MAX_SYMBOLS = max(
    5,
    int(
        os.environ.get(
            "INTRADAY_SCAN_MAX_SYMBOLS",
            "30"
        )
    )
)


TOP_N = max(
    1,
    int(
        os.environ.get(
            "INTRADAY_TOP_N",
            "3"
        )
    )
)


MIN_DAYTRADE_SCORE = int(
    os.environ.get(
        "INTRADAY_MIN_DAYTRADE_SCORE",
        "76"
    )
)


MIN_OVERNIGHT_SCORE = int(
    os.environ.get(
        "INTRADAY_MIN_OVERNIGHT_SCORE",
        "74"
    )
)


# =========================================================
# 模組開關
# =========================================================

# 正式架構預設永遠關閉舊 Fugle 當沖
ENABLE_DAYTRADE = (
    os.environ.get(
        "INTRADAY_ENABLE_DAYTRADE",
        "0"
    )
    .strip()
    .lower()
    in {
        "1",
        "true",
        "yes",
        "on",
    }
)


ENABLE_OVERNIGHT = (
    os.environ.get(
        "INTRADAY_ENABLE_OVERNIGHT",
        "1"
    )
    .strip()
    .lower()
    in {
        "1",
        "true",
        "yes",
        "on",
    }
)


# =========================================================
# HTTP Session
# =========================================================

_last_call = 0.0


session = requests.Session()

session.headers.update({
    "User-Agent":
        "MohrenQuant/2.0",

    "Accept":
        "application/json",
})


# =========================================================
# Helpers
# =========================================================

def num(
    value: Any
) -> float | None:

    try:

        if (
            value is None
            or value == ""
        ):
            return None

        result = float(
            value
        )

        if not math.isfinite(
            result
        ):
            return None

        return result

    except (
        TypeError,
        ValueError,
    ):

        return None


def clamp(
    value: float,
    low: float = 0.0,
    high: float = 1.0,
) -> float:

    return max(
        low,
        min(
            high,
            value
        )
    )


def sma(
    values: list[float],
    period: int,
) -> float | None:

    if len(values) < period:
        return None

    return (
        sum(
            values[-period:]
        )
        /
        period
    )


def pct_rank_from_hot_rank(
    rank: Any,
    universe: int = 500,
) -> float:

    value = num(
        rank
    )

    if value is None:
        return 0.5

    return clamp(
        1.0
        -
        (
            value - 1
        )
        /
        max(
            1,
            universe - 1
        )
    )


# =========================================================
# Fugle Rate Limit
# =========================================================

def wait_rate_limit() -> None:

    global _last_call

    elapsed = (
        time.monotonic()
        -
        _last_call
    )

    if elapsed < MIN_INTERVAL:

        time.sleep(
            MIN_INTERVAL
            -
            elapsed
        )

    _last_call = (
        time.monotonic()
    )


# =========================================================
# Fugle 5M
# =========================================================

def fugle_5m(
    symbol: str
) -> list[dict]:

    wait_rate_limit()

    url = (
        f"{FUGLE_BASE}/"
        f"intraday/candles/"
        f"{symbol}"
    )


    response = session.get(
        url,

        params={
            "timeframe": "5",
            "sort": "asc",
        },

        headers={
            "X-API-KEY":
                FUGLE_API_KEY,
        },

        timeout=HTTP_TIMEOUT,
    )


    if response.status_code == 404:
        return []


    # API rate limit retry
    if response.status_code == 429:

        sleep_seconds = max(
            3.0,
            MIN_INTERVAL * 3
        )

        print(
            f"[rate-limit] "
            f"{symbol} "
            f"sleep={sleep_seconds:.1f}s"
        )

        time.sleep(
            sleep_seconds
        )

        wait_rate_limit()

        response = session.get(
            url,

            params={
                "timeframe": "5",
                "sort": "asc",
            },

            headers={
                "X-API-KEY":
                    FUGLE_API_KEY,
            },

            timeout=HTTP_TIMEOUT,
        )


    response.raise_for_status()


    payload = (
        response.json()
        or {}
    )


    rows = (
        payload.get("data")
        or []
    )


    clean: list[dict] = []


    for row in rows:

        o = num(
            row.get("open")
        )

        h = num(
            row.get("high")
        )

        l = num(
            row.get("low")
        )

        c = num(
            row.get("close")
        )

        v = num(
            row.get("volume")
        )


        if (
            o is None
            or h is None
            or l is None
            or c is None
            or v is None
        ):

            continue


        clean.append({

            "date":
                row.get("date"),

            "open":
                o,

            "high":
                h,

            "low":
                l,

            "close":
                c,

            "volume":
                max(
                    0.0,
                    v
                ),

            "average":
                num(
                    row.get(
                        "average"
                    )
                ),

        })


    return clean


# =========================================================
# 5M -> 15M
# =========================================================

def aggregate_15m(
    rows: list[dict]
) -> list[dict]:

    output: list[dict] = []


    for index in range(
        0,
        len(rows),
        3
    ):

        chunk = rows[
            index:index + 3
        ]


        if len(chunk) < 3:
            continue


        output.append({

            "date":
                chunk[-1]["date"],

            "open":
                chunk[0]["open"],

            "high":
                max(
                    bar["high"]
                    for bar
                    in chunk
                ),

            "low":
                min(
                    bar["low"]
                    for bar
                    in chunk
                ),

            "close":
                chunk[-1]["close"],

            "volume":
                sum(
                    bar["volume"]
                    for bar
                    in chunk
                ),

        })


    return output


# =========================================================
# K-Bar Helpers
# =========================================================

def bar_position(
    bar: dict
) -> float:

    span = (
        bar["high"]
        -
        bar["low"]
    )

    if span <= 0:
        return 0.5

    return clamp(
        (
            bar["close"]
            -
            bar["low"]
        )
        /
        span
    )


def upper_wick_ratio(
    bar: dict
) -> float:

    span = (
        bar["high"]
        -
        bar["low"]
    )

    if span <= 0:
        return 0.0

    body_top = max(
        bar["open"],
        bar["close"]
    )

    return clamp(
        (
            bar["high"]
            -
            body_top
        )
        /
        span
    )


# =========================================================
# Trend
# =========================================================

def trend_score(
    rows: list[dict]
) -> tuple[
    float,
    list[str],
]:

    if len(rows) < 2:
        return (
            0.0,
            []
        )


    closes = [
        row["close"]
        for row
        in rows
    ]


    short_ma = sma(
        closes,
        3
    )

    slow_ma = sma(
        closes,
        6
    )


    last_close = (
        closes[-1]
    )


    recent = rows[
        -min(
            4,
            len(rows)
        ):
    ]


    comparisons = max(
        1,
        len(recent) - 1
    )


    higher_lows = 0
    higher_highs = 0


    for i in range(
        1,
        len(recent)
    ):

        if (
            recent[i]["low"]
            >=
            recent[
                i - 1
            ]["low"]
        ):

            higher_lows += 1


        if (
            recent[i]["high"]
            >=
            recent[
                i - 1
            ]["high"]
        ):

            higher_highs += 1


    score = 0.0

    reasons: list[str] = []


    if (
        short_ma is not None
        and slow_ma is not None
        and
        last_close
        >
        short_ma
        >
        slow_ma
    ):

        score += 0.55

        reasons.append(
            "短均線多頭"
        )


    elif (
        short_ma is not None
        and
        last_close
        >
        short_ma
    ):

        score += 0.35


    elif (
        closes
        and
        last_close
        >
        closes[0]
    ):

        score += 0.25


    score += (
        0.225
        *
        (
            higher_lows
            /
            comparisons
        )
    )


    score += (
        0.225
        *
        (
            higher_highs
            /
            comparisons
        )
    )


    if (
        higher_lows
        >=
        max(
            1,
            comparisons - 1
        )
        and
        higher_highs
        >=
        max(
            1,
            comparisons - 1
        )
    ):

        reasons.append(
            "高低點墊高"
        )


    return (
        clamp(score),
        reasons
    )


# =========================================================
# VWAP
# =========================================================

def vwap_proxy(
    rows: list[dict]
) -> float | None:

    if not rows:
        return None


    # Fugle 有 average 時優先使用
    last_average = num(
        rows[-1].get(
            "average"
        )
    )


    if (
        last_average is not None
        and last_average > 0
    ):

        return last_average


    total_volume = sum(
        row["volume"]
        for row
        in rows
    )


    if total_volume <= 0:
        return None


    total_value = 0.0


    for row in rows:

        typical_price = (
            row["high"]
            +
            row["low"]
            +
            row["close"]
        ) / 3


        total_value += (
            typical_price
            *
            row["volume"]
        )


    return (
        total_value
        /
        total_volume
    )


# =========================================================
# Volume
# =========================================================

def volume_score(
    rows: list[dict]
) -> tuple[
    float,
    float | None,
]:

    if len(rows) < 10:

        return (
            0.4,
            None
        )


    recent = [
        row["volume"]
        for row
        in rows[-3:]
    ]


    base = [
        row["volume"]
        for row
        in rows[-12:-3]
        if row["volume"] > 0
    ]


    if not base:

        return (
            0.4,
            None
        )


    recent_avg = (
        sum(recent)
        /
        len(recent)
    )


    base_avg = (
        sum(base)
        /
        len(base)
    )


    if base_avg <= 0:

        return (
            0.4,
            None
        )


    ratio = (
        recent_avg
        /
        base_avg
    )


    score = clamp(
        (
            ratio - 0.7
        )
        /
        1.8
    )


    return (
        score,
        ratio
    )


# =========================================================
# Historical Edge
# =========================================================

def historical_edge_score(
    stock: dict
) -> float:

    backtest = (
        stock.get(
            "backtest"
        )
        or {}
    )


    proxy = (
        backtest.get(
            "daytrade_proxy"
        )
        or {}
    )


    profit_factor = num(
        proxy.get(
            "profit_factor"
        )
    )


    avg_return = num(
        proxy.get(
            "avg_return"
        )
    )


    samples = (
        num(
            proxy.get(
                "signals"
            )
        )
        or 0
    )


    edge = 0.45


    if samples >= 20:

        pf_score = clamp(
            (
                (
                    profit_factor
                    or 1.0
                )
                -
                0.8
            )
            /
            0.8
        )


        return_score = clamp(
            (
                (
                    avg_return
                    or 0.0
                )
                +
                0.005
            )
            /
            0.02
        )


        edge = clamp(
            0.35
            +
            pf_score * 0.35
            +
            return_score * 0.30
        )


    return edge


# =========================================================
# Overnight Feature Engine
# =========================================================

def overnight_features(
    rows5: list[dict],
    rows15: list[dict],
    stock: dict,
    market_level_name: str,
) -> dict:

    if not rows5:

        raise ValueError(
            "rows5 is empty"
        )


    last = rows5[-1]

    close = float(
        last["close"]
    )


    # =====================================================
    # Day position
    # =====================================================

    day_high = max(
        row["high"]
        for row
        in rows5
    )


    day_low = min(
        row["low"]
        for row
        in rows5
    )


    day_span = max(
        1e-9,
        day_high
        -
        day_low
    )


    day_position = clamp(
        (
            close
            -
            day_low
        )
        /
        day_span
    )


    # =====================================================
    # VWAP
    # =====================================================

    vwap = vwap_proxy(
        rows5
    )


    vwap_distance = (
        None
        if not vwap
        else
        close / vwap - 1
    )


    # =====================================================
    # Trends
    # =====================================================

    five_trend, _ = (
        trend_score(
            rows5
        )
    )


    fifteen_trend, _ = (
        trend_score(
            rows15
        )
    )


    # =====================================================
    # Volume
    # =====================================================

    vol_score, vol_ratio = (
        volume_score(
            rows5
        )
    )


    # =====================================================
    # Last 30 minutes
    # =====================================================

    tail = (
        rows5[-6:]
        if len(rows5) >= 6
        else rows5
    )


    if (
        tail
        and
        tail[0]["open"]
    ):

        tail_return = (
            tail[-1]["close"]
            /
            tail[0]["open"]
            -
            1
        )

    else:

        tail_return = 0.0


    tail_strength = clamp(
        (
            tail_return
            +
            0.005
        )
        /
        0.03
    )


    # =====================================================
    # Close near high
    # =====================================================

    close_high_score = clamp(
        (
            day_position
            -
            0.45
        )
        /
        0.55
    )


    # =====================================================
    # Liquidity
    # =====================================================

    amount_rank_pct = num(
        stock.get(
            "amount_rank_pct"
        )
    )


    liquidity = clamp(
        amount_rank_pct
        if amount_rank_pct is not None
        else
        pct_rank_from_hot_rank(
            stock.get(
                "hot_rank"
            )
        )
    )


    # =====================================================
    # Institution
    # =====================================================

    inst = num(
        stock.get(
            "net15Total"
        )
    )


    if inst is None:

        inst_score = 0.5

    else:

        inst_score = clamp(
            (
                inst
                +
                2_000_000
            )
            /
            4_000_000
        )


    # =====================================================
    # Daily Trend
    # =====================================================

    sma20 = num(
        stock.get(
            "sma20"
        )
    )


    sma60 = num(
        stock.get(
            "sma60"
        )
    )


    daily_uptrend = bool(
        sma20 is not None
        and
        sma60 is not None
        and
        close > sma20
        and
        close > sma60
    )


    # =====================================================
    # Historical edge
    # =====================================================

    hist_edge = (
        historical_edge_score(
            stock
        )
    )


    # =====================================================
    # Overnight score
    # =====================================================

    overnight_score = round(
        100
        *
        (
            fifteen_trend
            * 0.25

            +
            tail_strength
            * 0.20

            +
            close_high_score
            * 0.15

            +
            vol_score
            * 0.15

            +
            liquidity
            * 0.10

            +
            inst_score
            * 0.10

            +
            hist_edge
            * 0.05
        )
    )


    # =====================================================
    # Vetoes
    # =====================================================

    vetoes: list[str] = []


    if (
        vwap
        and
        close
        <
        vwap * 0.998
    ):

        vetoes.append(
            "跌破VWAP"
        )


    if (
        vwap_distance is not None
        and
        vwap_distance > 0.03
    ):

        vetoes.append(
            "距VWAP過遠"
        )


    if (
        upper_wick_ratio(
            last
        )
        >= 0.55
        and
        bar_position(
            last
        )
        < 0.65
    ):

        vetoes.append(
            "末根爆上影"
        )


    if (
        market_level_name
        == "RED"
    ):

        vetoes.append(
            "市場紅燈"
        )


    # =====================================================
    # Reasons
    # =====================================================

    reasons: list[str] = []


    if tail_return >= 0.006:

        reasons.append(
            "尾盤30分鐘續強"
        )


    if fifteen_trend >= 0.60:

        reasons.append(
            "15分K維持多頭"
        )


    if day_position >= 0.78:

        reasons.append(
            "收盤靠近日高"
        )


    if (
        vol_ratio
        or 0
    ) >= 1.20:

        reasons.append(
            "量價配合"
        )


    if (
        inst is not None
        and inst > 0
    ):

        reasons.append(
            "15日法人偏多"
        )


    if daily_uptrend:

        reasons.append(
            "日K趨勢偏多"
        )


    return {

        "overnight_score":
            overnight_score,

        # 舊欄位保留相容性，
        # 但不再作為正式當沖
        "daytrade_score":
            None,

        "price":
            round(
                close,
                4
            ),

        "vwap":
            (
                round(
                    vwap,
                    4
                )
                if vwap
                else None
            ),

        "vwap_distance_pct":
            (
                round(
                    vwap_distance
                    * 100,
                    3
                )
                if (
                    vwap_distance
                    is not None
                )
                else None
            ),

        "volume_ratio":
            (
                round(
                    vol_ratio,
                    3
                )
                if (
                    vol_ratio
                    is not None
                )
                else None
            ),

        "day_position":
            round(
                day_position,
                4
            ),

        "tail_30m_return_pct":
            round(
                tail_return
                * 100,
                3
            ),

        "five_trend":
            round(
                five_trend
                * 100,
                1
            ),

        "fifteen_trend":
            round(
                fifteen_trend
                * 100,
                1
            ),

        "daily_uptrend":
            daily_uptrend,

        "historical_edge":
            round(
                hist_edge
                * 100,
                1
            ),

        "vetoes":
            vetoes,

        "daytrade_reasons":
            [],

        "overnight_reasons":
            reasons[:4],

    }


# =========================================================
# Market Level
# =========================================================

def market_level(
    stocks: list[dict]
) -> tuple[
    str,
    dict,
]:

    valid = []


    for stock in stocks:

        price = num(
            stock.get(
                "price"
            )
        )

        ma20 = num(
            stock.get(
                "sma20"
            )
        )

        ma60 = num(
            stock.get(
                "sma60"
            )
        )


        if (
            price is not None
            and
            ma20 is not None
            and
            ma60 is not None
        ):

            valid.append(
                stock
            )


    if not valid:

        return (
            "YELLOW",
            {
                "breadth":
                    None,

                "avg_momo20_pct":
                    None,
            }
        )


    strong = 0


    for stock in valid:

        price = num(
            stock.get(
                "price"
            )
        )

        ma20 = num(
            stock.get(
                "sma20"
            )
        )

        ma60 = num(
            stock.get(
                "sma60"
            )
        )


        if (
            price is not None
            and
            ma20 is not None
            and
            ma60 is not None
            and
            price > ma20
            and
            price > ma60
        ):

            strong += 1


    breadth = (
        strong
        /
        len(valid)
    )


    momentums: list[float] = []


    for stock in stocks:

        momo = num(
            stock.get(
                "momo20"
            )
        )


        if momo is not None:

            momentums.append(
                momo - 1
            )


    avg_momo = (
        sum(
            momentums
        )
        /
        len(
            momentums
        )
        if momentums
        else 0.0
    )


    if (
        breadth >= 0.60
        and
        avg_momo >= 0
    ):

        level = "GREEN"


    elif (
        breadth >= 0.42
        or
        avg_momo >= 0
    ):

        level = "YELLOW"


    else:

        level = "RED"


    return (
        level,
        {
            "breadth":
                round(
                    breadth,
                    4
                ),

            "avg_momo20_pct":
                round(
                    avg_momo
                    * 100,
                    3
                ),
        }
    )


# =========================================================
# Firebase Initialize
# =========================================================

def init_firebase() -> db.Reference:

    if not FIREBASE_DATABASE_URL:

        raise RuntimeError(
            "Missing FIREBASE_DATABASE_URL"
        )


    credential = None


    # GitHub Actions 使用 JSON secret
    if FIREBASE_SERVICE_ACCOUNT_JSON:

        try:

            service_account = json.loads(
                FIREBASE_SERVICE_ACCOUNT_JSON
            )

        except json.JSONDecodeError as exc:

            raise RuntimeError(
                "Invalid "
                "FIREBASE_SERVICE_ACCOUNT_JSON"
            ) from exc


        credential = (
            credentials.Certificate(
                service_account
            )
        )


    # Oracle VM / local 可用 file
    elif FIREBASE_SERVICE_ACCOUNT_FILE:

        if not os.path.exists(
            FIREBASE_SERVICE_ACCOUNT_FILE
        ):

            raise RuntimeError(
                "Firebase service account "
                "file not found"
            )


        credential = (
            credentials.Certificate(
                FIREBASE_SERVICE_ACCOUNT_FILE
            )
        )


    else:

        raise RuntimeError(
            "Missing Firebase credentials"
        )


    if not firebase_admin._apps:

        firebase_admin.initialize_app(
            credential,
            {
                "databaseURL":
                    FIREBASE_DATABASE_URL
            }
        )


    return db.reference(
        f"/{FIREBASE_ROOT_PATH}"
    )


# =========================================================
# First Seen State
# =========================================================

def load_seen_state(
    root: db.Reference,
    scan_date: str,
) -> dict:

    try:

        data = (
            root
            .child(
                "intraday_seen"
            )
            .child(
                scan_date
            )
            .get()
        )


        if not isinstance(
            data,
            dict
        ):

            return {}


        return data


    except Exception as exc:

        print(
            "[warn] "
            "unable to load "
            "intraday_seen: "
            f"{type(exc).__name__}: "
            f"{exc}"
        )

        return {}


def save_seen_state(
    root: db.Reference,
    scan_date: str,
    state: dict,
) -> None:

    try:

        (
            root
            .child(
                "intraday_seen"
            )
            .child(
                scan_date
            )
            .set(
                state
            )
        )


    except Exception as exc:

        print(
            "[warn] "
            "unable to save "
            "intraday_seen: "
            f"{type(exc).__name__}: "
            f"{exc}"
        )


def ensure_first_seen(
    state: dict,
    item: dict,
    now: datetime,
    pick_type: str,
) -> dict:

    symbol = str(
        item.get(
            "symbol"
        )
        or ""
    ).strip()


    if not symbol:
        return item


    now_iso = now.isoformat(
        timespec="seconds"
    )


    key = (
        f"{pick_type}_"
        f"{symbol}"
    )


    existing = (
        state.get(
            key
        )
    )


    if (
        isinstance(
            existing,
            dict
        )
        and
        existing.get(
            "first_seen_at"
        )
    ):

        first_seen_at = (
            existing[
                "first_seen_at"
            ]
        )


    else:

        first_seen_at = (
            now_iso
        )


        state[key] = {

            "symbol":
                symbol,

            "name":
                item.get(
                    "name"
                )
                or symbol,

            "first_seen_at":
                first_seen_at,

            "first_seen_type":
                pick_type,

            "first_seen_date":
                now.date().isoformat(),

        }


        print(
            "[first-seen] "
            f"{symbol} "
            f"{item.get('name') or ''} "
            f"{pick_type} "
            f"{first_seen_at}"
        )


    item[
        "first_seen_at"
    ] = first_seen_at


    item[
        "last_seen_at"
    ] = now_iso


    item[
        "first_seen_date"
    ] = (
        now.date()
        .isoformat()
    )


    return item


def calculate_duration_minutes(
    first_seen_at: str | None,
    last_seen_at: str | None,
) -> int | None:

    if not first_seen_at:
        return None


    try:

        first = (
            datetime.fromisoformat(
                first_seen_at
            )
        )


        last = (
            datetime.fromisoformat(
                last_seen_at
            )
            if last_seen_at
            else
            datetime.now(
                TPE
            )
        )


        return max(
            0,
            int(
                (
                    last
                    -
                    first
                )
                .total_seconds()
                //
                60
            )
        )


    except Exception:

        return None


def add_time_metadata(
    item: dict
) -> dict:

    item[
        "duration_minutes"
    ] = (
        calculate_duration_minutes(

            item.get(
                "first_seen_at"
            ),

            item.get(
                "last_seen_at"
            ),

        )
    )


    return item


# =========================================================
# Eligibility
# =========================================================

def eligible_overnight(
    item: dict
) -> bool:

    vetoes = (
        item.get(
            "vetoes"
        )
        or []
    )


    hard_veto = any(

        veto in {
            "跌破VWAP",
            "末根爆上影",
            "市場紅燈",
        }

        for veto
        in vetoes
    )


    return bool(

        (
            item.get(
                "overnight_score"
            )
            or 0
        )
        >=
        MIN_OVERNIGHT_SCORE

        and

        not hard_veto

        and

        len(
            item.get(
                "overnight_reasons"
            )
            or []
        )
        >= 2
    )


# =========================================================
# Candidate Selection
# =========================================================

def select_candidates(
    stocks: list[dict]
) -> list[dict]:

    ordered = sorted(

        stocks,

        key=lambda stock: (

            num(
                stock.get(
                    "amount_rank_pct"
                )
            )

            if num(
                stock.get(
                    "amount_rank_pct"
                )
            )
            is not None

            else

            pct_rank_from_hot_rank(
                stock.get(
                    "hot_rank"
                )
            )

        ),

        reverse=True,
    )


    candidates: list[dict] = []


    for stock in ordered:

        price = num(
            stock.get(
                "price"
            )
        )


        if (
            price is None
            or price <= 0
        ):

            continue


        amount_rank_pct = num(
            stock.get(
                "amount_rank_pct"
            )
        )


        # 流動性太低
        if (
            amount_rank_pct
            is not None
            and
            amount_rank_pct < 0.35
        ):

            continue


        daily_return = (
            num(
                stock.get(
                    "intraday_ret"
                )
            )
            or 0.0
        )


        stock_vol_ratio = (
            num(
                stock.get(
                    "volume_ratio"
                )
            )
            or 1.0
        )


        near_high = num(
            stock.get(
                "near_high_ratio"
            )
        )


        # 跌幅過大且沒有量
        if (
            daily_return < -0.035
            and
            stock_vol_ratio < 1.20
        ):

            continue


        # 明顯不在高檔
        if (
            near_high is not None
            and
            near_high < 0.55
        ):

            continue


        candidates.append(
            stock
        )


        if (
            len(candidates)
            >=
            SCAN_MAX_SYMBOLS
        ):

            break


    return candidates


# =========================================================
# Main
# =========================================================

def main() -> None:

    # =====================================================
    # Config check
    # =====================================================

    if not ENABLE_OVERNIGHT:

        print(
            "[done] "
            "overnight scanner disabled"
        )

        return


    if not FUGLE_API_KEY:

        raise RuntimeError(
            "Missing FUGLE_API_KEY"
        )


    root = init_firebase()


    # =====================================================
    # Read summary
    # =====================================================

    summary_raw = (
        root
        .child(
            "summary"
        )
        .get()
        or {}
    )


    if isinstance(
        summary_raw,
        list
    ):

        stocks = [
            item
            for item
            in summary_raw
            if isinstance(
                item,
                dict
            )
        ]


    elif isinstance(
        summary_raw,
        dict
    ):

        stocks = [
            item
            for item
            in summary_raw.values()
            if isinstance(
                item,
                dict
            )
        ]


    else:

        stocks = []


    if not stocks:

        raise RuntimeError(
            "Firebase summary is empty"
        )


    # =====================================================
    # Market Level
    # =====================================================

    level, market_metrics = (
        market_level(
            stocks
        )
    )


    # =====================================================
    # Candidate Pool
    # =====================================================

    candidates = select_candidates(
        stocks
    )


    print(
        "[scan] "
        f"market={level} "
        f"candidates="
        f"{len(candidates)} "
        f"max="
        f"{SCAN_MAX_SYMBOLS} "
        "mode=OVERNIGHT_ONLY"
    )


    # =====================================================
    # Scan
    # =====================================================

    scanned: list[dict] = []


    for index, stock in enumerate(
        candidates,
        start=1
    ):

        symbol = str(
            stock.get(
                "symbol"
            )
            or ""
        ).strip()


        if not symbol:
            continue


        try:

            rows5 = fugle_5m(
                symbol
            )


            if len(rows5) < 6:

                print(
                    f"[skip] "
                    f"{symbol}: "
                    f"only "
                    f"{len(rows5)} "
                    f"5m bars"
                )

                continue


            rows15 = aggregate_15m(
                rows5
            )


            if len(rows15) < 2:

                print(
                    f"[skip] "
                    f"{symbol}: "
                    "not enough 15m bars"
                )

                continue


            features = overnight_features(
                rows5=rows5,
                rows15=rows15,
                stock=stock,
                market_level_name=level,
            )


            result = {

                "symbol":
                    symbol,

                "name":
                    stock.get(
                        "name"
                    )
                    or symbol,

                "exchange":
                    stock.get(
                        "exchange"
                    ),

                "hot_rank":
                    stock.get(
                        "hot_rank"
                    ),

                "amount_rank_pct":
                    stock.get(
                        "amount_rank_pct"
                    ),

                **features,

            }


            scanned.append(
                result
            )


            print(
                f"[{index}/"
                f"{len(candidates)}] "
                f"{symbol} "
                f"overnight="
                f"{features['overnight_score']} "
                f"15m="
                f"{features['fifteen_trend']} "
                f"vol="
                f"{features['volume_ratio']} "
                f"veto="
                f"{','.join(features['vetoes']) or '-'}"
            )


        except requests.HTTPError as exc:

            status_code = getattr(
                exc.response,
                "status_code",
                "?"
            )


            print(
                f"[warn] "
                f"{symbol}: "
                f"Fugle HTTP "
                f"{status_code}"
            )


        except Exception as exc:

            print(
                f"[warn] "
                f"{symbol}: "
                f"{type(exc).__name__}: "
                f"{exc}"
            )


    # =====================================================
    # Picks
    # =====================================================

    overnight: list[dict] = []


    if ENABLE_OVERNIGHT:

        overnight = sorted(

            (
                item
                for item
                in scanned
                if eligible_overnight(
                    item
                )
            ),

            key=lambda item: (

                item.get(
                    "overnight_score"
                )
                or 0,

                item.get(
                    "fifteen_trend"
                )
                or 0,

                item.get(
                    "day_position"
                )
                or 0,

            ),

            reverse=True,

        )[:TOP_N]


    # =====================================================
    # Legacy DAYTRADE
    #
    # 正式停用。
    # 即使環境變數誤設，也不由這支程式產生。
    # =====================================================

    daytrade: list[dict] = []


    if ENABLE_DAYTRADE:

        print(
            "[warn] "
            "INTRADAY_ENABLE_DAYTRADE=1 "
            "was supplied, but legacy "
            "daytrade output remains disabled. "
            "Use /intraday_live from Shioaji."
        )


    # =====================================================
    # Time Metadata
    # =====================================================

    now = datetime.now(
        TPE
    )


    scan_date = (
        now.date()
        .isoformat()
    )


    generated_at = (
        now.isoformat(
            timespec="seconds"
        )
    )


    seen_state = (
        load_seen_state(
            root,
            scan_date
        )
    )


    for item in overnight:

        ensure_first_seen(
            state=seen_state,
            item=item,
            now=now,
            pick_type="OVERNIGHT",
        )

        add_time_metadata(
            item
        )


    save_seen_state(
        root=root,
        scan_date=scan_date,
        state=seen_state,
    )


    # =====================================================
    # Session
    # =====================================================

    if (
        now.hour > 13
        or
        (
            now.hour == 13
            and
            now.minute >= 30
        )
    ):

        session_name = "close"

    else:

        session_name = "intraday"


    # =====================================================
    # Firebase Payload
    # =====================================================

    payload = {

        "version":
            MODEL_VERSION,

        "generated_at":
            generated_at,

        "last_scan_at":
            generated_at,

        "scan_date":
            scan_date,

        "date":
            scan_date,

        "session":
            session_name,

        "source":
            "legacy_fugle_overnight",

        # ---------------------------------------------
        # 模組狀態
        # ---------------------------------------------

        "legacy_daytrade_enabled":
            False,

        "legacy_overnight_enabled":
            True,

        "daytrade_source":
            "disabled_use_intraday_live",

        "overnight_source":
            "fugle",

        # ---------------------------------------------
        # Market
        # ---------------------------------------------

        "market_level":
            level,

        "market_metrics":
            market_metrics,

        # ---------------------------------------------
        # Counts
        # ---------------------------------------------

        "scanned_symbols":
            len(scanned),

        "candidate_symbols":
            len(candidates),

        # ---------------------------------------------
        # Picks
        # ---------------------------------------------

        # 永遠空陣列。
        # 網頁正式當沖改讀 intraday_live。
        "daytrade":
            daytrade,

        "overnight":
            overnight,

        # ---------------------------------------------
        # Threshold
        # ---------------------------------------------

        "thresholds": {

            "daytrade":
                MIN_DAYTRADE_SCORE,

            "overnight":
                MIN_OVERNIGHT_SCORE,

        },

        # ---------------------------------------------
        # New Daytrade schedule
        # ---------------------------------------------

        "daytrade_schedule": {

            "source":
                "shioaji_live",

            "entry_start":
                "09:30",

            "entry_cutoff":
                "12:30",

            "force_exit":
                "12:55",

            "daytrade_end":
                "13:00",

        },

        # ---------------------------------------------
        # Time tracking
        # ---------------------------------------------

        "time_tracking": {

            "enabled":
                True,

            "timezone":
                "Asia/Taipei",

            "description":
                (
                    "overnight first_seen_at = "
                    "當日第一次符合隔日衝條件時間；"
                    "last_scan_at = "
                    "最後掃描完成時間"
                ),

        },

        # ---------------------------------------------
        # Method
        # ---------------------------------------------

        "method":
            (
                "Legacy Fugle overnight only: "
                "5m -> local 15m; "
                "tail strength + 15m trend + "
                "close near day high + volume + "
                "liquidity + institution + "
                "historical proxy. "
                "Live daytrade moved to "
                "Oracle VM + Sinotrade Shioaji."
            ),

        # ---------------------------------------------
        # Notes
        # ---------------------------------------------

        "notes": [

            (
                "舊 Fugle 當沖已停用；"
                "正式當沖由 Oracle VM + "
                "Shioaji intraday_live 提供。"
            ),

            (
                "正式當沖時間："
                "09:30 開始、"
                "12:30 停止新進場、"
                "12:55 強制出場、"
                "13:00 完全結束。"
            ),

            (
                "隔日衝仍使用 Fugle "
                "5分K / 15分K 尾盤模型。"
            ),

            (
                "隔日衝重視尾盤30分鐘、"
                "15分K趨勢、收盤靠近日高、"
                "量能、流動性與法人。"
            ),

            (
                "歷史 edge 僅作小權重確認，"
                "不等同真實成交績效。"
            ),

        ],

    }


    # =====================================================
    # Write Firebase
    #
    # 只寫 intraday_picks，
    # 絕對不碰 intraday_live。
    # =====================================================

    (
        root
        .child(
            "intraday_picks"
        )
        .set(
            payload
        )
    )


    # =====================================================
    # Log
    # =====================================================

    print(
        "[done] "
        "legacy_daytrade=DISABLED "
        f"overnight="
        f"{len(overnight)} "
        f"generated_at="
        f"{generated_at} "
        f"wrote=/{FIREBASE_ROOT_PATH}/"
        "intraday_picks"
    )


    print(
        "[safe] "
        "Shioaji /intraday_live "
        "was NOT modified."
    )


# =========================================================
# Entry
# =========================================================

if __name__ == "__main__":
    main()
