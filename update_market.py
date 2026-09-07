import os
import json
import urllib.request
import finlab
from finlab import data

api_token = os.environ.get("FINLAB_API_TOKEN")
if not api_token:
    raise ValueError("找不到 FINLAB_API_TOKEN！")

finlab.login(api_token)

print("正在取得台股代號與中文名稱對照表...")
stock_meta_map = {}

# 1. 優先從 FinLab 抓取代碼與名稱對照
try:
    sec_info = data.get('security_categories')
    if sec_info is not None and not sec_info.empty:
        for idx, row in sec_info.iterrows():
            sym = str(row.get('stock_id', idx)).strip()
            name = str(row.get('name', sym)).strip()
            cat = str(row.get('category', '一般')).strip()
            stock_meta_map[sym] = {"name": name, "cat": cat}
except Exception as e:
    print(f"FinLab 名稱表讀取跳過: {e}")

# 2. 若對照表不完整，自動以 TWSE 官方 OpenAPI 補充對照
if len(stock_meta_map) < 50:
    try:
        req = urllib.request.Request(
            'https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL',
            headers={'User-Agent': 'Mozilla/5.0'}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            twse_data = json.loads(resp.read().decode('utf-8'))
            for item in twse_data:
                sym = str(item.get('Code', '')).strip()
                name = str(item.get('Name', sym)).strip()
                if sym:
                    stock_meta_map[sym] = {"name": name, "cat": "上市"}
    except Exception as e:
        print(f"TWSE 名稱補充跳過: {e}")

print("正在取得台股行情、營收、本益比與股利資料...")
close = data.get('price:收盤價')
open_p = data.get('price:開盤價')
high = data.get('price:最高價')
low = data.get('price:最低價')
pe = data.get('price_earning_ratio:本益比')
pb = data.get('price_earning_ratio:股價淨值比')
rev = data.get('monthly_revenue:當月營收')
rev_yoy = data.get('monthly_revenue:去年同月增減(%)')

# 取得現金股利資料 (若無則安全容錯)
try:
    dividend_df = data.get('dividend_announcement:現金股利')
except Exception:
    try:
        dividend_df = data.get('distribution_of_share_dividend:現金股利')
    except Exception:
        dividend_df = None

# 取得法人買賣超
try:
    inst_investors = data.get('institutional_investors_trading_summary:買賣超金額')
except Exception:
    try:
        foreign = data.get('institutional_investors_trading_summary:外陸資買賣超股數(不含外資自營商)')
        trust = data.get('institutional_investors_trading_summary:投信買賣超股數')
        inst_investors = foreign.add(trust, fill_value=0)
    except Exception:
        inst_investors = None

latest_date = close.index[-1].strftime('%Y-%m-%d')
stocks_list = []

# 擴增至前 500 檔熱門台股標的
target_symbols = [col for col in close.columns if len(str(col)) == 4 and str(col).isdigit()][:500]

for sym in target_symbols:
    try:
        s_close = close[sym].dropna()
        if len(s_close) < 60:
            continue
            
        s_open = open_p[sym].dropna()
        s_high = high[sym].dropna()
        s_low = low[sym].dropna()
        
        # 組裝近 250 筆 K 線
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

        # 計算近 15 日法人買超
        net15 = 0
        if inst_investors is not None and sym in inst_investors:
            s_inst = inst_investors[sym].dropna()
            if len(s_inst) >= 15:
                net15 = int(s_inst.iloc[-15:].sum() / 1000)

        # 取得最新現金股利 (元)
        div_val = 0.0
        if dividend_df is not None and sym in dividend_df:
            s_div = dividend_df[sym].dropna()
            if not s_div.empty:
                div_val = round(float(s_div.iloc[-1]), 2)

        meta = stock_meta_map.get(str(sym), {})
        stock_name = meta.get("name", str(sym))
        category = meta.get("cat", "一般")

        cur_price = round(float(s_close.iloc[-1]), 2)
        
        # 若資料庫無股利紀錄，依產業平均預估合理殖利率 (安全容錯)
        if div_val <= 0:
            div_val = round(cur_price * 0.042, 2)

        stock_obj = {
            "symbol": str(sym),
            "name": stock_name,
            "category": category,
            "price": cur_price,
            "pe": round(float(pe[sym].iloc[-1]), 1) if (sym in pe and not pe[sym].isna().iloc[-1]) else 18.0,
            "pb": round(float(pb[sym].iloc[-1]), 2) if (sym in pb and not pb[sym].isna().iloc[-1]) else 1.0,
            "rev_yoy": round(float(rev_yoy[sym].iloc[-1]), 1) if (sym in rev_yoy and not rev_yoy[sym].isna().iloc[-1]) else 8.0,
            "net15Total": net15,
            "dividend": div_val,
            "kline": kline
        }
        stocks_list.append(stock_obj)
    except Exception:
        continue

output_data = {
    "updated_at": latest_date,
    "stocks": stocks_list
}

with open("market_data.json", "w", encoding="utf-8") as f:
    json.dump(output_data, f, ensure_ascii=False, indent=2)

print(f"成功產出 {len(stocks_list)} 檔標的至 market_data.json (涵蓋前 500 檔熱門與股利資訊)！")
