# easystock v0.70 Research 部署檢查表

1. 覆蓋 repo 內所有同名檔案，尤其：
   - `index.html`
   - `update_market.py`
   - `backfill_fugle.py`
   - `.github/workflows/update.yml`
   - `.github/workflows/backfill-fugle-history.yml`
   - `requirements.txt`
   - `tests/test_parsers.py`

2. GitHub Secrets 保留 / 確認：
   - `FIREBASE_DATABASE_URL`
   - `FIREBASE_SERVICE_ACCOUNT_JSON`
   - `FUGLE_API_KEY`

3. 先執行：
   - Actions → `Historical Research Backfill (Fugle)`
   - 第一次建議先選 `3 years`、`500 symbols`。
   - 若結果穩定且想跨更多市場循環，再重跑 `5 years`。

4. 歷史補檔完成後 workflow 會自動刷新分數與 rolling-forward 驗證。

5. 再執行一次：
   - Actions → `Daily Stock Data Update`

6. 網站確認：
   - 個股曲線約 250 根日 K。
   - 「模型回測驗證」顯示 rolling-forward 驗證窗。
   - 有 1D / 5D / 10D / 20D、Profit Factor、盈虧比、最大回撤、Sharpe、benchmark、超額報酬。
   - 有多頭 / 盤整 / 空頭分解與分數分層。

## 四區塊建議模式

- 均線回踩轉強：10D，多頭 / 震盪回升；優先看中位數、Profit Factor、回撤。
- 日線短線動能：1D，僅研究用；真正短線需 5/15 分 K，成本後報酬必須為正才值得繼續。
- 強勢波段主升：10–20D，多頭；優先看超額報酬、Profit Factor、90+ 分層與最大回撤。
- 穩健長期核心：季頻 / 3–12M；以基本面、估值、股利、負債與穩定度為主，不以 1D/10D 回測做核心判斷。
