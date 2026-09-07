import json
import math
import os
import re
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable

import firebase_admin
import numpy as np
import requests
from firebase_admin import credentials, db

# ============================================================
# Configuration
# ============================================================
FIREBASE_DATABASE_URL = os.environ.get("FIREBASE_DATABASE_URL")
FIREBASE_SERVICE_ACCOUNT_JSON = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")
FIREBASE_ROOT_PATH = os.environ.get("FIREBASE_ROOT_PATH", "market_data").strip("/") or "market_data"
FUGLE_API_KEY = os.environ.get("FUGLE_API_KEY", "").strip()

HOT_STOCK_COUNT = int(os.environ.get("HOT_STOCK_COUNT", "500"))
KLINE_DAYS = int(os.environ.get("KLINE_DAYS", "250"))
MIN_TECHNICAL_DAYS = int(os.environ.get("MIN_TECHNICAL_DAYS", "60"))
INSTITUTION_DAYS = int(os.environ.get("INSTITUTION_DAYS", "15"))
LEGACY_FUNDAMENTAL_MAX_AGE_DAYS = int(os.environ.get("LEGACY_FUNDAMENTAL_MAX_AGE_DAYS", "120"))
HTTP_TIMEOUT = float(os.environ.get("HTTP_TIMEOUT", "12"))
FUGLE_MIN_INTERVAL_SECONDS = float(os.environ.get("FUGLE_MIN_INTERVAL_SECONDS", "1.05"))
FUGLE_BOOTSTRAP_MAX_PER_RUN = int(os.environ.get("FUGLE_BOOTSTRAP_MAX_PER_RUN", "20"))
HTTP_WORKERS = max(2, min(8, int(os.environ.get("HTTP_WORKERS", "6"))))
BACKTEST_HISTORY_BARS = max(KLINE_DAYS, int(os.environ.get("BACKTEST_HISTORY_BARS", "1260")))
VALIDATION_OOS_DAYS = max(60, int(os.environ.get("VALIDATION_OOS_DAYS", "252")))
BACKTEST_TOTAL_COST_BPS = max(0.0, float(os.environ.get("BACKTEST_TOTAL_COST_BPS", "70")))
MODEL_VERSION = "0.70"

TWSE_BASE = "https://openapi.twse.com.tw/v1"
TPEX_BASE = "https://www.tpex.org.tw/openapi/v1"
TWSE_T86_URL = "https://www.twse.com.tw/rwd/zh/fund/T86"
FUGLE_BASE = "https://api.fugle.tw/marketdata/v1.0/stock"

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; easystock/0.70; +https://github.com/jimmyeyes03160729/easystock)",
    "Accept": "application/json,text/plain,*/*",
}
_THREAD_LOCAL = threading.local()
_LAST_FUGLE_CALL = 0.0


def get_http_session() -> requests.Session:
    session = getattr(_THREAD_LOCAL, "session", None)
    if session is None:
        session = requests.Session()
        session.headers.update(DEFAULT_HEADERS)
        _THREAD_LOCAL.session = session
    return session

# ============================================================
# Generic helpers
# ============================================================
def safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        text = str(value).strip().replace(",", "").replace("%", "")
        if text in {"", "--", "---", "-", "N/A", "nan", "None", "X"}:
            return None
        x = float(text)
        if math.isnan(x) or math.isinf(x):
            return None
        return x
    except (TypeError, ValueError):
        return None


def safe_int(value: Any) -> int | None:
    x = safe_float(value)
    return None if x is None else int(round(x))


def normalize_symbol(value: Any) -> str:
    return str(value or "").strip()


def normalize_key(value: Any) -> str:
    text = str(value or "").lower().strip()
    text = text.replace("（", "(").replace("）", ")").replace("％", "%")
    return re.sub(r"[\s_\-:/()（）\[\]{}%,，。．·]+", "", text)


def is_common_stock_code(symbol: str) -> bool:
    # easystock focuses on regular listed/OTC equities, not ETFs/ETNs/warrants.
    return len(symbol) == 4 and symbol.isdigit() and not symbol.startswith("0")


def roc_date_to_iso(value: Any) -> str | None:
    text = re.sub(r"\D", "", str(value or "").strip())
    if len(text) == 7:  # YYYMMDD
        try:
            year = int(text[:3]) + 1911
            return f"{year:04d}-{text[3:5]}-{text[5:7]}"
        except ValueError:
            return None
    if len(text) == 8 and int(text[:4]) >= 1900:
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return None


def iso_to_yyyymmdd(value: str) -> str:
    return value.replace("-", "")[:8]


def parse_iso_date(value: Any) -> date | None:
    text = str(value or "")[:10]
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def first_value(row: dict, aliases: Iterable[str]) -> Any:
    if not isinstance(row, dict):
        return None
    by_norm = {normalize_key(k): v for k, v in row.items()}
    for alias in aliases:
        key = normalize_key(alias)
        if key in by_norm:
            return by_norm[key]
    return None


def value_by_contains(row: dict, required_fragments: Iterable[str], excluded_fragments: Iterable[str] = ()) -> Any:
    req = [normalize_key(x) for x in required_fragments]
    exc = [normalize_key(x) for x in excluded_fragments]
    for key, value in row.items():
        nk = normalize_key(key)
        if all(fragment in nk for fragment in req) and not any(fragment in nk for fragment in exc):
            return value
    return None


def symbol_from_row(row: dict) -> str:
    return normalize_symbol(
        first_value(
            row,
            [
                "Code",
                "SecuritiesCompanyCode",
                "公司代號",
                "證券代號",
                "股票代號",
            ],
        )
    )


def name_from_row(row: dict) -> str:
    return str(
        first_value(row, ["Name", "CompanyName", "公司名稱", "證券名稱", "股票名稱"]) or ""
    ).strip()


def fetch_json(url: str, *, params: dict | None = None, required: bool = False, label: str = "") -> Any:
    try:
        print(f"[HTTP] {label or url}")
        response = get_http_session().get(url, params=params, timeout=HTTP_TIMEOUT)
        response.raise_for_status()
        payload = response.json()
        if required and payload in (None, [], {}):
            raise RuntimeError("empty payload")
        return payload
    except Exception as exc:
        print(f"[WARN] {label or url} failed: {exc}")
        if required:
            raise
        return None


def fetch_many(requests_spec: list[dict]) -> dict[str, Any]:
    """Fetch independent JSON endpoints concurrently and return them by key."""
    out: dict[str, Any] = {}
    if not requests_spec:
        return out
    workers = min(HTTP_WORKERS, len(requests_spec))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        future_map = {
            pool.submit(
                fetch_json,
                spec["url"],
                params=spec.get("params"),
                required=bool(spec.get("required", False)),
                label=spec.get("label", spec["key"]),
            ): spec["key"]
            for spec in requests_spec
        }
        for future in as_completed(future_map):
            key = future_map[future]
            out[key] = future.result()
    return out


def validate_environment() -> None:
    if not FIREBASE_DATABASE_URL:
        raise ValueError("找不到 FIREBASE_DATABASE_URL")
    if not FIREBASE_SERVICE_ACCOUNT_JSON:
        raise ValueError("找不到 FIREBASE_SERVICE_ACCOUNT_JSON")
    if not FIREBASE_DATABASE_URL.startswith("https://"):
        raise ValueError("FIREBASE_DATABASE_URL 必須是 https:// 開頭")

    try:
        service_account = json.loads(FIREBASE_SERVICE_ACCOUNT_JSON)
    except json.JSONDecodeError as exc:
        raise ValueError("FIREBASE_SERVICE_ACCOUNT_JSON 不是有效 JSON") from exc

    required_keys = {"type", "project_id", "private_key", "client_email"}
    missing = sorted(required_keys - set(service_account))
    if missing:
        raise ValueError(f"Firebase service account 缺少欄位：{', '.join(missing)}")


def init_firebase():
    service_account = json.loads(FIREBASE_SERVICE_ACCOUNT_JSON)
    if not firebase_admin._apps:
        cred = credentials.Certificate(service_account)
        firebase_admin.initialize_app(cred, {"databaseURL": FIREBASE_DATABASE_URL})
    return db.reference(f"/{FIREBASE_ROOT_PATH}")


# ============================================================
# TWSE / TPEx current market data
# ============================================================
def parse_twse_quotes(rows: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for row in rows or []:
        sym = normalize_symbol(row.get("Code"))
        if not is_common_stock_code(sym):
            continue
        close = safe_float(row.get("ClosingPrice"))
        open_v = safe_float(row.get("OpeningPrice"))
        high = safe_float(row.get("HighestPrice"))
        low = safe_float(row.get("LowestPrice"))
        volume = safe_int(row.get("TradeVolume"))
        amount = safe_float(row.get("TradeValue"))
        day = roc_date_to_iso(row.get("Date"))
        if close is None or open_v is None or high is None or low is None or not day:
            continue
        out[sym] = {
            "symbol": sym,
            "name": str(row.get("Name") or sym).strip(),
            "exchange": "TWSE",
            "date": day,
            "open": open_v,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "amount": amount if amount is not None else (close * volume if volume else None),
        }
    return out


def parse_tpex_quotes(rows: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for row in rows or []:
        sym = normalize_symbol(first_value(row, ["SecuritiesCompanyCode", "Code", "公司代號"]))
        if not is_common_stock_code(sym):
            continue
        close = safe_float(first_value(row, ["Close", "ClosingPrice", "收盤價"]))
        open_v = safe_float(first_value(row, ["Open", "OpeningPrice", "開盤價"]))
        high = safe_float(first_value(row, ["High", "HighestPrice", "最高價"]))
        low = safe_float(first_value(row, ["Low", "LowestPrice", "最低價"]))
        volume = safe_int(first_value(row, ["TradingShares", "TradeVolume", "成交股數"]))
        amount = safe_float(first_value(row, ["TransactionAmount", "TradeValue", "成交金額"]))
        day = roc_date_to_iso(first_value(row, ["Date", "日期", "交易日期"]))
        if close is None or open_v is None or high is None or low is None or not day:
            continue
        out[sym] = {
            "symbol": sym,
            "name": name_from_row(row) or sym,
            "exchange": "TPEx",
            "date": day,
            "open": open_v,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "amount": amount if amount is not None else (close * volume if volume else None),
        }
    return out


def parse_valuation(rows: list[dict], exchange: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for row in rows or []:
        sym = symbol_from_row(row)
        if not is_common_stock_code(sym):
            continue
        pe = safe_float(first_value(row, ["PEratio", "PriceEarningRatio", "本益比"]))
        pb = safe_float(first_value(row, ["PBratio", "PriceBookRatio", "股價淨值比"]))
        yield_pct = safe_float(first_value(row, ["DividendYield", "殖利率(%)", "殖利率％", "殖利率"]))
        out[sym] = {"pe": pe, "pb": pb, "exchange_yield_pct": yield_pct, "valuation_source": exchange}
    return out


def parse_company_basic(rows: list[dict], exchange: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for row in rows or []:
        sym = symbol_from_row(row)
        if not is_common_stock_code(sym):
            continue
        category = first_value(row, ["產業別", "產業類別", "Industry", "IndustryType"])
        out[sym] = {
            "name": name_from_row(row) or sym,
            "category": str(category or ("上市" if exchange == "TWSE" else "上櫃")).strip(),
            "exchange": exchange,
        }
    return out


# ============================================================
# Revenue, dividends, financial statements
# ============================================================
def parse_revenue(rows: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for row in rows or []:
        sym = symbol_from_row(row)
        if not is_common_stock_code(sym):
            continue
        yoy = safe_float(
            first_value(
                row,
                [
                    "營業收入-去年同月增減(%)",
                    "營業收入-去年同月增減％",
                    "去年同月增減(%)",
                    "去年同月增減％",
                ],
            )
        )
        month = first_value(row, ["資料年月", "年月", "YearMonth"])
        out[sym] = {"rev_yoy": yoy, "revenue_period": str(month or "").strip() or None}
    return out


def dividend_cash_per_share(row: dict) -> float:
    values = []
    for key, value in row.items():
        nk = normalize_key(key)
        if "現金" not in nk or "元股" not in nk:
            continue
        if "總金額" in nk or "期初" in nk or "期末" in nk:
            continue
        if "股東配發" not in nk and "現金股利" not in nk:
            continue
        v = safe_float(value)
        if v is not None and v > 0:
            values.append(v)
    return float(sum(values))


def parse_dividends(rows: list[dict], asof: date) -> dict[str, dict]:
    grouped: dict[str, list[dict]] = {}
    seen: set[tuple] = set()

    for row in rows or []:
        sym = symbol_from_row(row)
        if not is_common_stock_code(sym):
            continue
        cash = dividend_cash_per_share(row)
        if cash <= 0:
            continue
        decision_raw = first_value(row, ["董事會（擬議）股利分派日", "董事會(擬議)股利分派日", "董事會決議日"])
        decision_iso = roc_date_to_iso(decision_raw)
        decision_date = parse_iso_date(decision_iso) if decision_iso else None
        div_year_raw = first_value(row, ["股利年度", "年度"])
        try:
            div_year = int(str(div_year_raw).strip()) + 1911 if div_year_raw not in (None, "") and int(str(div_year_raw).strip()) < 1900 else int(str(div_year_raw).strip())
        except (TypeError, ValueError):
            div_year = decision_date.year if decision_date else None
        period = str(first_value(row, ["股利所屬期間", "股利所屬年(季)度", "期別"]) or "").strip()
        dedupe = (sym, div_year, period, round(cash, 8), decision_iso)
        if dedupe in seen:
            continue
        seen.add(dedupe)
        grouped.setdefault(sym, []).append(
            {"cash": cash, "decision_date": decision_date, "dividend_year": div_year, "period": period}
        )

    out: dict[str, dict] = {}
    cutoff = asof - timedelta(days=365)
    for sym, items in grouped.items():
        items.sort(key=lambda x: (x["decision_date"] or date.min, x["dividend_year"] or 0))
        latest = items[-1]["cash"] if items else None
        ttm_items = [x for x in items if x["decision_date"] and cutoff < x["decision_date"] <= asof]
        if ttm_items:
            ttm = float(sum(x["cash"] for x in ttm_items))
        else:
            years = [x["dividend_year"] for x in items if x["dividend_year"]]
            latest_year = max(years) if years else None
            ttm = float(sum(x["cash"] for x in items if x["dividend_year"] == latest_year)) if latest_year else None

        annual: dict[int, float] = {}
        for item in items:
            year = item["dividend_year"]
            if year:
                annual[year] = annual.get(year, 0.0) + item["cash"]
        positive_years = sorted(y for y, v in annual.items() if v > 0)
        continuity = 0
        if positive_years:
            start = positive_years[-1]
            year_set = set(positive_years)
            for y in range(start, start - 5, -1):
                if y in year_set:
                    continuity += 1
                else:
                    break
        out[sym] = {
            "dividend_latest": latest,
            "dividend_ttm": ttm,
            "dividend_continuity_years": continuity,
        }
    return out


def quarter_from_row(row: dict) -> int | None:
    raw = first_value(row, ["季別", "季度", "季", "Season", "Quarter"])
    text = str(raw or "")
    match = re.search(r"([1-4])", text)
    if match:
        return int(match.group(1))
    return None


def parse_income_statements(all_rows: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for row in all_rows or []:
        sym = symbol_from_row(row)
        if not is_common_stock_code(sym):
            continue

        revenue = safe_float(first_value(row, ["營業收入", "營業收入合計", "收入", "收益"]))
        if revenue is None:
            revenue = safe_float(value_by_contains(row, ["營業收入"], ["百分比", "比率"]))

        gross = safe_float(first_value(row, ["營業毛利（毛損）", "營業毛利(毛損)", "營業毛利（毛損）淨額", "營業毛利"]))
        if gross is None:
            gross = safe_float(value_by_contains(row, ["營業毛利"], ["率", "%"]))

        op_income = safe_float(first_value(row, ["營業利益（損失）", "營業利益(損失)", "營業利益", "營業淨利（淨損）"]))
        if op_income is None:
            op_income = safe_float(value_by_contains(row, ["營業利益"], ["率", "%"]))

        net_income = safe_float(
            first_value(
                row,
                [
                    "本期淨利（淨損）歸屬於母公司業主",
                    "本期淨利(淨損)歸屬於母公司業主",
                    "歸屬於母公司業主之淨利（損）",
                    "本期淨利（淨損）",
                    "本期淨利(淨損)",
                ],
            )
        )
        eps = safe_float(first_value(row, ["基本每股盈餘（元）", "基本每股盈餘(元)", "基本每股盈餘", "每股盈餘"]))
        q = quarter_from_row(row)
        if sym not in out or (q or 0) >= (out[sym].get("quarter") or 0):
            out[sym] = {
                "statement_revenue": revenue,
                "gross_profit": gross,
                "operating_income": op_income,
                "net_income": net_income,
                "eps": eps,
                "quarter": q,
                "gross_margin": (gross / revenue * 100) if gross is not None and revenue not in (None, 0) else None,
                "operating_margin": (op_income / revenue * 100) if op_income is not None and revenue not in (None, 0) else None,
            }
    return out


def parse_balance_sheets(all_rows: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for row in all_rows or []:
        sym = symbol_from_row(row)
        if not is_common_stock_code(sym):
            continue
        assets = safe_float(first_value(row, ["資產總額", "資產總計", "資產合計", "資產"]))
        liabilities = safe_float(first_value(row, ["負債總額", "負債總計", "負債合計", "負債"]))
        equity = safe_float(
            first_value(
                row,
                [
                    "權益總額",
                    "權益總計",
                    "權益合計",
                    "歸屬於母公司業主之權益合計",
                    "權益",
                ],
            )
        )
        q = quarter_from_row(row)
        if sym not in out or (q or 0) >= (out[sym].get("quarter") or 0):
            out[sym] = {
                "assets": assets,
                "liabilities": liabilities,
                "equity": equity,
                "quarter": q,
                "debt_ratio": (liabilities / assets * 100) if liabilities is not None and assets not in (None, 0) else None,
            }
    return out


def combine_fundamentals(income: dict[str, dict], balance: dict[str, dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for sym in set(income) | set(balance):
        inc = income.get(sym, {})
        bal = balance.get(sym, {})
        q = inc.get("quarter") or bal.get("quarter")
        net = inc.get("net_income")
        equity = bal.get("equity")
        annualizer = (4 / q) if q in {1, 2, 3, 4} else 1
        roe = (net * annualizer / equity * 100) if net is not None and equity not in (None, 0) else None
        out[sym] = {
            "eps": inc.get("eps"),
            "gross_margin": inc.get("gross_margin"),
            "operating_margin": inc.get("operating_margin"),
            "debt_ratio": bal.get("debt_ratio"),
            "roe": roe,
            "fundamental_quarter": q,
        }
    return out


# ============================================================
# Institutional flows
# ============================================================
def parse_twse_t86(payload: dict) -> dict[str, int]:
    if not isinstance(payload, dict):
        return {}
    fields = payload.get("fields") or []
    data_rows = payload.get("data") or []
    out: dict[str, int] = {}
    for values in data_rows:
        if not isinstance(values, list) or len(values) != len(fields):
            continue
        row = dict(zip(fields, values))
        sym = normalize_symbol(first_value(row, ["證券代號", "股票代號"]))
        if not is_common_stock_code(sym):
            continue
        foreign = safe_int(first_value(row, ["外陸資買賣超股數(不含外資自營商)", "外資及陸資買賣超股數"]))
        trust = safe_int(first_value(row, ["投信買賣超股數"]))
        if foreign is not None or trust is not None:
            out[sym] = int((foreign or 0) + (trust or 0))
    return out


def parse_tpex_institution(rows: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in rows or []:
        sym = symbol_from_row(row)
        if not is_common_stock_code(sym):
            continue
        foreign = safe_int(
            first_value(
                row,
                [
                    "ForeignInvestorsincludeMainlandAreaInvestors(ForeignDealersexcluded)-Difference",
                    "Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Difference",
                    "ForeignInvestors-Difference",
                ],
            )
        )
        trust = safe_int(
            first_value(
                row,
                [
                    "SecuritiesInvestmentTrustCompanies-Difference",
                    "Securities Investment Trust Companies-Difference",
                ],
            )
        )
        if foreign is None:
            foreign = safe_int(value_by_contains(row, ["foreign", "difference"]))
        if trust is None:
            trust = safe_int(value_by_contains(row, ["investmenttrust", "difference"]))
        if foreign is not None or trust is not None:
            out[sym] = int((foreign or 0) + (trust or 0))
        else:
            total = safe_int(first_value(row, ["TotalDifference", "Difference", "合計買賣超"]))
            if total is not None:
                out[sym] = total
    return out


def merge_institution_history(previous: list[dict] | None, today: str, current_net: int | None) -> list[dict]:
    merged: dict[str, int] = {}
    for item in previous or []:
        if not isinstance(item, dict):
            continue
        day = str(item.get("time") or "")[:10]
        value = safe_int(item.get("net_shares"))
        if day and value is not None:
            merged[day] = value
    if current_net is not None:
        merged[today] = current_net
    rows = [{"time": day, "net_shares": merged[day]} for day in sorted(merged)][-INSTITUTION_DAYS:]
    return rows


# ============================================================
# Kline and Fugle migration helpers
# ============================================================
def normalize_kline(rows: list[dict] | dict | None, limit: int | None = None) -> list[dict]:
    by_day: dict[str, dict] = {}
    source = rows.values() if isinstance(rows, dict) else (rows or [])
    for row in source:
        if not isinstance(row, dict):
            continue
        day = str(row.get("time") or row.get("date") or "")[:10]
        if not parse_iso_date(day):
            continue
        o = safe_float(row.get("open"))
        h = safe_float(row.get("high"))
        l = safe_float(row.get("low"))
        c = safe_float(row.get("close"))
        v = safe_int(row.get("volume"))
        if None in (o, h, l, c):
            continue
        by_day[day] = {
            "time": day,
            "open": round(o, 4),
            "high": round(h, 4),
            "low": round(l, 4),
            "close": round(c, 4),
            "volume": v,
            "amount": safe_float(row.get("amount")) or ((c * v) if v else None),
        }
    ordered = [by_day[k] for k in sorted(by_day)]
    if limit is None:
        limit = KLINE_DAYS
    return ordered[-limit:] if limit > 0 else ordered


def _wait_for_fugle_rate_limit() -> None:
    global _LAST_FUGLE_CALL
    elapsed = time.monotonic() - _LAST_FUGLE_CALL
    if elapsed < FUGLE_MIN_INTERVAL_SECONDS:
        time.sleep(FUGLE_MIN_INTERVAL_SECONDS - elapsed)
    _LAST_FUGLE_CALL = time.monotonic()


def fetch_fugle_history(symbol: str, end_day: str) -> list[dict]:
    if not FUGLE_API_KEY:
        return []
    end_date = parse_iso_date(end_day) or date.today()
    start_date = end_date - timedelta(days=360)
    _wait_for_fugle_rate_limit()
    payload = fetch_json(
        f"{FUGLE_BASE}/historical/candles/{symbol}",
        params={
            "from": start_date.isoformat(),
            "to": end_date.isoformat(),
            "timeframe": "D",
            "adjusted": "false",
            "fields": "open,high,low,close,volume,turnover",
            "sort": "asc",
        },
        label=f"Fugle {symbol} history",
    )
    rows = payload.get("data") if isinstance(payload, dict) else []
    result = []
    for row in rows or []:
        day = str(row.get("date") or "")[:10]
        o = safe_float(row.get("open"))
        h = safe_float(row.get("high"))
        l = safe_float(row.get("low"))
        c = safe_float(row.get("close"))
        v = safe_int(row.get("volume"))
        if not day or None in (o, h, l, c):
            continue
        result.append(
            {
                "time": day,
                "open": round(o, 4),
                "high": round(h, 4),
                "low": round(l, 4),
                "close": round(c, 4),
                "volume": v,
                "amount": safe_float(row.get("turnover")) or ((c * v) if v else None),
            }
        )
    return normalize_kline(result, KLINE_DAYS)


def merge_bars(existing: list[dict] | dict | None, quote: dict, extra_rows: list[dict] | None = None, *, limit: int) -> list[dict]:
    rows: list[dict] = []
    rows.extend(normalize_kline(existing, 0))
    rows.extend(extra_rows or [])
    rows.append(
        {
            "time": quote["date"],
            "open": quote["open"],
            "high": quote["high"],
            "low": quote["low"],
            "close": quote["close"],
            "volume": quote.get("volume"),
            "amount": quote.get("amount"),
        }
    )
    return normalize_kline(rows, limit)


def merge_kline(existing: list[dict] | dict | None, quote: dict, fugle_rows: list[dict] | None = None) -> list[dict]:
    return merge_bars(existing, quote, fugle_rows, limit=KLINE_DAYS)


# ============================================================
# Quant/backtest / rolling-forward validation helpers
# ============================================================
VALIDATION_HORIZONS = (1, 5, 10, 20)
PRIMARY_HORIZON = {"rebound": 10, "swing": 10, "daytrade_proxy": 1}
STRATEGY_LABEL = {"rebound": "均線回踩", "swing": "強勢波段", "daytrade_proxy": "日線短線代理"}


def daily_returns(closes: list[float]) -> list[float]:
    if len(closes) < 2:
        return []
    return [(closes[i] / closes[i - 1]) - 1 for i in range(1, len(closes)) if closes[i - 1] > 0]


def sharpe_annualized(closes: list[float]) -> float | None:
    rets = daily_returns(closes[-20:])
    if len(rets) < 10:
        return None
    mean = float(np.mean(rets))
    std = float(np.std(rets, ddof=1))
    return 0.0 if std <= 0 else (mean / std) * math.sqrt(252)


def sma(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    return float(np.mean(values[-window:]))


def clamp01(value: float | None) -> float:
    if value is None:
        return 0.0
    return max(0.0, min(1.0, float(value)))


def weighted_number(pairs: list[tuple[float | None, float]], fallback: float = 50.0) -> float:
    usable = [(float(v), float(w)) for v, w in pairs if v is not None and w > 0]
    weight = sum(w for _, w in usable)
    return fallback if weight <= 0 else sum(v * w for v, w in usable) / weight


def historical_features(kline: list[dict], i: int) -> dict:
    closes = [float(x["close"]) for x in kline]
    row = kline[i]
    close = closes[i]
    open_v = float(row["open"])
    high = float(row["high"])
    low = float(row["low"])
    volume = float(row.get("volume") or 0)
    ma20 = float(np.mean(closes[i - 19 : i + 1])) if i >= 19 else None
    ma60 = float(np.mean(closes[i - 59 : i + 1])) if i >= 59 else None
    high250 = max(float(x["high"]) for x in kline[max(0, i - 249) : i + 1]) if i >= 59 else None
    near_high = close / high250 if high250 and high250 > 0 else None
    window20 = closes[max(0, i - 19) : i + 1]
    rets = daily_returns(window20)
    std = float(np.std(rets, ddof=1)) if len(rets) >= 10 else 0.0
    sharpe = (float(np.mean(rets)) / std) * math.sqrt(252) if std > 0 else None
    prev_vol = [float(x.get("volume") or 0) for x in kline[max(0, i - 20) : i] if float(x.get("volume") or 0) > 0]
    avg_vol = float(np.mean(prev_vol)) if prev_vol else 0.0
    vol_ratio = volume / avg_vol if avg_vol > 0 else None
    intraday_ret = (close - open_v) / open_v if open_v > 0 else None
    day_range = high - low
    range_position = (close - low) / day_range if day_range > 0 else 0.5
    recent_min_low = min(float(x["low"]) for x in kline[max(0, i - 2) : i + 1])
    momo20 = close / closes[i - 20] if i >= 20 and closes[i - 20] > 0 else None
    return {
        "close": close, "open": open_v, "ma20": ma20, "ma60": ma60,
        "near_high": near_high, "sharpe": sharpe, "vol_ratio": vol_ratio,
        "intraday_ret": intraday_ret, "range_position": range_position,
        "recent_min_low": recent_min_low, "momo20": momo20,
    }


def strategy_signal_and_score(strategy: str, f: dict) -> tuple[bool, float]:
    close, open_v = f["close"], f["open"]
    ma20, ma60 = f["ma20"], f["ma60"]
    near_high, sharpe = f["near_high"], f["sharpe"]
    vol_ratio, intraday_ret, range_position = f["vol_ratio"], f["intraday_ret"], f["range_position"]

    if strategy == "swing":
        trend = ma20 is not None and ma60 is not None and close > ma20 and close > ma60
        signal = bool(near_high is not None and near_high >= 0.90 and sharpe is not None and sharpe >= 0.50 and trend)
        score = clamp01(near_high) * 50 + clamp01(((sharpe or 0) + 1) / 3) * 30 + (20 if trend else 5)
        return signal, round(score, 2)

    if strategy == "daytrade_proxy":
        signal = bool((intraday_ret or 0) > 0.01 and (vol_ratio or 0) > 1.2 and (range_position or 0) > 0.65)
        # Historical cross-sectional amount rank is unavailable, so the remaining
        # contemporaneously-known factors are reweighted instead of filling 0.
        score = weighted_number([
            (clamp01(((intraday_ret or 0) + 0.02) / 0.08) * 100, 35),
            (clamp01((vol_ratio or 0) / 3) * 100, 25),
            (clamp01(range_position) * 100, 15),
        ])
        return signal, round(score, 2)

    # rebound: historical revenue/institution cross-section is intentionally not
    # backfilled, therefore validation uses only point-in-time price/volume inputs.
    hit20 = ma20 is not None and f["recent_min_low"] <= ma20 * 1.02
    hit60 = ma60 is not None and f["recent_min_low"] <= ma60 * 1.02
    trend = ma20 is not None and ma60 is not None and close > ma20 and close > ma60
    red = close > open_v
    signal = bool(trend and (hit20 or hit60) and red)
    momo_score = clamp01((((f.get("momo20") or 1.0) - 0.90) / 0.25)) * 100
    score = weighted_number([
        (100.0 if signal else 0.0, 50),
        (clamp01(near_high) * 100 if near_high is not None else None, 20),
        (clamp01((vol_ratio or 0) / 3) * 100 if vol_ratio is not None else None, 15),
        (momo_score if f.get("momo20") is not None else None, 15),
    ])
    return signal, round(score, 2)


def build_benchmark_context(histories: dict[str, list[dict]]) -> dict:
    daily: dict[str, list[float]] = {}
    for rows in histories.values():
        rows = normalize_kline(rows, 0)
        for i in range(1, len(rows)):
            p = float(rows[i - 1]["close"])
            c = float(rows[i]["close"])
            if p > 0:
                daily.setdefault(rows[i]["time"], []).append(c / p - 1)

    dates = sorted(daily)
    index_values: list[float] = []
    value = 100.0
    regime_by_date: dict[str, str] = {}
    for idx, day in enumerate(dates):
        rets = daily[day]
        if rets:
            value *= 1 + float(np.mean(rets))
        index_values.append(value)
        if idx >= 59:
            ma20 = float(np.mean(index_values[idx - 19 : idx + 1]))
            ma60 = float(np.mean(index_values[idx - 59 : idx + 1]))
            if value > ma20 > ma60:
                regime_by_date[day] = "bull"
            elif value < ma20 < ma60:
                regime_by_date[day] = "bear"
            else:
                regime_by_date[day] = "sideways"
        else:
            regime_by_date[day] = "unknown"

    future: dict[int, dict[str, float]] = {h: {} for h in VALIDATION_HORIZONS}
    future_samples: dict[int, dict[str, list[float]]] = {h: {} for h in VALIDATION_HORIZONS}
    for rows in histories.values():
        rows = normalize_kline(rows, 0)
        for i in range(len(rows) - 1):
            signal_day = rows[i]["time"]
            for h in VALIDATION_HORIZONS:
                if i + h >= len(rows):
                    continue
                entry = float(rows[i + 1]["open"])
                exit_price = float(rows[i + h]["close"])
                if entry > 0:
                    future_samples[h].setdefault(signal_day, []).append(exit_price / entry - 1)
    for h in VALIDATION_HORIZONS:
        future[h] = {d: float(np.mean(xs)) for d, xs in future_samples[h].items() if xs}
    return {"dates": dates, "regime_by_date": regime_by_date, "future_returns": future}


def _base_trade_stats(records: list[dict], horizon: int) -> dict:
    if not records:
        return {
            "signals": 0, "win_rate": None, "avg_return": None, "gross_avg_return": None,
            "median_return": None, "avg_win": None, "avg_loss": None, "payoff_ratio": None,
            "profit_factor": None, "max_drawdown": None, "sharpe": None,
            "avg_benchmark_return": None, "avg_excess_return": None,
        }
    ordered = sorted(records, key=lambda x: (x.get("exit_date", ""), x.get("symbol", "")))
    rets = np.array([float(x["net_return"]) for x in ordered], dtype=float)
    gross = np.array([float(x["gross_return"]) for x in ordered], dtype=float)
    wins = rets[rets > 0]
    losses = rets[rets < 0]
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for r in rets:
        equity *= max(0.000001, 1 + float(r))
        peak = max(peak, equity)
        max_dd = min(max_dd, equity / peak - 1)
    std = float(np.std(rets, ddof=1)) if len(rets) > 1 else 0.0
    sharpe = None if std <= 0 else float(np.mean(rets) / std * math.sqrt(252 / max(1, horizon)))
    bench = [float(x["benchmark_return"]) for x in ordered if x.get("benchmark_return") is not None]
    excess = [float(x["net_return"] - x["benchmark_return"]) for x in ordered if x.get("benchmark_return") is not None]
    gross_profit = float(np.sum(wins)) if len(wins) else 0.0
    gross_loss = abs(float(np.sum(losses))) if len(losses) else 0.0
    avg_win = float(np.mean(wins)) if len(wins) else None
    avg_loss = float(np.mean(losses)) if len(losses) else None
    return {
        "signals": int(len(rets)),
        "win_rate": round(float(np.mean(rets > 0)) * 100, 2),
        "avg_return": round(float(np.mean(rets)) * 100, 4),
        "gross_avg_return": round(float(np.mean(gross)) * 100, 4),
        "median_return": round(float(np.median(rets)) * 100, 4),
        "avg_win": round(avg_win * 100, 4) if avg_win is not None else None,
        "avg_loss": round(avg_loss * 100, 4) if avg_loss is not None else None,
        "payoff_ratio": round(avg_win / abs(avg_loss), 4) if avg_win is not None and avg_loss is not None and avg_loss < 0 else None,
        "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss > 0 else None,
        "max_drawdown": round(max_dd * 100, 4),
        "sharpe": round(sharpe, 4) if sharpe is not None else None,
        "avg_benchmark_return": round(float(np.mean(bench)) * 100, 4) if bench else None,
        "avg_excess_return": round(float(np.mean(excess)) * 100, 4) if excess else None,
    }


def _score_bucket(score: float) -> str:
    if score < 60:
        return "<60"
    if score < 70:
        return "60-69"
    if score < 80:
        return "70-79"
    if score < 90:
        return "80-89"
    return "90+"


def enrich_primary_stats(records: list[dict], horizon: int) -> dict:
    stats = _base_trade_stats(records, horizon)
    regimes = {}
    for key in ["bull", "sideways", "bear"]:
        subset = [x for x in records if x.get("regime") == key]
        sub = _base_trade_stats(subset, horizon)
        regimes[key] = {k: sub[k] for k in ["signals", "win_rate", "avg_return", "median_return"]}
    buckets = {}
    for key in ["<60", "60-69", "70-79", "80-89", "90+"]:
        subset = [x for x in records if _score_bucket(float(x.get("score") or 0)) == key]
        sub = _base_trade_stats(subset, horizon)
        buckets[key] = {k: sub[k] for k in ["signals", "win_rate", "avg_return", "median_return"]}
    stats["regimes"] = regimes
    stats["score_buckets"] = buckets
    return stats


def generate_strategy_records(
    kline: list[dict], strategy: str, horizon: int, eval_start_date: str,
    benchmark_future: dict[str, float], regime_by_date: dict[str, str], symbol: str,
) -> list[dict]:
    rows = normalize_kline(kline, 0)
    min_i = 249 if strategy == "swing" else (59 if strategy == "rebound" else 20)
    if len(rows) <= min_i + horizon:
        return []
    cost_rate = BACKTEST_TOTAL_COST_BPS / 10000.0
    records: list[dict] = []
    i = min_i
    while i + horizon < len(rows):
        signal_day = rows[i]["time"]
        if signal_day < eval_start_date:
            i += 1
            continue
        features = historical_features(rows, i)
        signal, score = strategy_signal_and_score(strategy, features)
        if not signal:
            i += 1
            continue
        entry = float(rows[i + 1]["open"])
        exit_price = float(rows[i + horizon]["close"])
        if entry <= 0:
            i += 1
            continue
        gross_ret = exit_price / entry - 1
        net_ret = (1 + gross_ret) * (1 - cost_rate) - 1
        records.append({
            "symbol": symbol,
            "signal_date": signal_day,
            "entry_date": rows[i + 1]["time"],
            "exit_date": rows[i + horizon]["time"],
            "gross_return": gross_ret,
            "net_return": net_ret,
            "benchmark_return": benchmark_future.get(signal_day),
            "score": score,
            "regime": regime_by_date.get(signal_day, "unknown"),
        })
        # Same stock cannot create a second independent trade while the current
        # horizon is still being held.
        i += max(1, horizon)
    return records


def summarize_strategy_records(records_by_horizon: dict[int, list[dict]], strategy: str) -> dict:
    primary = PRIMARY_HORIZON[strategy]
    primary_records = records_by_horizon.get(primary, [])
    result = enrich_primary_stats(primary_records, primary)
    result["primary_horizon"] = primary
    result["cost_bps"] = BACKTEST_TOTAL_COST_BPS
    result["horizons"] = {
        str(h): {k: v for k, v in _base_trade_stats(records_by_horizon.get(h, []), h).items()
                 if k in ["signals", "win_rate", "avg_return", "median_return", "profit_factor", "max_drawdown", "sharpe", "avg_excess_return"]}
        for h in VALIDATION_HORIZONS
    }
    if strategy == "daytrade_proxy":
        result["recommended_mode"] = "1D｜僅研究；真正短線需 5/15 分K確認"
    elif strategy == "rebound":
        result["recommended_mode"] = "10D｜多頭或震盪回升；看 MA20/60 回踩後轉強"
    else:
        result["recommended_mode"] = "10–20D｜多頭；分數與趨勢同步時參考度較高"
    result["note"] = (
        f"Rolling-forward：訊號只使用當時以前資料；最後 {VALIDATION_OOS_DAYS} 個交易日為驗證窗。"
        f" 每筆扣除研究用總摩擦成本 {BACKTEST_TOTAL_COST_BPS/100:.2f}%；同股持有期間不重複進場。"
        " 股票池仍以目前熱門股為基礎，仍存在 current-universe 選擇偏誤。"
    )
    return result


def backtest_all_strategies(kline: list[dict], eval_start_date: str, benchmark: dict, symbol: str):
    results = {}
    raw = {}
    for strategy in ["rebound", "swing", "daytrade_proxy"]:
        records_by_h = {}
        for h in VALIDATION_HORIZONS:
            records_by_h[h] = generate_strategy_records(
                kline, strategy, h, eval_start_date,
                benchmark["future_returns"].get(h, {}), benchmark["regime_by_date"], symbol,
            )
        results[strategy] = summarize_strategy_records(records_by_h, strategy)
        raw[strategy] = records_by_h
    return results, raw


def aggregate_global_backtests(all_records: dict[str, dict[int, list[dict]]]) -> dict:
    return {strategy: summarize_strategy_records(records, strategy) for strategy, records in all_records.items()}


def compute_technical(kline: list[dict]) -> dict:
    if not kline:
        return {
            "sharpe20": None, "sma20": None, "sma60": None, "near_high_ratio": None,
            "momo20": None, "intraday_ret": None, "volume_ratio": None,
            "range_position": None, "recent_min_low_3": None,
        }
    closes = [float(x["close"]) for x in kline]
    volumes = [float(x.get("volume") or 0) for x in kline]
    latest = kline[-1]
    current_price = closes[-1]
    current_open = float(latest["open"])
    current_high = float(latest["high"])
    current_low = float(latest["low"])
    current_volume = volumes[-1]
    ma20 = sma(closes, 20)
    ma60 = sma(closes, 60)
    high250 = max(float(x["high"]) for x in kline) if len(kline) >= MIN_TECHNICAL_DAYS else None
    near_high_ratio = current_price / high250 if high250 else None
    momo20 = current_price / closes[-21] if len(closes) >= 21 and closes[-21] else None
    sharpe20 = sharpe_annualized(closes)
    prev20_volumes = [x for x in volumes[-21:-1] if x > 0]
    avg20_volume = float(np.mean(prev20_volumes)) if prev20_volumes else 0.0
    volume_ratio = current_volume / avg20_volume if avg20_volume else None
    intraday_ret = (current_price - current_open) / current_open if current_open else None
    day_range = current_high - current_low
    range_position = (current_price - current_low) / day_range if day_range > 0 else 0.5
    recent_min_low_3 = min(float(x["low"]) for x in kline[-3:]) if len(kline) >= 3 else None
    return {
        "sharpe20": sharpe20, "sma20": ma20, "sma60": ma60,
        "near_high_ratio": near_high_ratio, "momo20": momo20,
        "intraday_ret": intraday_ret, "volume_ratio": volume_ratio,
        "range_position": range_position, "recent_min_low_3": recent_min_low_3,
    }


# ============================================================
# Migration / fallback helpers
# ============================================================
def previous_metric(previous_summary: dict, key: str, latest_day: str) -> Any:
    value = previous_summary.get(key)
    if value is None:
        return None
    prev_day = parse_iso_date(previous_summary.get("updated_at"))
    now_day = parse_iso_date(latest_day)
    if not prev_day or not now_day:
        return None
    if (now_day - prev_day).days > LEGACY_FUNDAMENTAL_MAX_AGE_DAYS:
        return None
    return value


def choose_metric(current: Any, previous_summary: dict, key: str, latest_day: str) -> tuple[Any, bool]:
    if current is not None:
        return current, False
    fallback = previous_metric(previous_summary, key, latest_day)
    return fallback, fallback is not None


# ============================================================
# Main
# ============================================================
def main() -> None:
    validate_environment()
    market_ref = init_firebase()
    previous = market_ref.get() or {}
    previous_summary_map = previous.get("summary") or {}
    previous_kline_map = previous.get("kline") or {}
    previous_history_map = previous.get("history") or {}

    print("[1/8] 讀取 TWSE / TPEx 當日行情…")
    quote_payloads = fetch_many([
        {"key": "twse", "url": f"{TWSE_BASE}/exchangeReport/STOCK_DAY_ALL", "required": True, "label": "TWSE daily quotes"},
        {"key": "tpex", "url": f"{TPEX_BASE}/tpex_mainboard_daily_close_quotes", "required": True, "label": "TPEx daily quotes"},
    ])
    twse_quotes = parse_twse_quotes(quote_payloads.get("twse") or [])
    tpex_quotes = parse_tpex_quotes(quote_payloads.get("tpex") or [])
    quotes = {**twse_quotes, **tpex_quotes}
    if not quotes:
        raise RuntimeError("TWSE / TPEx 均沒有可用行情資料")

    quote_dates = sorted({q["date"] for q in quotes.values() if q.get("date")})
    latest_day = quote_dates[-1]
    if len(quote_dates) > 1:
        print(f"[WARN] TWSE/TPEx snapshot 日期不一致：{quote_dates}；個股保留各自來源日期，meta 使用最新日期 {latest_day}")

    print("[2/8] 讀取估值、公司基本資料與月營收…")
    base_payloads = fetch_many([
        {"key": "twse_val", "url": f"{TWSE_BASE}/exchangeReport/BWIBBU_ALL", "label": "TWSE valuation"},
        {"key": "tpex_val", "url": f"{TPEX_BASE}/tpex_mainboard_peratio_analysis", "label": "TPEx valuation"},
        {"key": "twse_company", "url": f"{TWSE_BASE}/opendata/t187ap03_L", "label": "TWSE company basics"},
        {"key": "tpex_company", "url": f"{TPEX_BASE}/mopsfin_t187ap03_O", "label": "TPEx company basics"},
        {"key": "twse_revenue", "url": f"{TWSE_BASE}/opendata/t187ap05_L", "label": "TWSE monthly revenue"},
        {"key": "tpex_revenue", "url": f"{TPEX_BASE}/mopsfin_t187ap05_O", "label": "TPEx monthly revenue"},
    ])
    valuation = {}
    valuation.update(parse_valuation(base_payloads.get("twse_val") or [], "TWSE"))
    valuation.update(parse_valuation(base_payloads.get("tpex_val") or [], "TPEx"))
    company = {}
    company.update(parse_company_basic(base_payloads.get("twse_company") or [], "TWSE"))
    company.update(parse_company_basic(base_payloads.get("tpex_company") or [], "TPEx"))
    revenue = {}
    revenue.update(parse_revenue(base_payloads.get("twse_revenue") or []))
    revenue.update(parse_revenue(base_payloads.get("tpex_revenue") or []))

    print("[3/8] 讀取股利資料…")
    asof = parse_iso_date(latest_day) or date.today()
    dividend_payloads = fetch_many([
        {"key": "twse", "url": f"{TWSE_BASE}/opendata/t187ap45_L", "label": "TWSE dividends"},
        {"key": "tpex", "url": f"{TPEX_BASE}/mopsfin_t187ap39_O", "label": "TPEx dividends"},
    ])
    dividend_rows = (dividend_payloads.get("twse") or []) + (dividend_payloads.get("tpex") or [])
    dividends = parse_dividends(dividend_rows, asof)

    print("[4/8] 讀取最新財務報表（並行下載；失敗時允許沿用近期舊值）…")
    twse_income_endpoints = ["t187ap06_L_ci", "t187ap06_L_basi", "t187ap06_L_bd", "t187ap06_L_fh", "t187ap06_L_ins", "t187ap06_L_mim"]
    twse_balance_endpoints = ["t187ap07_L_ci", "t187ap07_L_basi", "t187ap07_L_bd", "t187ap07_L_fh", "t187ap07_L_ins", "t187ap07_L_mim"]
    tpex_income_endpoints = ["mopsfin_t187ap06_O_ci", "mopsfin_t187ap06_O_basi", "mopsfin_t187ap06_O_bd", "mopsfin_t187ap06_O_fh", "mopsfin_t187ap06_O_ins", "mopsfin_t187ap06_O_mim"]
    tpex_balance_endpoints = ["mopsfin_t187ap07_O_ci", "mopsfin_t187ap07_O_basi", "mopsfin_t187ap07_O_bd", "mopsfin_t187ap07_O_fh", "mopsfin_t187ap07_O_ins", "mopsfin_t187ap07_O_mim"]
    finance_specs = []
    for endpoint in twse_income_endpoints + twse_balance_endpoints:
        finance_specs.append({"key": f"twse:{endpoint}", "url": f"{TWSE_BASE}/opendata/{endpoint}", "label": f"TWSE {endpoint}"})
    for endpoint in tpex_income_endpoints + tpex_balance_endpoints:
        finance_specs.append({"key": f"tpex:{endpoint}", "url": f"{TPEX_BASE}/{endpoint}", "label": f"TPEx {endpoint}"})
    finance_payloads = fetch_many(finance_specs)
    income_rows: list[dict] = []
    balance_rows: list[dict] = []
    for endpoint in twse_income_endpoints:
        income_rows.extend(finance_payloads.get(f"twse:{endpoint}") or [])
    for endpoint in twse_balance_endpoints:
        balance_rows.extend(finance_payloads.get(f"twse:{endpoint}") or [])
    for endpoint in tpex_income_endpoints:
        income_rows.extend(finance_payloads.get(f"tpex:{endpoint}") or [])
    for endpoint in tpex_balance_endpoints:
        balance_rows.extend(finance_payloads.get(f"tpex:{endpoint}") or [])
    fundamentals = combine_fundamentals(parse_income_statements(income_rows), parse_balance_sheets(balance_rows))

    print("[5/8] 讀取三大法人當日資料並累積 15 日歷史…")
    institution_payloads = fetch_many([
        {
            "key": "twse",
            "url": TWSE_T86_URL,
            "params": {"response": "json", "date": iso_to_yyyymmdd(latest_day), "selectType": "ALLBUT0999"},
            "label": "TWSE T86",
        },
        {"key": "tpex", "url": f"{TPEX_BASE}/tpex_3insti_daily_trading", "label": "TPEx institutional"},
    ])
    twse_inst = parse_twse_t86(institution_payloads.get("twse") or {})
    tpex_inst = parse_tpex_institution(institution_payloads.get("tpex") or [])
    institution_today = {**twse_inst, **tpex_inst}

    print("[6/8] 建立最新成交金額熱門股票池…")
    liquid = [q for q in quotes.values() if safe_float(q.get("amount")) and safe_float(q.get("amount")) > 0]
    liquid.sort(key=lambda x: float(x.get("amount") or 0), reverse=True)
    target_quotes = liquid[:HOT_STOCK_COUNT]
    if not target_quotes:
        raise RuntimeError("沒有可用的熱門股票池")
    amount_values = [float(q.get("amount") or 0) for q in target_quotes]
    n_amount = max(1, len(amount_values) - 1)

    print("[7/8] 合併既有 K 線、必要時 Fugle 補洞、計算技術指標與回測…")
    summaries: dict[str, dict] = {}
    klines: dict[str, list[dict]] = {}
    histories: dict[str, list[dict]] = {}
    fugle_bootstrap_count = 0
    legacy_fallback_count = 0

    for hot_rank, quote in enumerate(target_quotes, start=1):
        sym = quote["symbol"]
        prev_summary = previous_summary_map.get(sym) or {}
        existing_display = normalize_kline(previous_kline_map.get(sym) or prev_summary.get("kline") or [], KLINE_DAYS)
        existing_history = normalize_kline(previous_history_map.get(sym) or existing_display, BACKTEST_HISTORY_BARS)
        fugle_rows = []
        if (
            len(existing_display) < MIN_TECHNICAL_DAYS
            and FUGLE_API_KEY
            and fugle_bootstrap_count < FUGLE_BOOTSTRAP_MAX_PER_RUN
        ):
            fugle_rows = fetch_fugle_history(sym, quote["date"])
            if fugle_rows:
                fugle_bootstrap_count += 1
        history = merge_bars(existing_history, quote, fugle_rows, limit=BACKTEST_HISTORY_BARS)
        kline = normalize_kline(history, KLINE_DAYS)
        technical = compute_technical(kline)

        basic = company.get(sym, {})
        val = valuation.get(sym, {})
        rev = revenue.get(sym, {})
        div = dividends.get(sym, {})
        fund = fundamentals.get(sym, {})

        fallback_fields: list[str] = []
        roe, fb = choose_metric(fund.get("roe"), prev_summary, "roe", quote["date"]); fallback_fields += ["roe"] if fb else []
        eps, fb = choose_metric(fund.get("eps"), prev_summary, "eps", quote["date"]); fallback_fields += ["eps"] if fb else []
        gross_margin, fb = choose_metric(fund.get("gross_margin"), prev_summary, "gross_margin", quote["date"]); fallback_fields += ["gross_margin"] if fb else []
        operating_margin, fb = choose_metric(fund.get("operating_margin"), prev_summary, "operating_margin", quote["date"]); fallback_fields += ["operating_margin"] if fb else []
        debt_ratio, fb = choose_metric(fund.get("debt_ratio"), prev_summary, "debt_ratio", quote["date"]); fallback_fields += ["debt_ratio"] if fb else []
        # TWSE/TPEx OpenAPI does not expose a stable consolidated FCF field in the same way FinLab did.
        fcf, fb = choose_metric(None, prev_summary, "fcf", quote["date"]); fallback_fields += ["fcf"] if fb else []
        if fallback_fields:
            legacy_fallback_count += 1

        dividend_ttm = safe_float(div.get("dividend_ttm"))
        exchange_yield = safe_float(val.get("exchange_yield_pct"))
        yield_pct = (dividend_ttm / quote["close"] * 100) if dividend_ttm is not None and quote["close"] else exchange_yield

        previous_inst_history = prev_summary.get("institution_history") or []
        inst_history = merge_institution_history(previous_inst_history, quote["date"], institution_today.get(sym))
        net15 = sum(int(x["net_shares"]) for x in inst_history) if inst_history else None

        amount_rank_pct = 1.0 - ((hot_rank - 1) / n_amount) if len(target_quotes) > 1 else 1.0
        summary = {
            "symbol": sym,
            "name": basic.get("name") or quote.get("name") or sym,
            "category": basic.get("category") or ("上市" if quote["exchange"] == "TWSE" else "上櫃"),
            "exchange": quote["exchange"],
            "hot_rank": hot_rank,
            "updated_at": quote["date"],
            "price": round(float(quote["close"]), 4),
            "open": round(float(quote["open"]), 4),
            "high": round(float(quote["high"]), 4),
            "low": round(float(quote["low"]), 4),
            "volume": safe_int(quote.get("volume")),
            "amount": round(float(quote.get("amount") or 0), 2),
            "amount_rank_pct": round(amount_rank_pct, 6),
            "pe": val.get("pe"),
            "pb": val.get("pb"),
            "rev_yoy": rev.get("rev_yoy"),
            "roe": safe_float(roe),
            "eps": safe_float(eps),
            "gross_margin": safe_float(gross_margin),
            "operating_margin": safe_float(operating_margin),
            "fcf": safe_float(fcf),
            "debt_ratio": safe_float(debt_ratio),
            "dividend_latest": safe_float(div.get("dividend_latest")),
            "dividend_ttm": dividend_ttm,
            "dividend": dividend_ttm,
            "yield_pct": yield_pct,
            "dividend_continuity_years": safe_int(div.get("dividend_continuity_years")),
            "exchange_yield_pct": exchange_yield,
            "net15Total": net15,
            "institution_history": inst_history,
            "kline_count": len(kline),
            "history_count": len(history),
            "history_source": "firebase+official" if existing_history else ("fugle+official" if fugle_rows else "official-daily-only"),
            "fundamental_source": "official-filings" if fund else ("legacy-fallback" if fallback_fields else "unavailable"),
            "legacy_fallback_fields": fallback_fields,
            "revenue_period": rev.get("revenue_period"),
            "fundamental_quarter": fund.get("fundamental_quarter"),
            **technical,
        }
        summaries[sym] = summary
        klines[sym] = kline
        histories[sym] = history

    print("[7.5/8] 執行 rolling-forward 驗證、成本後績效與分數分層…")
    benchmark = build_benchmark_context(histories)
    validation_dates = benchmark.get("dates") or []
    if validation_dates:
        eval_start_idx = max(0, len(validation_dates) - VALIDATION_OOS_DAYS)
        eval_start_date = validation_dates[eval_start_idx]
        eval_end_date = validation_dates[-1]
    else:
        eval_start_date = latest_day
        eval_end_date = latest_day

    global_records: dict[str, dict[int, list[dict]]] = {
        key: {h: [] for h in VALIDATION_HORIZONS}
        for key in ["rebound", "swing", "daytrade_proxy"]
    }
    for sym, history in histories.items():
        bt, raw_records = backtest_all_strategies(history, eval_start_date, benchmark, sym)
        summaries[sym]["backtest"] = bt
        for strategy, by_h in raw_records.items():
            for h, records in by_h.items():
                global_records[strategy][h].extend(records)

    global_backtests = aggregate_global_backtests(global_records)

    print("[8/8] 寫入 Firebase /market_data…")
    if not summaries:
        raise RuntimeError("沒有成功建立任何股票資料，停止覆寫 Firebase。")

    quality_fields = ["pe", "pb", "rev_yoy", "roe", "eps", "debt_ratio", "dividend_ttm", "net15Total", "sharpe20"]
    quality_total = sum(sum(1 for key in quality_fields if stock.get(key) is not None) for stock in summaries.values())
    data_quality_pct = round(quality_total / max(1, len(summaries) * len(quality_fields)) * 100, 2)
    now_utc = datetime.now(timezone.utc).isoformat(timespec="seconds")

    output = {
        "meta": {
            "updated_at": latest_day,
            "generated_at_utc": now_utc,
            "source": "TWSE + TPEx",
            "history_source": "Firebase rolling history; Fugle historical bootstrap/fill",
            "version": MODEL_VERSION,
            "validation": {
                "method": "rolling-forward-oos",
                "evaluation_start": eval_start_date,
                "evaluation_end": eval_end_date,
                "oos_days": VALIDATION_OOS_DAYS,
                "history_bars_target": BACKTEST_HISTORY_BARS,
                "cost_bps": BACKTEST_TOTAL_COST_BPS,
                "benchmark": "current-universe equal-weight future-return proxy",
                "universe_bias": True,
            },
            "performance": {"http_timeout_seconds": HTTP_TIMEOUT, "http_workers": HTTP_WORKERS, "fugle_bootstrap_max_per_run": FUGLE_BOOTSTRAP_MAX_PER_RUN},
            "universe": {
                "name": f"熱門{HOT_STOCK_COUNT}檔",
                "definition": f"TWSE+TPEx 最新成交金額排名前{HOT_STOCK_COUNT}檔四位數普通股；排除0開頭ETF/ETN",
                "count": len(summaries),
            },
            "kline_days": KLINE_DAYS,
            "backtest_history_bars": BACKTEST_HISTORY_BARS,
            "institution_days": INSTITUTION_DAYS,
            "data_quality_pct": data_quality_pct,
            "schema": "split-summary-kline-history",
            "fugle_enabled": bool(FUGLE_API_KEY),
            "fugle_bootstrap_count": fugle_bootstrap_count,
            "legacy_fallback_stock_count": legacy_fallback_count,
            "notes": [
                "FinLab API 與 finlab 套件已完全移除。",
                f"官方 API 以最多 {HTTP_WORKERS} 個並行 worker 抓取，單一 HTTP 最長等待 {HTTP_TIMEOUT:g} 秒。",
                f"Fugle 每次最多補 {FUGLE_BOOTSTRAP_MAX_PER_RUN} 檔，避免單次 workflow 過久。",
                "TWSE/TPEx 官方 OpenAPI 提供當日行情、估值、營收、股利與財報；法人15日歷史由每日官方資料持續累積。",
                "前端 K 線保留最近 250 根；研究回測另保留最多 5 年 rolling history，不會一次載入瀏覽器。",
                f"Rolling-forward 主要驗證窗為最後 {VALIDATION_OOS_DAYS} 個交易日，每筆預設扣除 {BACKTEST_TOTAL_COST_BPS/100:.2f}% 研究用總摩擦成本。",
                "回測訊號只使用訊號日以前的價格/量資料；但歷史股票池仍以目前熱門股為基礎，current-universe 選擇偏誤尚未完全消除。",
                f"近期舊版基本面欄位最多只允許沿用 {LEGACY_FUNDAMENTAL_MAX_AGE_DAYS} 天，避免永久使用過期值。",
                "ROE 以最新累計淨利年化 / 期末權益近似；FCF 若官方資料無法直接取得，會暫時使用近期舊值或留空。",
            ],
        },
        "backtests": global_backtests,
        "summary": summaries,
        "kline": klines,
        "history": histories,
    }

    market_ref.set(output)
    print(
        f"完成：{len(summaries)} 檔，資料日 {latest_day}，品質 {data_quality_pct}%，"
        f"Fugle 補歷史 {fugle_bootstrap_count} 檔，舊基本面 fallback {legacy_fallback_count} 檔。"
    )


if __name__ == "__main__":
    main()
