// Chrome 2.0 Stage A: watchlist add / quote / index freshness regressions (synthetic fixtures only).
process.env.TZ = 'America/New_York'; // T16: results must not depend on the computer's time zone.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { JSDOM } from 'jsdom';
import * as core from '../core.js';

const { defaultState, quoteStatus, mergeQuote, sparkForQuote, indexQuality, lastSessionDate, formatTaipeiQuoteTime, normalizeQuoteTimestamp } = core;
const at = s => Date.parse(s);
let now = at('2026-10-15T10:48:00+08:00'); // Thursday, market open
Date.now = () => now;

const event = () => { const listeners = []; return { addListener: f => listeners.push(f), listeners }; };
let db = {}, calls = [], broadcasts = [];
let misMode = 'ok', misStamp = () => now, yahoo = {}, yahooDelay = 0, sparkPoints = {}, feedMode = 'ok';
globalThis.chrome = {
  runtime: { id: 'test', getURL: p => `chrome-extension://test/${p}`, onMessage: event(), onInstalled: event(), onStartup: event(), sendMessage: async m => { broadcasts.push(m); } },
  storage: { local: { get: async key => ({ [key]: structuredClone(db[key]) }), set: async value => Object.assign(db, structuredClone(value)) } },
  alarms: { get: async () => ({}), create: async () => {}, onAlarm: event() },
  notifications: { getPermissionLevel: async () => 'granted', create: async () => 'id', clear: async () => true, onClicked: event(), onButtonClicked: event(), onClosed: event() },
  tabs: { create: async () => {} }
};
const cfg = { schema_version: 1, global_vip_switch: false, vip_keys_hash: [], daytrade_strategy_signals: [], market_holidays: [] };
function yahooItem(sym, q) {
  return { symbol: `${sym}.${q.market || 'TW'}`, symbolName: q.name, price: { sort: q.price }, regularMarketPreviousClose: { sort: q.prev },
    change: { sort: q.price - q.prev }, changePercent: `${(((q.price - q.prev) / q.prev) * 100).toFixed(2)}%`, regularMarketTime: q.time };
}
globalThis.fetch = async (url, opts = {}) => {
  url = String(url); calls.push(url);
  const reply = body => new Response(JSON.stringify(body));
  if (url.includes('raw.githubusercontent')) return reply(cfg);
  if (url.includes('mis.twse.com.tw')) {
    if (misMode === 'fail') throw new Error('timeout');
    const tl = String(misStamp());
    return reply({ msgArray: [{ c: 't00', z: '47111.26', y: '46969.87', t: '10:48:00', d: '20261015', tlong: tl }, { c: 'o00', z: '400.26', y: '396.90', t: '10:48:00', tlong: tl }] });
  }
  if (url.includes('public_feed.json')) {
    if (feedMode === 'fail') throw new Error('feed down');
    // 1102 mirrors production: a 09:00 snapshot from the previous day, no previous close; 00878 missing.
    return reply({ '2330': { name: '台積電', price: 2435, updated_at: new Date(now - 60000).toISOString() }, '1102': { name: '1102', price: 37.4, updated_at: '2026-10-14T09:00:54+08:00' } });
  }
  if (url.includes('intraday_live.json')) return reply({});
  if (url.includes('rebound_feed.json')) return reply({ signals: [], as_of: '2026-10-14' });
  if (url.includes('StockServices.stockList')) {
    if (yahooDelay) await new Promise(r => setTimeout(r, yahooDelay));
    const syms = decodeURIComponent(url.split('symbols=')[1] || '').split(',');
    return reply(syms.map(s => { const [sym, mkt] = s.split('.'); const q = yahoo[sym]; return q && (q.market || 'TW') === mkt ? yahooItem(sym, q) : null; }).filter(Boolean));
  }
  if (url.includes('/v7/finance/spark')) {
    return reply({ spark: { result: Object.entries(sparkPoints).map(([sym, pts]) => ({ symbol: `${sym}.TW`, response: [{ timestamp: pts.map(p => p.t), indicators: { quote: [{ close: pts.map(p => p.c) }] } }] })) } });
  }
  if (url.includes('/v8/finance/chart/')) {
    const t0 = at('2026-10-15T09:00:00+08:00') / 1000;
    return reply({ chart: { result: [{ meta: { previousClose: 37.85, regularMarketPrice: 38.2 }, timestamp: [t0, t0 + 60, t0 + 120, t0 + 180],
      indicators: { quote: [{ close: [null, null, 38.0, null], open: [null, null, 37.9, null], high: [null, null, 38.1, null], low: [null, null, 37.9, null], volume: [0, 0, 10, 0] }] } }] } });
  }
  return reply({});
};
const bg = await import('../background.js');
const settle = async () => { for (let i = 0; i < 5; i++) await new Promise(r => setTimeout(r, 5)); await bg.feedSerial(async () => {}); await bg.serial(async () => {}); };
function reset() {
  db = {}; calls = []; broadcasts = []; misMode = 'ok'; feedMode = 'ok'; yahooDelay = 0; sparkPoints = {};
  now = at('2026-10-15T10:48:00+08:00'); misStamp = () => now;
  yahoo = {
    '2330': { name: '台積電', price: 2420, prev: 2440, time: new Date(now - 30000).toISOString() },
    '1102': { name: '亞泥', price: 38.2, prev: 37.85, time: new Date(now - 30000).toISOString() },
    '00878': { name: '國泰永續高股息', price: 35.53, prev: 35.09, time: new Date(now - 30000).toISOString() }
  };
  db.state = defaultState(); db.state.stocks = [];
}
const add = (symbol, name = symbol, market = 'TW') => bg.serial(() => bg.handle({ type: 'ADD', stock: { symbol, market, name, groups: ['watchlist'] } }));

test('T01 2330: saved to chrome.storage.local and visible before any quote arrives', async () => {
  reset(); yahooDelay = 50;
  const result = await add('2330', '台積電');
  assert.deepEqual(db.state.stocks.map(s => s.symbol), ['2330']);
  assert.ok(result.stocks.some(s => s.symbol === '2330'));
  assert.equal(result.notice, 'ADDED');
  assert.ok(result.pendingQuotes.includes('2330'), 'quote shown as loading, not as a failure');
  assert.equal(quoteStatus(result.quotes['2330'], now, { pending: true }).label, '載入中');
  await new Promise(r => setTimeout(r, 80)); await settle();
  assert.equal(db.feedCache.quotes['2330'].price, 2420);
  assert.ok(broadcasts.some(m => m.type === 'QUOTES_UPDATED' && m.symbols.includes('2330')));
});

test('T02/T04 1102: quote source down keeps the stock; status is 暫無行情, never an add failure', async () => {
  reset(); delete yahoo['1102'];
  await add('1102');
  await settle();
  assert.deepEqual(db.state.stocks.map(s => s.symbol), ['1102']);
  assert.equal(db.feedCache.quoteAttempts['1102'].ok, false);
  assert.equal(quoteStatus(db.feedCache.quotes['1102'], now).label, '暫無行情');
});

test('T03 00878 ETF: recognised as listed (TW), added, quoted, placeholder name corrected', async () => {
  reset();
  await add('00878');
  await settle();
  assert.equal(db.state.stocks[0].market, 'TW');
  assert.equal(db.feedCache.quotes['00878'].price, 35.53);
  assert.equal(db.state.stocks[0].name, '國泰永續高股息');
  assert.equal(quoteStatus(db.feedCache.quotes['00878'], now).state, 'live');
});

test('market guess is corrected when the quote only exists on the other exchange', async () => {
  reset(); yahoo['6505'] = { name: '台塑化', price: 50, prev: 49, time: new Date(now).toISOString(), market: 'TW' };
  await add('6505', '6505', 'TWO');
  await settle();
  assert.equal(db.state.stocks[0].market, 'TW');
  assert.equal(db.feedCache.quotes['6505'].price, 50);
});

test('T05/T07 worker restart and popup reopen read the same persisted watchlist and quotes', async () => {
  reset(); await add('2330', '台積電'); await settle();
  const fresh = await import('../background.js?restart=1');
  const snap = await fresh.handle({ type: 'BOOTSTRAP' });
  assert.deepEqual(snap.stocks.map(s => s.symbol), ['2330']);
  assert.equal(snap.quotes['2330'].price, 2420);
});

test('T06 duplicate add is a notice, not a write and not a second row', async () => {
  reset(); await add('2330', '台積電'); await settle();
  const rev = db.state.rev;
  const again = await add('2330', '台積電');
  assert.equal(again.notice, 'DUPLICATE');
  assert.equal(db.state.stocks.length, 1);
  assert.equal(db.state.rev, rev);
});

test('ADD is not queued behind a slow market refresh (root cause of "clicked add, nothing")', async () => {
  reset(); yahooDelay = 300; db.state.stocks = [{ symbol: '2330', market: 'TW', name: '台積電', groups: ['watchlist'] }];
  const listener = chrome.runtime.onMessage.listeners[0];
  let refreshDone = false, addDone = false;
  listener({ type: 'SNAPSHOT', refresh: true }, { id: 'test', url: 'chrome-extension://test/popup.html' }, () => { refreshDone = true; });
  listener({ type: 'ADD', stock: { symbol: '1102', market: 'TW', name: '亞泥', groups: ['watchlist'] } }, { id: 'test', url: 'chrome-extension://test/popup.html' }, r => { addDone = r.ok; });
  await new Promise(r => setTimeout(r, 60));
  assert.equal(addDone, true, 'add answered while refresh still running');
  assert.equal(refreshDone, false);
  assert.ok(db.state.stocks.some(s => s.symbol === '1102'));
  await new Promise(r => setTimeout(r, 400)); await settle();
});

test('a refresh snapshot reports the watchlist as of its end (includes a stock added meanwhile)', async () => {
  reset(); yahooDelay = 100; db.state.stocks = [{ symbol: '1102', market: 'TW', name: '亞泥', groups: ['watchlist'] }];
  const refresh = bg.handle({ type: 'SNAPSHOT', refresh: true });
  await new Promise(r => setTimeout(r, 20));
  await add('2330', '台積電');
  const snap = await refresh;
  assert.ok(snap.stocks.some(s => s.symbol === '2330'));
  assert.ok(snap.rev >= 1);
  await settle();
});

test('T09 a 1.05 saved watchlist is read without loss', async () => {
  reset();
  db.state = { version: 1, stocks: [
    { symbol: '2330', market: 'TW', name: '台積電', groups: ['watchlist'] },
    { symbol: '8299', market: 'TWO', name: '群聯', groups: ['watchlist', 'daytrade'] }
  ], settings: { daytrade: true, darkMode: true, pageSize: 7 }, vipHash: '' };
  const snap = await bg.handle({ type: 'BOOTSTRAP' });
  assert.deepEqual(snap.stocks.map(s => s.symbol), ['2330', '8299']);
  assert.deepEqual(snap.stocks[1].groups, ['watchlist', 'daytrade']);
  assert.equal(snap.settings.pageSize, 7);
});

test('T10/T11 index TTL expiry refreshes the index even while the broad feed cache is valid', async () => {
  reset(); db.state.settings.daytrade = true;
  const old = at('2026-10-15T10:16:00+08:00');
  db.feedCache = { at: now - 60000, quotes: {}, live: {}, taiex: { price: 46900, change: 1, change_pct: 0.01, quote_at: new Date(old).toISOString() }, taiexAttemptAt: now - 120000 };
  await bg.serial(bg.poll);
  assert.ok(calls.some(u => u.includes('mis.twse.com.tw')), 'index fetched');
  assert.equal(calls.filter(u => u.includes('public_feed.json')).length, 0, 'broad feed stays cached');
  assert.equal(Date.parse(db.feedCache.taiex.quote_at), now);
  assert.equal(indexQuality(db.feedCache.taiex, now).status, 'LIVE');
});

test('index refresh does not depend on alert settings (daytrade off)', async () => {
  reset(); db.state.settings.daytrade = false;
  db.feedCache = { at: now - 60000, quotes: {}, live: {}, taiexAttemptAt: now - 120000 };
  await bg.serial(bg.poll);
  assert.ok(calls.some(u => u.includes('mis.twse.com.tw')));
});

test('a failing public feed no longer discards a successful index fetch', async () => {
  reset(); feedMode = 'fail';
  const snap = await bg.handle({ type: 'SNAPSHOT', refresh: true });
  assert.equal(snap.taiex.price, 47111.26);
  assert.match(snap.error, /行情暫時無法更新/);
});

test('T12 index timeout keeps the last value and marks it STALE, not live', async () => {
  reset(); misMode = 'fail';
  const lastGood = { price: 46900, change: 1, change_pct: 0.01, quote_at: new Date(now - 32 * 60000).toISOString() };
  db.feedCache = { at: now - 60000, quotes: {}, live: {}, taiex: lastGood, taiexAttemptAt: now - 120000 };
  const snap = await bg.handle({ type: 'SNAPSHOT', taiexOnly: true });
  assert.equal(snap.taiex.price, 46900);
  assert.equal(snap.taiexQuality.status, 'STALE');
  assert.equal(snap.taiexQuality.fresh, false);
  assert.match(snap.taiexQuality.lastError, /無法連線/);
  assert.equal(snap.taiexQuality.age_seconds, 32 * 60);
});

test('T13 the production 1102 case: yesterday 09:00 snapshot is stale and never mixed with today', async () => {
  const yesterday = { name: '1102', price: 37.4, updated_at: '2026-10-14T09:00:54+08:00' };
  assert.equal(quoteStatus(yesterday, now).state, 'stale');
  const today = { name: '亞泥', price: 38.2, previous_close: 37.85, change: 0.35, change_pct: 0.92, quote_at: new Date(now - 30000).toISOString() };
  const merged = mergeQuote(yesterday, today);
  assert.equal(merged.price, 38.2);
  assert.equal(merged.name, '亞泥');
  // Reverse order must give the same answer: newest source time wins as a whole record.
  assert.equal(mergeQuote(today, yesterday).price, 38.2);
  // Previous close may only be carried within the same trading day.
  const liveNoPrev = { name: '1102', price: 38.3, quote_at: new Date(now).toISOString() };
  const m2 = mergeQuote(today, liveNoPrev);
  assert.equal(m2.price, 38.3); assert.equal(m2.previous_close, 37.85);
  const m3 = mergeQuote({ ...today, quote_at: '2026-10-14T13:30:00+08:00' }, liveNoPrev);
  assert.equal(m3.previous_close, undefined);
  // A quote without any source time cannot be presented as live.
  assert.equal(normalizeQuoteTimestamp(undefined), null);
  assert.equal(quoteStatus({ price: 10 }, now).state, 'stale');
});

test('the full refresh replaces the stale 1102 record with a complete current quote', async () => {
  reset(); db.state.stocks = [{ symbol: '1102', market: 'TW', name: '1102', groups: ['watchlist'] }];
  const snap = await bg.handle({ type: 'SNAPSHOT', refresh: true });
  assert.equal(snap.quotes['1102'].price, 38.2);
  assert.equal(quoteStatus(snap.quotes['1102'], now).state, 'live');
  await settle();
});

test('T14 Taipei session boundaries and last session date', () => {
  assert.equal(core.marketOpen(at('2026-10-15T08:59:59+08:00')), false);
  assert.equal(core.marketOpen(at('2026-10-15T09:00:00+08:00')), true);
  assert.equal(core.marketOpen(at('2026-10-15T13:29:59+08:00')), true);
  assert.equal(core.marketOpen(at('2026-10-15T13:30:00+08:00')), false);
  assert.equal(lastSessionDate(at('2026-10-15T08:30:00+08:00')), '2026-10-14');
  assert.equal(lastSessionDate(at('2026-10-18T10:00:00+08:00')), '2026-10-16');
  assert.equal(lastSessionDate(at('2026-10-27T08:00:00+08:00'), ['2026-10-26']), '2026-10-23');
});

test('T15 weekend / holiday: last session close is "收盤", not an API failure', () => {
  const sat = at('2026-10-17T11:00:00+08:00');
  const fridayClose = { price: 2420, quote_at: '2026-10-16T13:30:00+08:00' };
  assert.equal(quoteStatus(fridayClose, sat).state, 'close');
  assert.equal(indexQuality({ price: 47000, quote_at: '2026-10-16T13:33:00+08:00' }, sat).status, 'CLOSE');
  assert.equal(quoteStatus({ price: 2420, quote_at: '2026-10-15T13:30:00+08:00' }, sat).state, 'stale');
  const holiday = at('2026-10-26T10:00:00+08:00');
  assert.equal(quoteStatus({ price: 1, quote_at: '2026-10-23T13:30:00+08:00' }, holiday, { holidays: ['2026-10-26'] }).state, 'close');
});

test('T16 quote and index times are Taipei times regardless of the computer time zone', () => {
  assert.equal(new Date().getTimezoneOffset() !== -480, true, 'test runs in a non-Taipei zone');
  assert.equal(formatTaipeiQuoteTime('2026-10-15T02:48:00Z'), '10:48');
  assert.equal(bg.misQuoteAt({ d: '20261015', t: '10:48:00' }), '2026-10-15T10:48:00+08:00');
  assert.equal(bg.misQuoteAt({ tlong: String(at('2026-10-15T10:48:00+08:00')) }), '2026-10-15T02:48:00.000Z');
});

test('T17 no real intraday points means no line (no synthetic sparkline or back-filled bars)', async () => {
  assert.equal(sparkForQuote({ price: 1, quote_at: new Date(now).toISOString() }), null);
  const otherDay = [{ close: 1, timestamp: at('2026-10-14T09:00:00+08:00') / 1000 }, { close: 2, timestamp: at('2026-10-14T09:15:00+08:00') / 1000 }];
  assert.equal(sparkForQuote({ price: 1, quote_at: new Date(now).toISOString(), spark: otherDay }), null);
  const sameDay = otherDay.map(p => ({ ...p, timestamp: p.timestamp + 86400 }));
  const line = sparkForQuote({ price: 3, quote_at: new Date(now).toISOString(), spark: sameDay });
  assert.equal(line.length, 3, 'two real points plus the current quote at its own time');
  assert.equal(line.at(-1).close, 3);
  assert.equal(line.at(-1).timestamp, Math.floor(now / 1000));
  const intraday = await bg.fetchIntradayData('1102', 'TW');
  assert.equal(intraday.bars[0].close, 38.0, 'leading empty minutes are skipped, not filled with the previous close');
  assert.equal(intraday.bars.length, 2);
});

// ---- popup (jsdom) ----
async function popup({ hangRefresh = false, stocks = [], extra = {} } = {}) {
  const html = await readFile(new URL('../popup.html', import.meta.url), 'utf8');
  const source = await readFile(new URL('../popup.js', import.meta.url), 'utf8');
  const dom = new JSDOM(html, { url: 'https://example.test', runScripts: 'outside-only' });
  const w = dom.window, messages = [], confirms = [];
  w.setInterval = () => 0;
  w.confirm = m => { confirms.push(m); return true; };
  w.alert = m => { confirms.push(m); };
  const state = { ...defaultState(), rev: 1, quotes: {}, live: {}, taiex: null, quoteAttempts: {}, pendingQuotes: [] };
  state.stocks = stocks;
  Object.assign(state, extra);
  let releaseRefresh;
  const refreshGate = new Promise(r => { releaseRefresh = r; });
  w.chrome = { storage: { local: { get: async () => ({ state }) } }, runtime: { onMessage: { addListener: () => {} }, sendMessage: async message => {
    messages.push(message);
    if (message.type === 'SNAPSHOT' && message.refresh && hangRefresh) {
      const before = structuredClone(state); await refreshGate; return { ok: true, value: before };
    }
    if (message.type === 'ADD') {
      if (state.stocks.some(s => s.symbol === message.stock.symbol)) return { ok: true, value: { ...structuredClone(state), notice: 'DUPLICATE' } };
      state.stocks.push(message.stock); state.rev += 1;
      return { ok: true, value: { ...structuredClone(state), notice: 'ADDED', pendingQuotes: [message.stock.symbol] } };
    }
    return { ok: true, value: structuredClone(state) };
  } }, tabs: { create: async () => {} } };
  for (const [key, value] of Object.entries(core)) w[key] = value;
  w.icons = () => {};
  await w.eval(`(async()=>{${source.replace(/^import .*;\r?\n/gm, '')}})()`);
  await new Promise(r => setTimeout(r, 10));
  return { w, messages, confirms, state, releaseRefresh, dom };
}
const rows = w => [...w.document.querySelectorAll('.stock-row')].map(r => r.dataset.symbol);

test('T08 typing 2330 + 新增 adds directly: no confirm dialog, inline success, input cleared', async () => {
  const { w, messages, confirms, dom } = await popup();
  w.document.getElementById('input-search').value = '2330';
  w.document.getElementById('btn-add').click();
  await new Promise(r => setTimeout(r, 20));
  assert.equal(confirms.length, 0);
  assert.ok(messages.some(m => m.type === 'ADD' && m.stock.symbol === '2330'));
  assert.deepEqual(rows(w), ['2330']);
  assert.match(w.document.getElementById('add-feedback').textContent, /已加入 2330/);
  assert.equal(w.document.getElementById('input-search').value, '');
  assert.equal(w.document.querySelector('[data-symbol="2330"]').dataset.quoteState, 'loading');
  dom.window.close();
});

test('add works while a slow refresh is pending, and the late (older) refresh cannot remove it', async () => {
  const { w, messages, releaseRefresh, dom } = await popup({ hangRefresh: true });
  w.document.getElementById('input-search').value = '1102';
  w.document.getElementById('btn-add').click();
  await new Promise(r => setTimeout(r, 20));
  assert.ok(messages.some(m => m.type === 'ADD'), 'add not dropped while refresh pending');
  assert.deepEqual(rows(w), ['1102']);
  releaseRefresh();
  await new Promise(r => setTimeout(r, 20));
  assert.deepEqual(rows(w), ['1102'], 'older snapshot (lower rev) only updates market data');
  dom.window.close();
});

test('duplicate shows 已在自選 inline and does not add a row; invalid input shows inline error', async () => {
  const { w, messages, dom } = await popup({ stocks: [{ symbol: '2330', market: 'TW', name: '台積電', groups: ['watchlist'] }] });
  w.document.getElementById('input-search').value = '2330';
  w.document.getElementById('btn-add').click();
  await new Promise(r => setTimeout(r, 20));
  assert.match(w.document.getElementById('add-feedback').textContent, /已在自選/);
  assert.equal(messages.filter(m => m.type === 'ADD').length, 0);
  assert.deepEqual(rows(w), ['2330']);
  w.document.getElementById('input-search').value = '!!';
  w.document.getElementById('btn-add').click();
  await new Promise(r => setTimeout(r, 20));
  assert.match(w.document.getElementById('add-feedback').className, /es-error/);
  dom.window.close();
});

test('window height really sizes the popup (420–600, Chrome limit) and fixed page size still works', async () => {
  const stocks = ['2330', '2317', '2454', '2308', '2382'].map(symbol => ({ symbol, market: 'TW', name: symbol, groups: ['watchlist'] }));
  const tall = await popup({ stocks, extra: { settings: { ...defaultState().settings, windowHeight: 900, autoPageSize: false, pageSize: 3 } } });
  assert.equal(tall.w.document.documentElement.style.height, '600px', 'clamped to the Chrome popup maximum');
  assert.equal(tall.w.document.body.style.height, '600px');
  assert.equal(tall.w.document.getElementById('popup-container').style.height, '600px');
  assert.equal(tall.w.document.querySelectorAll('.stock-row').length, 3, 'auto-fill off: fixed 3 per page');
  assert.equal(tall.w.document.getElementById('range-page-size').disabled, false);
  assert.ok(tall.w.document.getElementById('btn-open-standalone'), 'standalone window offered for longer views');
  tall.dom.window.close();
  const short = await popup({ stocks, extra: { settings: { ...defaultState().settings, windowHeight: 300 } } });
  assert.equal(short.w.document.documentElement.style.height, '420px');
  assert.equal(short.w.document.getElementById('toggle-auto-page-size').checked, true, 'auto-fill is the default');
  assert.equal(short.w.document.getElementById('range-page-size').disabled, true);
  short.dom.window.close();
});

test('rows show 暫無行情 / 資料過期 and never draw a synthetic sparkline', async () => {
  // 00878 attempted with no data, 1102 only has yesterday's 09:00 snapshot (production case).
  const { w, dom } = await popup({ stocks: [
    { symbol: '00878', market: 'TW', name: '國泰永續高股息', groups: ['watchlist'] },
    { symbol: '1102', market: 'TW', name: '亞泥', groups: ['watchlist'] }
  ], extra: { quoteAttempts: { '00878': { ok: false }, '1102': { ok: true } }, quotes: { '1102': { price: 37.4, updated_at: '2026-10-14T09:00:54+08:00' } } } });
  const r878 = w.document.querySelector('[data-symbol="00878"]');
  const r1102 = w.document.querySelector('[data-symbol="1102"]');
  assert.match(r878.textContent, /暫無行情/);
  assert.equal(r1102.dataset.quoteState, 'stale');
  assert.match(r1102.textContent, /資料過期/);
  assert.equal(w.document.querySelectorAll('.stock-row svg.es-spark').length, 0);
  dom.window.close();
});
