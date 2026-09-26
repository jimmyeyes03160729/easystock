#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Generate sample LINE Bot cards for visual verification."""

import sys
from datetime import datetime, time
from pathlib import Path

# Add vm_runtime to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vm_runtime"))

from line_card_renderer import (
    render_stock_intraday_card,
    render_market_intraday_card,
    render_k_card,
    render_institutional_card,
)

OUT_DIR = Path(__file__).resolve().parent / "sample_cards"
OUT_DIR.mkdir(parents=True, exist_ok=True)

def generate_samples():
    print("Generating sample cards...")

    # 1. P2330 Intraday Stock
    snap_p2330 = {
        "name": "台積電",
        "code": "2330",
        "close": 1045.0,
        "change_price": 25.0,
        "change_rate": 2.45,
        "open": 1030.0,
        "high": 1050.0,
        "low": 1025.0,
        "average_price": 1041.2,
        "total_volume": 48920,
        "reference": 1020.0,
        "yesterday_volume": 38500,
        "estimated_volume": 52000,
        "timestamp_text": "09/26 13:30 收盤盤後",
    }

    # 270 minutes (09:00 to 13:30)
    intraday_rows = []
    curr = 1028.0
    for m in range(271):
        h = 9 + (m // 60)
        mn = m % 60
        t = time(h, mn)
        # simulate upward trend
        if m < 40:
            curr += 0.35
        elif m < 120:
            curr += 0.05
        elif m < 180:
            curr += 0.12
        else:
            curr += 0.03
        intraday_rows.append({
            "time": t,
            "close": round(curr, 1),
            "volume": 80 + (m % 25) * 12,
        })

    p_card = render_stock_intraday_card(snap_p2330, intraday_rows, OUT_DIR / "sample_P2330.png")
    print(f"P2330 generated: {p_card}")

    # 2. K2330 Daily K-line
    k_rows = []
    base_price = 940.0
    base_date = datetime(2026, 7, 1)
    for i in range(60):
        d = (base_date.replace(day=1) if i == 0 else datetime.fromordinal(base_date.toordinal() + i)).strftime("%Y-%m-%d")
        op = base_price + (i * 1.6) + ((i % 5) - 2) * 3
        cl = op + ((i % 7) - 3) * 4 + 1.2
        hi = max(op, cl) + abs((i % 3) * 2) + 2
        lo = min(op, cl) - abs((i % 4) * 2) - 1.5
        vol = 28000 + (i % 15) * 1500
        k_rows.append({
            "date": d,
            "open": op,
            "high": hi,
            "max": hi,
            "low": lo,
            "min": lo,
            "close": cl,
            "Trading_Volume": vol,
        })

    k_card = render_k_card("台積電", "2330", k_rows, OUT_DIR / "sample_K2330.png", is_market=False)
    print(f"K2330 generated: {k_card}")

    # 3. Market Intraday
    snap_market = {
        "name": "加權指數",
        "code": "TAIEX",
        "close": 23450.8,
        "change_price": 185.3,
        "change_rate": 0.80,
        "open": 23320.0,
        "high": 23510.5,
        "low": 23290.0,
        "total_amount": 425000000000,
        "reference": 23265.5,
        "up_count": 580,
        "down_count": 320,
        "limit_up_count": 22,
        "limit_down_count": 1,
        "timestamp_text": "09/26 13:30 收盤盤後",
    }
    market_rows = []
    curr_m = 23310.0
    for m in range(271):
        h = 9 + (m // 60)
        mn = m % 60
        t = time(h, mn)
        curr_m += (0.6 if m < 60 else 0.2 if m < 180 else 0.4)
        market_rows.append({
            "time": t,
            "close": round(curr_m, 1),
            "volume": 2000 + (m % 30) * 150,
        })

    m_card = render_market_intraday_card(snap_market, market_rows, OUT_DIR / "sample_P_market.png")
    print(f"P_market generated: {m_card}")

    # 4. Institutional Card
    inst_rows = []
    for i in range(40):
        d = f"09/{i+1:02d}" if i < 30 else f"10/{i-29:02d}"
        inst_rows.append({
            "date": f"2026-{d.replace('/', '-')}",
            "Foreign_Investor_buy": 15000000 + (i % 5) * 2000000,
            "Foreign_Investor_sell": 12000000 + (i % 4) * 2500000,
            "Foreign_Dealer_Self_buy": 0,
            "Foreign_Dealer_Self_sell": 0,
            "Investment_Trust_buy": 4000000 + (i % 3) * 1000000,
            "Investment_Trust_sell": 2000000,
            "Dealer_buy": 2000000,
            "Dealer_sell": 2500000,
            "Dealer_self_buy": 0,
            "Dealer_self_sell": 0,
            "Dealer_Hedging_buy": 0,
            "Dealer_Hedging_sell": 0,
        })
    t_card = render_institutional_card("台積電", "2330", snap_p2330, inst_rows, OUT_DIR / "sample_T2330.png")
    print(f"T2330 generated: {t_card}")

if __name__ == "__main__":
    generate_samples()
