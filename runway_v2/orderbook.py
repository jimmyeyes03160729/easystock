"""Runway V2: 五檔委託簿 (BidAsk / OrderBook) 微結構分析與過濾器
提供：
1. 台股升降檔位 (Tick Size) 精確計算
2. 買賣價差與滑價防護 (Spread Filter)
3. 委買賣量失衡度 (Order Book Imbalance, OBI)
4. 深度承接度與阻力檢驗
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from .config import (
    ORDERBOOK_ENABLED,
    MAX_SPREAD_TICKS,
    MAX_SPREAD_PCT,
    MIN_OBI_THRESHOLD,
    MIN_BID1_VOLUME,
)


def get_tick_size(price: float) -> float:
    """計算台股法規標準之升降檔位 (Tick Size)"""
    if price < 10.0:
        return 0.01
    elif price < 50.0:
        return 0.05
    elif price < 100.0:
        return 0.10
    elif price < 500.0:
        return 0.50
    elif price < 1000.0:
        return 1.00
    else:
        return 5.00


@dataclass
class OrderBookSnapshot:
    symbol: str
    dt_str: str
    bid_prices: list[float]
    bid_volumes: list[int]
    ask_prices: list[float]
    ask_volumes: list[int]

    @property
    def spread(self) -> float:
        if not self.ask_prices or not self.bid_prices:
            return 0.0
        return max(0.0, self.ask_prices[0] - self.bid_prices[0])

    @property
    def spread_ticks(self) -> int:
        if not self.bid_prices:
            return 0
        tick = get_tick_size(self.bid_prices[0])
        return max(0, int(round(self.spread / tick)))

    @property
    def spread_pct(self) -> float:
        if not self.bid_prices or self.bid_prices[0] <= 0:
            return 0.0
        return self.spread / self.bid_prices[0]

    @property
    def total_bid_vol(self) -> int:
        return sum(self.bid_volumes)

    @property
    def total_ask_vol(self) -> int:
        return sum(self.ask_volumes)

    @property
    def obi(self) -> float:
        """Order Book Imbalance (-1.0 ~ +1.0)"""
        tot = self.total_bid_vol + self.total_ask_vol
        if tot <= 0:
            return 0.0
        return (self.total_bid_vol - self.total_ask_vol) / tot

    @property
    def bid1_vol(self) -> int:
        return self.bid_volumes[0] if self.bid_volumes else 0

    @property
    def ask1_vol(self) -> int:
        return self.ask_volumes[0] if self.ask_volumes else 0


def parse_shioaji_bidask(symbol: str, quote: Any) -> OrderBookSnapshot | None:
    """從 Shioaji BidAskSTKv1 或 Dict 物件中解析五檔快照"""
    try:
        # Shioaji BidAsk 物件格式屬性
        b_prices = getattr(quote, "bid_price", None)
        b_vols = getattr(quote, "bid_volume", None)
        a_prices = getattr(quote, "ask_price", None)
        a_vols = getattr(quote, "ask_volume", None)
        dt = getattr(quote, "datetime", None)

        # 若是 dict 格式
        if isinstance(quote, dict):
            b_prices = quote.get("bid_price", b_prices)
            b_vols = quote.get("bid_volume", b_vols)
            a_prices = quote.get("ask_price", a_prices)
            a_vols = quote.get("ask_volume", a_vols)
            dt = quote.get("datetime", dt)

        if not b_prices or not a_prices or not b_vols or not a_vols:
            return None

        # 轉成 float 與 int 陣列
        bid_prices = [float(p) for p in b_prices if p is not None and float(p) > 0]
        ask_prices = [float(p) for p in a_prices if p is not None and float(p) > 0]
        bid_volumes = [int(v) for v in b_vols[: len(bid_prices)]]
        ask_volumes = [int(v) for v in a_vols[: len(ask_prices)]]

        if not bid_prices or not ask_prices:
            return None

        dt_str = dt.isoformat() if isinstance(dt, datetime) else str(dt or "")
        return OrderBookSnapshot(
            symbol=symbol,
            dt_str=dt_str,
            bid_prices=bid_prices,
            bid_volumes=bid_volumes,
            ask_prices=ask_prices,
            ask_volumes=ask_volumes,
        )
    except Exception:
        return None


def validate_orderbook(
    ob: OrderBookSnapshot | None, current_price: float
) -> tuple[bool, str, list[str]]:
    """驗證五檔微結構是否符合進場條件：
    回傳: (is_valid, reject_reason, reasons_to_add)
    """
    if not ORDERBOOK_ENABLED:
        return True, "", ["五檔檢驗已停用"]

    if ob is None:
        # 容錯：若尚無五檔串流（回測或冷啟動），允許進場
        return True, "", ["五檔待命中(Fallback)"]

    # 1. 買賣價差與跳檔數過濾 (Spread Filter)
    # 若買賣一檔直接相鄰 (spread_ticks <= 1)，屬於市場最佳最小價差
    if ob.spread_ticks > MAX_SPREAD_TICKS:
        return (
            False,
            f"買賣價差過大 (差距 {ob.spread_ticks} 檔 > 上限 {MAX_SPREAD_TICKS} 檔)，拒絕追高防滑價",
            [],
        )

    if ob.spread_ticks > 1 and ob.spread_pct > MAX_SPREAD_PCT:
        return (
            False,
            f"價差比例過大 ({ob.spread_pct * 100:.2f}% > 上限 {MAX_SPREAD_PCT * 100:.2f}%)，流動性不足",
            [],
        )

    # 2. 買一掛單深度檢查 (Bid1 Depth Check)
    if ob.bid1_vol < MIN_BID1_VOLUME:
        return (
            False,
            f"買一掛單過薄 ({ob.bid1_vol} 張 < 下限 {MIN_BID1_VOLUME} 張)，下檔支撐薄弱",
            [],
        )

    # 3. 委買賣量失衡度過濾 (OBI Filter)
    if ob.obi < MIN_OBI_THRESHOLD:
        return (
            False,
            f"五檔賣壓極端壓頂 (OBI={ob.obi:.2f} < 門檻 {MIN_OBI_THRESHOLD:.2f})，多方動能受阻",
            [],
        )

    # 通過檢驗，產出具備實戰價值的微結構特徵標籤
    reasons = [
        f"五檔緊密(差{ob.spread_ticks}檔)",
        f"委買OBI={ob.obi:+.2f}",
        f"買一厚度{ob.bid1_vol}張",
    ]
    return True, "", reasons


class OrderBookTracker:
    """管理盤中各標的之最新五檔快照"""

    def __init__(self):
        self._snapshots: dict[str, OrderBookSnapshot] = {}

    def update(self, symbol: str, quote: Any) -> OrderBookSnapshot | None:
        snap = parse_shioaji_bidask(symbol, quote)
        if snap:
            self._snapshots[symbol] = snap
        return snap

    def get(self, symbol: str) -> OrderBookSnapshot | None:
        return self._snapshots.get(symbol)

    def clear(self) -> None:
        self._snapshots.clear()
