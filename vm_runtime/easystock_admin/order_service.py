import os
import time
from pathlib import Path
import shioaji as sj

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


class OrderService:
    def __init__(self):
        self.api = None
        self.is_logged_in = False
        self.account_info = {}
        self._last_login_time = 0
        self._warmup_attempted = False

    def login(self, api_key: str = None, secret_key: str = None):
        api_key = api_key or os.environ.get("SJ_API_KEY", "")
        secret_key = secret_key or os.environ.get("SJ_SECRET_KEY", "")
        if not api_key or not secret_key:
            raise ValueError("缺少 API Key 或 Secret Key，請於環境變數或介面中填寫")

        if self.api is None:
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
            return self.account_info
        except Exception as e:
            self.is_logged_in = False
            raise RuntimeError(f"永豐 API 登入失敗: {e}")

    def ensure_ready(self):
        """確保 Shioaji API 已連線且可用（包含斷線重連機制）"""
        if not self.is_logged_in or not self.api:
            self.login()
        elif time.time() - self._last_login_time > 1800:
            try:
                self.login()
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

    def get_quote(self, symbol: str):
        self.ensure_ready()

        contract = self._find_contract(symbol)
        if not contract:
            try:
                self.login()
                contract = self._find_contract(symbol)
            except Exception:
                pass
            if not contract:
                raise ValueError(f"查無此股票代號: {symbol}")

        snapshots = None
        for attempt in range(2):
            try:
                snapshots = self.api.snapshots([contract])
                if snapshots:
                    break
            except Exception as e:
                err_str = str(e)
                if ("SessionNotEstablished" in err_str or "NotReady" in err_str) and attempt == 0:
                    time.sleep(2)
                    try:
                        self.login()
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
        }

    def place_order(self, symbol: str, action: str, price: float, quantity: int, is_odd_lot: bool, ca_passwd: str, ca_path: str = None):
        self.ensure_ready()

        ca_path = ca_path or CA_DEFAULT_PATH
        if not Path(ca_path).exists():
            raise FileNotFoundError(f"找不到憑證檔案: {ca_path}，請確認憑證已上傳至指定目錄")

        person_id = self.account_info.get("person_id") or os.environ.get("PERSON_ID", "")
        if not person_id:
            raise ValueError("尚未取得身分證字號，請先執行步驟 1 連線驗證或於環境變數配置 PERSON_ID")

        try:
            self.api.activate_ca(ca_path=ca_path, ca_passwd=ca_passwd, person_id=person_id)
        except Exception as e:
            raise RuntimeError(f"憑證簽章啟用失敗 (請核對憑證密碼或確認憑證有效性): {e}")

        contract = self._find_contract(symbol)
        if not contract:
            raise ValueError(f"查無標的代號: {symbol}")

        act = sj.constant.Action.Buy if action.upper() == "BUY" else sj.constant.Action.Sell
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

        trade = None
        last_exc = None
        for attempt in range(2):
            try:
                trade = self.api.place_order(contract, order)
                break
            except Exception as e:
                last_exc = e
                err_msg = str(e)
                if ("SessionNotEstablished" in err_msg or "NotReady" in err_msg) and attempt == 0:
                    time.sleep(2.5)
                    try:
                        self.login()
                        self.api.activate_ca(ca_path=ca_path, ca_passwd=ca_passwd, person_id=person_id)
                    except Exception:
                        pass
                    continue
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
            "action": "買進" if action.upper() == "BUY" else "賣出"
        }


order_service = OrderService()

# 模組載入時若具備環境變數金鑰，自動預熱連線
try:
    if os.environ.get("SJ_API_KEY") and os.environ.get("SJ_SECRET_KEY"):
        order_service.login()
except Exception:
    pass
