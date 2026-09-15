import math
import statistics
from typing import Any


# =========================================================
# 基礎工具
# =========================================================

def num(value: Any):
    try:
        if value is None or value == "":
            return None

        value = float(value)

        if math.isfinite(value):
            return value

        return None

    except (TypeError, ValueError):
        return None


def clamp(value, low=0.0, high=1.0):
    return max(low, min(high, value))


def sma(values, period):
    if len(values) < period:
        return None

    return sum(values[-period:]) / period


# =========================================================
# K棒工具
# =========================================================

def bar_position(bar):

    span = bar["high"] - bar["low"]

    if span <= 0:
        return 0.5

    return clamp(
        (bar["close"] - bar["low"])
        / span
    )


def upper_wick_ratio(bar):

    span = bar["high"] - bar["low"]

    if span <= 0:
        return 0.0

    body_top = max(
        bar["open"],
        bar["close"]
    )

    return clamp(
        (bar["high"] - body_top)
        / span
    )


# =========================================================
# 趨勢判斷
# =========================================================

def trend_score(rows):

    if len(rows) < 2:
        return 0.0, []

    closes = [
        row["close"]
        for row in rows
    ]

    short_ma = sma(
        closes,
        3
    )

    slow_ma = sma(
        closes,
        6
    )

    last_close = closes[-1]

    recent = rows[
        -min(4, len(rows)):
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
            >= recent[i - 1]["low"]
        ):
            higher_lows += 1

        if (
            recent[i]["high"]
            >= recent[i - 1]["high"]
        ):
            higher_highs += 1


    score = 0.0
    reasons = []


    if (
        short_ma is not None
        and slow_ma is not None
        and last_close > short_ma > slow_ma
    ):

        score += 0.55
        reasons.append(
            "短均線多頭"
        )


    elif (
        short_ma is not None
        and last_close > short_ma
    ):

        score += 0.35


    elif last_close > closes[0]:

        score += 0.25


    score += (
        0.225
        * (
            higher_lows
            / comparisons
        )
    )


    score += (
        0.225
        * (
            higher_highs
            / comparisons
        )
    )


    if (
        higher_lows
        >= max(
            1,
            comparisons - 1
        )
        and
        higher_highs
        >= max(
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

def calculate_vwap(rows):

    if not rows:
        return None


    total_volume = sum(
        float(row.get("volume", 0))
        for row in rows
    )


    if total_volume <= 0:
        return None


    total_value = 0.0


    for row in rows:

        typical_price = (
            row["high"]
            + row["low"]
            + row["close"]
        ) / 3


        total_value += (
            typical_price
            * row.get(
                "volume",
                0
            )
        )


    return (
        total_value
        / total_volume
    )


# =========================================================
# 量能
# =========================================================

def volume_score(rows):

    if len(rows) < 10:

        return (
            0.4,
            None
        )


    recent = [
        row["volume"]
        for row in rows[-3:]
    ]


    base = [
        row["volume"]
        for row in rows[-12:-3]
        if row["volume"] > 0
    ]


    if not base:

        return (
            0.4,
            None
        )


    recent_avg = (
        sum(recent)
        / len(recent)
    )


    base_avg = (
        sum(base)
        / len(base)
    )


    if base_avg <= 0:

        return (
            0.4,
            None
        )


    ratio = (
        recent_avg
        / base_avg
    )


    score = clamp(
        (ratio - 0.7)
        / 1.8
    )


    return (
        score,
        ratio
    )


# =========================================================
# 股票流動性
# =========================================================

def liquidity_score(stock):

    amount_pct = num(
        stock.get(
            "amount_rank_pct"
        )
    )


    if amount_pct is not None:

        return clamp(
            amount_pct
        )


    hot_rank = num(
        stock.get(
            "hot_rank"
        )
    )


    if hot_rank is None:

        return 0.5


    universe = 500


    return clamp(
        1.0
        - (
            hot_rank - 1
        )
        / (
            universe - 1
        )
    )


# =========================================================
# 歷史策略 Edge
# =========================================================

def historical_edge_score(stock):

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


    signals = (
        num(
            proxy.get(
                "signals"
            )
        )
        or 0
    )


    edge = 0.45


    if signals >= 20:

        pf_score = clamp(
            (
                (
                    profit_factor
                    or 1
                )
                - 0.8
            )
            / 0.8
        )


        return_score = clamp(
            (
                (
                    avg_return
                    or 0
                )
                + 0.005
            )
            / 0.02
        )


        edge = clamp(
            0.35
            + pf_score * 0.35
            + return_score * 0.30
        )


    return edge


# =========================================================
# 主策略
# =========================================================

def evaluate_daytrade(
    rows5,
    rows15,
    stock=None,
    market_level="YELLOW"
):

    stock = stock or {}


    if not rows5:

        return {
            "eligible": False,
            "reason": "沒有5分K資料"
        }


    if len(rows5) < 6:

        return {
            "eligible": False,
            "reason": "5分K資料不足"
        }


    if len(rows15) < 2:

        return {
            "eligible": False,
            "reason": "15分K資料不足"
        }


    last = rows5[-1]

    close = float(
        last["close"]
    )


    # =====================================================
    # 當日高低
    # =====================================================

    day_high = max(
        row["high"]
        for row in rows5
    )


    day_low = min(
        row["low"]
        for row in rows5
    )


    day_span = max(
        0.000000001,
        day_high - day_low
    )


    day_position = clamp(
        (
            close
            - day_low
        )
        / day_span
    )


    # =====================================================
    # VWAP
    # =====================================================

    vwap = calculate_vwap(
        rows5
    )


    if vwap:

        vwap_distance = (
            close / vwap
            - 1
        )

    else:

        vwap_distance = None


    # =====================================================
    # 5M / 15M 趨勢
    # =====================================================

    five_trend, five_reasons = (
        trend_score(
            rows5
        )
    )


    fifteen_trend, fifteen_reasons = (
        trend_score(
            rows15
        )
    )


    # =====================================================
    # 量能
    # =====================================================

    vol_score, vol_ratio = (
        volume_score(
            rows5
        )
    )


    # =====================================================
    # Opening Range Breakout
    # 前6根5分鐘 = 前30分鐘
    # =====================================================

    opening = rows5[:6]


    opening_high = max(
        (
            row["high"]
            for row in opening
        ),
        default=None
    )


    orb = bool(
        opening_high is not None
        and len(rows5) >= 7
        and close
        > opening_high * 1.001
    )


    # =====================================================
    # 壓縮後突破
    # =====================================================

    compression_breakout = False


    if len(rows5) >= 7:

        previous = (
            rows5[-7:-1]
        )


        pre_high = max(
            row["high"]
            for row in previous
        )


        pre_low = min(
            row["low"]
            for row in previous
        )


        pre_mid = statistics.mean(
            row["close"]
            for row in previous
        )


        if pre_mid > 0:

            compression = (
                (
                    pre_high
                    - pre_low
                )
                / pre_mid
                <= 0.018
            )


            compression_breakout = bool(

                compression

                and close
                > pre_high

                and (
                    vol_ratio
                    or 0
                )
                >= 1.15

            )


    # =====================================================
    # 日K趨勢
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

        sma20

        and sma60

        and close > sma20

        and close > sma60

    )


    # =====================================================
    # Pattern score
    # =====================================================

    pattern_score = clamp(

        five_trend * 0.55

        + fifteen_trend * 0.30

        + (
            0.15
            if (
                orb
                or compression_breakout
            )
            else 0
        )

    )


    # =====================================================
    # VWAP score
    # =====================================================

    vwap_score = 0.2


    if vwap:

        if close >= vwap:

            if (
                vwap_distance
                is not None
                and vwap_distance
                <= 0.02
            ):

                vwap_score = 0.85

            else:

                vwap_score = 0.60

        else:

            vwap_score = 0.10


    # =====================================================
    # 市場燈號
    # =====================================================

    market_score = {

        "GREEN": 1.00,

        "YELLOW": 0.60,

        "RED": 0.15,

    }.get(
        market_level,
        0.50
    )


    liquidity = (
        liquidity_score(
            stock
        )
    )


    historical_edge = (
        historical_edge_score(
            stock
        )
    )


    # =====================================================
    # 當沖分數
    # =====================================================

    daytrade_score = round(

        100
        * (

            pattern_score
            * 0.30

            + vol_score
            * 0.20

            + vwap_score
            * 0.15

            + market_score
            * 0.10

            + liquidity
            * 0.10

            + historical_edge
            * 0.15

        )

    )


    # =====================================================
    # Veto
    # =====================================================

    vetoes = []


    if (
        vwap
        and close
        < vwap * 0.998
    ):

        vetoes.append(
            "跌破VWAP"
        )


    if (
        vwap_distance
        is not None
        and vwap_distance
        > 0.03
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


    if len(rows5) >= 7:

        recent_low = min(

            row["low"]

            for row
            in rows5[-6:-1]

        )


        if close <= recent_low:

            vetoes.append(
                "5分K破短低"
            )


    if market_level == "RED":

        vetoes.append(
            "市場紅燈"
        )


    # =====================================================
    # 進場理由
    # =====================================================

    reasons = []


    if five_trend >= 0.65:

        reasons.append(
            "5分K多頭"
        )


    if fifteen_trend >= 0.60:

        reasons.append(
            "15分K同向"
        )


    if (
        vwap
        and close >= vwap
    ):

        reasons.append(
            "站上VWAP"
        )


    if (
        vol_ratio
        or 0
    ) >= 1.30:

        reasons.append(
            f"量能放大 {vol_ratio:.1f}x"
        )


    if orb:

        reasons.append(
            "突破早盤區間"
        )


    elif compression_breakout:

        reasons.append(
            "壓縮後放量突破"
        )


    if daily_uptrend:

        reasons.append(
            "日K多頭"
        )


    # =====================================================
    # 最終進場條件
    # =====================================================

    eligible = bool(

        daytrade_score >= 76

        and len(vetoes) == 0

        and len(reasons) >= 2

    )


    return {

        "eligible":
            eligible,

        "daytrade_score":
            daytrade_score,

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

        "day_position":
            round(
                day_position,
                4
            ),

        "opening_range_breakout":
            orb,

        "compression_breakout":
            compression_breakout,

        "daily_uptrend":
            daily_uptrend,

        "historical_edge":
            round(
                historical_edge
                * 100,
                1
            ),

        "vetoes":
            vetoes,

        "daytrade_reasons":
            reasons[:4],

        "five_trend_reasons":
            five_reasons,

        "fifteen_trend_reasons":
            fifteen_reasons,

    }
