"""Runway V2: 盤中重啟後還原跑道 B 部位
PositionManagerV2 只把部位放在記憶體，服務重啟後 positions 為空，ledger 的 OPEN 列就再也不會被
停損/停利或 12:55 強制平倉。runner 在每個交易日第一次 on_radar_update / on_tick 時呼叫
restore_positions()：

1. 今日進場、仍有股數在手的交易 (OPEN，或最後一腿為「分批停利 50%」的 CLOSED) 還原回
   manager.positions，之後照原本規則管理並在 12:55 平倉，也重新計入 MAX_CONCURRENT_POSITIONS。
2. 前一交易日以前遺留的交易不再交易 (沒有可信的出場價)，以 ledger.mark_orphaned 標記並記 log。

盤中狀態優先取 runway_v2_position_state (runner 每次開倉 / 價格更新時寫入)；
沒有 sidecar 列 (此功能上線前的部位) 時由 ledger 重建：
- 停損價：OPEN 列用 manager 預設 entry * (1 - STOP_LOSS_PCT)；分批後用進場價 (保本)。
- 剩餘股數：分批後為 shares - shares // 2 (與 update_price 相同算法)。
- 最高價 / 現價：OPEN 列為進場價；分批後為分批那一腿的出場價。
- 移動停利：False；之後 update_price 會依現價重新判斷是否啟動。
manager.py 受 META_B_FILTER_V1 預註冊釘選，此處只建立 PositionV2 物件並放進 positions，不改出場規則。
"""
from __future__ import annotations
from pathlib import Path
from .config import STOP_LOSS_PCT
from .ledger import (
    PARTIAL_EXIT_REASON,
    delete_position_state,
    get_unfinished_trades,
    load_position_states,
    mark_orphaned,
)
from .manager import PositionManagerV2, PositionV2

ORPHAN_NOTE = "重啟遺留未平倉：前一交易日部位無出場價，不再交易"


def _split_reasons(text: str | None) -> list[str]:
    return [r.strip() for r in str(text or "").split(",") if r.strip()]


def _build_position(trade: dict, state: dict | None) -> tuple[PositionV2, str]:
    entry = float(trade["entry_price"])
    initial_shares = int(trade["shares"])
    partial_done = trade["status"] == "CLOSED"  # 最後一腿為分批停利

    if partial_done:
        shares = initial_shares - initial_shares // 2
        leg_price = float(trade.get("exit_price") or entry)
        stop = max(float(state["stop_price"]) if state else entry, entry)
        highest = max(entry, leg_price, float(state["highest_price"]) if state else entry)
        current = float(state["current_price"]) if state else leg_price
        trailing = bool(state["trailing_active"]) if state else False
    else:
        shares = initial_shares
        stop = float(state["stop_price"]) if state else entry * (1.0 - STOP_LOSS_PCT)
        highest = max(entry, float(state["highest_price"]) if state else entry)
        current = float(state["current_price"]) if state else entry
        trailing = bool(state["trailing_active"]) if state else False

    pos = PositionV2(
        trade_id=trade["trade_id"],
        symbol=trade["symbol"],
        name=trade["name"],
        entry_price=entry,
        shares=shares,
        entry_time=trade["entry_time"],
        signal_type=trade["signal_type"],
        score=float(trade["score"]),
        reasons=_split_reasons(trade.get("reasons")),
        initial_stop_price=stop,
    )
    pos.initial_shares = initial_shares
    pos.highest_price = highest
    pos.current_price = current
    pos.half_closed = partial_done
    pos.trailing_active = trailing
    return pos, ("state" if state else "reconstructed")


def restore_positions(
    manager: PositionManagerV2,
    day: str,
    resolved_time: str,
    db_path: Path | str | None = None,
) -> dict:
    """把 day 當日仍在手的交易放回 manager.positions，並處理 day 以前的遺留交易。
    回傳 {"restored": [...], "orphaned": [...]}，每個動作各印一行 [RUNWAY_V2_RESTORE]。
    """
    states = load_position_states(db_path)
    restored: list[str] = []
    orphaned: list[str] = []
    live_ids: set[str] = set()

    # 記憶體中跨日留下的部位 (例如 12:55 後沒有任何 tick)：ledger 一併以遺留處理
    for sym, pos in list(manager.positions.items()):
        if not str(pos.entry_time).startswith(day):
            manager.positions.pop(sym, None)

    for trade in get_unfinished_trades(db_path):
        trade_id = trade["trade_id"]
        trade_day = str(trade["entry_time"])[:10]
        sym = trade["symbol"]

        if trade_day < day:
            mark_orphaned(trade_id, resolved_time, ORPHAN_NOTE, db_path)
            orphaned.append(trade_id)
            print(
                f"[RUNWAY_V2_RESTORE] orphaned {sym} {trade['name']} trade_id={trade_id} "
                f"entry_day={trade_day} status={trade['status']} "
                f"partial_done={trade['status'] == 'CLOSED'} action=no_trade reason=prior_day_no_exit_price"
            )
            continue
        if trade_day > day:
            continue  # 不應發生 (時鐘回撥)；不動它

        live_ids.add(trade_id)
        existing = manager.positions.get(sym)
        if existing is not None:
            if existing.trade_id != trade_id:
                print(
                    f"[RUNWAY_V2_RESTORE] skip {sym} trade_id={trade_id} "
                    f"reason=symbol_already_held_by={existing.trade_id}"
                )
            continue

        pos, source = _build_position(trade, states.get(trade_id))
        manager.positions[sym] = pos
        restored.append(trade_id)
        print(
            f"[RUNWAY_V2_RESTORE] restored {sym} {pos.name} trade_id={trade_id} "
            f"entry={pos.entry_price} shares={pos.shares}/{pos.initial_shares} "
            f"stop={pos.stop_price:.2f} highest={pos.highest_price} current={pos.current_price} "
            f"half_closed={pos.half_closed} trailing={pos.trailing_active} source={source}"
        )

    # 對應交易已平倉或已遺留處理的 sidecar 列
    for trade_id in set(states) - live_ids:
        if trade_id not in orphaned:
            delete_position_state(trade_id, db_path)

    print(
        f"[RUNWAY_V2_RESTORE] day={day} restored={len(restored)} orphaned={len(orphaned)} "
        f"open_now={len(manager.positions)}"
    )
    return {"restored": restored, "orphaned": orphaned}


__all__ = ["restore_positions", "ORPHAN_NOTE", "PARTIAL_EXIT_REASON"]
