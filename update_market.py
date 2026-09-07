import os
import json
import finlab
from finlab import data

# 讀取 GitHub Secret 中的 FinLab 金鑰
api_token = os.environ.get("FINLAB_API_TOKEN")
if not api_token:
    raise ValueError("找不到 FINLAB_API_TOKEN！")

# 登入 FinLab
finlab.login(api_token)

print("正在取得台股日線與基本面資料...")
# 取得行情與基本面特徵
close = data.get('price:收盤價')
open_p = data.get('price:開盤價')
high = data.get('price:最高價')
low = data.get('price:最低價')
pe = data.get('price_earning_ratio:本益比')
pb = data.get('price_earning_ratio:股價淨值比')
rev = data.get('monthly_revenue:當月營收')
rev_yoy = data.get('monthly_revenue:去年同月增減(%)')

# 修正：取得三大法人資料 (加入安全容錯，若取不到自動以 0 代替)
try:
    inst_investors = data.get('institutional_investors_trading_summary:買賣超金額')
except Exception:
    try:
        foreign = data.get('institutional_investors_trading_summary:外陸資買賣超股數(不含外資自營商)')
        trust = data.get('institutional_investors_trading_summary:投信買賣超股數')
        inst_investors = foreign.add(trust, fill_value=0)
    except Exception:
        inst_investors = None

# 取得最新交易日
latest_date = close.index[-1].strftime('%Y-%m-%d')
stocks_list = []

# 選取有效個股代碼 (過濾指數與存託憑證等非股票代碼)
target_symbols = [col for col in close.columns if len(str(col)) == 4 and str(col).isdigit()][:120]

for sym in target_symbols:
    try:
        s_close = close[sym].dropna()
        if len(s_close) < 20:
            continue
            
        s_open = open_p[sym].dropna()
        s_high = high[sym].dropna()
        s_low = low[sym].dropna()
        
        # 組裝近一年 (約 250 筆) K 線序列
        kline = []
        recent_dates = s_close.index[-250:]
        for d in recent_dates:
            d_str = d.strftime('%Y-%m-%d')
            if d in s_open.index and d in s_high.index and d in s_low.index:
                kline.append({
                    "time": d_str,
                    "open": round(float(s_open[d]), 2),
                    "high": round(float(s_high[d]), 2),
                    "low": round(float(s_low[d]), 2),
                    "close": round(float(s_close[d]), 2)
                })

        # 計算近 15 日法人買賣超 (張數或金額)
        net15 = 0
        if inst_investors is not None and sym in inst_investors:
            s_inst = inst_investors[sym].dropna()
            if len(s_inst) >= 15:
                # 轉成張數或百萬級距單位
                net15 = int(s_inst.iloc[-15:].sum() / 1000)

        stock_obj = {
            "symbol": str(sym),
            "name": str(sym),
            "category": "一般",
            "price": round(float(s_close.iloc[-1]), 2),
            "pe": round(float(pe[sym].iloc[-1]), 1) if (sym in pe and not pe[sym].isna().iloc[-1]) else 18.0,
            "pb": round(float(pb[sym].iloc[-1]), 2) if (sym in pb and not pb[sym].isna().iloc[-1]) else 1.0,
            "rev_yoy": round(float(rev_yoy[sym].iloc[-1]), 1) if (sym in rev_yoy and not rev_yoy[sym].isna().iloc[-1]) else 8.0,
            "net15Total": net15,
            "kline": kline
        }
        stocks_list.append(stock_obj)
    except Exception as e:
        continue

output_data = {
    "updated_at": latest_date,
    "stocks": stocks_list
}

with open("market_data.json", "w", encoding="utf-8") as f:
    json.dump(output_data, f, ensure_ascii=False, indent=2)

print(f"成功產出 {len(stocks_list)} 檔標的至 market_data.json (基準日: {latest_date})！")
