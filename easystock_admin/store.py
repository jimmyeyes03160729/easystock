"""Private local admin state; never stored in public Firebase."""
from contextlib import contextmanager, closing
import datetime
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import secrets
import sqlite3
import time

OWNER = os.environ.get('ADMIN_OWNER_EMAIL', '').strip().lower()
KEYS = ('min_price', 'max_price', 'max_gain_pct', 'max_recommendations')
LEGACY_KEYS = KEYS[:-1]
PIPELINE_DEFAULTS = {
    'history_target_symbols': 100, 'history_symbols': [], 'history_max_pairs': 5,
    'history_weekends': False, 'history_window_start': '14:00', 'history_window_end': '22:00',
    'learning_enabled': True, 'learning_time': '16:10', 'min_training_dates': 101,
    'min_training_samples': 1000, 'min_class_samples': 30, 'holdout_days': 20,
    'model_threshold': .6, 'fee_rate': .0015, 'minimum_fee_twd': 20,
    'sell_tax_rate': .003, 'slippage_bps': 10, 'shares': 1000,
    'model_retrain_every_days': 5, 'forward_observe_days': 20,
    'formal_candidate_for_live': False,
}

def db_path():
    return Path(os.environ.get('EASYSTOCK_ADMIN_DB', '/home/ubuntu/easystock-admin/state.sqlite'))

def digest(s):
    return hashlib.sha256(s.encode()).hexdigest()

def validate(value):
    if not isinstance(value, dict) or set(value) not in (set(KEYS), set(LEGACY_KEYS)):
        raise ValueError('只允許最低股價、最高股價、漲幅上限與推薦檔數上限。')
    value = {**value, 'max_recommendations': value.get('max_recommendations', 30)}
    result = {}
    for k, v in value.items():
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise ValueError('請填入有效數字。')
        if abs(v - round(v, 2)) > 1e-8:
            raise ValueError('最多填兩位小數。')
        result[k] = round(v, 2)
    if not .01 <= result['min_price'] <= result['max_price'] <= 1000000:
        raise ValueError('最低股價須大於0，且不得超過最高股價。')
    if not 0 <= result['max_gain_pct'] <= 100:
        raise ValueError('漲幅上限須介於0至100%。')
    if result['max_recommendations'] != int(result['max_recommendations']) or not 1 <= result['max_recommendations'] <= 30:
        raise ValueError('推薦檔數上限須為 1 至 30 的整數。')
    result['max_recommendations'] = int(result['max_recommendations'])
    return result

def defaults():
    from dotenv import dotenv_values
    values = dotenv_values('/home/ubuntu/easystock-learning.env')
    def get(key, fallback):
        return float(values.get(key) or os.environ.get(key, fallback))
    return validate({
        'min_price': get('DAYTRADE_MIN_PRICE', '1'),
        'max_price': get('DAYTRADE_MAX_PRICE', '1000000'),
        'max_gain_pct': get('DAYTRADE_MAX_GAIN_PCT', '5'),
        'max_recommendations': get('LIVE_RADAR_TOP_N', '30')
    })

def validate_pipeline(value):
    previous=set(PIPELINE_DEFAULTS)-{'model_retrain_every_days','forward_observe_days','formal_candidate_for_live'}
    if not isinstance(value, dict) or set(value) not in (set(PIPELINE_DEFAULTS),previous):
        raise ValueError('訓練與資料計畫欄位不正確。')
    result = {**PIPELINE_DEFAULTS,**value}
    symbols = result['history_symbols']
    if not isinstance(symbols, list) or len(symbols) > 200 or any(not isinstance(s, str) or not __import__('re').fullmatch(r'\d{4}', s) for s in symbols) or len(set(symbols)) != len(symbols):
        raise ValueError('指定股票請填入最多 200 個四位數代碼。')
    result['history_symbols'] = symbols
    for key, lo, hi in (('history_target_symbols', 1, 200), ('history_max_pairs', 1, 50), ('min_training_dates', 20, 1000), ('min_training_samples', 100, 1000000), ('min_class_samples', 10, 100000), ('holdout_days', 5, 250), ('shares', 1, 100000), ('model_retrain_every_days', 1, 20), ('forward_observe_days', 5, 60)):
        n = result[key]
        if isinstance(n, bool) or not isinstance(n, int) or not lo <= n <= hi: raise ValueError(f'{key} 超出安全範圍。')
    if result['min_class_samples'] * 2 > result['min_training_samples']: raise ValueError('正負樣本最低數量不可超過總樣本的一半。')
    if any(not isinstance(result[k],bool) for k in ('learning_enabled','history_weekends','formal_candidate_for_live')): raise ValueError('開關設定不正確。')
    for key in ('history_window_start', 'history_window_end', 'learning_time'):
        if not isinstance(result[key], str) or not __import__('re').fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', result[key]): raise ValueError('時間格式須為 HH:MM。')
    if result['history_window_start'] >= result['history_window_end']: raise ValueError('抓取開始時間須早於截止時間。')
    for key, lo, hi in (('model_threshold', .05, .95), ('fee_rate', 0, .01), ('minimum_fee_twd', 0, 10000), ('sell_tax_rate', 0, .01), ('slippage_bps', 0, 500)):
        n = result[key]
        if isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n) or not lo <= n <= hi: raise ValueError(f'{key} 超出安全範圍。')
        result[key] = float(n)
    return result

class Conflict(Exception): pass
class Denied(Exception): pass

class Store:
    def __init__(self, path=None, initial=None):
        self.path = Path(path or db_path())
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with closing(sqlite3.connect(self.path, timeout=5)) as db, db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''
            CREATE TABLE IF NOT EXISTS settings(id INTEGER PRIMARY KEY CHECK(id=1),body TEXT NOT NULL,version INTEGER NOT NULL,updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,csrf TEXT NOT NULL,expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS challenges(token TEXT PRIMARY KEY,nonce TEXT NOT NULL,expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS rate_limits(key TEXT PRIMARY KEY,start REAL NOT NULL,n INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,at REAL NOT NULL,actor TEXT NOT NULL,action TEXT NOT NULL,body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS paper_trade_settings(id INTEGER PRIMARY KEY CHECK(id=1),initial_capital REAL NOT NULL,current_capital REAL NOT NULL,status TEXT NOT NULL,start_date TEXT NOT NULL,updated_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS paper_trade_logs(date TEXT PRIMARY KEY,start_balance REAL NOT NULL,end_balance REAL NOT NULL,net_pnl REAL NOT NULL,symbols TEXT NOT NULL,costs REAL NOT NULL,trades_count INTEGER NOT NULL,created_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS paper_trade_positions(symbol TEXT PRIMARY KEY,name TEXT NOT NULL,entry_price REAL NOT NULL,shares INTEGER NOT NULL,entry_time TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS paper_trade_events(id INTEGER PRIMARY KEY AUTOINCREMENT,date TEXT NOT NULL,time_str TEXT NOT NULL,symbol TEXT NOT NULL,name TEXT NOT NULL,price REAL NOT NULL,action TEXT NOT NULL,reason TEXT NOT NULL,created_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS pipeline_settings(id INTEGER PRIMARY KEY CHECK(id=1),body TEXT NOT NULL,version INTEGER NOT NULL,updated REAL NOT NULL);
            ''')
            from .notifications import initialize as initialize_notifications
            initialize_notifications(db)
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT 1 FROM settings WHERE id=1').fetchone():
                db.execute('INSERT OR IGNORE INTO settings VALUES(1,?,1,?)', (json.dumps(validate(initial) if initial is not None else defaults()), time.time()))
            if not db.execute('SELECT 1 FROM pipeline_settings WHERE id=1').fetchone():
                db.execute('INSERT OR IGNORE INTO pipeline_settings VALUES(1,?,1,?)', (json.dumps(PIPELINE_DEFAULTS), time.time()))
            import paper_ledger
            paper_ledger.migrate(db)
        self.path.chmod(0o600)

    @contextmanager
    def tx(self):
        db = sqlite3.connect(self.path, timeout=5)
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _state(self, db):
        row = db.execute('SELECT body,version,updated FROM settings WHERE id=1').fetchone()
        return {'values': validate(json.loads(row[0])), 'version': row[1], 'updated_at': row[2]}

    def get(self):
        with self.tx() as db:
            return self._state(db)

    def _audit(self, db, actor, action, body):
        db.execute('INSERT INTO audit(at,actor,action,body) VALUES(?,?,?,?)', (time.time(), actor, action, json.dumps(body)))

    def update(self, value, version):
        value = validate(value)
        if isinstance(version, bool) or not isinstance(version, int):
            raise ValueError('缺少設定版本。')
        with self.tx() as db:
            before = self._state(db)
            if before['version'] != version:
                raise Conflict('設定已被更新，請重新載入後再修改。')
            db.execute('UPDATE settings SET body=?,version=version+1,updated=? WHERE id=1', (json.dumps(value), time.time()))
            self._audit(db, 'google', 'settings', {'before': before['values'], 'after': value})
            return self._state(db)

    def get_pipeline_settings(self):
        with self.tx() as db:
            row = db.execute('SELECT body,version,updated FROM pipeline_settings WHERE id=1').fetchone()
            return {'values': validate_pipeline(json.loads(row[0])), 'version': row[1], 'updated_at': row[2]}

    def update_pipeline_settings(self, value, version):
        value = validate_pipeline(value)
        if isinstance(version, bool) or not isinstance(version, int): raise ValueError('缺少設定版本。')
        with self.tx() as db:
            row = db.execute('SELECT body,version FROM pipeline_settings WHERE id=1').fetchone()
            if row[1] != version: raise Conflict('訓練與資料計畫已被更新，請重新載入。')
            previous = validate_pipeline(json.loads(row[0]))
            db.execute('UPDATE pipeline_settings SET body=?,version=version+1,updated=? WHERE id=1', (json.dumps(value), time.time()))
            self._audit(db, 'google', 'pipeline_settings', {'before': previous, 'after': value})
        return self.get_pipeline_settings()

    def get_paper_trade(self):
        import paper_ledger
        with closing(sqlite3.connect(self.path)) as db:
            exists = db.execute('SELECT 1 FROM paper_trade_settings WHERE id=1').fetchone()
        if not exists:
            return {'settings':paper_trade_defaults(),'positions':[],'events':[],'logs':[]}
        return paper_ledger.snapshot(self.path)

    def start_paper_trade(self, daily_buy_limit):
        if isinstance(daily_buy_limit, bool) or not isinstance(daily_buy_limit, (int, float)) or not math.isfinite(daily_buy_limit) or not 0 < daily_buy_limit <= 100000000:
            raise ValueError('請輸入大於 0 且不超過一億元的每日買進額度。')
        cap = round(float(daily_buy_limit), 2)
        if cap <= 0:
            raise ValueError('每日買進額度至少 0.01 元。')
        import paper_ledger
        today_str = paper_ledger.now().date().isoformat()
        with self.tx() as db:
            db.execute('''INSERT OR IGNORE INTO paper_trade_settings(id,initial_capital,current_capital,status,start_date,updated_at)
                          VALUES(1,?,?,'stopped',?,?)''',(cap,cap,today_str,time.time()))
            paper_ledger.migrate(db)
            pid=paper_ledger.period(db)
            if any(r['entry_date'] != today_str for r in paper_ledger.open_positions(db,pid)):
                raise ValueError('存在跨日未結部位；禁止啟動新交易，請先核對。')
            db.execute("UPDATE paper_trade_settings SET daily_buy_limit=?,status='running',updated_at=? WHERE id=1",(cap,time.time()))
            self._audit(db, 'google', 'paper_trade_start', {'daily_buy_limit': cap, 'semantics_version':paper_ledger.SEMANTICS})
        return self.get_paper_trade()

    def toggle_paper_trade(self):
        with self.tx() as db:
            row = db.execute('SELECT status FROM paper_trade_settings WHERE id=1').fetchone()
            current_status = row[0] if row else 'stopped'
            next_status = 'stopped' if current_status == 'running' else 'running'
            if not row:
                today_str = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).strftime('%Y-%m-%d')
                db.execute('''INSERT INTO paper_trade_settings(id, initial_capital, current_capital, status, start_date, updated_at)
                              VALUES(1, 100000.0, 100000.0, ?, ?, ?)''', (next_status, today_str, time.time()))
            import paper_ledger
            paper_ledger.migrate(db)
            if next_status == 'running' and any(r['entry_date'] != paper_ledger.now().date().isoformat() for r in paper_ledger.open_positions(db,paper_ledger.period(db))):
                raise ValueError('存在跨日未結部位；禁止啟動新交易。')
            db.execute('UPDATE paper_trade_settings SET status=?, updated_at=? WHERE id=1', (next_status, time.time()))
            self._audit(db, 'google', 'paper_trade_toggle', {'status': next_status})
        return self.get_paper_trade()

    def _limit(self, db, key, limit):
        now = time.time()
        row = db.execute('SELECT start,n FROM rate_limits WHERE key=?', (key,)).fetchone()
        if row and now - row[0] < 60:
            if row[1] >= limit:
                raise Denied('操作太頻繁，請稍後再試。')
            db.execute('UPDATE rate_limits SET n=n+1 WHERE key=?', (key,))
        else:
            db.execute('INSERT OR REPLACE INTO rate_limits VALUES(?,?,1)', (key, now))

    def challenge(self):
        cookie = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        with self.tx() as db:
            self._limit(db, 'google-challenge', 60)
            now = time.time()
            for table in ('sessions', 'challenges'):
                db.execute('DELETE FROM ' + table + ' WHERE expires<?', (now,))
            db.execute('DELETE FROM rate_limits WHERE start<?', (now - 86400,))
            db.execute('INSERT INTO challenges VALUES(?,?,?)', (digest(cookie), nonce, now + 300))
        return cookie, nonce

    def take_challenge(self, cookie):
        with self.tx() as db:
            key = digest(cookie)
            row = db.execute('SELECT nonce,expires FROM challenges WHERE token=?', (key,)).fetchone()
            db.execute('DELETE FROM challenges WHERE token=?', (key,))
        if not row or row[1] < time.time():
            raise Denied('登入驗證已過期，請重新登入。')
        return row[0]

    def login(self, claims, nonce):
        if not OWNER or claims.get('email', '').lower() != OWNER or claims.get('email_verified') is not True or not claims.get('sub'):
            raise Denied('此帳號沒有管理權限。')
        if not hmac.compare_digest(str(claims.get('nonce', '')), nonce):
            raise Denied('登入驗證不符。')
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        with self.tx() as db:
            sub = str(claims['sub'])
            old = db.execute("SELECT value FROM meta WHERE key='google_sub'").fetchone()
            if old and old[0] != sub:
                raise Denied('管理員身分不符。')
            db.execute("INSERT OR IGNORE INTO meta VALUES('google_sub',?)", (sub,))
            db.execute('INSERT INTO sessions VALUES(?,?,?)', (digest(token), csrf, time.time() + 8 * 3600))
            self._audit(db, 'google', 'login', {})
        return token, csrf

    def session(self, token):
        with self.tx() as db:
            row = db.execute('SELECT csrf,expires FROM sessions WHERE token=?', (digest(token),)).fetchone()
        if not row or row[1] < time.time():
            raise Denied('請先使用 Google 登入。')
        return row[0]

    def logout(self, token):
        with self.tx() as db:
            db.execute('DELETE FROM sessions WHERE token=?', (digest(token),))

def read_live_settings():
    path = db_path()
    uri = path.resolve().as_uri() + '?mode=ro'
    db = sqlite3.connect(uri, uri=True, timeout=1)
    try:
        row = db.execute('SELECT body FROM settings WHERE id=1').fetchone()
        if not row:
            raise RuntimeError('Admin settings missing')
        return validate(json.loads(row[0]))
    finally:
        db.close()


def read_pipeline_settings():
    """Read the plan from a worker without granting it write access to admin state."""
    path = db_path()
    uri = path.resolve().as_uri() + '?mode=ro'
    db = sqlite3.connect(uri, uri=True, timeout=1)
    try:
        row = db.execute('SELECT body FROM pipeline_settings WHERE id=1').fetchone()
        if not row:
            raise RuntimeError('Pipeline settings missing')
        return validate_pipeline(json.loads(row[0]))
    finally:
        db.close()


def paper_trade_defaults():
    return {'daily_buy_limit':100000.0,'daily_buy_used':0.0,'daily_buy_remaining':100000.0,
            'status':'stopped','start_date':'','performance_base':100000.0,
            'cumulative_net_pnl':0.0,'equity':100000.0,'net_pnl':0.0,'fees':0.0,'tax':0.0}


def read_paper_trade_settings():
    path = db_path()
    if not path.exists():
        return paper_trade_defaults()
    uri = path.resolve().as_uri() + '?mode=ro'
    db = sqlite3.connect(uri, uri=True, timeout=1)
    try:
        tbl = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='paper_trade_settings'").fetchone()
        if not tbl:
            return paper_trade_defaults()
        row = db.execute('SELECT 1 FROM paper_trade_settings WHERE id=1').fetchone()
        if not row:
            return paper_trade_defaults()
        import paper_ledger
        return paper_ledger.snapshot(path)['settings']
    finally:
        db.close()


def record_paper_trade_settlement(date_str, start_bal, end_bal, net_pnl, symbols_str, costs=0.0, trades_count=1):
    raise RuntimeError('Deprecated cash settlement; use paper_ledger.sell with a position identity')


def log_paper_trade_event(symbol: str, name: str, price: float, action: str, reason: str):
    path = db_path()
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
    today_str = now.strftime('%Y-%m-%d')
    time_str = now.strftime('%H:%M:%S')
    with closing(sqlite3.connect(path, timeout=5)) as db, db:
        db.execute('''
            INSERT INTO paper_trade_events(date, time_str, symbol, name, price, action, reason, created_at)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?)
        ''', (today_str, time_str, str(symbol), str(name), float(price), str(action), str(reason), time.time()))


def set_paper_position(symbol: str, name: str, price: float, shares: int):
    raise RuntimeError('Use paper_ledger.buy; positions require a corresponding BUY fill')


def clear_paper_position(symbol: str):
    raise RuntimeError('Use paper_ledger.sell; positions require a settlement receipt')


def get_paper_position(symbol: str) -> dict | None:
    path = db_path()
    with closing(sqlite3.connect(path, timeout=5)) as db:
        row = db.execute('SELECT symbol, name, entry_price, shares, entry_time FROM paper_trade_positions WHERE symbol=?', (str(symbol),)).fetchone()
        if row:
            return {'symbol': row[0], 'name': row[1], 'entry_price': float(row[2]), 'shares': int(row[3]), 'entry_time': row[4]}
        return None
