import json
import math
import os
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
import finlab
from finlab import data

import firebase_admin
from firebase_admin import credentials, db


# ============================================================
# Configuration
# ============================================================
FINLAB_TOKEN = os.environ.get("FINLAB_API_TOKEN")
FIREBASE_DATABASE_URL = os.environ.get("FIREBASE_DATABASE_URL")
FIREBASE_SERVICE_ACCOUNT_JSON = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")

HOT_STOCK_COUNT = 500
KLINE_DAYS = 250
INSTITUTION_DAYS = 15


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


def json_number(value: Any):
    """Return JSON-safe number or None."""
    x = safe_float(value)
    return x


def load_first(candidates: list[str], label: str, required: bool = False):
    """
    Try verified FinLab dataset names in order.
    A missing optional dataset becomes None; it is never replaced by fake values.
    """
    last_error = None
    for name in candidates:
        try:
            print(f"[DATA] {label}: {name}")
            df = data.get(name)
            if df is not None and not getattr(df, "empty", True):
                return df
        except Exception as exc:
            last_error = exc

    if required:
        raise RuntimeError(f"缺少必要 FinLab 資料：{label}; last_error={last_error}")
    print(f"[DATA] {label}: unavailable -> None")
    return None


def latest_value(df, symbol: str):
    if df is None or symbol not in df.columns:
        return None
    s = df[symbol].dropna()
    if s.empty:
        return None
    return safe_float(s.iloc[-1])


def get_history(df, symbol: str, periods: int | None = None):
    if df is None or symbol not in df.columns:
        return pd.Series(dtype=float)
    s = df[symbol].dropna()
    if periods is not None:
        s = s.iloc[-periods:]
    return s


def normalize_symbol(x) -> str:
    return str(x).strip()


def iso_date(x) -> str:
    if hasattr(x, "strftime"):
        return x.strftime("%Y-%m-%d")
    return str(x)[:10]


def clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, float(x)))


# ============================================================
# Firebase
# ============================================================
def init_firebase():
    if not FIREBASE_DATABASE_URL:
        raise ValueError("找不到 FIREBASE_DATABASE_URL")

    if not FIREBASE_SERVICE_ACCOUNT_JSON:
        raise ValueError("找不到 FIREBASE_SERVICE_ACCOUNT_JSON")

    try:
        service_account = json.loads(FIREBASE_SERVICE_ACCOUNT_JSON)
    except json.JSONDecodeError as exc:
        raise ValueError("FIREBASE_SERVICE_ACCOUNT_JSON 不是有效 JSON") from exc

    if not firebase_admin._apps:
        cred = credentials.Certificate(service_account)
        firebase_admin.initialize_app(cred, {
            "databaseURL": FIREBASE_DATABASE_URL
        })

    return db.reference("/")


def load_existing_stocks(root_ref):
    """Read the previous Firebase snapshot once, then locally merge today's new bar."""
    try:
        old = root_ref.child("stocks").get()
    except Exception as exc:
        print(f"[FIREBASE] 舊資料讀取失敗，將建立新資料：{exc}")
        return {}

    if isinstance(old, list):
        return {
            str(item.get("symbol")): item
            for item in old
            if isinstance(item, dict) and item.get("symbol")
        }

    if isinstance(old, dict):
        return {
            str(k): v for k, v in old.items()
            if isinstance(v, dict)
        }

    return {}


# ============================================================
# Backtest engine
# ============================================================
def daily_returns(closes: list[float]) -> list[float]:
    if len(closes) < 2:
        return []
    return [
        (closes[i] - closes[i-1]) / closes[i-1]
        for i in range(1, len(closes))
        if closes[i-1]
    ]


def sharpe_annualized(closes: list[float]) -> float | None:
    rets = daily_returns(closes[-20:])
    if len(rets) < 10:
        return None
    mean = float(np.mean(rets))
    std = float(np.std(rets, ddof=1))
    if std <= 0:
        return 0.0
    return (mean / std) * math.sqrt(252)


def rolling_sma(values: list[float], window: int):
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
            "note": note
        }

    wins = sum(1 for x in returns if x > 0)
    max_dd = 0.0
    peak = equity_curve[0] if equity_curve else 1.0
    for v in equity_curve:
        peak = max(peak, v)
        if peak > 0:
            max_dd = min(max_dd, (v / peak) - 1)

    return {
        "signals": len(returns),
        "win_rate": round(wins / len(returns) * 100, 2),
        "avg_return": round(float(np.mean(returns)) * 100, 4),
        "max_drawdown": round(max_dd * 100, 4),
        "note": note
    }


def backtest_rebound(kline: list[dict]):
    """
    Signal at close, enter next day's open, fixed 10-day exit.
    Uses only information available on signal day.
    Fundamental data is intentionally excluded because we only store current
    monthly revenue in this lightweight daily snapshot.
    """
    if len(kline) < 75:
        return calc_trade_stats([], [1.0], "資料不足，至少需要75個交易日。")

    closes = [float(x["close"]) for x in kline]
    opens = [float(x["open"]) for x in kline]
    lows = [float(x["low"]) for x in kline]
    returns = []
    equity = [1.0]
    i = 60
    while i < len(kline) - 10:
        sma20 = np.mean(closes[i-19:i+1])
        sma60 = np.mean(closes[i-59:i+1])
        recent_min_low = min(lows[i-2:i+1])
        hit = recent_min_low <= max(sma20, sma60) * 1.02
        red = closes[i] > opens[i]
        signal = closes[i] > sma20 and closes[i] > sma60 and hit and red

        if signal:
            entry = opens[i+1]
            exit_price = closes[i+10]
            if entry > 0:
                ret = exit_price / entry - 1
                returns.append(ret)
                equity.append(equity[-1] * (1 + ret))
                i += 10
                continue
        i += 1

    return calc_trade_stats(
        returns, equity,
        "訊號日收盤後，下一交易日開盤進場；固定持有10個交易日。未納入交易成本。"
    )


def backtest_swing(kline: list[dict]):
    """
    Signal at close, next-day open entry, 10-day hold.
    Near 250D high + positive 20D annualized Sharpe.
    """
    if len(kline) < 80:
        return calc_trade_stats([], [1.0], "資料不足。")

    closes = [float(x["close"]) for x in kline]
    returns = []
    equity = [1.0]
    i = 60

    while i < len(kline) - 10:
        window20 = closes[i-19:i+1]
        rets = daily_returns(window20)
        if len(rets) >= 10:
            std = np.std(rets, ddof=1)
            sharpe = (np.mean(rets) / std) * math.sqrt(252) if std > 0 else 0
        else:
            sharpe = 0

        high_window = closes[max(0, i-249):i+1]
        near_high = closes[i] / max(high_window)
        sma20 = np.mean(closes[i-19:i+1])
        sma60 = np.mean(closes[i-59:i+1])
        signal = near_high >= 0.90 and sharpe >= 0.50 and closes[i] > sma20 and closes[i] > sma60

        if signal:
            entry = kline[i+1]["open"]
            exit_price = closes[i+10]
            if entry > 0:
                ret = exit_price / entry - 1
                returns.append(ret)
                equity.append(equity[-1] * (1 + ret))
                i += 10
                continue
        i += 1

    return calc_trade_stats(
        returns, equity,
        "訊號日收盤後，下一交易日開盤進場；固定持有10個交易日。未納入交易成本。"
    )


def backtest_daytrade_proxy(kline: list[dict]):
    """
    Daily-data proxy, not real intraday backtest:
    signal is generated using yesterday's daily bar; today's open-to-close is the trade.
    """
    if len(kline) < 25:
        return calc_trade_stats([], [1.0], "資料不足。")

    returns = []
    equity = [1.0]

    for i in range(21, len(kline)):
        prev = kline[i-1]
        today = kline[i]

        prev_open = float(prev["open"])
        prev_close = float(prev["close"])
        prev_volume = float(prev.get("volume") or 0)
        prev_range = float(prev["high"]) - float(prev["low"])

        history_vol = [
            float(x.get("volume") or 0)
            for x in kline[max(0, i-21):i-1]
            if float(x.get("volume") or 0) > 0
        ]
        avg_vol = np.mean(history_vol) if history_vol else 0
        vol_ratio = prev_volume / avg_vol if avg_vol else 0
        intraday_ret = (prev_close - prev_open) / prev_open if prev_open else 0
        close_location = (
            (prev_close - prev["low"]) / prev_range
            if prev_range > 0 else 0.5
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
        returns, equity,
        "日線代理回測：前一日收盤產生訊號，隔日開盤進場、隔日收盤出場；不能代表真正5/15分鐘當沖。"
    )


def aggregate_backtests(stock_backtests: list[dict]):
    result = {}
    for key in ["rebound", "swing", "daytrade_proxy"]:
        samples = [x[key] for x in stock_backtests if key in x and x[key].get("signals", 0)]
        total_signals = sum(x.get("signals", 0) for x in samples)

        if not samples or total_signals == 0:
            result[key] = {
                "signals": 0,
                "win_rate": None,
                "avg_return": None,
                "max_drawdown": None,
                "note": "目前250日資料沒有足夠訊號。"
            }
            continue

        weighted_win = sum(
            (x.get("win_rate", 0) or 0) * x.get("signals", 0)
            for x in samples
        ) / total_signals
        weighted_avg = sum(
            (x.get("avg_return", 0) or 0) * x.get("signals", 0)
            for x in samples
        ) / total_signals

        result[key] = {
            "signals": total_signals,
            "win_rate": round(weighted_win, 2),
            "avg_return": round(weighted_avg, 4),
            "max_drawdown": round(min((x.get("max_drawdown", 0) or 0) for x in samples), 4),
            "note": samples[0].get("note", "")
        }

    return result


# ============================================================
# Data extraction
# ============================================================
if not FINLAB_TOKEN:
    raise ValueError("找不到 FINLAB_API_TOKEN！")

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
dividend_df = load_first([
    "dividend_announcement:現金股利",
    "distribution_of_share_dividend:現金股利",
], "現金股利")

institutional = load_first([
    "institutional_investors_trading_summary:投信買賣超股數"
], "投信買賣超股數")

foreign = load_first([
    "institutional_investors_trading_summary:外陸資買賣超股數(不含外資自營商)"
], "外資買賣超股數")

if institutional is not None and foreign is not None:
    inst_total = institutional.add(foreign, fill_value=0)
elif institutional is not None:
    inst_total = institutional
else:
    inst_total = foreign

print("[5/6] 計算熱門500檔股票池…")
latest_date = close.index[-1]
latest_close = close.loc[latest_date]
latest_vol = volume.reindex(index=close.index).loc[latest_date]

liquidity = pd.DataFrame({
    "close": latest_close,
    "volume": latest_vol
}).dropna()

liquidity = liquidity[
    liquidity.index.astype(str).str.len().eq(4)
    & liquidity.index.astype(str).str.isdigit()
].copy()

liquidity["amount"] = liquidity["close"] * liquidity["volume"]
liquidity = liquidity.replace([np.inf, -np.inf], np.nan).dropna(subset=["amount"])
liquidity = liquidity[liquidity["amount"] > 0].sort_values("amount", ascending=False).head(HOT_STOCK_COUNT)

target_symbols = [normalize_symbol(x) for x in liquidity.index.tolist()]

amount_ranks = (
    liquidity["amount"].rank(method="min", ascending=True, pct=True)
    .to_dict()
)

root_ref = init_firebase()
old_stocks = load_existing_stocks(root_ref)

# Name/category map; security_categories is explicitly used by the original project.
stock_meta_map = {}
try:
    sec_info = data.get("security_categories")
    if sec_info is not None and not sec_info.empty:
        for idx, row in sec_info.iterrows():
            sym = normalize_symbol(row.get("stock_id", idx))
            stock_meta_map[sym] = {
                "name": str(row.get("name", sym)).strip(),
                "category": str(row.get("category", "一般")).strip()
            }
except Exception as exc:
    print(f"[DATA] security_categories 略過：{exc}")

stocks = {}
stock_backtests = []

print("[6/6] 建立500檔資料、250日K線與模型…")

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
        kline = []

        for d in recent_dates:
            if d not in s_open.index or d not in s_high.index or d not in s_low.index or d not in s_volume.index:
                continue

            c = safe_float(s_close.loc[d])
            o = safe_float(s_open.loc[d])
            h = safe_float(s_high.loc[d])
            l = safe_float(s_low.loc[d])
            v = safe_float(s_volume.loc[d])

            if None in (c, o, h, l):
                continue

            kline.append({
                "time": iso_date(d),
                "open": round(o, 4),
                "high": round(h, 4),
                "low": round(l, 4),
                "close": round(c, 4),
                "volume": safe_int(v),
                "amount": round(c * v, 2) if v is not None else None
            })

        if len(kline) < 60:
            continue

        meta = stock_meta_map.get(sym, {"name": sym, "category": "一般"})
        current_price = safe_float(s_close.iloc[-1])

        # Current fundamentals only; missing values stay None.
        pe_v = latest_value(pe, sym)
        pb_v = latest_value(pb, sym)
        rev_v = latest_value(rev_yoy, sym)
        roe_v = latest_value(roe, sym)
        eps_v = latest_value(eps, sym)
        gm_v = latest_value(gross_margin, sym)
        opm_v = latest_value(operating_margin, sym)
        fcf_v = latest_value(fcf, sym)
        debt_v = latest_value(debt_ratio, sym)

        # Latest cash dividend. No synthetic fallback.
        dividend_v = latest_value(dividend_df, sym)
        yield_v = (dividend_v / current_price * 100) if dividend_v is not None and current_price else None

        # Dividend continuity: count positive annual records in the latest 5 calendar years.
        continuity_years = None
        if dividend_df is not None and sym in dividend_df.columns:
            ds = dividend_df[sym].dropna()
            if not ds.empty:
                try:
                    five_year_cutoff = pd.Timestamp(latest_date) - pd.DateOffset(years=5)
                    ds = ds[ds.index >= five_year_cutoff]
                    continuity_years = int((ds > 0).sum())
                except Exception:
                    continuity_years = None

        net15 = None
        inst_history = []
        if inst_total is not None and sym in inst_total.columns:
            inst_series = inst_total[sym].dropna().iloc[-INSTITUTION_DAYS:]
            if not inst_series.empty:
                net15 = int(inst_series.sum())
                inst_history = [
                    {"time": iso_date(idx), "net_shares": safe_int(val)}
                    for idx, val in inst_series.items()
                ]

        # Use locally preserved historical data to avoid re-downloading history from Firebase.
        old = old_stocks.get(sym, {})
        old_kline = old.get("kline", []) if isinstance(old, dict) else []

        # Merge the new 250-day FinLab snapshot with the existing snapshot.
        kline_map = {}
        for row in old_kline:
            if isinstance(row, dict) and row.get("time"):
                kline_map[row["time"]] = row
        for row in kline:
            kline_map[row["time"]] = row

        merged_kline = sorted(kline_map.values(), key=lambda x: x["time"])[-KLINE_DAYS:]

        # Compute current Sharpe from stored price history.
        kclose = [safe_float(x.get("close")) for x in merged_kline]
        kclose = [x for x in kclose if x is not None]
        sharpe20 = sharpe_annualized(kclose[-20:]) if len(kclose) >= 20 else None

        # Stock-level backtests.
        bt = {
            "rebound": backtest_rebound(merged_kline),
            "swing": backtest_swing(merged_kline),
            "daytrade_proxy": backtest_daytrade_proxy(merged_kline),
        }
        stock_backtests.append(bt)

        stock_obj = {
            "symbol": sym,
            "name": meta["name"],
            "category": meta["category"],

            "hot_rank": hot_rank,
            "updated_at": iso_date(latest_date),

            "price": round(current_price, 4),
            "open": round(safe_float(s_open.iloc[-1]), 4) if safe_float(s_open.iloc[-1]) is not None else None,
            "high": round(safe_float(s_high.iloc[-1]), 4) if safe_float(s_high.iloc[-1]) is not None else None,
            "low": round(safe_float(s_low.iloc[-1]), 4) if safe_float(s_low.iloc[-1]) is not None else None,
            "volume": safe_int(s_volume.iloc[-1]),
            "amount": round(float(liquidity.loc[sym, "amount"]), 2),
            "amount_rank_pct": round(float(amount_ranks.get(sym, 0.5)), 6),

            "pe": pe_v,
            "pb": pb_v,
            "rev_yoy": rev_v,
            "roe": roe_v,
            "eps": eps_v,
            "gross_margin": gm_v,
            "operating_margin": opm_v,
            "fcf": fcf_v,
            "debt_ratio": debt_v,

            "dividend": dividend_v,
            "yield_pct": yield_v,
            "dividend_continuity_years": continuity_years,

            "net15Total": net15,
            "institution_history": inst_history,

            "sharpe20": sharpe20,
            "backtest": bt,

            "kline": merged_kline
        }

        stocks[sym] = stock_obj

    except Exception as exc:
        print(f"[WARN] {sym} 跳過：{exc}")


global_backtests = aggregate_backtests(stock_backtests)

avg_quality_fields = [
    "pe","pb","rev_yoy","roe","eps","fcf","debt_ratio",
    "dividend","net15Total","sharpe20"
]

quality_count = 0
quality_total = 0
for s in stocks.values():
    quality_count += 1
    quality_total += sum(1 for key in avg_quality_fields if s.get(key) is not None)

data_quality_pct = round(
    quality_total / max(1, quality_count * len(avg_quality_fields)) * 100,
    2
)

# Save only the current hot-500 universe in Firebase.
# No service-account file and no FinLab token is stored in the repository.
output = {
    "updated_at": iso_date(latest_date),
    "source": "FinLab",
    "universe": {
        "name": "熱門500檔",
        "definition": "最新成交金額排名前500檔、四位數台股",
        "count": len(stocks)
    },
    "metadata": {
        "version": "0.40",
        "kline_days": KLINE_DAYS,
        "institution_days": INSTITUTION_DAYS,
        "data_quality_pct": data_quality_pct,
        "notes": [
            "缺失資料保留為 null，不用固定數字或虛構殖利率補值。",
            "熱門500依最新成交金額排序。",
            "當沖模型目前使用日線代理資料，不等同真實5/15分鐘盤中大單資料。",
            "長期高息策略只使用真實現金股利資料；缺失時不進入8%以上高息條件。",
            "回測為目前250日資料的樣本內驗證，不保證未來績效。"
        ]
    },
    "backtests": global_backtests,
    "stocks": stocks
}

print(f"[FIREBASE] 準備寫入 {len(stocks)} 檔…")
root_ref.set(output)

print(
    f"完成：{len(stocks)} 檔熱門500、更新日 {output['updated_at']}、"
    f"資料完整度 {data_quality_pct}%、"
    f"回測訊號 {sum(v.get('signals', 0) for v in global_backtests.values())}"
)
