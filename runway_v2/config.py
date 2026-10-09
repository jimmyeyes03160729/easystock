"""B1/B2/B3 跑道共用設定：環境檔、成本與資料目錄。"""
import os
import sys
from pathlib import Path

# 可選環境變數載入 (VM 生產環境；執行 pytest 時不載入，維持測試基準不變)
_ENV_FILE = Path(os.environ.get("RUNWAY_V2_ENV_FILE", "/home/ubuntu/easystock-ai-paper.env"))
if _ENV_FILE.exists() and "pytest" not in sys.modules:
    try:
        with open(_ENV_FILE, "r", encoding="utf-8") as _f:
            for _line in _f:
                _line = _line.strip()
                if _line and not _line.startswith("#") and "=" in _line:
                    _k, _v = _line.split("=", 1)
                    _k, _v = _k.strip(), _v.strip().strip("'\"")
                    if _k not in os.environ:
                        os.environ[_k] = _v
    except Exception:
        pass

# 成本計算 (28折手續費 + 0.15% 當沖稅)
FEE_RATE = 0.001425 * 0.28
TAX_RATE = 0.0015

# 資料目錄 (VM 為 /home/ubuntu/easystock-runway-v2，內含 lanes.sqlite 與 recordings)
_DEFAULT_DIR = Path(os.environ.get("RUNWAY_V2_DATA_DIR", "/home/ubuntu/easystock-runway-v2"))
if not _DEFAULT_DIR.exists() and not Path("/home/ubuntu").exists():
    _DEFAULT_DIR = Path(__file__).resolve().parent / "data"

DB_DIR = _DEFAULT_DIR
