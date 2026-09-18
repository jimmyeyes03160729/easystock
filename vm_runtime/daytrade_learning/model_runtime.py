from __future__ import annotations

from dataclasses import dataclass
from typing import Any


MODEL_RUNTIME_VERSION = "gate-v2-disabled-no-approved-model"


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def live_features(
    *,
    price: float,
    previous_close: float,
    now_ts: float,
    ticks: list | None = None,
    radar: dict | None = None,
) -> dict:
    """
    組合盤中模型可用的基礎特徵。

    目前尚未部署 approved model，因此此函式只負責
    產生穩定、可記錄的 feature row，不執行模型推論。
    """

    ticks = ticks or []
    radar = radar or {}

    price = _num(price)
    previous_close = _num(previous_close)

    gain_pct = 0.0
    if previous_close > 0:
        gain_pct = (price / previous_close - 1.0) * 100.0

    return {
        "price": price,
        "previous_close": previous_close,
        "gain_pct": gain_pct,
        "timestamp": _num(now_ts),
        "tick_count": len(ticks),
        "surge_60s": _num(radar.get("surge_60s")),
        "buy_ratio_60s": _num(radar.get("buy_ratio_60s")),
        "price_change_60_pct": _num(
            radar.get("price_change_60_pct")
        ),
        "radar_rank": radar.get("radar_rank"),
    }


@dataclass
class DaytradeModel:
    """
    Daytrade model runtime gate.

    目前沒有已核准模型 artifact，因此採 fail-safe：
    - 不宣稱模型已啟用
    - 不阻擋原本 rule-based 當沖策略
    - 保留未來 approved model 接入介面
    """

    model_version: str = MODEL_RUNTIME_VERSION
    threshold: float = 0.60

    def evaluate(self, features: dict | None) -> dict:
        return {
            "active": False,
            "evaluated": False,
            "approved": False,
            "probability": None,
            "threshold": self.threshold,
            "model_version": self.model_version,
            "reason": "no_approved_model",
        }

    def predict(self, features: dict | None) -> float | None:
        return None

    def run(self, features: dict | None) -> dict:
        return self.evaluate(features)
