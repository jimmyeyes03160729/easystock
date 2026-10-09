# EasyStock Z2 Pro NAS 備份

此目錄提供部署檔案與排程範例；加入 repository 不會部署、建立 cron 或連線 VM。

## SQLite 來源與備份檔名

| VM 正式資料來源 | NAS snapshot 檔名 |
| --- | --- |
| `/home/ubuntu/easystock-learning-data/rebound/dataset.sqlite` | `rebound-dataset.sqlite` |
| `/home/ubuntu/easystock-learning-data/research.sqlite` | `research.sqlite` |
| `/home/ubuntu/easystock-learning-data/decisions.sqlite` | `decisions.sqlite` |
| `/home/ubuntu/easystock-admin/state.sqlite` | `admin-state.sqlite` |

四個路徑獨立設定，沒有共同 SQLite root 或遞迴搜尋。snapshot 使用 Python `sqlite3.Connection.backup()`，每個資料庫各自一致；四個資料庫不是同一筆跨庫交易時間點。

## 同步行為

NAS 使用 `/workspace/.ssh/easystock_nas_ed25519` 主動連線 `ubuntu@141.147.182.42`。先同步 learning-data 中非 SQLite 檔案，再於 VM 的 `/home/ubuntu/easystock-sync-snapshots/<timestamp>/` 產生 SQLite snapshot，最後拉回 `/data/backup/vm/sqlite/<timestamp>/` 並檢查全部 `PRAGMA integrity_check` 結果。

全部成功才以原子替換更新 `/data/backup/vm/LAST_SUCCESS`。同時只允許一個同步程序。rsync 不使用 `--delete`，不刪除 VM 原始資料，不操作交易服務。失敗會以非零狀態退出並保留 NAS 未完成 snapshot；learning-data 是累積同步目錄，失敗時可能已收到部分更新，不是整批原子 snapshot。

NAS 四個 SQLite 完成驗證並關閉連線後，會刪除本次 NAS snapshot 內的 `*.sqlite-wal`、`*.sqlite-shm`，再建立 `.complete`；完整 snapshot 只保留四個 `.sqlite` 與 `.complete`。

只有 rsync 成功、NAS 四個 integrity_check 全部通過且 `.complete` 建立後，才清除本次 VM 產生的 `/home/ubuntu/easystock-sync-snapshots/<timestamp>`。清除前核對固定根目錄、timestamp、非 symlink、來源 DB 不在刪除目錄內及檔案清單；不掃描或清除其他 timestamp，不刪正式來源 DB。失敗時保留已產生的 VM snapshot 供排查（含建立 snapshot 階段失敗）；清理失敗會以非零狀態退出且不更新 LAST_SUCCESS。歷史失敗留下的 snapshot 需另行排查，不會被後續成功工作自動刪除。

NAS timestamp 目錄保留 14 天，成功驗證後才清理超過 14 天的目錄。

## 日後部署到 NAS

需先確認 `/data` 為實際持久儲存掛載點。把此目錄放在 `/workspace/easystock/ops/nas`；Docker image 已安裝備份所需工具。只有直接在容器外執行腳本時，該環境才需要 Bash、OpenSSH client、rsync、Python 3、flock、mountpoint 與一般 Linux 工具。

```sh
cd /workspace/easystock/ops/nas
test -f nas.env || cp nas.env.example nas.env
chmod 600 nas.env /workspace/.ssh/easystock_nas_ed25519
chmod +x sync_from_vm.sh healthcheck.sh
bash -n sync_from_vm.sh healthcheck.sh docker-entrypoint.sh
```

先透過可信管道核對 VM SSH host key，再寫入 `/workspace/.ssh/known_hosts`。腳本強制驗證 host key，不自動接受新的 key。`nas.env` 是可執行的 shell 設定，請只使用可信且權限受控的檔案；它已被 gitignore 與 Docker build context 排除。repository 只包含私鑰路徑，私鑰檔必須保留在 NAS 外部掛載。

在允許連線及部署後才手動執行 `./healthcheck.sh` 與 `./sync_from_vm.sh`。healthcheck 檢查 SSH、持久儲存掛載、90% 容量門檻、EasyStock 基本環境及 LAST_SUCCESS；退出碼 0 表示正常、1 表示警告、2 表示失敗。

## Z2 Pro ARM64 Docker Compose 部署

Dockerfile 使用支援 ARM64 的 `debian:bookworm-slim`，安裝 Debian cron。獨立的 `easystock-scheduler` 在容器內以 `/usr/sbin/cron -f` 作為主程序，不依賴 ZOS 主機 cron；不修改既有 `easystock-lab` 的設定或用途。

使用能操作 NAS Docker 的終端或 ZOS Docker／Compose 管理介面部署，無需設定 ZOS 系統 cron，也無需為此開放 NAS SSH。`root@easystock-lab` 的終端若顯示 `docker: command not found`，不可直接執行下列 Docker 命令；請使用既有 Docker 管理入口，不修改 easystock-lab。Compose 的 bind mount 來源由 Docker daemon 解讀：若 `/workspace`、`/data` 只是 lab 容器內路徑，先在 ZOS 掛載設定查明 NAS 實際來源，在本機部署檔調整左側來源路徑，右側容器路徑保持不變。`./nas.env` 也必須放在 Docker 可存取的部署目錄。

確認 `/data` 是 4.6T HDD 的實際掛載點後，在可使用 Docker 的部署環境執行：

```sh
cd /workspace/easystock/ops/nas
git pull --ff-only origin main
docker --version
docker compose version
# 若已經有實機驗證過的 nas.env，保留原檔。
test -f nas.env || test -f nas.env || cp nas.env.example nas.env
chmod 600 nas.env /workspace/.ssh/easystock_nas_ed25519
mkdir -p /data/backup/vm
bash -n sync_from_vm.sh healthcheck.sh docker-entrypoint.sh
docker compose -p easystock-nas -f compose.example.yaml config
docker compose -p easystock-nas -f compose.example.yaml build easystock-scheduler
docker compose -p easystock-nas -f compose.example.yaml up -d --no-deps easystock-scheduler
```

此專案名稱與 `easystock-lab` 分開管理。私鑰與 known_hosts 所在的 `/workspace/.ssh`、`nas.env` 都以唯讀方式掛載；備份與日誌寫入 `/data/backup/vm` 的持久 bind mount。容器以 root 執行 cron，以讀取權限 600 的 key 與設定檔。

每天（含週末）Asia/Taipei 14:30 同步、14:45 執行備份 healthcheck。映像將 `/etc/localtime` 與 `/etc/timezone` 固定為 Asia/Taipei，Compose 與 cron 工作環境亦設定 `TZ=Asia/Taipei`。`/etc/cron.d/easystock-backup` 使用絕對路徑，並明確設定 `NAS_CONFIG=/config/nas.env`，不依賴 cron 繼承容器環境。

日誌包含標準輸出與錯誤輸出：

- `/data/backup/vm/sync.log`
- `/data/backup/vm/healthcheck.log`

`restart: unless-stopped` 讓容器異常退出或 NAS/Docker 重啟後自動恢復排程（需確保 Docker 開機啟動，且容器未被手動停止）。cron 設定內建於映像，容器重啟不會遺失；錯過的排程不補跑。保留 `sync_from_vm.sh` 既有 `/data/backup/vm/.sync.lock` 與 `flock -n`，避免排程及手動同步同時執行。只啟動一個 scheduler，不要搭配另一份 ZOS cron 或另一個 Compose 專案重複排程；若曾安裝舊備份排程，部署前移除該兩筆備份工作。

## 確認排程與維運

```sh
cd /workspace/easystock/ops/nas
docker compose -p easystock-nas -f compose.example.yaml ps easystock-scheduler
docker compose -p easystock-nas -f compose.example.yaml exec easystock-scheduler /usr/bin/pgrep -a -x cron
docker compose -p easystock-nas -f compose.example.yaml exec easystock-scheduler /bin/date --iso-8601=seconds
docker compose -p easystock-nas -f compose.example.yaml exec easystock-scheduler /bin/cat /etc/cron.d/easystock-backup
tail -n 100 /data/backup/vm/sync.log /data/backup/vm/healthcheck.log
cat /data/backup/vm/LAST_SUCCESS
```

Dockerfile HEALTHCHECK 每 30 秒確認 cron process 存活，以及 `/data/backup/vm` 可讀、可寫、可進入；不檢查交易日、VM 連線或備份新鮮度，因此週末不會因此被判為 unhealthy。`healthy` 只代表排程程序存活，備份是否成功仍以日誌與 LAST_SUCCESS 判斷。Docker 不會因 `unhealthy` 自動重啟容器，cron 主程序退出才由 restart policy 恢復。14:45 的 healthcheck 不等待 sync 完成，若同步耗時較長，請依 sync.log 與後續 LAST_SUCCESS 判讀。

啟動時 entrypoint 會檢查三個 runtime 掛載檔案、備份目錄與兩個日誌可 append，顯示 Asia/Taipei、帶 `+08:00` 的日期及完整 cron schedule，再以 `exec /usr/sbin/cron -f` 啟動。檢查失敗會退出並在 container log 顯示原因。私鑰與 nas.env 不會被 COPY 進 image。Debian base 沒有 Node 依賴，不會升級或影響 lab 的 Node 版本。

查看容器及啟動檢查：

```sh
docker ps
docker logs easystock-scheduler
docker inspect --format '{{.State.Health.Status}}' easystock-scheduler
tail -f /data/backup/vm/sync.log
# 另開終端查看第二份日誌：
tail -f /data/backup/vm/healthcheck.log
```

不用等到 14:30，即可手動執行 healthcheck（會連線 VM，但不啟動 cron）：

```sh
docker compose -p easystock-nas -f compose.example.yaml run --rm --no-deps easystock-scheduler /opt/easystock/ops/nas/healthcheck.sh
```

也可在已啟動的 scheduler 執行，將輸出 append 到排程日誌：

```sh
docker exec easystock-scheduler /bin/bash -c '/bin/bash /opt/easystock/ops/nas/healthcheck.sh >> /data/backup/vm/healthcheck.log 2>&1'
```

上述手動檢查使用相同 entrypoint 驗證掛載，但明確指定腳本時只執行該腳本，不會啟動第二個 cron。正式 scheduler 的 `container_name` 固定為 `easystock-scheduler`，無 depends_on，與 easystock-lab 互不依賴。

需要手動檢查或同步時，也可使用保留的一次性服務（停用 scheduler 專用 HEALTHCHECK）：

```sh
docker compose -p easystock-nas -f compose.example.yaml run --rm easystock-nas-backup /opt/easystock/ops/nas/healthcheck.sh
docker compose -p easystock-nas -f compose.example.yaml run --rm easystock-nas-backup /opt/easystock/ops/nas/sync_from_vm.sh
```

定期輪替兩份日誌。更新程式後重新 build 並 `up -d --no-deps easystock-scheduler`。此部署不使用 GitHub Actions，也不操作 Oracle VM 正式交易服務；同步仍僅依原腳本產生、拉回及清理本次備份 snapshot。

## 五檔委託簿（BidAsk）封存搬移

VM 實盤引擎每收到一筆五檔報價，就由 `market_data/bidask_archive.py` 以背景執行緒寫入
`/home/ubuntu/easystock-orderbook/raw/<日期>/bidask-<pid>.jsonl.gz`（不阻塞行情回呼；佇列滿時丟棄並計數）。
涵蓋範圍是跑道 B 訂閱五檔的股票（雷達前 30 名中被評估過的標的），不是全市場。

- VM 每天 06:30 執行 `python -m market_data.bidask_archive seal`：替前一個交易日以前的資料寫 `MANIFEST.json`（每檔 sha256、筆數、丟棄數）與 `COMPLETE`。
- NAS 每天 15:15 執行 `sync_orderbook.sh`：只拉回已封存的日期到 `/data/backup/orderbook/raw/<日期>/`，在 NAS 重新驗證每個檔案的 sha256，成功才寫 `.verified`，再請 VM 執行 `prune`。
- VM 的 `prune` 只刪除「已封存、manifest 雜湊與 NAS 一致、且至少 5 天前」的日期目錄；任何不符就保留。因此 VM 上最多保留約 5 天，其餘只在 NAS。
- 研究要模擬時，從 NAS 的 `/data/backup/orderbook/raw/` 讀取；需要在 VM 上跑時，用 rsync 把指定日期暫時推回 VM 的研究目錄，用完即刪。

部署：NAS 端重新 build `easystock-scheduler`（Dockerfile 已加入 `sync_orderbook.sh`，compose 多掛 `/data/backup/orderbook`）。
