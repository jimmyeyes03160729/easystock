# LLM_CONSENSUS_PAPER_V1：AI 短線選股紙上測試

2026-10-10 凍結規則。只做紙上記錄，不下單。規則細節寫在 `llm_paper/run.py` 檔頭，之後不改，要改就開 V2。

## 流程
- **08:00（開盤日）** `easystock-llm-pick`：同一份提示詞（`llm_paper/prompt.txt`）同時問 ChatGPT、Claude（都開網路搜尋）。
  2026-10-10 第一批之前決定不用 Gemini（付費額度未開通）；要加回來就在 `.env` 設 `LLM_PAPER_PROVIDERS=openai,claude,gemini`，從加入那天起算新的比較。
  各取最多 5 檔有效的上市櫃普通股，名單、原始回覆、提示詞 sha256 存到 `/home/ubuntu/easystock-llm-paper/picks_YYYY-MM-DD.json`，
  並在 `picks.sha256` 記錄檔案雜湊。08:55 以後不再凍結；如果 09:00 以後才完成，該批作廢不計分。
- **01:50 / 08:20** `easystock-llm-feed`：用夜間日線算損益，寫 `llm-paper-latest.json`，發布到 `public_feed/llm_paper`。

## 計分
- T 日開盤買、第 5 個交易日收盤賣；開盤漲停買不到就留現金。扣手續費和證交稅，每組 100 萬平均分配。
- 組別：`openai`、`claude`、`consensus`（啟用的 AI 都選）、`majority2`（啟用三家以上才有）、
  對照組 `hot10`（前一日成交金額前 10）、`random5`（成交額 ≥ 5000 萬、股價 ≥ 10 元中固定亂數抽 5 檔）。
- 第二份提示詞 `p200`（`llm_paper/prompt_p200.txt`，本金 20 萬）：只收前一日收盤 ≤ 200 元的股票，超過的記為 invalid；
  組別加 `p200_` 前綴，`p200_hot10`、`p200_random5` 也只從 ≤ 200 元的股票挑。兩份提示詞同時跑，每天共 4 次 API 呼叫。
- 判讀：至少 40 個已結束批次後再看。`consensus` 要同時贏過 `hot10` 和 `random5`，而且每百萬平均損益扣成本後為正，才算有東西。

## 部署（VM）
1. 在 `/home/ubuntu/easystock/.env` 加入 `OPENAI_API_KEY=`、`ANTHROPIC_API_KEY=`（使用 Gemini 時另加 `GEMINI_API_KEY=`）。
   模型可用 `LLM_PAPER_OPENAI_MODEL`、`LLM_PAPER_ANTHROPIC_MODEL`、`LLM_PAPER_GEMINI_MODEL` 覆寫。
2. `bash deploy/install_llm_paper.sh`
3. 查看結果：`.venv/bin/python -m llm_paper.run report`
