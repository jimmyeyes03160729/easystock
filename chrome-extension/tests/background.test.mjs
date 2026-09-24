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
  await t.test('live exit signals correctly parse closed trades with telegram format', async () => {
    reset(); const stocks = defaultState().stocks;
    const data = {
      live: {
        closed_trades: [
          { symbol: '2330', name: '台積電', status: 'CLOSED', entry_price: 1000, exit_price: 1025,
            pnl_pct: 2.5, mfe_pct: 3.0, mae_pct: -0.5, duration_seconds: 1800,
            exit_reason: '12:55當沖強制出場', exit_time: new Date(now).toISOString() }
        ]
      }
    };
    const exits = bg.liveExitSignals(data, stocks, now, true);
    assert.equal(exits.length, 1);
    assert.equal(exits[0].action, 'SELL');
    assert.equal(exits[0].symbol, '2330');
    assert.match(exits[0].telegramText, /✅【當沖出場】/);
    assert.match(exits[0].telegramText, /報酬：\+2\.50%/);
  });
  await t.test('LIVE_DATA_SYNC from content script triggers instant telegram notifications', async () => {
    reset(); db.state = defaultState();
    const live = {
      open_positions: {
        '2330': {
          symbol: '2330', name: '台積電', status: 'OPEN', entry_price: 1000, entry_score: '0.90',
          entry_vwap: 998, entry_reasons: ['突破五分K'], stop_price: 985, take_profit_price: 1030,
          entry_time: new Date(now).toISOString()
        }
      },
      closed_trades: [
        {
          symbol: '2603', name: '長榮', status: 'CLOSED', entry_price: 200, exit_price: 206,
          pnl_pct: 3.0, mfe_pct: 3.5, mae_pct: -0.2, duration_seconds: 1200,
          exit_reason: '到達移動停利點', exit_time: new Date(now).toISOString()
        }
      ]
    };
    const listener = chrome.runtime.onMessage.listeners[0];
    let response;
    assert.equal(listener({ type: 'LIVE_DATA_SYNC', live }, { id: 'test', tab: { id: 1 } }, v => { response = v; }), true);
    await bg.serial(async () => {});
    assert.equal(response.ok, true);
    assert.equal(notifications.length, 2);
    assert.ok(notifications.some(n => n.options.title.includes('🚀【當沖進場訊號】') && n.options.message.includes('2330 台積電')));
    assert.ok(notifications.some(n => n.options.title.includes('✅【當沖出場】') && n.options.message.includes('2603 長榮')));
  });
  await t.test('conditional push filters signals by price range and change pct', async () => {
    reset(); db.state = defaultState();
    db.state.settings.filterMode = 'custom';
    db.state.settings.minPrice = 500;
    db.state.settings.minChangePct = 2.0;
    const cheapStock = {
      open_positions: {
        '2603': { symbol: '2603', name: '長榮', status: 'OPEN', entry_price: 200, pnl_pct: 3.0, entry_time: new Date(now).toISOString() }
      }
    };
    await bg.serial(() => bg.processLiveData(cheapStock));
    assert.equal(notifications.length, 0);

    const matchedStock = {
      open_positions: {
        '2330': { symbol: '2330', name: '台積電', status: 'OPEN', entry_price: 1000, pnl_pct: 2.5, entry_time: new Date(now).toISOString() }
      }
    };
    await bg.serial(() => bg.processLiveData(matchedStock));
    assert.equal(notifications.length, 1);
  });
  await t.test('rebound push respects independent switch and sends telegram format', async () => {
    reset(); db.state = defaultState();
    db.state.settings.daytrade = false;
    db.state.settings.rebound = false;
    cfg.bounce_strategy_signals.push(makeSignal('2330'));
    await bg.serial(bg.poll);
    assert.equal(notifications.length, 0);

    reset(); db.state = defaultState();
    db.state.stocks[0].groups = ['rebound'];
    db.state.settings.daytrade = false;
    db.state.settings.rebound = true;
    cfg.bounce_strategy_signals.push(makeSignal('2330'));
    await bg.serial(bg.poll);
    assert.equal(notifications.length, 1);
    assert.ok(notifications[0].options.title.includes('🛡️【觸底反彈訊號】'));
    assert.ok(notifications[0].options.message.includes('2330'));
  });
  await t.test('clicking notification opens standalone chart popup window if supported', async () => {
    reset();
    let winOpened = null;
    chrome.windows = {
      create: async opts => { winOpened = opts; return { id: 99 }; }
    };
    await bg.serial(() => bg.handle({ type: 'TEST', strategy: 'daytrade' }));
    const id = notifications[0].id;
    chrome.notifications.onClicked.listeners[0](id);
    await bg.serial(async () => {});
    assert.ok(winOpened);
    assert.equal(winOpened.type, 'popup');
    assert.ok(winOpened.url.includes('chart.html?symbol=2330'));
    delete chrome.windows;
  });
  await t.test('updateMarketStatusIcon updates action title and badge with market state', async () => {
    reset();
    let titleSet = '', badgeText = '', badgeColor = '';
    chrome.action = {
      setTitle: async ({ title }) => { titleSet = title; },
      setBadgeText: async ({ text }) => { badgeText = text; },
      setBadgeBackgroundColor: async ({ color }) => { badgeColor = color; }
    };
    const openData = {
      live: {
        market_level: 'GREEN',
        open_positions: { '2330': { status: 'OPEN' } },
        closed_trades: [{ symbol: '2317' }]
      }
    };
    const openDataWithTaiex = {
      ...openData,
      taiex: { price: 22800.5, change: 150.2, change_pct: 0.66, otc_price: 270.1, otc_change: 1.2, otc_change_pct: 0.45 }
    };
    await bg.updateMarketStatusIcon(openDataWithTaiex, now);
    assert.ok(titleSet.includes('加權指數：22,800.50 (+150.20 / +0.66%)'));
    assert.ok(titleSet.includes('櫃買指數：270.10 (+1.20 / +0.45%)'));
    assert.equal(badgeText, '+150');
    assert.equal(badgeColor, '#ef4444');

    // Negative taiex change
    const openDataDown = {
      ...openData,
      taiex: { price: 22600.0, change: -85.5, change_pct: -0.38 }
    };
    await bg.updateMarketStatusIcon(openDataDown, now);
    assert.ok(titleSet.includes('加權指數：22,600.00 (-85.50 / -0.38%)'));
    assert.equal(badgeText, '-85');
    assert.equal(badgeColor, '#22c55e');

    // Closed market test
    const offHours = Date.parse('2026-09-17T20:00:00+08:00');
    await bg.updateMarketStatusIcon(openDataWithTaiex, offHours);
    assert.ok(titleSet.includes('已收盤'));
    assert.equal(badgeText, '休');
    delete chrome.action;
  });
  await t.test('ADD_BATCH adds multiple valid stocks and ignores duplicates', async () => {
    reset(); db.state = defaultState();
    const batch = [
      { symbol: '2454', market: 'TW', name: '聯發科', groups: ['daytrade'] },
      { symbol: '2317', market: 'TW', name: '鴻海', groups: ['rebound'] }
    ];
    await bg.serial(() => bg.handle({ type: 'ADD_BATCH', stocks: batch }));
    assert.ok(db.state.stocks.some(s => s.symbol === '2454'));
    assert.ok(db.state.stocks.some(s => s.symbol === '2317'));

    // Re-adding same batch throws
    await assert.rejects(
      bg.serial(() => bg.handle({ type: 'ADD_BATCH', stocks: batch })),
      /所有股票均已在自選名單中/
    );
  });
});
