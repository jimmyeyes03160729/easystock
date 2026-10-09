"""台股升降檔位 (Tick Size)，供 B1/B2/B3 跑道使用。"""
from __future__ import annotations


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
