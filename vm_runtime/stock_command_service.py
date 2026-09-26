#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Easystock LINE stock command service V4.3.4 ETF

Commands:
P台積電 / P2330
K台積電 / K2330
T台積電 / T2330
D台積電 / D2330
#台積電 / #2330
#大盤
台積電大盤 / 2330大盤  -> same as P台積電 / P2330
指令

Data:
- 即時個股 / 大盤: Shioaji snapshot
- P 當日走勢: Shioaji Kbars
- K 日K: FinMind TaiwanStockPrice (90 calendar days)
- T 三大法人: FinMind TaiwanStockInstitutionalInvestorsBuySellWide
- D 股利: FinMind TaiwanStockDividend
- D 殖利率: TWSE / TPEx official OpenAPI, fallback calculated
- 股票名稱模糊解析: TWSE + TPEx official OpenAPI stock catalogs
- ETF 名稱/代碼解析: FinMind TaiwanStockInfo + Shioaji contract fallback
"""

from __future__ import annotations

import base64
import difflib
import hashlib
import json
import math
import os
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, time as dtime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

from line_card_renderer import (
    render_stock_intraday_card,
    render_market_intraday_card,
    render_k_card,
    render_institutional_card,
    render_stock_sparkline,
    render_market_sparkline,
)

TPE = timezone(timedelta(hours=8))
HTTP = requests.Session()
HTTP.headers.update({
    "User-Agent": "EasystockLineBot/1.0",
    "Accept": "application/json,text/plain,*/*",
})

FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"
TWSE_CATALOG = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
TPEX_CATALOG = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"
TWSE_YIELD = "https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL"
TPEX_YIELD = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_peratio_analysis"

CHART_DIR = Path(
    os.environ.get(
        "LINE_CHART_DIR",
        str(Path(__file__).resolve().parent / "line_charts"),
    )
)
CHART_DIR.mkdir(parents=True, exist_ok=True)

FINMIND_TOKEN = os.environ.get("FINMIND_TOKEN", "").strip()
PUBLIC_BASE_URL = os.environ.get(
    "LINE_BOT_PUBLIC_BASE_URL",
    "",
).rstrip("/")

EASYSTOCK_WEB_URL = os.environ.get(
    "EASYSTOCK_WEB_URL",
    "https://jimmyeyes03160729.github.io/easystock/",
).strip()

CATALOG_TTL = 6 * 3600
DATA_TIMEOUT = 20

# 台灣一般股票多為 4 碼；ETF 常見 4~6 碼，主動式/外幣 ETF
# 亦可能是 5 碼數字 + 1 個英文字母（例如 00980A）。
SECURITY_CODE_RE = re.compile(r"^(?:\d{4,6}|\d{5}[A-Z])$", re.I)

BARE_SECURITY_CODE_RE = re.compile(
    r"^(?:\d{4}|00\d{3,4}|00\d{3}[A-Z])$",
    re.I,
)



def now_tpe() -> datetime:
    return datetime.now(TPE)


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if isinstance(value, str):
            value = value.replace(",", "").replace("%", "").strip()
            if value in {"", "--", "-", "N/A", "nan", "None"}:
                return None
        return float(value)
    except Exception:
        return None


def _pick(row: dict, *keys: str) -> Any:
    for key in keys:
        if key in row and row.get(key) not in (None, ""):
            return row.get(key)
    return None


def _format_price(v: float | None) -> str:
    if v is None:
        return "--"
    if abs(v) >= 1000:
        return f"{v:,.2f}"
    if abs(v) >= 100:
        return f"{v:.2f}"
    return f"{v:.2f}"


def _format_int(v: float | None) -> str:
    if v is None:
        return "--"
    return f"{int(round(v)):,}"


def _normalize_name(text: str) -> str:
    s = str(text or "").strip().upper()
    s = s.replace(" ", "")
    s = s.replace("－", "-").replace("–", "-").replace("—", "-")
    s = s.replace("＊", "*")
    return s


def _alias_name(text: str) -> str:
    """
    用於模糊比對。
    材料-KY -> 材料
    材料-KY* -> 材料
    """
    s = _normalize_name(text)
    # 材料-KY / 材料*-KY / 材料-KY* 都視為「材料」。
    s = re.sub(r"\*?-KY\*?$", "", s)
    s = re.sub(r"-DR$", "", s)
    s = re.sub(r"\*+$", "", s)
    s = re.sub(r"[\(\)（）]", "", s)
    return s


@dataclass
class ParsedCommand:
    kind: str
    query: str = ""
    raw: str = ""


HELP_TEXT = """📌 當沖吧！牛馬仔｜EasyStock LINE Hub

【自動通知】
已關閉所有早報與盤中逐筆即時通知。
每日僅保留一則自動推播：
• 13:30 當沖結盤總結（今日買進部位、各別損益 %、總勝率）

【快速查價】
#台積電 / #2330 / 台積電股價 / 2330
00878 / #00878 / 006208 / #0050
#大盤 / 大盤

【即時圖卡 P】
P台積電 / P2330 / P0050 / P00878 / P元大台灣50 / P大盤

【K線 K】
K台積電 / K2330 / K0050 / K00878 / K大盤

【三大法人 T】
T台積電 / 台積電三大法人 / T0050 / T00878 / T大盤 / 三大法人

【股利 D】
D台積電 / D2330
ETF 配息目前不混用公司股利資料

【系統查詢】
早報 / 早上快報 → 最新 AI 早報
當沖 / 當沖狀態 → 13:30 當沖結盤與部位
通知 / 通知內容 → 自動通知規則說明
更新 / 更新內容 → 機器人更新內容

支援模糊名稱：#材料、P元大台灣50
輸入「指令」可再次查看本說明。"""


def parse_command(text: str) -> ParsedCommand | None:
    raw = str(text or "").strip()
    if not raw:
        return None

    compact = re.sub(r"\s+", "", raw)
    upper = compact.upper()

    if compact in {"指令", "幫助", "HELP", "help", "?"}:
        return ParsedCommand("HELP", raw=raw)

    if compact in {"更新", "更新內容", "版本", "版本更新"}:
        return ParsedCommand("UPDATE", raw=raw)

    if compact in {"早報", "早上快報", "開盤快報", "AI早報"}:
        return ParsedCommand("PREMARKET", raw=raw)

    if compact in {"當沖", "當沖狀態", "盤中狀態", "量能雷達"}:
        return ParsedCommand("DAYTRADE", raw=raw)

    if compact in {"通知", "通知內容", "通知說明"}:
        return ParsedCommand("NOTIFY_INFO", raw=raw)

    if BARE_SECURITY_CODE_RE.fullmatch(upper):
        return ParsedCommand("STOCK_TEXT", upper, raw)

    # 「大盤」是特殊市場關鍵字，不交給個股名稱解析。
    if compact in {"#大盤", "大盤"}:
        return ParsedCommand("MARKET_TEXT", "大盤", raw)

    # 整體市場三大法人。
    if compact in {"三大法人", "T大盤", "t大盤", "大盤三大法人"}:
        return ParsedCommand("T", "大盤", raw)

    # 大盤 K 線。
    if compact in {"K大盤", "k大盤", "大盤K線", "大盤K線圖", "大盤K"}:
        return ParsedCommand("K", "大盤", raw)

    if compact.startswith("#") and len(compact) > 1:
        return ParsedCommand("STOCK_TEXT", compact[1:], raw)

    # 直覺文字：台積電股價 / 2330股價 = #台積電 / #2330
    if compact.endswith("股價") and len(compact) > 2:
        query = compact[:-2]
        if query and query != "大盤":
            return ParsedCommand("STOCK_TEXT", query, raw)

    # 也順便支援：股價台積電 / 股價2330
    if compact.startswith("股價") and len(compact) > 2:
        query = compact[2:]
        if query and query != "大盤":
            return ParsedCommand("STOCK_TEXT", query, raw)

    # 直覺文字：台積電三大法人 / 2330三大法人 = T台積電 / T2330
    if compact.endswith("三大法人") and len(compact) > 4:
        query = compact[:-4]
        if query:
            return ParsedCommand("T", query, raw)

    # 也支援：三大法人台積電 / 三大法人2330
    if compact.startswith("三大法人") and len(compact) > 4:
        query = compact[4:]
        if query:
            return ParsedCommand("T", query, raw)

    if upper[0:1] in {"P", "K", "T", "D"} and len(compact) > 1:
        kind = upper[0]
        return ParsedCommand(kind, compact[1:], raw)

    # 舊凱衛相容：台積電大盤 = P台積電
    # 注意：單獨「大盤」不走這裡，大盤永遠代表市場。
    if compact.endswith("大盤") and compact != "大盤":
        query = compact[:-2]
        if query:
            return ParsedCommand("P", query, raw)

    # 普通群組聊天不要亂回。
    return None


class StockResolver:
    def __init__(self):
        self._rows: list[dict] = []
        self._last_refresh = 0.0
        self._lock = threading.Lock()

    def _fetch_json(self, url: str) -> list[dict]:
        r = HTTP.get(url, timeout=DATA_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        if isinstance(data, dict):
            # Some APIs wrap rows.
            for key in ("data", "aaData", "rows"):
                value = data.get(key)
                if isinstance(value, list):
                    return [x for x in value if isinstance(x, dict)]
        return []

    def _finmind_etf_rows(self) -> list[dict]:
        """Load Taiwan-listed ETF names/codes from FinMind TaiwanStockInfo.

        TaiwanStockInfo includes both TWSE and TPEx ETFs. We only merge rows
        whose industry_category is ETF so the existing official company
        catalogs remain the primary source for ordinary stocks.
        """
        params = {"dataset": "TaiwanStockInfo"}
        headers = {}
        if FINMIND_TOKEN:
            headers["Authorization"] = f"Bearer {FINMIND_TOKEN}"

        try:
            r = HTTP.get(
                FINMIND_URL,
                params=params,
                headers=headers,
                timeout=DATA_TIMEOUT,
            )
            r.raise_for_status()
            payload = r.json()
        except Exception:
            return []

        source = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(source, list):
            return []

        # Same stock_id may have multiple historical market rows.
        # Keep the newest one.
        newest: dict[str, dict] = {}
        for item in source:
            if not isinstance(item, dict):
                continue

            category = str(item.get("industry_category") or "").strip().upper()
            if category != "ETF":
                continue

            code = str(item.get("stock_id") or "").strip().upper()
            name = str(item.get("stock_name") or "").strip()
            market_raw = str(item.get("type") or "").strip().lower()
            date = str(item.get("date") or "")

            if not SECURITY_CODE_RE.fullmatch(code):
                continue
            if not name:
                continue

            market = {
                "twse": "TSE",
                "tpex": "OTC",
            }.get(market_raw, market_raw.upper())

            row = {
                "code": code,
                "name": name,
                "market": market,
                "asset_type": "ETF",
                "name_norm": _normalize_name(name),
                "alias_norm": _alias_name(name),
                "_date": date,
            }

            prior = newest.get(code)
            if prior is None or date >= str(prior.get("_date") or ""):
                newest[code] = row

        result = []
        for row in newest.values():
            row.pop("_date", None)
            result.append(row)
        return result

    def refresh(self, force: bool = False) -> None:
        with self._lock:
            if (
                not force
                and self._rows
                and time.time() - self._last_refresh < CATALOG_TTL
            ):
                return

            rows: list[dict] = []

            for market, url in (
                ("TSE", TWSE_CATALOG),
                ("OTC", TPEX_CATALOG),
            ):
                try:
                    source = self._fetch_json(url)
                except Exception:
                    source = []

                for item in source:
                    code = str(
                        _pick(
                            item,
                            "公司代號",
                            "SecuritiesCompanyCode",
                            "股票代號",
                            "Code",
                            "code",
                        )
                        or ""
                    ).strip()

                    name = str(
                        _pick(
                            item,
                            "公司簡稱",
                            "CompanyName",
                            "公司名稱",
                            "股票名稱",
                            "Name",
                            "name",
                        )
                        or ""
                    ).strip()

                    if not re.fullmatch(r"\d{4}", code):
                        continue
                    if not name:
                        continue

                    rows.append({
                        "code": code,
                        "name": name,
                        "market": market,
                        "asset_type": "STOCK",
                        "name_norm": _normalize_name(name),
                        "alias_norm": _alias_name(name),
                    })

            # 補入 ETF；FinMind TaiwanStockInfo 同時涵蓋 TWSE / TPEx ETF。
            try:
                rows.extend(self._finmind_etf_rows())
            except Exception:
                pass

            # 防重複，上市優先。
            dedup: dict[str, dict] = {}
            for row in rows:
                dedup.setdefault(row["code"], row)

            self._rows = list(dedup.values())
            self._last_refresh = time.time()

    def resolve(self, query: str) -> tuple[dict | None, list[dict]]:
        q = _normalize_name(query)
        qa = _alias_name(query)

        # 代碼優先。
        if SECURITY_CODE_RE.fullmatch(q):
            self.refresh()
            for row in self._rows:
                if row["code"] == q:
                    return row, []

            # 即使 catalog 暫時失敗，代碼仍可交給 Shioaji。
            return {
                "code": q,
                "name": q,
                "market": "",
                "asset_type": "UNKNOWN",
                "name_norm": q,
                "alias_norm": q,
            }, []

        self.refresh()

        scored: list[tuple[float, dict]] = []

        for row in self._rows:
            name = row["name_norm"]
            alias = row["alias_norm"]

            score = 0.0

            if q == name:
                score = 100.0
            elif qa == alias:
                score = 99.0
            elif name.startswith(q) or alias.startswith(qa):
                score = 92.0
            elif q in name or qa in alias:
                score = 87.0
            else:
                ratio = max(
                    difflib.SequenceMatcher(None, q, name).ratio(),
                    difflib.SequenceMatcher(None, qa, alias).ratio(),
                )
                if ratio >= 0.72:
                    score = ratio * 80.0

            if score > 0:
                scored.append((score, row))

        if not scored:
            return None, []

        scored.sort(
            key=lambda x: (x[0], len(x[1]["name"])),
            reverse=True,
        )

        best_score, best = scored[0]

        # 如果前幾名太接近，不自行猜，回選項。
        ambiguous = [
            row
            for score, row in scored[:5]
            if best_score - score <= 2.0
            and row["code"] != best["code"]
        ]

        if ambiguous and best_score < 99.0:
            return None, [best] + ambiguous[:4]

        return best, []


class ShioajiQuery:
    def __init__(self):
        self._api = None
        self._lock = threading.RLock()
        self._last_login = 0.0

    def api(self):
        with self._lock:
            if self._api is not None:
                return self._api

            import shioaji as sj

            key = os.environ.get("SJ_API_KEY", "").strip()
            secret = os.environ.get("SJ_SECRET_KEY", "").strip()
            if not key or not secret:
                raise RuntimeError("SJ_API_KEY / SJ_SECRET_KEY 未設定")

            api = sj.Shioaji()
            api.login(api_key=key, secret_key=secret)
            self._api = api
            self._last_login = time.time()
            return self._api

    def contract(self, code: str):
        api = self.api()
        c = api.contracts.get(str(code))
        if c is None:
            raise LookupError(f"查無商品：{code}")
        return c

    def stock_info(self, code: str) -> dict:
        api = self.api()
        c = self.contract(code)
        info = api.contracts.info(c)
        return {
            "contract": c,
            "code": str(getattr(info, "code", code)),
            "name": str(getattr(info, "name", code)),
            "exchange": str(getattr(c, "exchange", "")),
            "reference": _num(getattr(info, "reference", None)),
        }

    def snapshot(self, code: str) -> dict:
        api = self.api()
        info = self.stock_info(code)
        snaps = api.snapshots([info["contract"]])
        if not snaps:
            raise RuntimeError(f"{code} Snapshot 無資料")
        s = snaps[0]

        close = _num(getattr(s, "close", None))
        change = _num(getattr(s, "change_price", None))
        rate = _num(getattr(s, "change_rate", None))
        ref = info["reference"]

        if rate is None and close is not None and ref not in (None, 0):
            rate = (close / ref - 1.0) * 100.0

        return {
            "code": info["code"],
            "name": info["name"],
            "exchange": info["exchange"],
            "ts": getattr(s, "ts", None),
            "open": _num(getattr(s, "open", None)),
            "high": _num(getattr(s, "high", None)),
            "low": _num(getattr(s, "low", None)),
            "close": close,
            "change_price": change,
            "change_rate": rate,
            "average_price": _num(getattr(s, "average_price", None)),
            "volume": _num(getattr(s, "volume", None)),
            "total_volume": _num(getattr(s, "total_volume", None)),
            "total_amount": _num(getattr(s, "total_amount", None)),
            "buy_price": _num(getattr(s, "buy_price", None)),
            "sell_price": _num(getattr(s, "sell_price", None)),
            "reference": ref,
        }

    def market_snapshot(self) -> dict:
        api = self.api()
        c = api.contracts.get("IX0001")
        if c is None:
            raise RuntimeError("查無加權指數 IX0001")
        info = api.contracts.info(c)
        snaps = api.snapshots([c])
        if not snaps:
            raise RuntimeError("大盤 Snapshot 無資料")
        s = snaps[0]
        close = _num(getattr(s, "close", None))
        ref = _num(getattr(info, "reference", None))
        change = _num(getattr(s, "change_price", None))
        rate = _num(getattr(s, "change_rate", None))
        if change is None and close is not None and ref is not None:
            change = close - ref
        if rate is None and close is not None and ref not in (None, 0):
            rate = (close / ref - 1) * 100
        return {
            "code": "IX0001",
            "name": str(getattr(info, "name", "發行量加權股價指數")),
            "ts": getattr(s, "ts", None),
            "close": close,
            "reference": ref,
            "change_price": change,
            "change_rate": rate,
            "open": _num(getattr(s, "open", None)),
            "high": _num(getattr(s, "high", None)),
            "low": _num(getattr(s, "low", None)),
            "total_volume": _num(getattr(s, "total_volume", None)),
            "total_amount": _num(getattr(s, "total_amount", None)),
        }

    @staticmethod
    def _seq(value) -> list:
        """Safely convert Shioaji list/array-like fields to Python lists."""
        if value is None:
            return []
        try:
            return list(value)
        except Exception:
            return []

    @staticmethod
    def _historical_dt(raw, *, kbar: bool) -> datetime:
        """Decode Shioaji historical timestamps using Easystock's tested convention."""
        if isinstance(raw, datetime):
            dt = raw
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=TPE)
            else:
                dt = dt.astimezone(TPE)
            return dt - timedelta(minutes=1) if kbar else dt
        try:
            sec = float(raw) / 1_000_000_000.0
            dt = datetime.fromtimestamp(sec, tz=timezone.utc).replace(tzinfo=TPE)
            return dt - timedelta(minutes=1) if kbar else dt
        except Exception:
            return now_tpe()

    def _kbar_rows_for_date(self, code: str, date_text: str) -> list[dict]:
        api = self.api()
        c = self.contract(code)
        k = api.kbars(c, start=date_text, end=date_text)
        ts = self._seq(getattr(k, "ts", None))
        opens = self._seq(getattr(k, "Open", None))
        highs = self._seq(getattr(k, "High", None))
        lows = self._seq(getattr(k, "Low", None))
        closes = self._seq(getattr(k, "Close", None))
        volumes = self._seq(getattr(k, "Volume", None))
        rows: list[dict] = []
        n = min(len(ts), len(closes))
        for i in range(n):
            dt = self._historical_dt(ts[i], kbar=True)
            clock = dt.timetz().replace(tzinfo=None)
            if not (dtime(8, 59) <= clock <= dtime(13, 35)):
                continue
            rows.append({
                "time": dt,
                "open": _num(opens[i]) if i < len(opens) else None,
                "high": _num(highs[i]) if i < len(highs) else None,
                "low": _num(lows[i]) if i < len(lows) else None,
                "close": _num(closes[i]),
                "volume": _num(volumes[i]) if i < len(volumes) else 0.0,
            })
        return rows

    def _tick_rows_for_date(self, code: str, date_text: str) -> list[dict]:
        """After-close fallback: aggregate all-day historical ticks to 1-minute OHLCV."""
        api = self.api()
        c = self.contract(code)
        import shioaji as sj
        ticks = api.ticks(
            c,
            date=date_text,
            query_type=sj.constant.TicksQueryType.AllDay,
        )
        ts = self._seq(getattr(ticks, "ts", None))
        closes = self._seq(getattr(ticks, "close", None))
        volumes = self._seq(getattr(ticks, "volume", None))
        buckets: dict[datetime, dict] = {}
        n = min(len(ts), len(closes))
        for i in range(n):
            price = _num(closes[i])
            if price is None:
                continue
            dt = self._historical_dt(ts[i], kbar=False)
            clock = dt.timetz().replace(tzinfo=None)
            if not (dtime(9, 0) <= clock <= dtime(13, 35)):
                continue
            minute = dt.replace(second=0, microsecond=0)
            vol = (_num(volumes[i]) if i < len(volumes) else 0.0) or 0.0
            bar = buckets.get(minute)
            if bar is None:
                buckets[minute] = {
                    "time": minute,
                    "open": price,
                    "high": price,
                    "low": price,
                    "close": price,
                    "volume": vol,
                }
            else:
                bar["high"] = max(float(bar["high"]), price)
                bar["low"] = min(float(bar["low"]), price)
                bar["close"] = price
                bar["volume"] = float(bar.get("volume") or 0.0) + vol
        return [buckets[k] for k in sorted(buckets)]

    def intraday_rows(self, code: str) -> list[dict]:
        """
        Return the intraday curve that should be shown now.

        - During/after today's session: use today's data.
        - After close: use historical ticks as fallback when Kbars are incomplete.
        - Before open / weekends / holidays: automatically find the most recent
          date with actual market data (up to 10 calendar days back).
        """
        now = now_tpe()
        today = now.date()

        def load_date(target_date, *, tick_fallback: bool = True) -> list[dict]:
            date_text = target_date.isoformat()
            try:
                rows = self._kbar_rows_for_date(code, date_text)
            except Exception:
                rows = []
            if tick_fallback and len(rows) < 30:
                try:
                    tick_rows = self._tick_rows_for_date(code, date_text)
                    if len(tick_rows) > len(rows):
                        rows = tick_rows
                except Exception:
                    pass
            return rows

        # From 09:00 onward, today's partial data is valid and should not fall
        # back to yesterday merely because the session has only just started.
        if now.time() >= dtime(9, 0):
            try:
                today_rows = self._kbar_rows_for_date(code, today.isoformat())
            except Exception:
                today_rows = []
            if today_rows:

                # 收盤後強制使用完整 AllDay ticks 補齊整日走勢。
                # 避免 Kbars 不完整造成 P 圖看起來從尾盤開始。
                if now.time() >= dtime(13, 35):
                    try:
                        tick_rows = self._tick_rows_for_date(
                            code,
                            today.isoformat()
                        )

                        if len(tick_rows) >= len(today_rows):
                            today_rows = tick_rows

                    except Exception:
                        pass

                return today_rows

        # Before open / no-trading day: find latest date with real data.
        for days_back in range(1, 11):
            rows = load_date(today - timedelta(days=days_back), tick_fallback=True)
            if rows:
                return rows

        return []



RESOLVER = StockResolver()
SJ = ShioajiQuery()


def finmind(dataset: str, code: str, start_date: str, end_date: str | None = None) -> list[dict]:
    params = {
        "dataset": dataset,
        "data_id": code,
        "start_date": start_date,
    }
    if end_date:
        params["end_date"] = end_date

    headers = {}
    if FINMIND_TOKEN:
        headers["Authorization"] = f"Bearer {FINMIND_TOKEN}"

    r = HTTP.get(
        FINMIND_URL,
        params=params,
        headers=headers,
        timeout=DATA_TIMEOUT,
    )
    r.raise_for_status()
    payload = r.json()
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    return [x for x in rows if isinstance(x, dict)]


def finmind_total(dataset: str, start_date: str, end_date: str | None = None) -> list[dict]:
    """FinMind 不需要 data_id 的整體市場資料集。"""
    params = {
        "dataset": dataset,
        "start_date": start_date,
    }
    if end_date:
        params["end_date"] = end_date

    headers = {}
    if FINMIND_TOKEN:
        headers["Authorization"] = f"Bearer {FINMIND_TOKEN}"

    r = HTTP.get(
        FINMIND_URL,
        params=params,
        headers=headers,
        timeout=DATA_TIMEOUT,
    )
    r.raise_for_status()
    payload = r.json()
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    return [x for x in rows if isinstance(x, dict)]


def make_chart_url(path: Path) -> str | None:
    if not PUBLIC_BASE_URL:
        return None
    return f"{PUBLIC_BASE_URL}/charts/{quote(path.name)}"


def _matplotlib():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    return plt


def make_intraday_chart(code: str, name: str, rows: list[dict]) -> Path:
    plt = _matplotlib()
    if not rows:
        raise RuntimeError("當日分K尚無資料")

    times = [x["time"] for x in rows if x.get("close") is not None]
    closes = [x["close"] for x in rows if x.get("close") is not None]
    volumes = [x.get("volume") or 0 for x in rows if x.get("close") is not None]

    key = hashlib.sha1(
        f"P:{code}:{now_tpe().strftime('%Y%m%d%H%M')}".encode()
    ).hexdigest()[:16]
    path = CHART_DIR / f"P_{code}_{key}.png"

    fig = plt.figure(figsize=(10, 6), dpi=130)
    ax = fig.add_axes([0.09, 0.30, 0.87, 0.62])
    ax2 = fig.add_axes([0.09, 0.09, 0.87, 0.16], sharex=ax)

    ax.plot(times, closes, linewidth=1.6)
    ax.set_title(f"{name} {code} 當日即時走勢")
    ax.set_ylabel("Price")
    ax.grid(alpha=0.22)

    ax2.bar(times, volumes, width=0.00045)
    ax2.set_ylabel("Vol")
    ax2.grid(alpha=0.15)

    fig.autofmt_xdate()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def make_daily_k_chart(code: str, name: str, rows: list[dict]) -> Path:
    plt = _matplotlib()
    if not rows:
        raise RuntimeError("K線資料不足")

    rows = sorted(rows, key=lambda x: str(x.get("date"))) [-60:]
    dates = [str(x.get("date")) for x in rows]
    opens = [_num(x.get("open")) for x in rows]
    highs = [_num(x.get("max")) for x in rows]
    lows = [_num(x.get("min")) for x in rows]
    closes = [_num(x.get("close")) for x in rows]
    vols = [_num(x.get("Trading_Volume")) or 0 for x in rows]

    key = hashlib.sha1(
        f"K:{code}:{dates[-1] if dates else ''}".encode()
    ).hexdigest()[:16]
    path = CHART_DIR / f"K_{code}_{key}.png"

    fig = plt.figure(figsize=(10, 7), dpi=130)
    ax = fig.add_axes([0.08, 0.32, 0.89, 0.60])
    axv = fig.add_axes([0.08, 0.10, 0.89, 0.17], sharex=ax)

    for i, (o, h, l, c) in enumerate(zip(opens, highs, lows, closes)):
        if None in (o, h, l, c):
            continue
        ax.vlines(i, l, h, linewidth=1)
        bottom = min(o, c)
        height = max(abs(c - o), 0.01)
        rect = plt.Rectangle((i - 0.32, bottom), 0.64, height, fill=False, linewidth=1)
        ax.add_patch(rect)

    ax.set_xlim(-1, len(rows))
    ax.set_title(f"{name} {code} 日K（近60交易日）")
    ax.set_ylabel("Price")
    ax.grid(alpha=0.2)

    axv.bar(range(len(vols)), vols)
    axv.set_ylabel("Vol")
    axv.grid(alpha=0.15)

    step = max(1, len(rows) // 8)
    ticks = list(range(0, len(rows), step))
    axv.set_xticks(ticks)
    axv.set_xticklabels([dates[i][5:] for i in ticks], rotation=45, ha="right")

    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def make_institutional_chart(code: str, name: str, rows: list[dict]) -> Path:
    plt = _matplotlib()
    if not rows:
        raise RuntimeError("三大法人資料不足")

    rows = sorted(rows, key=lambda x: str(x.get("date"))) [-30:]

    def net(row, buy_key, sell_key):
        return (_num(row.get(buy_key)) or 0) - (_num(row.get(sell_key)) or 0)

    dates = [str(x.get("date")) for x in rows]
    foreign = [
        net(x, "Foreign_Investor_buy", "Foreign_Investor_sell")
        + net(x, "Foreign_Dealer_Self_buy", "Foreign_Dealer_Self_sell")
        for x in rows
    ]
    trust = [
        net(x, "Investment_Trust_buy", "Investment_Trust_sell")
        for x in rows
    ]
    dealer = [
        net(x, "Dealer_buy", "Dealer_sell")
        + net(x, "Dealer_self_buy", "Dealer_self_sell")
        + net(x, "Dealer_Hedging_buy", "Dealer_Hedging_sell")
        for x in rows
    ]

    key = hashlib.sha1(
        f"T:{code}:{dates[-1] if dates else ''}".encode()
    ).hexdigest()[:16]
    path = CHART_DIR / f"T_{code}_{key}.png"

    fig = plt.figure(figsize=(10, 6), dpi=130)
    ax = fig.add_axes([0.08, 0.18, 0.89, 0.74])
    x = list(range(len(rows)))

    ax.plot(x, foreign, label="Foreign")
    ax.plot(x, trust, label="Investment Trust")
    ax.plot(x, dealer, label="Dealer")
    ax.axhline(0, linewidth=0.8)
    ax.set_title(f"{name} {code} 三大法人買賣超")
    ax.set_ylabel("Shares")
    ax.legend()
    ax.grid(alpha=0.2)

    step = max(1, len(rows) // 8)
    ticks = list(range(0, len(rows), step))
    ax.set_xticks(ticks)
    ax.set_xticklabels([dates[i][5:] for i in ticks], rotation=45, ha="right")

    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def _twse_roc_date_to_iso(text: str) -> str:
    raw = str(text or "").strip()
    m = re.match(r"^(\d{2,3})/(\d{1,2})/(\d{1,2})$", raw)
    if not m:
        return raw
    year = int(m.group(1)) + 1911
    return f"{year:04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"


def twse_taiex_daily_rows(months: int = 4) -> list[dict]:
    """TWSE 官方發行量加權股價指數歷史 OHLC。"""
    rows: list[dict] = []
    seen = set()
    d = now_tpe().date().replace(day=1)

    for _ in range(months):
        date_param = d.strftime("%Y%m01")
        url = "https://www.twse.com.tw/indicesReport/MI_5MINS_HIST"
        r = HTTP.get(
            url,
            params={"response": "json", "date": date_param},
            timeout=DATA_TIMEOUT,
        )
        r.raise_for_status()
        payload = r.json()
        fields = payload.get("fields") or []
        data = payload.get("data") or []

        # 目前官方欄位順序：日期 / 開盤 / 最高 / 最低 / 收盤
        for item in data:
            if not isinstance(item, list) or len(item) < 5:
                continue
            iso = _twse_roc_date_to_iso(item[0])
            if iso in seen:
                continue
            seen.add(iso)
            rows.append({
                "date": iso,
                "open": _num(item[1]),
                "max": _num(item[2]),
                "min": _num(item[3]),
                "close": _num(item[4]),
                "Trading_Volume": 0,
            })

        # previous month
        if d.month == 1:
            d = d.replace(year=d.year - 1, month=12)
        else:
            d = d.replace(month=d.month - 1)

    return sorted(rows, key=lambda x: x["date"])


def make_market_k_chart(rows: list[dict]) -> Path:
    plt = _matplotlib()
    if not rows:
        raise RuntimeError("大盤 K 線資料不足")

    rows = sorted(rows, key=lambda x: str(x.get("date")))[-60:]
    dates = [str(x.get("date")) for x in rows]
    opens = [_num(x.get("open")) for x in rows]
    highs = [_num(x.get("max")) for x in rows]
    lows = [_num(x.get("min")) for x in rows]
    closes = [_num(x.get("close")) for x in rows]

    key = hashlib.sha1(
        f"KMKT:{dates[-1] if dates else ''}".encode()
    ).hexdigest()[:16]
    path = CHART_DIR / f"K_market_{key}.png"

    fig = plt.figure(figsize=(10, 6), dpi=130)
    ax = fig.add_axes([0.08, 0.16, 0.89, 0.76])

    for i, (o, h, l, c) in enumerate(zip(opens, highs, lows, closes)):
        if None in (o, h, l, c):
            continue
        ax.vlines(i, l, h, linewidth=1)
        bottom = min(o, c)
        height = max(abs(c - o), 0.01)
        rect = plt.Rectangle(
            (i - 0.32, bottom), 0.64, height,
            fill=False, linewidth=1,
        )
        ax.add_patch(rect)

    ax.set_xlim(-1, len(rows))
    ax.set_title("加權指數｜近60交易日日K")
    ax.set_ylabel("Index")
    ax.grid(alpha=0.2)

    step = max(1, len(rows) // 8)
    ticks = list(range(0, len(rows), step))
    ax.set_xticks(ticks)
    ax.set_xticklabels(
        [dates[i][5:] for i in ticks],
        rotation=45,
        ha="right",
    )

    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def _market_inst_daily(rows: list[dict]) -> list[dict]:
    daily: dict[str, dict] = {}
    for row in rows:
        date = str(row.get("date") or "")
        if not date:
            continue
        item = daily.setdefault(date, {
            "date": date,
            "foreign": 0.0,
            "trust": 0.0,
            "dealer": 0.0,
        })
        name = str(row.get("name") or "")
        net = (_num(row.get("buy")) or 0.0) - (_num(row.get("sell")) or 0.0)

        if name in {"Foreign_Investor", "Foreign_Dealer_Self"}:
            item["foreign"] += net
        elif name == "Investment_Trust":
            item["trust"] += net
        elif name in {"Dealer", "Dealer_self", "Dealer_Hedging"}:
            item["dealer"] += net

    return [daily[k] for k in sorted(daily)]


def make_market_institutional_chart(rows: list[dict]) -> tuple[Path, list[dict]]:
    plt = _matplotlib()
    daily = _market_inst_daily(rows)[-30:]
    if not daily:
        raise RuntimeError("大盤三大法人資料不足")

    dates = [x["date"] for x in daily]
    foreign = [x["foreign"] for x in daily]
    trust = [x["trust"] for x in daily]
    dealer = [x["dealer"] for x in daily]

    key = hashlib.sha1(
        f"TMKT:{dates[-1] if dates else ''}".encode()
    ).hexdigest()[:16]
    path = CHART_DIR / f"T_market_{key}.png"

    fig = plt.figure(figsize=(10, 6), dpi=130)
    ax = fig.add_axes([0.08, 0.18, 0.89, 0.74])
    x = list(range(len(daily)))

    ax.plot(x, foreign, label="Foreign")
    ax.plot(x, trust, label="Investment Trust")
    ax.plot(x, dealer, label="Dealer")
    ax.axhline(0, linewidth=0.8)
    ax.set_title("大盤｜三大法人買賣超")
    ax.set_ylabel("Net buy/sell")
    ax.legend()
    ax.grid(alpha=0.2)

    step = max(1, len(daily) // 8)
    ticks = list(range(0, len(daily), step))
    ax.set_xticks(ticks)
    ax.set_xticklabels(
        [dates[i][5:] for i in ticks],
        rotation=45,
        ha="right",
    )

    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path, daily


def _signed_compact(v: float) -> str:
    sign = "+" if v > 0 else ""
    return f"{sign}{v:,.0f}"


def _snapshot_datetime(ts) -> datetime | None:
    """Convert Shioaji snapshot ts to Taiwan exchange wall-clock time.

    Shioaji's Python examples cast the integer timestamp directly to a
    timezone-naive datetime and display Taiwan exchange clock time. Treating
    the value as a true UTC epoch and then astimezone(+08:00) adds an
    erroneous extra eight hours (e.g. 14:30 -> 22:30).

    We therefore decode the epoch number to its clock fields without applying
    an additional +8-hour shift, then attach Asia/Taipei semantics.
    """
    if ts is None:
        return None
    try:
        value = float(ts)
        if value > 1e17:
            value /= 1_000_000_000
        elif value > 1e14:
            value /= 1_000_000
        elif value > 1e11:
            value /= 1_000

        # Preserve Shioaji's exchange wall-clock fields.
        wall = datetime.fromtimestamp(value, tz=timezone.utc)
        return wall.replace(tzinfo=TPE)
    except Exception:
        return None


def _snapshot_time_text(ts, with_date: bool = False) -> str:
    dt = _snapshot_datetime(ts)
    if dt is None:
        dt = now_tpe()
    return dt.strftime("%m/%d %H:%M:%S" if with_date else "%H:%M:%S")


def _compact_price(v) -> str:
    if v is None:
        return "--"
    v = float(v)
    if v.is_integer():
        return str(int(v))
    return f"{v:.2f}".rstrip("0").rstrip(".")


def quote_text(s: dict) -> str:
    """#股票：使用者指定的單行簡潔格式。"""
    price = s.get("close")
    change = float(s.get("change_price") or 0)
    rate = float(s.get("change_rate") or 0)

    if change > 0:
        arrow = "▲"
    elif change < 0:
        arrow = "▼"
    else:
        arrow = "－"

    return (
        f"行情 {_snapshot_time_text(s.get('ts'))} "
        f"{s['name']}({s['code']}) "
        f"成交價：{_compact_price(price)} "
        f"{arrow}{abs(change):.2f}({rate:.2f}%)"
    )


def market_text() -> str:
    """#大盤：與 #股票 一樣採單行快速格式。"""
    s = SJ.market_snapshot()
    price = s.get("close")
    change = float(s.get("change_price") or 0)
    rate = float(s.get("change_rate") or 0)
    if change > 0:
        arrow = "▲"
    elif change < 0:
        arrow = "▼"
    else:
        arrow = "－"
    return (
        f"行情 {_snapshot_time_text(s.get('ts'))} "
        f"加權指數 成交：{_compact_price(price)} "
        f"{arrow}{abs(change):.2f}({rate:.2f}%)"
    )


def _yield_from_official(code: str, market: str) -> float | None:
    try:
        url = TWSE_YIELD if market == "TSE" else TPEX_YIELD
        r = HTTP.get(url, timeout=DATA_TIMEOUT)
        r.raise_for_status()
        payload = r.json()
        rows = payload if isinstance(payload, list) else payload.get("data", [])

        for row in rows:
            if not isinstance(row, dict):
                continue
            row_code = str(
                _pick(
                    row,
                    "Code",
                    "證券代號",
                    "SecuritiesCompanyCode",
                    "股票代號",
                    "code",
                )
                or ""
            ).strip()

            if row_code != code:
                continue

            return _num(
                _pick(
                    row,
                    "DividendYield",
                    "殖利率(%)",
                    "殖利率％",
                    "Dividend Yield(%)",
                    "yield",
                )
            )
    except Exception:
        pass

    return None


def dividend_text(stock: dict) -> str:
    code = stock["code"]
    name = stock["name"]
    end = now_tpe().date()
    start = end - timedelta(days=365 * 4)

    div_rows = finmind(
        "TaiwanStockDividend",
        code,
        start.isoformat(),
        end.isoformat(),
    )

    if not div_rows:
        return f"💰 {name} {code}\n查無股利資料。"

    div_rows = sorted(
        div_rows,
        key=lambda x: str(x.get("date") or x.get("year") or ""),
    )

    latest = div_rows[-1]
    cash = (
        _num(latest.get("CashEarningsDistribution")) or 0.0
    ) + (
        _num(latest.get("CashStatutorySurplus")) or 0.0
    )
    stock_div = (
        _num(latest.get("StockEarningsDistribution")) or 0.0
    ) + (
        _num(latest.get("StockStatutorySurplus")) or 0.0
    )

    snap = SJ.snapshot(code)
    price = snap.get("close")
    calc_yield = cash / price * 100 if cash and price else None
    official_yield = _yield_from_official(code, stock.get("market", ""))
    yield_pct = official_yield if official_yield is not None else calc_yield

    # 最新年度 EPS：FinMind 財報中抓 EPS 類型。
    eps = None
    try:
        fs_rows = finmind(
            "TaiwanStockFinancialStatements",
            code,
            (end - timedelta(days=365 * 3)).isoformat(),
            end.isoformat(),
        )
        eps_candidates = []
        for row in fs_rows:
            type_name = str(row.get("type") or "")
            origin = str(row.get("origin_name") or "")
            if "EPS" in type_name.upper() or "每股盈餘" in origin:
                value = _num(row.get("value"))
                if value is not None:
                    eps_candidates.append((str(row.get("date") or ""), value))
        if eps_candidates:
            eps = sorted(eps_candidates)[-1][1]
    except Exception:
        eps = None

    payout = cash / eps * 100 if cash and eps not in (None, 0) else None

    year = latest.get("year") or latest.get("date") or "--"

    return (
        f"💰 {name} {code}｜股利\n"
        f"年度：{year}\n"
        f"現金股利：{cash:.2f} 元\n"
        f"股票股利：{stock_div:.2f} 元\n"
        f"殖利率：{yield_pct:.2f}%\n" if yield_pct is not None else
        f"💰 {name} {code}｜股利\n"
        f"年度：{year}\n"
        f"現金股利：{cash:.2f} 元\n"
        f"股票股利：{stock_div:.2f} 元\n"
        f"殖利率：--\n"
    ) + (
        f"現金股利配發率：{payout:.1f}%\n"
        if payout is not None
        else "現金股利配發率：--\n"
    ) + (
        f"除息日：{latest.get('CashExDividendTradingDate') or '--'}"
    )


def _ambiguous_text(query: str, rows: list[dict]) -> str:
    lines = [f"🔎「{query}」有多個可能，請改用代碼："]
    for row in rows[:5]:
        lines.append(f"{row['code']} {row['name']}")
    return "\n".join(lines)


def resolve_or_message(query: str) -> tuple[dict | None, str | None]:
    stock, choices = RESOLVER.resolve(query)
    if stock is not None:
        # 用 Shioaji 補正式名稱 / 交易所，避免 catalog 欄位問題。
        try:
            info = SJ.stock_info(stock["code"])
            stock["name"] = info["name"]
            if not stock.get("market"):
                stock["market"] = info["exchange"]
        except Exception:
            pass
        return stock, None

    if choices:
        return None, _ambiguous_text(query, choices)

    return None, f"查不到「{query}」，請輸入完整股票/ETF名稱或代碼。"


def _card_path(prefix: str) -> Path:
    stamp = now_tpe().strftime("%Y%m%d_%H%M%S_%f")
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", str(prefix))
    return CHART_DIR / f"{safe}_{stamp}.png"


def _stamp_snapshot(snapshot: dict) -> dict:
    snapshot = dict(snapshot)
    snapshot["timestamp_text"] = _snapshot_time_text(snapshot.get("ts"), with_date=True)
    return snapshot


def text_message(text: str) -> dict:
    return {"type": "text", "text": text[:5000]}


def image_message(url: str) -> dict:
    """Legacy plain image message helper."""
    return {
        "type": "image",
        "originalContentUrl": url,
        "previewImageUrl": url,
    }


def yahoo_quote_url(target: str, market: bool = False) -> str:
    """Yahoo Taiwan quote page used when the user taps the chart image."""
    if market:
        return "https://tw.stock.yahoo.com/quote/%5ETWII"
    code = quote(str(target).strip(), safe="")
    return f"https://tw.stock.yahoo.com/quote/{code}"


def _format_compact_volume(vol: float | None, is_market: bool = False) -> str:
    if vol is None:
        return "--"
    if is_market:
        yi = vol / 100_000_000.0
        return f"{int(round(yi)):,}億"
    v = float(vol)
    if v >= 10000:
        return f"{v/1000.0:.1f}k張"
    return f"{int(round(v)):,}張"


def _build_nav_pill(label: str, action_data: dict, is_active: bool) -> dict:
    bg_color = "#F59E0B" if is_active else "#F3F4F6"
    text_color = "#FFFFFF" if is_active else "#374151"
    return {
        "type": "box",
        "layout": "vertical",
        "flex": 1,
        "cornerRadius": "6px",
        "paddingTop": "6px",
        "paddingBottom": "6px",
        "paddingStart": "2px",
        "paddingEnd": "2px",
        "backgroundColor": bg_color,
        "action": action_data,
        "contents": [
            {
                "type": "text",
                "text": label,
                "size": "xxs",
                "align": "center",
                "weight": "bold",
                "color": text_color,
            }
        ],
    }


def interactive_card_message(
    url: str,
    *,
    title: str,
    target: str,
    selected: str,
    market: bool = False,
    snapshot: dict | None = None,
) -> dict:
    """Wrap stock/market chart in a modern Apple-styled LINE Flex card.

    - P (Real-time): Hybrid Flex card. Header, price HUD, change badges, and navigation
      are native LINE text/box components. ONLY the sparkline curve is an image.
    - K (K-line) / T (Institutions): 1:1 rich chart with identical slender bottom tabs.
    - Slender pills use box actions with xxs font, ensuring all 6 buttons fit
      elegantly on mobile screens without truncation.
    """
    selected = selected.upper().strip()

    if market:
        buttons = [
            _build_nav_pill("P即時", {"type": "message", "label": "P即時", "text": "P大盤"}, selected == "P"),
            _build_nav_pill("K線", {"type": "message", "label": "K線", "text": "K大盤"}, selected == "K"),
            _build_nav_pill("T法人", {"type": "message", "label": "T法人", "text": "T大盤"}, selected == "T"),
            _build_nav_pill("官網", {"type": "uri", "label": "官網", "uri": EASYSTOCK_WEB_URL}, False),
        ]
        alt_target = "大盤"
    else:
        buttons = [
            _build_nav_pill("P即時", {"type": "message", "label": "P即時", "text": f"P{target}"}, selected == "P"),
            _build_nav_pill("K線", {"type": "message", "label": "K線", "text": f"K{target}"}, selected == "K"),
            _build_nav_pill("T法人", {"type": "message", "label": "T法人", "text": f"T{target}"}, selected == "T"),
            _build_nav_pill("EPS", {"type": "message", "label": "EPS", "text": f"#{target}"}, False),
            _build_nav_pill("F營收", {"type": "uri", "label": "F營收", "uri": f"https://tw.stock.yahoo.com/quote/{target}/revenue"}, False),
            _build_nav_pill("D股利", {"type": "message", "label": "D股利", "text": f"D{target}"}, selected == "D"),
        ]
        alt_target = target

    footer_box = {
        "type": "box",
        "layout": "horizontal",
        "spacing": "xs",
        "paddingAll": "8px",
        "backgroundColor": "#FFFFFF",
        "contents": buttons,
    }

    if selected == "P" and snapshot:
        close = _num(snapshot.get("close"))
        ref = _num(snapshot.get("reference"))
        change = _num(snapshot.get("change_price"))
        rate = _num(snapshot.get("change_rate"))
        if change is None and close is not None and ref is not None:
            change = close - ref
        if rate is None and close is not None and ref not in (None, 0):
            rate = (close / ref - 1.0) * 100.0

        if change is not None and change > 0:
            price_color = "#DC2626"
            pill_bg = "#FEE2E2"
            pill_text_color = "#DC2626"
            change_str = f"▲ +{change:.2f} (+{rate:.2f}%)" if rate is not None else f"▲ +{change:.2f}"
            share_change = f"+{change:.2f} (+{rate:.2f}%)" if rate is not None else f"+{change:.2f}"
        elif change is not None and change < 0:
            price_color = "#16A34A"
            pill_bg = "#DCFCE7"
            pill_text_color = "#16A34A"
            change_str = f"▼ {change:.2f} ({rate:.2f}%)" if rate is not None else f"▼ {change:.2f}"
            share_change = f"{change:.2f} ({rate:.2f}%)" if rate is not None else f"{change:.2f}"
        else:
            price_color = "#111827"
            pill_bg = "#F3F4F6"
            pill_text_color = "#4B5563"
            change_str = "- 0.00 (0.00%)"
            share_change = "0.00 (0.00%)"

        price_display = _format_price(close)

        if market:
            raw_share = f"台股加權指數 最新報價：{price_display} ({share_change}) 來自 EasyStock\n{EASYSTOCK_WEB_URL}"
        else:
            raw_share = f"{title} ({target}) 最新報價：{price_display} ({share_change}) 來自 EasyStock\n{EASYSTOCK_WEB_URL}"
        share_url = f"https://line.me/R/share?text={quote(raw_share)}"

        ts = snapshot.get("ts") or snapshot.get("timestamp") or snapshot.get("datetime")
        ts_str = ""
        if ts:
            ts_str = str(ts)[11:19] if len(str(ts)) >= 19 else str(ts)
        category = "指數" if market else (str(snapshot.get("exchange") or "上市") + " · " + target + ".TW")
        sub_info = f"{category} · {ts_str}" if ts_str else category

        open_val = _format_price(_num(snapshot.get("open")))
        high_val = _format_price(_num(snapshot.get("high")))
        low_val = _format_price(_num(snapshot.get("low")))
        ref_val = _format_price(ref)
        vol_val = _format_compact_volume(_num(snapshot.get("total_amount") if market else snapshot.get("total_volume")), is_market=market)

        def _col_box(lbl: str, val: str, c: str) -> dict:
            return {
                "type": "box",
                "layout": "vertical",
                "flex": 1,
                "alignItems": "center",
                "contents": [
                    {"type": "text", "text": lbl, "size": "xxs", "color": "#9CA3AF"},
                    {"type": "text", "text": val, "size": "xs", "weight": "bold", "color": c},
                ],
            }

        bubble = {
            "type": "bubble",
            "header": {
                "type": "box",
                "layout": "vertical",
                "spacing": "xs",
                "paddingBottom": "none",
                "backgroundColor": "#FFFFFF",
                "contents": [
                    {
                        "type": "box",
                        "layout": "horizontal",
                        "alignItems": "center",
                        "contents": [
                            {"type": "text", "text": title, "size": "xl", "weight": "bold", "color": "#111827", "flex": 0},
                            {
                                "type": "box",
                                "layout": "vertical",
                                "flex": 0,
                                "margin": "sm",
                                "backgroundColor": "#F3F4F6",
                                "cornerRadius": "4px",
                                "paddingStart": "6px",
                                "paddingEnd": "6px",
                                "paddingTop": "2px",
                                "paddingBottom": "2px",
                                "contents": [
                                    {"type": "text", "text": target, "size": "xxs", "weight": "bold", "color": "#4B5563"}
                                ],
                            },
                            {"type": "box", "layout": "vertical", "flex": 1, "contents": []},
                            {
                                "type": "box",
                                "layout": "horizontal",
                                "flex": 0,
                                "backgroundColor": "#F3F4F6",
                                "cornerRadius": "12px",
                                "paddingStart": "8px",
                                "paddingEnd": "8px",
                                "paddingTop": "3px",
                                "paddingBottom": "3px",
                                "action": {
                                    "type": "uri",
                                    "label": "分享",
                                    "uri": share_url,
                                },
                                "contents": [
                                    {"type": "text", "text": "分享 ↗", "size": "xxs", "weight": "bold", "color": "#6B7280"}
                                ],
                            },
                        ],
                    },
                    {"type": "text", "text": sub_info, "size": "xxs", "color": "#9CA3AF"},
                    {
                        "type": "box",
                        "layout": "horizontal",
                        "spacing": "md",
                        "alignItems": "center",
                        "margin": "sm",
                        "contents": [
                            {"type": "text", "text": price_display, "size": "xxl", "weight": "bold", "color": price_color, "flex": 0},
                            {
                                "type": "box",
                                "layout": "horizontal",
                                "flex": 0,
                                "backgroundColor": pill_bg,
                                "cornerRadius": "4px",
                                "paddingStart": "6px",
                                "paddingEnd": "6px",
                                "paddingTop": "3px",
                                "paddingBottom": "3px",
                                "contents": [
                                    {"type": "text", "text": change_str, "size": "xs", "weight": "bold", "color": pill_text_color}
                                ],
                            },
                        ],
                    },
                ],
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "sm",
                "paddingTop": "xs",
                "backgroundColor": "#FFFFFF",
                "contents": [
                    {
                        "type": "box",
                        "layout": "vertical",
                        "contents": [
                            {
                                "type": "image",
                                "url": url,
                                "size": "full",
                                "aspectRatio": "16:9",
                                "aspectMode": "cover",
                                "action": {
                                    "type": "uri",
                                    "label": "Yahoo股市",
                                    "uri": yahoo_quote_url(target, market=market),
                                },
                            }
                        ],
                    },
                    {
                        "type": "box",
                        "layout": "horizontal",
                        "backgroundColor": "#F9FAFB",
                        "cornerRadius": "8px",
                        "paddingAll": "8px",
                        "contents": [
                            _col_box("開盤", open_val, "#111827"),
                            {"type": "separator", "color": "#E5E7EB"},
                            _col_box("最高", high_val, "#DC2626"),
                            {"type": "separator", "color": "#E5E7EB"},
                            _col_box("最低", low_val, "#16A34A"),
                            {"type": "separator", "color": "#E5E7EB"},
                            _col_box("昨收", ref_val, "#111827"),
                            {"type": "separator", "color": "#E5E7EB"},
                            _col_box("成交", vol_val, "#D97706"),
                        ],
                    },
                    {
                        "type": "box",
                        "layout": "horizontal",
                        "backgroundColor": "#FEF3C7",
                        "cornerRadius": "6px",
                        "paddingAll": "6px",
                        "margin": "sm",
                        "action": {
                            "type": "uri",
                            "label": "當沖雷達",
                            "uri": "https://jimmyeyes.com/easystock/#dashboard",
                        },
                        "contents": [
                            {
                                "type": "text",
                                "text": "⚡ EasyStock 當沖量化雷達 · 點擊查看",
                                "size": "xxs",
                                "weight": "bold",
                                "color": "#B45309",
                                "align": "center",
                                "flex": 1,
                            }
                        ],
                    },
                ],
            },
            "footer": footer_box,
        }
        return {
            "type": "flex",
            "altText": f"{title} {alt_target} 即時走勢",
            "contents": bubble,
        }

    return {
        "type": "flex",
        "altText": f"{title} {alt_target} 圖卡",
        "contents": {
            "type": "bubble",
            "hero": {
                "type": "image",
                "url": url,
                "size": "full",
                "aspectRatio": "1:1",
                "aspectMode": "fit",
                "backgroundColor": "#FFFFFF",
                "action": {
                    "type": "uri",
                    "label": "Yahoo股市",
                    "uri": yahoo_quote_url(target, market=market),
                },
            },
            "footer": footer_box,
        },
    }


def chart_fallback(path: Path) -> dict:
    return text_message(
        "📊 圖表已產生，但 LINE_BOT_PUBLIC_BASE_URL 尚未設定，"
        "目前先回文字資料。"
    )


def handle_command(cmd: ParsedCommand) -> list[dict]:
    if cmd.kind == "HELP":
        return [text_message(HELP_TEXT)]

    if cmd.kind == "UPDATE":
        from line_hub_service import UPDATE_TEXT
        return [text_message(UPDATE_TEXT)]

    if cmd.kind == "NOTIFY_INFO":
        from line_hub_service import NOTIFY_INFO_TEXT
        return [text_message(NOTIFY_INFO_TEXT)]

    if cmd.kind == "PREMARKET":
        from line_hub_service import latest_premarket_text
        return [text_message(latest_premarket_text())]

    if cmd.kind == "DAYTRADE":
        from line_hub_service import latest_daytrade_text
        return [text_message(latest_daytrade_text())]

    if cmd.kind == "MARKET_TEXT":
        try:
            return [text_message(market_text())]
        except Exception as exc:
            return [text_message(f"大盤查詢失敗：{type(exc).__name__}: {exc}")]

    # 大盤是市場關鍵字，永遠不丟進個股 resolver。
    if cmd.query == "大盤":
        try:
            if cmd.kind == "P":
                snap = _stamp_snapshot(SJ.market_snapshot())
                try:
                    rows = SJ.intraday_rows("IX0001")
                except Exception:
                    rows = []
                chart = render_market_sparkline(
                    snap, rows, _card_path("P_market")
                )
                url = make_chart_url(chart)
                return [interactive_card_message(url, title="加權指數", target="大盤", selected="P", market=True, snapshot=snap)] if url else [chart_fallback(chart)]

            if cmd.kind == "K":
                rows = twse_taiex_daily_rows(months=4)
                chart = render_k_card(
                    "加權指數", "TAIEX", rows,
                    _card_path("K_market"), is_market=True,
                )
                url = make_chart_url(chart)
                return [interactive_card_message(url, title="加權指數", target="大盤", selected="K", market=True)] if url else [chart_fallback(chart)]

            if cmd.kind == "T":
                end = now_tpe().date()
                start = end - timedelta(days=100)
                raw = finmind_total(
                    "TaiwanStockTotalInstitutionalInvestors",
                    start.isoformat(), end.isoformat(),
                )
                daily = _market_inst_daily(raw)
                snap = _stamp_snapshot(SJ.market_snapshot())
                chart = render_institutional_card(
                    "加權指數", "TAIEX", snap, daily,
                    _card_path("T_market"), market=True,
                )
                url = make_chart_url(chart)
                return [interactive_card_message(url, title="加權指數", target="大盤", selected="T", market=True)] if url else [chart_fallback(chart)]

            return [text_message("大盤支援 #大盤、P大盤、K大盤、T大盤。")]

        except Exception as exc:
            return [text_message(
                f"⚠️ 大盤查詢失敗\n{type(exc).__name__}: {exc}"
            )]

    stock, error = resolve_or_message(cmd.query)
    if stock is None:
        return [text_message(error or "查無股票")]

    code = stock["code"]
    name = stock["name"]

    try:
        if cmd.kind == "STOCK_TEXT":
            snap = SJ.snapshot(code)
            snap["name"] = name
            return [text_message(quote_text(snap))]

        if cmd.kind == "P":
            snap = SJ.snapshot(code)
            snap["name"] = name
            snap = _stamp_snapshot(snap)
            rows = SJ.intraday_rows(code)
            chart = render_stock_sparkline(
                snap, rows, _card_path(f"P_{code}")
            )
            url = make_chart_url(chart)
            return [interactive_card_message(url, title=name, target=code, selected="P", market=False, snapshot=snap)] if url else [chart_fallback(chart)]

        if cmd.kind == "K":
            end = now_tpe().date()
            start = end - timedelta(days=140)
            rows = finmind(
                "TaiwanStockPrice", code,
                start.isoformat(), end.isoformat(),
            )
            chart = render_k_card(
                name, code, rows, _card_path(f"K_{code}"), is_market=False
            )
            url = make_chart_url(chart)
            return [interactive_card_message(url, title=name, target=code, selected="K", market=False)] if url else [chart_fallback(chart)]

        if cmd.kind == "T":
            end = now_tpe().date()
            start = end - timedelta(days=100)
            rows = finmind(
                "TaiwanStockInstitutionalInvestorsBuySellWide", code,
                start.isoformat(), end.isoformat(),
            )
            snap = SJ.snapshot(code)
            snap["name"] = name
            snap = _stamp_snapshot(snap)
            chart = render_institutional_card(
                name, code, snap, rows,
                _card_path(f"T_{code}"), market=False,
            )
            url = make_chart_url(chart)
            return [interactive_card_message(url, title=name, target=code, selected="T", market=False)] if url else [chart_fallback(chart)]

        if cmd.kind == "D":
            if str(stock.get("asset_type") or "").upper() == "ETF":
                return [text_message(
                    f"💰 {name} {code}｜ETF\n"
                    "目前 D 指令仍是「公司股利/殖利率」資料源，"
                    "ETF 配息資料我還沒混用，避免把公司股利資料誤當 ETF 配息。"
                )]
            return [text_message(dividend_text(stock))]

    except Exception as exc:
        return [text_message(
            f"⚠️ {name} {code} 查詢失敗\n{type(exc).__name__}: {exc}"
        )]

    return []


def cleanup_old_charts(max_age_hours: int = 24) -> None:
    cutoff = time.time() - max_age_hours * 3600
    try:
        for path in CHART_DIR.glob("*.png"):
            if path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
    except Exception:
        pass
