# EasyStock Codex NAS 開發節點

本目錄為 EasyStock 在 Z2 Pro NAS 上的獨立 **Codex** 開發節點配置。

---

## 1. 架構定位與目標

在 Z2 Pro NAS 主機上，各服務容器保持高度隔離與獨立性：

```text
Z2 Pro (ARM64 / aarch64, 4GB RAM)
├─ easystock-lab           (研究與即時行情)
├─ easystock-scheduler     (排程引擎)
├─ easystock-antigravity   (Antigravity AI 開發節點)
└─ easystock-codex         (Codex AI 開發節點 - 本模組)
```

### 第一階段目標（Phase 1）
* **Codex CLI**：採用 OpenAI 官方獨立 Linux ARM64 二進位／安裝流程。
* **ChatGPT 登入持久化**：透過獨立 Docker named volume 保存 `~/.codex` 憑證與工作階段設定。
* **GitHub EasyStock 獨立 checkout**：使用獨立的 GitHub SSH Deploy Key，具備專屬 `/workspace/easystock` 工作目錄，不與 Antigravity 共用 working tree。
* **開發環境齊備**：內建 Python 3 (venv)、Node.js 22、pnpm 10 等開發與測試必備工具。

### 第一階段暫不進行（Out of Scope）
* Oracle VM SSH 連線與正式環境連動。
* VM 部署流程。
* Tailscale 網路配置。
* Codex Remote host registration（手機端 Remote 註冊）。
* OpenAI API key 注入（本階段僅使用 ChatGPT 帳號登入）。
* GitHub Actions 自動化部署流程。

---

## 2. 獨立性與安全規範

1. **容器完全獨立**：
   * 容器名稱為 `easystock-codex`。
   * 與現有的 `easystock-lab`、`easystock-scheduler`、`easystock-antigravity` 完全獨立，不互相依賴、不共用網路命名空間，亦不修改現有三個容器的任何配置。
2. **獨立 Persistent Volumes**：
   * `codex-home:/home/codex`：持久化存放 `~/.codex`（含 ChatGPT 登入 session、`auth.json`、`config.toml`、對話紀錄與設定）以及個人環境設定。
   * `codex-workspace:/workspace`：持久化存放獨立 clone 的 `/workspace/easystock`，嚴禁與 Antigravity 共用同一個 working tree。
3. **最小權限與安全邊界**：
   * 容器內全程以非 root 帳號 `codex`（UID 1000 / GID 1000）執行，停用 root 身分作業。
   * 設定 `security_opt: - no-new-privileges:true` 防止權限提升。
   * **嚴格禁止掛載**：
     * 禁止掛載 Docker socket (`/var/run/docker.sock`)。
     * 禁止開啟 `--privileged` 特權模式。
     * 禁止掛載 NAS 主機 `/data` 備份目錄。
     * 禁止掛載 Antigravity HOME (`agent-home`)。
     * 禁止掛載 Oracle VM SSH key、`easystock_nas_ed25519` 或任何備份敏感金鑰。
   * 本階段執行期僅允許以唯讀方式 (`read_only: true`) 掛載專用 GitHub SSH 憑證目錄至 `/run/github`。

---

## 3. 資源限制與 OOM 警語

> [!WARNING]
> **NAS 總記憶體限制警語**：
> Z2 Pro 主機總實體記憶體僅 **4GB**。
> 本容器在 Compose 中已設定資源上限：
> * `cpus: 2.0`
> * `mem_limit: 2g`
>
> **特別注意事項**：
> 請**切勿**同時讓 Antigravity 與 Codex 在 NAS 上執行大型 `pytest`、前端 build 或密集資料運算。
> 若主機出現記憶體不足（OOM）或系統卡頓，請先暫停其中一個 AI 容器：
> ```bash
> docker compose -f /path/to/easystock-antigravity/compose.yaml stop
> # 或
> docker compose -f /path/to/easystock-codex/compose.yaml stop
> ```

---

## 4. 首次部署步驟

### 步驟 1：建立專用 GitHub SSH 金鑰與指紋
在 NAS 主機端建立儲存憑證的目錄（避免與其他服務共用）：

```bash
mkdir -p /volume1/docker/easystock-codex/secrets/github
cd /volume1/docker/easystock-codex/secrets/github

# 產生專用的 ed25519 金鑰對（請勿設定密碼 passphrase）
ssh-keygen -t ed25519 -C "easystock-codex-nas" -f id_ed25519 -N ""

# 擷取 github.com 官方主機公鑰指紋
ssh-keyscan github.com > known_hosts

# 確保權限嚴格
chmod 600 id_ed25519
chmod 644 id_ed25519.pub known_hosts
```

將產生的公鑰內容（`id_ed25519.pub`）新增至 GitHub 倉庫：
* 進入 GitHub 專案 `jimmyeyes03160729/easystock` -> **Settings** -> **Deploy keys**。
* 點擊 **Add deploy key**，Title 輸入 `EasyStock-Codex-NAS`，貼上公鑰內容。若未來需由 Codex 節點直接 push，請勾選 **Allow write access**。

### 步驟 2：配置環境變數檔 `.env`
進入 NAS 上的部署目錄，從範例檔複製：

```bash
cd /volume1/docker/easystock-codex
cp compose.example.yaml compose.yaml
cp .env.example .env
```

編輯 `.env` 檔案，填入真實資訊：
```env
TZ=Asia/Taipei
GIT_AUTHOR_NAME=Jimmy
GIT_AUTHOR_EMAIL=your-github-email@example.com
GITHUB_AUTH_DIR=/volume1/docker/easystock-codex/secrets/github
```

### 步驟 3：構建映像檔並啟動容器

```bash
# 構建 ARM64 映像檔
docker compose build

# 啟動容器（常駐 safe idle 模式：sleep infinity）
docker compose up -d

# 查看容器啟動與 entrypoint 自動 clone 紀錄
docker compose logs -f
```

容器首次啟動時，`entrypoint.sh` 會安全地：
1. 驗證 `/run/github` 內之金鑰與 `known_hosts`。
2. 自動設定 `git config --global user.name` 與 `user.email`。
3. 自動將專案 clone 至 `/workspace/easystock`（單分支 `main`）。
4. 進入安全 idle 模式常駐，保留系統資源。

---

## 5. ChatGPT 第一次登入步驟（Headless NAS）

Codex CLI 支援透過終端機進行 ChatGPT 授權：

### 步驟 1：進入容器觸發登入
連線至 NAS SSH 後執行：

```bash
# 方式 A：進入互動式 Codex 介面
docker compose exec -it easystock-codex codex
# 在選單中選擇「Sign in with ChatGPT」

# 方式 B：直接使用 device 授權指令
docker compose exec -it easystock-codex codex login --device-auth
```

### 步驟 2：瀏覽器授權
終端機會顯示類似以下資訊：
```text
Open the following URL in your browser:
https://auth.openai.com/codex/device
Enter code: ABCD-EFGH
```
在你的電腦或手機瀏覽器開啟該網址，登入你的 ChatGPT 帳號並輸入授權碼完成驗證。

### 步驟 3：驗證登入狀態
在 NAS 終端機執行：
```bash
docker compose exec -it easystock-codex codex login status
```
驗證輸出應顯示已成功登入之帳號或驗證狀態。

### 持久化保證
授權資訊將存放在 `/home/codex/.codex/auth.json`。因為 `/home/codex` 掛載至 Docker named volume `codex-home`，容器重新啟動或重新建立映像檔後，登入狀態依然保持，無須重複登入。

---

## 6. 手動驗證流程

### 1. 系統環境與工具版本驗證
在 NAS 執行：
```bash
docker compose exec -it easystock-codex bash -c "\
  uname -m && \
  id && \
  echo HOME=\$HOME && \
  codex --version && \
  git --version && \
  python3 --version && \
  node --version && \
  pnpm --version"
```

**預期輸出**：
* 架構：`aarch64`
* 身分：`uid=1000(codex) gid=1000(codex) groups=1000(codex)`
* 家目錄：`HOME=/home/codex`
* Codex：`codex-cli 0.160.0`（或更新版本）
* Git、Python 3、Node 22、pnpm 10 皆正常回報版本號。

### 2. Git 專案狀態驗證
```bash
docker compose exec -it easystock-codex bash -c "\
  cd /workspace/easystock && \
  git status && \
  git remote -v && \
  git branch --show-current"
```

**預期輸出**：
* 當前分支為 `main`。
* Remote origin 指向 `git@github.com:jimmyeyes03160729/easystock.git`。
* 工作目錄狀態乾淨（clean）。

---

## 7. Codex 實際功能測試（Read-Only Task）

完成登入後，請進入專案目錄下達只讀檢驗任務，以驗證 Codex 能否正常讀取儲存庫並回答：

```bash
docker compose exec -it easystock-codex bash
cd /workspace/easystock
codex
```

在 Codex Prompt 中輸入：
> 「只讀檢查這個 repo，告訴我目前 branch、latest commit、git status，不要修改檔案。」

確認 Codex 能正確調用工具讀取專案狀態並完成回答，第一階段即宣告 PASS。

---

## 8. 第二階段預留規劃（Phase 2: Remote）

* **未來的延伸目標**：
  * 支援 ChatGPT Mobile App Remote Control 連線至此 NAS 節點：
    `ChatGPT mobile Remote -> Codex connected host -> Z2 Pro`
* **注意事項**：
  * 第一階段本 commit 嚴格**不**預先設定 Remote host。
  * 待第一階段實機環境、ChatGPT 登入持久化與 CLI 本地運行完全驗證通過後，再規劃第二階段之 Remote host 註冊與網路連通。
