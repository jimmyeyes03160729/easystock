"""The live adapter must pass the strategy time, never the price, to PositionManager."""
import ast
import inspect
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import Mock

from position_manager import PositionManager

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 7, 9, 40, tzinfo=timezone(timedelta(hours=8)))


def adapter(path=ROOT / 'intraday_live.py'):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'call_manager_strategy_result')
    ns = {'inspect': inspect, 'Any': Any, 'datetime': datetime, 'PositionManager': PositionManager}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(path), 'exec'), ns)
    return ns['call_manager_strategy_result']


def test_open_position_receives_strategy_time_not_price(capsys):
    for path in (ROOT / 'intraday_live.py', ROOT / 'vm_runtime' / 'intraday_live.py'):
        manager = PositionManager(research_mode=True)
        manager.technical_exit_enabled = False
        manager.positions['6257'] = {'current_price': 283.5}
        manager.is_force_exit_time = Mock(return_value=False)
        adapter(path)(manager=manager, symbol='6257', result={}, price=283.5, dt=NOW)
        manager.is_force_exit_time.assert_called_once_with(NOW)
    assert '[WARN] on_strategy_result' not in capsys.readouterr().out


def test_force_exit_time_closes_through_adapter():
    manager = PositionManager(research_mode=True)
    manager.positions['6257'] = {'current_price': 283.5}
    manager.close_position = Mock(return_value={'type': 'EXIT'})
    late = NOW.replace(hour=12, minute=56)
    assert adapter()(manager=manager, symbol='6257', result={}, price=283.5, dt=late) == {'type': 'EXIT'}
    assert manager.close_position.call_args.kwargs['exit_time'] == late
