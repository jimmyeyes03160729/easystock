"""Durable pre-execution model observations, including candidates that cannot be bought."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta

TPE=timezone(timedelta(hours=8))

class Decisions:
    def __init__(self,path=None):
        self.path=Path(path or Path(os.getenv('LEARNING_DATA_DIR','/home/ubuntu/easystock-learning-data'))/'decisions.sqlite')
        self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        with self.connect() as c:
            c.execute('''CREATE TABLE IF NOT EXISTS decisions (
                id TEXT PRIMARY KEY,day TEXT,symbol TEXT,observed_at TEXT,features TEXT,
                model TEXT,price REAL,accepted INTEGER,execution TEXT,context TEXT)''')
        self.path.chmod(0o600)
    @contextmanager
    def connect(self):
        c=sqlite3.connect(self.path,timeout=10)
        try:
            with c:yield c
        finally:c.close()
    def record(self,symbol,at,price,features,model,context):
        # One immutable observation per five-minute window/model/symbol prevents retry overweighting.
        key=hashlib.sha256(f'{symbol}:{int(at.timestamp()//300)}:{model.get("model_version")}:{bool(model.get("accepted"))}'.encode()).hexdigest()[:24]
        body=lambda v:json.dumps(v,ensure_ascii=False,allow_nan=False,default=str)
        with self.connect() as c:
            c.execute('INSERT OR IGNORE INTO decisions VALUES (?,?,?,?,?,?,?,?,?,?)',
                (key,at.astimezone(TPE).date().isoformat(),symbol,at.isoformat(),body(features),body(model),float(price),int(bool(model.get('accepted'))),'not_bought',body(context)))
        return key
    def execution(self,key,result):
        with self.connect() as c:
            # Never replace an actual fill with a later retry outcome.
            c.execute("UPDATE decisions SET execution=? WHERE id=? AND execution NOT LIKE '%\"status\": \"bought\"%'",(json.dumps(result,ensure_ascii=False,allow_nan=False),key))
