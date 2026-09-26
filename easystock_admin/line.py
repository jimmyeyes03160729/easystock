"""Call ONLY after original LINE HMAC verification. Admin commands bypass stock-card caching."""
import re
from .store import Store, Denied


def handle_admin_command(text,source,event_id,store=None):
    if text!='當沖設定' and not text.startswith(('當沖設定 ','綁定管理員 ')):
        return None
    if source.get('type')!='user':return '管理員設定僅限私訊機器人操作。'
    store=store or Store()
    uid=source.get('userId','')
    try:
        if text.startswith('綁定管理員 '):
            code=text.split(maxsplit=1)[1].strip().upper()
            if not re.fullmatch('[0-9A-F]{32}',code):return '請貼上後台產生的完整綁定指令。'
            return store.line(uid,event_id,'bind',code)
        if text=='當沖設定':return store.line(uid,event_id,'read')
        match=re.fullmatch(r'當沖設定\s+(最低股價|最高股價|漲幅上限)\s+(\d+(?:\.\d{1,2})?)',text)
        if not match:return '指令範例：當沖設定 最高股價 100（數字不加元或%）'
        field={'最低股價':'min_price','最高股價':'max_price','漲幅上限':'max_gain_pct'}[match[1]]
        return store.line(uid,event_id,'update',{field:float(match[2])})
    except (Denied,ValueError) as exc:return str(exc)
