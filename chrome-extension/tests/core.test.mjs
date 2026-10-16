import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { taipei, marketOpen, fresh, normalizeQuoteTimestamp, formatTaipeiQuoteTime, config, signal, watchlist, ledger, canNotify, isVIP, sha256, defaultState, chartURL, TTL, formatTelegramEntry, formatTelegramExit, matchFilter, BUILTIN_STOCKS, searchStocks, searchOnlineStocks, calcChangePct, BROKERS, getBroker, sparklineSessionX, buildPartialDailyBar, resolveStockInput, sparkForQuote } from '../core.js';
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
test('quote timestamps are normalized once into Taiwan time', () => {
  const sampleNow = at('2026-09-29T09:20:00+08:00');
  const local = normalizeQuoteTimestamp('09:15:30', sampleNow);
  assert.equal(local, '2026-09-29T09:15:30+08:00');
  assert.equal(formatTaipeiQuoteTime(local), '09:15');
  const utc = normalizeQuoteTimestamp('2026-09-29T01:15:30Z', sampleNow);
  assert.equal(formatTaipeiQuoteTime(utc), '09:15');
});

test('1.05 sparkline uses fixed Taiwan 09:00-13:30 time axis', () => {
  const ts = value => Date.parse(value) / 1000;
  assert.equal(sparklineSessionX({ timestamp: ts('2026-09-30T09:00:00+08:00') }), 2);
  assert.equal(sparklineSessionX({ timestamp: ts('2026-09-30T09:17:00+08:00') }), 5.3);
  assert.equal(sparklineSessionX({ timestamp: ts('2026-09-30T13:30:00+08:00') }), 54);
  assert.equal(sparklineSessionX({ timestamp: ts('2026-09-30T08:59:00+08:00') }), null);
});
test('list sparkline follows the clock: 10:00 data stays on the left part of a 09:00–13:30 axis', () => {
  const ts = value => Date.parse(value) / 1000;
  const q = { price: 103, quote_at: '2026-09-30T10:07:00+08:00', spark: [
    { close: 101, timestamp: ts('2026-09-30T09:30:00+08:00') },
    { close: 100, timestamp: ts('2026-09-30T09:00:00+08:00') },
    { close: 102, timestamp: ts('2026-09-30T09:45:00+08:00') }
  ] };
  const pts = sparkForQuote(q);
  assert.deepEqual(pts.map(p => p.close), [100, 101, 102, 103], 'sorted by time, ends at the current quote');
  const xs = pts.map(p => sparklineSessionX(p));
  assert.equal(xs[0], 2, '09:00 at the left edge');
  assert.ok(xs.at(-1) < 15, `10:07 is ~25% across, not stretched to the right edge (x=${xs.at(-1)})`);
  for (let i = 1; i < xs.length; i++) assert.ok(xs[i] > xs[i - 1], 'x increases with time');
  // After the close, the line ends at 13:30 at most.
  const closed = sparkForQuote({ ...q, quote_at: '2026-09-30T14:05:00+08:00' });
  assert.equal(closed.length, 3, 'a quote outside the session adds no point');
});

test('1.05 partial daily K only aggregates valid bars from Taiwan today', () => {
  const rows = [
    { date: '2026-09-29', open: 99, high: 100, low: 98, close: 99, volume: 10 },
    { date: '2026-09-30', open: 100, high: 103, low: 99, close: 102, volume: 20 },
    { date: '2026-09-30', open: 102, high: 105, low: 101, close: 104, volume: 30 }
  ];
  assert.deepEqual(buildPartialDailyBar(rows, '2026-09-30'), {
    time: '2026-09-30', open: 100, high: 105, low: 99, close: 104, volume: 50, partial: true
  });
  assert.equal(buildPartialDailyBar(rows, '2026-10-01'), null);
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
  assert.equal(defaultState().settings.darkMode, false);
  assert.equal(defaultState().settings.colorMode, 'redgreen');
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
  assert.equal(m.version, '2.0.0');
  assert.equal(m.version_name, '2.0');
  // 2.0 adds only `identity` (no install warning); no new host permission, so 1.05 users are not
  // re-prompted. Identity Toolkit is reached via CORS without a host permission.
  assert.deepEqual(m.permissions, ['storage', 'alarms', 'notifications', 'identity']);
  assert.equal(m.host_permissions.some(x => x.includes('<all_urls>')), false);
  assert.equal(m.host_permissions.length, 6);
  // The source manifest may carry the public store key (unpacked loads get the store ID); the
  // production build strips it — verified on dist/production in vm.test and by package.mjs.
  assert.equal(m.content_security_policy.extension_pages, "script-src 'self'; object-src 'none'; base-uri 'none'");
  // auth-config.json may only hold public identifiers.
  const auth = JSON.parse(await readFile(new URL('../auth-config.json', import.meta.url), 'utf8'));
  assert.deepEqual(Object.keys(auth).sort(), ['_comment', 'database_url', 'extension_id', 'extension_public_key', 'firebase_api_key', 'firebase_project_id', 'oauth_client_id']);
  assert.match(auth.oauth_client_id, /^$|^[0-9]+-[a-z0-9]+\.apps\.googleusercontent\.com$/);
  // The source manifest carries the same real client ID (never a placeholder), so any build can sign in.
  if (m.oauth2) {
    assert.equal(m.oauth2.client_id, auth.oauth_client_id);
    assert.deepEqual(m.oauth2.scopes, ['openid', 'email', 'profile']);
  }
  if (m.key) assert.equal(m.key, auth.extension_public_key, 'source key is the store public key');
  const { _comment, ...values } = auth;
  assert.doesNotMatch(JSON.stringify(values), /secret|PRIVATE KEY|refresh_token/i);
  const html = await readFile(new URL('../popup.html', import.meta.url), 'utf8');
  assert.doesNotMatch(html, /<script[^>]+src="https?:/);
  const cfg = JSON.parse(await readFile(new URL('../config.json', import.meta.url)));
  assert.equal(cfg.vip_keys_hash.includes(await sha256('VIP888')), false);
  assert.equal(Object.prototype.hasOwnProperty.call(cfg, 'bounce_strategy_signals'), false);
});
test('telegram format generates matching entry and exit messages', () => {
  const entryMsg = formatTelegramEntry({
    symbol: '2330', name: '台積電', entry_price: 1000, entry_score: '0.88',
    entry_vwap: 996.5, entry_reasons: ['量價突破', '站在VWAP之上'],
    stop_price: 985, take_profit_price: 1030
  });
  // 2.0 wording: observation labels; same numbers from the same fields.
  assert.match(entryMsg, /▲【量多進攻】/);
  assert.match(entryMsg, /2330 台積電/);
  assert.match(entryMsg, /觀察價：1000\.00/);
  assert.match(entryMsg, /量能分數：0\.88/);
  assert.match(entryMsg, /✓ 量價突破/);
  assert.match(entryMsg, /下緣參考：985\.00/);
  assert.match(entryMsg, /上緣參考：1030\.00/);
  assert.match(entryMsg, /非買賣建議/);

  const exitMsg = formatTelegramExit({
    symbol: '2330', name: '台積電', entry_price: 1000, exit_price: 1025,
    pnl_pct: 2.5, mfe_pct: 3.0, mae_pct: -0.5, duration_seconds: 1800,
    exit_reason: '範例：量能轉弱'
  });
  assert.match(exitMsg, /▼【量減退守】/);
  assert.match(exitMsg, /2330 台積電/);
  assert.match(exitMsg, /觀察起點：1000\.00/);
  assert.match(exitMsg, /觀察終點：1025\.00/);
  assert.match(exitMsg, /區間漲跌：\+2\.50%/);
  assert.match(exitMsg, /區間最高：\+3\.00%/);
  assert.match(exitMsg, /區間最低：-0\.50%/);
  assert.match(exitMsg, /觀察時間：30分0秒/);
  assert.match(exitMsg, /說明：範例：量能轉弱/);
});

test('T39/T40 user-visible copy: 架構 tab, 量多進攻／量減退守, no buy/sell instruction wording', async () => {
  const files = ['../popup.html', '../popup.js', '../chart.html', '../chart.js', '../background.js', '../core.js', '../manifest.json'];
  const strip = s => s.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '').replace(/<!--[\s\S]*?-->/g, '');
  for (const file of files) {
    const text = strip(await readFile(new URL(file, import.meta.url), 'utf8'));
    for (const banned of ['當沖AI架構', '當沖 AI 架構', '當沖標的', '當沖進場', '當沖出場', '建議買入', '建議賣出', '買進訊號', '賣出訊號', '當沖多方訊號', '買進範例', '下單 ↗', '買進推播', '賣出推播']) {
      assert.equal(text.includes(banned), false, `${file} still shows "${banned}"`);
    }
  }
  const html = await readFile(new URL('../popup.html', import.meta.url), 'utf8');
  assert.match(html, /data-group="ai_matrix" aria-label="架構">架構<\/button>/);
  assert.match(html, /量多進攻/);
  assert.match(html, /量減退守/);
  const manifest = JSON.parse(await readFile(new URL('../manifest.json', import.meta.url), 'utf8'));
  assert.match(manifest.name, /^當沖吧！牛馬仔/, 'brand name kept');
  assert.doesNotMatch(manifest.name + manifest.description, /AI 量化雷達|突破點火/);
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
test('resolveStockInput: only real Taiwan stocks; lookup outage is not treated as "no such stock"', async () => {
  const yahoo = async q => ({ ok: true, results: q === '6505' ? [{ symbol: '6505', market: 'TW', name: '台塑化' }] : [] });
  assert.equal((await resolveStockInput('2330', {}, yahoo)).stock.name, '台積電');
  const found = await resolveStockInput('6505', {}, yahoo);
  assert.equal(found.status, 'found'); assert.equal(found.stock.market, 'TW');
  assert.equal((await resolveStockInput('1000', {}, yahoo)).status, 'notFound');
  assert.equal((await resolveStockInput('不存在的公司', {}, yahoo)).status, 'notFound');
  const down = async () => ({ ok: false, results: [] });
  const unverified = await resolveStockInput('00878', {}, down);
  assert.equal(unverified.status, 'unverified');
  assert.equal(unverified.stock.symbol, '00878');
  assert.equal((await resolveStockInput('台積', {}, down)).stock.symbol, '2330', 'built-in names work offline');
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

  // 2.0: numbers that match no known Taiwan stock are not invented as suggestions.
  assert.equal(searchStocks('1000').some(s => s.symbol === '1000'), false);
  assert.equal(searchStocks('9999').length, 0);
  // Symbols seen in the public feed count as known stocks.
  const fromFeed = searchStocks('1101', { '1101': { name: '台泥' } });
  assert.equal(fromFeed[0].symbol, '1101');
  assert.equal(fromFeed[0].market, 'TW');

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
  assert.ok(BROKERS.length >= 9);

  // 測試觀察看盤模式
  const observe = getBroker('observe');
  assert.equal(observe.id, 'observe');
  assert.equal(observe.isObserve, true);
  assert.equal(observe.url('2330'), '');

  const yahoo = getBroker('yahoo');
  assert.equal(yahoo.id, 'yahoo');
  assert.equal(yahoo.isObserve, true);
  assert.ok(yahoo.url('2330').includes('tw.stock.yahoo.com/quote/2330'));

  const wantgoo = getBroker('wantgoo');
  assert.equal(wantgoo.id, 'wantgoo');
  assert.equal(wantgoo.isObserve, true);
  assert.ok(wantgoo.url('2330').includes('wantgoo.com/stock/2330'));

  // 測試券商直通下單
  const sinopac = getBroker('sinopac');
  assert.equal(sinopac.id, 'sinopac');
  assert.equal(sinopac.icon, '🔴');
  assert.ok(sinopac.url('2330').includes('TradingCenter_TWStocks_Stock/?code=2330'));

  const fubon = getBroker('fubon');
  assert.equal(fubon.id, 'fubon');
  assert.equal(fubon.icon, '🔵');
  assert.ok(fubon.url('2454').includes('fbs.com.tw'));

  const yuanta = getBroker('yuanta');
  assert.equal(yuanta.id, 'yuanta');
  assert.ok(yuanta.url('2603').includes('eyuanta'));

  const fallback = getBroker('unknown_broker');
  assert.equal(fallback.id, 'sinopac');
});


