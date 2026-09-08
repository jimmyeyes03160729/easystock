#!/usr/bin/env python3
"""Fugle intraday pattern scanner for Mohren Quant Matrix v1.1.

Reads the current hot-stock universe from Firebase, screens liquid candidates,
fetches Fugle 5-minute candles, derives 15-minute candles locally, and writes
cross-confirmed day-trade / next-day picks to /market_data/intraday_picks.

Time tracking:
- first_seen_at: first time the symbol became eligible today
- last_seen_at: latest scan time
- generated_at: current scan completion time
- scan_date: Taiwan trading date

No API key is ever written to Firebase or logs.
"""

from __future__ import annotations

import json
import math
import os
import statistics
import time
from datetime import datetime, timezone, timedelta
from typing import Any

import firebase_admin
from firebase_admin import credentials, db
import requests


FIREBASE_DATABASE_URL = os.environ.get(
    "FIREBASE_DATABASE_URL", ""
).strip().rstrip("/")

FIREBASE_SERVICE_ACCOUNT_JSON = os.environ.get(
    "FIREBASE_SERVICE_ACCOUNT_JSON", ""
).strip()

FIREBASE_ROOT_PATH = (
    os.environ.get("FIREBASE_ROOT_PATH", "market_data").strip("/")
    or "market_data"
)

FUGLE_API_KEY = os.environ.get("FUGLE_API_KEY", "").strip()

FUGLE_BASE = "https://api.fugle.tw/marketdata/v1.0/stock"

HTTP_TIMEOUT = float(os.environ.get("HTTP_TIMEOUT", "12"))

SCAN_MAX_SYMBOLS = max(
    5,
    int(os.environ.get("INTRADAY_SCAN_MAX_SYMBOLS", "30"))
)

MIN_INTERVAL = max(
    0.0,
    float(os.environ.get("FUGLE_MIN_INTERVAL_SECONDS", "1.10"))
)

MIN_DAYTRADE_SCORE = int(
    os.environ.get("INTRADAY_MIN_DAYTRADE_SCORE", "76")
)

MIN_OVERNIGHT_SCORE = int(
    os.environ.get("INTRADAY_MIN_OVERNIGHT_SCORE", "74")
)
# =========================================================
# Legacy Fugle scanner switches
#
# 新版：
# Daytrade 由 Oracle VM + Shioaji 負責
# Fugle workflow 只保留 Overnight
# =========================================================

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
TOP_N = max(
    1,
    int(os.environ.get("INTRADAY_TOP_N", "3"))
)

MODEL_VERSION = "1.1"

TPE = timezone(timedelta(hours=8))

_last_call = 0.0

session = requests.Session()
session.headers.update({
    "User-Agent": "MohrenQuant/1.1",
    "Accept": "application/json"
})


def num(v: Any) -> float | None:
    try:
        if v is None or v == "":
            return None

        x = float(v)

        return x if math.isfinite(x) else None

    except (TypeError, ValueError):
        return None


def clamp(
    v: float,
    lo: float = 0.0,
    hi: float = 1.0
) -> float:

    return max(lo, min(hi, v))


def pct_rank_from_hot_rank(
    rank: Any,
    universe: int = 500
) -> float:

    r = num(rank)

    if r is None:
        return 0.5

    return clamp(
        1.0 - (r - 1) / max(1, universe - 1)
    )


def wait_rate_limit() -> None:

    global _last_call

    elapsed = time.monotonic() - _last_call

    if elapsed < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - elapsed)

    _last_call = time.monotonic()


def fugle_5m(symbol: str) -> list[dict]:

    wait_rate_limit()

    url = f"{FUGLE_BASE}/intraday/candles/{symbol}"

    resp = session.get(
        url,
        params={
            "timeframe": "5",
            "sort": "asc"
        },
        headers={
            "X-API-KEY": FUGLE_API_KEY
        },
        timeout=HTTP_TIMEOUT,
    )

    if resp.status_code == 404:
        return []

    if resp.status_code == 429:

        time.sleep(
            max(
                3.0,
                MIN_INTERVAL * 3
            )
        )

        wait_rate_limit()

        resp = session.get(
            url,
            params={
                "timeframe": "5",
                "sort": "asc"
            },
            headers={
                "X-API-KEY": FUGLE_API_KEY
            },
            timeout=HTTP_TIMEOUT,
        )

    resp.raise_for_status()

    payload = resp.json() or {}

    rows = payload.get("data") or []

    clean = []

    for row in rows:

        o, h, l, c, v = map(
            num,
            [
                row.get("open"),
                row.get("high"),
                row.get("low"),
                row.get("close"),
                row.get("volume"),
            ]
        )

        if None in (o, h, l, c) or v is None:
            continue

        clean.append({
            "date": row.get("date"),
            "open": o,
            "high": h,
            "low": l,
            "close": c,
            "volume": max(0.0, v),
            "average": num(row.get("average")),
        })

    return clean


def aggregate_15m(rows: list[dict]) -> list[dict]:

    out = []

    for i in range(0, len(rows), 3):

        chunk = rows[i:i + 3]

        if len(chunk) < 3:
            continue

        vol = sum(
            x["volume"]
            for x in chunk
        )

        out.append({
            "date": chunk[-1]["date"],
            "open": chunk[0]["open"],
            "high": max(
                x["high"]
                for x in chunk
            ),
            "low": min(
                x["low"]
                for x in chunk
            ),
            "close": chunk[-1]["close"],
            "volume": vol,
        })

    return out


def sma(
    values: list[float],
    n: int
) -> float | None:

    if len(values) < n:
        return None

    return sum(values[-n:]) / n


def bar_position(bar: dict) -> float:

    span = bar["high"] - bar["low"]

    if span <= 0:
        return 0.5

    return clamp(
        (bar["close"] - bar["low"]) / span
    )


def upper_wick_ratio(bar: dict) -> float:

    span = bar["high"] - bar["low"]

    if span <= 0:
        return 0.0

    return clamp(
        (
            bar["high"]
            - max(bar["open"], bar["close"])
        ) / span
    )


def trend_score(
    rows: list[dict]
) -> tuple[float, list[str]]:

    if len(rows) < 2:
        return 0.0, []

    closes = [
        x["close"]
        for x in rows
    ]

    short = sma(closes, 3)
    slow = sma(closes, 6)

    last = closes[-1]

    recent = rows[
        -min(4, len(rows)):
    ]

    comparisons = max(
        1,
        len(recent) - 1
    )

    higher_lows = sum(
        recent[i]["low"]
        >= recent[i - 1]["low"]
        for i in range(1, len(recent))
    )

    higher_highs = sum(
        recent[i]["high"]
        >= recent[i - 1]["high"]
        for i in range(1, len(recent))
    )

    score = 0.0

    reasons = []

    if (
        short is not None
        and slow is not None
        and last > short > slow
    ):

        score += 0.55

        reasons.append("短均線多頭")

    elif (
        short is not None
        and last > short
    ):

        score += 0.35

    elif last > closes[0]:

        score += 0.25

    score += (
        0.225
        * (higher_lows / comparisons)
    )

    score += (
        0.225
        * (higher_highs / comparisons)
    )

    if (
        higher_lows >= max(1, comparisons - 1)
        and higher_highs >= max(1, comparisons - 1)
    ):

        reasons.append("高低點墊高")

    return clamp(score), reasons


def vwap_proxy(
    rows: list[dict]
) -> float | None:

    if not rows:
        return None

    last_avg = num(
        rows[-1].get("average")
    )

    if last_avg and last_avg > 0:
        return last_avg

    vol = sum(
        x["volume"]
        for x in rows
    )

    if vol <= 0:
        return None

    return sum(
        (
            (
                x["high"]
                + x["low"]
                + x["close"]
            ) / 3
        ) * x["volume"]
        for x in rows
    ) / vol


def volume_score(
    rows: list[dict]
) -> tuple[float, float | None]:

    if len(rows) < 10:
        return 0.4, None

    recent = [
        x["volume"]
        for x in rows[-3:]
    ]

    base = [
        x["volume"]
        for x in rows[-12:-3]
        if x["volume"] > 0
    ]

    if not base:
        return 0.4, None

    ratio = (
        sum(recent) / len(recent)
    ) / (
        sum(base) / len(base)
    )

    return (
        clamp(
            (ratio - 0.7) / 1.8
        ),
        ratio
    )


def pattern_features(
    rows5: list[dict],
    rows15: list[dict],
    stock: dict,
    market_level: str
) -> dict:

    last = rows5[-1]

    close = last["close"]

    day_high = max(
        x["high"]
        for x in rows5
    )

    day_low = min(
        x["low"]
        for x in rows5
    )

    day_span = max(
        1e-9,
        day_high - day_low
    )

    day_pos = clamp(
        (close - day_low)
        / day_span
    )

    vwap = vwap_proxy(rows5)

    dist_vwap = (
        None
        if not vwap
        else close / vwap - 1
    )

    five_trend, five_reasons = trend_score(
        rows5
    )

    fifteen_trend, fifteen_reasons = trend_score(
        rows15
    )

    vol_score, vol_ratio = volume_score(
        rows5
    )

    opening = rows5[:6]

    opening_high = max(
        (
            x["high"]
            for x in opening
        ),
        default=None
    )

    orb = bool(
        opening_high is not None
        and len(rows5) >= 7
        and close > opening_high * 1.001
    )

    pre = (
        rows5[-7:-1]
        if len(rows5) >= 7
        else []
    )

    compression_breakout = False

    if pre:

        pre_high = max(
            x["high"]
            for x in pre
        )

        pre_low = min(
            x["low"]
            for x in pre
        )

        pre_mid = statistics.mean(
            x["close"]
            for x in pre
        )

        compression = (
            pre_mid > 0
            and (
                pre_high - pre_low
            ) / pre_mid <= 0.018
        )

        compression_breakout = bool(
            compression
            and close > pre_high
            and (vol_ratio or 0) >= 1.15
        )

    daily_up = bool(
        num(stock.get("sma20"))
        and num(stock.get("sma60"))
        and close > num(stock["sma20"])
        and close > num(stock["sma60"])
    )

    amount_pct = num(
        stock.get("amount_rank_pct")
    )

    liquidity = clamp(
        amount_pct
        if amount_pct is not None
        else pct_rank_from_hot_rank(
            stock.get("hot_rank")
        )
    )

    bt = (
        stock.get("backtest")
        or {}
    ).get("daytrade_proxy") or {}

    pf = num(
        bt.get("profit_factor")
    )

    avg_ret = num(
        bt.get("avg_return")
    )

    samples = (
        num(bt.get("signals"))
        or 0
    )

    hist_edge = 0.45

    if samples >= 20:

        hist_edge = clamp(
            0.35
            + clamp(
                ((pf or 1) - 0.8) / 0.8
            ) * 0.35
            + clamp(
                ((avg_ret or 0) + 0.005)
                / 0.02
            ) * 0.30
        )

    pattern_score = clamp(
        five_trend * 0.55
        + fifteen_trend * 0.30
        + (
            0.15
            if orb or compression_breakout
            else 0
        )
    )

    vwap_score = 0.2

    if vwap:

        if close >= vwap:

            vwap_score = (
                0.85
                if (dist_vwap or 0) <= 0.02
                else 0.60
            )

        else:

            vwap_score = 0.10

    market_score = {
        "GREEN": 1.0,
        "YELLOW": 0.60,
        "RED": 0.15,
    }.get(
        market_level,
        0.5
    )

    daytrade_score = round(
        100 * (
            pattern_score * 0.30
            + vol_score * 0.20
            + vwap_score * 0.15
            + market_score * 0.10
            + liquidity * 0.10
            + hist_edge * 0.15
        )
    )

    tail = (
        rows5[-6:]
        if len(rows5) >= 6
        else rows5
    )

    tail_ret = (
        (
            tail[-1]["close"]
            / tail[0]["open"]
            - 1
        )
        if tail
        and tail[0]["open"]
        else 0
    )

    tail_strength = clamp(
        (tail_ret + 0.005)
        / 0.03
    )

    close_high_score = clamp(
        (day_pos - 0.45)
        / 0.55
    )

    inst = num(
        stock.get("net15Total")
    )

    inst_score = (
        0.5
        if inst is None
        else clamp(
            (inst + 2_000_000)
            / 4_000_000
        )
    )

    daily_score = (
        1.0
        if daily_up
        else 0.35
    )

    overnight_score = round(
        100 * (
            fifteen_trend * 0.25
            + tail_strength * 0.20
            + close_high_score * 0.15
            + vol_score * 0.15
            + liquidity * 0.10
            + inst_score * 0.10
            + hist_edge * 0.05
        )
    )

    vetoes = []

    if vwap and close < vwap * 0.998:
        vetoes.append("跌破VWAP")

    if (
        dist_vwap is not None
        and dist_vwap > 0.03
    ):
        vetoes.append("距VWAP過遠")

    if (
        upper_wick_ratio(last) >= 0.55
        and bar_position(last) < 0.65
    ):
        vetoes.append("末根爆上影")

    if (
        len(rows5) >= 7
        and close <= min(
            x["low"]
            for x in rows5[-6:-1]
        )
    ):
        vetoes.append("5分K破短低")

    if market_level == "RED":
        vetoes.append("市場紅燈")

    day_reasons = []

    if five_trend >= 0.65:
        day_reasons.append("5分K多頭")

    if fifteen_trend >= 0.60:
        day_reasons.append("15分K同向")

    if vwap and close >= vwap:
        day_reasons.append("站上VWAP")

    if (vol_ratio or 0) >= 1.30:
        day_reasons.append(
            f"量能放大 {vol_ratio:.1f}x"
        )

    if orb:
        day_reasons.append("突破早盤區間")

    elif compression_breakout:
        day_reasons.append("壓縮後放量突破")

    if daily_up:
        day_reasons.append("日K多頭")

    overnight_reasons = []

    if tail_ret >= 0.006:
        overnight_reasons.append(
            "尾盤30分鐘續強"
        )

    if fifteen_trend >= 0.60:
        overnight_reasons.append(
            "15分K維持多頭"
        )

    if day_pos >= 0.78:
        overnight_reasons.append(
            "收盤靠近日高"
        )

    if (vol_ratio or 0) >= 1.20:
        overnight_reasons.append(
            "量價配合"
        )

    if inst is not None and inst > 0:
        overnight_reasons.append(
            "15日法人偏多"
        )

    if daily_up:
        overnight_reasons.append(
            "日K趨勢偏多"
        )

    return {
        "daytrade_score": daytrade_score,
        "overnight_score": overnight_score,
        "price": round(close, 4),
        "vwap": round(vwap, 4)
        if vwap else None,
        "vwap_distance_pct": round(
            (dist_vwap or 0) * 100,
            3
        )
        if dist_vwap is not None
        else None,
        "volume_ratio": round(
            vol_ratio,
            3
        )
        if vol_ratio is not None
        else None,
        "day_position": round(
            day_pos,
            4
        ),
        "tail_30m_return_pct": round(
            tail_ret * 100,
            3
        ),
        "five_trend": round(
            five_trend * 100,
            1
        ),
        "fifteen_trend": round(
            fifteen_trend * 100,
            1
        ),
        "opening_range_breakout": orb,
        "compression_breakout": compression_breakout,
        "daily_uptrend": daily_up,
        "historical_edge": round(
            hist_edge * 100,
            1
        ),
        "vetoes": vetoes,
        "daytrade_reasons": day_reasons[:4],
        "overnight_reasons": overnight_reasons[:4],
    }


def market_level(
    stocks: list[dict]
) -> tuple[str, dict]:

    valid = [
        s
        for s in stocks
        if num(s.get("price"))
        and num(s.get("sma20"))
        and num(s.get("sma60"))
    ]

    if not valid:
        return "YELLOW", {
            "breadth": None,
            "avg_momo20_pct": None
        }

    breadth = (
        sum(
            num(s["price"]) > num(s["sma20"])
            and num(s["price"]) > num(s["sma60"])
            for s in valid
        )
        / len(valid)
    )

    momos = [
        (
            num(s.get("momo20")) - 1
        )
        for s in stocks
        if num(s.get("momo20")) is not None
    ]

    avg_momo = (
        sum(momos) / len(momos)
        if momos
        else 0
    )

    level = (
        "GREEN"
        if breadth >= 0.60
        and avg_momo >= 0
        else "YELLOW"
        if breadth >= 0.42
        or avg_momo >= 0
        else "RED"
    )

    return level, {
        "breadth": round(
            breadth,
            4
        ),
        "avg_momo20_pct": round(
            avg_momo * 100,
            3
        )
    }


def init_firebase() -> db.Reference:

    if (
        not FIREBASE_DATABASE_URL
        or not FIREBASE_SERVICE_ACCOUNT_JSON
    ):
        raise RuntimeError(
            "Missing Firebase secrets"
        )

    payload = json.loads(
        FIREBASE_SERVICE_ACCOUNT_JSON
    )

    if not firebase_admin._apps:

        firebase_admin.initialize_app(
            credentials.Certificate(payload),
            {
                "databaseURL":
                    FIREBASE_DATABASE_URL
            }
        )

    return db.reference(
        f"/{FIREBASE_ROOT_PATH}"
    )


# ---------------------------------------------------------
# 首次出現時間管理
# ---------------------------------------------------------

def load_seen_state(
    root: db.Reference,
    scan_date: str
) -> dict:

    """
    讀取今天的首次出現紀錄。

    Firebase:
    market_data/
        intraday_seen/
            2026-09-08/
                2330/
                    first_seen_at
                    first_seen_type
                    symbol
                    name
    """

    try:

        data = (
            root
            .child("intraday_seen")
            .child(scan_date)
            .get()
        )

        if not isinstance(data, dict):
            return {}

        return data

    except Exception as e:

        print(
            f"[warn] unable to load "
            f"intraday_seen: {type(e).__name__}: {e}"
        )

        return {}


def save_seen_state(
    root: db.Reference,
    scan_date: str,
    seen_state: dict
) -> None:

    """
    保存今天的首次出現資料。
    """

    try:

        (
            root
            .child("intraday_seen")
            .child(scan_date)
            .set(seen_state)
        )

    except Exception as e:

        print(
            f"[warn] unable to save "
            f"intraday_seen: {type(e).__name__}: {e}"
        )


def ensure_first_seen(
    seen_state: dict,
    item: dict,
    now: datetime,
    pick_type: str
) -> dict:

    symbol = str(
        item.get("symbol") or ""
    ).strip()

    if not symbol:
        return item

    now_iso = now.isoformat(
        timespec="seconds"
    )

    existing = seen_state.get(
        symbol
    )

    if (
        isinstance(existing, dict)
        and existing.get("first_seen_at")
    ):

        first_seen_at = existing[
            "first_seen_at"
        ]

    else:

        first_seen_at = now_iso

        seen_state[symbol] = {
            "symbol": symbol,
            "name": item.get("name") or symbol,
            "first_seen_at": first_seen_at,
            "first_seen_type": pick_type,
            "first_seen_date": now.date().isoformat(),
        }

        print(
            f"[first-seen] "
            f"{symbol} "
            f"{item.get('name') or ''} "
            f"{pick_type} "
            f"{first_seen_at}"
        )

    item["first_seen_at"] = first_seen_at
    item["last_seen_at"] = now_iso
    item["first_seen_date"] = now.date().isoformat()

    return item


def calculate_duration_minutes(
    first_seen_at: str | None,
    last_seen_at: str | None
) -> int | None:

    if not first_seen_at:
        return None

    try:

        first = datetime.fromisoformat(
            first_seen_at
        )

        last = (
            datetime.fromisoformat(
                last_seen_at
            )
            if last_seen_at
            else datetime.now(TPE)
        )

        return max(
            0,
            int(
                (
                    last - first
                ).total_seconds()
                // 60
            )
        )

    except Exception:
        return None


def add_time_metadata(
    item: dict
) -> dict:

    duration = calculate_duration_minutes(
        item.get("first_seen_at"),
        item.get("last_seen_at")
    )

    item["duration_minutes"] = duration

    return item


def main() -> None:

    if not FUGLE_API_KEY:
        raise RuntimeError(
            "Missing FUGLE_API_KEY"
        )

    root = init_firebase()

    summary_raw = (
        root
        .child("summary")
        .get()
        or {}
    )

    if isinstance(summary_raw, list):

        stocks = [
            x
            for x in summary_raw
            if isinstance(x, dict)
        ]

    else:

        stocks = [
            x
            for x in summary_raw.values()
            if isinstance(x, dict)
        ]

    if not stocks:
        raise RuntimeError(
            "Firebase summary is empty"
        )

    stocks.sort(
        key=lambda s: (
            num(
                s.get("amount_rank_pct")
            )
            or pct_rank_from_hot_rank(
                s.get("hot_rank")
            )
        ),
        reverse=True
    )

    candidates = []

    for s in stocks:

        p = num(
            s.get("price")
        )

        if not p or p <= 0:
            continue

        if (
            num(s.get("amount_rank_pct"))
            or 0
        ) < 0.35:
            continue

        daily_ret = (
            num(s.get("intraday_ret"))
            or 0
        )

        vol_ratio = (
            num(s.get("volume_ratio"))
            or 1
        )

        near_high = (
            num(s.get("near_high_ratio"))
            or 0
        )

        if (
            daily_ret < -0.035
            and vol_ratio < 1.2
        ):
            continue

        if (
            near_high
            and near_high < 0.55
        ):
            continue

        candidates.append(s)

        if len(candidates) >= SCAN_MAX_SYMBOLS:
            break

    level, market_metrics = market_level(
        stocks
    )

    print(
        f"[scan] market={level} "
        f"candidates={len(candidates)} "
        f"max={SCAN_MAX_SYMBOLS}"
    )

    scanned = []

    for idx, stock in enumerate(
        candidates,
        1
    ):

        sym = str(
            stock.get("symbol") or ""
        ).strip()

        if not sym:
            continue

        try:

            rows5 = fugle_5m(sym)

            if len(rows5) < 6:

                print(
                    f"[skip] {sym}: "
                    f"only {len(rows5)} 5m bars"
                )

                continue

            rows15 = aggregate_15m(
                rows5
            )

            f = pattern_features(
                rows5,
                rows15,
                stock,
                level
            )

            scanned.append({
                "symbol": sym,
                "name": stock.get("name") or sym,
                "exchange": stock.get("exchange"),
                "hot_rank": stock.get("hot_rank"),
                **f,
            })

            print(
                f"[{idx}/{len(candidates)}] "
                f"{sym} "
                f"day={f['daytrade_score']} "
                f"overnight={f['overnight_score']} "
                f"veto="
                f"{','.join(f['vetoes']) or '-'}"
            )

        except requests.HTTPError as e:

            code = getattr(
                e.response,
                "status_code",
                "?"
            )

            print(
                f"[warn] {sym}: "
                f"Fugle HTTP {code}"
            )

        except Exception as e:

            print(
                f"[warn] {sym}: "
                f"{type(e).__name__}: {e}"
            )

    def eligible_day(
        x: dict
    ) -> bool:

        return (
            x["daytrade_score"]
            >= MIN_DAYTRADE_SCORE
            and not x["vetoes"]
            and len(
                x["daytrade_reasons"]
            ) >= 2
        )

    def eligible_overnight(
        x: dict
    ) -> bool:

        hard_veto = any(
            v in {
                "跌破VWAP",
                "末根爆上影",
                "市場紅燈"
            }
            for v in x["vetoes"]
        )

        return (
            x["overnight_score"]
            >= MIN_OVERNIGHT_SCORE
            and not hard_veto
            and len(
                x["overnight_reasons"]
            ) >= 2
        )

    day = sorted(
        (
            x
            for x in scanned
            if eligible_day(x)
        ),
        key=lambda x: (
            x["daytrade_score"],
            x["five_trend"],
            x["volume_ratio"] or 0
        ),
        reverse=True
    )[:TOP_N]

    overnight = sorted(
        (
            x
            for x in scanned
            if eligible_overnight(x)
        ),
        key=lambda x: (
            x["overnight_score"],
            x["fifteen_trend"],
            x["day_position"]
        ),
        reverse=True
    )[:TOP_N]

    now = datetime.now(TPE)

    scan_date = now.date().isoformat()

    generated_at = now.isoformat(
        timespec="seconds"
    )

    # -----------------------------------------------------
    # 讀取今天的首次出現紀錄
    # -----------------------------------------------------

    seen_state = load_seen_state(
        root,
        scan_date
    )

    # -----------------------------------------------------
    # 當沖首次出現
    # -----------------------------------------------------

    for item in day:

        ensure_first_seen(
            seen_state,
            item,
            now,
            "DAYTRADE"
        )

        add_time_metadata(item)

    # -----------------------------------------------------
    # 隔日衝首次出現
    # -----------------------------------------------------

    for item in overnight:

        ensure_first_seen(
            seen_state,
            item,
            now,
            "OVERNIGHT"
        )

        add_time_metadata(item)

    # -----------------------------------------------------
    # 保存首次出現資料
    # -----------------------------------------------------

    save_seen_state(
        root,
        scan_date,
        seen_state
    )

    # -----------------------------------------------------
    # Firebase 主資料
    # -----------------------------------------------------

    payload = {
        "version": MODEL_VERSION,

        # 本次掃描完成時間
        "generated_at": generated_at,

        # 額外明確命名
        "last_scan_at": generated_at,

        # 掃描日期
        "scan_date": scan_date,

        "date": scan_date,

        "session": (
            "close"
            if (
                now.hour > 13
                or (
                    now.hour == 13
                    and now.minute >= 30
                )
            )
            else "intraday"
        ),

        "market_level": level,

        "market_metrics": market_metrics,

        "scanned_symbols": len(scanned),

        "candidate_symbols": len(candidates),

        "daytrade": day,

        "overnight": overnight,

        "thresholds": {
            "daytrade":
                MIN_DAYTRADE_SCORE,
            "overnight":
                MIN_OVERNIGHT_SCORE,
        },

        "time_tracking": {
            "enabled": True,
            "timezone": "Asia/Taipei",
            "description": (
                "first_seen_at = "
                "第一次符合條件時間；"
                "last_scan_at = "
                "最後一次掃描完成時間"
            ),
        },

        "method": (
            "Fugle 5m -> local 15m "
            "cross-confirmation: trend + VWAP "
            "+ volume + breakout + daily trend "
            "+ liquidity + historical proxy; "
            "veto fake/extended setups"
        ),

        "notes": [
            "當沖以5分K為主、15分K與日K確認；跌破VWAP、末根長上影、5分K破短低或市場紅燈會否決。",
            "隔日衝重視尾盤30分鐘、15分K趨勢、收盤靠近日高、量能與法人；避免尾盤轉弱或距VWAP過遠。",
            "歷史edge目前只以既有日線隔日代理回測作小權重確認，不等同真正分K歷史回測。",
            "首次出現時間只在當日第一次符合條件時建立，後續掃描不會覆蓋。",
        ],
    }

    # -----------------------------------------------------
    # 寫入 Firebase
    # -----------------------------------------------------

    (
        root
        .child("intraday_picks")
        .set(payload)
    )

    print(
        "[done] "
        f"daytrade={len(day)} "
        f"overnight={len(overnight)} "
        f"generated_at={generated_at} "
        f"wrote "
        f"/{FIREBASE_ROOT_PATH}/intraday_picks"
    )


if __name__ == "__main__":
    main()
