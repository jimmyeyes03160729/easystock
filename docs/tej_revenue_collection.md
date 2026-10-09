# TEJ 營收與公告日期收集

TEJ 原先僅在 VM `/home/ubuntu/easystock-research/tej` 使用，未納入主網站排程。
2026-10-09 實測金鑰可連線，`TRAIL/TASALE` 查台積電 2026-09 返回 0 筆；
`TWN/APISALE` 無權限。已下載的 2025 全市場營收檔可匯入私人 SQLite。
這是資料可用期間限制，不代表已驗證可取得最新營收。

現在每日台灣時間 09:20、21:10 收集前兩個營收月份，寫入
`easystock-market-events/tej-revenue.sqlite` 和 `tej-revenue-status.json`。
金鑰仍在 VM 私人檔，沒有提交或公開。沿用既有 TEJ 專用虛擬環境。
狀態區分成功、無近期資料、額度／分頁不完整、失敗；保留每月抓取筆數。
每次呼叫預留 5,000 筆額度，只接受完整的單頁結果；完整月資料超過單頁時
拒絕匯入並標註 incomplete_page，不把截斷資料視為完整。

已驗證 TASALE 欄位：annd_s 為營收發布日，d0001 為千元營收，
d0003/d0004 為年增／月增；完整 t8100m/mfr2/mfr3 優先採以合併為主的三欄。
不混用不同口徑的金額和成長率。無公告日期、非有限數字、未來公告排除。
保留來源、資料表、營收月份、公告日與實際收集時間。

營收正向消息觀察器只讀私人快取，可採較官方來源更新的月份；同月官方優先。
超過兩個月、未來收集／公告資料不進觀察。仍要求年增、月增均 > 0，
且 MOPS 公告有獨立正向證據；TEJ 公告日期不冒充公告全文。
觀察從實際收集之後的下一交易日開始，不回填歷史模擬訊號。
歷史檔的 observed_at 是匯入時間，不是歷史當時可用性的證明。

部署：安裝 deploy/easystock-tej-revenue.service/timer 並啟用 timer；
初次可用 `python -m market_events.tej_revenue --import-cache
/home/ubuntu/easystock-research/tej/data/tasale_2025.csv.gz` 匯入既有檔。
改用付費表前，必須驗證授權和欄位對應；目前不自動升級、不購買服務。
