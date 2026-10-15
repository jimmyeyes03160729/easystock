"""Unit tests for intraday day trading candidate filtering.

Separation of Concerns:
1. Universe / Scanner / load_candidates_from_firebase (資料採樣與盤後學習層):
   - 金額無上限、價格無上限（高價千金股如創意 3443 等皆保留供採樣與特徵學習）。
   - 扣除 ETF (00, 01, 02, 91 開頭、非4位代碼、ETF/ETN 關鍵字)。
2. Paper Trade Entry (模擬當沖開倉層):
   - 嚴格限制股價 30~200 元 (DAYTRADE_MIN_PRICE, DAYTRADE_MAX_PRICE)。
   - 嚴格限制成交張數 >= 3000 張 (DAYTRADE_MIN_LOTS)。
   - 嚴格排除 ETF (is_etf)。
"""
import sys
import types
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

# Only provide minimal stub for shioaji if not installed
try:
    import shioaji
except ImportError:
    shioaji = types.ModuleType("shioaji")
    shioaji.ScannerType = types.SimpleNamespace()
    shioaji.TickType = types.SimpleNamespace()
    sys.modules["shioaji"] = shioaji

# Only provide minimal stub for firebase_admin if not installed
try:
    import firebase_admin
    from firebase_admin import db
except ImportError:
    firebase_admin = types.ModuleType("firebase_admin")
    firebase_admin._apps = []
    db = types.ModuleType("firebase_admin.db")
    db.reference = lambda path: None
    firebase_admin.db = db
    sys.modules["firebase_admin"] = firebase_admin
    sys.modules["firebase_admin.db"] = db

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from intraday_live import is_etf, load_candidates_from_firebase
from market_data.a_candidates import candidate as a_candidate

TPE = timezone(timedelta(hours=8))


def test_is_etf_identifies_etf_and_non_standard_stocks():
    # ETFs starting with 00
    assert is_etf("0050", "元大台灣50") is True
    assert is_etf("0056", "元大高股息") is True
    assert is_etf("00878", "國泰永續高股息") is True
    assert is_etf("00919", "群益台灣精選高息") is True
    assert is_etf("00632R", "元大台灣50反1") is True
    assert is_etf("00679B", "元大美債20年") is True

    # TDR / Non-standard securities
    assert is_etf("9105", "泰金寶-DR") is True
    assert is_etf("010004", "特種證券") is True
    assert is_etf("ABC", "外國代碼") is True

    # Names with ETF keywords
    assert is_etf("1234", "某某ETF基金") is True
    assert is_etf("1234", "某某ETN") is True
    assert is_etf("1234", "境外指數基金") is True
    assert is_etf("1234", "台灣加權反1") is True
    assert is_etf("1234", "富邦期信") is True

    # Ordinary Taiwan common stocks
    assert is_etf("2330", "台積電") is False
    assert is_etf("2303", "聯電") is False
    assert is_etf("3231", "緯創") is False
    assert is_etf("2454", "聯發科") is False
    assert is_etf("6217", "中探針") is False
    assert is_etf("3443", "創意") is False


def test_universe_allows_unlimited_price_and_excludes_etf():
    """Universe 池金額與價格無上限，以採樣千金股進行盤後特徵學習；但扣除 ETF。"""
    mock_summary = {
        "s_ok1": {
            "symbol": "2303",
            "name": "聯電",
            "price": 133.5,
            "volume": 200_000_000,
            "amount": 29_000_000_000,
            "amount_rank_pct": 0.99,
            "hot_rank": 1,
        },
        "s_high_price": {
            "symbol": "3443",
            "name": "創意",
            "price": 1670.0,  # 高價千金股，價格無上限，應進入 Universe 供盤後特徵學習
            "volume": 2_358_000,
            "amount": 18_000_000_000,
            "amount_rank_pct": 0.98,
            "hot_rank": 2,
        },
        "s_etf": {
            "symbol": "0050",
            "name": "元大台灣50",
            "price": 180.0,
            "volume": 50_000_000,
            "amount": 9_000_000_000,
            "amount_rank_pct": 0.95,
            "hot_rank": 3,
        },
        "s_penny": {
            "symbol": "1314",
            "name": "中石化",
            "price": 8.85,
            "volume": 56_000_000,
            "amount": 500_000_000,
            "amount_rank_pct": 0.50,
            "hot_rank": 50,
        },
    }

    with patch("intraday_live.db.reference") as mock_ref:
        mock_ref.return_value.get.return_value = mock_summary
        candidates = load_candidates_from_firebase(max_symbols=10)

        symbols = [c["symbol"] for c in candidates]
        # 千金股 3443 必須被載入 Universe 以供盤後學習
        assert "3443" in symbols
        assert "2303" in symbols
        # ETF 0050 必須被排除
        assert "0050" not in symbols


def test_a_candidates_watchlist_excludes_etf():
    """A 候選推薦觀察名單嚴格排除 ETF。"""
    now = datetime(2026, 10, 16, 9, 30, 0, tzinfo=TPE)
    stock_etf = {"name": "元大台灣50", "previous_close": 178.0, "daytrade_eligibility": "Yes"}
    result_ok = {"daytrade_score": 85, "eligible": True, "reasons": ["突破"]}

    # ETF 0050 should return None
    item_etf = a_candidate(
        symbol="0050",
        stock=stock_etf,
        result=result_ok,
        price=180.0,
        now=now,
        quote_at=now,
        limits={"min_price": 30, "max_price": 200, "max_gain_pct": 5},
        market_pass=True,
        entry_window=True,
        mode="rules",
    )
    assert item_etf is None

    # 普通股 2303 應可通過
    stock_common = {"name": "聯電", "previous_close": 130.0, "daytrade_eligibility": "Yes"}
    item_common = a_candidate(
        symbol="2303",
        stock=stock_common,
        result=result_ok,
        price=133.0,
        now=now,
        quote_at=now,
        limits={"min_price": 30, "max_price": 200, "max_gain_pct": 5},
        market_pass=True,
        entry_window=True,
        mode="rules",
    )
    assert item_common is not None
    assert item_common["symbol"] == "2303"
