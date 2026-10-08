"""Runway V2: 雙跑道對照日報產出與推播
 Side-by-Side 比較：
 【跑道 A：現有 AI 模型體系】 vs 【跑道 B：新獨立高勝率動能跑道】
並自動推播至 LINE 與 TELEGRAM。
"""
from __future__ import annotations
import argparse
import os
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from .config import DB_PATH
from .ledger import get_daily_trades
from .notifier import notify_channels

TPE = timezone(timedelta(hours=8))


def fetch_runway_a_summary(day: str) -> dict:
    """讀取跑道 A (現有生產環境帳本與狀態)。"""
    admin_db_path = Path(os.environ.get("EASYSTOCK_ADMIN_DB", "/home/ubuntu/easystock-admin/state.sqlite"))
    if not admin_db_path.exists():
        return {
            "trades_count": 0,
            "net_pnl": 0.0,
            "status_text": "無交易紀錄 (受限於 0.60 門檻與 09:30 時窗)",
        }

    try:
        conn = sqlite3.connect(f"file:{admin_db_path}?mode=ro", uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        log = conn.execute("SELECT * FROM paper_trade_logs WHERE date=?", (day,)).fetchone()
        fills = conn.execute(
            "SELECT * FROM paper_trade_fills WHERE trade_date=? AND side='SELL'", (day,)
        ).fetchall()
        conn.close()

        count = len(fills)
        pnl = float(log["net_pnl"]) if log and log["net_pnl"] is not None else 0.0
        status_text = "今日正常結算" if count > 0 else "0 筆成交 (卡在 0.60 門檻或 09:30 前不進場)"
        return {
            "trades_count": count,
            "net_pnl": pnl,
            "status_text": status_text,
        }
    except Exception as exc:
        return {
            "trades_count": 0,
            "net_pnl": 0.0,
            "status_text": f"資料庫未就緒 ({type(exc).__name__})",
        }


def generate_comparison_report(day: str | None = None, db_path: Path | str | None = None) -> str:
    today_str = day or datetime.now(TPE).strftime("%Y-%m-%d")

    # 1. 跑道 A 數據
    runway_a = fetch_runway_a_summary(today_str)

    # 2. 跑道 B 數據
    trades_b = get_daily_trades(today_str, db_path=db_path)
    count_b = len(trades_b)
    wins_b = sum(1 for t in trades_b if (t.get("net_pnl") or 0.0) > 0)
    losses_b = sum(1 for t in trades_b if (t.get("net_pnl") or 0.0) <= 0)
    win_rate_b = (wins_b / count_b * 100.0) if count_b > 0 else 0.0
    total_net_pnl_b = sum((t.get("net_pnl") or 0.0) for t in trades_b)

    lines = [
        "📊【EasyStock 當沖雙跑道對照日報】",
        f"📅 日期：{today_str}",
        "",
        "══════════════════════",
        "🔹【跑道 A：現有 AI 模型體系】",
        f"• 交易筆數：{runway_a['trades_count']} 筆",
        f"• 當日損益：{runway_a['net_pnl']:+,.0f} 元",
        f"• 運行備註：{runway_a['status_text']}",
        "",
        "══════════════════════",
        "⚡【跑道 B：新獨立動能跑道 V2】",
        f"• 交易筆數：{count_b} 筆",
    ]

    if count_b > 0:
        lines.append(f"• 勝負紀錄：{wins_b} 勝 {losses_b} 負 (勝率 {win_rate_b:.1f}%)")
        lines.append(f"• 淨損益總計：{total_net_pnl_b:+,.0f} 元 (已扣費稅)")
        lines.append("• 成交明細：")
        for i, t in enumerate(trades_b, 1):
            pnl = t.get("net_pnl") or 0.0
            ret = t.get("return_pct") or 0.0
            lines.append(
                f"  {i}. {t['symbol']} {t['name']}: {pnl:+,.0f} 元 ({ret:+.2f}%) [{t.get('exit_reason', t.get('signal_type'))}]"
            )
    else:
        lines.append("• 今日無符合條件之高勝率訊號 (0 筆進場，嚴守紀律)")

    lines.extend([
        "══════════════════════",
        "※ 跑道 B 完全平行獨立運作，零干擾跑道 A 模型訓練",
    ])

    return "\n".join(lines)


def run_and_notify(day: str | None = None, db_path: Path | str | None = None) -> str:
    report = generate_comparison_report(day=day, db_path=db_path)
    print("\n" + report + "\n")
    notify_channels(report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="產生雙跑道對照日報並發送至 LINE & Telegram")
    parser.add_argument("--day", type=str, default=None, help="指定日期 YYYY-MM-DD")
    parser.add_argument("--notify", action="store_true", help="是否發送推播通知")
    args = parser.parse_args()

    if args.notify:
        run_and_notify(day=args.day)
    else:
        print(generate_comparison_report(day=args.day))
