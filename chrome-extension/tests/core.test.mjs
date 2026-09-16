import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { taipei, marketOpen, fresh, config, signal, watchlist, ledger, canNotify, isVIP, sha256, defaultState, chartURL, TTL } from '../core.js';
const at = s => Date.parse(s);
const now = at('2026-09-17T09:30:00+08:00');
const sample = { id: 'a', symbol: '2330', market: 'TW', name: '台積電', price: 1000, change_pct: 1, reason: '爆量', generated_at: '2026-09-17T09:29:00+08:00', quote_at: '2026-09-17T09:29:00+08:00' };
test('Taipei sessions, weekend, holidays, exact close and midnight', () => {
  assert.equal(marketOpen(at('2026-09-17T08:59:59+08:00')), false);
  assert.equal(marketOpen(at('2026-09-17T09:00:00+08:00')), true);
  assert.equal(marketOpen(at('2026-09-17T13:29:59+08:00')), true);
  assert.equal(marketOpen(at('2026-09-17T13:30:00+08:00')), false);
  assert.equal(marketOpen(at('2026-09-19T10:00:00+08:00')), false);
  assert.equal(marketOpen(now, ['2026-09-17']), false);
  assert.equal(taipei(at('2026-09-16T16:00:00Z')).date, '2026-09-17');
});
test('freshness rejects future, naive, stale and invalid timestamps', () => {
  assert.equal(fresh(sample.quote_at, now), true);
  for (const stamp of ['2026-09-17T09:31:00+08:00', '2026-09-17T09:29:00', '2026-09-16T09:29:00+08:00', 'garbage']) assert.equal(fresh(stamp, now), false);
  assert.equal(fresh(sample.quote_at, now + TTL), false);
});
test('signal schema blocks incomplete or dangerous values', () => {
  assert.equal(signal(sample, 'daytrade', now).symbol, '2330');
  for (const patch of [{ market: 'EVIL' }, { symbol: '../x' }, { price: 0 }, { change_pct: null }, { id: '' }, { reason: 123 }, { generated_at: '2000-01-01T09:00:00+08:00' }]) assert.equal(signal({ ...sample, ...patch }, 'daytrade', now), null);
  assert.equal(signal({ ...sample, change_pct: null }, 'daytrade', now, true).change_pct, null);
});
test('config is data only; payment URLs cannot execute script', () => {
  const base = { schema_version: 1, global_vip_switch: false, vip_keys_hash: [], bounce_strategy_signals: [] };
  assert.equal(config(base).payment_gateway_url, '');
  for (const url of ['javascript:alert(1)', 'http://example.com', 'https://user:pass@example.com']) assert.throws(() => config({ ...base, payment_gateway_url: url }));
  assert.throws(() => config({ ...base, global_vip_switch: 'true' }));
  assert.throws(() => config({ ...base, vip_keys_hash: ['VIP888'] }));
});
test('watchlist is bounded, typed, deduplicated, and export-safe', () => {
  const s = defaultState().stocks[0];
  assert.deepEqual(watchlist([s]), [s]);
  for (const input of [[s, s], [{ ...s, symbol: '__proto__' }], [{ ...s, groups: [] }], [{ ...s, market: 'X' }], Array(101).fill(s)]) assert.throws(() => watchlist(input));
  assert.equal(chartURL({ symbol: '8299', market: 'TWO' }), 'https://tw.stock.yahoo.com/quote/8299.TWO');
});
test('quota, cooldown, stable event id and next-day reset', () => {
  const s = signal(sample, 'daytrade', now), l = ledger(null, now);
  assert.equal(canNotify(s, l, now, false), true);
  l.count = 3; assert.equal(canNotify(s, l, now, false), false); assert.equal(canNotify(s, l, now, true), true);
  l.last['2330'] = now; assert.equal(canNotify(s, l, now + 1799999, true), false); assert.equal(canNotify(s, l, now + 1800000, true), true);
  l.seen['daytrade:a'] = true; assert.equal(canNotify(s, l, now + 3600000, true), false);
  l.ignored['2330'] = true; assert.equal(ledger(l, now + 86400000).count, 0);
  assert.equal(canNotify(s, ledger(l, now + 86400000), now + 86400000, false), true);
});
test('VIP revalidated against config, not a stored boolean', async () => {
  const hash = await sha256('VIP888');
  assert.match(hash, /^[0-9a-f]{64}$/);
  assert.equal(isVIP({ global_vip_switch: false, vip_keys_hash: [hash] }, hash), true);
  assert.equal(isVIP({ global_vip_switch: false, vip_keys_hash: [] }, hash), false);
  assert.equal(isVIP({ global_vip_switch: true, vip_keys_hash: [] }, ''), true);
  assert.equal(isVIP(null, hash), false);
});
test('production has narrow permissions, packaged resources, no test VIP', async () => {
  const m = JSON.parse(await readFile(new URL('../manifest.json', import.meta.url)));
  assert.equal(m.manifest_version, 3);
  assert.deepEqual(m.permissions, ['storage', 'alarms', 'notifications']);
  assert.equal(m.host_permissions.some(x => x.includes('<all_urls>')), false);
  const html = await readFile(new URL('../popup.html', import.meta.url), 'utf8');
  assert.doesNotMatch(html, /<script[^>]+src="https?:/);
  const cfg = JSON.parse(await readFile(new URL('../config.json', import.meta.url)));
  assert.equal(cfg.vip_keys_hash.includes(await sha256('VIP888')), false);
  assert.deepEqual(cfg.bounce_strategy_signals, []);
});
