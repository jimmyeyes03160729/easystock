import json
import math
import os
from datetime import datetime, timezone
from typing import Any

import firebase_admin
import finlab
import numpy as np
import pandas as pd
from firebase_admin import credentials, db
from finlab import data

# ============================================================
# Configuration
# ============================================================
FINLAB_TOKEN = os.environ.get("FINLAB_API_TOKEN")
FIREBASE_DATABASE_URL = os.environ.get("FIREBASE_DATABASE_URL")
FIREBASE_SERVICE_ACCOUNT_JSON = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")
FIREBASE_ROOT_PATH = os.environ.get("FIREBASE_ROOT_PATH", "market_data").strip("/") or "market_data"

HOT_STOCK_COUNT = int(os.environ.get("HOT_STOCK_COUNT", "500"))
KLINE_DAYS = int(os.environ.get("KLINE_DAYS", "250"))
INSTITUTION_DAYS = int(os.environ.get("INSTITUTION_DAYS", "15"))
MODEL_VERSION = "0.50"


# ============================================================
# Generic helpers
# ============================================================
def safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        x = float(value)
        if math.isnan(x) or math.isinf(x):
            return None
        return x
    except (TypeError, ValueError):
        return None


def safe_int(value: Any) -> int | None:
    x = safe_float(value)
    return None if x is None else int(round(x))


def normalize_symbol(value: Any) -> str:
    return str(value).strip()


def iso_date(value: Any) -> str:
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    return str(value)[:10]


def load_first(candidates: list[str], label: str, required: bool = False):
    """Load the first available FinLab dataset; never fabricate missing values."""
    last_error = None
    for name in candidates:
        try:
            print(f"[DATA] {label}: {name}")
            df = data.get(name)
            if df is not None and not getattr(df, "empty", True):
                return df
        except Exception as exc:  # FinLab may throw for unavailable datasets/plan limits.
            last_error = exc
            print(f"[DATA] {label}: {name} failed -> {exc}")
    if required:
        raise RuntimeError(f"缺少必要 FinLab 資料：{label}; last_error={last_error}")
    print(f"[DATA] {label}: unavailable -> None")
    return None


def latest_value(df, symbol: str):
    if df is None or symbol not in df.columns:
        return None
    series = pd.to_numeric(df[symbol], errors="coerce").dropna()
    return None if series.empty else safe_float(series.iloc[-1])


def get_history(df, symbol: str, periods: int | None = None):
    if df is None or symbol not in df.columns:
        return pd.Series(dtype=float)
    series = pd.to_numeric(df[symbol], errors="coerce").dropna()
    if periods is not None:
        series = series.iloc[-periods:]
    return series


def validate_environment() -> None:
    if not FINLAB_TOKEN:
        raise ValueError("找不到 FINLAB_API_TOKEN")
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
    # Only replace /market_data, never the Firebase database root.
    return db.reference(f"/{FIREBASE_ROOT_PATH}")


# ============================================================
# Dividend helpers
# ============================================================
def normalized_dated_series(df, symbol: str) -> pd.Series:
    if df is None or symbol not in df.columns:
        return pd.Series(dtype=float)

    raw = pd.to_numeric(df[symbol], errors="coerce").dropna()
    if raw.empty:
        return pd.Series(dtype=float)

    idx = pd.to_datetime(raw.index, errors="coerce")
    valid = ~pd.isna(idx)
    if not valid.any():
        return pd.Series(dtype=float)

    series = pd.Series(raw.to_numpy()[valid], index=idx[valid], dtype=float)
    return series.sort_index()


def dividend_metrics(dividend_df, symbol: str, asof_date) -> tuple[float | None, float | None, int | None]:
    """
    Returns (latest_positive_dividend, trailing_365d_dividend, consecutive_years_up_to_5).

    The TTM value is the sum of positive cash-dividend records dated within the
    last 365 days. Continuity counts consecutive calendar years with positive
    dividend records, starting from the latest year that has a positive record.
    """
    series = normalized_dated_series(dividend_df, symbol)
    if series.empty:
        return None, None, None

    positive = series[series > 0]
    if positive.empty:
        return None, 0.0, 0

    asof = pd.Timestamp(asof_date)
    cutoff = asof - pd.Timedelta(days=365)
    ttm = positive[(positive.index > cutoff) & (positive.index <= asof)].sum()
    latest = safe_float(positive.iloc[-1])

    annual = positive.groupby(positive.index.year).sum()
    positive_years = sorted(int(y) for y, value in annual.items() if safe_float(value) and value > 0)
    if not positive_years:
        continuity = 0
    else:
        start_year = positive_years[-1]
        year_set = set(positive_years)
        continuity = 0
        for year in range(start_year, start_year - 5, -1):
            if year in year_set:
                continuity += 1
            else:
                break

    return latest, safe_float(ttm), continuity


# ============================================================
# Quant/backtest helpers
# ============================================================
def daily_returns(closes: list[float]) -> list[float]:
    if len(closes) < 2:
        return []
    out = []
    for i in range(1, len(closes)):
        prev = closes[i - 1]
        if prev:
            out.append((closes[i] - prev) / prev)
    return out


def sharpe_annualized(closes: list[float]) -> float | None:
    rets = daily_returns(closes[-20:])
    if len(rets) < 10:
        return None
    mean = float(np.mean(rets))
    std = float(np.std(rets, ddof=1))
    if std <= 0:
        return 0.0
    return (mean / std) * math.sqrt(252)


def sma(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    return float(np.mean(values[-window:]))


def calc_trade_stats(returns: list[float], equity_curve: list[float], note: str):
    if not returns:
        return {
            "signals": 0,
            "win_rate": None,
            "avg_return": None,
            "max_drawdown": None,
            "note": note,
        }

    wins = sum(1 for x in returns if x > 0)
    max_dd = 0.0
    peak = equity_curve[0] if equity_curve else 1.0
    for value in equity_curve:
        peak = max(peak, value)
        if peak > 0:
            max_dd = min(max_dd, (value / peak) - 1)

    return {
        "signals": len(returns),
        "win_rate": round(wins / len(returns) * 100, 2),
        "avg_return": round(float(np.mean(returns)) * 100, 4),
        "max_drawdown": round(max_dd * 100, 4),
        "note": note,
    }


def backtest_rebound(kline: list[dict]):
    if len(kline) < 75:
        return calc_trade_stats([], [1.0], "資料不足，至少需要75個交易日。")

    closes = [float(x["close"]) for x in kline]
    opens = [float(x["open"]) for x in kline]
    lows = [float(x["low"]) for x in kline]
    returns: list[float] = []
    equity = [1.0]

    i = 60
    while i < len(kline) - 10:
        ma20 = np.mean(closes[i - 19 : i + 1])
        ma60 = np.mean(closes[i - 59 : i + 1])
        recent_min_low = min(lows[i - 2 : i + 1])
        hit = recent_min_low <= max(ma20, ma60) * 1.02
        red = closes[i] > opens[i]
        signal = closes[i] > ma20 and closes[i] > ma60 and hit and red
        if signal:
            entry = opens[i + 1]
            exit_price = closes[i + 10]
            if entry > 0:
                ret = exit_price / entry - 1
                returns.append(ret)
                equity.append(equity[-1] * (1 + ret))
                i += 10
                continue
        i += 1

    return calc_trade_stats(
        returns,
        equity,
        "訊號日收盤後，下一交易日開盤進場；固定持有10個交易日。未納入交易成本。",
    )


def backtest_swing(kline: list[dict]):
    if len(kline) < 80:
        return calc_trade_stats([], [1.0], "資料不足。")

    closes = [float(x["close"]) for x in kline]
    returns: list[float] = []
    equity = [1.0]

    i = 60
    while i < len(kline) - 10:
        window20 = closes[i - 19 : i + 1]
        rets = daily_returns(window20)
        std = np.std(rets, ddof=1) if len(rets) >= 10 else 0
        sharpe = (np.mean(rets) / std) * math.sqrt(252) if std > 0 else 0
        high_window = closes[max(0, i - 249) : i + 1]
        near_high = closes[i] / max(high_window)
        ma20 = np.mean(closes[i - 19 : i + 1])
        ma60 = np.mean(closes[i - 59 : i + 1])
        signal = near_high >= 0.90 and sharpe >= 0.50 and closes[i] > ma20 and closes[i] > ma60
        if signal:
            entry = float(kline[i + 1]["open"])
            exit_price = closes[i + 10]
            if entry > 0:
                ret = exit_price / entry - 1
                returns.append(ret)
                equity.append(equity[-1] * (1 + ret))
                i += 10
                continue
        i += 1

    return calc_trade_stats(
        returns,
        equity,
        "訊號日收盤後，下一交易日開盤進場；固定持有10個交易日。未納入交易成本。",
    )


def backtest_daytrade_proxy(kline: list[dict]):
    if len(kline) < 25:
        return calc_trade_stats([], [1.0], "資料不足。")

    returns: list[float] = []
    equity = [1.0]

    for i in range(21, len(kline)):
        prev = kline[i - 1]
        today = kline[i]
        prev_open = float(prev["open"])
        prev_close = float(prev["close"])
        prev_volume = float(prev.get("volume") or 0)
        prev_range = float(prev["high"]) - float(prev["low"])
        history_vol = [
            float(x.get("volume") or 0)
            for x in kline[max(0, i - 21) : i - 1]
            if float(x.get("volume") or 0) > 0
        ]
        avg_vol = float(np.mean(history_vol)) if history_vol else 0.0
        vol_ratio = prev_volume / avg_vol if avg_vol else 0.0
        intraday_ret = (prev_close - prev_open) / prev_open if prev_open else 0.0
        close_location = (
            (prev_close - float(prev["low"])) / prev_range if prev_range > 0 else 0.5
        )
        signal = intraday_ret > 0.01 and vol_ratio > 1.2 and close_location > 0.65
        if signal:
            entry = float(today["open"])
            exit_price = float(today["close"])
            if entry > 0:
                ret = exit_price / entry - 1
                returns.append(ret)
                equity.append(equity[-1] * (1 + ret))

    return calc_trade_stats(
        returns,
        equity,
        "日線代理回測：前一日收盤產生訊號，隔日開盤進場、隔日收盤出場；不代表真正5/15分鐘當沖。",
    )


def aggregate_backtests(stock_backtests: list[dict]):
    result = {}
    for key in ["rebound", "swing", "daytrade_proxy"]:
        samples = [x[key] for x in stock_backtests if x.get(key, {}).get("signals", 0)]
        total_signals = sum(x.get("signals", 0) for x in samples)
        if not samples or total_signals == 0:
            result[key] = {
                "signals": 0,
                "win_rate": None,
                "avg_return": None,
                "max_drawdown": None,
                "note": "目前250日資料沒有足夠訊號。",
            }
            continue

        weighted_win = sum((x.get("win_rate", 0) or 0) * x.get("signals", 0) for x in samples) / total_signals
        weighted_avg = sum((x.get("avg_return", 0) or 0) * x.get("signals", 0) for x in samples) / total_signals
        result[key] = {
            "signals": total_signals,
            "win_rate": round(weighted_win, 2),
            "avg_return": round(weighted_avg, 4),
            "max_drawdown": round(min((x.get("max_drawdown", 0) or 0) for x in samples), 4),
            "note": samples[0].get("note", ""),
        }
    return result


# ============================================================
# Main
# ============================================================
def main() -> None:
    validate_environment()
    finlab.login(FINLAB_TOKEN)

    print("[1/6] 載入必要價量資料…")
    close = load_first(["price:收盤價"], "收盤價", required=True)
    open_df = load_first(["price:開盤價"], "開盤價", required=True)
    high = load_first(["price:最高價"], "最高價", required=True)
    low = load_first(["price:最低價"], "最低價", required=True)
    volume = load_first(["price:成交股數"], "成交股數", required=True)

    print("[2/6] 載入估值與營收資料…")
    pe = load_first(["price_earning_ratio:本益比"], "本益比")
    pb = load_first(["price_earning_ratio:股價淨值比"], "股價淨值比")
    rev_yoy = load_first(["monthly_revenue:去年同月增減(%)"], "營收YoY")

    print("[3/6] 載入基本面資料…")
    roe = load_first(["fundamental_features:ROE稅後", "fundamental_features:股東權益報酬率"], "ROE")
    eps = load_first(["financial_statement:每股盈餘"], "EPS")
    gross_margin = load_first(["fundamental_features:營業毛利率"], "營業毛利率")
    operating_margin = load_first(["fundamental_features:營業利益率"], "營業利益率")
    fcf = load_first(["fundamental_features:自由現金流量"], "自由現金流量")
    debt_ratio = load_first(["fundamental_features:負債比率"], "負債比率")

    print("[4/6] 載入股利與法人資料…")
    dividend_df = load_first(
        ["dividend_announcement:現金股利", "distribution_of_share_dividend:現金股利"],
        "現金股利",
    )
    institutional = load_first(["institutional_investors_trading_summary:投信買賣超股數"], "投信買賣超股數")
    foreign = load_first(
        ["institutional_investors_trading_summary:外陸資買賣超股數(不含外資自營商)"],
        "外資買賣超股數",
    )

    if institutional is not None and foreign is not None:
        inst_total = institutional.add(foreign, fill_value=0)
    elif institutional is not None:
        inst_total = institutional
    else:
        inst_total = foreign

    print("[5/6] 計算熱門500檔股票池…")
    latest_date = close.index[-1]
    latest_close = close.loc[latest_date]
    aligned_volume = volume.reindex(index=close.index)
    latest_vol = aligned_volume.loc[latest_date]

    liquidity = pd.DataFrame({"close": latest_close, "volume": latest_vol}).dropna()
    symbols = liquidity.index.astype(str)
    liquidity = liquidity[symbols.str.len().eq(4) & symbols.str.isdigit()].copy()
    liquidity["amount"] = liquidity["close"] * liquidity["volume"]
    liquidity = (
        liquidity.replace([np.inf, -np.inf], np.nan)
        .dropna(subset=["amount"])
        .query("amount > 0")
        .sort_values("amount", ascending=False)
        .head(HOT_STOCK_COUNT)
    )

    target_symbols = [normalize_symbol(x) for x in liquidity.index.tolist()]
    amount_ranks = liquidity["amount"].rank(method="min", ascending=True, pct=True).to_dict()

    stock_meta_map: dict[str, dict] = {}
    try:
        sec_info = data.get("security_categories")
        if sec_info is not None and not sec_info.empty:
            for idx, row in sec_info.iterrows():
                sym = normalize_symbol(row.get("stock_id", idx))
                stock_meta_map[sym] = {
                    "name": str(row.get("name", sym)).strip(),
                    "category": str(row.get("category", "一般")).strip(),
                }
    except Exception as exc:
        print(f"[DATA] security_categories 略過：{exc}")

    summaries: dict[str, dict] = {}
    klines: dict[str, list[dict]] = {}
    stock_backtests: list[dict] = []

    print("[6/6] 建立摘要、250日K線與回測…")
    for hot_rank, sym in enumerate(target_symbols, start=1):
        try:
            s_close = get_history(close, sym)
            s_open = get_history(open_df, sym)
            s_high = get_history(high, sym)
            s_low = get_history(low, sym)
            s_volume = get_history(volume, sym)
            if len(s_close) < 60:
                continue

            recent_dates = s_close.index[-KLINE_DAYS:]
            kline: list[dict] = []
            for dt in recent_dates:
                if dt not in s_open.index or dt not in s_high.index or dt not in s_low.index or dt not in s_volume.index:
                    continue
                c = safe_float(s_close.loc[dt])
                o = safe_float(s_open.loc[dt])
                h = safe_float(s_high.loc[dt])
                l = safe_float(s_low.loc[dt])
                v = safe_float(s_volume.loc[dt])
                if None in (c, o, h, l):
                    continue
                kline.append(
                    {
                        "time": iso_date(dt),
                        "open": round(o, 4),
                        "high": round(h, 4),
                        "low": round(l, 4),
                        "close": round(c, 4),
                        "volume": safe_int(v),
                        "amount": round(c * v, 2) if v is not None else None,
                    }
                )

            if len(kline) < 60:
                continue

            closes = [float(x["close"]) for x in kline]
            volumes = [float(x.get("volume") or 0) for x in kline]
            current_price = closes[-1]
            current_open = float(kline[-1]["open"])
            current_high = float(kline[-1]["high"])
            current_low = float(kline[-1]["low"])
            current_volume = volumes[-1]

            ma20 = sma(closes, 20)
            ma60 = sma(closes, 60)
            high250 = max(float(x["high"]) for x in kline)
            near_high_ratio = current_price / high250 if high250 else None
            momo20 = current_price / closes[-21] if len(closes) >= 21 and closes[-21] else None
            sharpe20 = sharpe_annualized(closes)
            prev20_volumes = [x for x in volumes[-21:-1] if x > 0]
            avg20_volume = float(np.mean(prev20_volumes)) if prev20_volumes else 0.0
            volume_ratio = current_volume / avg20_volume if avg20_volume else None
            intraday_ret = (current_price - current_open) / current_open if current_open else None
            day_range = current_high - current_low
            range_position = (current_price - current_low) / day_range if day_range > 0 else 0.5
            recent_min_low_3 = min(float(x["low"]) for x in kline[-3:])

            latest_dividend, dividend_ttm, continuity_years = dividend_metrics(dividend_df, sym, latest_date)
            yield_v = (dividend_ttm / current_price * 100) if dividend_ttm is not None and current_price else None

            net15 = None
            inst_history: list[dict] = []
            if inst_total is not None and sym in inst_total.columns:
                inst_series = pd.to_numeric(inst_total[sym], errors="coerce").dropna().iloc[-INSTITUTION_DAYS:]
                if not inst_series.empty:
                    net15 = int(inst_series.sum())
                    inst_history = [
                        {"time": iso_date(idx), "net_shares": safe_int(value)}
                        for idx, value in inst_series.items()
                    ]

            bt = {
                "rebound": backtest_rebound(kline),
                "swing": backtest_swing(kline),
                "daytrade_proxy": backtest_daytrade_proxy(kline),
            }
            stock_backtests.append(bt)

            meta = stock_meta_map.get(sym, {"name": sym, "category": "一般"})
            summary = {
                "symbol": sym,
                "name": meta["name"],
                "category": meta["category"],
                "hot_rank": hot_rank,
                "updated_at": iso_date(latest_date),
                "price": round(current_price, 4),
                "open": round(current_open, 4),
                "high": round(current_high, 4),
                "low": round(current_low, 4),
                "volume": safe_int(current_volume),
                "amount": round(float(liquidity.loc[sym, "amount"]), 2),
                "amount_rank_pct": round(float(amount_ranks.get(sym, 0.5)), 6),
                "pe": latest_value(pe, sym),
                "pb": latest_value(pb, sym),
                "rev_yoy": latest_value(rev_yoy, sym),
                "roe": latest_value(roe, sym),
                "eps": latest_value(eps, sym),
                "gross_margin": latest_value(gross_margin, sym),
                "operating_margin": latest_value(operating_margin, sym),
                "fcf": latest_value(fcf, sym),
                "debt_ratio": latest_value(debt_ratio, sym),
                "dividend_latest": latest_dividend,
                "dividend_ttm": dividend_ttm,
                "dividend": dividend_ttm,  # Backward-compatible field: now means trailing-365d total.
                "yield_pct": yield_v,
                "dividend_continuity_years": continuity_years,
                "net15Total": net15,
                "institution_history": inst_history,
                "sharpe20": sharpe20,
                "sma20": ma20,
                "sma60": ma60,
                "near_high_ratio": near_high_ratio,
                "momo20": momo20,
                "intraday_ret": intraday_ret,
                "volume_ratio": volume_ratio,
                "range_position": range_position,
                "recent_min_low_3": recent_min_low_3,
                "kline_count": len(kline),
                "backtest": bt,
            }

            summaries[sym] = summary
            klines[sym] = kline

        except Exception as exc:
            print(f"[WARN] {sym} 跳過：{exc}")

    if not summaries:
        raise RuntimeError("沒有成功建立任何股票資料，停止覆寫 Firebase。")

    global_backtests = aggregate_backtests(stock_backtests)
    quality_fields = [
        "pe", "pb", "rev_yoy", "roe", "eps", "fcf", "debt_ratio",
        "dividend_ttm", "net15Total", "sharpe20",
    ]
    quality_total = sum(sum(1 for key in quality_fields if stock.get(key) is not None) for stock in summaries.values())
    data_quality_pct = round(quality_total / max(1, len(summaries) * len(quality_fields)) * 100, 2)

    now_utc = datetime.now(timezone.utc).isoformat(timespec="seconds")
    output = {
        "meta": {
            "updated_at": iso_date(latest_date),
            "generated_at_utc": now_utc,
            "source": "FinLab",
            "version": MODEL_VERSION,
            "universe": {
                "name": "熱門500檔",
                "definition": "最新成交金額排名前500檔、四位數台股",
                "count": len(summaries),
            },
            "kline_days": KLINE_DAYS,
            "institution_days": INSTITUTION_DAYS,
            "data_quality_pct": data_quality_pct,
            "schema": "split-summary-kline",
            "notes": [
                "缺失資料保留為 null，不用固定數字補值。",
                "殖利率以近365日正現金股利紀錄加總除以最新收盤價計算。",
                "股利連續性以有正現金股利紀錄的連續日曆年度計算，最多5年。",
                "當沖模型使用日線代理資料，不等同真實5/15分鐘盤中資料。",
                "回測使用目前熱門股票池的250日樣本內資料，存在股票池選擇偏誤，不是完整 point-in-time walk-forward。",
            ],
        },
        "backtests": global_backtests,
        "summary": summaries,
        "kline": klines,
    }

    market_ref = init_firebase()
    print(f"[FIREBASE] 準備寫入 /{FIREBASE_ROOT_PATH}：{len(summaries)} 檔…")
    market_ref.set(output)
    print(
        f"完成：{len(summaries)} 檔，資料日 {output['meta']['updated_at']}，"
        f"完整度 {data_quality_pct}% ，Firebase path=/{FIREBASE_ROOT_PATH}"
    )


if __name__ == "__main__":
    main()
