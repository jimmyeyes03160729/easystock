#!/usr/bin/env python3
"""
Easystock / Rebound Strategy Scanner
波段觸底反彈 盤中確認排程 (設定於 13:15 執行)

模型邏輯：
防線一：流動性與位階過濾 (繼承原版 select_candidates)
防線二：極端乖離 (距離 20MA 跌幅 > 15%)
防線三：右側確認 (突破昨高 + 收紅K + 近5日報酬轉正)
"""

from __future__ import annotations

import json
import os
import time
import math
import requests
import pandas as pd
from datetime import datetime, timedelta, timezone

import firebase_admin
from firebase_admin import credentials, db

# =========================================================
# 基本設定與常數 (繼承原專案)
# =========================================================
MODEL_VERSION = "1.0-rebound-strategy"
TPE = timezone(timedelta(hours=8))

FIREBASE_DATABASE_URL = os.environ.get("FIREBASE_DATABASE_URL", "").strip().rstrip("/")
FIREBASE_SERVICE_ACCOUNT_JSON = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON", "").strip()
FIREBASE_ROOT_PATH = os.environ.get("FIREBASE_ROOT_PATH", "market_data").strip("/") or "market_data"

FUGLE_API_KEY = os.environ.get("FUGLE_API_KEY", "").strip()
FUGLE_BASE = "https://api.fugle.tw/marketdata/v1.0/stock"
HTTP_TIMEOUT = float(os.environ.get("HTTP_TIMEOUT", "12"))
MIN_INTERVAL = max(0.0, float(os.environ.get("FUGLE_MIN_INTERVAL_SECONDS", "1.10")))

SCAN_MAX_SYMBOLS = max(5, int(os.environ.get("INTRADAY_SCAN_MAX_SYMBOLS", "50")))

# =========================================================
# HTTP Session & Rate Limit
# =========================================================
_last_call = 0.0
session = requests.Session()
session.headers.update({"User-Agent": "MohrenQuant/ReboundScanner/1.0", "Accept": "application/json"})

def wait_rate_limit() -> None:
    global _last_call
    elapsed = time.monotonic() - _last_call
    if elapsed < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - elapsed)
    _last_call = time.monotonic()

def num(value) -> float | None:
    try:
        if value is None or value == "": return None
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None

# =========================================================
# Firebase 初始化 (完全繼承)
# =========================================================
def init_firebase() -> db.Reference:
    if not FIREBASE_DATABASE_URL:
        raise RuntimeError("Missing FIREBASE_DATABASE_URL")

    if not firebase_admin._apps:
        service_account = json.loads(FIREBASE_SERVICE_ACCOUNT_JSON)
        credential = credentials.Certificate(service_account)
        firebase_admin.initialize_app(credential, {"databaseURL": FIREBASE_DATABASE_URL})

    return db.reference(f"/{FIREBASE_ROOT_PATH}")

# =========================================================
# Telegram 推播模組
# =========================================================
def send_telegram_alert(buy_list: list[dict]) -> None:
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    
    if not bot_token or not chat_id:
        print("[warn] 未設定 Telegram 憑證，略過推播。")
        return

    now_str = datetime.now(TPE).strftime('%Y-%m-%d %H:%M')
    
    if not buy_list:
        message = f"【EasyStock 觸底反彈】\n掃描時間：{now_str}\n本日無符合波段進場條件標的。"
    else:
        message = f"🚀【EasyStock 觸底反彈確認】\n掃描時間：{now_str}\n" + "="*20 + "\n"
        for item in buy_list:
            message += (
                f"📌 {item['symbol']} ({item['name']})\n"
                f"現價：{item['price']}\n"
                f"防守(停損)：{item['stop_loss']}\n"
                f"目標(20MA)：{item['target']}\n"
                f"--------------------\n"
            )

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message}
    try:
        resp = requests.post(url, json=payload, timeout=HTTP_TIMEOUT)
        if resp.status_code == 200:
            print("[telegram] 推播發送成功！")
        else:
            print(f"[telegram] 推播失敗：{resp.text}")
    except Exception as e:
        print(f"[telegram] 推播發生異常：{e}")

# =========================================================
# 富果 API：抓取日 K 線 (含今日盤中即時)
# =========================================================
def fetch_daily_kbars(symbol: str) -> pd.DataFrame | None:
    """獲取歷史日K，若無今日資料則自動補上即時行情"""
    wait_rate_limit()
    
    # 1. 抓取歷史日 K
    url = f"{FUGLE_BASE}/historical/candles/{symbol}"
    resp = session.get(url, params={"timeframe": "D"}, headers={"X-API-KEY": FUGLE_API_KEY}, timeout=HTTP_TIMEOUT)
    if resp.status_code != 200:
        return None
        
    data = resp.json().get("data", [])
    if not data:
        return None

    df = pd.DataFrame(data)
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date').reset_index(drop=True)

    # 2. 檢查是否包含今天，若無則打盤中 Quote API 補上
    today_str = datetime.now(TPE).strftime('%Y-%m-%d')
    last_date_str = df['date'].iloc[-1].strftime('%Y-%m-%d')

    if last_date_str != today_str:
        wait_rate_limit()
        q_url = f"{FUGLE_BASE}/intraday/quote/{symbol}"
        q_resp = session.get(q_url, headers={"X-API-KEY": FUGLE_API_KEY}, timeout=HTTP_TIMEOUT)
        
        if q_resp.status_code == 200:
            q_data = q_resp.json().get("data", {}).get("quote", {})
            if q_data and q_data.get("open"):
                today_row = {
                    "date": pd.to_datetime(today_str),
                    "open": q_data.get("open"),
                    "high": q_data.get("high"),
                    "low": q_data.get("low"),
                    "close": q_data.get("close"),
                    "volume": q_data.get("total", {}).get("tradeVolume", 0)
                }
                df = pd.concat([df, pd.DataFrame([today_row])], ignore_index=True)

    # 轉型並清理
    for col in ['open', 'high', 'low', 'close', 'volume']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    
    return df.dropna(subset=['close'])

# =========================================================
# 觸底反彈 核心演算法
# =========================================================
def check_easystock_rebound(df: pd.DataFrame, stock_info: dict) -> dict | None:
    if len(df) < 25:
        return None
        
    today = df.iloc[-1]
    yesterday = df.iloc[-2]
    
    # 【防線二：極端乖離】
    ma_20 = df['close'].rolling(window=20).mean().iloc[-1]
    bias_20 = (today['close'] - ma_20) / ma_20
    is_oversold = bias_20 <= -0.15 
    
    # 【防線三：右側確認】
    break_yesterday_high = today['close'] > yesterday['high']
    is_red_candle = today['close'] > today['open']
    
    # 近5日報酬轉正 (FinLab 實證濾網)
    price_5_days_ago = df.iloc[-6]['close']
    is_rebound_started = (today['close'] - price_5_days_ago) / price_5_days_ago > 0
    
    if is_oversold and break_yesterday_high and is_red_candle and is_rebound_started:
        stop_loss = df['low'].iloc[-3:].min() # 近3日最低點為防守點
        return {
            "symbol": stock_info.get("symbol"),
            "name": stock_info.get("name", ""),
            "price": float(today['close']),
            "stop_loss": round(float(stop_loss), 2),
            "target": round(float(ma_20), 2)
        }
    return None

# =========================================================
# 候選名單篩選 (繼承原版邏輯作為防線一)
# =========================================================
def select_candidates(stocks: list[dict]) -> list[dict]:
    # 直接使用你原本過濾流動性與熱度的優質邏輯
    candidates = []
    for stock in sorted(stocks, key=lambda x: num(x.get("amount_rank_pct")) or 0, reverse=True):
        if num(stock.get("price")) is None or num(stock.get("price")) <= 0: continue
        amt_rank = num(stock.get("amount_rank_pct"))
        if amt_rank is not None and amt_rank < 0.35: continue # 剔除流動性過低標的
        candidates.append(stock)
        if len(candidates) >= SCAN_MAX_SYMBOLS: break
    return candidates

# =========================================================
# Main
# =========================================================
def main() -> None:
    if not FUGLE_API_KEY:
        raise RuntimeError("Missing FUGLE_API_KEY")

    root = init_firebase()

    # 從 Firebase 取得最新的市場狀態與候選名單
    active = root.child('active_release').get()
    snapshot = root.child('releases').child(active) if active else root
    summary_raw = snapshot.child('summary').get() or {}

    if isinstance(summary_raw, list):
        stocks = [item for item in summary_raw if isinstance(item, dict)]
    elif isinstance(summary_raw, dict):
        stocks = [item for item in summary_raw.values() if isinstance(item, dict)]
    else:
        stocks = []

    if not stocks:
        raise RuntimeError("Firebase summary is empty")

    candidates = select_candidates(stocks)
    print(f"[scan] 啟動觸底反彈掃描，候選檔數: {len(candidates)}")

    buy_list = []
    
    # 逐檔掃描
    for index, stock in enumerate(candidates, start=1):
        symbol = str(stock.get("symbol") or "").strip()
        if not symbol: continue
        
        try:
            df = fetch_daily_kbars(symbol)
            if df is not None and not df.empty:
                result = check_easystock_rebound(df, stock)
                if result:
                    buy_list.append(result)
                    print(f"[hit] ★ {symbol} 符合觸底反彈確認條件！")
            
            # 簡單進度顯示
            if index % 10 == 0:
                print(f"[{index}/{len(candidates)}] 掃描中...")
                
        except Exception as exc:
            print(f"[warn] {symbol}: {type(exc).__name__}: {exc}")

    # 發送 Telegram 推播
    send_telegram_alert(buy_list)
    
    # 將結果存入 Firebase 以供網頁端或後續追蹤
    if buy_list:
        scan_date = datetime.now(TPE).strftime('%Y-%m-%d')
        root.child("rebound_picks").child(scan_date).set(buy_list)
        print(f"[done] 已將 {len(buy_list)} 檔標的寫入 /rebound_picks/{scan_date}")
    else:
        print("[done] 本日無標的符合條件。")

if __name__ == "__main__":
    main()
