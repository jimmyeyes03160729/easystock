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

需先確認 `/data` 為實際持久儲存掛載點。把此目錄放在 `/workspace/easystock/ops/nas`，安裝 Bash、OpenSSH client、rsync、Python 3、flock、mountpoint 與一般 Linux 工具。

```sh
cd /workspace/easystock/ops/nas
cp nas.env.example nas.env
chmod 600 nas.env /workspace/.ssh/easystock_nas_ed25519
chmod +x sync_from_vm.sh healthcheck.sh
bash -n sync_from_vm.sh healthcheck.sh
```

先透過可信管道核對 VM SSH host key，再寫入 `/workspace/.ssh/known_hosts`。腳本強制驗證 host key，不自動接受新的 key。`nas.env` 是可執行的 shell 設定，請只使用可信且權限受控的檔案；它已被 gitignore 與 Docker build context 排除。repository 只包含私鑰路徑，私鑰檔必須保留在 NAS 外部掛載。

在允許連線及部署後才手動執行 `./healthcheck.sh` 與 `./sync_from_vm.sh`。healthcheck 檢查 SSH、持久儲存掛載、90% 容量門檻、EasyStock 基本環境及 LAST_SUCCESS；退出碼 0 表示正常、1 表示警告、2 表示失敗。

## Docker 範例

```sh
docker compose -f compose.example.yaml build
docker compose -f compose.example.yaml run --rm easystock-nas-backup /opt/easystock/ops/nas/healthcheck.sh
docker compose -f compose.example.yaml run --rm easystock-nas-backup /opt/easystock/ops/nas/sync_from_vm.sh
```

私鑰及 known_hosts 以唯讀方式掛載，nas.env 以唯讀方式掛载。容器使用 Asia/Taipei。只有 `/data/backup/vm` 掛載到容器；healthcheck 接受此獨立 bind mount。此服務是一次性工作，不會自行啟動 cron。

## 每日 14:30 Asia/Taipei（僅範例，未安裝）

NAS 系統及 cron daemon 的時區須設定為 Asia/Taipei；只設定工作環境 `TZ` 不保證所有 cron 實作以該時區觸發。每天（含週末）14:30 同步，14:45 檢查。部署時才將下列內容加到 NAS 排程：

```cron
TZ=Asia/Taipei
30 14 * * * /bin/bash /workspace/easystock/ops/nas/sync_from_vm.sh >> /data/backup/vm/sync.log 2>&1
45 14 * * * /bin/bash /workspace/easystock/ops/nas/healthcheck.sh >> /data/backup/vm/healthcheck.log 2>&1
```

若使用 Docker，把命令改成含絕對 `--project-directory /workspace/easystock/ops/nas` 與 `-f /workspace/easystock/ops/nas/compose.example.yaml` 的 `docker compose run --rm`。定期輪替日誌。沒有 GitHub Actions 部署流程。
