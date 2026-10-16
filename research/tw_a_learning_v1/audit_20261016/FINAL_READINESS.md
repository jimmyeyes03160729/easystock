# 台股學習資料稽核結論

資料盤點時間：2026-10-16T20:52:59.442136+08:00。歷史內容截止：2026-10-02。

**目前有6,224筆可追溯、可作重建候選的五特徵紀錄；尚無已完成全部台股12特徵與執行條件驗證的研究樣本。**後者是「尚未核准」，不是宣稱完全沒有可用資料。

- [可用樣本候選清單](SAMPLE_INVENTORY.md)
- [成本差異表](COST_COMPARISON.md)
- [缺少欄位表](MISSING_FIELDS.md)

## 已完成

日期／來源邊界、6,260筆標籤結構與重複鍵、六套profile、6,224筆原始日誌與分鐘檔案接回、報價時間檢查、指定raw檔案存在盤點、首末日期schema抽查、12份成本快照與兩個SQLite schema盤點。沒有評估勝率、獲利或新模型。

## 建議的執行順序

1. 在新資料表封裝可接回的quote_at、policy、明確市場／資格來源與不可變版本；保留舊資料原樣。
2. 先查證raw買賣量單位、逐筆時序與可成交量，再對本次已對上的3,393筆逐項確認能否重建。其餘2,831筆在指定擴充來源未找到檔案，其他來源仍為NOT_VERIFIED。
3. 尋找經核准、日期合規的盤中加權／櫃買資料；官方日收盤指數不能代替盤中路徑。
4. 完成新的事件／成本／標籤版本與明確時間切分計畫，凍結Stage 1後才訓練比較；先驗證線性基準及LightGBM，再處理外部權重。

## 狀態

`FINAL_READINESS=REQUIRES_RECONSTRUCTION_AND_PROVENANCE_AUDIT`

`TRAINING_EXECUTED=false`、`BACKTEST_EXECUTED=false`、`POST_CUTOFF_CONTENT_READ=false`、`HOLDOUT_CONTENT_READ=false`、`PRODUCTION_CHANGED=false`。

最近曾討論的1,200筆沒有在本次重讀或加入研究；6,224筆不是新增訓練成果。現有A/B、資料庫、模型、風控及VM檔案沒有被修改。本次只對允許歷史JSON解碼以統計結構與來源，沒有評估或輸出其中的結果數值。
