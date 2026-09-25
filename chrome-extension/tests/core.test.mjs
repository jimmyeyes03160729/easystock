import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { taipei, marketOpen, fresh, config, signal, watchlist, ledger, canNotify, isVIP, sha256, defaultState, chartURL, TTL, formatTelegramEntry, formatTelegramExit, formatTelegramRebound, matchFilter, BUILTIN_STOCKS, searchStocks, searchOnlineStocks, calcChangePct, BROKERS, getBroker } from '../core.js';
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
test('telegram format generates matching entry and exit messages', () => {
  const entryMsg = formatTelegramEntry({
    symbol: '2330', name: '台積電', entry_price: 1000, entry_score: '0.88',
    entry_vwap: 996.5, entry_reasons: ['量價突破', '站在VWAP之上'],
    stop_price: 985, take_profit_price: 1030
  });
  assert.match(entryMsg, /🚀【當沖進場訊號】/);
  assert.match(entryMsg, /2330 台積電/);
  assert.match(entryMsg, /訊號價：1000\.00/);
  assert.match(entryMsg, /分數：0\.88/);
  assert.match(entryMsg, /✓ 量價突破/);
  assert.match(entryMsg, /停損參考：985\.00/);
  assert.match(entryMsg, /狀態：OPEN/);

  const exitMsg = formatTelegramExit({
    symbol: '2330', name: '台積電', entry_price: 1000, exit_price: 1025,
    pnl_pct: 2.5, mfe_pct: 3.0, mae_pct: -0.5, duration_seconds: 1800,
    exit_reason: '12:55當沖強制出場'
  });
  assert.match(exitMsg, /✅【當沖出場】/);
  assert.match(exitMsg, /2330 台積電/);
  assert.match(exitMsg, /訊號進場：1000\.00/);
  assert.match(exitMsg, /訊號出場：1025\.00/);
  assert.match(exitMsg, /報酬：\+2\.50%/);
  assert.match(exitMsg, /最高浮盈：\+3\.00%/);
  assert.match(exitMsg, /最大浮虧：-0\.50%/);
  assert.match(exitMsg, /持有時間：30分0秒/);
  assert.match(exitMsg, /出場原因：12:55當沖強制出場/);
});
test('matchFilter supports all-pass, price-range, and change-percentage criteria', () => {
  const allSettings = { filterMode: 'all', minPrice: 100, maxPrice: 500, minChangePct: 3.0 };
  assert.equal(matchFilter(50, 1.0, allSettings), true);

  const customSettings = { filterMode: 'custom', minPrice: 50, maxPrice: 200, minChangePct: 2.0 };
  assert.equal(matchFilter(100, 2.5, customSettings), true);
  assert.equal(matchFilter(40, 2.5, customSettings), false);
  assert.equal(matchFilter(250, 2.5, customSettings), false);
  assert.equal(matchFilter(100, 1.5, customSettings), false);
});
test('telegram rebound formatting outputs complete signal message', () => {
  const reboundMsg = formatTelegramRebound({
    symbol: '2330', name: '台積電', price: 1000, change_pct: 2.5, reason: '底部出量紅K確認'
  });
  assert.match(reboundMsg, /🛡️【觸底反彈訊號】/);
  assert.match(reboundMsg, /2330 台積電/);
  assert.match(reboundMsg, /現價：1000\.00 元｜漲跌：\+2\.50%/);
  assert.match(reboundMsg, /底部出量紅K確認/);
  assert.match(reboundMsg, /狀態：REBOUND/);
});
test('searchStocks finds stocks by Chinese name, code, prefix, and dynamic codes', () => {
  assert.ok(BUILTIN_STOCKS.length >= 70);
  const byName = searchStocks('台積電');
  assert.equal(byName[0].symbol, '2330');
  assert.equal(byName[0].name, '台積電');

  const byCode = searchStocks('2330');
  assert.equal(byCode[0].symbol, '2330');

  const partial = searchStocks('聯');
  assert.ok(partial.some(s => s.symbol === '2454' && s.name === '聯發科'));
  assert.ok(partial.some(s => s.symbol === '2303' && s.name === '聯電'));

  const unknownStock = searchStocks('1101');
  assert.equal(unknownStock[0].symbol, '1101');
  assert.equal(unknownStock[0].market, 'TW');

  const otcStock = searchStocks('6285');
  assert.equal(otcStock[0].symbol, '6285');
  assert.equal(otcStock[0].market, 'TWO');

  const withExtra = searchStocks('微星', { '2377': { name: '微星' } });
  assert.equal(withExtra[0].symbol, '2377');
  assert.equal(withExtra[0].name, '微星');
});
test('searchOnlineStocks queries online autocomplete API and registers results', async () => {
  const origFetch = globalThis.fetch;
  globalThis.fetch = async url => {
    assert.ok(url.includes('AutocompleteService'));
    return new Response(JSON.stringify({
      ResultSet: {
        Result: [
          { symbol: '2645.TW', name: '長榮航太', typeDisp: '權益' },
          { symbol: '068299.TW', name: '長榮航太認購', typeDisp: '認購' },
          { symbol: '8069.TWO', name: '元太', typeDisp: '權益' }
        ]
      }
    }));
  };
  try {
    const list = await searchOnlineStocks('長榮航太');
    assert.equal(list.length, 2);
    assert.equal(list[0].symbol, '2645');
    assert.equal(list[0].name, '長榮航太');
    assert.equal(list[0].market, 'TW');
    assert.equal(list[1].symbol, '8069');
    assert.equal(list[1].market, 'TWO');

    const syncFind = searchStocks('長榮航太');
    assert.ok(syncFind.some(s => s.symbol === '2645' && s.name === '長榮航太'));
  } finally {
    globalThis.fetch = origFetch;
  }
});

test('searchOnlineStocks excludes 5-digit convertible bonds and prefers TW over duplicate TWO', async () => {
  const origFetch = globalThis.fetch;
  globalThis.fetch = async () => {
    return new Response(JSON.stringify({
      ResultSet: {
        Result: [
          { symbol: '6862.TW', name: '三集瑞-KY', typeDisp: '權益' },
          { symbol: '68621.TWO', name: '三集瑞一KY', typeDisp: '債券' },
          { symbol: '6862.TWO', name: '三集瑞-KY(舊櫃)', typeDisp: '權益' }
        ]
      }
    }));
  };
  try {
    const list = await searchOnlineStocks('6862');
    assert.equal(list.length, 1);
    assert.equal(list[0].symbol, '6862');
    assert.equal(list[0].name, '三集瑞-KY');
    assert.equal(list[0].market, 'TW');
  } finally {
    globalThis.fetch = origFetch;
  }
});

test('calcChangePct calculates percentage from change_pct, change, or previous_close', () => {
  assert.equal(calcChangePct({ change_pct: 1.5 }), 1.5);
  assert.equal(calcChangePct({ price: 105, previous_close: 100 }), 5.0);
  assert.equal(calcChangePct({ price: 105, change: 5 }), 5.0);
  assert.equal(calcChangePct(null), null);
  assert.equal(calcChangePct({}), null);
});

test('BROKERS definitions, URL generation, and fallback', () => {
  assert.ok(BROKERS.length >= 6);
  const sinopac = getBroker('sinopac');
  assert.equal(sinopac.id, 'sinopac');
  assert.equal(sinopac.icon, '🔴');
  assert.ok(sinopac.url('2330').includes('TradingCenter_TWStocks_Stock/?code=2330'));

  const fubon = getBroker('fubon');
  assert.equal(fubon.id, 'fubon');
  assert.equal(fubon.icon, '🔵');
  assert.ok(fubon.url('2454').includes('ZCA.djhtm?a=2454'));

  const yuanta = getBroker('yuanta');
  assert.equal(yuanta.id, 'yuanta');
  assert.ok(yuanta.url('2603').includes('eyuanta'));

  const fallback = getBroker('unknown_broker');
  assert.equal(fallback.id, 'sinopac');
});


