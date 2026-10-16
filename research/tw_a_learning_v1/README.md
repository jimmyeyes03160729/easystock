# 跑道 A：台股學習適配，第 0 階段

本目錄落實台股專用資料合約與模型比較前的檢查，不是已完成的模型訓練器。
正式 A/B、風控、紅綠燈、模型門檻及 VM 都沒有接入或改動。

## 2026-10-16 唯讀資料稽核

已完成[候選樣本清單](audit_20261016/SAMPLE_INVENTORY.md)、
[成本差異表](audit_20261016/COST_COMPARISON.md)與
[缺少欄位表](audit_20261016/MISSING_FIELDS.md)。
整體仍為 [REQUIRES_RECONSTRUCTION_AND_PROVENANCE_AUDIT](audit_20261016/FINAL_READINESS.md)，
不是新增訓練、准許讀取近期／保留區資料或提升正式模型資格。

`audit_inventory.py` 只盤點截止日前標籤結構、日誌來源鍵、成本設定與有限schema樣本，
在開檔前拒絕越界日期與符號連結；SQLite只讀schema。
來源端經標準輸入執行，沒有部署檔案；沒有評估報酬或改寫來源。
[審閱後的中繼資料快照](audit_20261016/audit_evidence.json)與
[已執行的重現notebook](audit_20261016/AUDIT_REPRODUCTION.ipynb)可供檢查。
notebook只讀同目錄快照，不重新連來源、不讀行情或訓練。

## 已完成的入口

- `contract.py`：純函式，檢查台灣普通股、已知當沖資格、明確 UTC+8、
  A 原有進場時段、同時點加權／櫃買指數、明確成交量單位與買賣報價。
  產生所有表格候選共用的 12 個特徵，缺資料就拒絕，不以美股／陸股／ETF代理補值。
- `completed_candles`：只接受決策前完成且當時已可取得的一分鐘 K；
  保留台股每日 09:00～13:30 真實時間，拒絕缺洞、混股、未完成棒、
  零量補價和偽造的跨日連續分鐘。
- `preflight.py`：只讀明確指定的中繼資料 JSON，檢查研究範圍、
  標籤成本、資料來源、保留區隔離、模型權重授權與版本等聲明。
  不遍歷資料目錄、不開行情與標籤檔、不下載或載入模型、不呼叫券商。
- `readiness.manifest.json`：如實標記尚未驗證的項目，預期輸出 `BLOCKED_NOT_READY`。

上述檢查無法證明呼叫者填入的時間與市場分類是真的；仍須獨立來源稽核。
`METADATA_COMPLETE_NOT_AUTHORIZED` 也只是聲明欄位完整，不是訓練或存取許可。
目前沒有模型比較 adapter、訓練、推論、回測或漂移監控服務；不可宣稱已在學習。

## 固定比較方向

| 候選 | 台股適配方式 | 目前 |
|---|---|---|
| `logistic_tw` | 現有線性模型類型，使用與其他表格模型相同的台股事件／特徵 | 待 Stage 1 |
| `lightgbm_tw` | 只用核准的台股標籤訓練；與線性基準比較非線性資訊 | 待 Stage 1 |
| `tabpfn_v2_tw` | 台股標籤作上下文；外部預訓練只當先驗，不代表台股有效 | 權重授權／來源與版本尚未稽核 |
| `logistic_tw_plus_kronos_mini` | 凍結 K線模型；額外特徵與同一線性基準比較 | 預訓練時間重疊／權重／資源尚未稽核 |
| River／ADWIN | 只作研究告警，監測資料／成熟結果的誤差變化 | 未安裝、未接交易與紅綠燈 |

不混入美股／陸股的標籤，不用外國市場結果挑選台股模型。
預訓練模型可能包含全球資料；不能宣稱已去除其中美／陸資料，
也不能宣稱權重已學會台股。若其訓練時間與評估期不明，先阻擋比較。

## 為何尚未拿既有 1,200 筆訓練

既有研究費稅與 A paper 費稅是不同 profile：
`daytrade_learning/settings.json` 是保守研究費率 0.0015、賣出稅 0.003、
另加 10bps 滑價；`paper_execution.py` 的 A paper 手續費為 0.001425×0.28、
最低 20 元，符合資格之當沖稅率 0.0015，整元 ROUND_HALF_UP。
不能把既有結果直接混用，或把研究假設冒稱帳戶實際費率。

此外，本研究保守沿用 `<=2026-10-02` 的歷史邊界；10/12～10/16 的
1,200 筆不在允許範圍。Rebound、Phase2C、Runway 保留確認資料，包含
複製／改名／重建的資料，都不能拿來補樣本。今天已討論的交易也不是未見確認樣本。
本次沒有讀取任何歷史行情、標籤結果或保留區結果。

## 執行與驗證（不需要任何機器學習套件）

在 repo 根目錄執行：

```text
python -m unittest discover -s tests -p test_tw_a_learning_contract.py -v
python -m research.tw_a_learning_v1.preflight --manifest research/tw_a_learning_v1/readiness.manifest.json
```

第二個命令預期 exit code 2，表示缺少已驗證資料／凍結資料／權重證據，
不是程式壞掉。測試只使用手寫合成輸入，不匯入任何正式研究資料庫。

## 下一階段的完成條件

先完成註冊資料範圍、成本與標籤稽核、模型不可變版本與授權／預訓練來源稽核，
再提交完整 Stage 1 計畫：明確日期分區、結果成熟時間的 purge/embargo、
訓練參數、K線窗口／預測長度、所有候選計數、主要目標、敏感度檢查與判定門檻。
必須在實際訓練或查看結果前凍結與登錄曝光；第 0 階段文件不授權那次執行。
即使將來通過研究，也不自動調整 A 的既有 101 天升級條件或切換 model 模式。

相關定義：[第0階段合約](../../docs/research_governance/preregistrations/TW_A_LEARNING_V1_STAGE0.yaml)。
現有 `research/meta_b_filter_v1/` 已研究過 meta-labeling，本計畫不得把相同方向
包裝成全新假說，亦不得讀取其保留確認資料來挑模型。
