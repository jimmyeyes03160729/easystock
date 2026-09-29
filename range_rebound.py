"""Shared range-rebound rules for EasyStock Web/Chrome publication.

This is the server-side counterpart of assets/rebound-engine.js (range-rebound-0.3).
It publishes one deterministic feed so the website, Chrome extension and bots can
consume the same selected symbols instead of re-implementing strategy selection.
"""
from __future__ import annotations

from datetime import date, datetime
from math import isfinite
from statistics import median
from typing import Any

RULE_VERSION = "range-rebound-0.3"
MIN_BARS = 90
MIN_TOUCH_GAP = 7
MIN_TOUCH_SPAN = 14
MIN_RANGE = 0.10
MAX_RANGE_POSITION = 0.35
MAX_ABOVE_SUPPORT = 0.10
MIN_NET_RR = 1.5
COST_PCT = 0.006


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if isfinite(n) else None


def _day_number(value: Any) -> int | None:
    try:
        return date.fromisoformat(str(value)[:10]).toordinal()
    except (TypeError, ValueError):
        return None


def evaluate_financial(stock: dict[str, Any], asof: str) -> dict[str, Any]:
    missing: list[str] = []
    failed: list[str] = []
    checks: list[dict[str, Any]] = []
    optional: list[dict[str, Any]] = []

    category = str(stock.get("category") or "")
    name = str(stock.get("name") or "")
    if category.strip() == "17" or any(x in category for x in ("金融", "銀行", "保險", "證券")) or any(
        x in name for x in ("金控", "銀行", "證券", "產險", "壽險")
    ):
        return {"status": "unsupported", "missing": [], "failed": ["金融業需另訂財務門檻"], "checks": [], "optional": []}

    rules = [
        ("rev_yoy", "單月營收年增", lambda v: v >= -20),
        ("eps", "每股盈餘", lambda v: v > 0),
        ("operating_margin", "營業利益率", lambda v: v > 0),
        ("debt_ratio", "負債比", lambda v: 0 <= v < 70),
    ]
    meta_map = stock.get("field_meta") or {}
    fallback = set(stock.get("legacy_fallback_fields") or [])
    asof_day = _day_number(asof)

    for key, label, passed in rules:
        meta = meta_map.get(key) if isinstance(meta_map, dict) else None
        value = _num(stock.get(key))
        observed = _day_number(meta.get("as_of")) if isinstance(meta, dict) else None
        age = (asof_day - observed) if asof_day is not None and observed is not None else None
        source = meta.get("source") if isinstance(meta, dict) else None
        usable = value is not None and source in {"official-api", "official-filings"} and age is not None and 0 <= age <= 45 and key not in fallback
        if not usable:
            missing.append(label)
        elif not passed(value):
            failed.append(label + "未達初篩")
        else:
            checks.append(
                {
                    "key": key,
                    "label": label,
                    "value": value,
                    "observed_at": meta.get("as_of"),
                    "period": meta.get("period"),
                }
            )

    fcf_meta = meta_map.get("fcf") if isinstance(meta_map, dict) else None
    fcf_value = _num(stock.get("fcf"))
    fcf_observed = _day_number(fcf_meta.get("as_of")) if isinstance(fcf_meta, dict) else None
    fcf_age = (asof_day - fcf_observed) if asof_day is not None and fcf_observed is not None else None
    fcf_usable = (
        fcf_value is not None
        and isinstance(fcf_meta, dict)
        and fcf_meta.get("source") in {"official-api", "official-filings"}
        and fcf_age is not None
        and 0 <= fcf_age <= 200
        and "fcf" not in fallback
    )
    optional.append(
        {
            "key": "fcf",
            "label": "自由現金流",
            "status": ("positive" if fcf_value and fcf_value > 0 else "negative") if fcf_usable else "unavailable",
            "value": fcf_value if fcf_usable else None,
            "observed_at": fcf_meta.get("as_of") if fcf_usable else None,
            "period": fcf_meta.get("period") if fcf_usable else None,
        }
    )

    rev = "".join(ch for ch in str(stock.get("revenue_period") or "") if ch.isdigit())
    yr = mo = None
    if len(rev) == 5:
        yr, mo = int(rev[:3]) + 1911, int(rev[3:])
    elif len(rev) == 6:
        yr, mo = int(rev[:4]), int(rev[4:])
    try:
        asof_date = date.fromisoformat(asof)
        gap = (asof_date.year - yr) * 12 + asof_date.month - mo if yr and mo and 1 <= mo <= 12 else None
    except ValueError:
        gap = None
    if gap is None or not 1 <= gap <= 2:
        missing.append("近期營收月份")

    status = "failed" if failed else ("incomplete" if missing else "passed")
    return {
        "status": status,
        "missing": list(dict.fromkeys(missing)),
        "failed": failed,
        "checks": checks,
        "optional": optional,
    }


def _clusters(points: list[dict[str, Any]], tolerance: float) -> list[dict[str, Any]]:
    groups: list[list[dict[str, Any]]] = []
    for point in points:
        group = None
        for candidate in groups:
            center = median([x["v"] for x in candidate])
            if center and abs(point["v"] / center - 1) <= tolerance:
                group = candidate
                break
        if group is None:
            group = []
            groups.append(group)
        if not group or point["i"] - group[-1]["i"] >= MIN_TOUCH_GAP:
            group.append(point)

    result = []
    for group in groups:
        if len(group) >= 2 and group[-1]["i"] - group[0]["i"] >= MIN_TOUCH_SPAN:
            result.append(
                {
                    "price": median([x["v"] for x in group]),
                    "touches": len(group),
                    "last": group[-1]["i"],
                }
            )
    return result


def evaluate_technical(rows: list[dict[str, Any]], asof: str, price: Any) -> dict[str, Any]:
    def fail(reason: str) -> dict[str, Any]:
        return {"eligible": False, "reason": reason, "rule_version": RULE_VERSION}

    if not isinstance(rows, list):
        return fail("缺少日 K")
    bars = [b for b in rows if _day_number(b.get("time")) is not None and str(b.get("time")) <= asof][-252:]
    if len(bars) < MIN_BARS:
        return fail("日 K 少於 90 個交易日")
    if str(bars[-1].get("time")) != asof:
        return fail("K 線與行情日期不一致")

    normalized: list[dict[str, float | str]] = []
    for i, raw in enumerate(bars):
        vals = {k: _num(raw.get(k)) for k in ("open", "high", "low", "close")}
        if any(v is None or v <= 0 for v in vals.values()):
            return fail("K 線結構或日期異常")
        if vals["high"] < max(vals["open"], vals["close"], vals["low"]) or vals["low"] > min(vals["open"], vals["close"]):
            return fail("K 線結構或日期異常")
        if i and str(raw.get("time")) <= str(bars[i - 1].get("time")):
            return fail("K 線結構或日期異常")
        if normalized and abs(vals["open"] / normalized[-1]["close"] - 1) > 0.12:
            return fail("價格跳空過大，需核對除權息與資料")
        normalized.append(
            {
                "time": str(raw.get("time")),
                "open": vals["open"],
                "high": vals["high"],
                "low": vals["low"],
                "close": vals["close"],
            }
        )
    bars = normalized
    p = _num(price)
    if p is None or p <= 0 or abs(p / bars[-1]["close"] - 1) > 0.005:
        return fail("最新價與日 K 不一致")

    atr_sum = 0.0
    for j, bar in enumerate(bars[-20:]):
        previous = bars[len(bars) - 21 + j]["close"]
        atr_sum += max(bar["high"] - bar["low"], abs(bar["high"] - previous), abs(bar["low"] - previous))
    atr = atr_sum / 20
    tolerance = min(0.04, max(0.02, atr / p))

    lows: list[dict[str, Any]] = []
    highs: list[dict[str, Any]] = []
    for i in range(3, len(bars) - 3):
        neighbours = bars[i - 3 : i] + bars[i + 1 : i + 4]
        if all(bars[i]["low"] <= x["low"] for x in neighbours) and any(bars[i]["low"] < x["low"] for x in neighbours):
            lows.append({"i": i, "v": bars[i]["low"]})
        if all(bars[i]["high"] >= x["high"] for x in neighbours) and any(bars[i]["high"] > x["high"] for x in neighbours):
            highs.append({"i": i, "v": bars[i]["high"]})

    supports = [
        g for g in _clusters(lows, tolerance)
        if g["last"] >= len(bars) - 100 and p >= g["price"] * (1 - tolerance) and p <= g["price"] * (1 + MAX_ABOVE_SUPPORT)
    ]
    supports.sort(key=lambda x: -x["price"])
    rejected: list[str] = []

    for support in supports:
        resistances = [
            g for g in _clusters(highs, tolerance)
            if g["price"] > p and g["last"] >= len(bars) - 120
        ]
        resistances.sort(key=lambda x: x["price"])
        resistance = resistances[0] if resistances else None
        if not resistance or resistance["price"] / support["price"] < 1 + MIN_RANGE:
            rejected.append("壓力觸及不足或區間小於 10%")
            continue

        floor = support["price"] * (1 - tolerance)
        ceiling = support["price"] * (1 + tolerance)
        if any(b["close"] < floor * 0.98 for b in bars[support["last"] + 1 :]):
            rejected.append("支撐曾收盤跌破")
            continue
        if (p - support["price"]) / (resistance["price"] - support["price"]) > MAX_RANGE_POSITION:
            rejected.append("已離開區間底部 35%")
            continue
        if not any(b["low"] <= ceiling and b["low"] >= floor * 0.98 for b in bars[-8:]):
            rejected.append("近 8 日未回測支撐")
            continue

        confirmed = False
        for i in range(len(bars) - 3, len(bars)):
            b = bars[i]
            prior = bars[i - 1]
            if b["close"] > prior["high"] and b["close"] > b["open"] and all(x["close"] >= prior["high"] for x in bars[i:]):
                confirmed = True
                break
        last, prev, third = bars[-1], bars[-2], bars[-3]
        early = (
            last["close"] > prev["close"] > third["close"]
            and last["close"] > last["open"]
            and last["high"] > last["low"]
            and (last["close"] - last["low"]) / (last["high"] - last["low"]) >= 0.65
        )
        prior_lows = [b["low"] for b in bars[-6:-1]]
        if last["low"] < min(prior_lows) * 0.995 or (not confirmed and not early):
            rejected.append("尚未確認突破或連兩日止跌")
            continue

        invalid = floor - max(atr * 0.5, p * 0.01)
        target = resistance["price"] * (1 - tolerance)
        risk = p - invalid
        reward = target - p
        cost = p * COST_PCT
        rr = reward / risk if risk > 0 else -1
        net_rr = (reward - cost) / (risk + cost) if risk + cost > 0 else -1
        if not (risk > 0 and reward > cost and net_rr >= MIN_NET_RR):
            rejected.append("扣假設成本後空間不足 1.5 倍")
            continue

        score = min(
            95,
            round(
                55
                + min(support["touches"], 4) * 4
                + min(resistance["touches"], 4) * 3
                + min(net_rr, 5) * 2
                + (3 if confirmed else 0)
            ),
        )
        return {
            "eligible": True,
            "score": score,
            "dailyChangePct": (last["close"] / prev["close"] - 1) * 100,
            "support": [floor, ceiling],
            "resistance": [resistance["price"] * (1 - tolerance), resistance["price"] * (1 + tolerance)],
            "invalid": invalid,
            "target": target,
            "rr": rr,
            "netRR": net_rr,
            "costPct": COST_PCT,
            "confirmation": "breakout" if confirmed else "early",
            "touches": support["touches"],
            "pressureTouches": resistance["touches"],
            "reasons": [
                "多次回測支撐",
                "近 8 日回測、今日未破近期低點",
                "近 3 日突破昨高並守穩" if confirmed else "連兩日收高、收紅且位於當日上緣",
            ],
            "rule_version": RULE_VERSION,
            "validated": False,
        }

    return fail("；".join(dict.fromkeys(rejected)) if supports and rejected else "未形成重複支撐或距支撐超過 10%")


def build_rebound_feed(
    summaries: dict[str, dict[str, Any]],
    klines: dict[str, list[dict[str, Any]]],
    asof: str,
    release_id: str,
    generated_at: str,
) -> dict[str, Any]:
    passed: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []

    for symbol, stock in summaries.items():
        if not str(symbol).isdigit() or len(str(symbol)) != 4:
            continue
        if str(stock.get("updated_at") or "") != asof:
            continue
        amount = _num(stock.get("amount"))
        if amount is None or amount < 5_000_000:
            continue
        financial = evaluate_financial(stock, asof)
        if financial["status"] in {"failed", "unsupported"}:
            continue
        technical = evaluate_technical(klines.get(symbol) or [], asof, stock.get("price"))
        if not technical.get("eligible"):
            continue

        exchange = str(stock.get("exchange") or "").upper()
        market = "TWO" if exchange in {"TPEX", "TWO", "OTC"} else "TW"
        row = {
            "id": f"range-rebound:{asof}:{symbol}",
            "symbol": str(symbol),
            "market": market,
            "name": str(stock.get("name") or symbol),
            "price": float(stock["price"]),
            "change_pct": float(technical.get("dailyChangePct") or 0),
            "reason": " · ".join(technical.get("reasons") or ["底部反彈觀察"]),
            "score": technical.get("score"),
            "confirmation": technical.get("confirmation"),
            "generated_at": generated_at,
            "quote_at": f"{asof}T13:30:00+08:00",
            "strategy_version": RULE_VERSION,
            "technical": technical,
            "financial": financial,
        }
        (passed if financial["status"] == "passed" else pending).append(row)

    def rank(row: dict[str, Any]) -> tuple[int, float, str]:
        return (
            0 if row.get("confirmation") == "breakout" else 1,
            -float(row.get("score") or 0),
            str(row.get("symbol")),
        )

    passed.sort(key=rank)
    pending.sort(key=rank)
    return {
        "schema_version": 1,
        "release_id": release_id,
        "as_of": asof,
        "generated_at": generated_at,
        "strategy_version": RULE_VERSION,
        "signals": passed[:3],
        "pending": pending[:3],
    }
