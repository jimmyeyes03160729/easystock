import math
import os
import re
import time
import threading
from functools import wraps
from datetime import datetime
from zoneinfo import ZoneInfo
from decimal import Decimal
from pathlib import Path

try:
    import shioaji as sj
except ModuleNotFoundError:
    sj = None

# 自動載入 .env
env_file = Path("/home/ubuntu/easystock/.env")
if env_file.exists():
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip("'\"")
            if k and k not in os.environ:
                os.environ[k] = v

CA_DEFAULT_PATH = os.environ.get("CA_PATH", "/home/ubuntu/easystock/cert/Sinopac.pfx")
LIVE_ORDERING_ENABLED = "LIVE_ORDERING_ENABLED"
LIVE_ORDERING_CONFIRMATION = "LIVE_ORDERING_CONFIRMATION"
LIVE_ORDERING_CONFIRMATION_VALUE = "I_UNDERSTAND_LIVE_ORDERING"
# 單筆委託上限：整張 499 張（交易所單筆上限）、零股 999 股，另有金額上限。
MAX_COMMON_LOTS = 499
MAX_ODD_SHARES = 999
MAX_NOTIONAL_TWD = float(os.environ.get("LIVE_ORDER_MAX_NOTIONAL_TWD", "1000000"))


def validate_order(symbol, action, price, quantity, is_odd_lot):
    """Normalize one limit order or raise ValueError; nothing is defaulted."""
    if not isinstance(symbol, str) or not re.fullmatch(r"[0-9]{4,6}[A-Z]?", symbol.strip()):
        raise ValueError("股票代號格式不正確。")
    if action not in ("BUY", "SELL"):
        raise ValueError("買賣方向必須是 BUY 或 SELL。")
    if not isinstance(is_odd_lot, bool):
        raise ValueError("請指定整張或零股。")
    if isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0:
        raise ValueError("委託價格必須是正數。")
    from paper_execution import tick_size
    if Decimal(str(price)) % tick_size(price):
        raise ValueError(f"委託價格不符合升降單位 {tick_size(price)} 元。")
    limit = MAX_ODD_SHARES if is_odd_lot else MAX_COMMON_LOTS
    if isinstance(quantity, bool) or not isinstance(quantity, int) or not 1 <= quantity <= limit:
        raise ValueError(f"委託數量須為 1 至 {limit} 的整數{'股' if is_odd_lot else '張'}。")
    notional = float(price) * quantity * (1 if is_odd_lot else 1000)
    if notional > MAX_NOTIONAL_TWD:
        raise ValueError(f"委託金額 {notional:,.0f} 元超過單筆上限 {MAX_NOTIONAL_TWD:,.0f} 元。")
    return {"symbol": symbol.strip(), "action": action, "price": float(price),
            "quantity": quantity, "is_odd_lot": is_odd_lot}


def mask(value, keep=4):
    text = str(value or "")
    return ("*" * len(text) if len(text) <= keep else "*" * (len(text)-keep) + text[-keep:]) if text else ""


def live_ordering_enabled() -> bool:
    """Require an explicit, two-factor environment switch for real orders.

    The application is paper-first.  Credentials alone must never make the
    admin endpoint capable of placing a broker order.
    """
    return (
        os.environ.get(LIVE_ORDERING_ENABLED, "").strip().lower() in {"1", "true", "yes"}
        and os.environ.get(LIVE_ORDERING_CONFIRMATION, "")
        == LIVE_ORDERING_CONFIRMATION_VALUE
    )


def synchronized(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        with self.console_lock:
            return method(self, *args, **kwargs)
    return call


class OrderService:
    def __init__(self):
        self.api = None
        self.is_logged_in = False
        self.account_info = {}
        self._last_login_time = 0
        self.console_lock = threading.RLock()

    @synchronized
    def login(self, force_new: bool = True):
        """Log in with the server's own credentials; browsers never supply keys."""
        if sj is None:
            raise RuntimeError("伺服器環境未安裝 shioaji 套件，無法連線永豐金證券 API")

        api_key = os.environ.get("SJ_API_KEY", "")
        secret_key = os.environ.get("SJ_SECRET_KEY", "")
        if not api_key or not secret_key:
            raise ValueError("伺服器未設定永豐 API Key 或 Secret Key")

        # 斷線後必須銷毀舊實例重新實例化 Shioaji，否則底層 SolClient C++ Session 無法復原
        if force_new or self.api is None:
            if self.api is not None:
                try:
                    self.api.logout()
                except Exception:
                    pass
            self.api = sj.Shioaji()

        try:
            self.api.login(api_key=api_key, secret_key=secret_key)
            acc = self.api.stock_account
            if acc:
                self.api.set_default_account(acc)

            # 等待底層 SolClient 完成連線交握
            time.sleep(1.8)

            self.is_logged_in = True
            self._last_login_time = time.time()
            self.account_info = {
                "person_name": getattr(acc, "person_name", "已連線用戶"),
                "person_id": getattr(acc, "person_id", "") or os.environ.get("PERSON_ID", ""),
                "account_id": getattr(acc, "account_id", ""),
                "broker_id": getattr(acc, "broker_id", ""),
            }
            return self.public_account()
        except Exception as e:
            self.is_logged_in = False
            self.api = None
            raise RuntimeError(f"永豐 API 登入失敗: {e}")

    def public_account(self):
        """Account summary safe to show in the browser; the ID number never leaves the server."""
        info = self.account_info
        return {"person_name": info.get("person_name", ""), "broker_id": info.get("broker_id", ""),
                "account_id": mask(info.get("account_id"))}

    def reconnect(self):
        """徹底銷毀舊連線並重新連線建立全新 Session"""
        return self.login(force_new=True)

    def ensure_ready(self):
        """確保 Shioaji API 已連線且可用（逾時自動重建實例）"""
        if sj is None:
            raise RuntimeError("伺服器環境未安裝 shioaji 套件，無法連線永豐金證券 API")
        if not self.is_logged_in or not self.api:
            self.login(force_new=True)
        elif time.time() - self._last_login_time > 600:
            # 超過 10 分鐘無操作，主動重建連線防 Solace 靜默斷線
            try:
                self.reconnect()
            except Exception:
                pass

    def _find_contract(self, symbol: str):
        sym = str(symbol).strip()
        roots = []
        if hasattr(self.api, "contracts"):
            roots.append(self.api.contracts)
        if hasattr(self.api, "Contracts"):
            roots.append(self.api.Contracts)

        for root in roots:
            for attr in ["stocks", "Stocks"]:
                store = getattr(root, attr, None)
                if store is None:
                    continue
                try:
                    target = store[sym]
                    if target:
                        return target
                except Exception:
                    pass
                for market in ["TSE", "OTC"]:
                    m_store = getattr(store, market, None)
                    if m_store is not None:
                        try:
                            target = m_store[sym]
                            if target:
                                return target
                        except Exception:
                            pass
        return None

    @synchronized
    def broker_snapshot(self):
        from .broker_read import snapshot
        return snapshot(self, sj)

    @synchronized
    def get_quote(self, symbol: str):
        self.ensure_ready()

        snapshots = None
        contract = None

        for attempt in range(2):
            try:
                contract = self._find_contract(symbol)
                if not contract:
                    # 重新連線獲取合約表
                    self.reconnect()
                    contract = self._find_contract(symbol)
                if not contract:
                    raise ValueError(f"查無此股票代號: {symbol}")

                snapshots = self.api.snapshots([contract])
                if snapshots:
                    break
            except Exception as e:
                err_str = str(e)
                # 若遇到 SessionNotEstablished 或 NotReady，自動重建實例再重試
                if ("SessionNotEstablished" in err_str or "NotReady" in err_str) and attempt == 0:
                    time.sleep(1.5)
                    try:
                        self.reconnect()
                    except Exception:
                        pass
                    continue
                raise RuntimeError(f"取得即時報價失敗: {err_str}")

        if not snapshots:
            raise ValueError(f"目前無法取得 {symbol} 即時行情快照（非交易時段或連線暫未就緒）")

        s = snapshots[0]
        close = float(getattr(s, "close", 0.0) or 0.0)
        chg_rate = float(getattr(s, "change_rate", 0.0) or 0.0)
        chg_price = float(getattr(s, "change_price", 0.0) or 0.0)

        def parse_levels(prices, vols):
            levels = []
            if isinstance(prices, (list, tuple)):
                vols = vols if isinstance(vols, (list, tuple)) else [1] * len(prices)
                for p, v in zip(prices, vols):
                    if p and float(p) > 0:
                        levels.append({"price": float(p), "volume": int(v)})
            elif isinstance(prices, (int, float)) and prices > 0:
                v = int(vols) if isinstance(vols, (int, float)) and vols > 0 else 1
                levels.append({"price": float(prices), "volume": v})
            return levels

        bids = parse_levels(getattr(s, "buy_price", None), getattr(s, "buy_volume", None))
        asks = parse_levels(getattr(s, "sell_price", None), getattr(s, "sell_volume", None))
        quote_at = None
        try:
            stamp = float(getattr(s, 'ts'))
            stamp /= 1e9 if stamp >= 1e17 else 1e6 if stamp >= 1e14 else 1e3 if stamp >= 1e11 else 1
            quote_at = datetime.fromtimestamp(stamp, ZoneInfo('Asia/Taipei')).isoformat()
        except (TypeError, ValueError, AttributeError, OverflowError, OSError):
            pass

        return {
            "symbol": symbol,
            "name": getattr(contract, "name", symbol),
            "close": close,
            "change_pct": round(chg_rate, 2),
            "change_price": round(chg_price, 2),
            "high": float(getattr(s, "high", close) or close),
            "low": float(getattr(s, "low", close) or close),
            "bids": bids,
            "asks": asks,
            "quote_at": quote_at,
        }

    @synchronized
    def place_order(self, symbol: str, action: str, price: float, quantity: int, is_odd_lot: bool, ca_passwd: str, before_submit=None):
        if not live_ordering_enabled():
            raise PermissionError(
                "真實下單入口目前已隔離；需由伺服器明確啟用 LIVE_ORDERING_ENABLED "
                "及 LIVE_ORDERING_CONFIRMATION 才能送出委託。"
            )
        order = validate_order(symbol, action, price, quantity, is_odd_lot)
        symbol, price, quantity = order["symbol"], order["price"], order["quantity"]
        self.ensure_ready()

        # The certificate location is server configuration, never request input.
        ca_path = CA_DEFAULT_PATH
        if not Path(ca_path).exists():
            raise FileNotFoundError(f"找不到憑證檔案: {ca_path}，請確認憑證已上傳至指定目錄")

        person_id = self.account_info.get("person_id") or os.environ.get("PERSON_ID", "")
        if not person_id:
            raise ValueError("尚未取得身分證字號，請先執行步驟 1 連線驗證或於環境變數配置 PERSON_ID")

        try:
            self.api.activate_ca(ca_path=ca_path, ca_passwd=ca_passwd, person_id=person_id)
        except Exception as e:
            raise RuntimeError(f"憑證簽章啟用失敗 (請核對憑證密碼或確認憑證有效性): {e}")

        trade = None
        last_exc = None

        # A broker submission exception is ambiguous: never retry a potentially accepted order.
        for attempt in range(1):
            try:
                contract = self._find_contract(symbol)
                if not contract:
                    self.reconnect()
                    contract = self._find_contract(symbol)
                if not contract:
                    raise ValueError(f"查無標的代號: {symbol}")

                act = sj.constant.Action.Buy if action == "BUY" else sj.constant.Action.Sell
                lot_type = getattr(sj.constant.StockOrderLot, "IntradayOdd", "IntradayOdd") if is_odd_lot else getattr(sj.constant.StockOrderLot, "Common", "Common")
                stock_order_type = getattr(sj.constant, "StockOrderType", None) or getattr(sj.constant, "StockOrderLot", None)
                rod_type = getattr(stock_order_type, "ROD", "ROD")

                order = self.api.Order(
                    price=float(price),
                    quantity=int(quantity),
                    action=act,
                    price_type=sj.constant.StockPriceType.LMT,
                    order_type=rod_type,
                    order_lot=lot_type,
                    account=self.api.stock_account
                )

                if before_submit is not None:
                    before_submit()
                if not live_ordering_enabled():
                    raise PermissionError('live_ordering_disabled')
                trade = self.api.place_order(contract, order)
                break
            except Exception as e:
                last_exc = e
                break

        if trade is None:
            err_msg = str(last_exc) if last_exc else "未知錯誤"
            if "doesn't have permission" in err_msg or "401" in err_msg:
                raise RuntimeError("永豐金證券回應權限不足 (401: Token doesn't have permission)。您的 API 金鑰尚未開通【下單交易權限】，請先向永豐證券營業員或於官網 Python API 專區申請開通下單權限。")
            if "SessionNotEstablished" in err_msg or "NotReady" in err_msg:
                raise RuntimeError("永豐交易通道連線尚未就緒 (Session Not Established)，非交易時段（盤後或休市）永豐下單伺服器通道不開放，請於交易日開盤時段 (08:30~13:30) 測試。")
            raise RuntimeError(f"委託送出失敗: {err_msg}")

        return {
            "order_id": getattr(getattr(trade, "order", None), "id", "已送出"),
            "status": str(getattr(getattr(trade, "status", None), "status", "SUBMITTED")),
            "symbol": symbol,
            "price": price,
            "quantity": quantity,
            "lot_type": "盤中零股" if is_odd_lot else "整張",
            "action": "買進" if action == "BUY" else "賣出"
        }


order_service = OrderService()

# 模組載入時若具備環境變數金鑰且已安裝 shioaji，自動預熱連線
if sj is not None:
    try:
        if os.environ.get("SJ_API_KEY") and os.environ.get("SJ_SECRET_KEY"):
            order_service.login()
    except Exception:
        pass
