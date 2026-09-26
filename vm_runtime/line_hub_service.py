#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Any
UPDATE_TEXT="""🆕 當沖吧！牛馬仔｜EasyStock LINE Hub V5.2
更新日期：2026/09/09

• LINE 群組通知升級
  自動取得群組 ID
  Firebase 管理啟用群組
  AI早報 / 當沖訊號支援群組推播

• ETF 查詢補強
  00878 可直接輸入
  支援 0050 / 00878 / 006208 / 00980A 等 ETF

• LINE 查詢整合
  即時行情、K線、法人、大盤、ETF、股利集中同一 Bot

• 當沖雷達通知
  ENTRY 訊號即時通知
  EXIT 訊號即時通知
  不影響策略與交易邏輯

• 圖卡優化
  Compact 圖卡
  K線最高/最低標示
  點擊圖卡前往 Yahoo 股市

• 圖片快取
  /dev/shm RAM 暫存
  60 秒重用
  10 分鐘清理
  最多 50 張

• 指令整合
  指令 → 功能列表
  更新 → 版本內容
  早報 → 最新 AI 快報
  當沖 → 盤中狀態

輸入「指令」查看全部功能。"""

NOTIFY_INFO_TEXT = """🔔 當沖吧！牛馬仔｜LINE 自動通知

【自動推播規則】
目前已全面關閉所有早報與盤中逐筆通知。
每日僅保留一則自動推播：
• 13:30 當沖結盤總結（今日買進部位、各別損益 %、總勝率）

【手動即時查詢】
輸入「當沖」：隨時查閱今日當沖結盤與部位
輸入「早報」：隨時查閱開盤前 AI 市場快報
輸入「P2330」：隨時查閱即時蘋果風走勢圖卡"""
def _db_module():
    import firebase_admin
    from firebase_admin import db
    if not firebase_admin._apps:
        from firebase_store import FirebaseStore
        FirebaseStore()
    return db
def _read(path): return _db_module().reference(path).get()
def _num(v):
    try:return None if v is None else float(v)
    except Exception:return None
def _rows(value):
    if isinstance(value,dict):return [x for x in value.values() if isinstance(x,dict)]
    if isinstance(value,list):return [x for x in value if isinstance(x,dict)]
    return []
def _fmt(v,d=2):
    x=_num(v); return '--' if x is None else f'{x:,.{d}f}'
def _market_line(brief,key,label):
    item=(brief.get('market_data') or {}).get(key) or {}
    if not isinstance(item,dict):return f'{label}：--'
    latest=_num(item.get('latest')); change=_num(item.get('change_pct'))
    if latest is None:return f'{label}：--'
    return f'{label}：{latest:,.2f}' if change is None else f'{label}：{latest:,.2f} ({change:+.2f}%)'
def latest_premarket_text():
    try:
        brief = _read('/market_data/premarket_brief')
    except Exception as exc:
        return f'⚠️ 最新早報讀取失敗\n{type(exc).__name__}: {exc}'

    if not isinstance(brief, dict) or not brief:
        return 'ℹ️ Firebase 尚無開盤前資料。'


    level = str(
        brief.get("market_level") or "--"
    ).upper()


    icon = {
        "GREEN": "🟢",
        "YELLOW": "🟡",
        "RED": "🔴",
    }.get(level, "⚪")


    focus = brief.get("focus") or []

    if not isinstance(focus, list):
        focus = []


    risks = brief.get("key_risks") or []

    if not isinstance(risks, list):
        risks = []


    focus_text = (
        str(focus[0])
        if focus
        else "留意強勢族群"
    )


    risk_text = (
        str(risks[0])
        if risks
        else "留意市場波動"
    )


    return "\n".join([
        "🌅 當沖吧！牛馬仔｜開盤早報",
        "",
        f"{icon} 市場：{level}",
        f"🔥 焦點：{focus_text}",
        f"⚠️ 風險：{risk_text}",
    ])

def latest_daytrade_text(target_date: str | None = None):
    from datetime import datetime, timezone, timedelta
    import math
    today = target_date or datetime.now(timezone(timedelta(hours=8))).date().isoformat()
    try:
        root = _read('/market_data/intraday_live')
    except Exception:
        root = {}

    closed = []
    opens = []

    if isinstance(root, dict) and root.get('scan_date') == today:
        def same_day(row):
            try:
                value = datetime.fromisoformat(str(row.get('entry_time', '')).replace('Z', '+00:00'))
                if value.tzinfo is None:
                    value = value.replace(tzinfo=timezone(timedelta(hours=8)))
                return value.astimezone(timezone(timedelta(hours=8))).date().isoformat() == today
            except (TypeError, ValueError):
                return False
        closed = [r for r in _rows(root.get('closed_trades')) if same_day(r) and str(r.get('status','')).upper() == 'CLOSED']
        opens = [r for r in _rows(root.get('open_positions')) if same_day(r)]

    # 若 Firebase 尚無或已清除，嘗試自本地學習日誌中讀取
    if not closed and not opens:
        try:
            from daytrade_learning.runtime import DATA
            jpath = DATA / f"journal-{today}.jsonl"
            if jpath.exists():
                import json
                with open(jpath, encoding="utf-8") as f:
                    for line in f:
                        if not line.strip(): continue
                        try:
                            rec = json.loads(line)
                            if rec.get("kind") == "exit" and isinstance(rec.get("data"), dict):
                                closed.append(rec["data"])
                        except Exception:
                            pass
        except Exception:
            pass

    values = []
    lines = [f"📊 EasyStock｜13:30 當沖結盤總結", f"📅 日期：{today}", ""]
    if closed:
        lines.append("【今日當沖部位與損益】")
        for row in sorted(closed, key=lambda r:str(r.get('entry_time',''))):
            raw = row.get('pnl_pct')
            if raw is None:
                raw = row.get('return_pct')
            pnl = _num(raw)
            if pnl is not None and not math.isfinite(pnl):
                pnl = None
            name = str(row.get('name') or row.get('symbol') or '--')
            sym = str(row.get('symbol') or '')
            sym_tag = f" ({sym})" if sym and sym != name else ""
            if pnl is None:
                lines.append(f"⚪ {name}{sym_tag} 已結束，損益缺值")
            else:
                values.append(pnl)
                icon = '🔴' if pnl > 0 else '🟢' if pnl < 0 else '⚪'
                lines.append(f"{icon} {name}{sym_tag} {pnl:+.2f}%")

    lines += ["", f"推薦 {len(closed)+len(opens)} 筆｜已結束 {len(closed)} 筆｜追蹤中 {len(opens)} 筆"]
    if values:
        wins = sum(v > 0 for v in values)
        lines += [
            f"🎯 總勝率：{wins/len(values)*100:.1f}%（{wins}/{len(values)}）",
            f"📈 平均報酬：{sum(values)/len(values):+.2f}%"
        ]
    elif not closed and not opens:
        lines.append("今日無推薦或當沖交易紀錄。")
    else:
        lines.append("尚無可計算的已結束損益。")

    return "\n".join(lines)
