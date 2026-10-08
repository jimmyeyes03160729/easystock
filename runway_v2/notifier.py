"""Runway V2: LINE 與 Telegram 推播器
整合現有 easystock_admin.notifications 配置，支援：
1. 跑道 B 開倉即時通知
2. 跑道 B 平倉即時通知
3. 盤後雙跑道盲測對比日報 (跑道 A vs 跑道 B)
"""
from __future__ import annotations
import hashlib
import json
import uuid
import requests


def _send_line(text: str) -> str:
    try:
        from easystock_admin.notifications import line_config
        token, target = line_config()
    except Exception:
        return "disabled"

    if not token or not target:
        return "disabled"

    retry_key = str(uuid.uuid4())
    try:
        resp = requests.post(
            "https://api.line.me/v2/bot/message/push",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "X-Line-Retry-Key": retry_key,
            },
            json={"to": target, "messages": [{"type": "text", "text": text[:5000]}]},
            timeout=(3, 10),
        )
        return "sent" if 200 <= resp.status_code < 300 else f"failed:{resp.status_code}"
    except Exception as exc:
        return f"error:{type(exc).__name__}"


def _send_telegram(text: str) -> str:
    try:
        from easystock_admin.notifications import telegram_config
        token, chat = telegram_config()
    except Exception:
        return "disabled"

    if not token or not chat:
        return "disabled"

    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat,
                "text": text[:4096],
                "link_preview_options": {"is_disabled": True},
            },
            timeout=(3, 10),
        )
        return "sent" if resp.status_code == 200 and resp.json().get("ok") is True else f"failed:{resp.status_code}"
    except Exception as exc:
        return f"error:{type(exc).__name__}"


def notify_channels(text: str) -> dict[str, str]:
    """同時發送訊息至 LINE 與 Telegram。"""
    res_line = _send_line(text)
    res_tg = _send_telegram(text)
    print(f"[RUNWAY_V2_NOTIFY] LINE: {res_line} | TG: {res_tg}")
    return {"line": res_line, "telegram": res_tg}


def notify_entry(symbol: str, name: str, price: float, shares: int, signal_type: str, score: float, reasons: list[str]) -> dict[str, str]:
    msg = (
        f"🚀【跑道 B：實驗動能規則（回測為負）】進場通知\n"
        f"━━━━━━━━━━━━━━\n"
        f"標的：{symbol} {name}\n"
        f"時間：進場建立\n"
        f"進場價：{price:.2f} 元\n"
        f"股數：{shares:,} 股\n"
        f"型態：{signal_type}\n"
        f"動能評分：{score:.1f} 分\n"
        f"理由：{', '.join(reasons)}\n"
        f"━━━━━━━━━━━━━━\n"
        f"※ 跑道 B 獨立模擬驗證，不影響跑道 A"
    )
    return notify_channels(msg)


def notify_exit(symbol: str, name: str, entry_price: float, exit_price: float, shares: int, net_pnl: float, return_pct: float, reason: str) -> dict[str, str]:
    emoji = "🎉" if net_pnl > 0 else "🛑"
    msg = (
        f"{emoji}【跑道 B：實驗動能規則（回測為負）】平倉通知\n"
        f"━━━━━━━━━━━━━━\n"
        f"標的：{symbol} {name}\n"
        f"進場價：{entry_price:.2f} 元\n"
        f"平倉價：{exit_price:.2f} 元\n"
        f"股數：{shares:,} 股\n"
        f"平倉理由：{reason}\n"
        f"報酬率：{return_pct:+.2f}%\n"
        f"淨損益：{net_pnl:+,.0f} 元 (已扣手續費與稅)\n"
        f"━━━━━━━━━━━━━━\n"
        f"※ 跑道 B 獨立模擬驗證"
    )
    return notify_channels(msg)
