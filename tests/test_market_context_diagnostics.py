import json
from datetime import datetime, timedelta
from unittest.mock import patch
from market_data.context import diagnostics
from market_data.health import TPE


def test_diagnostics_stale_closed_future_and_secret_allowlist(tmp_path, monkeypatch):
    monkeypatch.setenv('EASYSTOCK_MARKET_DATA_DIR', str(tmp_path))
    now=datetime(2026,10,7,10,tzinfo=TPE)
    payload={'generated_at':now.isoformat(),'secret':'do-not-display',
             'breadth':{'source':'esun','symbol':'TSE+OTC','quote_at':now.isoformat(),'fresh':True,'valid':True,'status':'OK','advancers':2,'password':'do-not-display'},
             'sectors':{'status':'OK','rows':[{'quote_at':now.isoformat(),'source':'esun','valid':True,'fresh':True,'return_day':1}]},
             'rotation':{'type':'sector_rotation_proxy','quote_at':now.isoformat(),'valid':True,'rotation_state':'MIXED'}}
    (tmp_path/'context.json').write_text(json.dumps(payload),encoding='utf8')
    with patch('market_data.health.market_session',return_value='OPEN'):
        current=diagnostics(now);assert current['breadth']['advancers']==2;assert 'do-not-display' not in json.dumps(current)
        for at in [now+timedelta(seconds=91),now-timedelta(seconds=1),now+timedelta(days=1)]:
            stale=diagnostics(at);assert stale['breadth']['advancers'] is None;assert stale['rotation']['rotation_state']=='UNKNOWN'
    with patch('market_data.health.market_session',return_value='CLOSED'):
        assert diagnostics(now)['sectors']['rows'][0]['return_day'] is None


def test_market_context_is_not_wired_to_production_strategy():
    from pathlib import Path
    for name in ('intraday_live.py','position_manager.py','market_risk.py'):
        path=Path(name)
        if path.exists():
            code=path.read_text(encoding='utf8')
            assert 'sector_rotation_proxy' not in code
            assert 'market_data.context import diagnostics' not in code


def test_new_admin_runtime_files_do_not_drift():
    from pathlib import Path
    for name in ('store.py','web.py','order_service.py','broker_read.py','live_console.py',
                 'static/index.html','static/admin.js','static/admin.css','static/live-console.js'):
        assert Path('easystock_admin',name).read_bytes() == Path('vm_runtime/easystock_admin',name).read_bytes()
