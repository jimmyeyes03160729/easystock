"""REVENUE_HIST_V1 wrapper: constants rebound, 5-of-7 fold majorities, replication verdict."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'research' / 'revenue_hist_v1'))
import hist_study as H  # noqa: E402

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _restore_rev_study():
    # rev_study is shared with test_revenue_drift; undo configure() after each test.
    saved = dict(vars(H.R))
    yield
    for k, v in saved.items():
        setattr(H.R, k, v)


def _months(tops):
    return [{'fold': y, 'top': t, 'excess': t, 'n_top': 25} for y, t in tops for _ in range(6)]


def test_configure_rebinds_period_and_paths(tmp_path):
    H.configure(tmp_path)
    assert (H.R.FIRST_EVENT, H.R.LAST_EVENT, H.R.CUTOFF) == ('2015-01', '2021-12', '2022-03-31')
    assert H.R.DAILY_DB == str(tmp_path / 'daily' / 'market-daily.sqlite')
    assert H.R.FOLDS[-1] == 2022


def test_fold_majority_needs_five_of_seven_full_years(tmp_path):
    H.configure(tmp_path)
    four = [(2015, 1), (2016, 1), (2017, 1), (2018, 1), (2019, -1), (2020, -1), (2021, -1), (2022, 5)]
    c, _ = H.R.criteria(_months(four))
    assert not c['B'] and not c['D']           # 2022 (one event) cannot supply the fifth year
    five = [(2015, 1), (2016, 1), (2017, 1), (2018, 1), (2019, 1), (2020, -1), (2021, -1)]
    c, _ = H.R.criteria(_months(five))
    assert c['B'] and c['D'] and c['G']


def test_verdict_mapping():
    assert H.verdict('STRONG') == 'REPLICATED'
    assert H.verdict('RELATIVE_ONLY') == 'PARTIAL'
    assert H.verdict('WEAK') == 'NOT_REPLICATED' and H.verdict('INSUFFICIENT') == 'NOT_REPLICATED'
