"""Private local admin state; never stored in public Firebase."""
from contextlib import contextmanager, closing
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import secrets
import sqlite3
import time

OWNER=os.environ.get('ADMIN_OWNER_EMAIL','').strip().lower()
KEYS=('min_price','max_price','max_gain_pct')

def db_path():
    return Path(os.environ.get('EASYSTOCK_ADMIN_DB','/home/ubuntu/easystock-admin/state.sqlite'))

def digest(s):return hashlib.sha256(s.encode()).hexdigest()

def validate(value):
    if not isinstance(value,dict) or set(value)!=set(KEYS):raise ValueError('只允許最低股價、最高股價與漲幅上限。')
    result={}
    for k,v in value.items():
        if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v):raise ValueError('請填入有效數字。')
        if abs(v-round(v,2))>1e-8:raise ValueError('最多填兩位小數。')
        result[k]=round(v,2)
    if not .01<=result['min_price']<=result['max_price']<=1000000:raise ValueError('最低股價須大於0，且不得超過最高股價。')
    if not 0<=result['max_gain_pct']<=100:raise ValueError('漲幅上限須介於0至100%。')
    return result

def defaults():
    from dotenv import dotenv_values
    values=dotenv_values('/home/ubuntu/easystock-learning.env')
    def get(key,fallback):return float(values.get(key) or os.environ.get(key,fallback))
    return validate({'min_price':get('DAYTRADE_MIN_PRICE','1'),'max_price':get('DAYTRADE_MAX_PRICE','1000000'),'max_gain_pct':get('DAYTRADE_MAX_GAIN_PCT','5')})

class Conflict(Exception):pass
class Denied(Exception):pass

class Store:
    def __init__(self,path=None,initial=None):
        self.path=Path(path or db_path())
        self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        with closing(sqlite3.connect(self.path,timeout=5)) as db, db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''
            CREATE TABLE IF NOT EXISTS settings(id INTEGER PRIMARY KEY CHECK(id=1),body TEXT NOT NULL,version INTEGER NOT NULL,updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,csrf TEXT NOT NULL,expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS challenges(token TEXT PRIMARY KEY,nonce TEXT NOT NULL,expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS binds(code TEXT PRIMARY KEY,expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS receipts(event TEXT PRIMARY KEY,body TEXT NOT NULL,created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS rate_limits(key TEXT PRIMARY KEY,start REAL NOT NULL,n INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,at REAL NOT NULL,actor TEXT NOT NULL,action TEXT NOT NULL,body TEXT NOT NULL);
            ''')
            if not db.execute('SELECT 1 FROM settings WHERE id=1').fetchone():
                db.execute('INSERT OR IGNORE INTO settings VALUES(1,?,1,?)',(json.dumps(validate(initial) if initial is not None else defaults()),time.time()))
        self.path.chmod(0o600)

    @contextmanager
    def tx(self):
        db=sqlite3.connect(self.path,timeout=5)
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except Exception:
            db.rollback();raise
        finally:db.close()

    def _state(self,db):
        row=db.execute('SELECT body,version,updated FROM settings WHERE id=1').fetchone()
        return {'values':validate(json.loads(row[0])),'version':row[1],'updated_at':row[2]}

    def get(self):
        with self.tx() as db:return self._state(db)

    def _audit(self,db,actor,action,body):
        db.execute('INSERT INTO audit(at,actor,action,body) VALUES(?,?,?,?)',(time.time(),actor,action,json.dumps(body)))

    def update(self,value,version):
        value=validate(value)
        if isinstance(version,bool) or not isinstance(version,int):raise ValueError('缺少設定版本。')
        with self.tx() as db:
            before=self._state(db)
            if before['version']!=version:raise Conflict('設定已被更新，請重新載入後再修改。')
            db.execute('UPDATE settings SET body=?,version=version+1,updated=? WHERE id=1',(json.dumps(value),time.time()))
            self._audit(db,'google','settings',{'before':before['values'],'after':value})
            return self._state(db)

    def _limit(self,db,key,limit):
        now=time.time();row=db.execute('SELECT start,n FROM rate_limits WHERE key=?',(key,)).fetchone()
        if row and now-row[0]<60:
            if row[1]>=limit:raise Denied('操作太頻繁，請稍後再試。')
            db.execute('UPDATE rate_limits SET n=n+1 WHERE key=?',(key,))
        else:db.execute('INSERT OR REPLACE INTO rate_limits VALUES(?,?,1)',(key,now))

    def challenge(self):
        cookie=secrets.token_urlsafe(32);nonce=secrets.token_urlsafe(32)
        with self.tx() as db:
            self._limit(db,'google-challenge',60)
            now=time.time()
            for table in ('sessions','challenges','binds'):db.execute('DELETE FROM '+table+' WHERE expires<?',(now,))
            db.execute('DELETE FROM receipts WHERE created<?',(now-7*86400,))
            db.execute('DELETE FROM rate_limits WHERE start<?',(now-86400,))
            db.execute('INSERT INTO challenges VALUES(?,?,?)',(digest(cookie),nonce,now+300))
        return cookie,nonce

    def take_challenge(self,cookie):
        with self.tx() as db:
            key=digest(cookie)
            row=db.execute('SELECT nonce,expires FROM challenges WHERE token=?',(key,)).fetchone()
            db.execute('DELETE FROM challenges WHERE token=?',(key,))
        if not row or row[1]<time.time():raise Denied('登入驗證已過期，請重新登入。')
        return row[0]

    def login(self,claims,nonce):
        if not OWNER or claims.get('email','').lower()!=OWNER or claims.get('email_verified') is not True or not claims.get('sub'):
            raise Denied('此帳號沒有管理權限。')
        if not hmac.compare_digest(str(claims.get('nonce','')),nonce):raise Denied('登入驗證不符。')
        token=secrets.token_urlsafe(32);csrf=secrets.token_urlsafe(32)
        with self.tx() as db:
            sub=str(claims['sub'])
            old=db.execute("SELECT value FROM meta WHERE key='google_sub'").fetchone()
            if old and old[0]!=sub:raise Denied('管理員身分不符。')
            db.execute("INSERT OR IGNORE INTO meta VALUES('google_sub',?)",(sub,))
            db.execute('INSERT INTO sessions VALUES(?,?,?)',(digest(token),csrf,time.time()+8*3600))
            self._audit(db,'google','login',{})
        return token,csrf

    def session(self,token):
        with self.tx() as db:row=db.execute('SELECT csrf,expires FROM sessions WHERE token=?',(digest(token),)).fetchone()
        if not row or row[1]<time.time():raise Denied('請先使用 Google 登入。')
        return row[0]

    def logout(self,token):
        with self.tx() as db:db.execute('DELETE FROM sessions WHERE token=?',(digest(token),))

    def bind_code(self):
        code=secrets.token_hex(16).upper()
        with self.tx() as db:
            db.execute('DELETE FROM binds')
            db.execute('INSERT INTO binds VALUES(?,?)',(digest(code),time.time()+300))
        return code

    def linked(self):
        with self.tx() as db:row=db.execute("SELECT value FROM meta WHERE key='line_user'").fetchone()
        return bool(row)

    def unlink(self):
        with self.tx() as db:
            db.execute("DELETE FROM meta WHERE key='line_user'");db.execute('DELETE FROM binds')
            self._audit(db,'google','unlink',{})

    def line(self,uid,event,action,value=None):
        if not uid or not event:raise Denied('無法確認 LINE 身分或訊息編號。')
        key=digest(uid+':'+event)
        # Rate limit commits separately, including denied binding attempts.
        with self.tx() as db:self._limit(db,'line:'+digest(uid),12)
        with self.tx() as db:
            old=db.execute('SELECT body FROM receipts WHERE event=?',(key,)).fetchone()
            if old:return old[0]
            actor=db.execute("SELECT value FROM meta WHERE key='line_user'").fetchone()
            if action=='bind':
                row=db.execute('SELECT expires FROM binds WHERE code=?',(digest(value),)).fetchone()
                if not row or row[0]<time.time():raise Denied('綁定碼無效或已過期，請回後台重新產生。')
                db.execute('DELETE FROM binds')
                db.execute("INSERT OR REPLACE INTO meta VALUES('line_user',?)",(uid,))
                self._audit(db,'line','bind',{})
                reply='管理員 LINE 已綁定。輸入「當沖設定」查看設定。'
            else:
                if not actor or not hmac.compare_digest(actor[0],uid):raise Denied('請先在 Google 後台綁定你的 LINE。')
                state=self._state(db)
                if action=='update':
                    fields=validate({**state['values'],**value})
                    db.execute('UPDATE settings SET body=?,version=version+1,updated=? WHERE id=1',(json.dumps(fields),time.time()))
                    self._audit(db,'line','settings',{'before':state['values'],'after':fields})
                    state=self._state(db)
                fields=state['values']
                reply=(f"當沖設定（版本 {state['version']}）\n最低股價：{fields['min_price']:g} 元\n最高股價：{fields['max_price']:g} 元\n"
                       f"推薦當下漲幅上限：{fields['max_gain_pct']:g}%\n\n"
                       "修改範例：\n當沖設定 最高股價 100\n當沖設定 最低股價 20\n當沖設定 漲幅上限 5\n\n新推薦與LINE發送前會讀取最新設定；既有訊號繼續追蹤。")
            db.execute('INSERT INTO receipts VALUES(?,?,?)',(key,reply,time.time()))
            return reply


def read_live_settings():
    """Fail closed if installed state is missing/corrupt; no environment fallback after integration."""
    path=db_path()
    uri=path.resolve().as_uri()+'?mode=ro'
    db=sqlite3.connect(uri,uri=True,timeout=1)
    try:
        row=db.execute('SELECT body FROM settings WHERE id=1').fetchone()
        if not row:raise RuntimeError('Admin settings missing')
        return validate(json.loads(row[0]))
    finally:db.close()
