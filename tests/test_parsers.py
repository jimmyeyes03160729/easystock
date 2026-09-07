import importlib.util
import sys
import types

# Parser tests do not touch Firebase; provide minimal stubs when firebase-admin is unavailable.
try:
    import firebase_admin  # noqa: F401
except ModuleNotFoundError:
    firebase_admin = types.ModuleType("firebase_admin")
    firebase_admin._apps = []
    credentials = types.ModuleType("firebase_admin.credentials")
    db = types.ModuleType("firebase_admin.db")
    credentials.Certificate = lambda payload: payload
    db.reference = lambda path: None
    firebase_admin.credentials = credentials
    firebase_admin.db = db
    sys.modules["firebase_admin"] = firebase_admin
    sys.modules["firebase_admin.credentials"] = credentials
    sys.modules["firebase_admin.db"] = db

from datetime import date
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "update_market.py"
spec = importlib.util.spec_from_file_location("update_market", MODULE_PATH)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def test_twse_quote():
    rows = [{
        "Date": "1150904", "Code": "2330", "Name": "台積電",
        "TradeVolume": "12,345", "TradeValue": "123,450,000",
        "OpeningPrice": "1000", "HighestPrice": "1010", "LowestPrice": "995", "ClosingPrice": "1005"
    }]
    q = m.parse_twse_quotes(rows)["2330"]
    assert q["date"] == "2026-09-04"
    assert q["volume"] == 12345
    assert q["amount"] == 123450000


def test_tpex_quote():
    rows = [{
        "Date": "1150904", "SecuritiesCompanyCode": "6488", "CompanyName": "環球晶",
        "Close": "500", "Open": "490", "High": "505", "Low": "488",
        "TradingShares": "100000", "TransactionAmount": "50000000"
    }]
    q = m.parse_tpex_quotes(rows)["6488"]
    assert q["exchange"] == "TPEx"
    assert q["close"] == 500


def test_valuation():
    twse = m.parse_valuation([{"Code": "2330", "PEratio": "25.1", "PBratio": "6.2", "DividendYield": "1.7"}], "TWSE")
    tpex = m.parse_valuation([{"SecuritiesCompanyCode": "6488", "PriceEarningRatio": "18.2", "PriceBookRatio": "2.1", "DividendYield": "3.0"}], "TPEx")
    assert twse["2330"]["pe"] == 25.1
    assert tpex["6488"]["pb"] == 2.1


def test_dividend_sum_and_continuity():
    rows = [
        {"公司代號":"2330", "股利年度":"115", "股利所屬期間":"1150101~1150331", "董事會（擬議）股利分派日":"1150510", "股東配發-盈餘分配之現金股利(元/股)":"5.0", "股東配發-資本公積發放之現金(元/股)":"0.5"},
        {"公司代號":"2330", "股利年度":"114", "股利所屬期間":"1141001~1141231", "董事會（擬議）股利分派日":"1150210", "股東配發-盈餘分配之現金股利(元/股)":"4.5"},
        {"公司代號":"2330", "股利年度":"113", "股利所屬期間":"113年度", "董事會（擬議）股利分派日":"1140301", "股東配發-盈餘分配之現金股利(元/股)":"4.0"},
    ]
    d = m.parse_dividends(rows, date(2026, 9, 4))["2330"]
    assert round(d["dividend_ttm"], 2) == 10.0
    assert d["dividend_continuity_years"] == 3


def test_financial_ratios():
    income = m.parse_income_statements([{
        "公司代號":"2330", "季別":"2", "營業收入":"1000", "營業毛利（毛損）":"500",
        "營業利益（損失）":"400", "本期淨利（淨損）歸屬於母公司業主":"300", "基本每股盈餘（元）":"10"
    }])
    balance = m.parse_balance_sheets([{
        "公司代號":"2330", "季別":"2", "資產總額":"5000", "負債總額":"2000", "權益總額":"3000"
    }])
    f = m.combine_fundamentals(income, balance)["2330"]
    assert f["gross_margin"] == 50.0
    assert f["operating_margin"] == 40.0
    assert f["debt_ratio"] == 40.0
    assert round(f["roe"], 2) == 20.0


def test_t86_and_history():
    payload = {
        "fields": ["證券代號", "外陸資買賣超股數(不含外資自營商)", "投信買賣超股數"],
        "data": [["2330", "1,000", "500"]]
    }
    assert m.parse_twse_t86(payload)["2330"] == 1500
    hist = m.merge_institution_history([{"time":"2026-09-03", "net_shares":100}], "2026-09-04", 1500)
    assert sum(x["net_shares"] for x in hist) == 1600


def test_kline_merge_dedupes_today():
    existing = [{"time":"2026-09-04", "open":99, "high":101, "low":98, "close":100, "volume":1000}]
    quote = {"date":"2026-09-04", "open":100, "high":103, "low":99, "close":102, "volume":2000, "amount":204000}
    k = m.merge_kline(existing, quote)
    assert len(k) == 1
    assert k[0]["close"] == 102


if __name__ == "__main__":
    tests = [v for k, v in globals().copy().items() if k.startswith("test_") and callable(v)]
    for test in tests:
        test()
        print("PASS", test.__name__)
    print(f"{len(tests)} parser tests passed")
