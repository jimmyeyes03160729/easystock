"""Exact, reviewable patch for the separately deployed eight-method observer."""
from pathlib import Path


def patched_source(source):
    edits=[
        ("if item.get('kind') != 'sample':", "if item.get('kind') not in ('sample', 'opening_boundary'):"),
        ("name = '發行量加權股價指數' if r['symbol'] == 'IX0001' else '櫃買指數'", "name = 'TAIEX' if r['symbol'] == 'IX0001' else 'TPEX'"),
        ("    diagnostics += enrich_daily(rows, DAILY, now)",
         "    from market_data.opening_observations import merge_indices\n"
         "    market = Path(os.getenv('EASYSTOCK_MARKET_DATA_DIR', '/home/ubuntu/easystock-market-data'))\n"
         "    diagnostics += merge_indices(rows, market / 'dataset' / (now.date().isoformat()+'.jsonl'), now)\n"
         "    diagnostics += enrich_daily(rows, DAILY, now)"),
        ("journal 每五分鐘取樣，邊界缺 Tick 不補值。", "journal 加開盤邊界成交與既有指數快照，缺 Tick 不補值。")]
    for old,new in edits:
        if source.count(old)!=1:raise ValueError('observer_source_changed: '+old[:50])
        source=source.replace(old,new,1)
    return source


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('source');p.add_argument('output');a=p.parse_args()
    source=Path(a.source).read_text(encoding='utf-8');Path(a.output).write_text(patched_source(source),encoding='utf-8')
