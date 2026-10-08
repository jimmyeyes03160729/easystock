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

# 2027 年暫定休市表：TWSE 尚未公布時使用，官方公布（API 或快取）後一律以官方為準。
# 來源：行政院人事行政總處 116 年政府行政機關辦公日曆表（115.05.21 院授人培字第1153026132號函）的平日放假日，
# 加上 TWSE 歷年慣例「春節假期前最後兩個交易日市場無交易」（2024、2025、2026 皆是），保守視為休市。
PROVISIONAL_2027_CLOSED: dict[str, str] = {
    "2027-01-01": "中華民國開國紀念日（暫定，DGPA）",
    "2027-02-02": "市場無交易，僅辦理結算交割作業（暫定，依 TWSE 慣例推估）",
    "2027-02-03": "市場無交易，僅辦理結算交割作業（暫定，依 TWSE 慣例推估）",
    "2027-02-04": "農曆除夕前一日（暫定，DGPA）",
    "2027-02-05": "農曆除夕（暫定，DGPA）",
    "2027-02-08": "春節（暫定，DGPA）",
    "2027-02-09": "春節補假（暫定，DGPA）",
    "2027-02-10": "春節補假（暫定，DGPA）",
    "2027-03-01": "和平紀念日補假（暫定，DGPA）",
    "2027-04-05": "民族掃墓節（暫定，DGPA）",
    "2027-04-06": "兒童節補假（暫定，DGPA）",
    "2027-04-30": "勞動節補假（暫定，DGPA）",
    "2027-06-09": "端午節（暫定，DGPA）",
    "2027-09-15": "中秋節（暫定，DGPA）",
    "2027-09-28": "孔子誕辰紀念日 / 教師節（暫定，DGPA）",
    "2027-10-11": "國慶日補假（暫定，DGPA）",
    "2027-10-25": "臺灣光復暨金門古寧頭大捷紀念日（暫定，DGPA）",
    "2027-12-24": "行憲紀念日補假（暫定，DGPA）",
    "2027-12-31": "2028 開國紀念日補假（暫定，DGPA）",
}
PROVISIONAL_CLOSED: dict[int, dict[str, str]] = {2027: PROVISIONAL_2027_CLOSED}

# 台指期日盤（08:45 開盤）是否已成交：颱風、地震等臨時休市時期交所與證交所同步停止交易。
TAIFEX_QUOTE_URL = "https://mis.taifex.com.tw/futures/api/getQuoteList"
FUTURES_CHECK_START = (8, 50)    # 開盤後 5 分鐘才判定，避免剛開盤尚無成交
FUTURES_CHECK_END = (13, 45)

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


class CalendarUnavailable(RuntimeError):
    """指定年份沒有可信的官方行事曆；呼叫端必須視為無法確認，而非開盤。"""


def _same_year(closed_map: Any, year: int) -> dict[str, str]:
    """只保留屬於指定年份的日期；TWSE 曾對未知年份回傳當年度資料。"""
    if not isinstance(closed_map, dict):
        return {}
    prefix = f"{year:04d}-"
    return {str(d): str(n) for d, n in closed_map.items() if str(d).startswith(prefix)}


def _load_cache_calendar(year: int) -> dict[str, str] | None:
    """從本地快取讀取已下載之行事曆"""
    cache_path = CALENDAR_CACHE_DIR / f"calendar-{year}.json"
    if not cache_path.exists():
        return None
    try:
        content = json.loads(cache_path.read_text(encoding="utf-8"))
        closed_map = None
        if isinstance(content, dict) and "closed_map" in content:
            closed_map = content["closed_map"]
        elif isinstance(content, dict) and "closed" in content:
            closed_map = {d: "排定休市" for d in content["closed"]}
        # 舊版可能把其他年份資料存成本年度快取；不同年份的快取一律視為不存在。
        closed_map = _same_year(closed_map, year)
        return closed_map if len(closed_map) >= 5 else None
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
    若網路不通或失敗，依序回退至本地快取與內建表；
    三者皆無該年份資料時拋出 CalendarUnavailable，不默認為開盤。
    """
    cached = _load_cache_calendar(year)

    # TWSE 以 date 參數選擇年度；queryYear 會被忽略並回傳當年度資料。
    url = f"{TWSE_HOLIDAY_URL}?response=json&date={year:04d}0101"

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

                closed_map = _same_year(closed_map, year)
                if len(closed_map) >= 5:
                    _save_cache_calendar(year, closed_map)
                    return closed_map
    except Exception:
        pass

    if cached:
        return cached

    if year == 2026:
        return dict(BUILTIN_2026_CLOSED)

    if year in PROVISIONAL_CLOSED:
        return dict(PROVISIONAL_CLOSED[year])

    raise CalendarUnavailable(f"TWSE {year} 年行事曆尚未取得；請於官方公布後執行 market_calendar.py --sync {year}")


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


def _futures_cache_path(day: date) -> Path:
    return CALENDAR_CACHE_DIR / f"futures-open-{day.isoformat()}.json"


def check_taifex_day_session(now: datetime | None = None, timeout: float = 6.0) -> tuple[str, str]:
    """
    以台指期近月合約當日是否已成交，判斷今日期貨日盤（08:45 開盤）有無開市。

    回傳 (state, reason)，state 為：
        "OPEN"    今日已有成交
        "CLOSED"  08:50 後仍無任何今日成交 → 視為臨時休市（颱風、地震等）
        "UNKNOWN" 不在判定時段、查詢失敗或資料不足 → 不做判斷，交由其他規則
    OPEN/CLOSED 當日結果會快取，避免盤中反覆查詢。
    """
    now = (now or now_tpe()).astimezone(TPE)
    if os.environ.get("EASYSTOCK_FUTURES_OPEN_CHECK", "1") == "0":
        return "UNKNOWN", "期貨開盤檢查已停用"
    hm = (now.hour, now.minute)
    if not (FUTURES_CHECK_START <= hm < FUTURES_CHECK_END):
        return "UNKNOWN", "非台指期日盤判定時段"
    cache = _futures_cache_path(now.date())
    try:
        cached = json.loads(cache.read_text(encoding="utf-8"))
        if cached.get("state") in ("OPEN", "CLOSED"):
            return cached["state"], cached.get("reason", "")
    except Exception:
        pass
    body = {"MarketType": "0", "SymbolType": "F", "KindID": "1", "CID": "TXF", "ExpireMonth": "",
            "RowSize": "全部", "PageNo": "", "SortColumn": "", "AscDesc": "A"}
    try:
        resp = requests.post(TAIFEX_QUOTE_URL, json=body, timeout=timeout,
                             headers={"User-Agent": "Mozilla/5.0 (compatible; EasyStock/1.0)"})
        if resp.status_code != 200:
            return "UNKNOWN", f"期交所回應碼異常 ({resp.status_code})"
        quotes = ((resp.json() or {}).get("RtData") or {}).get("QuoteList") or []
    except Exception as exc:
        return "UNKNOWN", f"期交所查詢失敗 ({type(exc).__name__})"
    futures = [q for q in quotes if str(q.get("SymbolID", "")).startswith("TXF") and str(q.get("SymbolID", "")).endswith("-F")]
    if not futures:
        return "UNKNOWN", "期交所未回傳台指期合約"
    today = now.strftime("%Y%m%d")

    def volume(q):
        try:
            return float(str(q.get("CTotalVolume") or "0").replace(",", ""))
        except ValueError:
            return 0.0

    traded = [q for q in futures if str(q.get("CDate")) == today and volume(q) > 0]
    if traded:
        state, reason = "OPEN", f"台指期今日已成交（{traded[0].get('DispCName', 'TXF')}）"
    elif all(str(q.get("CDate") or "") < today for q in futures):
        state, reason = "CLOSED", "台指期日盤 08:50 後仍無今日成交（判定臨時休市）"
    else:
        return "UNKNOWN", "台指期資料日期與成交量不一致，不做判斷"
    try:
        CALENDAR_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"state": state, "reason": reason, "checked_at": now.isoformat(timespec="seconds")},
                                    ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    return state, reason


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
        "is_futures_closure": False,
        "provisional_calendar": False,
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
    details["provisional_calendar"] = twse_calendar == PROVISIONAL_CLOSED.get(year)
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

    # 5. 當日盤中：台指期日盤沒有成交 → 臨時休市（颱風、地震等未及時反映於公告時的備援）
    if target_date == now_tpe().date():
        fut_state, fut_reason = check_taifex_day_session()
        details["futures_day_session"] = fut_state
        details["futures_reason"] = fut_reason
        if fut_state == "CLOSED":
            details["is_futures_closure"] = True
            return False, f"臨時休市: {fut_reason}", details

    # 6. 通過所有檢查，今日為正常交易日
    return True, "台股正常開盤交易日", details


def main():
    parser = argparse.ArgumentParser(description="EasyStock Taiwan Market Calendar & Open Status")
    parser.add_argument("--check-today", action="store_true", help="檢查今天是否開盤（若開盤 exit 0，若休市 exit 1）")
    parser.add_argument("--check-tomorrow", action="store_true", help="檢查明天是否開盤")
    parser.add_argument("--check-date", type=str, help="檢查指定日期 (YYYY-MM-DD)")
    parser.add_argument("--json", action="store_true", help="輸出 JSON 格式")
    parser.add_argument("--sync", type=int, help="同步指定年份 TWSE 官方行事曆至快取")

    args = parser.parse_args()

    try:
        if args.sync:
            year = args.sync
            calendar = fetch_twse_calendar(year)
            if calendar == PROVISIONAL_CLOSED.get(year):
                print(f"⚠️ TWSE 尚未公布 {year} 年行事曆；目前使用 DGPA 暫定表（{len(calendar)} 天），公布後請再執行 --sync {year}",
                      file=sys.stderr)
                sys.exit(2)
            print(f"✅ 已同步 {year} 年 TWSE 行事曆，共 {len(calendar)} 個排定休市日")
            return
    except CalendarUnavailable as exc:
        print(f"❌ {exc}", file=sys.stderr)
        sys.exit(2)

    target = None
    if args.check_today:
        target = now_tpe().date()
    elif args.check_tomorrow:
        target = now_tpe().date() + timedelta(days=1)
    elif args.check_date:
        target = args.check_date
    else:
        target = now_tpe().date()

    try:
        is_open, reason, details = is_market_open(target)
    except CalendarUnavailable as exc:
        # 無法確認時以非零結束；systemd ExecCondition 會略過而不是當作開盤。
        print(f"⚠️ [無法確認] {exc}", file=sys.stderr)
        sys.exit(2)

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
