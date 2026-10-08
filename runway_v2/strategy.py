"""Runway V2: 高勝率當沖動能策略
核心原則：
1. 開盤搶跑 (09:05 ~ 09:35)：ORB 突破第一根 5 分 K 高點，伴隨爆量與強勢買盤。
2. 盤中回踩 (09:35 ~ 11:30)：回測 VWAP 不破，再度出量轉強。
3. 相對動能排名：依綜合強度打分，選取前 Top-K 標的，不被絕對閾值綁死。
"""
from __future__ import annotations
import math
from typing import Any
from .config import (
    MIN_PRICE,
    MAX_PRICE,
    MIN_GAIN_PCT,
    MAX_GAIN_PCT,
)
from .orderbook import OrderBookSnapshot, validate_orderbook


def calculate_vwap(bars: list[dict]) -> float | None:
    if not bars:
        return None
    total_volume = sum(float(b.get("volume", 0)) for b in bars)
    if total_volume <= 0:
        return None
    total_value = sum(
        ((float(b["high"]) + float(b["low"]) + float(b["close"])) / 3.0) * float(b.get("volume", 0))
        for b in bars
    )
    return total_value / total_volume


def score_candidate(
    price: float,
    vwap: float | None,
    previous_close: float,
    radar_metrics: dict,
    kbars5: list[dict] | None = None,
) -> tuple[float, list[str]]:
    """計算綜合動能得分 (0 ~ 100) 與進場理由。"""
    score = 0.0
    reasons = []

    gain_pct = (price / previous_close - 1.0) * 100.0 if previous_close > 0 else 0.0
    surge_60s = float(radar_metrics.get("surge_60s") or 0.0)
    buy_ratio_60s = float(radar_metrics.get("buy_ratio_60s") or 0.0)
    amount_60s = float(radar_metrics.get("amount_60s") or 0.0)

    # 1. 買盤強度 (最高 30 分)
    if buy_ratio_60s >= 0.85:
        score += 30.0
        reasons.append(f"強勢外盤買進 {buy_ratio_60s*100:.0f}%")
    elif buy_ratio_60s >= 0.70:
        score += 22.0
        reasons.append(f"主動買盤集中 {buy_ratio_60s*100:.0f}%")
    elif buy_ratio_60s >= 0.60:
        score += 15.0

    # 2. 瞬間爆量速度 (最高 25 分)
    if surge_60s >= 4.0:
        score += 25.0
        reasons.append(f"瞬間暴量 {surge_60s:.1f}x")
    elif surge_60s >= 2.0:
        score += 18.0
        reasons.append(f"量能增溫 {surge_60s:.1f}x")
    elif surge_60s >= 1.3:
        score += 10.0

    # 3. VWAP 結構 (最高 25 分)
    if vwap is not None and vwap > 0:
        vwap_dist = (price / vwap - 1.0) * 100.0
        if 0.2 <= vwap_dist <= 2.2:
            score += 25.0
            reasons.append("站穩均價線且距離適中")
        elif 0.0 <= vwap_dist < 0.2:
            score += 18.0
            reasons.append("貼近均價線支撐")
        elif 2.2 < vwap_dist <= 3.5:
            score += 12.0
        else:
            score += 0.0

    # 4. 漲幅動能健康度 (最高 20 分)
    # 漲幅在 2% ~ 6% 之間最容易持續上攻；低於 1% 動能不足，高於 8% 易追高反轉
    if 2.5 <= gain_pct <= 6.0:
        score += 20.0
        reasons.append(f"動能漲幅健康 +{gain_pct:.1f}%")
    elif 1.0 <= gain_pct < 2.5:
        score += 14.0
    elif 6.0 < gain_pct <= 7.5:
        score += 10.0

    return min(100.0, score), reasons


def evaluate_signal(
    symbol: str,
    name: str,
    current_price: float,
    previous_close: float,
    current_time_str: str,  # "HH:MM:SS"
    kbars5: list[dict],
    radar_metrics: dict,
    orderbook: OrderBookSnapshot | None = None,
) -> dict | None:
    """評估單檔股票是否符合進場訊號。
    回傳訊號字典或 None。
    """
    if current_price <= 0 or previous_close <= 0:
        return None

    # 1. 價格門檻
    if not (MIN_PRICE <= current_price <= MAX_PRICE):
        return None

    # 2. 漲幅門檻
    gain_pct = (current_price / previous_close - 1.0) * 100.0
    if not (MIN_GAIN_PCT <= gain_pct <= MAX_GAIN_PCT):
        return None

    # 3. 計算 VWAP
    vwap = calculate_vwap(kbars5)
    if vwap is not None and current_price < vwap * 0.998:
        # 跌破均價線一律不進場
        return None

    # 4. 型態判斷
    # 型態 A: ORB 早盤突破 (09:05 ~ 09:35)
    # 需要至少前一根 5 分 K
    signal_type = None
    is_orb = False
    is_pullback = False

    if "09:05:00" <= current_time_str <= "09:35:00" and kbars5:
        first_bar = kbars5[0]
        opening_high = float(first_bar.get("high", 0))
        if opening_high > 0 and current_price >= opening_high:
            is_orb = True
            signal_type = "ORB_BREAKOUT"

    # 型態 B: VWAP 回踩轉強 (09:35 ~ 11:30)
    elif "09:35:00" <= current_time_str <= "11:30:00" and len(kbars5) >= 3 and vwap:
        recent_bars = kbars5[-3:]
        # 檢查過去 2~3 根低點是否曾觸碰 VWAP 附近 (0.995 ~ 1.010)
        touched_vwap = any(
            0.995 <= (float(b["low"]) / vwap) <= 1.010 for b in recent_bars
        )
        # 最新一根是紅K且收在 VWAP 之上
        last_bar = recent_bars[-1]
        bullish_reversal = float(last_bar["close"]) > float(last_bar["open"]) and current_price >= vwap
        if touched_vwap and bullish_reversal:
            is_pullback = True
            signal_type = "VWAP_PULLBACK"

    if not (is_orb or is_pullback):
        return None

    # 5. 計算動能評分
    score, reasons = score_candidate(
        price=current_price,
        vwap=vwap,
        previous_close=previous_close,
        radar_metrics=radar_metrics,
        kbars5=kbars5,
    )

    # 門檻：綜合評分 >= 60 分
    if score < 60.0:
        return None

    # 6. 五檔微結構檢驗 (價差、流動性與 OBI 失衡度)
    if orderbook is not None:
        ob_ok, ob_reject, ob_reasons = validate_orderbook(orderbook, current_price)
        if not ob_ok:
            print(f"[RUNWAY_V2_OB_REJECT] {symbol} {name}: {ob_reject}")
            return None
        reasons.extend(ob_reasons)

    # 設定防守停損價：以進場價格下緣 1.5% 或 VWAP 低點
    structural_stop = current_price * 0.985
    if vwap and vwap * 0.995 > structural_stop:
        structural_stop = vwap * 0.995

    return {
        "symbol": symbol,
        "name": name,
        "price": current_price,
        "previous_close": previous_close,
        "gain_pct": gain_pct,
        "vwap": vwap,
        "signal_type": signal_type,
        "score": round(score, 1),
        "reasons": reasons,
        "stop_price": round(structural_stop, 2),
    }
