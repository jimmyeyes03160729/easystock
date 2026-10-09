"""META_B_FILTER_V1 shared setup: pinned sources, radar thresholds, paths. Research only."""
from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent.parent
PINNED = ROOT / 'pinned' / 'runway_v2'   # byte-identical runway_v2 rule files at 6aa1e5a (git show)
PIN_PKG = 'mb_pinned_runway_v2'          # private package name, so the repo's runway_v2 is never shadowed

# Production radar thresholds, pinned from the VM service environment (/home/ubuntu/easystock/.env, read 2026-10-08;
# the file was last modified 2026-10-08 06:53, so the 2026-10-02 values are not independently verified).
# They must be in os.environ before intraday_live is imported, because it reads them at import time.
RADAR_ENV = {
    'LIVE_RADAR_MIN_60S_VOLUME': '10',
    'LIVE_RADAR_MIN_60S_AMOUNT': '1500000',
    'LIVE_RADAR_MIN_SURGE': '1.4',
    'LIVE_RADAR_MIN_BUY_RATIO': '0.52',
    'LIVE_RADAR_MIN_CLASSIFIED_RATIO': '0.35',
    'LIVE_RADAR_MIN_PRICE_CHANGE_60_PCT': '-0.10',
}
RADAR_TOP_N = 30          # live recommendation_limit(): admin max_recommendations default 30 = RADAR_TOP_N default

# Git blob hashes frozen in the preregistration (runway_v2 at 6aa1e5a).
PINNED_BLOBS = {
    'strategy.py': 'ebcd8a4c5ec414b8f2c5281021de5da4639e04b3',
    'manager.py': '58f9bc7a033ac9db5c8d316dca9738545b41136d',
    'config.py': '918711c038ec37bc792db56d3ab4925b9fc249e5',
    'orderbook.py': '0030b447291db53e1f9798d7ba7555bed9319572',
}
RUNWAY_ENV_PREFIX = 'RUNWAY_V2_'

STAGE1_LAST_DAY = '2026-08-27'


def git_blob_sha(path: Path) -> str:
    data = Path(path).read_bytes()
    return hashlib.sha1(b'blob %d\0' % len(data) + data).hexdigest()


def repo_first():
    """This checkout first on sys.path (the VM production checkout may also be on it)."""
    if str(REPO) in sys.path:
        sys.path.remove(str(REPO))
    sys.path.insert(0, str(REPO))


def prepare_worker_environment():
    """Worker process only: pin the radar environment and drop runway overrides before anything reads them."""
    for k in [k for k in os.environ if k.startswith(RUNWAY_ENV_PREFIX)]:
        del os.environ[k]
    os.environ.update(RADAR_ENV)
    repo_first()


def pinned(name: str):
    """A module of the pinned runway_v2 copy, loaded as a private package (relative imports stay inside it)."""
    if PIN_PKG not in sys.modules:
        spec = importlib.util.spec_from_file_location(PIN_PKG, PINNED / '__init__.py',
                                                      submodule_search_locations=[str(PINNED)])
        pkg = importlib.util.module_from_spec(spec)
        sys.modules[PIN_PKG] = pkg
        spec.loader.exec_module(pkg)
    return importlib.import_module(PIN_PKG + '.' + name)


def verify_pins():
    """Fail closed unless the pinned rule files match the preregistered blobs."""
    seen = {}
    for rel, want in PINNED_BLOBS.items():
        mod = pinned(rel[:-3])
        path = Path(mod.__file__).resolve()
        got = git_blob_sha(path)
        seen[rel] = got
        if path.parent != PINNED.resolve() or got != want:
            raise RuntimeError(f'pinned_source_mismatch:{rel}:{got}')
    return {'runway_root': str(PINNED), 'blobs': seen}


def radar_functions():
    import intraday_live as L
    for k, v in RADAR_ENV.items():
        attr = 'RADAR_' + k[len('LIVE_RADAR_'):]
        if abs(float(getattr(L, attr)) - float(v)) > 1e-12:
            raise RuntimeError('radar_env_not_applied:' + attr)
    return L.compute_volume_surge_metrics, L.qualifies_volume_surge, L.score_volume_surge, {
        'intraday_live': git_blob_sha(Path(L.__file__)), 'history_seconds': L.RADAR_HISTORY_SECONDS,
        'baseline_windows': L.RADAR_BASELINE_WINDOWS, **RADAR_ENV}


def module_files():
    """Where the shared modules were actually imported from, with their blob hashes (manifest evidence)."""
    out = {}
    for name in ('daytrade_learning.event_audit.timebase', 'daytrade_learning.event_audit.bars', 'paper_execution',
                 'intraday_live', PIN_PKG + '.strategy', 'pf_run', 'pf_fill', 'hv60_common'):
        mod = sys.modules.get(name)
        if mod is not None and getattr(mod, '__file__', None):
            out[name] = {'file': mod.__file__, 'blob': git_blob_sha(Path(mod.__file__))}
    return out


def log(obj):
    print(json.dumps(obj, ensure_ascii=False), flush=True)
