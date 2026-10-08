"""Runway B live fixes: 12:55 force-exit pricing, daily buy cap and realized-loss circuit breaker.
Synthetic dates and prices only; no market data is read.
"""
from datetime import datetime, timedelta, timezone

import pytest

import runway_v2.runner as runner_mod
from runway_v2.config import DAILY_MAX_BUY_AMOUNT, DAILY_MAX_LOSS_CIRCUIT_BREAKER
from runway_v2.ledger import get_daily_trades
from runway_v2.limits import BUY_CAP, LOSS_CIRCUIT_BREAKER, DailyLimits, planned_shares
from runway_v2.manager import PositionManagerV2, calculate_costs

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
        "reasons": ["test"],
        "stop_price": round(price * 0.985, 2),
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


@pytest.mark.parametrize(
    "trigger, trigger_price, expected_1101",
    [("9999", 77.0, 101.0), ("1101", 101.2, 101.2)],
)
def test_force_exit_closes_each_position_at_its_own_latest_price(
    tmp_path, monkeypatch, trigger, trigger_price, expected_1101
):
    db = tmp_path / "ledger.sqlite"
    runner = make_runner(db, monkeypatch)
    radar(runner, [row("1101", 100.0), row("1102", 50.0), row("1103", 40.0)], at(9, 10))
    assert set(runner.manager.positions) == {"1101", "1102", "1103"}

    runner.on_tick("1101", 101.0, at(10, 0))
    runner.on_tick("1102", 50.6, at(10, 1))  # intraday high
    runner.on_tick("1102", 50.2, at(10, 2))  # latest trade price
    # 1103 never trades again after entry

    runner.on_tick(trigger, trigger_price, at(12, 55))
    assert runner.manager.positions == {}

    trades = {t["symbol"]: t for t in get_daily_trades(DAY, db)}
    assert {s: t["exit_price"] for s, t in trades.items()} == {
        "1101": expected_1101,
        "1102": 50.2,
        "1103": 40.0,
    }
    assert all(t["exit_reason"] == "收盤強制平倉" for t in trades.values())
    assert trades["1102"]["net_pnl"] == pytest.approx(net(50.0, 50.2, 6000))


def test_buy_cap_skips_an_entry_that_would_exceed_it_and_keeps_scanning(tmp_path, monkeypatch, capsys):
    runner = make_runner(tmp_path / "ledger.sqlite", monkeypatch)
    radar(runner, [row("1101", 100.0), row("1102", 100.0)], at(9, 10))
    assert runner.limits.buy_amount == 600_000

    # 1103: 450 x 1,000 sh -> 1,050,000 > cap, skipped; 1104: 400 x 1,000 sh lands exactly on the cap, allowed
    radar(runner, [row("1103", 450.0), row("1104", 400.0)], at(9, 11))
    assert set(runner.manager.positions) == {"1101", "1102", "1104"}
    assert runner.limits.buy_amount == DAILY_MAX_BUY_AMOUNT

    out = capsys.readouterr().out
    assert "[RUNWAY_V2_LIMIT] skip 1103" in out
    assert f"reason={BUY_CAP}" in out


def test_closing_a_position_does_not_free_buy_quota(tmp_path, monkeypatch, capsys):
    runner = make_runner(tmp_path / "ledger.sqlite", monkeypatch)
    radar(runner, [row("1101", 100.0), row("1102", 100.0), row("1103", 100.0)], at(9, 10))
    assert runner.limits.buy_amount == 900_000

    # 1101 closes at a profit: half at +2.5%, the rest on the trailing pullback
    runner.on_tick("1101", 102.5, at(9, 20))
    runner.on_tick("1101", 102.5, at(9, 21))
    runner.on_tick("1101", 101.5, at(9, 22))
    assert "1101" not in runner.manager.positions
    assert runner.limits.realized_net_pnl == pytest.approx(
        net(100.0, 102.5, 1500) + net(100.0, 101.5, 1500), abs=0.01
    )

    # a slot is free, but 900,000 + 300,000 > 1,000,000 of buys
    radar(runner, [row("1104", 100.0)], at(9, 30))
    radar(runner, [row("1104", 100.0)], at(9, 31))
    assert "1104" not in runner.manager.positions
    assert runner.limits.buy_amount == 900_000
    assert capsys.readouterr().out.count("[RUNWAY_V2_LIMIT] skip 1104") == 1


@pytest.mark.parametrize("exit_price, blocked", [(98.4, False), (98.0, True)])
def test_loss_circuit_breaker_stops_new_entries(tmp_path, monkeypatch, capsys, exit_price, blocked):
    runner = make_runner(tmp_path / "ledger.sqlite", monkeypatch)
    radar(runner, [row("1101", 100.0)], at(9, 10))
    runner.on_tick("1101", exit_price, at(9, 20))  # stop 98.5 -> full stop-out
    assert "1101" not in runner.manager.positions

    loss = net(100.0, exit_price, 3000)
    assert runner.limits.realized_net_pnl == pytest.approx(loss, abs=0.01)
    assert (loss <= -DAILY_MAX_LOSS_CIRCUIT_BREAKER) is blocked

    radar(runner, [row("1102", 100.0)], at(9, 30))
    assert ("1102" in runner.manager.positions) is not blocked
    out = capsys.readouterr().out
    assert ("[RUNWAY_V2_LIMIT] skip 1102" in out) is blocked
    assert (f"reason={LOSS_CIRCUIT_BREAKER}" in out) is blocked


def test_restart_keeps_todays_buy_quota(tmp_path, monkeypatch, capsys):
    db = tmp_path / "ledger.sqlite"
    first = make_runner(db, monkeypatch)
    radar(first, [row("1101", 100.0), row("1102", 100.0), row("1103", 100.0)], at(9, 10))
    first.on_tick("1101", 98.5, at(9, 20))  # stop-out frees a slot, not the buy quota

    restarted = make_runner(db, monkeypatch)  # in-memory counters are gone; open positions are restored
    radar(restarted, [row("1104", 100.0)], at(9, 30))
    assert set(restarted.manager.positions) == {"1102", "1103"}
    assert restarted.limits.buy_amount == 900_000
    assert f"reason={BUY_CAP}" in capsys.readouterr().out


def test_restart_keeps_the_loss_circuit_breaker(tmp_path, monkeypatch, capsys):
    db = tmp_path / "ledger.sqlite"
    first = make_runner(db, monkeypatch)
    radar(first, [row("1101", 100.0)], at(9, 10))
    first.on_tick("1101", 98.0, at(9, 20))

    restarted = make_runner(db, monkeypatch)
    radar(restarted, [row("1102", 100.0)], at(9, 30))
    assert restarted.manager.positions == {}
    assert restarted.limits.realized_net_pnl == pytest.approx(net(100.0, 98.0, 3000), abs=0.01)
    assert f"reason={LOSS_CIRCUIT_BREAKER}" in capsys.readouterr().out


def test_previous_day_trades_do_not_count_toward_today(tmp_path, monkeypatch):
    runner = make_runner(tmp_path / "ledger.sqlite", monkeypatch)
    radar(runner, [row("1101", 100.0), row("1102", 100.0), row("1103", 100.0)], at(9, 10, day=PREV_DAY))
    runner.on_tick("1101", 98.0, at(9, 20, day=PREV_DAY))
    runner.on_tick("1102", 100.0, at(12, 55, day=PREV_DAY))
    assert runner.limits.realized_net_pnl <= -DAILY_MAX_LOSS_CIRCUIT_BREAKER

    radar(runner, [row("1104", 100.0)], at(9, 10))
    assert "1104" in runner.manager.positions
    assert runner.limits.day == DAY
    assert runner.limits.buy_amount == 300_000
    assert runner.limits.realized_net_pnl == 0


def test_partial_take_profit_leg_stays_in_the_trade_pnl(tmp_path):
    db = tmp_path / "ledger.sqlite"
    manager = PositionManagerV2(db_path=db)
    manager.open_position(
        "1101", "S1101", 100.0, f"{DAY}T09:10:00+08:00", "ORB_BREAKOUT", 80.0, ["test"], stop_price=98.5
    )
    half = manager.update_price("1101", 101.6, f"{DAY}T09:20:00+08:00")
    rest = manager.update_price("1101", 99.9, f"{DAY}T09:30:00+08:00")
    assert half["is_partial"] is True
    assert rest["reason"] == "保本出場"

    (trade,) = get_daily_trades(DAY, db)
    assert trade["status"] == "CLOSED"
    assert trade["exit_price"] == 99.9
    assert trade["net_pnl"] == pytest.approx(net(100.0, 101.6, 1500) + net(100.0, 99.9, 1500))


def test_limit_boundaries(tmp_path):
    limits = DailyLimits(db_path=tmp_path / "ledger.sqlite")
    limits.buy_amount = 700_000
    assert limits.block_reason(300_000) is None  # reaching the cap exactly is allowed
    assert limits.block_reason(300_000.01) == BUY_CAP

    limits.buy_amount = 0
    limits.realized_net_pnl = -5_999.99
    assert limits.block_reason(300_000) is None
    limits.realized_net_pnl = -6_000
    assert limits.block_reason(300_000) == LOSS_CIRCUIT_BREAKER


@pytest.mark.parametrize("price", [15.0, 33.35, 99.9, 100.0, 150.5, 299.5, 300.0, 300.5, 450.0, 600.0])
def test_planned_shares_matches_manager_sizing(tmp_path, price):
    manager = PositionManagerV2(db_path=tmp_path / "ledger.sqlite")
    pos = manager.open_position("1101", "S1101", price, f"{DAY}T09:10:00+08:00", "ORB_BREAKOUT", 80.0, ["test"])
    assert pos.shares == planned_shares(price)
