// Chrome 2.0 Stage B/C: Google sign-in (mock OAuth) and Firebase sync (mock RTDB REST). Synthetic data only.
import test from 'node:test';
import assert from 'node:assert/strict';
import { createAuth, authConfigStatus, describeBlocked, AUTH_BLOCKED } from '../auth.js';
import { createSync, mergeAll, emptyMeta, legacyMeta, touchStocks, touchSettings, touchGroups, readCloud, sameContent, LEGACY_T } from '../sync.js';
import { defaultState, migrateState, watchlist } from '../core.js';

const DB = 'https://easystock-c237a-default-rtdb.firebaseio.com';
const CFG = { firebase_api_key: 'AIzaSyTEST-public-identifier', database_url: DB };
const MANIFEST = { oauth2: { client_id: '123456789-abcdefg.apps.googleusercontent.com' } };
const S = (symbol, name = symbol, groups = ['watchlist'], market = 'TW') => ({ symbol, market, name, groups });

// ---- fakes -------------------------------------------------------------------------------------
function prune(v) {
  if (Array.isArray(v)) return v.map(prune);
  if (!v || typeof v !== 'object') return v;
  const out = {};
  for (const [k, x] of Object.entries(v)) { const p = prune(x); if (p === null || p === undefined || (typeof p === 'object' && !Array.isArray(p) && !Object.keys(p).length)) continue; out[k] = p; }
  return out;
}
function world() {
  const w = {
    clock: Date.parse('2026-10-16T10:00:00+08:00'),
    online: true,
    googleAccount: 'A',          // Chrome profile's Google account
    consent: true,               // user approves the consent screen
    rejectGoogleTokens: new Set(), // Firebase rejects these Google tokens (expired / revoked)
    removed: [],
    cloud: {},                   // users/{uid}
    idTokens: new Map(),         // Firebase ID token → uid
    requests: [],
    failPut: 0,
    raceOnce: null,
    tokenSeq: 0,
    googleSeq: 0
  };
  w.identity = {
    async getAuthToken({ interactive }) {
      if (!w.consent && interactive) throw new Error('The user did not approve access.');
      if (!w.consent) throw new Error('OAuth2 not granted or revoked.');
      return { token: `gtok-${w.googleAccount}-${w.googleSeq}` };
    },
    async removeCachedAuthToken({ token }) { w.removed.push(token); w.googleSeq += 1; },
    async clearAllCachedAuthTokens() { w.googleSeq += 1; }
  };
  w.fetch = async (url, init = {}) => {
    url = String(url);
    const method = init.method || 'GET';
    w.requests.push({ method, url });
    if (!w.online) throw new TypeError('Failed to fetch');
    if (url.startsWith('https://identitytoolkit.googleapis.com/v1/accounts:signInWithIdp')) {
      if (!url.includes(`key=${encodeURIComponent(CFG.firebase_api_key)}`)) return new Response(JSON.stringify({ error: { message: 'API key not valid' } }), { status: 400 });
      const body = JSON.parse(init.body);
      const token = decodeURIComponent(/access_token=([^&]+)/.exec(body.postBody)[1]);
      if (w.rejectGoogleTokens.has(token)) return new Response(JSON.stringify({ error: { message: 'INVALID_IDP_RESPONSE : token expired' } }), { status: 400 });
      const uid = `uid-${token.split('-')[1]}`;
      const idToken = `idt-${uid}-${++w.tokenSeq}`;
      w.idTokens.set(idToken, uid);
      return new Response(JSON.stringify({ localId: uid, idToken, email: `${uid}@example.test`, displayName: uid, expiresIn: '3600', refreshToken: 'never-stored' }));
    }
    const m = /^https:\/\/easystock-c237a-default-rtdb\.firebaseio\.com\/users\/([^/.]+)\.json\?auth=([^&]+)/.exec(url);
    if (!m) return new Response('{"error":"Permission denied"}', { status: 401 });
    const [, uid, rawToken] = m;
    // Mirrors the proposed rule: users/$uid readable and writable only when auth.uid === $uid.
    if (w.idTokens.get(decodeURIComponent(rawToken)) !== decodeURIComponent(uid)) return new Response('{"error":"Permission denied"}', { status: 401 });
    const etag = () => `"${Buffer.from(JSON.stringify(w.cloud[uid] ?? null)).toString('base64').slice(0, 24)}${JSON.stringify(w.cloud[uid] ?? null).length}"`;
    if (method === 'GET') {
      const res = new Response(JSON.stringify(w.cloud[uid] ?? null), { headers: { ETag: etag() } });
      if (w.raceOnce) { const f = w.raceOnce; w.raceOnce = null; f(uid); }
      return res;
    }
    if (method === 'PUT') {
      if (w.failPut > 0) { w.failPut -= 1; return new Response('{"error":"boom"}', { status: 500 }); }
      const ifMatch = init.headers?.['if-match'];
      if (ifMatch && ifMatch !== etag()) return new Response('{"error":"ETag mismatch"}', { status: 412 });
      w.cloud[uid] = prune(JSON.parse(init.body));
      return url.includes('print=silent') ? new Response(null, { status: 204 }) : new Response(init.body, { status: 200 });
    }
    return new Response('{}', { status: 405 });
  };
  return w;
}
function store(initial = {}) {
  const data = structuredClone(initial);
  return {
    data,
    async get(key) { return { [key]: structuredClone(data[key]) }; },
    async set(obj) { Object.assign(data, structuredClone(obj)); },
    async remove(key) { delete data[key]; }
  };
}
// A device = local storage + session storage + auth + sync engine + a serial state queue.
function device(w, { state = defaultState(), meta = null } = {}) {
  const local = store({ state, syncMeta: meta || emptyMeta() });
  const session = store();
  let tail = Promise.resolve();
  const serial = fn => { const t = tail.then(fn); tail = t.catch(() => {}); return t; };
  const transact = fn => serial(async () => {
    const st = migrateState(local.data.state);
    const mt = structuredClone(local.data.syncMeta);
    const out = await fn(st, mt);
    if (out?.state) { out.state.stocks = watchlist(out.state.stocks); local.data.state = structuredClone(out.state); }
    if (out?.meta) local.data.syncMeta = structuredClone(out.meta);
    return out;
  });
  const auth = createAuth({ identity: w.identity, fetchImpl: w.fetch, config: CFG, manifest: MANIFEST, sessionStore: session, localStore: local, now: () => w.clock });
  const sync = createSync({ auth, dbUrl: DB, fetchImpl: w.fetch, transact, readMeta: async () => structuredClone(local.data.syncMeta), now: () => w.clock, online: () => w.online });
  // Local edit helper (what background.handle does): mutate, then record timestamps for sync.
  const edit = fn => serial(async () => {
    const st = migrateState(local.data.state);
    const before = structuredClone(st.stocks);
    const keys = fn(st) || [];
    st.stocks = watchlist(st.stocks);
    local.data.state = st;
    const mt = local.data.syncMeta;
    touchStocks(mt, before, st.stocks, w.clock);
    touchSettings(mt, keys, w.clock);
  });
  return { local, session, auth, sync, edit, stocks: () => local.data.state.stocks.map(s => s.symbol), state: () => local.data.state };
}

// ---- Google Authentication ---------------------------------------------------------------------
test('T23 missing OAuth client / API key: BLOCKED_BY_OAUTH_CONFIGURATION, never "signed in"', async () => {
  assert.equal(authConfigStatus({}, {}).status, AUTH_BLOCKED);
  assert.deepEqual(authConfigStatus({ firebase_api_key: 'x', database_url: DB }, { oauth2: { client_id: 'YOUR_CHROME_EXTENSION_OAUTH_CLIENT_ID' } }).missing, ['oauth2.client_id']);
  assert.equal(authConfigStatus(CFG, MANIFEST).ready, true);
  const w = world();
  const a = createAuth({ identity: w.identity, fetchImpl: w.fetch, config: {}, manifest: {}, localStore: store() });
  await assert.rejects(a.signIn({ interactive: true }), e => e.code === AUTH_BLOCKED);
  assert.equal(await a.profile(), null);
  assert.equal(w.requests.length, 0);
});

test('an unpacked copy with a different Extension ID is blocked with a plain explanation', async () => {
  const cfg = { ...CFG, extension_id: 'khidbieahmnnandhkcmjceideljgjfid' };
  const wrong = authConfigStatus(cfg, MANIFEST, 'abcdefghijklmnopabcdefghijklmnop');
  assert.equal(wrong.ready, false);
  assert.deepEqual(wrong.missing, ['extension_id']);
  assert.match(describeBlocked(wrong), /abcdefghijklmnopabcdefghijklmnop/);
  assert.match(describeBlocked(wrong), /khidbieahmnnandhkcmjceideljgjfid/);
  assert.match(describeBlocked(wrong), /oauth-test/);
  assert.equal(authConfigStatus(cfg, MANIFEST, 'khidbieahmnnandhkcmjceideljgjfid').ready, true);
  assert.match(describeBlocked(authConfigStatus(cfg, {}, 'khidbieahmnnandhkcmjceideljgjfid')), /OAuth Client ID/);
});

test('T18 Google sign-in yields a Firebase UID; tokens are not written to chrome.storage.local', async () => {
  const w = world(); const d = device(w);
  const profile = await d.auth.signIn({ interactive: true });
  assert.equal(profile.uid, 'uid-A');
  assert.equal(profile.email, 'uid-A@example.test');
  const persisted = JSON.stringify(d.local.data);
  assert.doesNotMatch(persisted, /idt-|gtok-|never-stored/, 'no ID token, Google token or refresh token in local storage');
  assert.match(JSON.stringify(d.session.data), /idt-uid-A/, 'ID token only in session storage');
  const { uid } = await d.auth.getIdToken();
  assert.equal(uid, 'uid-A');
});

test('T19 declining Google consent keeps local use intact', async () => {
  const w = world(); w.consent = false;
  const d = device(w, { state: { ...defaultState(), stocks: [S('2330', '台積電'), S('1102', '亞泥')] } });
  await assert.rejects(d.auth.signIn({ interactive: true }), e => e.code === 'CANCELLED');
  assert.deepEqual(d.stocks(), ['2330', '1102']);
  assert.equal(await d.auth.profile(), null);
});

test('T22 a Google token rejected as expired is evicted from Chrome\'s cache and retried once', async () => {
  const w = world(); const d = device(w);
  w.rejectGoogleTokens.add('gtok-A-0');
  const profile = await d.auth.signIn({ interactive: false });
  assert.equal(profile.uid, 'uid-A');
  assert.deepEqual(w.removed, ['gtok-A-0']);
  // Expired Firebase ID token renews silently.
  w.clock += 3600 * 1000;
  const before = w.tokenSeq;
  await d.auth.getIdToken();
  assert.equal(w.tokenSeq, before + 1);
  // Consent revoked: renewal asks for an explicit sign-in instead of failing silently.
  w.clock += 3600 * 1000; w.consent = false;
  await assert.rejects(d.auth.getIdToken(), e => e.code === 'CANCELLED' || e.code === 'REAUTH_REQUIRED');
});

test('T20 after sign-out the previous account\'s cloud data is no longer reachable', async () => {
  const w = world(); const d = device(w, { state: { ...defaultState(), stocks: [S('2330', '台積電')] } });
  await d.auth.signIn({ interactive: true });
  assert.equal((await d.sync.syncNow()).ok, true);
  await d.auth.signOut();
  assert.equal(await d.auth.profile(), null);
  assert.equal(d.session.data.authSession, undefined);
  await assert.rejects(d.auth.getIdToken(), e => e.code === 'SIGNED_OUT');
  const n = w.requests.length;
  const result = await d.sync.syncNow();
  assert.equal(result.ok, false);
  assert.equal(w.requests.length, n, 'no request made without a session');
  assert.deepEqual(d.stocks(), ['2330'], 'local copy stays usable offline');
});

// ---- Firebase sync ----------------------------------------------------------------------------
test('T24/T09 first sign-in uploads the complete 1.05 watchlist, groups and settings', async () => {
  const w = world();
  const old = { version: 1, stocks: [S('2330', '台積電', ['watchlist', 'daytrade']), S('8299', '群聯', ['watchlist'], 'TWO'), S('00878', '國泰永續高股息')], settings: { daytrade: true, darkMode: true, filterMode: 'custom', minPrice: 30, maxPrice: null, pageSize: 8 }, vipHash: 'abc' };
  const d = device(w, { state: old, meta: legacyMeta(migrateState(old)) });
  await d.auth.signIn({ interactive: true });
  const r = await d.sync.syncNow();
  assert.equal(r.ok, true); assert.equal(r.mode, 'migration');
  const cloud = w.cloud['uid-A'];
  assert.deepEqual(Object.keys(cloud.watchlist).sort(), ['00878', '2330', '8299']);
  assert.deepEqual(cloud.watchlist['2330'].groups, { watchlist: true, daytrade: true });
  assert.equal(cloud.watchlist['8299'].market, 'TWO');
  assert.equal(cloud.watchlist['2330'].source, 'local_migration');
  assert.equal(cloud.settings.darkMode.v, true);
  assert.equal(cloud.alerts.minPrice.v, 30);
  assert.equal(cloud.alerts.maxPrice.v, undefined, 'null threshold stored as an entry without v');
  assert.equal(JSON.stringify(cloud).includes('abc'), false, 'VIP hash is never uploaded');
  assert.deepEqual(d.stocks(), ['2330', '8299', '00878'], 'local data intact');
  assert.equal(d.local.data.syncMeta.dirty, false);
  assert.equal(d.local.data.syncMeta.ownerUid, 'uid-A');
});

test('T25/T26 union with existing cloud data: nothing dropped, same stock once, groups united', async () => {
  const w = world();
  w.cloud['uid-A'] = { watchlist: {
    '2330': { symbol: '2330', market: 'TW', name: '台積電', groups: { daytrade: true }, updatedAt: 100 },
    '2454': { symbol: '2454', market: 'TW', name: '聯發科', groups: { watchlist: true }, updatedAt: 100 }
  } };
  const d = device(w, { state: { ...defaultState(), stocks: [S('2330', '2330'), S('1102', '亞泥')] } });
  await d.auth.signIn({ interactive: true });
  await d.sync.syncNow();
  assert.deepEqual(d.stocks(), ['2330', '1102', '2454']);
  const tsmc = d.state().stocks.find(s => s.symbol === '2330');
  assert.deepEqual(tsmc.groups.sort(), ['daytrade', 'watchlist']);
  assert.equal(tsmc.name, '台積電', 'placeholder name replaced by the real one');
  assert.deepEqual(Object.keys(w.cloud['uid-A'].watchlist).sort(), ['1102', '2330', '2454']);
});

test('T26 repeated syncs never duplicate a stock', async () => {
  const w = world(); const d = device(w, { state: { ...defaultState(), stocks: [S('2330', '台積電')] } });
  await d.auth.signIn({ interactive: true });
  for (let i = 0; i < 4; i++) { w.clock += 60000; await d.sync.syncNow(); }
  assert.deepEqual(d.stocks(), ['2330']);
  assert.equal(Object.keys(w.cloud['uid-A'].watchlist).length, 1);
});

test('T33 an unchanged sync reads once and writes nothing', async () => {
  const w = world(); const d = device(w, { state: { ...defaultState(), stocks: [S('2330', '台積電')] } });
  await d.auth.signIn({ interactive: true });
  await d.sync.syncNow();
  w.requests.length = 0;
  w.clock += 60000;
  const r = await d.sync.syncNow();
  assert.equal(r.wrote, false);
  assert.deepEqual(w.requests.map(x => x.method), ['GET']);
  // maybeSync respects the pull interval: no request at all when nothing is due.
  w.requests.length = 0;
  assert.equal(await d.sync.maybeSync({ maxPullAgeMs: 10 * 60000 }), null);
  assert.equal(w.requests.length, 0);
});

test('two devices: add on one appears on the other; deliberate delete does not resurrect', async () => {
  const w = world();
  const d1 = device(w, { state: { ...defaultState(), stocks: [S('2330', '台積電')] } });
  const d2 = device(w, { state: { ...defaultState(), stocks: [] } });
  await d1.auth.signIn({ interactive: true }); await d1.sync.syncNow();
  await d2.auth.signIn({ interactive: true }); await d2.sync.syncNow();
  assert.deepEqual(d2.stocks(), ['2330']);
  w.clock += 60000;
  await d1.edit(st => { st.stocks.push(S('1102', '亞泥')); });
  await d1.sync.syncNow();
  w.clock += 60000;
  await d2.edit(st => { st.stocks = st.stocks.filter(s => s.symbol !== '2330'); });
  await d2.sync.syncNow();
  w.clock += 60000;
  await d1.sync.syncNow(); await d2.sync.syncNow();
  assert.deepEqual(d1.stocks(), ['1102']);
  assert.deepEqual(d2.stocks(), ['1102']);
  assert.equal(w.cloud['uid-A'].watchlist['2330'].deleted, true);
  // Re-adding later wins over the old tombstone.
  w.clock += 60000;
  await d1.edit(st => { st.stocks.push(S('2330', '台積電')); });
  await d1.sync.syncNow(); await d2.sync.syncNow();
  assert.deepEqual(d2.stocks().sort(), ['1102', '2330']);
});

test('T27/T28 offline edits are kept, marked pending, and uploaded after reconnecting', async () => {
  const w = world(); const d = device(w, { state: { ...defaultState(), stocks: [S('2330', '台積電')] } });
  await d.auth.signIn({ interactive: true }); await d.sync.syncNow();
  w.online = false; w.clock += 60000;
  await d.edit(st => { st.stocks.push(S('00878', '國泰永續高股息')); });
  const off = await d.sync.syncNow();
  assert.equal(off.code, 'OFFLINE');
  assert.equal(d.local.data.syncMeta.dirty, true);
  assert.equal(d.local.data.syncMeta.status, 'offline');
  assert.deepEqual(d.stocks(), ['2330', '00878']);
  w.online = true; w.clock += 60000;
  const r = await d.sync.maybeSync();
  assert.equal(r.ok, true);
  assert.ok(w.cloud['uid-A'].watchlist['00878']);
  assert.equal(d.local.data.syncMeta.dirty, false);
});

test('T29 a failing upload never clears local data; retries back off exponentially', async () => {
  const w = world(); const d = device(w, { state: { ...defaultState(), stocks: [S('2330', '台積電'), S('1102', '亞泥')] } });
  await d.auth.signIn({ interactive: true });
  w.failPut = 2;
  const r1 = await d.sync.syncNow();
  assert.equal(r1.ok, false);
  assert.deepEqual(d.stocks(), ['2330', '1102']);
  const m1 = d.local.data.syncMeta;
  assert.equal(m1.failures, 1); assert.equal(m1.nextRetryAt - w.clock, 30000);
  assert.equal(m1.status, 'error');
  assert.equal(await d.sync.maybeSync(), null, 'not retried before the backoff window');
  w.clock += 30000;
  await d.sync.maybeSync();
  assert.equal(d.local.data.syncMeta.failures, 2);
  assert.equal(d.local.data.syncMeta.nextRetryAt - w.clock, 60000);
  w.clock += 60000;
  assert.equal((await d.sync.maybeSync()).ok, true);
  assert.equal(d.local.data.syncMeta.failures, 0);
  assert.ok(w.cloud['uid-A'].watchlist['1102']);
});

test('concurrent writer: ETag conflict (412) re-reads and merges instead of overwriting', async () => {
  const w = world(); const d = device(w, { state: { ...defaultState(), stocks: [S('2330', '台積電')] } });
  await d.auth.signIn({ interactive: true }); await d.sync.syncNow();
  w.clock += 60000;
  await d.edit(st => { st.stocks.push(S('1102', '亞泥')); });
  // Another device writes between our GET and PUT.
  w.raceOnce = uid => { w.cloud[uid].watchlist['2454'] = { symbol: '2454', market: 'TW', name: '聯發科', groups: { watchlist: true }, updatedAt: w.clock }; };
  const r = await d.sync.syncNow();
  assert.equal(r.ok, true);
  assert.deepEqual(Object.keys(w.cloud['uid-A'].watchlist).sort(), ['1102', '2330', '2454']);
  assert.ok(d.stocks().includes('2454'));
});

test('T21 switching Google accounts never mixes data; each account gets its own list back', async () => {
  const w = world(); const d = device(w, { state: { ...defaultState(), stocks: [S('2330', '台積電')] } });
  w.cloud['uid-B'] = { watchlist: { '2603': { symbol: '2603', market: 'TW', name: '長榮', groups: { watchlist: true }, updatedAt: 5 } } };
  await d.auth.signIn({ interactive: true }); await d.sync.syncNow();
  await d.auth.signOut();
  w.googleAccount = 'B';
  await d.auth.signIn({ interactive: true });
  await d.sync.syncNow();
  assert.deepEqual(d.stocks(), ['2603'], 'B sees only B');
  assert.equal(w.cloud['uid-B'].watchlist['2330'], undefined, 'A\'s stock never uploaded to B');
  assert.deepEqual(d.local.data.syncMeta.stash['uid-A'].stocks.map(s => s.symbol), ['2330'], 'A\'s copy parked locally');
  await d.auth.signOut();
  w.googleAccount = 'A';
  await d.auth.signIn({ interactive: true });
  await d.sync.syncNow();
  assert.deepEqual(d.stocks(), ['2330']);
  assert.equal(w.cloud['uid-A'].watchlist['2603'], undefined);
});

test('T30 the fake database enforces users/{uid} isolation (mirrors the proposed rule)', async () => {
  const w = world(); const d = device(w);
  await d.auth.signIn({ interactive: true });
  const { idToken } = await d.auth.getIdToken();
  const other = await w.fetch(`${DB}/users/uid-B.json?auth=${idToken}`);
  assert.equal(other.status, 401);
  const anon = await w.fetch(`${DB}/users/uid-A.json`);
  assert.equal(anon.status, 401);
});

test('T32 settings: a 1.05 dark theme survives; a fresh device restores the cloud theme', async () => {
  const w = world();
  const old = { version: 1, stocks: [S('2330', '台積電')], settings: { darkMode: true, pageSize: 5 } };
  const d1 = device(w, { state: old, meta: legacyMeta(migrateState(old)) });
  assert.equal(migrateState(old).settings.darkMode, true);
  await d1.auth.signIn({ interactive: true }); await d1.sync.syncNow();
  assert.equal(d1.state().settings.darkMode, true);
  const d2 = device(w); // brand-new install: light default, never set by the user
  assert.equal(d2.state().settings.darkMode, false);
  await d2.auth.signIn({ interactive: true }); await d2.sync.syncNow();
  assert.equal(d2.state().settings.darkMode, true, 'restored from the cloud, not overwritten by the default');
  assert.equal(w.cloud['uid-A'].settings.darkMode.v, true);
  // An explicit change later wins everywhere.
  w.clock += 60000;
  await d2.edit(st => { st.settings.darkMode = false; st.settings.colorMode = 'mono'; return ['darkMode', 'colorMode']; });
  await d2.sync.syncNow(); await d1.sync.syncNow();
  assert.equal(d1.state().settings.darkMode, false);
  assert.equal(d1.state().settings.colorMode, 'mono');
});

test('watchlist groups follow the Google account: names and membership sync across devices', async () => {
  const w = world();
  const d1 = device(w, { state: { ...defaultState(), stocks: [{ ...S('2330', '台積電'), lists: ['g1', 'g2'] }] } });
  await d1.auth.signIn({ interactive: true });
  w.clock += 1000;
  await d1.edit(st => { st.watchGroups = st.watchGroups.map(g => (g.id === 'g2' ? { ...g, name: '半導體' } : g)); });
  touchGroups(d1.local.data.syncMeta, ['g2'], w.clock);
  await d1.sync.syncNow();
  assert.equal(w.cloud['uid-A'].groups.g2.name, '半導體');
  assert.deepEqual(w.cloud['uid-A'].watchlist['2330'].lists, { g1: true, g2: true });
  // A fresh computer gets the names and memberships back after sign-in.
  const d2 = device(w);
  await d2.auth.signIn({ interactive: true }); await d2.sync.syncNow();
  assert.equal(d2.state().watchGroups.find(g => g.id === 'g2').name, '半導體');
  assert.deepEqual(d2.state().stocks.find(s => s.symbol === '2330').lists, ['g1', 'g2']);
  // Moving a stock between groups on one computer shows up on the other.
  w.clock += 60000;
  await d2.edit(st => { st.stocks = st.stocks.map(s => (s.symbol === '2330' ? { ...s, lists: ['g3'] } : s)); });
  await d2.sync.syncNow(); await d1.sync.syncNow();
  assert.deepEqual(d1.state().stocks.find(s => s.symbol === '2330').lists, ['g3']);
});

test('cloud rows written before groups existed land in group 1; invalid group names are ignored', () => {
  const cloud = readCloud({ watchlist: { '2330': { market: 'TW', name: '台積電', groups: { watchlist: true }, updatedAt: 1 } },
    groups: { g1: { name: '自選股', t: 5 }, g2: { name: '太長的名字', t: 5 }, g9: { name: 'x', t: 5 } } });
  assert.deepEqual(cloud.watchlist['2330'].lists, ['g1']);
  assert.deepEqual(Object.keys(cloud.groups), ['g1']);
  assert.equal(cloud.groups.g1.name, '自選股');
});

test('malformed cloud data is ignored, never trusted', () => {
  const cloud = readCloud({ watchlist: { '../x': {}, '2330': { market: 'EVIL', name: 'x', groups: { watchlist: true } }, '2454': { market: 'TW', name: '聯發科', groups: { watchlist: true }, updatedAt: 1 } },
    settings: { darkMode: { v: 'yes', t: 9 }, colorMode: { v: 'mono', t: 9 }, __proto__: { v: 1 } }, alerts: { minPrice: { t: 3 } } });
  assert.deepEqual(Object.keys(cloud.watchlist), ['2454']);
  assert.equal(cloud.settings.darkMode, undefined);
  assert.equal(cloud.settings.colorMode.v, 'mono');
  assert.equal(cloud.alerts.minPrice.v, null);
});

test('more than 100 stocks: local rows are never dropped, extras stay in the cloud', () => {
  const local = { stocks: Array.from({ length: 95 }, (_, i) => S(String(1000 + i))), settings: defaultState().settings };
  const wl = {}; for (let i = 0; i < 10; i++) wl[String(3000 + i)] = { symbol: String(3000 + i), market: 'TW', name: 'X', groups: { watchlist: true }, updatedAt: 1 };
  const r = mergeAll({ local, meta: emptyMeta(), cloudDoc: { watchlist: wl }, mode: 'migration', now: 10 });
  assert.equal(r.stocks.length, 100);
  assert.equal(r.overflow, 5);
  assert.ok(local.stocks.every(s => r.stocks.some(x => x.symbol === s.symbol)));
  assert.equal(Object.keys(r.doc.watchlist).length, 105);
});

test('sameContent ignores profile.updatedAt and Firebase null/empty pruning', () => {
  assert.equal(sameContent({ profile: { updatedAt: 1, schema: 1 }, alerts: {}, settings: { minPrice: { t: 0 } } }, { profile: { updatedAt: 2, schema: 1 }, settings: { minPrice: { t: 0 } } }), true);
  assert.equal(sameContent({ watchlist: { a: { n: 1 } } }, { watchlist: { a: { n: 2 } } }), false);
  assert.equal(LEGACY_T, 1);
});
