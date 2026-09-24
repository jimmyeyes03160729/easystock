#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
EasyStock - Taiwan Market Calendar & Trading Day Checker
========================================================

自動判定台灣股市（TWSE / TPEx）開休市狀態：
1. 週末例假日（週六、週日）休市判定。
2. 證交所（TWSE）官方行事曆排定之國定假日、春節封關與補假（自動抓取 + 內建離線備份）。
3. 天然災害 / 颱風天停止上班自動判別（依據行政院人事行政總處 DGPA / 台北市政府停班公告）。
4. 支援本地快取、手動覆蓋清單 (EXTRA_CLOSED_DATES)、離線 Fallback 與 CLI 查詢。
"""

from __future__ import annotations

import argparse
import html
import json
import math
import os
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

TPE = timezone(timedelta(hours=8))

# 內建 2026 年 TWSE 官方市場開休市完整行事曆（離線防斷網基礎表）
BUILTIN_2026_CLOSED: dict[str, str] = {
    "2026-01-01": "中華民國開國紀念日",
    "2026-02-12": "市場無交易，僅辦理結算交割作業",
    "2026-02-13": "市場無交易，僅辦理結算交割作業",
    "2026-02-15": "農曆除夕及春節",
    "2026-02-16": "農曆除夕及春節",
    "2026-02-17": "農曆除夕及春節",
    "2026-02-18": "農曆除夕及春節",
    "2026-02-19": "農曆除夕及春節",
    "2026-02-20": "農曆除夕及春節補假",
    "2026-02-27": "和平紀念日補假",
    "2026-02-28": "和平紀念日",
    "2026-04-03": "兒童節及民族掃墓節補假",
    "2026-04-04": "兒童節及民族掃墓節",
    "2026-04-05": "兒童節及民族掃墓節",
    "2026-04-06": "民族掃墓節補假",
    "2026-05-01": "勞動節",
    "2026-06-19": "端午節",
    "2026-09-25": "中秋節",
    "2026-09-28": "孔子誕辰紀念日 / 教師節",
    "2026-10-09": "國慶日補假",
    "2026-10-10": "國慶日",
    "2026-10-25": "臺灣光復暨金門古寧頭大捷紀念日",
    "2026-10-26": "臺灣光復紀念日補假",
    "2026-12-25": "行憲紀念日",
}

# 快取檔案儲存目錄
CALENDAR_CACHE_DIR = Path(os.environ.get("CALENDAR_CACHE_DIR", Path(__file__).resolve().parent / "data"))

# 行政院人事行政總處（DGPA）天然災害停班停課即時查詢網址
DGPA_NDS_URL = "https://www.dgpa.gov.tw/typh/daily/nds.html"
# TWSE 官方行事曆 API
TWSE_HOLIDAY_URL = "https://www.twse.com.tw/holidaySchedule/holidaySchedule"


def now_tpe() -> datetime:
    """取得台灣時區當前時間"""
    return datetime.now(TPE)


def parse_date(value: Any) -> date:
    """標準化傳入日期為 date 物件"""
    if value is None:
        return now_tpe().date()
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone(TPE).date()
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = value.strip().replace("/", "-")
        if "T" in text:
            text = text.split("T", 1)[0]
        elif " " in text:
            text = text.split(" ", 1)[0]
        return date.fromisoformat(text)
    raise ValueError(f"無法解析日期格式: {value}")


def _load_cache_calendar(year: int) -> dict[str, str] | None:
    """從本地快取讀取已下載之行事曆"""
    cache_path = CALENDAR_CACHE_DIR / f"calendar-{year}.json"
    if not cache_path.exists():
        return None
    try:
        content = json.loads(cache_path.read_text(encoding="utf-8"))
        if isinstance(content, dict) and "closed_map" in content:
            return content["closed_map"]
        if isinstance(content, dict) and "closed" in content:
            return {d: "排定休市" for d in content["closed"]}
    except Exception:
        pass
    return None


def _save_cache_calendar(year: int, closed_map: dict[str, str]) -> None:
    """儲存行事曆快取至本地"""
    try:
        CALENDAR_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_path = CALENDAR_CACHE_DIR / f"calendar-{year}.json"
        payload = {
            "year": year,
            "closed_map": closed_map,
            "closed": sorted(closed_map.keys()),
            "updated_at": now_tpe().isoformat(timespec="seconds"),
        }
        cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def fetch_twse_calendar(year: int, timeout: float = 8.0) -> dict[str, str]:
    """
    從 TWSE 官方 API 取得指定年份開休市清單。
    若網路不通或失敗，依序回退至本地快取與內建表。
    """
    cached = _load_cache_calendar(year)

    # 民國年計算（TWSE 查詢參數）
    roc_year = year - 1911
    url = f"{TWSE_HOLIDAY_URL}?response=json&queryYear={roc_year}"

    try:
        resp = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; EasyStock/1.0)", "Accept": "application/json"},
            timeout=timeout,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("stat", "").lower() == "ok" and data.get("data"):
                closed_map = {}
                for row in data["data"]:
                    # row: [日期 "2026-01-01", 名稱 "中華民國開國紀念日", 說明 "..."]
                    day_str = str(row[0]).strip()
                    name = str(row[1]).strip() if len(row) > 1 else "國定假日"
                    desc = str(row[2]).strip() if len(row) > 2 else ""

                    # 「開始交易日」與「最後交易日」為開盤交易提示，不是休市日
                    if any(x in name for x in ("開始交易", "最後交易")):
                        continue

                    # 「市場無交易，僅辦理結算交割作業」或一般國定假日皆屬休市
                    closed_map[day_str] = name or desc or "排定休市"

                if len(closed_map) >= 5:
                    _save_cache_calendar(year, closed_map)
                    return closed_map
    except Exception:
        pass

    if cached:
        return cached

    if year == 2026:
        return dict(BUILTIN_2026_CLOSED)

    return {}


def check_dgpa_typhoon_closure(target_date: date, timeout: float = 6.0) -> tuple[bool, str]:
    """
    查詢行政院人事行政總處（DGPA）天然災害停班停課情形。
    依據證交所規定：台北市政府宣布停止上班時，台股集中與櫃買市場全日休市。

    回傳：
        (is_closed_for_typhoon: bool, reason: str)
    """
    today = now_tpe().date()

    # 人事行政總處只公告今日與次日之停班停課資訊
    # 若查詢非今日或次日，DGPA 即時頁面不具參考性
    if target_date != today and target_date != (today + timedelta(days=1)):
        return False, "非即時天然災害通報窗口日期"

    try:
        resp = requests.get(
            DGPA_NDS_URL,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "text/html,application/xhtml+xml",
            },
            timeout=timeout,
        )
        if resp.status_code != 200:
            return False, f"DGPA 回應碼異常 ({resp.status_code})"

        resp.encoding = "utf-8"
        content = resp.text

        # 1. 若明確載明「無停班停課訊息」，則全台正常上班
        if "無停班停課訊息" in content:
            return False, "全台無天然災害停班停課訊息"

        # 2. 清理 HTML 標籤後檢視台北市情形
        # 尋找包含「臺北市」或「台北市」的表格行或區塊
        clean_text = re.sub(r"<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>", "", content, flags=re.I)
        clean_text = re.sub(r"<style\b[^<]*(?:(?!<\/style>)<[^<]*)*<\/style>", "", clean_text, flags=re.I)
        clean_text = html.unescape(clean_text)

        # 針對「臺北市」或「台北市」擷取描述
        pattern = r"(臺北市|台北市)[\s\S]{0,100}?(停止上班|照常上班|全日停止|尚未列入)"
        match = re.search(pattern, clean_text)

        if match:
            city = match.group(1)
            status = match.group(2)

            if "停止上班" in status or "全日停止" in status:
                return True, f"{city}宣布停止上班（颱風/天然災害休市）"
            elif "照常上班" in status:
                return False, f"{city}照常上班（正常交易）"

        # 亦可搜尋通案性「全日停止上班」且位於北部/臺北市鄰近
        if re.search(r"(臺北市|台北市)[\s\S]{0,300}?(停止上班|全日停止上班及上課|停止上班及上課)", clean_text):
            return True, "台北市政府宣布停止上班（颱風/天然災害休市）"

    except Exception as exc:
        return False, f"天然災害查詢逾時或未連線 ({type(exc).__name__})"

    return False, "無台北市停止上班資訊"


def get_extra_closed_dates() -> set[str]:
    """取得由環境變數或自訂設定傳入的額外休市日"""
    env_dates = os.environ.get("EXTRA_CLOSED_DATES", "").strip()
    if not env_dates:
        return set()
    dates = set()
    for raw in env_dates.split(","):
        cleaned = raw.strip()
        if cleaned:
            try:
                d = parse_date(cleaned)
                dates.add(d.isoformat())
            except Exception:
                pass
    return dates


def is_market_open(target: Any = None) -> tuple[bool, str, dict[str, Any]]:
    """
    核心開休市判定函式。

    參數：
        target: 可傳入 None（代表今天）、date、datetime 或 'YYYY-MM-DD' 字串。

    回傳：
        (is_open: bool, reason: str, details: dict)
        - is_open: True 為開盤交易日，False 為休市。
        - reason: 判斷原因（繁體中文說明）。
        - details: 詳細資訊字典。
    """
    target_date = parse_date(target)
    day_str = target_date.isoformat()
    weekday_idx = target_date.weekday()
    weekday_names = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    weekday_name = weekday_names[weekday_idx]

    details: dict[str, Any] = {
        "date": day_str,
        "weekday": weekday_name,
        "is_weekend": False,
        "is_scheduled_holiday": False,
        "is_typhoon_closure": False,
        "is_extra_closed": False,
    }

    # 1. 週末例假日檢查（週六、週日休市）
    # 依台灣現行制度，週末補上班日台股亦不開盤交易
    if weekday_idx >= 5:
        details["is_weekend"] = True
        return False, f"週末例假日休市 ({weekday_name})", details

    # 2. 外部手動指定休市檢查 (EXTRA_CLOSED_DATES)
    extra_closed = get_extra_closed_dates()
    if day_str in extra_closed:
        details["is_extra_closed"] = True
        return False, f"手動指定特殊休市日 ({day_str})", details

    # 3. 證交所（TWSE）排定國定假日與節慶休市檢查
    year = target_date.year
    twse_calendar = fetch_twse_calendar(year)
    if day_str in twse_calendar:
        holiday_name = twse_calendar[day_str]
        details["is_scheduled_holiday"] = True
        details["holiday_name"] = holiday_name
        return False, f"國定假日/排定休市: {holiday_name}", details

    # 4. 天然災害 / 颱風天停班自動檢查（依台北市停班公告）
    is_typhoon, typhoon_reason = check_dgpa_typhoon_closure(target_date)
    if is_typhoon:
        details["is_typhoon_closure"] = True
        details["typhoon_reason"] = typhoon_reason
        return False, f"天然災害/颱風停班休市: {typhoon_reason}", details

    # 5. 通過所有檢查，今日為正常交易日
    return True, "台股正常開盤交易日", details


def main():
    parser = argparse.ArgumentParser(description="EasyStock Taiwan Market Calendar & Open Status")
    parser.add_argument("--check-today", action="store_true", help="檢查今天是否開盤（若開盤 exit 0，若休市 exit 1）")
    parser.add_argument("--check-tomorrow", action="store_true", help="檢查明天是否開盤")
    parser.add_argument("--check-date", type=str, help="檢查指定日期 (YYYY-MM-DD)")
    parser.add_argument("--json", action="store_true", help="輸出 JSON 格式")
    parser.add_argument("--sync", type=int, help="同步指定年份 TWSE 官方行事曆至快取")

    args = parser.parse_args()

    if args.sync:
        year = args.sync
        calendar = fetch_twse_calendar(year)
        print(f"✅ 已同步 {year} 年 TWSE 行事曆，共 {len(calendar)} 個排定休市日")
        return

    target = None
    if args.check_today:
        target = now_tpe().date()
    elif args.check_tomorrow:
        target = now_tpe().date() + timedelta(days=1)
    elif args.check_date:
        target = args.check_date
    else:
        target = now_tpe().date()

    is_open, reason, details = is_market_open(target)

    if args.json:
        output = {"is_open": is_open, "reason": reason, **details}
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        status_icon = "🟢 [開盤]" if is_open else "🔴 [休市]"
        print(f"{status_icon} 日期: {details['date']} ({details['weekday']}) | 原因: {reason}")

    # 若指定 --check-today 且休市，以 exit 1 結束，供 systemd ExecCondition 判定
    if (args.check_today or args.check_tomorrow or args.check_date) and not is_open:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
