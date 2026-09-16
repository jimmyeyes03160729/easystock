import test from 'node:test';
import assert from 'node:assert/strict';
import { defaultState, TTL, sha256 } from '../core.js';
let now = Date.parse('2026-09-17T09:30:00+08:00');
Date.now = () => now;
const event = () => { const listeners = []; return { addListener: f => listeners.push(f), listeners }; };
let db = {}, calls = [], notifications = [], tabs = [], fail = false, denied = false, failCreate = false;
let cfg = { schema_version: 1, global_vip_switch: false, vip_keys_hash: [], bounce_strategy_signals: [], daytrade_strategy_signals: [] };
globalThis.chrome = {
  runtime: { id: 'test', getURL: path => `chrome-extension://test/${path}`, onMessage: event(), onInstalled: event(), onStartup: event() },
  storage: { local: { get: async key => ({ [key]: structuredClone(db[key]) }), set: async value => Object.assign(db, structuredClone(value)) } },
  alarms: { get: async () => null, create: async () => {}, onAlarm: event() },
  notifications: { getPermissionLevel: async () => denied ? 'denied' : 'granted', create: async (id, options) => { if (failCreate) throw new Error('OS error'); notifications.push({ id, options }); return id; }, clear: async () => true, onClicked: event(), onButtonClicked: event(), onClosed: event() },
  tabs: { create: async value => tabs.push(value) }
};
globalThis.fetch = async url => {
  calls.push(url);
  if (fail) throw new Error('offline');
  return new Response(JSON.stringify(url.includes('raw.githubusercontent') ? cfg : {}));
};
const bg = await import('../background.js');
function reset() {
  db = {}; calls = []; notifications = []; tabs = []; fail = false; denied = false; failCreate = false;
  now = Date.parse('2026-09-17T09:30:00+08:00');
  cfg = { schema_version: 1, global_vip_switch: false, vip_keys_hash: [], bounce_strategy_signals: [], daytrade_strategy_signals: [] };
}
const makeSignal = (symbol, id = symbol) => ({ id, symbol, market: 'TW', name: symbol, price: 100, change_pct: 1, reason: '爆量突破', generated_at: new Date(now).toISOString(), quote_at: new Date(now).toISOString() });
function setupSignals(count = 5) {
  db.state = defaultState(); db.state.stocks = [];
  for (let i = 0; i < count; i++) {
    const symbol = String(2330 + i);
    db.state.stocks.push({ symbol, market: 'TW', name: symbol, groups: ['daytrade'] }); cfg.daytrade_strategy_signals.push(makeSignal(symbol));
  }
}
test('background behavior', async t => {
  await t.test('5 minute successful and failed request cache survives memory reset', async () => {
    reset(); await bg.remoteConfig(now); await bg.remoteConfig(now + 1); assert.equal(calls.length, 1);
    now += TTL; await bg.remoteConfig(now); assert.equal(calls.length, 2);
    now += TTL; fail = true; await assert.rejects(bg.remoteConfig(now)); await assert.rejects(bg.remoteConfig(now + 1)); assert.equal(calls.length, 3);
  });
  await t.test('parallel polls cannot overrun three-notification quota', async () => {
    reset(); setupSignals(); await Promise.all([bg.serial(bg.poll), bg.serial(bg.poll), bg.serial(bg.poll)]);
    assert.equal(notifications.length, 3); assert.equal(db.ledger.count, 3);
    assert.equal(notifications[0].options.title, '【當沖多方訊號】2330 2330');
    assert.equal(notifications[0].options.buttons.length, 2);
  });
  await t.test('stored VIP hash revalidated; unlimited still respects dedup', async () => {
    reset(); setupSignals(); const hash = await sha256('private-test'); cfg.vip_keys_hash = [hash]; db.state.vipHash = hash;
    await bg.serial(bg.poll); await bg.serial(bg.poll); assert.equal(notifications.length, 5);
    assert.equal(db.ledger.count, 5);
  });
  await t.test('manual tests bypass quota/off-hours/toggles without changing counters', async () => {
    reset(); now = Date.parse('2026-09-19T22:00:00+08:00');
    for (let i = 0; i < 4; i++) await bg.serial(() => bg.handle({ type: 'TEST', strategy: 'daytrade' }));
    assert.equal(notifications.length, 4); assert.equal(db.ledger.count, 0); assert.equal(calls.length, 0);
    assert.match(notifications[0].options.title, /VM 測試/);
  });
  await t.test('notification errors do not consume daily allowance', async () => {
    reset(); setupSignals(1); denied = true; await assert.rejects(bg.serial(bg.poll)); assert.equal(db.ledger, undefined);
    denied = false; failCreate = true; await assert.rejects(bg.serial(bg.poll)); assert.equal(db.ledger.count, 0);
  });
  await t.test('button clicks open chart or suppress today, body opens chart', async () => {
    reset(); setupSignals(1); await bg.serial(bg.poll); const id = notifications[0].id;
    chrome.notifications.onButtonClicked.listeners[0](id, 1); await bg.serial(async () => {});
    assert.equal(db.ledger.ignored['2330'], true); assert.equal(tabs.length, 0);
    chrome.notifications.onClicked.listeners[0](id); await bg.serial(async () => {});
    assert.equal(tabs[0].url, 'https://tw.stock.yahoo.com/quote/2330.TW');
    // Persisted routing, not an in-memory map, also works after service-worker reload.
    assert.equal(db.ledger.routes[id].symbol, '2330');
  });
  await t.test('test ignore does not mute production ticker', async () => {
    reset(); await bg.serial(() => bg.handle({ type: 'TEST', strategy: 'rebound' }));
    chrome.notifications.onButtonClicked.listeners[0](notifications[0].id, 1); await bg.serial(async () => {});
    assert.equal(db.ledger.ignored['2330'], undefined);
  });
  await t.test('outside session has zero network activity; holiday no feed fetch', async () => {
    reset(); now = Date.parse('2026-09-17T13:30:00+08:00'); await bg.serial(bg.poll); assert.equal(calls.length, 0);
    reset(); cfg.market_holidays = ['2026-09-17']; await bg.serial(bg.poll); assert.equal(calls.length, 1);
  });
  await t.test('disabled/unwatched/wrong-market/stale signals do not notify', async () => {
    reset(); setupSignals(1); cfg.daytrade_strategy_signals[0].market = 'TWO'; await bg.serial(bg.poll); assert.equal(notifications.length, 0);
    reset(); setupSignals(1); db.state.settings.daytrade = false; await bg.serial(bg.poll); assert.equal(notifications.length, 0);
    reset(); setupSignals(1); cfg.daytrade_strategy_signals[0].quote_at = '2026-09-16T09:30:00+08:00'; await bg.serial(bg.poll); assert.equal(notifications.length, 0);
  });
  await t.test('valid live OPEN entry works without fabricating percentage', async () => {
    reset(); const stocks = defaultState().stocks;
    const data = { quotes: { '2330': { price: 100, updated_at: new Date(now).toISOString() } }, live: { open_positions: { '2330': { status: 'OPEN', entry_time: new Date(now).toISOString(), entry_reasons: ['量價突破'] } } } };
    const result = bg.liveSignals(data, stocks, now); assert.equal(result.length, 1); assert.equal(result[0].change_pct, null);
    data.live.open_positions['2330'].status = 'CLOSED'; assert.equal(bg.liveSignals(data, stocks, now).length, 0);
  });
  await t.test('message endpoint rejects other origins before executing', async () => {
    reset(); const listener = chrome.runtime.onMessage.listeners[0]; let response;
    assert.equal(listener({ type: 'TEST', strategy: 'daytrade' }, { id: 'evil', url: 'https://example.com' }, v => { response = v; }), false);
    assert.equal(response, undefined); assert.equal(notifications.length, 0);
    assert.equal(listener({ type: 'TEST', strategy: 'daytrade' }, { id: 'test', url: 'chrome-extension://test/popup.html' }, v => { response = v; }), true);
    await bg.serial(async () => {}); assert.equal(response.ok, true);
  });
  await t.test('invalid import atomic; VIP never stored as plaintext', async () => {
    reset(); db.state = defaultState(); const original = structuredClone(db.state);
    await assert.rejects(bg.serial(() => bg.handle({ type: 'IMPORT', stocks: [{ symbol: '../bad' }] })));
    assert.deepEqual(db.state, original);
    const hash = await sha256('secret-test'); cfg.vip_keys_hash = [hash];
    await bg.serial(() => bg.handle({ type: 'VIP', key: 'secret-test' }));
    assert.equal(db.state.vipHash, hash); assert.equal(JSON.stringify(db).includes('secret-test'), false);
  });
});
