"""Unit tests for intraday day trading candidate filtering (ETF exclusion, price 30-200, volume >= 3000 lots)."""
import sys
import types
from pathlib import Path
from unittest.mock import patch, MagicMock

# Offline stubs for packages not installed in local regression test environment
for mod in ["shioaji", "firebase_admin", "firebase_admin.credentials", "firebase_admin.db"]:
    if mod not in sys.modules:
        m = types.ModuleType(mod)
        if mod == "shioaji":
            m.ScannerType = types.SimpleNamespace()
            m.TickType = types.SimpleNamespace()
        elif mod == "firebase_admin":
            m._apps = []
        elif mod == "firebase_admin.db":
            m.reference = lambda path: None
        sys.modules[mod] = m

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from intraday_live import is_etf, load_candidates_from_firebase


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


def test_load_candidates_from_firebase_applies_all_filters():
    mock_summary = {
        "s_ok1": {
            "symbol": "2303",
            "name": "聯電",
            "price": 133.5,
            "volume": 200_000_000,  # 200,000 lots
            "amount": 29_000_000_000,
            "amount_rank_pct": 0.99,
            "hot_rank": 1,
        },
        "s_ok2": {
            "symbol": "3231",
            "name": "緯創",
            "price": 176.0,
            "volume": 75_000_000,  # 75,000 lots
            "amount": 13_000_000_000,
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
            "price": 8.85,  # < 30
            "volume": 56_000_000,
            "amount": 500_000_000,
            "amount_rank_pct": 0.50,
            "hot_rank": 50,
        },
        "s_high_price": {
            "symbol": "3443",
            "name": "創意",
            "price": 1670.0,  # > 200
            "volume": 2_358_000,
            "amount": 18_000_000_000,
            "amount_rank_pct": 0.97,
            "hot_rank": 4,
        },
        "s_low_vol": {
            "symbol": "9999",
            "name": "量不足股",
            "price": 100.0,
            "volume": 1_000_000,  # 1,000 lots < 3,000 lots
            "amount": 100_000_000,
            "amount_rank_pct": 0.80,
            "hot_rank": 20,
        },
    }

    with patch("intraday_live.db.reference") as mock_ref:
        mock_ref.return_value.get.return_value = mock_summary
        candidates = load_candidates_from_firebase(max_symbols=10)

        symbols = [c["symbol"] for c in candidates]
        assert symbols == ["2303", "3231"]
        assert "0050" not in symbols
        assert "1314" not in symbols
        assert "3443" not in symbols
        assert "9999" not in symbols
