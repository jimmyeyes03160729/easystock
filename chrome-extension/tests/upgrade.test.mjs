// Chrome 2.0: 1.05 → 2.0 upgrade, new-install defaults, account wiring in the service worker.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { defaultState, migrateState } from '../core.js';

const event = () => { const listeners = []; return { addListener: f => listeners.push(f), listeners }; };
let db = {}, session = {}, identityCalls = 0;
globalThis.chrome = {
  runtime: { id: 'test', getURL: p => `chrome-extension://test/${p}`, getManifest: () => JSON.parse(manifestText), onMessage: event(), onInstalled: event(), onStartup: event(), sendMessage: async () => {} },
  storage: {
    local: { get: async key => ({ [key]: structuredClone(db[key]) }), set: async v => Object.assign(db, structuredClone(v)), remove: async k => { delete db[k]; } },
    session: { get: async key => ({ [key]: structuredClone(session[key]) }), set: async v => Object.assign(session, structuredClone(v)), remove: async k => { delete session[k]; } }
  },
  identity: { getAuthToken: async () => { identityCalls++; return { token: 'should-not-be-called' }; }, removeCachedAuthToken: async () => {} },
  alarms: { get: async () => ({}), create: async () => {}, onAlarm: event() },
  notifications: { getPermissionLevel: async () => 'granted', create: async () => 'id', clear: async () => true, onClicked: event(), onButtonClicked: event(), onClosed: event() },
  tabs: { create: async () => {} }
};
const manifestText = await readFile(new URL('../manifest.json', import.meta.url), 'utf8');
// Fixed fixture: the test must not depend on whether the real auth-config.json is filled in yet.
const authConfigText = JSON.stringify({ database_url: 'https://easystock-c237a-default-rtdb.firebaseio.com', firebase_api_key: '', oauth_client_id: '' });
globalThis.fetch = async url => {
  if (String(url).endsWith('auth-config.json')) return new Response(authConfigText);
  return new Response('{}');
};
const bg = await import('../background.js');
const reset = () => { db = {}; session = {}; identityCalls = 0; };

test('new install: light theme, red/green price colours', async () => {
  reset();
  await bg.onInstalledMigration({ reason: 'install' });
  const snap = await bg.handle({ type: 'BOOTSTRAP' });
  assert.equal(snap.settings.darkMode, false);
  assert.equal(snap.settings.colorMode, 'redgreen');
  assert.equal(db.syncMeta.ownerUid, null);
});

test('1.05 upgrade without saved state keeps the dark theme it showed', async () => {
  reset();
  await bg.onInstalledMigration({ reason: 'update', previousVersion: '1.0.5' });
  assert.equal(db.state.settings.darkMode, true);
  assert.equal(db.state.version, 2);
  assert.equal(db.state.migratedFrom, 1);
});

test('1.05 upgrade: watchlist, groups, alerts and an explicit light choice are all preserved', async () => {
  reset();
  db.state = { version: 1, stocks: [{ symbol: '2330', market: 'TW', name: '台積電', groups: ['watchlist', 'daytrade'] }, { symbol: '8299', market: 'TWO', name: '群聯', groups: ['watchlist'] }],
    settings: { daytrade: false, allDaytradeAlerts: false, filterMode: 'custom', minPrice: 50, darkMode: false, fontSize: 'large', preferredBroker: 'fubon' }, vipHash: 'h' };
  const before = structuredClone(db.state);
  await bg.onInstalledMigration({ reason: 'update', previousVersion: '1.0.5' });
  // Same stocks and alert groups; each lands in watchlist group 1.
  assert.deepEqual(db.state.stocks, before.stocks.map(s => ({ ...s, lists: ['g1'] })));
  assert.deepEqual(db.state.watchGroups.map(g => g.name), ['1', '2', '3', '4', '5']);
  for (const [k, v] of Object.entries(before.settings)) assert.equal(db.state.settings[k], v, k);
  assert.equal(db.state.settings.colorMode, 'redgreen');
  assert.equal(db.state.vipHash, 'h');
  assert.equal(db.syncMeta.settings.darkMode, 1, 'legacy value counts as an explicit choice for sync');
  assert.equal(db.syncMeta.stocks['8299'].updatedAt, 1);
});

test('migrateState is idempotent and never resets an existing dark preference', () => {
  const v1 = { version: 1, stocks: [], settings: { darkMode: true } };
  const once = migrateState(v1);
  assert.deepEqual(migrateState(once), once);
  assert.equal(migrateState({ version: 2, stocks: [], settings: { darkMode: true, colorMode: 'mono' } }).settings.colorMode, 'mono');
  assert.equal(migrateState(null).settings.darkMode, false);
});

test('T23 unconfigured OAuth: status BLOCKED, sign-in refused without touching chrome.identity', async () => {
  reset(); db.state = defaultState();
  const snap = await bg.handle({ type: 'BOOTSTRAP' });
  assert.equal(snap.account.configured, false);
  assert.equal(snap.account.status, 'BLOCKED_BY_OAUTH_CONFIGURATION');
  assert.equal(snap.account.signedIn, false);
  await assert.rejects(bg.handleAccount({ type: 'AUTH_SIGN_IN' }), /BLOCKED_BY_OAUTH_CONFIGURATION/);
  assert.equal(identityCalls, 0);
  assert.deepEqual(snap.stocks.map(s => s.symbol), ['2330'], 'local watchlist works without sign-in');
});

test('local edits are queued for sync (dirty + timestamps) even while signed out', async () => {
  reset(); db.state = defaultState(); db.syncMeta = { ...(await import('../sync.js')).emptyMeta() };
  await bg.serial(() => bg.handle({ type: 'ADD', stock: { symbol: '1102', market: 'TW', name: '亞泥', groups: ['watchlist'] } }));
  await bg.serial(() => bg.handle({ type: 'SETTINGS', strategy: 'colorMode', value: 'mono' }));
  await bg.serial(() => bg.handle({ type: 'DELETE', symbol: '2330' }));
  assert.equal(db.syncMeta.dirty, true);
  assert.ok(db.syncMeta.stocks['1102'].updatedAt > 1);
  assert.equal(db.syncMeta.stocks['2330'].deleted, true);
  assert.ok(db.syncMeta.settings.colorMode > 1);
  await assert.rejects(bg.serial(() => bg.handle({ type: 'SETTINGS', strategy: 'colorMode', value: 'purple' })));
});

test('watchlist groups in the worker: membership merge, delete within a group, rename rules, sync queue', async () => {
  reset(); db.state = defaultState(); db.syncMeta = { ...(await import('../sync.js')).emptyMeta() };
  const add = (symbol, lists) => bg.serial(() => bg.handle({ type: 'ADD', stock: { symbol, market: 'TW', name: symbol, groups: ['watchlist'], lists } }));
  await add('2317', ['g2']);
  await add('2330', ['g3']); // 2330 already in g1 → one row, two groups
  assert.equal(db.state.stocks.filter(s => s.symbol === '2330').length, 1);
  assert.deepEqual(db.state.stocks.find(s => s.symbol === '2330').lists, ['g1', 'g3']);
  assert.equal((await add('2330', ['g3'])).notice, 'DUPLICATE');
  await bg.serial(() => bg.handle({ type: 'DELETE', symbol: '2330', list: 'g3' }));
  assert.deepEqual(db.state.stocks.find(s => s.symbol === '2330').lists, ['g1'], 'removed from g3 only');
  await bg.serial(() => bg.handle({ type: 'DELETE', symbol: '2330', list: 'g1' }));
  assert.equal(db.state.stocks.some(s => s.symbol === '2330'), false, 'last group → stock deleted');
  await bg.serial(() => bg.handle({ type: 'RENAME_GROUP', id: 'g2', name: '半導體' }));
  assert.equal(db.state.watchGroups.find(g => g.id === 'g2').name, '半導體');
  assert.ok(db.syncMeta.groups.g2 > 1, 'rename queued for sync');
  await assert.rejects(bg.serial(() => bg.handle({ type: 'RENAME_GROUP', id: 'g2', name: '四個字的' })), /1–3/);
  await assert.rejects(bg.serial(() => bg.handle({ type: 'RENAME_GROUP', id: 'g9', name: 'x' })));
  await assert.rejects(bg.serial(() => bg.handle({ type: 'RENAME_GROUP', id: 'g2', name: '  ' })));
  const snap = await bg.handle({ type: 'BOOTSTRAP' });
  assert.deepEqual(snap.watchGroups.map(g => g.name), ['1', '半導體', '3', '4', '5']);
});

test('T41 existing alert settings and test notifications still work in 2.0', async () => {
  reset(); db.state = defaultState();
  await bg.serial(() => bg.handle({ type: 'SETTINGS', strategy: 'daytrade', enabled: false }));
  assert.equal(db.state.settings.daytrade, false);
  const r = await bg.serial(() => bg.handle({ type: 'TEST', strategy: 'daytrade' }));
  assert.equal(r.sent, true);
});
