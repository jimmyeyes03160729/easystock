"""Runway V2: 獨立高勝率當沖動能跑道配置
完全獨立於生產環境與既有 AI 模型訓練，零干擾。
"""
import os
import sys
from pathlib import Path

# 可選環境變數載入 (支援 VM 生產環境與本地客製化，但在執行 pytest 測試時不載入生產 env 檔，維持測試基準不變)
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

# 開關
RUNWAY_V2_ENABLED = os.environ.get("RUNWAY_V2_ENABLED", "1").lower() in ("1", "true", "yes")

# 時間時窗（解鎖早盤黃金動能時段 09:05 ~ 09:30）
ENTRY_START_TIME = os.environ.get("RUNWAY_V2_ENTRY_START", "09:05:00")
ENTRY_CUTOFF_TIME = os.environ.get("RUNWAY_V2_ENTRY_CUTOFF", "09:30:00")  # 黃金進場窗限制 (避開盤中誘多)
FORCE_EXIT_TIME = os.environ.get("RUNWAY_V2_FORCE_EXIT", "12:55:00")

# 篩選條件
MIN_PRICE = float(os.environ.get("RUNWAY_V2_MIN_PRICE", "15.0"))
MAX_PRICE = float(os.environ.get("RUNWAY_V2_MAX_PRICE", "600.0"))
MIN_GAIN_PCT = float(os.environ.get("RUNWAY_V2_MIN_GAIN_PCT", "1.0"))  # 至少 1% 漲幅動能
MAX_GAIN_PCT = float(os.environ.get("RUNWAY_V2_MAX_GAIN_PCT", "7.5"))  # 放寬至 7.5%，避開已漲停追不到的

# 每日額度與風控熔斷 (100萬版本優化)
DAILY_MAX_BUY_AMOUNT = float(os.environ.get("RUNWAY_V2_DAILY_MAX_BUY", "1000000.0"))  # 每日買入成交額上限 100 萬
DAILY_MAX_LOSS_CIRCUIT_BREAKER = float(os.environ.get("RUNWAY_V2_DAILY_MAX_LOSS", "6000.0"))  # 當日已實現虧損達 6,000 元熔斷停止開倉

# 部位與出場風控
MAX_CONCURRENT_POSITIONS = int(os.environ.get("RUNWAY_V2_MAX_POSITIONS", "3"))
DEFAULT_POSITION_AMOUNT = float(os.environ.get("RUNWAY_V2_POS_AMOUNT", "300000.0"))  # 預設每檔 30 萬
STOP_LOSS_PCT = float(os.environ.get("RUNWAY_V2_STOP_LOSS_PCT", "0.015"))
TAKE_PROFIT_HALF_PCT = float(os.environ.get("RUNWAY_V2_TP_HALF_PCT", "0.015"))
TRAILING_TRIGGER_PCT = float(os.environ.get("RUNWAY_V2_TRAILING_TRIGGER_PCT", "0.020"))  # +2.0% 啟動移動停利
TRAILING_PULLBACK_PCT = float(os.environ.get("RUNWAY_V2_TRAILING_PULLBACK_PCT", "0.008"))  # 回檔 0.8% 出場

# 成本計算 (28折手續費 + 0.15% 當沖稅)
FEE_RATE = 0.001425 * 0.28
TAX_RATE = 0.0015
SLIPPAGE_RATE = 0.0005  # 滑價估計 0.05%

# 資料庫路徑 (本地 fallback，VM 為 /home/ubuntu/easystock-runway-v2/ledger_v2.sqlite)
_DEFAULT_DIR = Path(os.environ.get("RUNWAY_V2_DATA_DIR", "/home/ubuntu/easystock-runway-v2"))
if not _DEFAULT_DIR.exists() and not Path("/home/ubuntu").exists():
    _DEFAULT_DIR = Path(__file__).resolve().parent / "data"

DB_DIR = _DEFAULT_DIR
DB_PATH = DB_DIR / "ledger_v2.sqlite"

# 五檔 BidAsk 微結構風控
ORDERBOOK_ENABLED = os.environ.get("RUNWAY_V2_ORDERBOOK_ENABLED", "1").lower() in ("1", "true", "yes")
MAX_SPREAD_TICKS = int(os.environ.get("RUNWAY_V2_MAX_SPREAD_TICKS", "2"))        # 買一賣一跳檔差距不可超過 2 ticks
MAX_SPREAD_PCT = float(os.environ.get("RUNWAY_V2_MAX_SPREAD_PCT", "0.0060"))     # 價差比例上限 0.60% (防多跳檔滑價)
MIN_OBI_THRESHOLD = float(os.environ.get("RUNWAY_V2_MIN_OBI", "-0.40"))         # 委買賣量失衡度不得低於 -0.40 (防極端賣壓壓頂)
MIN_BID1_VOLUME = int(os.environ.get("RUNWAY_V2_MIN_BID1_VOL", "3"))            # 買一至少需有 3 張掛單承接
