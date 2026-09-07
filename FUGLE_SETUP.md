# Fugle 設定 — v1.1

## 1. GitHub Secret

Repository → Settings → Secrets and variables → Actions → New repository secret：

- Name: `FUGLE_API_KEY`
- Secret: 貼上 Fugle API Key

不要把 Key 放進 `index.html`、Python、README 或任何 commit。

## 2. Fugle 在 v1.1 的用途

- `backfill_fugle.py`：歷史日 K 回填
- `scan_intraday.py`：盤中 5 分 K 掃描；15 分 K 由程式本地聚合
- `update_market.py`：新進熱門股歷史不足時少量 bootstrap

## 3. GitHub Actions

### Historical Research Backfill (Fugle)

第一次部署或歷史不足時手動跑。

### Intraday & Overnight Picks

平日盤中自動跑，將結果寫入：

```text
/market_data/intraday_picks
```

若要先測試，可在 GitHub → Actions → `Intraday & Overnight Picks` 手動 Run workflow。

## 4. 注意

- 盤中掃描預設只挑約 30 檔高流動性候選，避免大量 API 呼叫。
- 只向 Fugle抓 5 分 K，15 分 K 本地聚合，降低額度消耗。
- GitHub Actions cron 可能有數分鐘延遲，不是券商級即時訊號。
- 歷史補檔使用未還原價，與 TWSE / TPEx 每日實際 OHLC 保持一致。
