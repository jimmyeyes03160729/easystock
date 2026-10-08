"""Runway B restart safety: today's unfinished ledger trades are restored into the manager,
prior-day leftovers are marked ORPHANED. Synthetic dates and prices only; no market data is read.
"""
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

import runway_v2.runner as runner_mod
from runway_v2.config import MAX_CONCURRENT_POSITIONS, STOP_LOSS_PCT
from runway_v2.ledger import (
    ORPHANED,
    PARTIAL_EXIT_REASON,
    get_daily_trades,
    init_db,
    load_position_states,
    record_entry,
    record_exit,
)
from runway_v2.manager import calculate_costs
from runway_v2.reporter import generate_comparison_report
from runway_v2.restore import ORPHAN_NOTE

TPE = timezone(timedelta(hours=8))
PREV_DAY = "2026-09-14"
DAY = "2026-09-15"


def at(hh, mm, ss=0, day=DAY):
    y, m, d = map(int, day.split("-"))
    return datetime(y, m, d, hh, mm, ss, tzinfo=TPE)


def row(symbol, price):
    return {"symbol": symbol, "name": f"S{symbol}", "close": price}


def fake_signal(**kw):
    price = kw["current_price"]
    return {
        "signal_type": "ORB_BREAKOUT",
        "score": 80.0,
        "reasons": ["test", "vwap"],
        "stop_price": round(price * 0.99, 2),  # structural stop tighter than the 1.5% default
    }


def make_runner(db_path, monkeypatch):
    monkeypatch.setattr(runner_mod, "evaluate_signal", fake_signal)
    monkeypatch.setattr(runner_mod, "notify_entry", lambda **kw: None)
    monkeypatch.setattr(runner_mod, "notify_exit", lambda **kw: None)
    monkeypatch.setattr(runner_mod.RunwayV2Runner, "sync_to_firebase", lambda self: None)
    runner = runner_mod.RunwayV2Runner(db_path=db_path)
    runner.enabled = True
    return runner


def radar(runner, rows, when):
    prev = {r["symbol"]: r["close"] / 1.02 for r in rows}
    runner.on_radar_update(rows, None, prev, when)


def net(entry, exit_price, shares):
    _, _, cost = calculate_costs(entry, exit_price, shares)
    return (exit_price - entry) * shares - cost


def by_symbol(db, day=DAY):
    return {t["symbol"]: t for t in get_daily_trades(day, db)}


def test_restart_restores_open_positions_and_force_closes_them(tmp_path, monkeypatch, capsys):
    db = tmp_path / "ledger.sqlite"
    first = make_runner(db, monkeypatch)
    radar(first, [row("1101", 100.0), row("1102", 50.0), row("1103", 40.0)], at(9, 10))
    first.on_tick("1101", 100.8, at(9, 30))  # new high
    first.on_tick("1101", 100.4, at(9, 31))  # latest price
    first.on_tick("1102", 50.3, at(9, 32))

    # service restarts: fresh runner, empty manager, same ledger
    second = make_runner(db, monkeypatch)
    assert second.manager.positions == {}
    capsys.readouterr()

    second.on_tick("9999", 77.0, at(10, 0))
    assert set(second.manager.positions) == {"1101", "1102", "1103"}
    p = second.manager.positions["1101"]
    assert (p.shares, p.stop_price, p.highest_price, p.current_price) == (3000, 99.0, 100.8, 100.4)
    assert p.reasons == ["test", "vwap"]
    out = capsys.readouterr().out
    assert out.count("[RUNWAY_V2_RESTORE] restored") == 3
    assert "source=state" in out
    assert "restored=3 orphaned=0 open_now=3" in out

    # restored positions are still managed: 1103 hits its structural stop (39.6)
    second.on_tick("1103", 39.5, at(10, 5))
    assert "1103" not in second.manager.positions

    second.on_tick("1101", 100.6, at(12, 55))
    assert second.manager.positions == {}
    trades = by_symbol(db)
    assert {s: t["status"] for s, t in trades.items()} == dict.fromkeys(trades, "CLOSED")
    assert {s: t["exit_price"] for s, t in trades.items()} == {"1101": 100.6, "1102": 50.3, "1103": 39.5}
    assert trades["1102"]["exit_reason"] == "收盤強制平倉"
    assert trades["1102"]["net_pnl"] == pytest.approx(net(50.0, 50.3, 6000))
    assert load_position_states(db) == {}


def test_restored_positions_count_toward_max_concurrent(tmp_path, monkeypatch):
    db = tmp_path / "ledger.sqlite"
    first = make_runner(db, monkeypatch)
    radar(first, [row("1101", 100.0), row("1102", 100.0), row("1103", 100.0)], at(9, 10))
    assert MAX_CONCURRENT_POSITIONS == 3

    second = make_runner(db, monkeypatch)
    radar(second, [row("2201", 20.0)], at(9, 40))
    assert set(second.manager.positions) == {"1101", "1102", "1103"}
    assert len(get_daily_trades(DAY, db)) == 3


def test_restart_after_partial_exit_restores_the_remaining_half(tmp_path, monkeypatch, capsys):
    db = tmp_path / "ledger.sqlite"
    first = make_runner(db, monkeypatch)
    radar(first, [row("1101", 100.0)], at(9, 10))
    first.on_tick("1101", 101.6, at(9, 20))  # +1.6% -> 1,500 sh sold, stop to break-even
    first.on_tick("1101", 102.1, at(9, 21))  # trailing armed, high 102.1
    t = by_symbol(db)["1101"]
    assert (t["status"], t["exit_reason"]) == ("CLOSED", PARTIAL_EXIT_REASON)

    second = make_runner(db, monkeypatch)
    capsys.readouterr()
    second.on_tick("1101", 101.9, at(9, 40))
    p = second.manager.positions["1101"]
    assert (p.shares, p.initial_shares, p.half_closed, p.trailing_active) == (1500, 3000, True, True)
    assert (p.stop_price, p.highest_price) == (100.0, 102.1)
    assert "half_closed=True" in capsys.readouterr().out

    # 0.8% pullback from 102.1 -> trailing exit of the remaining 1,500 sh
    second.on_tick("1101", 101.2, at(9, 41))
    assert second.manager.positions == {}
    t = by_symbol(db)["1101"]
    assert t["exit_reason"] == "移動停利出場"
    assert t["net_pnl"] == pytest.approx(net(100.0, 101.6, 1500) + net(100.0, 101.2, 1500), abs=0.01)


def test_rows_without_saved_state_are_reconstructed_from_the_ledger(tmp_path, monkeypatch, capsys):
    db = tmp_path / "ledger.sqlite"
    init_db(db)
    record_entry("T-OPEN", "1101", "S1101", at(9, 10).isoformat(), 100.0, 3000, "ORB_BREAKOUT", 80.0, ["a"], db)
    record_entry("T-HALF", "1102", "S1102", at(9, 11).isoformat(), 50.0, 6000, "ORB_BREAKOUT", 80.0, ["a"], db)
    record_exit("T-HALF", at(9, 30).isoformat(), 50.8, PARTIAL_EXIT_REASON, 2400.0, 50.0, 228.0, 2122.0, 1.6, db)

    runner = make_runner(db, monkeypatch)
    capsys.readouterr()
    radar(runner, [], at(9, 45))  # no rows: the radar call still triggers restore
    runner.on_tick("9999", 1.0, at(9, 45))

    a, b = runner.manager.positions["1101"], runner.manager.positions["1102"]
    assert (a.shares, a.half_closed, a.highest_price) == (3000, False, 100.0)
    assert a.stop_price == pytest.approx(100.0 * (1 - STOP_LOSS_PCT))
    assert (b.shares, b.half_closed, b.stop_price, b.highest_price, b.current_price) == (3000, True, 50.0, 50.8, 50.8)
    out = capsys.readouterr().out
    assert out.count("source=reconstructed") == 2


def test_prior_day_leftovers_are_orphaned_not_traded(tmp_path, monkeypatch, capsys):
    db = tmp_path / "ledger.sqlite"
    init_db(db)
    record_entry("T-OLD", "1101", "S1101", at(9, 10, day=PREV_DAY).isoformat(), 100.0, 3000, "ORB_BREAKOUT", 80.0, ["a"], db)
    record_entry("T-OLDHALF", "1102", "S1102", at(9, 11, day=PREV_DAY).isoformat(), 50.0, 6000, "ORB_BREAKOUT", 80.0, ["a"], db)
    record_exit("T-OLDHALF", at(9, 30, day=PREV_DAY).isoformat(), 50.8, PARTIAL_EXIT_REASON, 2400.0, 50.0, 228.0, 2122.0, 1.6, db)

    runner = make_runner(db, monkeypatch)
    capsys.readouterr()
    runner.on_tick("1101", 101.0, at(9, 0))
    assert runner.manager.positions == {}

    old = by_symbol(db, PREV_DAY)
    assert old["1101"]["status"] == ORPHANED
    assert old["1101"]["exit_reason"] == ORPHAN_NOTE
    assert old["1101"]["exit_price"] is None and old["1101"]["net_pnl"] is None
    assert old["1102"]["status"] == "CLOSED"
    assert old["1102"]["exit_reason"] == f"{PARTIAL_EXIT_REASON}；{ORPHAN_NOTE}"
    assert old["1102"]["net_pnl"] == 2122.0

    out = capsys.readouterr().out
    assert out.count("[RUNWAY_V2_RESTORE] orphaned") == 2
    assert "restored=0 orphaned=2" in out

    # restore runs once per day; a slot is free for a new B entry today
    runner.on_tick("1101", 101.0, at(9, 1))
    assert "[RUNWAY_V2_RESTORE]" not in capsys.readouterr().out
    radar(runner, [row("1101", 100.0)], at(9, 10))
    assert "1101" in runner.manager.positions


def test_position_still_in_memory_on_a_new_day_is_dropped_and_orphaned(tmp_path, monkeypatch):
    db = tmp_path / "ledger.sqlite"
    runner = make_runner(db, monkeypatch)
    radar(runner, [row("1101", 100.0)], at(9, 10, day=PREV_DAY))
    # no tick after 12:55 that day; next morning
    runner.on_tick("1101", 99.0, at(9, 0))
    assert runner.manager.positions == {}
    assert by_symbol(db, PREV_DAY)["1101"]["status"] == ORPHANED


def test_restart_after_force_exit_time_closes_on_first_tick(tmp_path, monkeypatch):
    db = tmp_path / "ledger.sqlite"
    first = make_runner(db, monkeypatch)
    radar(first, [row("1101", 100.0)], at(9, 10))
    first.on_tick("1101", 100.7, at(12, 50))

    second = make_runner(db, monkeypatch)
    second.on_tick("9999", 77.0, at(12, 58))
    t = by_symbol(db)["1101"]
    assert (t["status"], t["exit_price"], t["exit_reason"]) == ("CLOSED", 100.7, "收盤強制平倉")


def test_snapshot_lists_restored_positions(tmp_path, monkeypatch):
    db = tmp_path / "ledger.sqlite"
    first = make_runner(db, monkeypatch)
    radar(first, [row("1101", 100.0)], at(9, 10))
    second = make_runner(db, monkeypatch)
    second.on_tick("9999", 1.0, at(9, 20))
    assert set(second.export_snapshot()["open_positions"]) == {"1101"}


def test_price_only_state_writes_are_throttled(tmp_path, monkeypatch):
    db = tmp_path / "ledger.sqlite"
    runner = make_runner(db, monkeypatch)
    radar(runner, [row("1101", 100.0)], at(9, 10))
    runner.on_tick("1101", 100.5, at(9, 11, 0))   # new high: written
    runner.on_tick("1101", 100.3, at(9, 11, 1))   # price only, 1s later: skipped
    (state,) = load_position_states(db).values()
    assert state["current_price"] == 100.5
    runner.on_tick("1101", 100.2, at(9, 11, 6))   # price only, 6s later: written
    (state,) = load_position_states(db).values()
    assert state["current_price"] == 100.2


def test_report_counts_only_closed_trades(tmp_path):
    db = tmp_path / "ledger.sqlite"
    init_db(db)
    record_entry("T-C", "1101", "S1101", at(9, 10).isoformat(), 100.0, 3000, "ORB_BREAKOUT", 80.0, ["a"], db)
    record_exit("T-C", at(10, 0).isoformat(), 101.0, "移動停利出場", 3000.0, 170.0, 454.0, 2376.0, 1.0, db)
    record_entry("T-O", "1102", "S1102", at(9, 11).isoformat(), 50.0, 6000, "ORB_BREAKOUT", 80.0, ["a"], db)
    record_entry("T-X", "1103", "S1103", at(9, 12).isoformat(), 40.0, 7000, "ORB_BREAKOUT", 80.0, ["a"], db)
    conn = sqlite3.connect(str(db))
    with conn:
        conn.execute("UPDATE runway_v2_trades SET status = ? WHERE trade_id = 'T-X'", (ORPHANED,))
    conn.close()

    report = generate_comparison_report(day=DAY, db_path=db)
    assert "交易筆數：1 筆" in report
    assert "1 勝 0 負" in report
    assert "未平倉：1 筆" in report
    assert "重啟遺留未平倉：1 筆" in report
