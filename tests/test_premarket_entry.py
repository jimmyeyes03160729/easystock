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
