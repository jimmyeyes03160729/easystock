"""Verify routing only; do not run Firebase, broker or LINE code."""
import importlib.util
from pathlib import Path
import sys
from unittest.mock import patch

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('premarket_entry_test', root/'premarket_ai.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
before = list(sys.path)
try:
    with patch('dotenv.load_dotenv') as dotenv, patch.object(module.runpy, 'run_path') as run:
        module.main()
        assert sys.path[0] == str(root/'vm_runtime')
        dotenv.assert_called_once_with(root/'.env')
        run.assert_called_once_with(str(root/'vm_runtime/premarket_ai.py'), run_name='__main__')
finally:
    sys.path[:] = before
print('PASS premarket entry: runtime imports and existing env location, no external calls')

# Loading the runtime calendar by its public module name must resolve the root
# implementation without recursively importing the runtime wrapper itself.
calendar_spec = importlib.util.spec_from_file_location('market_calendar', root/'vm_runtime/market_calendar.py')
calendar = importlib.util.module_from_spec(calendar_spec)
with patch.dict(sys.modules, {'market_calendar': calendar}):
    calendar_spec.loader.exec_module(calendar)
    assert callable(calendar.is_market_open)
    assert calendar.now_tpe().tzinfo is not None
