// EasyStock Chrome 2.0 — local-first, event-driven cloud sync to Firebase Realtime Database (REST).
//
// Principles
// - chrome.storage.local stays the source the UI reads; the cloud is a replica keyed by Firebase UID.
// - First sign-in on a device ("migration") only merges: union of local and cloud, nothing deleted.
// - Afterwards, per-stock and per-setting last-writer-wins with timestamps; deletions are tombstones,
//   so a stock deleted on purpose does not come back, and a stock added later wins over an old delete.
// - Short REST requests only (no long-lived listeners): GET with ETag, conditional PUT (if-match),
//   bounded retry with exponential backoff, debounced writes, a dirty flag as the offline queue.
// - Never uploaded: quote / K-line caches, tokens, VIP hash, notification ledger, broker data.
import { SYMBOL, GROUPS, plain, finite, BROKERS, defaultState } from './core.js';

export const SYNC_SCHEMA = 1;
export const ALERT_KEYS = ['daytrade', 'allDaytradeAlerts', 'filterMode', 'minPrice', 'maxPrice', 'minChangePct'];
export const PREF_KEYS = ['darkMode', 'colorMode', 'fontSize', 'pageSize', 'cardDensity', 'windowHeight', 'showSparkline', 'preferredBroker'];
export const SYNC_KEYS = [...ALERT_KEYS, ...PREF_KEYS];
export const MAX_STOCKS = 100;
export const TOMBSTONE_TTL_MS = 90 * 86400000;
export const LEGACY_T = 1; // timestamp for values that existed before 2.0 (1.05 upgrade)
const MAX_DOC_BYTES = 256 * 1024;

const isBool = v => typeof v === 'boolean';
const numOrNull = v => v === null || finite(v);
const VALIDATORS = {
  daytrade: isBool, allDaytradeAlerts: isBool, showSparkline: isBool, darkMode: isBool,
  filterMode: v => v === 'all' || v === 'custom',
  minPrice: numOrNull, maxPrice: numOrNull, minChangePct: numOrNull,
  pageSize: v => Number.isInteger(v) && v >= 3 && v <= 10,
  cardDensity: v => v === 'compact' || v === 'normal',
  windowHeight: v => finite(v) && v >= 380 && v <= 580,
  fontSize: v => ['small', 'standard', 'large'].includes(v),
  preferredBroker: v => BROKERS.some(b => b.id === v),
  colorMode: v => v === 'redgreen' || v === 'mono'
};
const NULLABLE = new Set(['minPrice', 'maxPrice', 'minChangePct']);

export function validSetting(key, value) { return !!VALIDATORS[key] && VALIDATORS[key](value); }

export function emptyMeta() {
  return { schema: SYNC_SCHEMA, ownerUid: null, stocks: {}, settings: {}, dirty: false, changeSeq: 0,
    lastSyncAt: null, lastPullAt: null, failures: 0, nextRetryAt: 0, status: 'signed_out', lastError: '', stash: {} };
}

// Meta for a device that already had 1.05 data: every existing value counts as a real (legacy) choice.
export function legacyMeta(state) {
  const meta = emptyMeta();
  for (const s of state?.stocks || []) meta.stocks[s.symbol] = { updatedAt: LEGACY_T };
  for (const key of SYNC_KEYS) if (state?.settings && key in state.settings) meta.settings[key] = LEGACY_T;
  return meta;
}

const sameGroups = (a, b) => [...a].sort().join() === [...b].sort().join();

// Record what changed in a local mutation (called inside the state queue).
export function touchStocks(meta, before, after, now) {
  const prev = new Map((before || []).map(s => [s.symbol, s]));
  const next = new Map((after || []).map(s => [s.symbol, s]));
  let changed = false;
  for (const [sym, s] of next) {
    const p = prev.get(sym);
    if (!p || p.market !== s.market || p.name !== s.name || !sameGroups(p.groups, s.groups)) {
      meta.stocks[sym] = { updatedAt: now, ...(p ? { addedAt: meta.stocks[sym]?.addedAt } : { addedAt: now }) };
      changed = true;
    }
  }
  for (const sym of prev.keys()) {
    if (!next.has(sym)) { meta.stocks[sym] = { updatedAt: now, deleted: true }; changed = true; }
  }
  if (changed) markDirty(meta);
  return changed;
}
export function touchSettings(meta, keys, now) {
  const synced = keys.filter(k => SYNC_KEYS.includes(k));
  for (const key of synced) meta.settings[key] = now;
  if (synced.length) markDirty(meta);
  return synced.length > 0;
}
export function markDirty(meta) { meta.dirty = true; meta.changeSeq = (meta.changeSeq || 0) + 1; }

function groupList(raw) {
  if (Array.isArray(raw)) return raw.filter(g => GROUPS.includes(g));
  if (plain(raw)) return GROUPS.filter(g => raw[g] === true);
  return [];
}
// Defensive read of the cloud document: anything malformed is ignored, never trusted.
export function readCloud(doc) {
  const out = { watchlist: {}, alerts: {}, settings: {}, extra: {} };
  if (!plain(doc)) return out;
  for (const [key, value] of Object.entries(doc)) {
    if (!['watchlist', 'alerts', 'settings', 'profile'].includes(key)) out.extra[key] = value;
  }
  if (plain(doc.watchlist)) {
    for (const [sym, raw] of Object.entries(doc.watchlist)) {
      if (!SYMBOL.test(sym) || !plain(raw)) continue;
      const updatedAt = finite(raw.updatedAt) ? raw.updatedAt : 0;
      if (raw.deleted === true) { out.watchlist[sym] = { symbol: sym, deleted: true, updatedAt }; continue; }
      const groups = groupList(raw.groups);
      const name = typeof raw.name === 'string' ? raw.name.trim().slice(0, 60) : '';
      if (!['TW', 'TWO'].includes(raw.market) || !groups.length || !name) continue;
      out.watchlist[sym] = { symbol: sym, market: raw.market, name, groups, updatedAt, addedAt: finite(raw.addedAt) ? raw.addedAt : updatedAt };
    }
  }
  for (const section of ['alerts', 'settings']) {
    if (!plain(doc[section])) continue;
    for (const [key, raw] of Object.entries(doc[section])) {
      if (!SYNC_KEYS.includes(key) || !plain(raw)) continue;
      const value = 'v' in raw ? raw.v : (NULLABLE.has(key) ? null : undefined);
      if (!validSetting(key, value)) continue;
      out[section][key] = { v: value, t: finite(raw.t) ? raw.t : 0 };
    }
  }
  return out;
}

const isPlaceholderName = (name, sym) => !name || name === sym || /^\d{4,6}[A-Z]?$/.test(name);

/**
 * Merge local state with the cloud document.
 * mode 'migration': first sync of this device's data into this account — union only, nothing removed.
 * mode 'sync': regular sync — per-item last-writer-wins, tombstones honoured.
 */
export function mergeAll({ local, meta, cloudDoc, mode = 'sync', now = Date.now() }) {
  const cloud = readCloud(cloudDoc);
  const nextMeta = structuredClone(meta);
  const localStocks = local.stocks || [];
  const localMap = new Map(localStocks.map(s => [s.symbol, s]));
  const symbols = new Set([...localMap.keys(), ...Object.keys(cloud.watchlist), ...Object.keys(nextMeta.stocks || {})]);
  const kept = new Map();
  const cloudOut = {};
  const removedLocally = [];

  for (const sym of symbols) {
    const l = localMap.get(sym) || null;
    const lm = nextMeta.stocks[sym] || null;
    const c = cloud.watchlist[sym] || null;
    const lT = l ? (mode === 'migration' ? Math.max(lm?.updatedAt || 0, now) : (lm?.updatedAt ?? LEGACY_T)) : (lm?.deleted ? lm.updatedAt : -1);
    const cT = c ? c.updatedAt : -1;

    if (l && (!c || c.deleted)) {
      if (!c || mode === 'migration' || lT > cT) {
        kept.set(sym, { ...l });
        nextMeta.stocks[sym] = { updatedAt: lT, addedAt: lm?.addedAt ?? lT };
      } else {
        removedLocally.push(sym);
        nextMeta.stocks[sym] = { updatedAt: cT, deleted: true };
      }
    } else if (!l && c && !c.deleted) {
      if (lm?.deleted && lT >= cT && mode !== 'migration') {
        nextMeta.stocks[sym] = { updatedAt: lT, deleted: true };
      } else {
        kept.set(sym, { symbol: sym, market: c.market, name: c.name, groups: [...c.groups] });
        nextMeta.stocks[sym] = { updatedAt: Math.max(cT, 0), addedAt: c.addedAt };
      }
    } else if (l && c && !c.deleted) {
      let row;
      if (mode === 'migration' || lT === cT) {
        // Same stock on both sides: one row, groups united, best known name.
        const newer = cT > lT ? c : l;
        row = { symbol: sym, market: newer.market, name: isPlaceholderName(newer.name, sym) ? (isPlaceholderName(l.name, sym) ? c.name : l.name) : newer.name,
          groups: [...new Set([...l.groups, ...c.groups])].filter(g => GROUPS.includes(g)) };
      } else {
        const newer = cT > lT ? c : l;
        row = { symbol: sym, market: newer.market, name: newer.name, groups: [...newer.groups] };
        if (isPlaceholderName(row.name, sym)) row.name = isPlaceholderName(l.name, sym) ? c.name : l.name;
      }
      kept.set(sym, row);
      nextMeta.stocks[sym] = { updatedAt: Math.max(lT, cT), addedAt: lm?.addedAt ?? c.addedAt };
    } else {
      // Both absent / deleted: keep the newest tombstone.
      const t = Math.max(lm?.deleted ? lm.updatedAt : -1, c?.deleted ? c.updatedAt : -1);
      if (t >= 0) nextMeta.stocks[sym] = { updatedAt: t, deleted: true };
      else delete nextMeta.stocks[sym];
    }
  }

  // Local order first, then new cloud rows by addedAt. Never drop a local row to make room.
  const ordered = [];
  for (const s of localStocks) if (kept.has(s.symbol)) ordered.push(kept.get(s.symbol));
  const added = [...kept.values()].filter(s => !localMap.has(s.symbol))
    .sort((a, b) => (nextMeta.stocks[a.symbol]?.addedAt || 0) - (nextMeta.stocks[b.symbol]?.addedAt || 0) || a.symbol.localeCompare(b.symbol));
  const overflow = Math.max(0, ordered.length + added.length - MAX_STOCKS);
  const stocks = [...ordered, ...added].slice(0, MAX_STOCKS);
  const shown = new Set(stocks.map(s => s.symbol));

  for (const [sym, m] of Object.entries(nextMeta.stocks)) {
    if (m.deleted) {
      if (now - m.updatedAt > TOMBSTONE_TTL_MS && m.updatedAt > LEGACY_T) { delete nextMeta.stocks[sym]; continue; }
      cloudOut[sym] = { symbol: sym, deleted: true, updatedAt: m.updatedAt };
    } else if (shown.has(sym)) {
      const s = kept.get(sym);
      const prevSource = typeof cloudDoc?.watchlist?.[sym]?.source === 'string' ? cloudDoc.watchlist[sym].source : '';
      cloudOut[sym] = { symbol: sym, market: s.market, name: s.name, groups: Object.fromEntries(s.groups.map(g => [g, true])),
        updatedAt: m.updatedAt, addedAt: m.addedAt ?? m.updatedAt,
        source: prevSource === 'local_migration' || prevSource === 'chrome' ? prevSource : (mode === 'migration' && localMap.has(sym) ? 'local_migration' : 'chrome') };
    }
  }
  // Rows that did not fit locally stay in the cloud untouched.
  for (const [sym, c] of Object.entries(cloud.watchlist)) {
    if (!(sym in cloudOut) && !c.deleted) cloudOut[sym] = { symbol: sym, market: c.market, name: c.name, groups: Object.fromEntries(c.groups.map(g => [g, true])), updatedAt: c.updatedAt, addedAt: c.addedAt };
  }

  // Settings: field-level last-writer-wins. Never-set local defaults (no timestamp) lose to any cloud value,
  // so a restored dark theme is not overwritten by the 2.0 light default, and a 1.05 choice is kept.
  const settings = { ...local.settings };
  const alertsOut = {}, settingsOut = {};
  for (const key of SYNC_KEYS) {
    const section = ALERT_KEYS.includes(key) ? 'alerts' : 'settings';
    const c = cloud[section][key];
    const lT = nextMeta.settings[key] ?? -1;
    let value = settings[key], t = lT;
    if (c && c.t > lT) { value = c.v; t = c.t; settings[key] = c.v; nextMeta.settings[key] = c.t; }
    if (!validSetting(key, value)) continue;
    // Firebase cannot store null: a cleared threshold is an entry without "v".
    (section === 'alerts' ? alertsOut : settingsOut)[key] = value === null ? { t: Math.max(t, 0) } : { v: value, t: Math.max(t, 0) };
  }

  const doc = {
    ...cloud.extra,
    profile: { schema: SYNC_SCHEMA, client: 'chrome-extension', updatedAt: now },
    watchlist: cloudOut, alerts: alertsOut, settings: settingsOut
  };
  return { stocks, settings, meta: nextMeta, doc, overflow, removedLocally };
}

function stable(value) {
  if (Array.isArray(value)) return `[${value.map(stable).join(',')}]`;
  if (plain(value)) return `{${Object.keys(value).sort().map(k => `${JSON.stringify(k)}:${stable(value[k])}`).join(',')}}`;
  return JSON.stringify(value ?? null);
}
// Compare documents ignoring profile.updatedAt (which changes on every write by design).
// Firebase drops nulls and empty objects, so both sides are pruned the same way first.
function prune(value) {
  if (Array.isArray(value)) return value.map(prune);
  if (!plain(value)) return value;
  const out = {};
  for (const [k, v] of Object.entries(value)) {
    const p = prune(v);
    if (p === null || p === undefined || (plain(p) && !Object.keys(p).length)) continue;
    out[k] = p;
  }
  return out;
}
export function sameContent(a, b) {
  const strip = d => {
    if (!plain(d)) return {};
    const { profile, ...rest } = d;
    return prune({ ...rest, profile: plain(profile) ? { ...profile, updatedAt: 0 } : null });
  };
  return stable(strip(a)) === stable(strip(b));
}

function friendlyHttp(status) {
  if (status === 401 || status === 403) return { code: 'PERMISSION_DENIED', message: '雲端權限不足：Firebase Rules 尚未開放 users/{uid}' };
  if (status === 412) return { code: 'CONFLICT', message: '雲端資料同時被修改' };
  return { code: 'NETWORK', message: `雲端同步暫時失敗 (${status})` };
}

/**
 * Sync engine. Dependencies:
 *  auth.getIdToken() → { uid, idToken }
 *  transact(fn) runs fn(state, meta) inside the state queue; fn returns { state?, meta } to persist.
 *  readMeta() → current meta (read-only snapshot)
 */
export function createSync({ auth, dbUrl, fetchImpl = fetch, transact, readMeta, now = () => Date.now(), online = () => true }) {
  let running = null, again = false;

  function backoff(meta) {
    meta.failures = (meta.failures || 0) + 1;
    meta.nextRetryAt = now() + Math.min(30 * 60000, 30000 * 2 ** (meta.failures - 1));
  }
  async function setStatus(status, extra = {}) {
    await transact(async (_state, meta) => { Object.assign(meta, { status }, extra); return { meta }; });
  }

  async function request(url, init) {
    const res = await fetchImpl(url, { cache: 'no-store', credentials: 'omit', redirect: 'error', ...init });
    return res;
  }

  async function once() {
    if (!online()) { await setStatus('offline'); return { ok: false, code: 'OFFLINE' }; }
    let token;
    try { token = await auth.getIdToken(); } catch (e) {
      const code = e?.code || 'AUTH';
      const status = code === 'SIGNED_OUT' ? 'signed_out' : (code === 'BLOCKED_BY_OAUTH_CONFIGURATION' ? 'blocked' : 'reauth');
      await setStatus(status, { lastError: code === 'SIGNED_OUT' ? '' : (e?.message || '需要重新登入') });
      return { ok: false, code };
    }
    const base = `${dbUrl}/users/${encodeURIComponent(token.uid)}.json`;
    const authQuery = `auth=${encodeURIComponent(token.idToken)}`;
    await setStatus('syncing');
    for (let attempt = 0; attempt < 3; attempt++) {
      let res;
      try { res = await request(`${base}?${authQuery}`, { headers: { 'X-Firebase-ETag': 'true' } }); }
      catch (_) { return fail({ code: 'NETWORK', message: '雲端同步暫時失敗（網路）' }); }
      if (!res.ok) return fail(friendlyHttp(res.status));
      const etag = res.headers.get('ETag') || '';
      let cloudDoc = null;
      try { cloudDoc = await res.json(); } catch (_) { cloudDoc = null; }

      let plan = null;
      await transact(async (state, meta) => {
        let mode = 'sync';
        let localState = { stocks: state.stocks, settings: state.settings };
        let workMeta = meta;
        if (!meta.ownerUid) mode = 'migration';
        else if (meta.ownerUid !== token.uid) {
          // Account switch: park the previous account's local copy on this device only, and start from
          // this account's own parked copy (if any). Data never crosses between UIDs.
          workMeta = structuredClone(meta);
          workMeta.stash ||= {};
          workMeta.stash[meta.ownerUid] = { stocks: state.stocks, settings: Object.fromEntries(SYNC_KEYS.filter(k => k in state.settings).map(k => [k, state.settings[k]])), metaStocks: meta.stocks, metaSettings: meta.settings, at: now() };
          const own = workMeta.stash[token.uid];
          const defaults = Object.fromEntries(SYNC_KEYS.map(k => [k, defaultState().settings[k]]).filter(([, v]) => v !== undefined));
          localState = { stocks: own?.stocks || [], settings: { ...state.settings, ...defaults, ...(own?.settings || {}) } };
          workMeta.stocks = own?.metaStocks || {};
          workMeta.settings = own?.metaSettings || {};
          delete workMeta.stash[token.uid];
          mode = own ? 'migration' : 'sync';
        }
        const merged = mergeAll({ local: localState, meta: workMeta, cloudDoc, mode, now: now() });
        merged.meta.ownerUid = token.uid;
        plan = { doc: merged.doc, seq: merged.meta.changeSeq, overflow: merged.overflow, mode };
        const nextState = { ...state, stocks: merged.stocks, settings: merged.settings };
        const localChanged = JSON.stringify(nextState.stocks) !== JSON.stringify(state.stocks) || JSON.stringify(nextState.settings) !== JSON.stringify(state.settings);
        return { state: localChanged ? nextState : undefined, meta: merged.meta };
      });

      const body = JSON.stringify(plan.doc);
      if (body.length > MAX_DOC_BYTES) return fail({ code: 'TOO_LARGE', message: '雲端資料超過大小上限，已停止上傳' });
      if (sameContent(plan.doc, cloudDoc)) {
        // Nothing new for the cloud: no write (saves Spark quota), just record the pull.
        await finish(plan);
        return { ok: true, mode: plan.mode, overflow: plan.overflow, wrote: false };
      }
      let put;
      try {
        put = await request(`${base}?${authQuery}&print=silent`, { method: 'PUT', headers: { 'Content-Type': 'application/json', ...(etag ? { 'if-match': etag } : {}) }, body });
      } catch (_) { return fail({ code: 'NETWORK', message: '雲端同步暫時失敗（網路）' }); }
      if (put.status === 412) continue; // someone else wrote first: re-read, re-merge, retry
      if (!put.ok) return fail(friendlyHttp(put.status));
      await finish(plan);
      return { ok: true, mode: plan.mode, overflow: plan.overflow, wrote: true };
    }
    return fail({ code: 'CONFLICT', message: '雲端資料持續被同時修改，稍後重試' });
  }

  async function finish(plan) {
    await transact(async (_state, meta) => {
      // Only clear the dirty flag if nothing changed locally while the upload was in flight.
      if ((meta.changeSeq || 0) === plan.seq) meta.dirty = false;
      Object.assign(meta, { status: 'synced', lastError: plan.overflow ? `自選上限 ${MAX_STOCKS} 檔，${plan.overflow} 檔保留在雲端未顯示` : '', lastSyncAt: new Date(now()).toISOString(), lastPullAt: now(), failures: 0, nextRetryAt: 0 });
      return { meta };
    });
  }

  async function fail(err) {
    await transact(async (_state, meta) => { backoff(meta); Object.assign(meta, { status: 'error', lastError: err.message }); return { meta }; });
    return { ok: false, code: err.code, message: err.message };
  }

  // De-duplicated: concurrent calls share one run; a call during a run schedules exactly one more.
  function syncNow() {
    if (running) { again = true; return running; }
    running = (async () => {
      let result;
      do { again = false; result = await once(); } while (again && result?.ok);
      return result;
    })().finally(() => { running = null; });
    return running;
  }

  // Alarm / popup hook: sync when dirty and the backoff window passed, or when the last pull is old.
  async function maybeSync({ maxPullAgeMs = 6 * 3600000 } = {}) {
    const meta = (await readMeta()) || emptyMeta();
    if (now() < (meta.nextRetryAt || 0)) return null; // backoff applies to pulls and pushes alike
    const due = meta.dirty || !meta.lastPullAt || now() - meta.lastPullAt >= maxPullAgeMs;
    return due ? syncNow() : null;
  }

  return { syncNow, maybeSync };
}
