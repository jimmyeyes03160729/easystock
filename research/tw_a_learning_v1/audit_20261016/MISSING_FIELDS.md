# 缺少欄位與可修復性

資料盤點時間：2026-10-16T20:52:59.442136+08:00。歷史內容截止：2026-10-02。

**缺在標籤表，不等於整個系統沒有資料。**下表分開記錄直接欄位、已驗證可接回項目與尚未驗證項目。

| 所需資訊 | 標籤／現有證據 | 能否接回 | 嚴重度／狀態 |
| --- | --- | --- | --- |
| 歷史市場別、普通股身分、當沖資格及known-at | 標籤未直接封裝；只通過代碼格式篩選 | 官方日資料庫有exchange欄位，但本次僅讀schema | HIGH／REQUIRES_JOIN；逐日資格及來源時刻NOT_VERIFIED |
| quote_at與原始policy | 標籤沒有；6,224筆均能接回日誌 | 接回報價皆不晚於觀察且<=30秒 | RECOVERABLE；仍需封裝不可變來源證據 |
| 五特徵schema與features_as_of | 6,224筆有限五數值；未存獨立features_as_of | 目前FEATURES定義可查，但歷史程式完整性待核 | HIGH／NOT_VERIFIED；報價新鮮不等於所有特徵因果 |
| 盤中加權／櫃買60秒、5分鐘與當時高點 | 標籤未直接封裝 | 官方indices表僅day/name/close，不是盤中路徑 | HIGH／NOT_VERIFIED；不得用當日收盤回填盤中資訊 |
| 成交量／買賣量明確單位 | 標籤未封裝累計量及單位 | 抽查raw有volume、bid_volume、ask_volume | HIGH／UNIT_UNVERIFIED；不能按數字大小猜股或張 |
| 最佳報價與可成交量 | 標籤無；3,393筆有指定raw檔案可追查 | 4個raw schema樣本均有bid/ask價格與量 | HIGH／PARTIAL；不能推定44,673檔全有完整深度 |
| 五檔完整價格與深度 | 標籤及4個raw schema樣本沒有多檔陣列 | 最佳一檔不等於完整五檔 | NOT_VERIFIED；若凍結A門檻依賴多檔，須補來源 |
| Kronos使用的成交金額Amount | 學習分鐘包的2個schema樣本沒有amount；producer也只封裝OHLCV | 4個raw樣本的kbars有Amount | REQUIRES_JOIN；各普通股／日期覆蓋未全驗證 |
| 每根K棒start/end/available_at與來源延遲 | 學習分鐘包只有at；downloaded_at是下載時間 | producer把SDK分鐘結束轉為分鐘起點 | HIGH／REQUIRES_RECONSTRUCTION；不能將下載時間冒充歷史可用時間 |
| label_available_at | 6,260筆均未直接封裝 | 6,224筆exit_at順序正常，但exit_at不是標籤生成時間 | HIGH／MISSING；依生成紀錄或事前固定保守規則處理成熟時間 |
| 每筆完整成本／股數／費稅版本 | 有cost_twd；無逐項費稅／股數欄位 | 12份報告保存相同研究假設，與A paper不同 | HIGH／PROFILE_MISMATCH；獨立新版本重建 |
| 不可變程式版本與原始檔hash | 標籤未封裝；日誌policy有source_version欄位 | 是否足以唯一對應歷史Git版本尚未核 | HIGH／NOT_VERIFIED；當前來源hash不代表歷史生成版本 |
| 歷史股票池與雷達完整排行 | 標籤有radar_selected布林；非完整候選排名與可投資性快照 | 登錄的擴充100股池非PIT股票池 | HIGH／UNIVERSE_BIAS；限縮可宣稱範圍 |

## 證據與限制

- 全量標籤欄位存在數：`audit_evidence.json.labels.fields_present`；日誌接回：同檔 `labels.files[].journal_join`。
- 日誌保存範圍：`daytrade_learning/runtime.py:82`。
- 當前五特徵：`daytrade_learning/features.py:5`；分鐘正規化：`daytrade_learning/research.py:163`。
- 官方日資料schema：`rebound_learning/market_daily.py:68`；實際SQLite只查sqlite_master與PRAGMA，未讀任何日行情值。
- raw必要欄位：`history/collector_core.py:22`；本次抽查實際額外含bid_volume/ask_volume。必要欄位列表不保證額外欄位全量存在。
- 只有483筆帶有research_features欄位；本次未檢視其內容或定義，不能把欄位名稱當作已具備台股市場特徵的證據。
- 日誌接回檢查確認存在相同鍵的來源；尚未檢查同鍵多筆日誌的policy值一致性，不能把接回成功冒稱完整來源認證。
