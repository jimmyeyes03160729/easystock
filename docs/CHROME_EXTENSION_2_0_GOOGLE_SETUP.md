# Chrome Extension 2.0 — Google 登入與 Firebase 設定（Owner 手動操作指南）

> 狀態：程式已完成並通過 Mock 測試；**真實 Google 登入尚未驗證**，目前為 `BLOCKED_BY_OAUTH_CONFIGURATION`。
> 完成本文件第 1–7 步並把兩個公開值交給開發者後，才能做 LIVE 驗收；第 8 步（Rules）需 Owner 確認後才發布。

## 先看：哪些可以給開發者、哪些絕對不能

| 可以提供（公開識別碼，可放進 Repository） | 絕對不能貼到程式碼、Issue、聊天或 Repository |
| --- | --- |
| Firebase 專案 ID（`easystock-c237a`） | Google 帳號密碼 |
| Firebase **Web API Key**（`AIza…`，用來識別專案，不是密碼） | OAuth **Client Secret**（Chrome 擴充功能類型本來就沒有） |
| Chrome 擴充功能類型 **OAuth Client ID**（`…apps.googleusercontent.com`） | Firebase / GCP **服務帳戶 JSON（私鑰）** |
| Chrome Web Store **Item ID**、商店頁「Public key」 | Firebase Database Secret（舊式）、任何 Refresh Token |
| 測試帳號的 Email（只用於加入測試使用者名單） | 券商帳號、API Key、憑證 |

開發者拿到 Web API Key 與 OAuth Client ID 後，只需填入 `chrome-extension/auth-config.json` 的 `firebase_api_key`、`oauth_client_id` 並重新 `pnpm build`；build 會自動把 `oauth2` 寫進 `dist/production/manifest.json`。

---

## 1. 確認 Firebase 正式專案 ID

- 網址：https://console.firebase.google.com/project/easystock-c237a/settings/general
- Console：專案設定 → 一般
- 要確認：
  - 專案 ID = `easystock-c237a`（若不同，立即告知開發者，不要另建第二個專案）。
  - Realtime Database URL = `https://easystock-c237a-default-rtdb.firebaseio.com`（Build → Realtime Database 頁面頂端）。
  - 方案仍為 **Spark**（不需要升級 Blaze 才能使用 Google 登入）。
- 取得 **Web API Key**：同一頁「您的應用程式」。若沒有 Web 應用程式，按「</>」新增一個（名稱例如 `easystock-chrome`，**不要**勾 Hosting），畫面上的 `apiKey` 即為 Web API Key。
- 可提供給開發者：專案 ID、Web API Key。
- 完成確認：開發者把 Key 填入後，擴充功能設定頁的「Google 帳號同步」不再顯示「缺少 firebase_api_key」。

## 2. 開啟 Firebase Authentication 的 Google 登入

- 網址：https://console.firebase.google.com/project/easystock-c237a/authentication/providers
- Console：Build → Authentication → Sign-in method → 新增供應商 → **Google** → 啟用
- 要填：專案的公開名稱（例如「當沖吧！牛馬仔」）、支援電子郵件。
- 授權網域：Authentication → 設定 → 授權網域，按官方 Chrome 擴充功能文件加入
  `chrome-extension://khidbieahmnnandhkcmjceideljgjfid`（`localhost` 預設已存在，請保留）。
- 若第 4 步的 OAuth Client 不在 `easystock-c237a` 這個 GCP 專案：在 Google 供應商設定的「將外部專案的用戶端 ID 加入許可清單」貼上該 Client ID。
- 完成確認：Sign-in method 清單中 Google 顯示「已啟用」。

## 3. 設定 Google OAuth 品牌／同意畫面

- 網址：https://console.cloud.google.com/auth/branding?project=easystock-c237a
- Console：Google Auth Platform → 品牌（Branding）／目標對象（Audience）／資料存取（Data access）
- 要填：
  - 應用程式名稱：當沖吧！牛馬仔
  - 使用者支援電子郵件、開發人員聯絡電子郵件
  - 應用程式首頁：`https://jimmyeyes.com/easystock`
  - 隱私權政策連結：已發布的 `privacy.html`（2.0 版內容）網址，例如 `https://jimmyeyes.com/easystock/privacy.html`（請以實際可公開開啟的網址為準）
  - 授權網域：`jimmyeyes.com`
  - 目標對象：外部（External）
  - 資料存取（Scopes）：只加 `openid`、`.../auth/userinfo.email`、`.../auth/userinfo.profile`（皆為非敏感範圍）
- 不要加入任何敏感或受限範圍（Gmail、Drive 等）。
- 完成確認：品牌頁顯示上述資訊；Data access 只有三個範圍。

## 4. 建立「Chrome 擴充功能」類型的 OAuth Client

- 網址：https://console.cloud.google.com/auth/clients?project=easystock-c237a
- Console：Google Auth Platform → 用戶端（Clients）→ 建立用戶端
- 要填：
  - 應用程式類型：**Chrome 擴充功能（Chrome extension）**
  - 名稱：`easystock-chrome-2.0`
  - 項目 ID（Item ID）：`khidbieahmnnandhkcmjceideljgjfid`
- 建立後會得到 Client ID（`數字-亂碼.apps.googleusercontent.com`）。此類型沒有 Client Secret；若畫面出現任何 secret，**不要**複製或提供。
- 可提供給開發者：Client ID。
- 完成確認：用戶端清單出現該 Client，類型為 Chrome 擴充功能，Item ID 正確。

## 5. 確認現有 Chrome Web Store Extension ID

- 網址：https://chrome.google.com/webstore/devconsole
- Console：選擇「當沖吧！牛馬仔」→ 套件（Package）
- 要確認：Item ID = `khidbieahmnnandhkcmjceideljgjfid`（OAuth Client 綁定此 ID；ID 不同登入一定失敗）。
- 本機測試用（選用）：同頁「公開金鑰（Public key）」可提供給開發者，填入 `auth-config.json` 的 `extension_public_key`。
  已填入：原始碼 `chrome-extension/manifest.json` 與 `dist/oauth-test` 都帶這把公開金鑰，以「載入未封裝項目」安裝任一資料夾，ID 都會與商店版相同，才能測真實登入（或以 `EASYSTOCK_PIN_KEY=1 pnpm build` 產生帶金鑰的 `dist/production`）。
  **上傳商店的 ZIP 不可含 `key`**（`package.mjs` 會檢查並拒絕）。
- 完成確認：未封裝測試版在 `chrome://extensions` 顯示的 ID 與商店版相同。

## 6. 取得並交付正確的 Client ID

- 把第 1 步的 Web API Key 與第 4 步的 Client ID 交給開發者（可放在私訊；兩者都是公開識別碼，但仍建議不要貼在公開 Issue）。
- 開發者會更新 `chrome-extension/auth-config.json` 並重新打包。
- 完成確認：設定頁「Google 帳號同步」按鈕可按，狀態從「待設定」變成「未登入」。

## 7. 設定測試使用者或發布狀態

- 網址：https://console.cloud.google.com/auth/audience?project=easystock-c237a
- 發布前：保持「測試中（Testing）」，在「測試使用者」加入要驗收的 Google 帳號（建議至少兩個，用於第 9 步跨帳號測試；上限 100 個）。
- 正式上架前：按「發布應用程式（In production）」。本擴充功能只用非敏感範圍，一般不需完整驗證，但 Google 可能要求品牌驗證（名稱、Logo、網域），請依 Console 指示完成。
- 完成確認：測試帳號可登入；非測試帳號在 Testing 狀態下會被拒絕（正常現象）。

## 8. 驗證並發布 Realtime Database Security Rules（需 Owner 確認後才執行）

目前線上規則已確認：未登入時讀取根目錄、`/users`、`/market_data`（淺層）都回 401（2026-10-16 實測），代表根目錄沒有被公開讀取。但現行規則**沒有** `users/{uid}`，所以同步在規則發布前會得到「雲端權限不足」，本機資料不受影響。

要新增的規則（Repository：`firebase.rules.json` 的 `users` 區塊）：

```json
"users": {
  "$uid": {
    ".read": "auth != null && auth.uid === $uid",
    ".write": "auth != null && auth.uid === $uid",
    "profile":   { ".validate": "newData.hasChildren(['schema', 'updatedAt']) && newData.child('schema').isNumber() && newData.child('updatedAt').isNumber()" },
    "watchlist": { "$symbol": { ".validate": "$symbol.matches(/^[0-9]{4,6}[A-Z]?$/) && newData.child('symbol').val() === $symbol && newData.child('updatedAt').isNumber()" } },
    "alerts":    { "$key": { ".validate": "newData.child('t').isNumber()" } },
    "settings":  { "$key": { ".validate": "newData.child('t').isNumber()" } },
    "groups":    { ".validate": "newData.hasChildren()" },
    "$other":    { ".validate": false }
  }
}
```

重要：Realtime Database 的 `.read/.write` 由上往下繼承，且**子節點無法撤銷父節點已給的權限**。只要根目錄或 `users` 有 `".read": true`，上面的規則就沒有保護作用。發布工具會先檢查這點。

建議作法（在持有服務帳戶的 VM 上執行，憑證不離開 VM）：

```bash
# 1) 乾跑：只讀目前規則，印出 current / candidate 摘要，不修改
python tools/firebase_rules.py --env-file .env --service-account <服務帳戶檔路徑> \
  --candidate firebase.rules.json --backup-dir ~/easystock-maintenance/firebase-rules --merge-users
# 2) 確認後套用：只「加入」users 區塊，其餘線上規則原封不動；先備份、套用後驗證，失敗自動回滾
python tools/firebase_rules.py ...同上... --merge-users --apply --expected-sha256 <步驟 1 的 current_rules_sha256>
```

- 套用後工具會驗證：原本公開的 `market_data` 節點仍可讀、私有節點仍不可讀、未登入讀 `/users` 為 401；任何一項失敗會自動回滾到備份。
- 手動回滾：把備份檔內容貼回 Firebase Console → Realtime Database → 規則，或以同一工具套用備份。
- 也可在 Console 的「規則」編輯器手動把 `users` 區塊加進現有規則（不要整份覆蓋），再用「規則模擬器」驗證：
  - 未驗證：讀 `/users/uidA` → 拒絕
  - 已驗證 UID=`uidA`：讀寫 `/users/uidA` → 允許；讀寫 `/users/uidB` → 拒絕
  - 已驗證：寫 `/market_data/public_feed` → 拒絕
- 對公開行情的影響：無。只新增 `users` 子樹，根目錄與 `market_data` 規則不變。
- 完成確認：設定頁按「同步」顯示「已同步」，Firebase Console 資料頁出現 `users/<UID>`。

## 9. 測試跨帳號資料隔離

使用兩個測試帳號（A、B），各自一個 Chrome 設定檔，或同一設定檔先後登入：

1. A 登入 → 新增 2330、1102 → 「已同步」。
2. 登出 → Chrome 切換為 B 帳號 → 登入擴充功能 → 列表只應出現 B 自己的股票，**不可**出現 A 的 2330、1102。
3. Firebase Console 檢查：`users/<A 的 UID>` 只有 A 的資料，`users/<B 的 UID>` 只有 B 的資料。
4. B 登出、A 再登入 → A 的清單回來。
5. 規則模擬器：以 A 的 UID 讀 `users/<B 的 UID>` → 拒絕。
- 完成確認：以上五點全部符合，回報開發者後才可把「T18/T20/T21/T30 LIVE」標為通過。

## 10. 上架前更新隱私權政策與 Chrome Web Store 隱私權做法

- 發布 2.0 版 `privacy.html`（本 Repository 已更新內容）到第 3 步填寫的公開網址。
- Chrome Web Store 開發人員資訊主頁 → 項目 → **隱私權做法（Privacy practices）**：
  - 單一用途：台股自選行情與指數觀察，選用的 Google 登入只用於同步自選股與設定。
  - 權限理由：
    - `identity`：使用者主動選擇 Google 登入以同步自選股與設定。
    - `storage`：本機保存自選股、提醒與偏好。
    - `alarms`：盤中定時更新指數與自選行情。
    - `notifications`：使用者開啟的量能觀察提醒。
    - 主機權限：只讀公開行情（TWSE MIS、Yahoo）、EasyStock 公開設定（GitHub）、Firebase 資料庫（公開行情與使用者自己的同步資料）。
  - 資料使用揭露：勾選「個人識別資訊」（Google 帳號 Email／名稱，用於登入顯示與帳號識別）；必要時勾選「驗證資訊」（登入期間的權杖，僅存於瀏覽器工作階段）。不勾選健康、財務付款、位置、網頁瀏覽記錄等。
  - 勾選三項認證：不出售資料、不用於與單一用途無關的目的、不用於信用評估。
  - 隱私權政策網址：第 3 步的 `privacy.html` 網址。
- 商店說明文字：已改為「台股行情觀察」，不宣稱 AI 選股或買賣建議；更改文案不代表已通過投資顧問法規審查。
- 完成確認：Privacy practices 頁無警示；送審前由 Owner 自行按下「提交審核」（開發者不會代為提交）。
