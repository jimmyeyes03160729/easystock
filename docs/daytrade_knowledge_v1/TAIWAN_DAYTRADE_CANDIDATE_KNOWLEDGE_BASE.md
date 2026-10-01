作為「台股當沖量化研究員」，本研究已全面下載並完整解析三本指定教材（《100張圖學會K線當沖》、《人人都能學會股票當沖全圖解》、《【圖解】最高勝率手機當沖》），並將書中所有盤前選股、盤中型態、籌碼避險、五檔委託、成交明細流（Orderflow）及風險管理規則，系統化轉譯為可回測、可特徵化、可交由演算法驗證的**台股當沖候選知識庫**。

---

# 01_BOOK_SUMMARY

### 書籍一：《100張圖學會K線當沖》
* **作者**：台股大學堂 會長（Johnny）
* **核心哲學**：型態為王、價量為真、防守至上。不預設立場，強調「追高不是錯，追錯不砍才是錯」，將極短線當沖視為反射動作與大腦肌肉記憶。
* **交易風格與工具**：現股當沖（先買後賣為主，極少做空），部位快速移動（30萬資金移動式操作，日交易量約1,000萬～1,500萬），單日出手10～15檔，持倉時間由數分鐘至數十分鐘。
* **核心技術模型**：
  * 日K型態：「多方標準型態」（5MA/10MA/20MA多頭排列 + 60MA翻揚 + 站上5MA + 距前高收盤價10%以內）、「多方連續型態」（昨日剛創高、今日跳空開高）、「多方複合型態」。
  * 盤中即時防守：均價線（VWAP）為第一防線、開盤價為第二防線、左邊K棒高/收為第三防線、前一轉折低為第四防線。
  * 部位控制：試單先行、做對加碼（最多分3筆加碼至半倉，絕不向下攤平），同一時間最多只盯2檔標的（1檔昨日留單、1檔今日新單）。
* **量化研究員視角評估**：
  * **優點**：價格與均線結構定義明確，對日內均價線（VWAP）與關鍵K棒高低點的防守邏輯具高度可量化性。
  * **量化盲點與偏誤**：作者主觀偏向做多（認為做空風險無限且緩漲急跌難掌握），忽略空方當沖空間；「氣勢強」、「大人物進場」等敘述具主觀模糊性，且其日K型態選股存在強烈的**倖存者偏誤（Survivorship Bias）**與**後見之明（Hindsight Bias）**。

---

### 書籍二：《人人都能學會股票當沖全圖解》
* **作者**：《Smart智富》真・投資研究室（彙整詹大、零克連、林昇、權證小哥等四大達人技法）
* **核心哲學**：工欲善其事必先利其器。從交易工具（現股、股票期貨、台指期）的成本結構（手續費、證交稅跳檔損益兩平點）、盤前籌碼大數據（法人未平倉、權證自營商避險）到盤中分秒必爭的下單介面與指標連動。
* **交易風格與工具**：
  1. **詹大（樓層式當沖法）**：現股當沖，以近期日K「高頻重複價位」劃分3～5個關鍵價位帶（樓層），站上地板做多、跌破天花板放空，持倉偏日內波（數十分鐘至數小時）。
  2. **零克連（台指期當沖術）**：台指期當沖，前日法人期現貨籌碼定多空，盤中以摩台期/電子期/金融期強弱度 + 前20大權值股紅K比例 + 5分K KD黃金交叉/死亡交叉 + MACD柱狀體轉折進出。
  3. **林昇（線條式當沖法）**：股票期貨當沖（以成交口數>500口為池），利用美股道瓊與台指期前3日K線定開盤預期，盤中只交易08:45～09:45（黃金1小時）；利用台指期「委買賣成交口數差」與「1分K布林通道（1倍標準差）」定大盤，再以「個股走勢強於大盤」與「內外盤成交線」選股進場。
  4. **權證小哥（籌碼當沖法）**：股票期貨當沖，盤前篩選「自營比絕對值 > 10%」且期貨量 > 100口；盤中利用權證隔日沖主力退場引發的自營商現貨Delta避險反向拋售/回補機制（09:00～09:15），配合現貨漲跌幅<2%、正逆價差<1%、期貨買賣價差比<0.6%進場放空或做多，急跌/急漲爆量力竭時平倉。
* **量化研究員視角評估**：
  * **優點**：四大流派中權證小哥與林昇的方法量化維度最高，具有明確的衍生品造市避險微觀結構（Market Microstructure）與盤口口數差門檻，成本敏感度極高。
  * **量化盲點與偏誤**：詹大的「重複價位」缺乏精確的統計核密度（KDE）或成交量分布（Volume Profile）定義；台指期與股期的大戶軟體指標（如口數差線）常包含委託單，容易受「虛晃抽單（Spoofing）」欺騙。

---

### 書籍三：《【圖解】最高勝率手機當沖》
* **作者**：Jasper
* **核心哲學**：不看落後指標（包含5分K棒都不看），回歸價格漲跌的最根本訊號——「成交明細（逐筆成交）」與「五檔掛單（L2 Orderbook）」。強調做順勢、拉回進場、嚴格停損。
* **交易風格與工具**：手機現股當沖（追求極致簡化，09:00～09:30早盤為主），單筆操作時間極短（30秒至30分鐘），極度講求手續費日退、ROD市價停損。
* **核心技術模型**：
  * 選股清單：三大排行（昨日漲幅、跌幅、週轉排行），股價<300元，50元以下成交量>2萬張，50元以上成交量>1萬張。
  * 進場三大支柱：
    1. **加權指數連動**：大盤急拉或回檔力道衰竭點進場。
    2. **同族群類股連動**：領頭羊帶量發動，5分鐘內跟進同族群連動股；若5分鐘內無連動則視為分歧放棄。
    3. **拉回進場**：強勢股拉回不破前低且五檔委買掛單增多進場；弱勢股反彈不破前高且委賣掛單增多進場。
  * 風險鐵律：每日最大虧損金額限制為單月當沖本金之 1/10（如本金2萬，日虧損達2,000元立即關機停止交易）。
* **量化研究員視角評估**：
  * **優點**：對台股逐筆撮合（Continuous Trading）下的委託簿微觀結構（Order Book Dynamics）、抽單現象、大單造勢與真假防守有敏銳的實戰描繪。
  * **量化盲點與偏誤**：作者強調「只用手機看盤、不看K線」，許多決策高度仰賴個人主觀「盤感」（例如「外盤成交不連貫」、「感覺主力只想防守不想拉抬」），需要嚴謹轉譯為數學特徵方能回測。

---

# 02_RULE_CANDIDATES

### RULE_ID: R_001
* **TITLE**: 多方標準型態日K突破前高進場假說
* **SOURCE_BOOK**: 《100張圖學會K線當沖》
* **SOURCE_CHAPTER**: Part-2 2-1「多方標準型態」
* **SOURCE_PAGE**: p.36 - p.40
* **DIRECTION**: LONG
* **CATEGORY**: STOCK_SELECTION
* **AUTHOR_CLAIM**: 當股票短中長線皆站在多方，5MA翻揚且站上，距離左邊波段高點收盤價在10%漲幅以內時，隔日極易開盤帶量突破，形成帶有氣勢的多方噴出。
* **ORIGINAL_CONTEXT**: 盤後選股建立次日當沖口袋名單（自選池）。
* **MARKET_CONDITION**: 大盤日線未走空，市場有多頭主流。
* **TIME_CONDITION**: 盤後選股（EOD），次日開盤追蹤。
* **PRICE_CONDITION**: 收盤價 $Close_0 > MA5_0$；短天期均線呈現多頭排列（$MA5_0 > MA10_0 > MA20_0$）；長天期季線 $MA60_0$ 翻揚（$MA60_0 > MA60_{-1}$）；長天期均線不可在5MA之上（無蓋頭反壓）；左方存在波段高點 $X$，且當前收盤價與 $X$ 的收盤價價差在10%以內：
  $$0 \le \frac{Close_X - Close_0}{Close_0} \le 0.10$$
* **VOLUME_CONDITION**: 作者在此處未對成交量給出絕對數值，僅要求不可為冷門無量股。
* **CANDLE_CONDITION**: 當日收盤為實體紅K棒（收在相對高點）。
* **ORDERFLOW_CONDITION**: 無（盤後日線層級）。
* **INDEX_CONDITION**: 無特定指標限制，但大盤不宜為重挫空頭格局。
* **SECTOR_CONDITION**: 屬於盤面強勢或具題材族群。
* **ENTRY_TRIGGER**: 次日開盤若帶跳空開高（$Open_1 > Close_0$），且盤中放量突破左方高點 $Close_X$ 時進場。
* **EXIT_TRIGGER**: 盤中漲停鎖死獲利全出，或收盤前未達預期平倉。
* **STOP_LOSS**: 盤中跌破當日開盤價，或跌破日內均價線（VWAP），或跌破 $Close_X$。
* **TAKE_PROFIT**: 漲停板鎖死前全數獲利了結，或獲利達標（3%～5%）。
* **INVALIDATION**: 開盤跌破前日收盤價，或跌破5MA。
* **REQUIRED_DATA**: 每日日線OHLCV、歷史還原除權息價格、5MA/10MA/20MA/60MA。
* **POSSIBLE_FEATURES**: `dist_to_prev_high_10d_pct`, `ma5_slope_5d`, `ma_alignment_score`, `gap_open_pct`
* **QUANTIFIABLE**: YES
* **BACKTESTABLE**: YES
* **AI_INFERENCE**: true
* **AI_INFERENCE_DETAIL**: 作者書中僅以示意圖表示「K棒A與K棒X收盤價差在10%漲幅內」及「季線翻揚」，量化上需嚴格定義為過去 $N$ 天（建議 $N=20$ 至 $60$）的局部收盤價最大值 $Close_X$，且限制均線斜率 $MA60_t - MA60_{t-5} > 0$。
* **AMBIGUITY**: 均線「走得扭捏糾結」與「翻揚角度」在作者文字中屬質化描繪，需以回歸斜率量化。
* **LOOKAHEAD_BIAS_RISK**: LOW（使用前一日確定收盤價）。
* **SURVIVORSHIP_BIAS_RISK**: HIGH（書中範例皆為成功飆漲案例，如台表科、矽力-KY，忽略大量接近前高後反轉下殺之失敗個股）。
* **IMPLEMENTATION_RISK**: 隔日開盤跳空若過大（如開在+6%以上），追高進場極易遭遇早盤當沖獲利回吐賣壓。
* **NEEDS_TRANSACTION_COST**: YES
* **NEEDS_SLIPPAGE**: YES
* **RESEARCH_PRIORITY**: HIGH

---

### RULE_ID: R_002
* **TITLE**: 多方連續型態跳空開高續創高進場假說
* **SOURCE_BOOK**: 《100張圖學會K線當沖》
* **SOURCE_CHAPTER**: Part-2 2-2「多方連續型態」
* **SOURCE_PAGE**: p.42 - p.46
* **DIRECTION**: LONG
* **CATEGORY**: ENTRY
* **AUTHOR_CLAIM**: 昨日剛創歷史或波段新高的強勢股，今日若帶跳空開高，代表買盤氣勢強烈；即使是追高買進，只要跌破前日收盤價立即停損，便能持續參與強者恆強的噴出行情。
* **ORIGINAL_CONTEXT**: 追逐市場妖股、題材龍頭股或連拉漲停之標的。
* **MARKET_CONDITION**: 市場處於主升段或高風險偏好格局。
* **TIME_CONDITION**: 09:00～09:15 早盤黃金衝刺期。
* **PRICE_CONDITION**: 昨日最高價為過去歷史或波段高點（$High_0 \ge \max(High_{-20:0})$）；今日開盤跳空開高（$Open_1 > High_0$ 或 $Open_1 > Close_0 \times 1.01$）。
* **VOLUME_CONDITION**: 開盤第一根量（1分K或5分K）大於前五日開盤均量。
* **CANDLE_CONDITION**: 開盤後第一根K棒收紅且不破開盤價。
* **ORDERFLOW_CONDITION**: 書中未特別強調，僅稱「買盤積極」。
* **INDEX_CONDITION**: 大盤早盤亦為紅盤或未重挫。
* **SECTOR_CONDITION**: 同族群股票同步開高。
* **ENTRY_TRIGGER**: 今日價格突破開盤第一根高點，或盤中創當日新高時市價追價進場。
* **EXIT_TRIGGER**: 尾盤 13:00～13:20 平倉，或盤中觸及漲停板部分/全數平倉。
* **STOP_LOSS**: 絕對防守點為前一日收盤價 $Close_0$（或今日開盤價 $Open_1$）。
* **TAKE_PROFIT**: 漲停板前一檔全出，或獲利達3%以上分批獲利。
* **INVALIDATION**: 開盤跌破昨日收盤價（翻黑）。
* **REQUIRED_DATA**: 逐筆 Tick、1分K、日K歷史數據。
* **POSSIBLE_FEATURES**: `is_prev_day_high_break`, `gap_up_ratio`, `vol_ratio_open_5d`, `intraday_high_break_flag`
* **QUANTIFIABLE**: YES
* **BACKTESTABLE**: YES
* **AI_INFERENCE**: true
* **AI_INFERENCE_DETAIL**: 作者定義「剛創高」未給出天數窗口，量化需設定過去 60 日或 250 日滾動高點。防守停損若設在「前日收盤價」，若跳空幅度達 4%，單筆停損過大，量化應加入以日內 VWAP 或今日開盤價作為動態停損點。
* **AMBIGUITY**: 「買盤氣勢強」未量化。
* **LOOKAHEAD_BIAS_RISK**: LOW
* **SURVIVORSHIP_BIAS_RISK**: HIGH
* **IMPLEMENTATION_RISK**: 開高走低「開盤即最高」之出貨黑K（假突破）極易引發連續滑價停損。
* **NEEDS_TRANSACTION_COST**: YES
* **NEEDS_SLIPPAGE**: YES
* **RESEARCH_PRIORITY**: MEDIUM

---

### RULE_ID: R_003
* **TITLE**: 盤中均價線（VWAP）回測不破加碼與跌破停損假說
* **SOURCE_BOOK**: 《100張圖學會K線當沖》
* **SOURCE_CHAPTER**: Part-2 2-6「均價線是當沖最重要的一條生命線」
* **SOURCE_PAGE**: p.62 - p.67
* **DIRECTION**: BOTH（多方加碼與多單停損）
* **CATEGORY**: ENTRY / EXIT
* **AUTHOR_CLAIM**: 均價線（成交金額 / 成交股數）是當日市場所有進場者的平均持股成本。股價在均價線上代表多方控盤，任何回測接近均價線且量縮不破皆是做多/加碼點；一旦帶量跌破均價線，代表多方全軍覆沒，多單必須無條件停損。
* **ORIGINAL_CONTEXT**: 盤中即時部位監控與加碼退場準則。
* **MARKET_CONDITION**: 任何盤態。
* **TIME_CONDITION**: 09:15～11:30。
* **PRICE_CONDITION**: 價格大於當前累積 VWAP（$Price_t > VWAP_t$）。
* **VOLUME_CONDITION**: 回測 VWAP 時成交量萎縮，隨後再度出量。
* **CANDLE_CONDITION**: 1分K或5分K下影線觸及或接近 VWAP 後收長紅。
* **ORDERFLOW_CONDITION**: 委買在 VWAP 處出現大單支撐。
* **INDEX_CONDITION**: 無。
* **SECTOR_CONDITION**: 無。
* **ENTRY_TRIGGER**: 價格拉回至距離 VWAP 0.3% 以內未破，隨後出現外盤主動買單（Aggressive Buy）拉開價差時進場/加碼。
* **EXIT_TRIGGER**: 盤中價格跌破 $VWAP_t$ 超過 1～2 個檔位（Tick）。
* **STOP_LOSS**: $Price_t < VWAP_t \times (1 - \delta)$（作者定義為直接跌破 VWAP 即砍）。
* **TAKE_PROFIT**: 創高後爆量停利，或尾盤前平倉。
* **INVALIDATION**: 股價開盤後始終在 VWAP 之下。
* **REQUIRED_DATA**: 盤中逐筆成交價格與成交量（計算即時滾動 Cumulative Volume-Weighted Average Price）。
* **POSSIBLE_FEATURES**: `dist_to_vwap_pct`, `vwap_touch_count`, `pullback_vol_decay_ratio`, `break_below_vwap_flag`
* **QUANTIFIABLE**: YES
* **BACKTESTABLE**: YES
* **AI_INFERENCE**: false（作者書中明確指出均價線為當沖第一道防線，跌破即砍）。
* **AMBIGUITY**: 「接近均價線」的量化距離容忍度（Tolerance Band）未明確說明。
* **LOOKAHEAD_BIAS_RISK**: NONE（VWAP 計算僅使用 $0$ 到 $t$ 的歷史成交累積）。
* **SURVIVORSHIP_BIAS_RISK**: LOW
* **IMPLEMENTATION_RISK**: 在無趨勢的日內震盪盤（Choppy Market），價格會反覆上下穿越 VWAP，造成大量「洗盤連續停損」（Whipsaw）。
* **NEEDS_TRANSACTION_COST**: YES
* **NEEDS_SLIPPAGE**: YES
* **RESEARCH_PRIORITY**: HIGH

---

### RULE_ID: R_004
* **TITLE**: 權證自營商避險隔日沖賣壓放空假說（小哥自營比策略）
* **SOURCE_BOOK**: 《人人都能學會股票當沖全圖解》
* **SOURCE_CHAPTER**: 第三篇 實戰操作 3-4「權證小哥：自營比大於10%，跟著隔日沖主力賺」
* **SOURCE_PAGE**: p.184 - p.197
* **DIRECTION**: SHORT
* **CATEGORY**: ENTRY
* **AUTHOR_CLAIM**: 權證隔日沖主力大買認購權證後，發行權證的自營商被迫在現貨市場買進標的股票進行 Delta 避險，造成現貨尾盤大漲。隔日開盤權證主力獲利了結賣出認購權證，自營商必須在現貨市場同步拋售避險股票，導致現貨早盤（09:00～09:15）面臨強大且必然的下殺賣壓，可放空現貨或股票期貨獲利。
* **ORIGINAL_CONTEXT**: 利用衍生品造市商結構性避險特性的跨市場套利當沖。
* **MARKET_CONDITION**: 盤前確認，無特定大盤要求。
* **TIME_CONDITION**: 09:00～09:15（黃金拋售期）。
* **PRICE_CONDITION**: 
  1. 盤前：標的股票期貨成交量 > 100口（確保流動性）。
  2. 盤前：自營商避險買超比率（自營比） $> 10\%$（自營比 = 自營商買賣超金額 / 該股成交金額）。
  3. 盤中開盤：標的現貨漲跌幅在 $+2\%$ 至 $-2\%$ 之間（不可開太高或直接開跌停）。
  4. 股期價差比 $< 0.6\%$，正逆價差 $< 1\%$。
* **VOLUME_CONDITION**: 股期開盤有量（避免滑價過大）。
* **CANDLE_CONDITION**: 現貨或股期開盤第一根K棒（1分K）出量收黑棒，或反彈不過高。
* **ORDERFLOW_CONDITION**: 內盤成交比例大增，連續出現外盤大單拋出至內盤成交。
* **INDEX_CONDITION**: 大盤早盤未大幅暴漲。
* **SECTOR_CONDITION**: 無。
* **ENTRY_TRIGGER**: 09:00 開盤後，見現貨與股期開始出現自營商避險出脫賣單（內盤連續成交），股期跌破開盤價或現貨開高走低跌破第一檔支撐時進場放空。
* **EXIT_TRIGGER**: 09:15 之前，當股價急跌爆大量、買賣盤出現大筆回補單力竭時平倉。
* **STOP_LOSS**: 股期或現貨突破當日開盤價，或突破當日早盤高點，立即停損。
* **TAKE_PROFIT**: 下跌 1.5%～3% 滿足點，或時間到達 09:15～09:20 權證賣壓宣洩完畢時主動平倉。
* **INVALIDATION**: 現貨開盤直接跳空漲停（無法放空避險）或跳空重挫 > 5%。
* **REQUIRED_DATA**: 每日盤後券商分點權證進出資料、證交所三大法人買賣超（自營商買賣超區分自行買賣與避險）、標的股票期貨 1-Tick 及 1-Min OHLCV、標的股票現貨逐筆資料。
* **POSSIBLE_FEATURES**: `dealer_hedging_ratio_eod`, `warrant_delta_turnover_ratio`, `open_gap_pct`, `futures_basis_spread_pct`, `orderflow_bid_ask_trade_ratio`
* **QUANTIFIABLE**: YES
* **BACKTESTABLE**: YES
* **AI_INFERENCE**: false（小哥在書中將「自營比>10%」、「09:00～09:15」、「正逆價差<1%」明確數字化）。
* **AMBIGUITY**: 「大單拋出」、「急跌爆量力竭」需量化。
* **LOOKAHEAD_BIAS_RISK**: NONE（自營比為前一日盤後證交所公開資訊）。
* **SURVIVORSHIP_BIAS_RISK**: LOW（全市場每日皆可客觀計算自營比排名）。
* **IMPLEMENTATION_RISK**: 若盤中遇到主力轉隔日沖為波段拉抬（或現貨發動軋空），自營商反向被迫追買現貨避險，空頭會遭遇劇烈軋空。
* **NEEDS_TRANSACTION_COST**: YES（股期交易成本極低，此策略適合股期）。
* **NEEDS_SLIPPAGE**: YES
* **RESEARCH_PRIORITY**: HIGH（最優先驗證之微觀結構量化策略）。

---

### RULE_ID: R_005
* **TITLE**: 台指期委買賣成交口數差與1分K布林通道多空假說（林昇線條式當沖）
* **SOURCE_BOOK**: 《人人都能學會股票當沖全圖解》
* **SOURCE_CHAPTER**: 第三篇 實戰操作 3-3「林昇：線條式當沖，只要看懂4條線」
* **SOURCE_PAGE**: p.166 - p.183
* **DIRECTION**: BOTH
* **CATEGORY**: MARKET_REGIME / ENTRY
* **AUTHOR_CLAIM**: 散戶習慣掛假單，但「成交口數」絕對無法作假。透過台指期盤中「委買成交總口數」與「委賣成交總口數」之差額，可精確看出大盤實質多空力量；再結合台指期 1分K 布林通道（1倍標準差），突破上軌且口數差多方勝出則做多強勢股，跌破下軌且空方勝出則放空弱勢股。
* **ORIGINAL_CONTEXT**: 股期與現貨當沖的大盤濾網與方向確認。
* **MARKET_CONDITION**: 每日 08:45～09:45。
* **TIME_CONDITION**: 開盤後一小時內。
* **PRICE_CONDITION**: 台指期 1分K 收盤價突破布林通道上軌（$Close_t > UpperBand_t$）為多方；跌破布林通道下軌（$Price_t < LowerBand_t$）為空方。（參數：週期取短天期，標準差 $\sigma = 1$）。
* **VOLUME_CONDITION**: 個股股票期貨當日預估量或近3日均量 > 500口。
* **CANDLE_CONDITION**: 個股 1分K 出現與大盤方向一致之趨勢K棒。
* **ORDERFLOW_CONDITION**: 
  * 多方條件：台指期「委買成交口數 － 委賣成交口數」$> 0$ 且差距持續擴大。
  * 空方條件：台指期「委買成交口數 － 委賣成交口數」$< 0$ 且負差距持續擴大。
  * 個股內外盤成交線：做多時外盤成交量線高於內盤成交量線。
* **INDEX_CONDITION**: 台指期與加權指數走勢同向。
* **SECTOR_CONDITION**: 個股走勢強度強於大盤（大盤回檔時個股抗跌或創高）。
* **ENTRY_TRIGGER**: 當大盤指標（口數差正向 + 站上1倍標準差上軌）成立，選取強於大盤之個股，於其突破開盤區間高點時買進股票期貨。
* **EXIT_TRIGGER**: 台指期 1分K 跌回布林通道中軌（MA），或口數差翻轉，或時間到達 09:45～10:00。
* **STOP_LOSS**: 個股期貨跌破進場當根 1分K 低點，或台指期灌破布林下軌。
* **TAKE_PROFIT**: 個股觸及壓力區，或獲利達 2% 以上分批平倉。
* **INVALIDATION**: 09:45 後未發動趨勢，強制平倉離場。
* **REQUIRED_DATA**: 台指期逐筆委託與撮合成交資料（包含成交累計內外盤口數）、台指期 1分K、股票期貨逐筆資料。
* **POSSIBLE_FEATURES**: `tx_net_traded_lots_diff`, `tx_bb_1sigma_pos`, `stock_vs_index_relative_strength_1m`, `stock_ask_bid_trade_diff`
* **QUANTIFIABLE**: YES
* **BACKTESTABLE**: YES
* **AI_INFERENCE**: true
* **AI_INFERENCE_DETAIL**: 書中提及布林通道「常態分布1倍標準差有68.3%機率在帶內，跑出帶外代表極強勢」，但未給予布林中軌 MA 的滾動均線長度，AI 推導應預設為標準 $MA(20)$ 於 1分K。
* **AMBIGUITY**: 「口數差持續擴大」需要量化為斜率門檻（如 $\Delta \text{Diff} > K$ lots/min）。
* **LOOKAHEAD_BIAS_RISK**: NONE
* **SURVIVORSHIP_BIAS_RISK**: LOW
* **IMPLEMENTATION_RISK**: 1分K配合 1倍標準差之布林帶寬度極窄，極易產生頻繁假突破訊號。
* **NEEDS_TRANSACTION_COST**: YES
* **NEEDS_SLIPPAGE**: YES
* **RESEARCH_PRIORITY**: HIGH

---

### RULE_ID: R_006
* **TITLE**: 關鍵價位帶（樓層式）突破做多與破底放空假說（詹大樓層法）
* **SOURCE_BOOK**: 《人人都能學會股票當沖全圖解》
* **SOURCE_CHAPTER**: 第三篇 實戰操作 3-1「詹大：樓層式當沖，找出關鍵價位」
* **SOURCE_PAGE**: p.130 - p.147
* **DIRECTION**: BOTH
* **CATEGORY**: ENTRY / EXIT
* **AUTHOR_CLAIM**: 股價漲跌並非毫無軌跡，而是像在電梯中於樓層（支撐與壓力）之間移動。透過日K線找出近 5～20 日重複出現的密集收盤價/轉折高低點，畫出 3～5 條關鍵價位線（樓層）。盤中突破天花板代表進入上一樓層，順勢做多；跌破地板代表下墜，順勢放空。
* **ORIGINAL_CONTEXT**: 日內震盪與區間突破交易。
* **MARKET_CONDITION**: 震盪盤或區間盤。
* **TIME_CONDITION**: 09:05～12:30。
* **PRICE_CONDITION**: 盤前計算好支撐位 $S_1, S_2$ 與壓力位 $R_1, R_2$。盤中即時價格 $Price_t$ 突破 $R_1$ 或跌破 $S_1$。
* **VOLUME_CONDITION**: 突破關鍵價位帶時，必須有大單或 5分K 帶量。
* **CANDLE_CONDITION**: 5分K 實體完全收在關鍵價位帶之外（站穩）。
* **ORDERFLOW_CONDITION**: 突破當下五檔委賣第一檔大單被市價買盤一口氣吃掉。
* **INDEX_CONDITION**: 無。
* **SECTOR_CONDITION**: 無。
* **ENTRY_TRIGGER**: 5分K 收盤確認站上壓力線 $R_1$（轉為新地板）進場做多；跌破支撐線 $S_1$（轉為新天花板）進場放空。
* **EXIT_TRIGGER**: 上漲至上一層天花板 $R_2$ 遇阻力平倉，或跌至下一層地板 $S_2$ 平倉。
* **STOP_LOSS**: 做多跌破進場之關鍵價位 $R_1$ 且未於 3～5 分鐘內收復；做空突破 $S_1$ 停損。
* **TAKE_PROFIT**: 到達目標樓層價位獲利了結。
* **INVALIDATION**: 盤中價格在兩樓層中間狹幅混亂整理（不操作）。
* **REQUIRED_DATA**: 日K歷史OHLCV、盤中 5分K 與 Tick 資料。
* **POSSIBLE_FEATURES**: `dist_to_key_support_pct`, `dist_to_key_resistance_pct`, `breakout_volume_multiple`, `key_level_density_score`
* **QUANTIFIABLE**: PARTIAL
* **BACKTESTABLE**: PARTIAL
* **AI_INFERENCE**: true
* **AI_INFERENCE_DETAIL**: 作者所謂「高頻重複價位」屬人工畫線經驗，量化上需轉換為演算法：如使用核密度估計（Kernel Density Estimation, KDE）計算日K過去20日的高低點分布峰值，或計算成交量分布（Volume Profile / VPVR）的高成交量節點（High Volume Node, HVN）。
* **AMBIGUITY**: 樓層寬度如果過窄（如僅差 0.5%），交易成本會吃掉所有利潤。
* **LOOKAHEAD_BIAS_RISK**: LOW
* **SURVIVORSHIP_BIAS_RISK**: MEDIUM
* **IMPLEMENTATION_RISK**: 在趨勢噴出行情中，所有歷史樓層會被瞬間打穿，若逢高放空會面臨毀滅性虧損。
* **NEEDS_TRANSACTION_COST**: YES
* **NEEDS_SLIPPAGE**: YES
* **RESEARCH_PRIORITY**: MEDIUM

---

### RULE_ID: R_007
* **TITLE**: 五檔大單假防守摜破追空假說（Jasper 盤口結構）
* **SOURCE_BOOK**: 《【圖解】最高勝率手機當沖》
* **SOURCE_CHAPTER**: 第三章「盤中實戰策略」之「五檔委託單的虛與實」
* **SOURCE_PAGE**: EPUB Section A-26, A-27
* **DIRECTION**: SHORT
* **CATEGORY**: ENTRY
* **AUTHOR_CLAIM**: 很多新手看到委買五檔掛出數百張、上千張的大買單，以為有主力在防守而跟著買進做多，結果往往被修理。主力真正要買進不會掛在下面給人倒貨；五檔出現異常肥大的委買單往往是主力「假撐盤、真出貨」，一旦該肥大買單被主動大單摜穿或突然撤單（Spoofing），盤面會引發踩踏暴跌，應立刻跟進追空。
* **ORIGINAL_CONTEXT**: 盤中針對弱勢股或高檔盤整股的盤口反轉操作。
* **MARKET_CONDITION**: 個股日內處於弱勢，或大盤開高走低。
* **TIME_CONDITION**: 09:15～11:00。
* **PRICE_CONDITION**: 股價在當日相對低檔或 VWAP 之下。
* **VOLUME_CONDITION**: 委買掛單量遠大於委賣掛單量（Order Book Imbalance 倒掛）。
* **CANDLE_CONDITION**: 不看K線（作者原則），純看跳動。
* **ORDERFLOW_CONDITION**: 
  1. 買一或買二掛單量大於前五檔平均掛單量的 3 倍以上（假厚防守）。
  2. 出現一筆或多筆主動賣單（內盤成交）直接吃光該檔掛單，或者該大單於成交前瞬間取消。
  3. 價格瞬間向下跌破該檔位，且賣一檔立刻補上大量壓單。
* **INDEX_CONDITION**: 無。
* **SECTOR_CONDITION**: 同族群股票同步走弱。
* **ENTRY_TRIGGER**: 見委買巨大防守單被完全擊穿（或成交量爆出且價格穿透該價位）的瞬間，市價（ROD或IOC）追空。
* **EXIT_TRIGGER**: 下跌 2～4 個 Tick 快速回補，或下檔再次出現大量實質換手單時平倉。
* **STOP_LOSS**: 嚴格設定 2～3 個 Tick。若價格反彈站回被擊穿的委買價位，無條件砍倉。
* **TAKE_PROFIT**: 獲利達 1%～2% 或 3～5 個 Tick 分批獲利。
* **INVALIDATION**: 委買大單被吃掉後，下一秒買盤立刻湧入並向上反咬。
* **REQUIRED_DATA**: Level 2（L2）完整委託簿快照（深度5檔或全部深度）、逐筆成交資料（含主動買/主動賣屬性與委託撤單事件）。
* **POSSIBLE_FEATURES**: `bid_wall_volume_ratio`, `wall_consumed_speed_ms`, `order_cancellation_ratio`, `post_breakdown_tick_momentum`
* **QUANTIFIABLE**: YES
* **BACKTESTABLE**: YES
* **AI_INFERENCE**: true
* **AI_INFERENCE_DETAIL**: 作者在書中以手機截圖顯示「委買778張、委賣僅32張，看似支撐強烈，實則隨後大跌」，量化上需嚴謹定義「厚度倍數（Wall Ratio）」與「穿透時間窗口（$T < 500\text{ms}$）」。
* **AMBIGUITY**: 需精確區分是「真實成交擊破」還是「主力抽單（Cancellation）」。
* **LOOKAHEAD_BIAS_RISK**: NONE
* **SURVIVORSHIP_BIAS_RISK**: LOW
* **IMPLEMENTATION_RISK**: 延遲競爭（Latency Risk）。若系統撮合與下單延遲高於數十毫秒，追空往往成交在反彈低點（空在地板）。
* **NEEDS_TRANSACTION_COST**: YES（高頻 Tick 策略對手續費折讓極度敏感）。
* **NEEDS_SLIPPAGE**: YES
* **RESEARCH_PRIORITY**: HIGH

---

### RULE_ID: R_008
* **TITLE**: 強勢股拉回前低不破且委買轉強做多假說（Jasper 順勢拉回法）
* **SOURCE_BOOK**: 《【圖解】最高勝率手機當沖》
* **SOURCE_CHAPTER**: 第三章「盤中實戰策略」之「拉回進場操作法」
* **SOURCE_PAGE**: EPUB Section A-30, A-31
* **DIRECTION**: LONG
* **CATEGORY**: ENTRY
* **AUTHOR_CLAIM**: 絕不追在急噴的第一根紅K，因為手機下單容易滑價被套；正確的高勝率做法是等待強勢股衝高後自然回檔，回檔時觀察成交量是否萎縮且「未跌破早盤前一波起漲低點」。當五檔委賣單被連續外盤大單敲進、委買掛單開始墊高時進場做多。
* **ORIGINAL_CONTEXT**: 早盤強勢股二次發動動能捕捉。
* **MARKET_CONDITION**: 大盤偏多或回檔支撐確認。
* **TIME_CONDITION**: 09:15～10:30。
* **PRICE_CONDITION**: 
  1. 早盤第一波漲幅 $> 2.5\%$。
  2. 回檔最低點 $Low_{pullback} > Low_{morning}$（不破早盤起漲點或開盤價）。
  3. 回檔幅度不超過第一波漲幅的 $50\%$（波浪理論健康回檔）。
* **VOLUME_CONDITION**: 上漲出量，拉回量縮（拉回成交速度明顯變慢）。
* **CANDLE_CONDITION**: 股價止跌橫盤 3～5 分鐘。
* **ORDERFLOW_CONDITION**: 委買掛單逐檔墊高，外盤成交比例（Trade Aggressiveness）由小於 40% 快速翻轉至 60% 以上。
* **INDEX_CONDITION**: 大盤在此時未出現連續急殺。
* **SECTOR_CONDITION**: 同族群龍頭股維持強勢或再創新高。
* **ENTRY_TRIGGER**: 盤口出現單筆大於百萬以上之外盤主動買單吃穿賣一檔，隨後買一檔立刻補上買單時進場。
* **EXIT_TRIGGER**: 突破前波高點後出現外盤掛大單停滯，或獲利達到 1.5%～3%。
* **STOP_LOSS**: 跌破本次拉回的最低點 $Low_{pullback}$（通常約 3～5 個 Tick）。
* **TAKE_PROFIT**: 創當日新高後 3～5 檔內分批停利。
* **INVALIDATION**: 拉回直接灌破今日起漲點或開盤價。
* **REQUIRED_DATA**: 逐筆成交與委託明細、日內 1分K OHLCV、即時五檔。
* **POSSIBLE_FEATURES**: `pullback_depth_ratio`, `pullback_volume_decay`, `orderflow_aggressor_flip`, `ticks_to_pullback_low`
* **QUANTIFIABLE**: YES
* **BACKTESTABLE**: YES
* **AI_INFERENCE**: true
* **AI_INFERENCE_DETAIL**: 作者強調「拉回不破前低」與「買盤變積極」，量化上需將前低定義為日內微結構轉折低（Swing Low），並將買盤轉積極定義為外盤成交量加速度 $\frac{d(Vol_{ask})}{dt} > \theta$。
* **AMBIGUITY**: 書中「感覺跌不下去了」為純主觀心理，需以盤口連續 3 檔買盤墊高為量化代理變數。
* **LOOKAHEAD_BIAS_RISK**: NONE
* **SURVIVORSHIP_BIAS_RISK**: LOW
* **IMPLEMENTATION_RISK**: 拉回可能演變成「假反彈、真崩跌」的頭肩頂型態。
* **NEEDS_TRANSACTION_COST**: YES
* **NEEDS_SLIPPAGE**: YES
* **RESEARCH_PRIORITY**: HIGH

---

### RULE_ID: R_009
* **TITLE**: 領頭羊帶量發動之同族群連動跟進假說（Jasper 族群效應）
* **SOURCE_BOOK**: 《【圖解】最高勝率手機當沖》
* **SOURCE_CHAPTER**: 第三章「盤中實戰策略」之「族群類股連動法」
* **SOURCE_PAGE**: EPUB Section A-28, A-29
* **DIRECTION**: LONG
* **CATEGORY**: STOCK_SELECTION / ENTRY
* **AUTHOR_CLAIM**: 資金在台股有極強的族群群聚效應。當某族群指標領頭羊（如散熱雙雄之雙鴻）帶大量急拉甚至直奔漲停時，同族群第二、第三名（如奇鋐、超眾）在 3～5 分鐘內極大概率會出現補漲連動。若能第一時間切入尚未大漲的二線同族群股，勝率極高；但若 5 分鐘內二線股毫無動靜，則表示連動失敗，不可戀戰。
* **ORIGINAL_CONTEXT**: 捕捉跨個股盤中資金溢出效應（Spillover Effect）。
* **MARKET_CONDITION**: 族群題材發酵、盤面有明確多頭主流。
* **TIME_CONDITION**: 09:05～10:30。
* **PRICE_CONDITION**: 
  1. 領頭股 $A$ 盤中 3 分鐘內漲幅 $> 3\%$ 或直接亮燈漲停。
  2. 跟隨股 $B$ 當前漲幅 $< 1.5\%$，尚未啟動。
* **VOLUME_CONDITION**: 領頭股成交量暴增（超過其過去 20 分鐘均量 3 倍）。
* **CANDLE_CONDITION**: 領頭股連續出實體長紅K。
* **ORDERFLOW_CONDITION**: 跟隨股 $B$ 的五檔委賣單開始出現連續小筆外盤敲進，有主力轉場試單跡象。
* **INDEX_CONDITION**: 大盤方向不與該族群逆向。
* **SECTOR_CONDITION**: 同細產業族群分類。
* **ENTRY_TRIGGER**: 當領頭股 $A$ 觸及漲停板或維持在最高點，且跟隨股 $B$ 出現第一筆大單敲進外盤時進場做多 $B$。
* **EXIT_TRIGGER**: 
  1. 領頭股 $A$ 漲停打開下殺，立即市價出清 $B$。
  2. 跟隨股 $B$ 出現補漲滿足（上漲 1.5%～2.5%）平倉。
* **STOP_LOSS**: 進場後超過 3～5 分鐘 $B$ 仍未跟進發動，或者跌破進場點 2 個 Tick，立即手動停損。
* **TAKE_PROFIT**: 跟隨股補漲爆量或接近族群整體漲幅時平倉。
* **INVALIDATION**: 領頭股為假突破，急拉後立刻反轉大跳水。
* **REQUIRED_DATA**: 即時全市場各產業族群分類對應表、全市場逐筆行情、高頻跨個股共變異矩陣監控。
* **POSSIBLE_FEATURES**: `leader_3m_return`, `follower_lag_return_diff`, `sector_co_movement_score`, `time_elapsed_since_leader_breakout`
* **QUANTIFIABLE**: YES
* **BACKTESTABLE**: YES
* **AI_INFERENCE**: true
* **AI_INFERENCE_DETAIL**: 書中僅以經驗說明「看雙鴻拉奇鋐」，量化系統需先進行盤前或歷史「高頻成對回歸（Co-integration & Lead-Lag Cross-Correlation）」計算，確認 $A$ 與 $B$ 過去 30 日的日內 Lead-Lag 係數顯著大於 0.6，且需嚴格設定「5分鐘發動失效計時器（Time-out Invalidation）」。
* **AMBIGUITY**: 領頭羊的定義在實況中可能盤中切換（今天A領漲、明天B領漲）。
* **LOOKAHEAD_BIAS_RISK**: LOW
* **SURVIVORSHIP_BIAS_RISK**: MEDIUM
* **IMPLEMENTATION_RISK**: 補漲股可能因自身基本面極差而成為「弱勢跟不上」，反而在領頭股拉回時跌得更兇。
* **NEEDS_TRANSACTION_COST**: YES
* **NEEDS_SLIPPAGE**: YES
* **RESEARCH_PRIORITY**: HIGH

---

### RULE_ID: R_010
* **TITLE**: 漲停板未鎖死回跌放空假說（Limit-Up Breakdown Short）
* **SOURCE_BOOK**: 《【圖解】最高勝率手機當沖》
* **SOURCE_CHAPTER**: 第三章「盤中實戰策略」之「漲停未鎖死操作法」
* **SOURCE_PAGE**: EPUB Section A-32, A-33
* **DIRECTION**: SHORT
* **CATEGORY**: ENTRY
* **AUTHOR_CLAIM**: 很多投資人以為碰漲停就是極強，但如果一檔股票多次觸碰漲停板卻無法鎖死（委買排隊量稀少或頻繁被大單砸開），代表主力只是藉由漲停氣勢掩護出貨。當漲停板被摜破且回跌超過 2% 時，早盤追高與排隊買進的隔日沖主力全部被套牢，隨後必定產生停損多殺多骨牌效應，是極高勝率的放空機會。
* **ORIGINAL_CONTEXT**: 捕捉強勢股多空易位的高爆發放空機會。
* **MARKET_CONDITION**: 盤中爆量震盪或中小型投機股。
* **TIME_CONDITION**: 09:30～12:30。
* **PRICE_CONDITION**: 
  1. 今日盤中最高價曾觸及漲停板價位（$High_{today} = LimitUp\_Price$）。
  2. 價格自漲停板回跌超過 2%（$Price_t \le LimitUp\_Price \times 0.98$）。
* **VOLUME_CONDITION**: 漲停板打開時伴隨當日單量最大之巨量成交。
* **CANDLE_CONDITION**: 5分K 收出長上影線或大黑K。
* **ORDERFLOW_CONDITION**: 漲停價位原本數千張委買掛單在 1～3 秒內被連續市價大賣單全部擊穿，或委買單主動撤銷後價格崩跌。
* **INDEX_CONDITION**: 大盤未能持續創高。
* **SECTOR_CONDITION**: 無。
* **ENTRY_TRIGGER**: 跌破漲停板價位且連續出現內盤主動賣單，跌幅達到 1.5%～2% 確認破線時進場放空。
* **EXIT_TRIGGER**: 價格急跌至日內均價線（VWAP）或跌幅達 4%～5% 時平倉。
* **STOP_LOSS**: 股價再度反彈逼近漲停板（如距離漲停 2 個 Tick），無條件停損。
* **TAKE_PROFIT**: 回補於均價線附近或爆量下影線時。
* **INVALIDATION**: 漲停打開後僅回測 0.5% 便再次以萬張大單強勢鎖死。
* **REQUIRED_DATA**: 漲跌停限制價格表、盤中逐筆成交與委託量、跌破速度計算。
* **POSSIBLE_FEATURES**: `limit_up_touch_count`, `limit_up_unlocked_volume`, `fall_from_limit_up_pct`, `vwap_distance_from_limit_up`
* **QUANTIFIABLE**: YES
* **BACKTESTABLE**: YES
* **AI_INFERENCE**: false（書中明確指出觸及漲停未鎖、回跌超過2%為放空進場點）。
* **AMBIGUITY**: 書中「數次碰漲停」的「數次」未精確量化，建議設定為 $\ge 2$ 次。
* **LOOKAHEAD_BIAS_RISK**: NONE
* **SURVIVORSHIP_BIAS_RISK**: LOW
* **IMPLEMENTATION_RISK**: 若主力採取「洗盤式開板」，開板後瞬間回鎖，空單會直接被關在漲停板裡面面臨無法回補或借券費的巨大風險（台股現股當沖先賣若未補需借券）。
* **NEEDS_TRANSACTION_COST**: YES
* **NEEDS_SLIPPAGE**: YES
* **RESEARCH_PRIORITY**: HIGH（同時具備 Filter 與 Short Strategy 雙重價值）。

---

### RULE_ID: R_011
* **TITLE**: 早盤三筆分批金字塔加碼部位管理規則
* **SOURCE_BOOK**: 《100張圖學會K線當沖》
* **SOURCE_CHAPTER**: Part-1 1-4「進場部位分配與心態控制」
* **SOURCE_PAGE**: p.24 - p.28
* **DIRECTION**: LONG
* **CATEGORY**: RISK / POSITION_SIZING
* **AUTHOR_CLAIM**: 當沖絕對不能一筆敲進滿倉，更嚴禁賠錢攤平。正確做法是將單日預算分為三筆試單：第一筆試單進場後，有獲利拉開成本才准加碼第二筆，再突破確認才敲第三筆；且早盤（09:00～09:30）整體部位絕對不超過總額度的一半，防範早盤劇烈假突破。
* **ORIGINAL_CONTEXT**: 當沖部位風險控制與槓桿控管。
* **MARKET_CONDITION**: 任何盤態。
* **TIME_CONDITION**: 09:00～13:00 全日部位管理。
* **PRICE_CONDITION**: 
  * 第 1 筆部位：基礎倉位（如 20%）。
  * 第 2 筆加碼：當前價格高於第 1 筆成本 $+0.8\%$ 且站穩 VWAP，加碼 20%。
  * 第 3 筆加碼：當前價格再創新高且出量，加碼 10%。
  * 任何虧損狀態下：嚴禁任何加碼（加碼條件為 $Unrealized\_PnL > 0$）。
* **VOLUME_CONDITION**: 加碼點必須伴隨買盤外盤成交量放大。
* **CANDLE_CONDITION**: 形成階梯式向上（Higher Highs）。
* **ORDERFLOW_CONDITION**: 無。
* **INDEX_CONDITION**: 無。
* **SECTOR_CONDITION**: 無。
* **ENTRY_TRIGGER**: 符合基本進場訊號敲第 1 筆；訊號確認且獲利達標敲第 2、3 筆。
* **EXIT_TRIGGER**: 只要價格跌破前一筆加碼成本線，全數部位離場。
* **STOP_LOSS**: 第 1 筆虧損達 1.5% 或破防守點即砍，絕不給予加碼攤平機會。
* **TAKE_PROFIT**: 整體部位於目標價或尾盤平倉。
* **INVALIDATION**: 第一筆即看錯虧損。
* **REQUIRED_DATA**: 即時成交回報、未實現損益監控、即時價格。
* **POSSIBLE_FEATURES**: `current_unrealized_pnl_pct`, `position_step_count`, `time_since_last_entry`
* **QUANTIFIABLE**: YES
* **BACKTESTABLE**: YES
* **AI_INFERENCE**: true
* **AI_INFERENCE_DETAIL**: 會長書中提出「分三筆買進」、「早盤不打滿」及「賺錢才加碼」原則，量化時需將加碼門檻精確設定為固定的已實現/未實現獲利比率（如 +0.8%、+1.5%），並強制設定單一標的最大曝險上限為總資金之 50%。
* **AMBIGUITY**: 「拉開成本」的精確百分比在書中為動態口語表達。
* **LOOKAHEAD_BIAS_RISK**: NONE
* **SURVIVORSHIP_BIAS_RISK**: NONE
* **IMPLEMENTATION_RISK**: 在震盪盤中，加碼會提高平均成本，導致原本第一筆獲利在反轉時迅速轉為全倉虧損。
* **NEEDS_TRANSACTION_COST**: YES
* **NEEDS_SLIPPAGE**: YES
* **RESEARCH_PRIORITY**: HIGH

---

### RULE_ID: R_012
* **TITLE**: 每日最大虧損熔斷關機規則（Jasper 心理與風控防線）
* **SOURCE_BOOK**: 《【圖解】最高勝率手機當沖》
* **SOURCE_CHAPTER**: 第四章「心理建設與資金控管」
* **SOURCE_PAGE**: EPUB Section A-44, A-45
* **DIRECTION**: BOTH
* **CATEGORY**: RISK / FILTER
* **AUTHOR_CLAIM**: 當沖交易員最致命的死因是「凹單」與「失控情緒化交易（Revenge Trading）」。必須在盤前設定好不可妥協的每日最大虧損金額（設定為當沖操作本金的 10%）；一旦當日累積已實現加上未實現虧損觸及該界限，必須強制關閉軟體、拔掉網路線、立即離場，當日絕對不得再下任何一筆單。
* **ORIGINAL_CONTEXT**: 交易系統最外層的帳戶級風控防護網（System-Level Circuit Breaker）。
* **MARKET_CONDITION**: 任何市場環境。
* **TIME_CONDITION**: 全交易時段（09:00～13:30）。
* **PRICE_CONDITION**: 帳戶級即時淨值監控。
  $$\text{Daily\_PnL}_t = \text{Realized\_PnL}_t + \text{Unrealized\_PnL}_t$$
  $$\text{Daily\_PnL}_t \le -\text{Max\_Daily\_Loss\_Limit}$$
* **VOLUME_CONDITION**: 無。
* **CANDLE_CONDITION**: 無。
* **ORDERFLOW_CONDITION**: 無。
* **INDEX_CONDITION**: 無。
* **SECTOR_CONDITION**: 無。
* **ENTRY_TRIGGER**: 當日嚴格禁止進場（Trading Halting）。
* **EXIT_TRIGGER**: 若觸發時手上仍有未平倉部位，全部以市價單（ROD/IOC）強制全數出清平倉。
* **STOP_LOSS**: 系統帳戶級停止運作。
* **TAKE_PROFIT**: 無。
* **INVALIDATION**: 無。
* **REQUIRED_DATA**: 交易帳戶即時成交帳務、未平倉損益串流。
* **POSSIBLE_FEATURES**: `daily_cum_pnl_ratio`, `consecutive_loss_count`, `drawdown_from_daily_peak`
* **QUANTIFIABLE**: YES
* **BACKTESTABLE**: YES
* **AI_INFERENCE**: false（作者書中明確以2萬元本金每日虧2,000元即停止交易為例）。
* **AMBIGUITY**: 無（純帳務數學邊界）。
* **LOOKAHEAD_BIAS_RISK**: NONE
* **SURVIVORSHIP_BIAS_RISK**: NONE
* **IMPLEMENTATION_RISK**: 實務上需防範斷線或強制市價平倉時之極端滑價。
* **NEEDS_TRANSACTION_COST**: YES
* **NEEDS_SLIPPAGE**: YES
* **RESEARCH_PRIORITY**: HIGH（量化實盤交易系統必備基石）。

---

# 03_FEATURE_CANDIDATES

本章節將三本教材中模糊的定性文字（如「長紅棒」、「爆大量」、「大單敲進」、「盤面很強」），轉譯為現代統計與機器學習可直接使用的數值特徵。

### 1. K線幾何與結構特徵庫（Candle & Geometry）
| 原書概念 | 數學轉譯候選特徵（Candidate Features） | 量化定義 / 計算公式 | AI_INFERENCE |
| :--- | :--- | :--- | :--- |
| **長紅棒 / 長黑棒** | `body_ratio`<br>`body_return_pct` | `body_ratio` = $\frac{|Close - Open|}{High - Low + \epsilon}$<br>`body_return_pct` = $\frac{Close - Open}{Open}$ | true |
| **上影線壓力** | `upper_shadow_ratio` | $\frac{High - \max(Open, Close)}{High - Low + \epsilon}$ | true |
| **下影線支撐** | `lower_shadow_ratio` | $\frac{\min(Open, Close) - Low}{High - Low + \epsilon}$ | true |
| **收盤強弱位置** | `close_location_value` (CLV) | $\frac{(Close - Low) - (High - Close)}{High - Low + \epsilon}$，區間 $[-1, +1]$ | true |
| **跳空幅度** | `gap_open_pct` | $\frac{Open_t - Close_{t-1}}{Close_{t-1}}$ | true |
| **均線排列分數** | `ma_alignment_score` | $\text{sgn}(MA_5 - MA_{10}) + \text{sgn}(MA_{10} - MA_{20}) + \text{sgn}(MA_{20} - MA_{60})$，範圍 $[-3, +3]$ | true |
| **距前高壓力距離** | `dist_to_prev_high_pct` | $\frac{\max_{1 \le i \le N}(High_{t-i}) - Price_t}{Price_t}$ | true |

### 2. 成交量能與加速度特徵庫（Volume Dynamics）
| 原書概念 | 數學轉譯候選特徵（Candidate Features） | 量化定義 / 計算公式 | AI_INFERENCE |
| :--- | :--- | :--- | :--- |
| **早盤爆量** | `relative_volume_open` (RVOL) | $\frac{Volume_{09:00-09:05}}{\frac{1}{20}\sum_{d=1}^{20} Volume_{09:00-09:05, d}}$ | true |
| **即時量增率** | `volume_ratio_5m` | $\frac{Vol_{t}}{\frac{1}{5}\sum_{i=1}^5 Vol_{t-i}}$ | true |
| **成交加速度** | `volume_acceleration` | $\frac{d^2(Volume)}{dt^2} \approx (Vol_t - Vol_{t-1}) - (Vol_{t-1} - Vol_{t-2})$ | true |
| **週轉率強度** | `turnover_rate_intraday` | $\frac{\sum_{\tau=0}^t TradedShares_{\tau}}{TotalOutstandingShares}$ | true |
| **回檔量縮比** | `pullback_vol_decay_ratio` | $\frac{\text{Mean Volume in Pullback Ticks}}{\text{Mean Volume in Breakout Ticks}}$ | true |

### 3. 即時微觀結構與盤口特徵庫（Orderflow & Level 2 L2）
| 原書概念 | 數學轉譯候選特徵（Candidate Features） | 量化定義 / 計算公式 | AI_INFERENCE |
| :--- | :--- | :--- | :--- |
| **五檔虛實失衡** | `order_book_imbalance_5` (OBI) | $\frac{\sum_{i=1}^5 BidQty_i - \sum_{i=1}^5 AskQty_i}{\sum_{i=1}^5 BidQty_i + \sum_{i=1}^5 AskQty_i}$ | true |
| **買賣主動侵略度** | `trade_aggressiveness_ratio` | $\frac{TradedVol_{Ask} - TradedVol_{Bid}}{TradedVol_{Ask} + TradedVol_{Bid}}$，區間 $[-1, +1]$ | true |
| **假支撐防守比** | `bid_wall_thickness_ratio` | $\frac{\max(BidQty_{1:5})}{\text{Median}(BidQty_{1:5})}$ | true |
| **盤口跳動換手率** | `quote_flip_rate_1m` | 1分鐘內買一與賣一報價檔位跳動（Quote Flip）次數 | true |
| **大單吃穿速度** | `wall_depletion_velocity` | $\frac{\Delta TradedLots}{\Delta t}$（特定檔位大單被完全吃穿之毫秒時間） | true |

### 4. 衍生品與跨市場連動特徵庫（Derivatives & Cross-Asset）
| 原書概念 | 數學轉譯候選特徵（Candidate Features） | 量化定義 / 計算公式 | AI_INFERENCE |
| :--- | :--- | :--- | :--- |
| **權證避險自營比** | `dealer_hedging_ratio_eod` | $\frac{\text{Dealer Net Buy Amount}}{\text{Total Stock Traded Amount}}$（書中門檻 $> 10\%$） | false（小哥原文） |
| **股期正逆價差率** | `futures_basis_pct` | $\frac{FuturesPrice_t - SpotPrice_t}{SpotPrice_t}$（書中要求 $< 1\%$） | false（小哥原文） |
| **台指期淨口數差** | `tx_traded_lots_spread` | $\sum TradedLots_{Tx, Buy} - \sum TradedLots_{Tx, Sell}$ | false（林昇原文） |
| **族群動能遲滯差** | `sector_lead_lag_return_diff` | $Return_{Leader, 3m} - Return_{Follower, 3m}$ | true |

---

# 04_ENTRY_RULES

將三本書中分散的進場邏輯，整合為三大結構性流派：

### 1. 動能突破流（Breakout / Momentum）
* **代表書籍**：《100張圖學會K線當沖》（會長）、《人人都能學會股票當沖全圖解》（詹大）
* **核心量化架構**：
  * **先驗條件**：日K為多方標準排列（$MA5 > MA10 > MA20$ 且近10日內未破5MA）或近期箱型密集整理帶。
  * **觸發點**：盤中 1分K 或 5分K 帶量（$RVOL > 2.0$）突破前高（昨日最高點、盤前樓層天花板、或早盤高點）。
  * **微觀結構驗證**：外盤連續成交、買一檔迅速補進大單、OBI $> 0.2$。

### 2. 折返確認流（Pullback / Reversal）
* **代表書籍**：《【圖解】最高勝率手機當沖》（Jasper）、《100張圖學會K線當沖》（會長）
* **核心量化架構**：
  * **先驗條件**：標的已具備日內強勢動能（早盤漲幅 $> 2\%$ 且股價在 VWAP 之上）。
  * **觸發點**：價格衝高後拉回不破前低（$Low_{pullback} > Low_{morning}$），且拉回過程中成交量大幅萎縮（$Vol_{pullback} < 0.5 \times Vol_{breakout}$）。
  * **微觀結構驗證**：價格碰觸 VWAP 或支撐檔位後，出現連續 3 筆外盤主動大單且買檔向上墊高。

### 3. 微觀結構與衍生品造市套利流（Microstructure & Cross-Asset Arbitrage）
* **代表書籍**：《人人都能學會股票當沖全圖解》（權證小哥、林昇）、《【圖解】最高勝率手機當沖》（Jasper）
* **核心量化架構**：
  * **先驗條件**：前日盤後自營商避險買超比 $> 10\%$（小哥），或盤中台指期實質成交口數差顯著偏多/偏空（林昇），或同族群龍頭股率先鎖死漲停（Jasper）。
  * **觸發點**：09:00～09:15 自營商反向倒貨賣壓湧現，或跟隨股出現大單補漲敲進，或五檔巨大委買牆被瞬間擊破。

---

# 05_EXIT_RULES

### 1. 停損規則（Stop-Loss Mechanisms）
* **絕對底線停損**：
  * **VWAP 停損法**（會長）：任何做多部位，若 1分K 收盤價低於日內 VWAP 超過 0.2%，無條件市價平倉。
  * **Tick 級硬停損法**（Jasper）：高價股（>100元）進場後，若價格反向滑落 2～3 個 Tick，立即手動市價停損，單筆損失嚴格控制在 0.5%～0.8% 內。
  * **關鍵K棒低點停損法**（會長、詹大）：以突破進場當根 5分K 的最低點為防守點，灌破立即砍倉。
* **時間停損（Time-based Invalidation）**：
  * **族群連動失效**（Jasper）：跟隨股進場後 3～5 分鐘內未見補漲動能，不論損益強制退場。
  * **權證避險時段過期**（小哥）：放空部位超過 09:20 賣壓未湧現，主動平倉避開後續盤中主力反擊。
  * **林昇黃金小時**：超過 09:45 趨勢未明，全數離場。

### 2. 停利規則（Take-Profit Mechanisms）
* **目標階梯停利**：詹大樓層目標位（下一層天花板/地板）、整數關卡（百元大關、200元大關前一檔掛出）。
* **極限動能停利**：觸及漲停板前一檔全數出清（會長原則：絕不留單賭隔日跳空）；或急拉後高檔出爆量但價格停滯（Jasper：賣單源源不絕湧出）主動平倉。
* **移動追蹤停利（Trailing Stop）**：獲利達到 2% 後，啟動高點回檔 0.8% 強制保底平倉機制。

---

# 06_RISK_RULES

### 1. 單日停損熔斷機制（Daily Circuit Breaker）
* **規則**：每日最大累計虧損達到操作本金的 10%（Jasper）或絕對固定金額（如會長之單日上限），系統直接切斷當日下單權限，取消所有盤口掛單，進入強制休眠（Cool-down Mode）至次日。

### 2. 資金管理與倉位限制（Position Sizing & Exposure）
* **早盤倉位上限**：09:00～09:30 間，累計動用保證金不得超過總額度的 50%（會長）。
* **加碼鐵律**：嚴禁虧損攤平（Martingale）；加碼僅限於第一筆獲利且技術面二次突破時，採倒金字塔式（如 30% $\to$ 20% $\to$ 10%）。
* **持倉檔數限制**：同一時間處於活躍交易之標的不得超過 2 檔。

### 3. 流動性與股價絕對過濾器（Liquidity & Price Filter）
* **排除低流動性標的**：50元以下股成交量需 $> 20,000$ 張，50元以上股成交量需 $> 10,000$ 張（Jasper）；股票期貨成交量需 $> 500$ 口（林昇）或 $> 100$ 口（小哥）。
* **排除極端高價股**：股價 $> 300$ 元或 $> 500$ 元中小型股，跳檔成本與流動性非散戶能承受者予以過濾。

### 4. 絕對禁止交易條件（Prohibited Trading Conditions）
* **重大數據公佈前後**（如美股非農、大選日、台指期結算日最後半小時）。
* **開盤直接跳空漲停或跌停**（流動性鎖死，滑價與借券風險不可控）。
* **標的成交明細出現頻繁單筆 1 張且跳空交錯**（機器人對倒假量，流動性真實深度不足）。

---

# 07_ORDERFLOW_FEATURES

本章節深度拆解 Level 2 委託簿（五檔）與逐筆成交資料（Tick）之量化特徵：

### 1. 買賣盤失衡指標（Order Book Imbalance, OBI）
傳統五檔單純看張數總和極易受到深檔（第4、第5檔）虛單欺騙。量化需引入**距離加權失衡公式（Decay-Weighted OBI）**：
$$OBI_t = \frac{\sum_{i=1}^5 w_i \cdot BidQty_i - \sum_{i=1}^5 w_i \cdot AskQty_i}{\sum_{i=1}^5 w_i \cdot BidQty_i + \sum_{i=1}^5 w_i \cdot AskQty_i}$$
其中權重 $w_i = \frac{1}{i}$，即越靠近最佳買賣價的檔位權重越高。
* **假說**：當價格接近壓力位且加權 $OBI_t < -0.3$（委賣遠厚於委買），突破極易失敗；反之當加權 $OBI_t > 0.4$ 時，順勢突破勝率提升。

### 2. 主動進攻與成交侵略度（Trade Aggressiveness）
逐筆成交中，根據撮合價是成交在最佳賣價（Ask）還是最佳買價（Bid），精確計算**滾動成交侵略流（Rolling Aggressive Volume Delta, CVD）**：
$$DeltaVol_{\Delta t} = \sum_{\tau \in \Delta t} Vol_{\tau} \cdot \mathbb{I}(\text{TickType} = \text{Out/Ask}) - \sum_{\tau \in \Delta t} Vol_{\tau} \cdot \mathbb{I}(\text{TickType} = \text{In/Bid})$$
* **假說**：若股價在區間橫盤，但 $DeltaVol$ 呈現強烈正斜率累積，代表主力在被動委託中暗中市價掃貨，為潛在起漲前兆。

### 3. 虛假防守與大單瞬間擊破（Wall Breakdown & Spoofing Detection）
* **大單牆定義**：當單一檔位掛單量 $Qty_i \ge 3 \times \overline{Qty}$。
* **假支撐偵測**：當大買單牆出現在買一或買二，若在價格即將觸碰前 $100\text{ms}$ 內突然撤銷（Order Cancel），且內盤無相應成交量，標記 `spoofing_bid_detected = 1`。
* **真擊破特徵**：大買單牆於特定時間內被連續市價大單直接吞食，隨後最佳買價向下跌破 1 個 Tick 且最佳賣價立即掛出大壓單，標記 `bid_wall_breakdown = 1`（觸發放空）。

### 4. 買賣報價跳動換手率（Quote Flip Rate）
統計固定時間（如 30 秒）內最佳一檔報價（Best Bid / Best Ask）跳動的頻率與方向交替次數。頻率過高且價差未拉開代表多空爭奪激烈、籌碼換手迅速；若跳動驟降代表動能停滯。

---

# 08_CASE_LIBRARY

從三本書中嚴選 18 個經典具體實戰案例，進行量化解構：

| CASE_ID | 來源書籍 | 個股/標的 | 方向 | 型態/情境架構 | 進場理由（原書） | 出場理由（原書） | 量化通用性 | 潛在偏誤（Bias） |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **C_001** | 《100張圖》p.38 | 台表科 (6278) | LONG | 多方標準型態 | 5MA翻揚、離前高收盤<10%，開盤跳空創高 | 盤中觸及漲停或尾盤平倉 | YES | **倖存者偏誤**：只挑選隔日連拉大紅K案例。 |
| **C_002** | 《100張圖》p.44 | 矽力-KY (6415) | LONG | 多方連續型態 | 昨日創歷史新高，今日開盤再度跳空開高 | 守前日收盤價，尾盤獲利平倉 | YES | **高價股滑價風險**：千元股跳一檔即為巨大損益。 |
| **C_003** | 《100張圖》p.50 | 穩懋 (3105) | LONG | 多方複合型態 | 三角收斂末端，帶量跳空站上所有均線 | 盤中沿均價線上漲，跌破均價線平倉 | YES | **主觀畫線偏誤**：形態收斂邊界缺乏統計精確度。 |
| **C_004** | 《100張圖》p.64 | 宏捷科 (8086) | LONG | 均價線回測 | 早盤衝高後拉回至 VWAP 量縮有守，再出量買進 | 尾盤獲利平倉或跌破 VWAP 停損 | YES | **洗盤風險**：震盪市容易反覆停損。 |
| **C_005** | 《100張圖》p.102 | 國巨 (2327) | LONG | 被動元件主流飆漲 | 族群共振，早盤 09:05 帶量突破早盤高點 | 漲停板前一檔獲利全出 | YES | **後見之明**：歷史大行情時任何買點皆賺錢。 |
| **C_006** | 《100張圖》p.140 | 華新科 (2492) | LONG | 試單加碼實例 | 開盤敲第一筆，拉開成本敲第二筆，破高敲第三筆 | 盤中未跌破成本線，抱至尾盤獲利 | YES | **順水推舟偏誤**：忽略逆勢時加碼快速爆倉之慘劇。 |
| **C_007** | 《智富》p.134 | 友達 (2409) | LONG | 詹大樓層突破 | 日K密集價位13.5元突破，由天花板轉為地板 | 上漲至下一樓層14.2元天花板平倉 | PARTIAL | **人工畫線偏誤**：樓層帶缺乏量化定義。 |
| **C_008** | 《智富》p.142 | 群創 (3481) | SHORT | 詹大樓層跌破 | 股價跌破近期密集支撐地板，空單進場 | 回補於下一樓層地板 | PARTIAL | **同上**。 |
| **C_009** | 《智富》p.156 | 台指期 | LONG | 零克連台指期 | 摩台/電子期同步強勢，5分K KD黃金交叉且MACD轉紅 | 5分K KD死亡交叉平倉 | YES | **指標滯後偏誤**：極短線KD與MACD極易被反向巴頭。 |
| **C_010** | 《智富》p.170 | 大立光期 (IJ) | LONG | 林昇線條式 | 台指期委買口數差暴增 + 股期走勢強於大盤 | 台指期口數差轉折或跌破布林中軌 | YES | **流動性限制**：股期大單容易無對手盤。 |
| **C_011** | 《智富》p.186 | TPK-KY (3673) | SHORT | 權證小哥自營比 | 前日權證自營比買超達14%，股期開盤走弱放空 | 09:12 急跌爆量回補平倉 | YES | **極具量化價值**：微觀結構避險機制具有實質經濟學意義。 |
| **C_012** | 《智富》p.192 | 美律 (2439) | SHORT | 權證小哥自營比 | 自營比>10%，早盤現貨與期貨跌破均價線放空 | 09:15 滿足點平倉 | YES | **同上**。 |
| **C_013** | 《手機當沖》A-27 | 康友-KY (6452) | SHORT | 五檔大單假防守 | 委買掛700張大買單，被連續主動大賣單摜破追空 | 下跌4個Tick快速平倉 | YES | **延遲風險**：人工手機操作可能成功，量化需極低延遲。 |
| **C_014** | 《手機當沖》A-29 | 奇鋐 (3017) | LONG | 族群連動跟進 | 散熱龍頭雙鴻帶量噴漲停，奇鋐在3分鐘內跟進做多 | 奇鋐補漲2%遇賣壓平倉 | YES | **連動失敗風險**：若龍頭炸板，跟隨股率先崩跌。 |
| **C_015** | 《手機當沖》A-31 | 宏達電 (2498) | LONG | 拉回不破前低 | 強勢股急拉後橫盤回檔，不破起漲點且買檔墊高 | 再次創高爆量平倉 | YES | **形態識別偏誤**：橫盤與起漲點需精準演算法定義。 |
| **C_016** | 《手機當沖》A-33 | 玉晶光 (3406) | SHORT | 漲停未鎖回跌 | 觸及漲停板數次打開，隨後回跌超過2%追空 | 跌至VWAP均價線平倉 | YES | **極高推廣性**：多殺多踩踏流動性具有高度統計顯著性。 |
| **C_017** | 《手機當沖》A-41 | 國巨 (2327) | EXIT | 嚴格3-Tick停損 | 買進後未如預期上攻，反向跌破2個Tick手動砍倉 | 避免後續連續重挫5%的大虧損 | YES | **執法成本**：頻繁停損對交易手續費侵蝕極大。 |
| **C_018** | 《手機當沖》A-45 | 帳戶熔斷 | RISK | 達到每日虧損上限 | 兩筆交易虧損達2,000元（本金2萬），強制關機離場 | 當日停止交易，避免非理性凹單破產 | YES | **純帳務邏輯**，100%可系統化。 |

---

# 09_CROSS_BOOK_CONSENSUS

透過三本書橫向交叉比對，萃取出核心交易法則之共識與歧異：

### 1. 三本書完全一致的共識（High Research Priority）
1. **嚴格禁止虧損加碼（攤平）**：三位作者皆視向下攤平為當沖毀滅之源。停損必須果斷，絕不心存僥倖。
2. **極度重視日內平均成本線（VWAP）與開盤價**：無論是會長、智富達人還是 Jasper，均視 VWAP 與開盤價為日內多空分水嶺，站上偏多、跌破偏空。
3. **早盤黃金時段聚焦（09:00～10:00）**：全天當沖成交量與動能 70% 集中於開盤前一小時，是勝率最高、流動性最充沛的區間。
4. **流動性至上**：絕對不交易無量冷門股，必須具備大成交量或大成交口數作為安全進出後盾。

### 2. 兩本書共同出現的概念（Medium Research Priority）
1. **族群連動效應（Jasper vs 會長）**：兩者皆強調不要單打獨鬥，個股發動必須有同族群或整體類股氣勢背書。
2. **衍生品跨市場與避險連動（智富 vs Jasper）**：台指期口數差、摩台期、權證自營商避險對股票現貨與股期具有先行引導力量。
3. **日K大週期趨勢定多空（會長 vs 詹大）**：當沖雖為日內交易，但順著日K多頭排列或關鍵樓層突破方向操作，勝率遠高於逆勢抄底摸頂。

### 3. 僅單一書籍提出的獨特概念（Hypothesis Generation）
1. **權證自營商 Delta 避險隔日沖拋售（僅《智富》權證小哥）**：具有極高結構確定性之量化造市商微觀機制。
2. **完全拋棄K線、純看五檔與明細（僅《手機當沖》Jasper）**：極端微觀結構視角，視K棒為落後產物。
3. **日K多方標準型態與均線糾結翻揚架構（僅《100張圖》會長）**：經典日線幾何形態選股池。

### 4. 三本書互相衝突的概念（Contradiction Analysis）
| 爭議概念 | 書籍 A 觀點 | 書籍 B / C 觀點 | 量化研究員客觀分析 |
| :--- | :--- | :--- | :--- |
| **做多 vs 做空** | **會長**：強烈主張「只做多、不做空」，認為放空風險無限且空方常有軋空斷頭危險。 | **小哥 / Jasper**：多空雙向靈活操作，認為弱勢股下殺速度更快，利潤更為乾脆。 | 會長的主張源自個人心理偏好與散戶恐懼；客觀量化回測必須**多空對稱檢驗**，台股日內跌勢往往伴隨多殺多踩踏，下行速度常高於上行。 |
| **看指標 vs 純看盤口** | **零克連 / 林昇**：高度依賴技術指標（KD、MACD、布林通道）與均線計算。 | **Jasper**：嚴禁看指標與5分K，認為指標必然嚴重落後，只看 L2 委託簿與逐筆成交。 | 技術指標在分鐘級別確實存在平滑延遲（Lagging）；但在高頻環境下，純人工盤口容易受假單誘騙。量化系統應以「指標定區間/狀態，盤口定精確觸發」。 |
| **追高 vs 買拉回** | **會長**：「追高不是錯，追錯不砍才是錯」，敢於在創高出量時第一時間市價追進。 | **Jasper**：嚴禁追高在第一根長紅，主張衝高後拉回不破前低才准進場。 | 取決於市場 Regime：在強趨勢主升段，追突破 MFE 極大；在震盪盤中，追突破極易遭受假突破反手巴頭，買拉回具有較佳之夏普比率（Sharpe Ratio）。 |

---

# TOP_RESEARCH_CANDIDATES

從所有規則中，篩選出 5 個最值得優先投入歷史真實 Tick / L2 資料進行回測的**核心研究假說**。此處為嚴謹量化研究規格：

---

### 候選假說 1：權證自營商避險倒貨之次日早盤反向動能假說（Warrant Delta Hedging Imbalance）
* **假說核心邏輯**：
  前一日權證主力大買認購權證造成自營商現貨避險買超佔比 $>10\%$ 之股票，次日開盤（09:00～09:15）因權證主力平倉，自營商在現貨市場被動拋售對沖部位，產生持續性外生賣壓（Exogenous Selling Pressure），造成現貨與股期顯著負向超額報酬。
* **所需資料規格**：
  1. 盤後證交所三大法人買賣超資料（需細分自營商「自行買賣」與「避險」）。
  2. 盤後券商分點權證進出明細（計算認購權證 Delta 曝險總值）。
  3. 股票期貨與股票現貨之 1-Tick 及 5-Second 撮合明細與五檔資料。
* **量化特徵與進場條件**：
  * **篩選門檻**：
    $$\text{Dealer\_Ratio}_{t-1} = \frac{\text{Dealer\_Hedge\_Amount}_{t-1}}{\text{Total\_Turnover}_{t-1}} \ge 0.10$$
  * **開盤過濾**：開盤價漲跌幅 $|Gap\_pct| \le 2.0\%$，股期買賣價差 $< 0.5\%$。
  * **進場觸發**：09:00 開盤後第 1 分鐘，若 $Price_t < VWAP_t$ 且主動賣單比例 $> 60\%$，進場放空股票期貨。
* **避免 Look-ahead Bias 機制**：
  自營商買賣超資料需嚴格限定於 $t-1$ 日下午 17:30 證交所公開發布數據，不得使用任何盤中預估值。
* **Forward Return 檢驗週期**：
  記錄進場後 **1m, 3m, 5m, 10m, 15m, 30m** 之前向收益率。
* **MFE / MAE 記錄規格**：
  記錄進場至 09:15 區間內的 Maximum Favorable Excursion（下殺最大幅度）與 Maximum Adverse Excursion（向上反抽最大幅度），以評估固定停損/停利檔位之最佳參數分佈。
* **市場狀態分割維度（Market Regimes）**：
  * **行情維度**：牛市 vs 熊市 vs 震盪市（熊市下自營商倒貨效果顯著增強）。
  * **時段劃分**：嚴格限定早盤（09:00～09:15），09:20 後因避險單出清效應遞減，應停止放空。

---

### 候選假說 2：多方標準型態日K共振之早盤突破與VWAP支撐假說（Multi-timeframe Trend & VWAP Breakout）
* **假說核心邏輯**：
  日線級別呈現標準多頭排列且距離歷史/波段前高 $<10\%$ 之股票，在日內早盤帶量突破前高後，回測日內 VWAP 具備強大的多方支撐動能，為兼具趨勢強度與進場防守依據的做多策略。
* **所需資料規格**：
  1. 歷史還原日線 OHLCV（至少 250 天計算 60MA 季線斜率）。
  2. 盤中 1分K OHLCV 與即時 Tick 累積計算之即時 VWAP。
* **量化特徵與進場條件**：
  * **日線過濾**：$MA5 > MA10 > MA20$ 且 $\text{Slope}(MA60, 5) > 0$，收盤距前 20 日最高收盤價 $< 10\%$。
  * **突破條件**：09:00～09:30 間，價格突破昨日高點，且早盤 5 分鐘成交量超過前 20 日同期均量 2 倍。
  * **拉回進場**：首波衝高後拉回，價格回測 $|Price_t - VWAP_t| / VWAP_t \le 0.3\%$ 且不跌破 VWAP，隨後出現外盤大單敲進時做多。
* **避免 Look-ahead Bias 機制**：
  日線指標僅能使用截至昨日（$t-1$）收盤確認之數據；日內 VWAP 僅能使用開盤至當下 $t$ 時間點之累積量價。
* **Forward Return 檢驗週期**：
  記錄進場後 **5m, 10m, 30m, 60m, EOD（收盤平倉）** 之報酬率。
* **MFE / MAE 記錄規格**：
  以進場點為基準，記錄至收盤前之 MFE 與 MAE，特別檢驗「回測 VWAP 時的下潛深度（Slippage into VWAP）」。
* **市場狀態分割維度（Market Regimes）**：
  * **大盤環境**：加權指數當日為多頭（大盤在自身 VWAP 之上）vs 空頭（大盤在 VWAP 之下）。
  * **波動度劃分**：高 ATR（前20%）vs 低 ATR 標的分組。

---

### 候選假說 3：弱勢股反彈高不過高與盤口委賣增厚壓制假說（Orderbook Resistance & Exhaustion Short）
* **假說核心邏輯**：
  開盤弱勢（開低走低且在 VWAP 之下）的股票，盤中反彈若無法越過早盤第一波高點，且五檔報價中賣盤顯著增厚（OBI 呈現負向傾斜），代表多頭反彈無力，是做空勝率極高的順勢放空點。
* **所需資料規格**：
  1. 盤中逐筆成交（Trade）資料與 Level 2 五檔委託快照（Snapshot 每 100ms 一筆）。
  2. 日內 1分K 資料。
* **量化特徵與進場條件**：
  * **弱勢定義**：開盤跌破前日收盤價，且開盤前 15 分鐘均價處於 VWAP 之下。
  * **反彈衰竭**：價格出現反彈波，反彈高點 $High_{rebound} < High_{morning}$，且反彈段之總成交量小於起跌段之 50%。
  * **盤口壓制**：反彈至高點停滯時，加權 $OBI \le -0.35$ 且外盤主動成交量驟降（Aggressive Buy Decay）。
* **避免 Look-ahead Bias 機制**：
  早盤高點與反彈高點必須依賴流動因果之「鋸齒轉折演算法（ZigZag Algorithm, 僅使用過去 Tick 確認轉折）」，嚴禁使用未來已知高點。
* **Forward Return 檢驗週期**：
  記錄進場後 **3m, 5m, 10m, 30m** 報酬率。
* **MFE / MAE 記錄規格**：
  記錄放空後向上反抽（MAE）是否會觸及前波反彈高點，並計算停損設定為前高 +1 Tick 時的盈虧比。
* **市場狀態分割維度（Market Regimes）**：
  * **大盤狀態**：大盤早盤同步開高走低 vs 大盤反彈拉抬。
  * **時段劃分**：中盤（09:30～10:30）效應最為顯著。

---

### 候選假說 4：同族群高Beta龍頭發動之遲滯配對動能跟隨假說（Intraday Cross-Asset Sector Momentum Spillover）
* **假說核心邏輯**：
  市場資金聚焦於特定族群時，一線龍頭股的大買單通常由法人或主力巨單發動；一般演算法與散戶在 1～3 分鐘內會尋找同族群二線標的進行補漲套利，產生具有可預測性的遲滯溢出動能（Lagged Momentum）。
* **所需資料規格**：
  1. 盤前細產業族群分類對應表（同一產業鏈定義）。
  2. 全市場全時段逐筆行情資料（同頻率同步計算）。
* **量化特徵與進場條件**：
  * **龍頭發動條件**：龍頭股 $A$ 於 3 分鐘內累計報酬率 $\ge 2.5\%$ 且成交量 $\ge 3 \times \overline{Vol_{20m}}$，或觸及漲停板。
  * **跟隨股篩選**：同族群跟隨股 $B$ 此時報酬率 $< 1.0\%$，且過去 20 日與 $A$ 之高頻報酬相關係數 $\rho(A, B) \ge 0.65$。
  * **進場觸發**：$A$ 爆發後 30 秒至 180 秒內，$B$ 出現第一筆單量大於 50 萬之外盤主動大單時做多 $B$。
  * **失效條件**：進場後 180 秒內 $B$ 未出現漲幅擴大，強制平倉退場。
* **避免 Look-ahead Bias 機制**：
  族群相關性矩陣 $\rho$ 必須基於前 $t-1$ 日之歷史數據計算，不得使用當日全天數據進行盤後相關性擬合。
* **Forward Return 檢驗週期**：
  記錄進場後 **1m, 3m, 5m, 10m** 報酬率（此為超短線溢價，預期超額收益在 5 分鐘內收斂）。
* **MFE / MAE 記錄規格**：
  記錄 5 分鐘內 $B$ 的最大爆發幅度（MFE）與回檔幅度（MAE）。
* **市場狀態分割維度（Market Regimes）**：
  * **族群熱度維度**：族群總成交金額佔全市場比例（熱門主流族群連動性極高，冷門族群連動性趨近於零）。
  * **時段劃分**：早盤（09:05～10:00）vs 尾盤（12:30～13:00）。

---

### 候選假說 5：漲停未鎖回跌大於2%之流動性踩踏放空/禁止做多假說（Limit-Up Failure Breakdown）
* **假說核心邏輯**：
  盤中觸及或逼近漲停板（$+9.0\%$ 以上）的股票，若隨後未能封死並快速回跌超過 2%，代表多頭鎖板動能完全瓦解，早盤追高與隔日沖大戶的多單將面臨停損賣壓，引發多殺多流動性踩踏。
* **所需資料規格**：
  1. 盤中逐筆成交明細與漲跌停價格表。
  2. L2 漲停價位委買排隊量變更歷史。
* **量化特徵與進場條件**：
  * **事件觸發條件**：
    $$\max_{\tau \le t}(Price_{\tau}) \ge LimitUp\_Price - 2 \text{ ticks}$$
    $$Price_t \le \max_{\tau \le t}(Price_{\tau}) \times 0.98$$
  * **交易動作**：
    1. **硬性過濾器（Filter）**：觸發後當天將該股列入「絕對禁止做多黑名單」。
    2. **放空假說（Short Trigger）**：自高點跌破 2% 且成交量伴隨放大時，以市價放空，回補點設在當日 VWAP 或回跌 5% 處。
* **避免 Look-ahead Bias 機制**：
  當日最高價為滾動累計計算，跌破 2% 之門檻為即時觸價判定。
* **Forward Return 檢驗週期**：
  記錄觸發後 **5m, 10m, 30m, 60m, EOD** 報酬率。
* **MFE / MAE 記錄規格**：
  記錄放空後向上反抽幅度（MAE）與下殺深度（MFE）。
* **市場狀態分割維度（Market Regimes）**：
  * **行情維度**：牛市 vs 熊市（牛市強行重新封漲停機率高，需極嚴格停損；熊市或震盪市中踩踏下殺極強）。
  * **時段劃分**：早盤（09:30～10:30）衝高失敗 vs 中尾盤（11:30～13:00）炸板。

---

### 研究總結報告備註
本候選知識庫已排除過時法規與手續費制度（例如早期台股當沖千分之三交易稅或券商人工喊單測試），並嚴格恪守純模擬交易邊界。本報告不含任何程式實作，亦不直接修改 EasyStock 當前實時運行之策略引擎，純粹以客觀、量化之獨立研究員標準，產出完整且可直接對接高頻回測框架的台股當沖量化假說資產。