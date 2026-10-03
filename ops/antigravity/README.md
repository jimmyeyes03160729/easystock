# EasyStock 獨立 Antigravity NAS 開發節點

第三個容器 `easystock-antigravity`，使用獨立 Compose project、network、home/workspace volumes。
不引用或修改 `easystock-lab`、`easystock-scheduler`；不掛載 NAS 備份、Docker socket、Oracle VM 金鑰或 SSH agent，不執行 VM 部署。
容器內使用 UID/GID 1000 的非 root `agent`，沒有 sudo、對外 port 或 privileged 模式。
這是程式開發節點，可由 Remote Control 指示 Git pull、修改、測試、commit/push main。
GitHub 寫入權限必須由使用者提供；不自動 push，也不在重啟時 pull/reset 或覆蓋未提交工作。

## 官方查核（2026-10-03）

- [官方 CLI 安裝與 SSH OAuth](https://antigravity.google/docs/cli/install/)：Linux 安裝入口為 `https://antigravity.google/cli/install.sh`；SSH 登入採 URL / 授權碼流程。
- 官方 installer 實際辨識 `aarch64/arm64`，選取 `linux_arm64` manifest 並驗證 SHA512。
- [官方 ARM64 manifest](https://antigravity-cli-auto-updater-974169037036.us-central1.run.app/manifests/linux_arm64.json) 查核版本為 **1.2.16**。Dockerfile 固定此 manifest 的下載 URL 與 SHA512，而非每次抓未知 latest。官方 tar 包含 `antigravity` executable，複製為 `agy`。
- [官方 Remote Control](https://antigravity.google/docs/remote-control/) 提供 `agy remote-control start --name ...`、`status`、`stop`；Linux 一般使用 systemd user service。
- [官方 changelog 1.2.14](https://github.com/google-antigravity/antigravity-cli/blob/main/CHANGELOG.md)：無 systemd 的容器會改用背景 process，`status` 顯示 PID，但不負責崩潰重啟。較早版本不適用本設計。
- 同一 changelog 記錄 headless / 無 D-Bus 時避開 OS keyring，改用檔案保存憑證。因此持久保存整個 HOME，沒有啟動 D-Bus 或假設有桌面 keyring。

`node:22-bookworm-slim` 支援 linux/arm64，採 Debian glibc；包含 Node 22、pnpm 10.18.3、Python 3.11 venv、git、SSH client、compiler / build tools。
此套件可執行 Python/Node 測試，但各專案依賴需另行安裝，不在容器啟動時執行套件腳本。
官方 CLI 可自行更新 HOME 下的執行檔；重建 image 不會覆蓋已保存的 CLI。升級前備份 volumes，升級後重新驗證 `status` PID 格式。
若要回到 image 的版本，停止容器後以 one-off shell 移除 HOME 中 `.local/bin/agy`，下次 entrypoint 會重新複製。

## Z2 Pro 實際部署（在 NAS SSH 終端操作）

前提：NAS 是 `aarch64`，可使用 Docker Engine / Compose v2，能連 GitHub 與 Google；帳號已開啟 Remote Control。4GB NAS 的範例限制此容器 2GB、2 CPU，測試 OOM 時應調整或拆分測試。

```bash
uname -m
docker compose version
git clone --branch main --single-branch https://github.com/jimmyeyes03160729/easystock.git easystock-agent-ops
cd easystock-agent-ops/ops/antigravity
cp .env.example .env
cp compose.example.yaml compose.yaml
```

如果已經有 checkout，用 `git pull --ff-only origin main` 更新後进入該 `ops/antigravity`。
編輯 `.env` 的 Git author name/email 與 `GITHUB_AUTH_DIR`。此路徑應是 repo 外的專用目錄，**只放 GitHub 憑證，不能放 VM key**。

### GitHub 認證（二選一）

SSH（預設）：建立專用 key，將 `.pub` 登錄成此 repo **允許寫入**的 GitHub deploy key，或專用帳號的 SSH key。

```bash
sudo mkdir -p /data/antigravity-github
sudo chown 1000:1000 /data/antigravity-github
sudo chmod 700 /data/antigravity-github
sudo -u '#1000' ssh-keygen -t ed25519 -N '' -f /data/antigravity-github/id_ed25519 -C easystock-antigravity
cat /data/antigravity-github/id_ed25519.pub
ssh-keyscan -t ed25519 github.com > /tmp/github-known-hosts
ssh-keygen -lf /tmp/github-known-hosts
```

**先比對 [GitHub 官方 SSH fingerprints](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints)**。
`ssh-keyscan` 本身不驗證伺服器身分。比對成功後才安裝：

```bash
sudo install -o 1000 -g 1000 -m 600 /tmp/github-known-hosts /data/antigravity-github/known_hosts
```

範例用無 passphrase 的專用 key 供背景工作；不要使用個人通用或 VM key。NAS 不支援上述 sudo 語法時，以管理者執行建立，再將所有權設成 UID/GID 1000。

Token：`.env` 設 `GITHUB_AUTH_MODE=token`；以文字編輯器在專用目錄建立 `token` 檔，內容只有單行 token（LF），權限 `600`、owner `1000:1000`。
使用只授權 `jimmyeyes03160729/easystock`、Contents read/write 的 fine-grained PAT；若需改 workflows，另行給必要權限。
不把 token 放 `.env`、clone URL、shell history 或 Docker build args。Credential helper 只對此 GitHub repo 回應、不保存 token，runtime 掛載為 read-only。

### 建置與第一次 Google 授權

首次先用 one-off 登入，不先啟動尚未授權的 daemon：

```bash
docker compose --env-file .env -f compose.yaml config --quiet
docker compose --env-file .env -f compose.yaml build --pull
docker compose --env-file .env -f compose.yaml run --rm easystock-antigravity login
```

entrypoint 第一次 clone main 到 `/workspace/easystock`，啟動 `agy` 並以 SSH 環境提示官方遠端 OAuth。
把終端顯示的授權 URL 開在自己電腦或手機瀏覽器，登入 Google，將完成後的授權碼貼回終端。
登入成功後 `/exit`。請勿將授權碼、token、HOME 備份貼到 GitHub。

```bash
docker compose --env-file .env -f compose.yaml up -d
docker compose --env-file .env -f compose.yaml logs --tail=100 -f
docker compose --env-file .env -f compose.yaml exec easystock-antigravity agy remote-control status
```

entrypoint 自動執行官方 `agy remote-control start --name EasyStock-NAS`。
看到 `Daemon status: active (background process, PID ...)` 和 supervisor 訊息後，到 [Remote Control Dashboard](https://antigravity.google.com/) 登入**同一個 Google 帳號**，選取 `EasyStock-NAS`，以 `/workspace/easystock` 為工作區。
不用額外手動啟動第二個 daemon。若帳號政策未開啟 Remote Control，登入成功也不代表 Remote Control 可用，依官方錯誤訊息處理。

## 開發與測試

```bash
docker compose --env-file .env -f compose.yaml exec -w /workspace/easystock easystock-antigravity bash
git status
git pull --ff-only origin main
python -m pip install -r requirements.txt pytest
pnpm install
pnpm test
python -m pytest tests
git diff --check
git diff
git add <明確要提交的檔案>
git commit -m 'fix: describe change'
git push origin main
```

依實際改動選擇 repo 測試；完整 Python suite 可能需要額外依賴、資料或服務。缺少正式環境 secret 的測試不可假裝通過。
不要同時讓多人/多個 agent 編輯同一 checkout。遇到遠端 main 前進，先處理工作區改動並更新 main，**不要 force push**。
Remote Control 仍遵循 CLI permissions；首次可用 `/permissions` 核准必要命令，沒有預設開啟 always-proceed。

## 常駐、故障與資料保存

Tini 作為 PID1 回收子程序並傳遞信號；entrypoint 啟動官方 daemon，再解析官方 status 的 PID。
PID 不存在或 daemon 結束時，entrypoint 以非零狀態退出，Docker `unless-stopped` 重啟。SIGTERM 執行官方 stop；沒有用 `tail -f /dev/null` 假裝服務正常。
PID 解析採 fail-closed；CLI 更新後若格式改變會退出並留下錯誤，不會把沒有 daemon 的容器當成已成功。
Healthcheck 只表示 process 還活著，**不表示 Google tunnel / 帳號 / 網路正常**。Docker 不會因 unhealthy 自動重啟；網路問題先看 CLI status 與 log，不要盲目重啟正在執行的任務。
NAS 重啟後由 Docker restart policy 恢復（需確認 NAS Docker 本身會開機啟動）。

- `easystock-antigravity_agent-home`：Google 登入/設定/歷史、CLI 執行檔、Git 設定、SSH 私鑰的私有副本。
- `easystock-antigravity_agent-workspace`：checkout 與未提交程式。
- Python venv 位於 image 的 `/opt/venv`；容器重建後需重裝 pip 依賴。可自行在 workspace 建立專案 `.venv` 以持久保存。
- 不要執行 `docker compose down -v`，那會刪除登入與工作區。HOME 也包含 secrets，備份須加密且限制存取。
- 移除 runtime key 不會撤銷已複製的 SSH key；撤銷請先停容器並在 GitHub 刪除 deploy key / revoke token，再清除 HOME 私有副本。

重新登入：先 `docker compose --env-file .env -f compose.yaml stop`，重跑 `run --rm easystock-antigravity login`，最後 `up -d`，避免登入與 daemon 同時改認證檔案。
若需要看 CLI logs，在容器內檢查 `$HOME/.gemini/antigravity-cli/log`；不要公開含認證資訊的 log。

## 第二階段受限 VM SSH（僅設計，未啟用）

未建立或掛載任何 VM key，也未提供可執行部署腳本。
未來另行批准後，VM 上建立專用 deploy 帳號及 root-owned `/home/ubuntu/bin/deploy_easystock.sh`，以 `authorized_keys` 的 `restrict,command="..."` 強制執行固定 wrapper（另限制來源網路）；禁止 interactive shell、port/agent/X11 forwarding 與 PTY。
wrapper 驗證指定 commit、乾淨 checkout 與允許的 main ref，拒絕任意 shell / 路徑 / ref 輸入。
只允許更新 EasyStock、必要測試、指定服務 restart、健康檢查及失敗回復；sudoers 精確列出單一服務操作，不授予任意 sudo/systemctl。
VM 必須先處理既有未提交變更與部署流程，再部署此設計；本階段不碰正式 VM。

## 驗證與部署驗收

本次提交前已通過：兩支 shell script 各自 `bash -n`、Docker Compose v2.39.4 的 SSH/token 設定解析、單一獨立 service / ARM64 / 三個隔離 mounts 的檢查、敏感路徑 `git check-ignore`、`git diff --check`。
以原始 entrypoint 的 supervisor 區段模擬官方 start/status/stop，確認 daemon 死亡回傳 exit 1、執行 stop cleanup、異常 status 無 PID 時 fail-closed。Credential helper 亦確認拒絕非 GitHub host。
官方 ARM64 tar 已下載並通過固定 SHA512，解包 binary 為 ELF64、machine 183 (AArch64)；Docker Hub 的 `node:22-bookworm-slim` index 確認包含 linux/arm64/v8。
執行驗證的 Windows 主機沒有 Docker Engine/WSL Linux：尚未進行 ARM64 image 實際建置、完整 runtime/OAuth/Remote Control 連線測試。以下為 NAS 端剩餘驗收步驟，不能視為已通過。

```bash
bash -n entrypoint.sh github-credential.sh
docker compose --env-file .env -f compose.yaml config --quiet
git check-ignore .env secrets/token credentials/id_ed25519 .gemini/config/config.json workspace/private
docker image inspect easystock-antigravity:1.2.16 --format '{{.Architecture}}'
docker compose --env-file .env -f compose.yaml exec easystock-antigravity bash -lc 'uname -m; agy --version; git --version; python --version; node --version; pnpm --version'
```

ARM64 binary SHA512 / ELF machine 與官方 image manifest 可以離線於 NAS 之外核對；**image 建置、真實 OAuth、Google 連線與重啟恢復必須在 NAS 驗收**。
完成登入後可在空閒時從容器內終止 status 顯示的 daemon PID，觀察 Docker restart count 增加並重新出現在 Dashboard；重啟 NAS 再確認相同工作區、Google 登入與未提交測試檔仍存在。
不要在 agent 正執行時做終止測試；重啟可恢復節點，但無法保證被中斷的任務會自動續跑。
