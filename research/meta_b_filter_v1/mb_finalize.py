#!/usr/bin/env python3
"""META_B_FILTER_V1 Stage 1: expanding walk-forward over the five FOLD_WINDOWS, frozen criteria A-E/G, outputs."""
import gzip, hashlib, json, os, sys, tarfile
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import mb_common as M  # noqa: E402
M.repo_first()
from daytrade_learning.event_audit import timebase as TB  # noqa: E402
import mb_stats as ST  # noqa: E402

WORK, OUT = ROOT / 'work', ROOT / 'output'


class Filter:
    """L2 logistic regression (C=1.0, lbfgs) on standardized features, threshold chosen on the inner split only."""

    def __init__(self, train):
        import numpy as np
        from sklearn.linear_model import LogisticRegression
        self.np = np
        rows = [f for f in train if ST.complete(f)]
        self.n_train = len(rows)
        self.n_pos = sum(f['quote']['bps'] > 0 for f in rows)
        self.status = 'ESTIMATED' if self.n_train >= ST.MIN_TRAIN_EVENTS and self.n_pos >= ST.MIN_TRAIN_POSITIVES else 'NOT_ESTIMABLE'
        if self.status != 'ESTIMATED':
            return
        inner_fit, inner_val = ST.inner_split(rows)
        self.tau = 0.50
        if inner_fit and inner_val and len({f['quote']['bps'] > 0 for f in inner_fit}) == 2:
            m = self._fit(inner_fit, LogisticRegression)
            self.tau = ST.choose_tau(self._prob(m, inner_val), [f['quote']['bps'] for f in inner_val])
        self.model = self._fit(rows, LogisticRegression)

    def _fit(self, rows, cls):
        X = self.np.array([ST.vector(f) for f in rows], dtype=float)
        y = self.np.array([1 if f['quote']['bps'] > 0 else 0 for f in rows])
        mu, sd = X.mean(axis=0), X.std(axis=0)
        sd[sd == 0] = 1.0
        clf = cls(penalty='l2', C=1.0, solver='lbfgs', max_iter=1000).fit((X - mu) / sd, y)
        return clf, mu, sd

    def _prob(self, m, rows):
        clf, mu, sd = m
        if not rows:
            return []
        X = self.np.array([ST.vector(f) for f in rows], dtype=float)
        return [float(p) for p in clf.predict_proba((X - mu) / sd)[:, 1]]

    def accept_map(self, rows):
        ok = [f for f in rows if ST.complete(f)]
        probs = self._prob(self.model, ok)
        return {id(f): bool(p >= self.tau) for f, p in zip(ok, probs)}

    def coefficients(self):
        clf = self.model[0]
        return {'intercept': float(clf.intercept_[0]), 'tau': self.tau,
                **{k: float(c) for k, c in zip(ST.FEATURES, clf.coef_[0])}}


def load():
    firings, meta = [], {'days': 0, 'cnt': {}, 'failed': 0}
    for p in sorted(WORK.glob('*.json.gz')):
        d = json.loads(gzip.decompress(p.read_bytes()))
        if d['date'] > M.STAGE1_LAST_DAY:
            raise SystemExit('stage 1 must not read days after ' + M.STAGE1_LAST_DAY)
        meta['days'] += 1
        meta['failed'] += len(d['failed'])
        for k, v in d['cnt'].items():
            meta['cnt'][k] = meta['cnt'].get(k, 0) + v
        for f in d['firings']:
            f['date'] = d['date']
            firings.append(f)
    return firings, meta


def describe(rows):
    q = [f['quote']['bps'] for f in rows]
    t = [f['trade']['bps'] for f in rows]
    return {'n': len(rows), 'win_rate': (sum(x > 0 for x in q) / len(q)) if q else None,
            'mean_quote_bps': ST.mean(q), 'mean_trade_bps': ST.mean(t),
            'orb_n': sum(f['signal_type'] == 'ORB_BREAKOUT' for f in rows),
            'orb_mean_quote_bps': ST.mean([f['quote']['bps'] for f in rows if f['signal_type'] == 'ORB_BREAKOUT']),
            'pullback_mean_quote_bps': ST.mean([f['quote']['bps'] for f in rows if f['signal_type'] == 'VWAP_PULLBACK'])}


def main():
    firings, meta = load()
    events = ST.event_level(firings)
    folds, pooled_rows, pooled_acc, all_raw, accepted_raw = [], [], [], [], set()
    for fid, a, b in TB.FOLD_WINDOWS:
        train = [f for f in events if f['date'] < a]
        test = [f for f in events if a <= f['date'] <= b]
        raw = [f for f in firings if a <= f['date'] <= b]
        flt = Filter(train)
        row = {'fold': fid, 'from': a, 'through': b, 'status': flt.status, 'n_train': flt.n_train,
               'n_train_positive': flt.n_pos, 'n_all': len(test), 'all_mean_bps': ST.mean([f['quote']['bps'] for f in test]),
               'unfiltered': describe(test), 'portfolio_unfiltered': ST.portfolio(raw, lambda f: True)}
        if flt.status == 'ESTIMATED':
            acc = flt.accept_map(test)
            acc_raw = flt.accept_map(raw)
            mask = [acc.get(id(f), False) for f in test]
            chosen = [f for f, m in zip(test, mask) if m]
            ex, se, t = ST.excess_t([(f['date'], f['quote']['bps']) for f in test], mask)
            row.update(tau=flt.tau, n_filtered=len(chosen), filtered_mean_bps=ST.mean([f['quote']['bps'] for f in chosen]),
                       filtered=describe(chosen), excess_bps=ex, excess_se=se, excess_t=t,
                       portfolio_filtered=ST.portfolio(raw, lambda f, acc_raw=acc_raw: acc_raw.get(id(f), False)),
                       coefficients=flt.coefficients())
            pooled_rows += [(f['date'], f['quote']['bps']) for f in test]
            pooled_acc += mask
            all_raw += raw
            accepted_raw |= {id(f) for f in raw if acc_raw.get(id(f), False)}
        else:
            row.update(n_filtered=0, filtered_mean_bps=None)
        folds.append(row)
    ex, se, t = ST.excess_t(pooled_rows, pooled_acc) if pooled_rows else (None, None, None)
    chosen = [b for (_, b), m in zip(pooled_rows, pooled_acc) if m]
    agg = {'n_all': len(pooled_rows), 'n_filtered': len(chosen), 'all_mean_bps': ST.mean([b for _, b in pooled_rows]),
           'filtered_mean_bps': ST.mean(chosen), 'excess_bps': ex, 'excess_se': se, 'excess_t': t,
           'portfolio_unfiltered': ST.portfolio([f for f in firings if TB.fold_for_date(f['date']) >= 1], lambda f: True),
           'portfolio_filtered': ST.portfolio(all_raw, lambda f: id(f) in accepted_raw)}
    crit = {k: bool(v) for k, v in ST.criteria(folds, agg).items()}
    decision = ST.classify(crit)
    OUT.mkdir(exist_ok=True)
    result = {'preregistration': 'META_B_FILTER_V1', 'stage': 1, 'decision': decision, 'criteria': crit,
              'aggregate': agg, 'folds': folds, 'inputs': meta, 'n_firings': len(firings), 'n_events': len(events),
              'code_commit': os.environ.get('MB_CODE_COMMIT', 'unknown')}
    (OUT / 'META_B_FILTER_V1_STAGE1.json').write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str))
    lines = [f"META_B_FILTER_V1 stage 1 decision: {decision}",
             'criteria: ' + ' '.join(f"{k}={'T' if v else 'F'}" for k, v in crit.items()),
             f"aggregate: all {agg['n_all']} mean {fmt(agg['all_mean_bps'])} bps | filtered {agg['n_filtered']} mean "
             f"{fmt(agg['filtered_mean_bps'])} bps | excess {fmt(agg['excess_bps'])} t {fmt(agg['excess_t'])}",
             f"portfolio TWD per 1M buys: unfiltered {fmt(agg['portfolio_unfiltered']['net_twd_per_1m_buys'])} "
             f"({agg['portfolio_unfiltered']['trades']} trades) | filtered {fmt(agg['portfolio_filtered']['net_twd_per_1m_buys'])} "
             f"({agg['portfolio_filtered']['trades']} trades)"]
    for r in folds:
        lines.append(f"fold {r['fold']} {r['status']}: all {r['n_all']} {fmt(r['all_mean_bps'])} bps | filtered "
                     f"{r['n_filtered']} {fmt(r.get('filtered_mean_bps'))} bps | t {fmt(r.get('excess_t'))} | tau {r.get('tau')} | "
                     f"1M unfiltered {fmt(r['portfolio_unfiltered']['net_twd_per_1m_buys'])} filtered "
                     f"{fmt((r.get('portfolio_filtered') or {}).get('net_twd_per_1m_buys'))}")
    (OUT / 'FINAL_LINES.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    bundle = OUT / 'meta_b_filter_v1_stage1_bundle.tar.gz'
    with tarfile.open(bundle, 'w:gz') as tar:
        for p in sorted(OUT.glob('*')):
            if p != bundle:
                tar.add(p, arcname=p.name)
    (OUT / 'BUNDLE_SHA256').write_text(hashlib.sha256(bundle.read_bytes()).hexdigest() + '\n')
    print('\n'.join(lines))


def fmt(x):
    return 'NA' if x is None else f'{x:.2f}'


if __name__ == '__main__':
    main()
