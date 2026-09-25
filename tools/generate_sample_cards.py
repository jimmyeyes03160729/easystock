#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Generate sample LINE Bot cards using line_card_renderer_white for visual verification."""

import sys
from datetime import datetime, time, timedelta
from pathlib import Path

# Add vm_runtime to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vm_runtime"))

from line_card_renderer import (
    render_stock_intraday_card,
    render_market_intraday_card,
    render_k_card,
    render_institutional_card,
)

OUT_DIR = Path(__file__).resolve().parent / "sample_white_cards"
OUT_DIR.mkdir(parents=True, exist_ok=True)

def generate_samples():
    print("Generating White Theme sample cards...")

    # 1. P2330 Intraday Stock (台積電 2330 下跌 -1.00% matching screenshot)
    snap_p2330 = {
        "name": "台積電",
        "code": "2330",
        "category": "電子-半導體",
        "close": 2475.0,
        "change_price": -25.0,
        "change_rate": -1.00,
        "open": 2480.0,
        "high": 2490.0,
        "low": 2470.0,
        "average_price": 2478.5,
        "total_volume": 14324,
        "reference": 2500.0,
        "yesterday_volume": 18500,
        "estimated_volume": 15000,
        "timestamp_text": "09/24 13:30:00",
    }
    
    intraday_rows = []
    curr = 2485.0
    for m in range(271):
        h = 9 + (m // 60)
        mn = m % 60
        t = time(h, mn)
        if m < 40:
            curr += 0.2
        elif m < 120:
            curr -= 0.15
        elif m < 200:
            curr -= 0.08
        else:
            curr += 0.02
        intraday_rows.append({
            "time": t,
            "close": round(curr, 1),
            "volume": 60 + (m % 20) * 10,
        })

    p_card = render_stock_intraday_card(snap_p2330, intraday_rows, OUT_DIR / "sample_white_P2330.png")
    print(f"P2330 generated: {p_card}")

    # 2. Market Intraday (加權指數 48024.6 下跌 -132.69 matching screenshot 1)
    snap_market = {
        "name": "加權指數",
        "code": "",
        "category": "指數",
        "close": 48024.6,
        "change_price": -132.69,
        "change_rate": -0.27,
        "open": 48075.39,
        "high": 48117.54,
        "low": 47754.72,
        "total_amount": 736624000000, # 7366.24 億
        "reference": 48157.29,
        "up_count": 427,
        "down_count": 600,
        "limit_up_count": 11,
        "limit_down_count": 1,
        "timestamp_text": "09/24 13:33:00",
    }
    market_rows = []
    curr_m = 48075.0
    for m in range(271):
        h = 9 + (m // 60)
        mn = m % 60
        t = time(h, mn)
        if m < 30:
            curr_m += 1.2
        elif m < 90:
            curr_m -= 3.5
        elif m < 180:
            curr_m += 1.0
        else:
            curr_m += 0.5
        market_rows.append({
            "time": t,
            "close": round(curr_m, 2),
            "volume": 2500 + (m % 30) * 120,
        })

    m_card = render_market_intraday_card(snap_market, market_rows, OUT_DIR / "sample_white_P_market.png")
    print(f"P_market generated: {m_card}")

    # 3. K2330 Daily K-line (matching screenshot 2)
    k_rows = []
    base_price = 2250.0
    base_date = datetime(2026, 6, 26)
    for i in range(60):
        d = (base_date if i == 0 else datetime.fromordinal(base_date.toordinal() + int(i * 1.5))).strftime("%Y-%m-%d")
        op = base_price + (i * 3.5) + ((i % 5) - 2) * 8
        cl = op + ((i % 7) - 3) * 10 + 2.0
        hi = max(op, cl) + abs((i % 4) * 4) + 6
        lo = min(op, cl) - abs((i % 3) * 4) - 5
        vol = 14000 + (i % 12) * 800
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
    # Make the last row match the screenshot: open 2480, high 2490, low 2470, close 2475, vol 14324, date 2026-09-24
    k_rows[-1] = {
        "date": "2026-09-24",
        "open": 2480.0,
        "high": 2490.0,
        "max": 2490.0,
        "low": 2470.0,
        "min": 2470.0,
        "close": 2475.0,
        "Trading_Volume": 14324,
    }

    k_card = render_k_card("台積電", "2330", k_rows, OUT_DIR / "sample_white_K2330.png", is_market=False)
    print(f"K2330 generated: {k_card}")

    # 4. Institutional Card (matching screenshot 3)
    inst_rows = []
    for i in range(45):
        d = (datetime(2026, 7, 1) + timedelta(days=i * 2)).strftime("%Y-%m-%d")
        # Net buys/sells
        foreign_buy = 20000000 + ((i % 7) - 3) * 5000000
        foreign_sell = 20000000
        trust_buy = 5000000 + ((i % 5) - 2) * 2000000
        trust_sell = 5000000
        dealer_buy = 3000000 + ((i % 4) - 2) * 1500000
        dealer_sell = 3000000

        inst_rows.append({
            "date": d,
            "Foreign_Investor_buy": foreign_buy,
            "Foreign_Investor_sell": foreign_sell,
            "Foreign_Dealer_Self_buy": 0,
            "Foreign_Dealer_Self_sell": 0,
            "Investment_Trust_buy": trust_buy,
            "Investment_Trust_sell": trust_sell,
            "Dealer_buy": dealer_buy,
            "Dealer_sell": dealer_sell,
            "Dealer_self_buy": 0,
            "Dealer_self_sell": 0,
            "Dealer_Hedging_buy": 0,
            "Dealer_Hedging_sell": 0,
        })
    # Last day
    inst_rows[-1]["Foreign_Investor_buy"] = 10000000
    inst_rows[-1]["Foreign_Investor_sell"] = 14668000 # -4,668 張
    inst_rows[-1]["Investment_Trust_buy"] = 3000000
    inst_rows[-1]["Investment_Trust_sell"] = 4288000 # -1,288 張
    inst_rows[-1]["Dealer_buy"] = 2243000
    inst_rows[-1]["Dealer_sell"] = 2000000 # +243 張

    t_card = render_institutional_card("台積電", "2330", snap_p2330, inst_rows, OUT_DIR / "sample_white_T2330.png")
    print(f"T2330 generated: {t_card}")

if __name__ == "__main__":
    generate_samples()
