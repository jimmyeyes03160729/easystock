# EasyStock Daytrade Knowledge V1 工程規格

本包完成所提供教材與Gemini主要規則/案例的交叉核對，供研究工程交接。三本原檔均取得並記SHA-256；兩PDF各228頁，EPUB 48個XHTML項目。所有未獲直接支持的主張留UNVERIFIABLE，所有AI門檻與效果主張分開。並未宣稱全書每行已核驗，或任何策略已有可交易效果。本次沒有修改EasyStock repo或實作策略；未讀repo，不臆造工程路徑。

## 檔案契約

七份主檔：source_verified_rules.yaml、ai_quantization_candidates.yaml、feature_candidates.yaml、risk_candidates.yaml、case_library_verified.yaml、research_parameter_grids.yaml、implementation_spec.md。另有OpenCode_final_prompt.md、source_manifest.yaml、source_issues.yaml、claim_audit.yaml、README.md、validation_summary.json與checksums.sha256。Gemini原檔附供對照；不將教材原檔或全文另行打包。

source_verified_rules保存35條具語境的原子主張；原草稿12條規則保留在ai_quantization_candidates，不能因部份核心概念支持而整段升級。18個Gemini原案例隔離；case_library_verified另建立VC案例。參數grid沒有production預設。

## 狀態與證據不可混合

status 是該項研究內容的性質；book_source_status / parent_source_status 是教材支持情況。AI_QUANTIZED 並不代表母概念已經教材證實。SOURCE_MISMATCH 需讀 mismatch_scope：報告內衝突是直接確認的草稿問題；BOOK_DIRECT 是本次直接教材核對；先前助理審查不是單獨證據。AI_INFERENCE=false 沒有任何升級權限。每個混合規則必須拆成作者原話、適用語境、量化公式、閾值、效果主張及資料需求，分別判定。

原書支持不等於回測有效；有效不等於可交易；案例不等於統計樣本。作者例子、特定價格級距與練習本金都不能變成正式風控預設。來源不全時缺值用 null，不補寫頁碼、原文、股票日期或交易價格。

## 已確認的來源差異與保留問題

本次兩PDF均228頁。先前助理「Smart僅到p152」是先前摘要的範圍判斷，不能沿用為這次附件完整度。B2 p156/170/186/192本次可直接檢查，實際是指標設定、創意、嘉聯益及自營比介紹。TPK-KY案例實際在p214–220，原書自營比25%，不是Gemini14%；出場情境10:10–10:15，不是09:12。每日09:15必須平倉並非這個作者通用規則。

B1 R_003 均價線章節實際3-1 p54–57；R_011部位管理實際4-2/4-3 p86–97。R_001概念在2-1 p32–37，R_002在2-2 p38–39。以每頁可見印刷頁標號定位，不把OCR頁尾排序或統一偏移當唯一證據。B2的出版品開頭未見完整封面/目錄；228頁不等於完整出版品。

B2 R_006樓層式當沖實際是詹大第2章：檢視開收高低及近幾個月重複價位；Gemini零克連歸屬、p130–147引用與5–20日窗口不受支持。

B3 A-29威剛、A-30華擎、A-31立積、A-32寶齡富錦/熱映、A-33昇揚半導體；A-39虧損範圍、A-45獲利金額、A-41是節奏示例，不能假造國巨案例；無A-27.xhtml。R_010漲停回跌2%與該引用不符，仍作獨立假說，不能寫原書規則。

自營比的原書分子/分母是股數，Gemini金額比為SOURCE_MISMATCH。委買/委賣成交口數差含委託與成交差額，不是主動買賣成交差。原書spread以委買價為分母；保留另命名的mid版研究不得混門檻。B2印刷p152圖7有BBandMA30；它是圖示參數，不能宣稱作者明訂通用30，也不能宣稱原書完全沒有中軌參數。

作者半倉/三筆與五筆/3比2/大盤佳可滿倉是不同語境；不得整合成全帳戶硬50%。B3「5分鐘注意分歧」不等於進場後180秒强制平倉。50元整的文字重疊仍UNVERIFIABLE。VWAP畫線與交易所/供應商平均價之具體計算包含哪些session或成交仍須工程資料定義；不能靠名詞等同。

UNVERIFIABLE不等於不存在；OCR無匹配不能作全書否定證據。沒有定位的前高天數、0.2/0.3%、OBI、3倍牆、100ms、相關0.65、50萬元大單等按AI設計保留。未證實效果一律RESEARCH_HYPOTHESIS。來源不支持的複合規則只可按獨立AI設計研究，作者標籤撤回。

## 未來 repo 對照工作（唯讀）

先閱讀 repo 的 AGENTS.md、研究資料入口、feature registry、時間/資產/價格單位、測試慣例、研究輸出位置與production邊界。列出現有feature到本包feature的映射、名稱衝突、公式差異和缺失資料。未檢查repo前不可寫「已對應現有架構」，也不可臆造路徑。輸出 repository_mapping.md、data_capability_matrix.yaml、research_plan.md 與未解決問題。這些未來檔案本次不生成虛假內容。

## 資料與因果時點契約

所有資料記 event_time、receive_time、publication_time（若有）、sequence、source、asset_id、session_id、timezone、unit、quality_flags。decision_time 只能看 availability_time <= decision_time 的版本。日線特徵在當日使用昨日完成數據；不得用未來修訂的除權價格、族群分類、上市名單或當日最終量。公告可用時間需從資料元信息取得，不硬編「每日17:30」。跨市場使用as-of join並設定最大陳舊度；禁止往未來找最近quote。

K棒只在收完後提供完整OHLC；未收完棒须用另一個前綴明確表示。早盤RVOL依相同已經過時段匹配歷史量。轉折點使用過去資料确认，feature記 confirm_time，不回填pivot_time當進場時間；不可用事後ZigZag。leader選取、相關係數、regime分類與族群熱度都只能使用決策當下可得資料。

只有五檔快照時不能確證cancel、order identity、queue position或spoofing意圖。100ms快照不足以知道兩快照間事件順序。牆消失只作代理；完整撤單事件仍不能直接证明欺騙意圖。缺L2時相關研究標unsupported，不以K線偽造盤口。內外盤需区分provider原始标记与quote-rule推断，未知成交保留unknown并報分類覆蓋率。

股數/張數/口數與金額不得混用。歷史tick size、limit price、交易session、費用、稅率、合約乘數、交易資格和借券條件都需按資產與生效日載入官方規則或供應商合約。本包沒有驗證最新市場制度，也不內建其數值。

## 未來研究設計（此交接階段不執行）

先做資料可得性及來源審計，再預註冊小規模事件研究。進場事件、可用價格、horizon、停損/停利、失效時鐘起點與EOD界線需要逐個固定。五個H只是假說，並非已批准實作清單；沒有來源不妨提出獨立AI假說，但要明確標記、取得後續實作授權。

前向收益可取1/3/5/10/15/30/60分鐘與EOD，按單一假說選定而非每次挑最有利horizon。long的signed return=P_h/P_entry-1，short為其負值。MFE=max(0,max signed_return_path)，MAE=max(0,-min signed_return_path)；均為非負幅度。必須標明採trade、mid還是可成交bid/ask；研究事件標記價不等於真實填單價。完整標的樣本含下市和失敗事件，案例不能當訓練母體。

先按日期切train/validation/frozen holdout，再對重疊標籤採purge/embargo；相同交易日/族群事件不能當獨立樣本。回報事件數、股票數、交易日、成本前後收益分布、尾損、MFE/MAE、成交率及缺資料比例；信賴區間以交易日等適當群組重抽樣並處理多重比較。記下全部嘗試的grid，不能用最終holdout調參。牛熊/震盪及ATR分位須由訓練期或截至t的資料定義。

成本情境包含手續費、稅、滑價、延遲及借券/回補成本（若适用），用版本化輸入，不填猜測數字。觸及價格不代表可成交，限價封鎖、部分成交、拒單、quote過期、停牌和強制平倉不可直接視為成功。執行模擬與純事件收益分別報告。

## 未來實作驗收要求

本次不寫程式或tests。交給OpenCode後若使用者明確要求工程化，必要檢查為：未來資料擾動不改過去feature；改quote/trade時序能揭露延遲；零分母、50元/100元tick邊界、跨session、停牌與除權處理正確；缺L2不產確定cancel；60% buy-share正確映射signed delta；時鐘從指定事件起算；paper與production隔離。實作不得修改正式baseline、模型gate、下單權限或帳戶參數。

## 發布驗收

本次V1要求教材證據、原子分類、案例重建、引用一致性與coverage；未解條目保持隔離；所有YAML可解析、ID唯一、引用可解析。未解決條目可留 UNVERIFIABLE，但不得放入已驗證清單或掩飾缺件。只有後續研究及paper結果經獨立審核才可討論promotion；本包始終不授權production或實單。
