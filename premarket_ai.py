#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Easystock AI Premarket Brief
============================

每天台灣時間 08:35 執行一次：
1. 取得前一交易日 / 最新可用的美股與跨市場資料
2. 取得台指期近一最新資料（Yahoo 台灣期權頁，best effort）
3. 取得最新新聞標題（Google News RSS，best effort）
4. 用 deterministic features 算 base risk score
5. 若 GEMINI_API_KEY 已設定，交由 AI 做：
   - headline risk adjustment（限制 -5 ~ +5）
   - 市場摘要
   - sector_bias
   - key_risks / key_supports
6. 寫入 Firebase：
      /market_data/premarket_brief
7. 推送 LINE
8. LINE 訊息固定包含：
      https://jimmyeyes03160729.github.io/easystock/

注意：
- 原始價格與漲跌不交給 AI 猜，全部由公開資料取得/計算。
- AI 只做綜合判讀與小幅 headline adjustment。
- 若 AI API 不可用，仍會產生 deterministic fallback brief。
"""

from __future__ import annotations

import html
import json
import math
import os

from line_group_manager import get_active_groups

import random
import re
import sys
import time
import xml.etree.ElementTree as ET

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests
import shioaji as sj
from firebase_admin import db

from firebase_store import FirebaseStore


TPE = timezone(timedelta(hours=8))

WEBSITE_URL = "https://jimmyeyes03160729.github.io/easystock/"

YAHOO_CHART_HOSTS = [
    "https://query1.finance.yahoo.com",
    "https://query2.finance.yahoo.com",
]
YAHOO_TW_FUTURE_URL = "https://tw.stock.yahoo.com/quote/WTX%26"
GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"

HTTP_TIMEOUT = 12

# 使用 daily regular-session close。08:35 TPE 時美股已收盤。
MARKET_SYMBOLS = {
    "sp500": "^GSPC",
    "nasdaq": "^IXIC",
    "sox": "^SOX",
    "vix": "^VIX",
    "tsm_adr": "TSM",
    "usd_twd": "TWD=X",
    "us10y": "^TNX",
    "oil_wti": "CL=F",
}

DISPLAY_NAMES = {
    "sp500": "S&P 500",
    "nasdaq": "NASDAQ",
    "sox": "SOX",
    "vix": "VIX",
    "tsm_adr": "台積電 ADR",
    "usd_twd": "USD/TWD",
    "us10y": "美國10年債",
    "oil_wti": "WTI 原油",
    "taiwan_futures": "台指期近一",
}


def load_dotenv_simple(path: str | Path = ".env") -> None:
    p = Path(path)
    if not p.exists():
        return

    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


load_dotenv_simple()


def env_first(*names: str, default: str = "") -> str:
    for name in names:
        value = os.environ.get(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return default


GEMINI_API_KEY = env_first("GEMINI_API_KEY", "GOOGLE_API_KEY")
GEMINI_MODEL = env_first("GEMINI_PREMARKET_MODEL", default="gemini-2.5-flash")

SJ_API_KEY = env_first(
    "SJ_API_KEY",
    "SHIOAJI_API_KEY",
)

SJ_SECRET_KEY = env_first(
    "SJ_SECRET_KEY",
    "SHIOAJI_SECRET_KEY",
)

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


def now_tpe() -> datetime:
    return datetime.now(TPE)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def num(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        x = float(value)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def pct_change(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or previous == 0:
        return None
    return (current / previous - 1.0) * 100.0


_SESSION = requests.Session()
_LAST_YAHOO_CALL = 0.0


def http_get(
    url: str,
    *,
    retries: int = 3,
    retry_429: bool = True,
    **kwargs,
) -> requests.Response:
    """
    一般 HTTP GET。
    對 429 / 5xx 做短暫 backoff。
    """
    headers = kwargs.pop("headers", {})
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "*/*",
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.7",
        "Connection": "keep-alive",
        **headers,
    }

    last_exc = None

    for attempt in range(max(1, retries)):
        try:
            response = _SESSION.get(
                url,
                headers=headers,
                timeout=HTTP_TIMEOUT,
                **kwargs,
            )

            if (
                response.status_code == 429
                and retry_429
                and attempt < retries - 1
            ):
                wait = 1.5 * (attempt + 1) + random.uniform(0.2, 0.8)
                print(
                    f"[WARN] HTTP 429，{wait:.1f}s 後重試："
                    f"{url.split('?')[0]}"
                )
                time.sleep(wait)
                continue

            if (
                response.status_code >= 500
                and attempt < retries - 1
            ):
                wait = 1.0 * (attempt + 1)
                time.sleep(wait)
                continue

            response.raise_for_status()
            return response

        except requests.RequestException as exc:
            last_exc = exc

            if attempt >= retries - 1:
                raise

            time.sleep(
                1.0 * (attempt + 1)
            )

    if last_exc:
        raise last_exc

    raise RuntimeError("HTTP request failed")


def _yahoo_rate_limit_pause() -> None:
    """
    Oracle Cloud IP 對 Yahoo 連續 chart request 偶爾會出現 429。
    各 symbol 間保留至少約 0.8 秒。
    """
    global _LAST_YAHOO_CALL

    elapsed = time.monotonic() - _LAST_YAHOO_CALL
    minimum_gap = 0.80

    if elapsed < minimum_gap:
        time.sleep(
            minimum_gap - elapsed
            + random.uniform(0.05, 0.20)
        )

    _LAST_YAHOO_CALL = time.monotonic()


def fetch_yahoo_daily(symbol: str) -> dict:
    """
    Yahoo chart API，取最近 daily closes。

    防 429：
    - query1 / query2 兩個 host fallback
    - symbol 間節流
    - 429 exponential-ish retry
    - 只抓 5d daily，減少 payload
    """
    errors = []

    for host in YAHOO_CHART_HOSTS:
        _yahoo_rate_limit_pause()

        url = (
            f"{host}/v8/finance/chart/"
            + quote(symbol, safe="")
        )

        try:
            response = http_get(
                url,
                params={
                    "range": "5d",
                    "interval": "1d",
                    "includePrePost": "false",
                    "events": "div,splits",
                },
                retries=3,
            )

            payload = response.json()

            chart = payload.get("chart") or {}
            if chart.get("error"):
                raise RuntimeError(
                    f"Yahoo chart error: {chart.get('error')}"
                )

            results = chart.get("result") or []
            result = results[0] if results else None

            if not isinstance(result, dict):
                raise RuntimeError(
                    f"Yahoo chart empty: {symbol}"
                )

            timestamps = result.get("timestamp") or []

            quote_blocks = (
                result.get("indicators", {})
                .get("quote", [])
            )
            quote_block = (
                quote_blocks[0]
                if quote_blocks
                else {}
            )

            closes = (
                quote_block.get("close")
                if isinstance(quote_block, dict)
                else []
            ) or []

            points = []

            for ts, close in zip(timestamps, closes):
                c = num(close)

                if c is None:
                    continue

                dt = datetime.fromtimestamp(
                    int(ts),
                    tz=timezone.utc,
                ).astimezone(TPE)

                points.append(
                    (dt, c)
                )

            if len(points) < 2:
                raise RuntimeError(
                    f"Yahoo chart insufficient: {symbol}"
                )

            latest_dt, latest = points[-1]
            _, previous = points[-2]

            return {
                "symbol": symbol,
                "latest": latest,
                "previous": previous,
                "change_pct": pct_change(
                    latest,
                    previous,
                ),
                "as_of": latest_dt.isoformat(
                    timespec="seconds"
                ),
                "source": (
                    "yahoo_chart_"
                    + host.split("//", 1)[1]
                ),
            }

        except Exception as exc:
            errors.append(
                f"{host}: {type(exc).__name__}: {exc}"
            )

    raise RuntimeError(
        " | ".join(errors)
    )

def fetch_market_snapshot() -> dict:
    output = {}

    for key, symbol in MARKET_SYMBOLS.items():
        try:
            output[key] = fetch_yahoo_daily(symbol)
        except Exception as exc:
            output[key] = {
                "symbol": symbol,
                "error": f"{type(exc).__name__}: {exc}",
                "source": "yahoo_chart",
            }

    return output


def _html_to_text(raw_html: str) -> str:
    # 保留分隔，讓 regex 比較容易。
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", raw_html, flags=re.S | re.I)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _shioaji_ts_to_tpe(value: Any) -> str:
    """
    Shioaji snapshot ts 是 Unix ns。
    依目前專案先前已驗證的 Shioaji 時間表示法，
    將 raw ns 的鐘面轉成台灣時間。
    """
    try:
        numeric = float(value)

        if abs(numeric) >= 1e17:
            seconds = numeric / 1_000_000_000
        elif abs(numeric) >= 1e14:
            seconds = numeric / 1_000_000
        elif abs(numeric) >= 1e11:
            seconds = numeric / 1_000
        else:
            seconds = numeric

        dt = datetime.fromtimestamp(
            seconds,
            tz=timezone.utc,
        ).replace(
            tzinfo=None
        ).replace(
            tzinfo=TPE
        )

        return dt.isoformat(
            timespec="seconds"
        )

    except Exception:
        return now_tpe().isoformat(
            timespec="seconds"
        )


def fetch_taiwan_futures_shioaji() -> dict:
    """
    使用已經在 Easystock 上驗證成功的 Shioaji，
    查詢臺股期貨近月連續契約 TXFR1 的單次 Snapshot。

    這比解析 Yahoo HTML 穩定：
      api.contracts.get("TXFR1")
      api.snapshots([contract])

    08:35 只查一次，不做輪詢。
    """
    if not SJ_API_KEY or not SJ_SECRET_KEY:
        raise RuntimeError(
            "Shioaji credentials not configured"
        )

    api = sj.Shioaji()

    try:
        api.login(
            api_key=SJ_API_KEY,
            secret_key=SJ_SECRET_KEY,
        )

        contract = api.contracts.get(
            "TXFR1"
        )

        if contract is None:
            raise RuntimeError(
                "Shioaji TXFR1 contract not found"
            )

        snapshots = api.snapshots(
            [contract]
        )

        if not snapshots:
            raise RuntimeError(
                "Shioaji TXFR1 snapshot empty"
            )

        snap = snapshots[0]

        latest = num(
            getattr(
                snap,
                "close",
                None,
            )
        )

        change_price = num(
            getattr(
                snap,
                "change_price",
                None,
            )
        )

        change_rate = num(
            getattr(
                snap,
                "change_rate",
                None,
            )
        )

        if (
            latest is None
            or not (
                5000
                <= latest
                <= 100000
            )
        ):
            raise RuntimeError(
                f"Shioaji TXFR1 price invalid: {latest}"
            )

        previous = None

        if change_price is not None:
            previous = (
                latest
                -
                change_price
            )

            if not (
                5000
                <= previous
                <= 100000
            ):
                previous = None

        # Shioaji Snapshot 已提供 change_rate；
        # 若缺失才用 close / previous 自算。
        if change_rate is None:
            change_rate = pct_change(
                latest,
                previous,
            )

        code = str(
            getattr(
                snap,
                "code",
                "",
            )
            or "TXFR1"
        )

        target_code = str(
            getattr(
                contract,
                "target_code",
                "",
            )
            or code
        )

        ts = getattr(
            snap,
            "ts",
            None,
        )

        return {
            "symbol": "TXFR1",
            "resolved_symbol": (
                target_code
                or code
            ),
            "latest": latest,
            "previous": previous,
            "change_price": change_price,
            "change_pct": change_rate,
            "as_of": _shioaji_ts_to_tpe(
                ts
            ),
            "source": "sinotrade_shioaji_snapshot",
        }

    finally:
        try:
            api.logout()
        except Exception:
            pass


def fetch_taiwan_futures_yahoo() -> dict:
    """
    Yahoo 後備來源。
    僅在 Shioaji 不可用時使用。

    改用 /future/WTX& 頁面，並以欄位標籤「成交 / 昨收」解析；
    不再以任意數字位置猜價格。
    """
    url = "https://tw.stock.yahoo.com/future/WTX%26"

    response = http_get(
        url,
        retries=3,
    )

    page_text = _html_to_text(
        response.text
    )

    def labeled_price(
        label: str,
    ) -> float | None:
        patterns = [
            rf"{re.escape(label)}\s*([0-9][0-9,]*(?:\.\d+)?)",
            rf"{re.escape(label)}[^0-9]{{0,20}}([0-9][0-9,]*(?:\.\d+)?)",
        ]

        for pattern in patterns:
            match = re.search(
                pattern,
                page_text,
            )

            if not match:
                continue

            value = num(
                match.group(1).replace(
                    ",",
                    "",
                )
            )

            if (
                value is not None
                and
                5000
                <= value
                <= 100000
            ):
                return value

        return None

    latest = labeled_price(
        "成交"
    )

    previous = labeled_price(
        "昨收"
    )

    if latest is None:
        raise RuntimeError(
            "Yahoo WTX& 成交價解析失敗"
        )

    change_pct = pct_change(
        latest,
        previous,
    )

    return {
        "symbol": "WTX&",
        "latest": latest,
        "previous": previous,
        "change_pct": change_pct,
        "as_of": now_tpe().isoformat(
            timespec="seconds"
        ),
        "source": "yahoo_tw_future_fallback",
    }


def fetch_taiwan_futures() -> dict:
    """
    優先 Shioaji，失敗才 Yahoo fallback。
    """
    errors = []

    try:
        return fetch_taiwan_futures_shioaji()

    except Exception as exc:
        errors.append(
            "Shioaji: "
            f"{type(exc).__name__}: {exc}"
        )

    try:
        result = fetch_taiwan_futures_yahoo()
        result["fallback_errors"] = errors
        return result

    except Exception as exc:
        errors.append(
            "Yahoo: "
            f"{type(exc).__name__}: {exc}"
        )

    raise RuntimeError(
        " | ".join(errors)
    )

def fetch_news(limit: int = 10) -> list[dict]:
    """
    Google News RSS best-effort。
    """
    query_text = (
        "台股 OR 台積電 OR TSMC OR semiconductor "
        "OR Federal Reserve OR 美股"
    )

    params = {
        "q": query_text,
        "hl": "zh-TW",
        "gl": "TW",
        "ceid": "TW:zh-Hant",
    }

    response = http_get(
        GOOGLE_NEWS_RSS,
        params=params,
    )

    root = ET.fromstring(response.content)
    items = []

    for item in root.findall(".//item")[:limit]:
        title = (item.findtext("title") or "").strip()
        pub_date = (item.findtext("pubDate") or "").strip()
        link = (item.findtext("link") or "").strip()

        if not title:
            continue

        items.append({
            "title": title,
            "published": pub_date,
            "link": link,
        })

    return items


def signal_change(snapshot: dict, key: str) -> float | None:
    item = snapshot.get(key)
    if not isinstance(item, dict):
        return None
    return num(item.get("change_pct"))


def signal_latest(snapshot: dict, key: str) -> float | None:
    item = snapshot.get(key)
    if not isinstance(item, dict):
        return None
    return num(item.get("latest"))


def base_risk_score(snapshot: dict) -> tuple[int, list[str], list[str]]:
    """
    0 = risk-on / 100 = risk-off。
    deterministic，不讓 LLM 猜原始市場。
    """
    risk = 50.0
    supports = []
    risks = []

    def equity_component(key: str, weight: float):
        nonlocal risk
        chg = signal_change(snapshot, key)
        if chg is None:
            return

        # 正漲跌 -> risk 降；負漲跌 -> risk 升
        adjustment = -clamp(chg, -4.0, 4.0) * weight
        risk += adjustment

        name = DISPLAY_NAMES.get(key, key)
        if chg >= 0.5:
            supports.append(f"{name} {chg:+.2f}%")
        elif chg <= -0.5:
            risks.append(f"{name} {chg:+.2f}%")

    equity_component("sp500", 2.0)
    equity_component("nasdaq", 2.3)
    equity_component("sox", 3.0)
    equity_component("tsm_adr", 3.0)
    equity_component("taiwan_futures", 3.2)

    vix = signal_latest(snapshot, "vix")
    vix_chg = signal_change(snapshot, "vix")

    if vix is not None:
        if vix >= 30:
            risk += 18
            risks.append(f"VIX {vix:.1f} 高檔")
        elif vix >= 24:
            risk += 11
            risks.append(f"VIX {vix:.1f} 偏高")
        elif vix >= 20:
            risk += 5
        elif vix < 16:
            risk -= 5
            supports.append(f"VIX {vix:.1f} 低檔")

    if vix_chg is not None:
        risk += clamp(vix_chg, -15, 15) * 0.35

    usd_twd = signal_change(snapshot, "usd_twd")
    if usd_twd is not None:
        # USD/TWD 上升 = 台幣轉弱，偏 risk-off。
        risk += clamp(usd_twd, -1.5, 1.5) * 4.0
        if usd_twd >= 0.35:
            risks.append(f"台幣偏弱 USD/TWD {usd_twd:+.2f}%")
        elif usd_twd <= -0.35:
            supports.append(f"台幣偏強 USD/TWD {usd_twd:+.2f}%")

    y10 = signal_change(snapshot, "us10y")
    if y10 is not None:
        risk += clamp(y10, -3.0, 3.0) * 0.6
        if y10 >= 1.5:
            risks.append(f"10Y 殖利率指標上升 {y10:+.2f}%")

    oil = signal_change(snapshot, "oil_wti")
    if oil is not None and abs(oil) >= 3:
        risk += abs(clamp(oil, -8, 8)) * 0.35
        risks.append(f"WTI 波動 {oil:+.2f}%")

    return round(clamp(risk, 0, 100)), supports[:6], risks[:6]


def market_level_from_score(score: int) -> str:
    if score <= 35:
        return "GREEN"
    if score >= 65:
        return "RED"
    return "YELLOW"


def expected_volatility(snapshot: dict, score: int) -> str:
    vix = signal_latest(snapshot, "vix")
    fut = abs(signal_change(snapshot, "taiwan_futures") or 0)

    if (vix is not None and vix >= 26) or fut >= 1.8 or score >= 75:
        return "HIGH"
    if (vix is not None and vix >= 19) or fut >= 0.8 or score >= 55:
        return "MEDIUM"
    return "LOW"


def default_sector_bias(snapshot: dict) -> dict:
    sox = signal_change(snapshot, "sox")
    tsm = signal_change(snapshot, "tsm_adr")
    oil = signal_change(snapshot, "oil_wti")

    semi_score = (sox or 0) * 0.6 + (tsm or 0) * 0.4

    if semi_score >= 0.8:
        semi = "BULLISH"
    elif semi_score <= -0.8:
        semi = "BEARISH"
    else:
        semi = "NEUTRAL"

    if oil is not None and oil >= 2:
        energy = "BULLISH"
    elif oil is not None and oil <= -2:
        energy = "BEARISH"
    else:
        energy = "NEUTRAL"

    return {
        "semiconductor": semi,
        "electronics": semi,
        "financial": "NEUTRAL",
        "shipping": "NEUTRAL",
        "energy": energy,
    }


def compact_market_for_ai(snapshot: dict) -> dict:
    output = {}
    for key, item in snapshot.items():
        if not isinstance(item, dict):
            continue
        output[key] = {
            "name": DISPLAY_NAMES.get(key, key),
            "latest": item.get("latest"),
            "change_pct": item.get("change_pct"),
            "as_of": item.get("as_of"),
            "error": item.get("error"),
        }
    return output


def call_ai(
    snapshot: dict,
    news: list[dict],
    base_score: int,
    supports: list[str],
    risks: list[str],
) -> dict:
    """
    Gemini REST API 版本。

    原則：
    - 不使用 google-genai SDK，避免 SDK/AFC 卡住。
    - 直接呼叫已在 Oracle VM 驗證 HTTP 200 的：
        /v1beta/models/{model}:generateContent
    - 35 秒 read timeout。
    - 429 / 5xx 自動重試。
    - structured JSON response。
    - headline_risk_adjustment 嚴格限制 -5 ~ +5。
    """
    if not GEMINI_API_KEY:
        return {
            "ai_used": False,
            "provider": "gemini_rest",
            "model": GEMINI_MODEL,
            "headline_risk_adjustment": 0,
            "focus": [
            "開盤觀察台指期與權值股量價變化",
            "半導體續強但避免追價過熱標的",
            "當沖優先尋找爆量突破與 VWAP 站穩個股",
        ],
        "summary": "",
            "sector_bias": {},
            "key_risks": [],
            "key_supports": [],
            "error": "GEMINI_API_KEY not configured",
        }

    input_payload = {
        "taipei_time": now_tpe().isoformat(timespec="seconds"),
        "market_data": compact_market_for_ai(snapshot),
        "base_risk_score": base_score,
        "deterministic_supports": supports,
        "deterministic_risks": risks,
        "headlines": [
            {
                "title": x.get("title"),
                "published": x.get("published"),
            }
            for x in news[:10]
        ],
    }

    system_prompt = """
你是台灣股票「開盤前風險判讀」分析器。

你收到的市場數值已由程式取得，禁止改寫、臆測或捏造任何價格與漲跌幅。

任務：
1. 只根據提供的 market_data 與 headlines 做判讀。
2. headline_risk_adjustment 必須是 -5 到 +5 的整數。
   正值代表新聞讓風險升高，負值代表新聞讓風險下降。
3. summary 使用繁體中文，約100~220字，給台股短線/當沖使用。
4. focus 產生 3 項「今日重點」，每項使用簡短繁體中文。
   重點優先包含盤勢、強弱族群/權值股、當沖執行注意事項。
5. sector_bias 只能使用 BULLISH / NEUTRAL / BEARISH。
6. key_risks、key_supports 各最多4項，使用短句。
7. 資料缺失時明確降低信心，不可自行補造。
8. 不可提供保證獲利或確定性預測。
9. 只回傳符合指定 schema 的 JSON。
""".strip()

    response_schema = {
        "type": "object",
        "properties": {
            "headline_risk_adjustment": {
                "type": "integer",
                "description": "新聞風險調整，只能 -5 到 +5。",
            },
            "summary": {
                "type": "string",
                "description": "繁體中文盤前市場摘要。",
            },
            "focus": {
                "type": "array",
                "items": {"type": "string"},
                "description": "今日重點，回傳3項簡短繁體中文重點。",
            },
            "sector_bias": {
                "type": "object",
                "properties": {
                    "semiconductor": {
                        "type": "string",
                        "enum": ["BULLISH", "NEUTRAL", "BEARISH"],
                    },
                    "electronics": {
                        "type": "string",
                        "enum": ["BULLISH", "NEUTRAL", "BEARISH"],
                    },
                    "financial": {
                        "type": "string",
                        "enum": ["BULLISH", "NEUTRAL", "BEARISH"],
                    },
                    "shipping": {
                        "type": "string",
                        "enum": ["BULLISH", "NEUTRAL", "BEARISH"],
                    },
                    "energy": {
                        "type": "string",
                        "enum": ["BULLISH", "NEUTRAL", "BEARISH"],
                    },
                },
                "required": [
                    "semiconductor",
                    "electronics",
                    "financial",
                    "shipping",
                    "energy",
                ],
            },
            "key_risks": {
                "type": "array",
                "items": {"type": "string"},
            },
            "key_supports": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": [
            "headline_risk_adjustment",
            "summary",
            "focus",
            "sector_bias",
            "key_risks",
            "key_supports",
        ],
    }

    url = (
        "https://generativelanguage.googleapis.com/"
        f"v1beta/models/{GEMINI_MODEL}:generateContent"
    )

    request_body = {
        "systemInstruction": {
            "parts": [
                {
                    "text": system_prompt,
                }
            ]
        },
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "text": json.dumps(
                            input_payload,
                            ensure_ascii=False,
                        ),
                    }
                ],
            }
        ],
        "generationConfig": {
            "thinkingConfig": {
                "thinkingLevel": "low",
            },
            "responseMimeType": "application/json",
            "responseJsonSchema": response_schema,
        },
    }

    last_error = None

    for attempt in range(3):
        try:
            response = requests.post(
                url,
                headers={
                    "x-goog-api-key": GEMINI_API_KEY,
                    "Content-Type": "application/json",
                },
                json=request_body,
                timeout=(10, 35),
            )

            if response.status_code == 429:
                wait = 2.0 * (attempt + 1)
                last_error = (
                    f"Gemini HTTP 429: {response.text[:500]}"
                )

                if attempt < 2:
                    print(
                        f"[WARN] Gemini 429，{wait:.0f}s 後重試..."
                    )
                    time.sleep(wait)
                    continue

            if response.status_code >= 500:
                wait = 2.0 * (attempt + 1)
                last_error = (
                    f"Gemini HTTP {response.status_code}: "
                    f"{response.text[:500]}"
                )

                if attempt < 2:
                    print(
                        f"[WARN] Gemini {response.status_code}，"
                        f"{wait:.0f}s 後重試..."
                    )
                    time.sleep(wait)
                    continue

            response.raise_for_status()

            payload = response.json()

            candidates = payload.get(
                "candidates"
            ) or []

            if not candidates:
                raise RuntimeError(
                    "Gemini response has no candidates"
                )

            parts = (
                candidates[0]
                .get("content", {})
                .get("parts", [])
            )

            text_parts = []

            for part in parts:
                if not isinstance(part, dict):
                    continue

                part_text = part.get("text")

                if part_text:
                    text_parts.append(
                        str(part_text)
                    )

            raw = "\n".join(
                text_parts
            ).strip()

            if not raw:
                raise RuntimeError(
                    "Gemini returned empty text"
                )

            raw = re.sub(
                r"^```(?:json)?\s*",
                "",
                raw,
                flags=re.I,
            )

            raw = re.sub(
                r"\s*```$",
                "",
                raw,
            )

            data = json.loads(
                raw
            )

            adjustment = int(
                round(
                    num(
                        data.get(
                            "headline_risk_adjustment"
                        )
                    )
                    or 0
                )
            )

            adjustment = int(
                clamp(
                    adjustment,
                    -5,
                    5,
                )
            )

            sector = data.get(
                "sector_bias"
            )

            if not isinstance(
                sector,
                dict,
            ):
                sector = {}

            allowed = {
                "BULLISH",
                "NEUTRAL",
                "BEARISH",
            }

            clean_sector = {}

            for key in (
                "semiconductor",
                "electronics",
                "financial",
                "shipping",
                "energy",
            ):
                value = str(
                    sector.get(key)
                    or "NEUTRAL"
                ).upper()

                clean_sector[key] = (
                    value
                    if value in allowed
                    else "NEUTRAL"
                )

            summary = str(
                data.get("summary")
                or ""
            ).strip()

            if not summary:
                raise RuntimeError(
                    "Gemini summary empty"
                )

            return {
                "ai_used": True,
                "provider": "gemini_rest",
                "model": GEMINI_MODEL,
                "headline_risk_adjustment": adjustment,
                "summary": summary,
                "focus": [
                    str(x).strip()
                    for x in (data.get("focus") or [])
                    if str(x).strip()
                ][:3],
                "sector_bias": clean_sector,
                "key_risks": [
                    str(x)
                    for x in (
                        data.get("key_risks")
                        or []
                    )[:4]
                ],
                "key_supports": [
                    str(x)
                    for x in (
                        data.get("key_supports")
                        or []
                    )[:4]
                ],
            }

        except (
            requests.Timeout,
            requests.ConnectionError,
        ) as exc:
            last_error = (
                f"{type(exc).__name__}: {exc}"
            )

            if attempt < 2:
                print(
                    "[WARN] Gemini REST timeout/network error，"
                    "2s 後重試..."
                )
                time.sleep(2)
                continue

        except Exception as exc:
            last_error = (
                f"{type(exc).__name__}: {exc}"
            )
            break

    return {
        "ai_used": False,
        "provider": "gemini_rest",
        "model": GEMINI_MODEL,
        "headline_risk_adjustment": 0,
        "summary": "",
        "sector_bias": {},
        "key_risks": [],
        "key_supports": [],
        "error": last_error or "Gemini REST unknown error",
    }

def build_fallback_summary(
    score: int,
    level: str,
    volatility: str,
    supports: list[str],
    risks: list[str],
) -> str:
    support_text = "、".join(supports[:3]) if supports else "暫無明顯外部多方訊號"
    risk_text = "、".join(risks[:3]) if risks else "外部風險暫無明顯擴大"

    return (
        f"盤前風險分數 {score}/100，市場燈號 {level}，"
        f"預期波動 {volatility}。"
        f"支撐面：{support_text}；"
        f"風險面：{risk_text}。"
        "當沖仍以開盤後量價、VWAP 與5分K確認為準。"
    )


def build_brief() -> dict:
    snapshot = fetch_market_snapshot()

    try:
        snapshot["taiwan_futures"] = fetch_taiwan_futures()
    except Exception as exc:
        snapshot["taiwan_futures"] = {
            "symbol": "WTX&",
            "source": "yahoo_tw_future",
            "error": f"{type(exc).__name__}: {exc}",
        }

    try:
        news = fetch_news(limit=10)
    except Exception as exc:
        news = [{
            "title": f"新聞來源暫時不可用：{type(exc).__name__}",
            "published": "",
            "link": "",
        }]

    base_score, deterministic_supports, deterministic_risks = (
        base_risk_score(snapshot)
    )

    ai = call_ai(
        snapshot=snapshot,
        news=news,
        base_score=base_score,
        supports=deterministic_supports,
        risks=deterministic_risks,
    )

    adjustment = int(
        clamp(
            num(ai.get("headline_risk_adjustment")) or 0,
            -5,
            5,
        )
    )

    final_score = int(
        round(
            clamp(
                base_score + adjustment,
                0,
                100,
            )
        )
    )

    level = market_level_from_score(final_score)
    volatility = expected_volatility(snapshot, final_score)

    sector = default_sector_bias(snapshot)
    if ai.get("ai_used") and isinstance(ai.get("sector_bias"), dict):
        sector.update(ai["sector_bias"])

    supports = list(deterministic_supports)
    risks = list(deterministic_risks)

    if ai.get("ai_used"):
        supports.extend(ai.get("key_supports") or [])
        risks.extend(ai.get("key_risks") or [])

    summary = str(ai.get("summary") or "").strip()
    if not summary:
        summary = build_fallback_summary(
            score=final_score,
            level=level,
            volatility=volatility,
            supports=supports,
            risks=risks,
        )

    now = now_tpe()

    return {
        "version": "premarket_ai_v1",
        "source": "public_market_data_plus_ai",
        "generated_at": now.isoformat(timespec="seconds"),
        "scan_date": now.date().isoformat(),
        "risk_score": final_score,
        "base_risk_score": base_score,
        "headline_risk_adjustment": adjustment,
        "market_level": level,
        "expected_volatility": volatility,
        "sector_bias": sector,
        "summary": summary,
        "focus": (
            list(ai.get("focus") or [])[:3]
            or (
                ([f"支撐：{supports[0]}"] if supports else [])
                +
                ([f"風險：{risks[0]}"] if risks else [])
            )
            or ["開盤觀察權值股與盤中量價變化"]
        ),
        "key_supports": supports[:6],
        "key_risks": risks[:6],
        "market_data": snapshot,
        "news": news[:10],
        "ai": {
            "used": bool(ai.get("ai_used")),
            "provider": ai.get("provider") or "gemini_rest",
            "model": ai.get("model"),
            "error": ai.get("error"),
        },
        "website_url": WEBSITE_URL,
    }


def write_firebase(brief: dict) -> None:
    # FirebaseStore() 負責初始化 firebase_admin。
    FirebaseStore()

    db.reference(
        "/market_data/premarket_brief"
    ).set(brief)


def format_number(value: Any, digits: int = 2) -> str:
    x = num(value)
    if x is None:
        return "--"
    return f"{x:,.{digits}f}"


def market_line(brief: dict, key: str) -> str:
    item = (
        brief.get("market_data", {})
        .get(key, {})
    )

    if not isinstance(item, dict):
        return f"{DISPLAY_NAMES.get(key, key)}：--"

    latest = num(item.get("latest"))
    chg = num(item.get("change_pct"))

    if latest is None:
        return f"{DISPLAY_NAMES.get(key, key)}：資料缺失"

    if chg is None:
        return f"{DISPLAY_NAMES.get(key, key)}：{format_number(latest)}"

    return (
        f"{DISPLAY_NAMES.get(key, key)}："
        f"{format_number(latest)} ({chg:+.2f}%)"
    )


def format_line_message(brief: dict) -> str:
    level_icon = {
        "GREEN": "🟢",
        "YELLOW": "🟡",
        "RED": "🔴",
    }.get(brief.get("market_level"), "⚪")

    sector = brief.get("sector_bias") or {}

    lines = [
        "🤖 墨衡量化｜AI 開盤前市場通報",
        f"{brief.get('scan_date')} 08:35",
        "",
        (
            f"{level_icon} 市場燈號：{brief.get('market_level')} "
            f"｜風險 {brief.get('risk_score')}/100 "
            f"｜波動 {brief.get('expected_volatility')}"
        ),
        "",
        market_line(brief, "sp500"),
        market_line(brief, "nasdaq"),
        market_line(brief, "sox"),
        market_line(brief, "tsm_adr"),
        market_line(brief, "taiwan_futures"),
        market_line(brief, "vix"),
        market_line(brief, "usd_twd"),
        market_line(brief, "us10y"),
        market_line(brief, "oil_wti"),
        "",
        (
            "半導體："
            f"{sector.get('semiconductor', 'NEUTRAL')} "
            "｜電子："
            f"{sector.get('electronics', 'NEUTRAL')}"
        ),
        "",
        str(brief.get("summary") or ""),
        "",
        WEBSITE_URL,
    ]

    return "\n".join(lines)


def push_line_text(text: str) -> bool:

    groups = get_active_groups()

    if groups:
        ok = False

        for gid in groups:
            try:
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

    # 先相容既有 line_bot.py
    try:
        import inspect
        import line_bot

        for name in (
            "push_message",
            "push_text",
            "send_message",
            "send_line_message",
            "line_push",
            "push_line_message",
        ):
            fn = getattr(line_bot, name, None)
            if not callable(fn):
                continue

            try:
                params = list(inspect.signature(fn).parameters.values())

                if len(params) == 1:
                    result = fn(text)
                    return result is not False

                if len(params) >= 2:
                    result = fn(LINE_TARGET_ID, text)
                    return result is not False
            except Exception:
                continue

    except Exception:
        pass

    # fallback LINE HTTP
    if not LINE_TOKEN or not LINE_TARGET_ID:
        print("[WARN] LINE token/target not configured")
        return False

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
        timeout=HTTP_TIMEOUT,
    )

    print(f"[LINE] status={response.status_code}")
    return response.status_code == 200


def print_brief(brief: dict) -> None:
    print("======================================")
    print("Easystock AI Premarket Brief")
    print("======================================")
    print(f"scan_date: {brief.get('scan_date')}")
    print(f"risk_score: {brief.get('risk_score')}")
    print(f"base_risk_score: {brief.get('base_risk_score')}")
    print(f"headline adjustment: {brief.get('headline_risk_adjustment')}")
    print(f"market_level: {brief.get('market_level')}")
    print(f"expected_volatility: {brief.get('expected_volatility')}")
    print(f"AI used: {brief.get('ai', {}).get('used')}")
    print(
        "AI provider:",
        brief.get("ai", {}).get("provider")
    )
    print(
        "AI model:",
        brief.get("ai", {}).get("model")
    )

    if brief.get("ai", {}).get("error"):
        print(f"AI error: {brief['ai']['error']}")
    print()
    print(brief.get("summary"))
    print()
    print("Market data:")
    for key in MARKET_SYMBOLS:
        print(" -", market_line(brief, key))

        item = (
            brief.get("market_data", {})
            .get(key, {})
        )

        if (
            isinstance(item, dict)
            and item.get("error")
        ):
            print(
                "   ERROR:",
                item.get("error")
            )

    print(
        " -",
        market_line(
            brief,
            "taiwan_futures",
        )
    )

    fut_item = (
        brief.get("market_data", {})
        .get("taiwan_futures", {})
    )

    if (
        isinstance(fut_item, dict)
        and fut_item.get("error")
    ):
        print(
            "   ERROR:",
            fut_item.get("error")
        )


def main() -> None:
    no_line = "--no-line" in sys.argv
    no_firebase = "--no-firebase" in sys.argv

    brief = build_brief()
    print_brief(brief)

    if not no_firebase:
        write_firebase(brief)
        print("✅ Firebase /market_data/premarket_brief updated")

    if not no_line:
        ok = push_line_text(format_line_message(brief))
        print("✅ LINE sent" if ok else "⚠️ LINE not sent")

    print("✅ Premarket brief complete")


if __name__ == "__main__":
    main()
