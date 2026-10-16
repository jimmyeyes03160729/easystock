import { VM_MODE, CONFIG_URL, FIREBASE_ROOT } from './environment.js';
import { createAuth, describeBlocked } from './auth.js';
import { createSync, emptyMeta, legacyMeta, touchStocks, touchSettings } from './sync.js';
import { TTL, TAIEX_TTL, QUOTE_FRESH_MS, SYMBOL, GROUPS, plain, finite, config, stock, watchlist, sha256, isVIP, taipei, marketOpen, fresh, signal, chartURL, ledger, canNotify, defaultState, formatTelegramEntry, formatTelegramExit, matchFilter, calcChangePct, fetchStockClosingQuotes, buildPartialDailyBar, mergeQuote, quoteStampMs, quoteStatus, indexQuality, migrateState, COLOR_MODES, SIGNAL_LABELS } from './core.js';

const ALARM = 'easystock-five-minutes';
let tail = Promise.resolve();
// All state mutations, including simultaneous alarms/messages/clicks, share one queue.
export function serial(fn) {
  const task = tail.then(fn);
  tail = task.catch(() => {});
  return task;
}
// Market-data cache writes have their own short queue. Network I/O happens outside it, so a
// slow quote refresh can never delay adding a stock (2.0 fix for "click add, nothing happens").
let feedTail = Promise.resolve();
export function feedSerial(fn) {
  const task = feedTail.then(fn);
  feedTail = task.catch(() => {});
  return task;
}
function emptyFeed() { return { quotes: {}, live: {}, quoteAttempts: {} }; }
async function commitFeed(patch) {
  return feedSerial(async () => {
    const current = (await read('feedCache', null)) || emptyFeed();
    const next = await patch(structuredClone(current));
    await write('feedCache', next);
    return next;
  });
}
async function cachedHolidays() {
  const cached = await read('configCache', null);
  return Array.isArray(cached?.value?.market_holidays) ? cached.value.market_holidays : [];
}
const quoteInflight = new Set();
function broadcast(message) {
  try { chrome.runtime.sendMessage?.(message)?.catch?.(() => {}); } catch (_) { /* popup closed */ }
}
async function read(key, fallback) { return (await chrome.storage.local.get(key))[key] ?? fallback; }
async function write(key, value) { await chrome.storage.local.set({ [key]: value }); }
async function state() {
  return migrateState(await read('state', null));
}

// ---- 2.0 account + cloud sync wiring ---------------------------------------------------------
let authConfigCache = null;
async function authConfig() {
  if (authConfigCache) return authConfigCache;
  try {
    const res = await fetch(chrome.runtime.getURL('auth-config.json'), { cache: 'no-store' });
    authConfigCache = res.ok ? await res.json() : {};
  } catch (_) { authConfigCache = {}; }
  return authConfigCache;
}
function manifestInfo() {
  try { return chrome.runtime.getManifest?.() || {}; } catch (_) { return {}; }
}
let authInstance = null;
async function auth() {
  if (authInstance) return authInstance;
  const cfg = await authConfig();
  authInstance = createAuth({
    identity: chrome.identity || { getAuthToken: async () => { throw new Error('identity API unavailable'); }, removeCachedAuthToken: async () => {} },
    config: cfg,
    manifest: manifestInfo(),
    sessionStore: chrome.storage.session,
    localStore: chrome.storage.local,
    runtimeId: chrome.runtime?.id || ''
  });
  return authInstance;
}
async function readMeta() {
  const meta = await read('syncMeta', null);
  if (meta) return meta;
  const saved = await read('state', null);
  return saved ? legacyMeta(migrateState(saved)) : emptyMeta();
}
// Runs fn(state, meta) inside the state queue and persists what it returns.
function transact(fn) {
  return serial(async () => {
    const st = await state();
    const meta = await readMeta();
    const out = await fn(st, meta);
    if (out?.state) {
      out.state.rev = (st.rev || 0) + 1;
      out.state.stocks = watchlist(out.state.stocks);
      await write('state', out.state);
      broadcast({ type: 'STATE_UPDATED' });
    }
    if (out?.meta) await write('syncMeta', out.meta);
    return out;
  });
}
let syncInstance = null;
async function syncEngine() {
  if (syncInstance) return syncInstance;
  const cfg = await authConfig();
  const a = await auth();
  syncInstance = createSync({
    auth: a, dbUrl: String(cfg.database_url || '').replace(/\/$/, ''), transact, readMeta,
    online: () => (typeof navigator === 'undefined' ? true : navigator.onLine !== false)
  });
  return syncInstance;
}
async function signedInProfile() {
  try { return await (await auth()).profile(); } catch (_) { return null; }
}
let syncTimer = null;
// Debounced: several quick edits produce one upload. Never awaited from inside the state queue.
function scheduleSync(delay = 3000) {
  clearTimeout(syncTimer);
  syncTimer = setTimeout(() => safe((async () => {
    if (VM_MODE || !(await signedInProfile())?.uid) return;
    await (await syncEngine()).syncNow();
  })()), delay);
}
async function periodicSync(maxPullAgeMs) {
  if (VM_MODE || !(await signedInProfile())?.uid) return null;
  return (await syncEngine()).maybeSync(maxPullAgeMs ? { maxPullAgeMs } : {});
}
async function accountView() {
  const a = await auth();
  const cfg = a.status();
  const profile = await a.profile();
  const meta = await readMeta();
  return {
    configured: cfg.ready, status: cfg.status, missing: cfg.missing, blockedMessage: cfg.ready ? '' : describeBlocked(cfg),
    signedIn: !!profile?.uid, email: profile?.email || '', displayName: profile?.displayName || '',
    uidShort: profile?.uid ? `${profile.uid.slice(0, 6)}…` : '',
    sync: { status: profile?.uid ? meta.status : 'signed_out', lastSyncAt: meta.lastSyncAt || null, lastError: meta.lastError || '', pending: !!meta.dirty }
  };
}
async function json(url, maxBytes = 1500000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 8000);
  try {
    const r = await fetch(url, { signal: controller.signal, cache: 'no-store', credentials: 'omit', redirect: 'error' });
    if (!r.ok) throw new Error(`資料服務暫時無法使用 (${r.status})`);
    if (Number(r.headers.get('content-length')) > maxBytes) throw new Error('資料回應過大');
    const reader = r.body.getReader();
    const chunks = []; let size = 0;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > maxBytes) { await reader.cancel(); throw new Error('資料回應過大'); }
      chunks.push(value);
    }
    const bytes = new Uint8Array(size); let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
    return JSON.parse(new TextDecoder().decode(bytes));
  } finally { clearTimeout(timer); }
}
export async function remoteConfig(now = Date.now()) {
  const cache = await read('configCache', null);
  if (cache && now >= cache.at && now - cache.at < TTL) return config(cache.value);
  // Failed requests are also throttled across worker restarts. No stale VIP grant.
  const attempt = await read('configAttempt', 0);
  if (attempt && now >= attempt && now - attempt < TTL) throw new Error('遠端設定讀取失敗，五分鐘後重試');
  await write('configAttempt', now);
  const value = config(await json(VM_MODE ? chrome.runtime.getURL('vm-config.json') : CONFIG_URL, 250000));
  await write('configCache', { at: now, value });
  return value;
}
// TWSE MIS gives an epoch-ms `tlong` and a Taipei `d`/`t`; both are source time, never receive time.
export function misQuoteAt(row) {
  const tlong = Number(row?.tlong);
  if (Number.isFinite(tlong) && tlong > 1e12) return new Date(tlong).toISOString();
  const d = String(row?.d || ''), t = String(row?.t || '');
  if (/^\d{8}$/.test(d) && /^\d{2}:\d{2}(:\d{2})?$/.test(t)) {
    return `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6, 8)}T${t.length === 5 ? `${t}:00` : t}+08:00`;
  }
  return null;
}
export async function fetchTaiexIndex() {
  if (VM_MODE) {
    const stamp = new Date().toISOString();
    return {
      price: 22800.00,
      change: 120.50,
      change_pct: 0.53,
      time: '13:30:00',
      otc_price: 268.50,
      otc_change: 1.20,
      otc_change_pct: 0.45,
      source: 'VM_SAMPLE', quote_at: stamp, received_at: stamp
    };
  }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 4000);
  try {
    const res = await fetch('https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_t00.tw|otc_o00.tw&json=1&delay=0', {
      signal: controller.signal,
      cache: 'no-store'
    });
    if (!res.ok) return null;
    const json = await res.json();
    const arr = json?.msgArray;
    if (!Array.isArray(arr)) return null;

    const tse = arr.find(m => m && m.c === 't00');
    const otc = arr.find(m => m && m.c === 'o00');

    let tseData = null, otcData = null;
    if (tse) {
      const price = parseFloat(tse.z || tse.y);
      const prev = parseFloat(tse.y);
      if (Number.isFinite(price) && Number.isFinite(prev) && prev > 0) {
        const change = price - prev;
        const change_pct = (change / prev) * 100;
        tseData = {
          price,
          change,
          change_pct,
          time: tse.t || '',
          quote_at: misQuoteAt(tse),
          high: parseFloat(tse.h) || price,
          low: parseFloat(tse.l) || price
        };
      }
    }
    if (otc) {
      const price = parseFloat(otc.z || otc.y);
      const prev = parseFloat(otc.y);
      if (Number.isFinite(price) && Number.isFinite(prev) && prev > 0) {
        const change = price - prev;
        const change_pct = (change / prev) * 100;
        otcData = {
          price,
          change,
          change_pct,
          time: otc.t || ''
        };
      }
    }

    if (!tseData) return null;
    return {
      price: tseData.price,
      change: tseData.change,
      change_pct: tseData.change_pct,
      time: tseData.time,
      high: tseData.high,
      low: tseData.low,
      otc_price: otcData?.price,
      otc_change: otcData?.change,
      otc_change_pct: otcData?.change_pct,
      source: 'TWSE_MIS',
      quote_at: tseData.quote_at,
      received_at: new Date().toISOString()
    };
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}


// The index has its own TTL and its own cache fields; failure keeps the last value and marks the error.
export async function refreshTaiexOnly(now = Date.now()) {
  const taiex = await fetchTaiexIndex().catch(() => null);
  const value = await commitFeed(cur => {
    cur.taiexAttemptAt = now;
    if (taiex) {
      const oldMs = quoteStampMs(cur.taiex), newMs = quoteStampMs(taiex);
      if (!cur.taiex || !finite(oldMs) || !finite(newMs) || newMs >= oldMs) cur.taiex = taiex;
      cur.taiexAt = now;
      cur.taiexError = '';
    } else {
      cur.taiexError = '指數來源暫時無法連線';
    }
    return cur;
  });
  safe(updateMarketStatusIcon(value, now));
  return value;
}
function taiexDue(cache, now) {
  return !cache?.taiexAttemptAt || now < cache.taiexAttemptAt || now - cache.taiexAttemptAt >= TAIEX_TTL;
}

// Watchlist quotes (Yahoo) and real sparklines for specific stocks; persisted, never popup-memory only.
export async function refreshSymbolQuotes(stocks, now = Date.now()) {
  const list = (Array.isArray(stocks) ? stocks : []).filter(s => s && SYMBOL.test(s.symbol));
  if (!list.length || VM_MODE) return read('feedCache', null);
  for (const s of list) quoteInflight.add(s.symbol);
  try {
    const [closingMap, sparkMap] = await Promise.all([
      fetchQuotesWithMarketFallback(list),
      fetchStockSparklines(list).catch(() => ({}))
    ]);
    const value = await commitFeed(cur => {
      cur.quotes ||= {}; cur.quoteAttempts ||= {};
      for (const s of list) {
        const item = closingMap[s.symbol];
        if (item) cur.quotes[s.symbol] = mergeQuote(cur.quotes[s.symbol], item);
        if (cur.quotes[s.symbol] && Array.isArray(sparkMap[s.symbol])) cur.quotes[s.symbol] = { ...cur.quotes[s.symbol], spark: sparkMap[s.symbol] };
        cur.quoteAttempts[s.symbol] = { at: now, ok: !!item };
      }
      cur.watchAt = now;
      return cur;
    });
    broadcast({ type: 'QUOTES_UPDATED', symbols: list.map(s => s.symbol) });
    return value;
  } finally {
    for (const s of list) quoteInflight.delete(s.symbol);
  }
}
// Correct a guessed market (TW/TWO) or a placeholder name once a real quote proves otherwise.
async function reconcileStocks(fixes) {
  if (!fixes.length) return;
  await serial(async () => {
    const st = await state();
    let changed = false;
    for (const fix of fixes) {
      const row = st.stocks.find(x => x.symbol === fix.symbol);
      if (!row) continue;
      if (fix.market && ['TW', 'TWO'].includes(fix.market) && row.market !== fix.market) { row.market = fix.market; changed = true; }
      const name = typeof fix.name === 'string' ? fix.name.trim().slice(0, 60) : '';
      if (name && /^\d{4,6}[A-Z]?$/.test(row.name) && name !== row.name) { row.name = name; changed = true; }
    }
    if (changed) {
      const before = (await state()).stocks;
      st.rev = (st.rev || 0) + 1;
      await write('state', st);
      const meta = await readMeta();
      if (touchStocks(meta, before, st.stocks, Date.now())) { await write('syncMeta', meta); scheduleSync(); }
      broadcast({ type: 'STATE_UPDATED' });
    }
  });
}

// Account messages run outside the state queue: an interactive Google consent may take a while
// and must not block adding stocks. Their own state changes go through transact().
export const ACCOUNT_MESSAGES = new Set(['AUTH_SIGN_IN', 'AUTH_SIGN_OUT', 'SYNC_NOW']);
export async function handleAccount(message) {
  if (VM_MODE) throw new Error('VM 隔離版不提供 Google 登入');
  const a = await auth();
  if (message.type === 'AUTH_SIGN_IN') {
    const cfg = a.status();
    if (!cfg.ready) throw new Error(`${describeBlocked(cfg)}（${cfg.status}）`);
    await a.signIn({ interactive: true });
    const result = await (await syncEngine()).syncNow();
    return { ...(await snapshot(false, false, true)), syncResult: result };
  }
  if (message.type === 'AUTH_SIGN_OUT') {
    clearTimeout(syncTimer);
    await a.signOut();
    // The cloud copy is untouched; the local copy stays usable offline and remembers its owner UID,
    // so a different account signing in next never receives it (see sync.js account switch).
    await transact(async (_st, meta) => { Object.assign(meta, { status: 'signed_out', lastError: '' }); return { meta }; });
    return snapshot(false, false, true);
  }
  if (message.type === 'SYNC_NOW') {
    if (!(await a.profile())?.uid) throw new Error('尚未登入 Google');
    const result = await (await syncEngine()).syncNow();
    return { ...(await snapshot(false, false, true)), syncResult: result };
  }
  throw new Error('不支援的操作');
}
export async function fetchQuotesWithMarketFallback(list) {
  const map = await fetchStockClosingQuotes(list).catch(() => ({}));
  const fixes = [];
  const missing = list.filter(s => !map[s.symbol]);
  if (missing.length) {
    const flipped = missing.map(s => ({ symbol: s.symbol, market: s.market === 'TWO' ? 'TW' : 'TWO' }));
    const alt = await fetchStockClosingQuotes(flipped).catch(() => ({}));
    for (const s of flipped) if (alt[s.symbol]) { map[s.symbol] = alt[s.symbol]; fixes.push({ symbol: s.symbol, market: s.market }); }
  }
  for (const s of list) {
    const name = map[s.symbol]?.name;
    if (name && /^\d{4,6}[A-Z]?$/.test(String(s.name || '')) && name !== s.symbol) fixes.push({ symbol: s.symbol, name });
  }
  // Not awaited: callers may already be inside the state queue (poll), which would deadlock.
  if (fixes.length) safe(reconcileStocks(fixes));
  return map;
}
function queueQuoteRefresh(stocks) {
  const list = (stocks || []).filter(s => s && !quoteInflight.has(s.symbol));
  if (list.length) safe(refreshSymbolQuotes(list));
}

async function feeds(now, forced = false) {
  const cache = await read('feedCache', null);
  const open = marketOpen(now);

  if (!forced && cache?.at && now >= cache.at && now - cache.at < TTL) {
    // The broad feed may be cached for five minutes, but the market index is not (2.0 fix:
    // 1.05 returned the old cache in both branches, so the index waited for the 5-minute feed).
    if (open && taiexDue(cache, now)) return refreshTaiexOnly(now);
    return cache;
  }

  const at = await read('feedAttempt', 0);
  if (!forced && at && now >= at && now - at < TTL) {
    const base = open && taiexDue(cache, now) ? await refreshTaiexOnly(now) : (cache || emptyFeed());
    return { ...base, error: '行情暫時無法更新' };
  }
  if (!forced && !open) return cache || emptyFeed();

  await write('feedAttempt', now);
  // Index refresh runs independently: a broken public feed must not discard a good index value.
  const indexTask = refreshTaiexOnly(now).catch(() => null);
  let quotesRaw = null, live = null, feedError = '';
  if (VM_MODE) {
    const stamp = new Date(now).toISOString();
    quotesRaw = { '2330': { name: '台積電（VM 示例）', price: 1000, change_pct: 1.25, updated_at: stamp, quote_at: stamp } };
    live = {};
  } else {
    const [q, l] = await Promise.allSettled([
      json(`${FIREBASE_ROOT}/public_feed.json`),
      json(`${FIREBASE_ROOT}/intraday_live.json`)
    ]);
    if (q.status === 'fulfilled' && plain(q.value)) quotesRaw = q.value; else feedError = '行情暫時無法更新；舊報價僅供檢視';
    if (l.status === 'fulfilled' && plain(l.value)) live = l.value;
  }

  let closingMap = {}, sparkMap = {}, targets = [];
  if (!VM_MODE) {
    const st = await state().catch(() => null);
    const holidays = await cachedHolidays();
    if (st?.stocks?.length) {
      const known = { ...(cache?.quotes || {}) };
      if (quotesRaw) for (const [sym, q] of Object.entries(quotesRaw)) known[sym] = mergeQuote(known[sym], q);
      targets = st.stocks.filter(row => {
        const q = known[row.symbol];
        const status = quoteStatus(q, now, { holidays }).state;
        return forced || !['live', 'close'].includes(status) || !finite(calcChangePct(q)) ||
          (open && !fresh(q?.quote_at || q?.updated_at, now, QUOTE_FRESH_MS));
      });
      for (const s of targets) quoteInflight.add(s.symbol);
      try {
        [closingMap, sparkMap] = await Promise.all([
          targets.length ? fetchQuotesWithMarketFallback(targets) : {},
          fetchStockSparklines(st.stocks).catch(() => ({}))
        ]);
      } finally {
        for (const s of targets) quoteInflight.delete(s.symbol);
      }
    }
  }
  await indexTask;

  const value = await commitFeed(cur => {
    cur.quotes ||= {}; cur.quoteAttempts ||= {};
    if (quotesRaw) for (const [sym, q] of Object.entries(quotesRaw)) cur.quotes[sym] = mergeQuote(cur.quotes[sym], q);
    for (const [sym, item] of Object.entries(closingMap)) cur.quotes[sym] = mergeQuote(cur.quotes[sym], item);
    for (const [sym, points] of Object.entries(sparkMap)) {
      if (cur.quotes[sym] && Array.isArray(points)) cur.quotes[sym] = { ...cur.quotes[sym], spark: points };
    }
    for (const s of targets) cur.quoteAttempts[s.symbol] = { at: now, ok: !!closingMap[s.symbol] };
    if (live) cur.live = live;
    delete cur.summaryRebound; // 2.0: 觸底反彈 removed from Chrome; drop the old cache field
    if (quotesRaw) cur.at = now;
    cur.watchAt = now;
    return cur;
  });
  safe(updateMarketStatusIcon(value, now));
  return feedError ? { ...value, error: feedError } : value;
}

export async function updateMarketStatusIcon(data, now = Date.now(), explicitTaiex = null) {
  if (!chrome.action || typeof chrome.action.setTitle !== 'function') return;
  const isMarketOpen = marketOpen(now);
  const timeStr = new Date(now).toLocaleTimeString('zh-TW', { hour12: false });
  const openPos = data?.live?.open_positions ? Object.values(data.live.open_positions).filter(p => p?.status === 'OPEN') : [];
  const closedCount = data?.live?.closed_trades ? (Array.isArray(data.live.closed_trades) ? data.live.closed_trades.length : Object.keys(data.live.closed_trades).length) : 0;
  const marketLevel = data?.live?.market_level || (isMarketOpen ? 'GREEN' : 'UNKNOWN');

  const tInfo = explicitTaiex || data?.taiex;
  const statusTag = isMarketOpen ? '' : ' (已收盤)';
  let taiexLine = isMarketOpen ? '加權指數：讀取中...' : '加權指數：休市中';
  let otcLine = '';
  let badgeText = '休';
  let badgeColor = '#64748b';

  if (tInfo && typeof tInfo.price === 'number') {
    const sign = tInfo.change >= 0 ? '+' : '';
    taiexLine = `加權指數：${tInfo.price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} (${sign}${tInfo.change.toFixed(2)} / ${sign}${tInfo.change_pct.toFixed(2)}%)${statusTag}`;
    if (typeof tInfo.otc_price === 'number') {
      const oSign = tInfo.otc_change >= 0 ? '+' : '';
      otcLine = `櫃買指數：${tInfo.otc_price.toFixed(2)} (${oSign}${tInfo.otc_change.toFixed(2)} / ${oSign}${tInfo.otc_change_pct.toFixed(2)}%)${statusTag}`;
    }
  }

  if (isMarketOpen) {
    if (tInfo && typeof tInfo.change === 'number') {
      if (tInfo.change > 0) {
        badgeText = `+${Math.abs(Math.round(tInfo.change))}`;
        badgeColor = '#ef4444';
      } else if (tInfo.change < 0) {
        badgeText = `-${Math.abs(Math.round(tInfo.change))}`;
        badgeColor = '#22c55e';
      } else {
        badgeText = '平';
        badgeColor = '#f59e0b';
      }
      if (badgeText.length > 4) {
        badgeText = tInfo.change >= 0 ? `+${tInfo.change_pct.toFixed(1)}%` : `${tInfo.change_pct.toFixed(1)}%`;
      }
    } else {
      if (marketLevel === 'GREEN') {
        badgeText = openPos.length > 0 ? String(openPos.length) : '多';
        badgeColor = '#ef4444';
      } else if (marketLevel === 'RED') {
        badgeText = '空';
        badgeColor = '#22c55e';
      } else {
        badgeText = openPos.length > 0 ? String(openPos.length) : '震';
        badgeColor = '#f59e0b';
      }
    }
  } else {
    badgeText = '休';
    badgeColor = '#64748b';
  }

  const titleLines = [
    `EasyStock 台股加權指數`,
    taiexLine,
    ...(otcLine ? [otcLine] : [])
  ];

  try {
    await chrome.action.setTitle({ title: titleLines.join('\n') });
    if (chrome.action.setBadgeText) {
      await chrome.action.setBadgeText({ text: '' });
    }
  } catch (_) {}
}
export function liveSignals(data, stocks, now, allAlerts = false) {
  // A radar candidate is NOT an entry. Only confirmed OPEN signal positions qualify.
  const positions = data.live?.open_positions;
  if (!plain(positions)) return [];
  const targets = allAlerts
    ? Object.keys(positions).map(sym => {
        const s = stocks.find(x => x.symbol === sym);
        const p = positions[sym];
        const m = s?.market || (sym.length === 4 && (sym.startsWith('5') || sym.startsWith('6') || sym.startsWith('8')) ? 'TWO' : 'TW');
        return { symbol: sym, market: m, name: p?.name || s?.name || sym, groups: ['daytrade'] };
      })
    : stocks;

  return targets.flatMap(s => {
    const p = positions[s.symbol], q = data.quotes?.[s.symbol];
    if (p?.status !== 'OPEN' || !fresh(p.entry_time, now)) return [];
    if (q && !fresh(q.updated_at, now)) return [];
    // Current public feed may lack previous close/change. Never invent a percentage.
    const price = q && finite(q.price) ? q.price : (finite(p.entry_price) ? p.entry_price : 100);
    const quoteAt = q?.updated_at && fresh(q.updated_at, now) ? q.updated_at : p.entry_time;
    const pct = q && finite(q.change_pct) ? q.change_pct : (q && finite(q.previous_close) && q.previous_close > 0 ? (q.price / q.previous_close - 1) * 100 : (finite(p.change_pct) ? p.change_pct : (finite(p.pnl_pct) ? p.pnl_pct : null)));
    const base = signal({ id: `entry:${s.symbol}:${p.entry_time}`, symbol: s.symbol, market: s.market,
      name: p.name || s.name, price, change_pct: pct, generated_at: p.entry_time, quote_at: quoteAt,
      reason: Array.isArray(p.entry_reasons) ? (p.entry_reasons.join('；').slice(0, 200) || SIGNAL_LABELS.entry) : (p.reason || SIGNAL_LABELS.entry) }, 'daytrade', now, true);
    if (!base) return [];
    return [{
      ...base,
      action: 'BUY',
      entry_price: p.entry_price,
      entry_score: p.entry_score,
      entry_vwap: p.entry_vwap,
      entry_reasons: p.entry_reasons,
      stop_price: p.stop_price,
      take_profit_price: p.take_profit_price,
      telegramText: formatTelegramEntry({ ...p, symbol: s.symbol, name: p.name || s.name })
    }];
  });
}

export function liveExitSignals(data, stocks, now, allAlerts = false) {
  const closedRaw = data.live?.closed_trades;
  if (!closedRaw) return [];
  const list = Array.isArray(closedRaw) ? closedRaw : (plain(closedRaw) ? Object.values(closedRaw) : []);
  return list.flatMap(t => {
    if (!t || t.status !== 'CLOSED' || !fresh(t.exit_time, now)) return [];
    const sym = String(t.symbol);
    const s = stocks.find(x => x.symbol === sym);
    if (!allAlerts && !s) return [];
    const market = s?.market || (sym.length === 4 && (sym.startsWith('5') || sym.startsWith('6') || sym.startsWith('8')) ? 'TWO' : 'TW');
    const name = t.name || s?.name || sym;
    const price = finite(t.exit_price) ? t.exit_price : (finite(t.price) ? t.price : 100);
    const pnl = finite(t.pnl_pct) ? t.pnl_pct : null;
    const base = signal({
      id: `exit:${sym}:${t.exit_time}`,
      symbol: sym,
      market,
      name,
      price,
      change_pct: pnl,
      generated_at: t.exit_time,
      quote_at: t.exit_time,
      reason: t.exit_reason || SIGNAL_LABELS.exit
    }, 'daytrade', now, true);
    if (!base) return [];
    return [{
      ...base,
      action: 'SELL',
      entry_price: t.entry_price,
      exit_price: t.exit_price,
      pnl_pct: t.pnl_pct,
      mfe_pct: t.mfe_pct,
      mae_pct: t.mae_pct,
      duration_seconds: t.duration_seconds,
      exit_reason: t.exit_reason,
      telegramText: formatTelegramExit({ ...t, symbol: sym, name })
    }];
  });
}

async function notify(s, { test = false, vip = false, now = Date.now() } = {}) {
  if (await chrome.notifications.getPermissionLevel() !== 'granted') throw new Error('Chrome 系統通知權限已關閉');
  const original = ledger(await read('ledger', null), now);
  if (!test && !canNotify(s, original, now, vip)) return false;
  const next = structuredClone(original);
  const id = `stockwatch:${crypto.randomUUID()}`;
  // Persist before create: restart cannot double-spend the quota. If Chrome crashes
  // between this write and create, one allowance may be lost (at-most-once policy).
  if (!test) {
    next.count += 1; next.last[s.symbol] = now; next.seen[`${s.strategy}:${s.id}`] = true;
  }
  next.routes[id] = { symbol: s.symbol, market: s.market, name: s.name, strategy: s.strategy, day: next.day, test, at: now };
  const routes = Object.entries(next.routes).sort((a, b) => b[1].at - a[1].at).slice(0, 500);
  next.routes = Object.fromEntries(routes);
  await write('ledger', next);
  try {
    const isExit = s.action === 'SELL' || s.id?.startsWith('exit:');
    const isDaytrade = s.strategy === 'daytrade';
    // 2.0 wording: \u91cf\u591a\u9032\u653b / \u91cf\u6e1b\u9000\u5b88 are observation labels; the signal source is unchanged.
    const label = isExit ? `\u25bc\u3010${SIGNAL_LABELS.exit}\u3011` : `\u25b2\u3010${SIGNAL_LABELS.entry}\u3011`;
    const title = s.customTitle && !s.telegramText ? s.customTitle : `${test ? '\u3010\u7bc4\u4f8b\u3011' : ''}${label}${s.symbol} ${s.name}`;

    const changePctVal = calcChangePct(s);
    const defaultMsg = `現價 ${s.price.toFixed(2)} 元｜${finite(changePctVal) ? `${changePctVal >= 0 ? '+' : ''}${changePctVal.toFixed(2)}%` : '結盤 0.00%'}\n${s.reason}`;
    const message = (s.telegramText || defaultMsg) + (test ? '\n範例數字，非交易訊號、不計額度。' : '');

    await chrome.notifications.create(id, {
      type: 'basic', iconUrl: chrome.runtime.getURL('assets/icon128.png'),
      title,
      message,
      buttons: [{ title: '查看線圖' }, { title: '今日忽略' }], priority: 2, silent: false, requireInteraction: true
    });
    if (typeof chrome.runtime?.sendMessage === 'function') {
      try {
        chrome.runtime.sendMessage({
          type: 'LIVE_SIGNAL',
          signal: { ...s, telegramText: s.telegramText || defaultMsg, title }
        }).catch(() => {});
      } catch { /* ignore if popup is closed */ }
    }
    return true;
  } catch (e) { await write('ledger', original); throw e; }
}
async function snapshot(refresh = false, taiexOnly = false, localOnly = false) {
  let now = Date.now();
  let c = null, configError = '';

  if (localOnly) {
    const cachedConfig = await read('configCache', null);
    try { c = cachedConfig?.value ? config(cachedConfig.value) : null; } catch (_) {}
  } else {
    try { c = await remoteConfig(now); } catch (e) { configError = e.message; }
  }

  let data;
  if (taiexOnly) data = await refreshTaiexOnly(now);
  else if (refresh) data = await feeds(now, true);
  else data = (await read('feedCache', null)) || emptyFeed();

  // State is read after network I/O: a refresh that started before an ADD must not return
  // (and let the popup render) the older watchlist.
  now = Date.now();
  const st = await state();
  const holidays = c?.market_holidays || await cachedHolidays();
  const day = ledger(await read('ledger', null), now);
  safe(updateMarketStatusIcon(data, now));
  // Opening the popup pulls cloud changes at most every 10 minutes (short REST request, no listener).
  if (refresh) safe(periodicSync(10 * 60000).catch(() => null));
  let account = null;
  try { account = await accountView(); } catch (_) { account = null; }

  return {
    rev: st.rev || 0,
    account,
    version: manifestInfo().version_name || manifestInfo().version || '',
    stocks: st.stocks,
    settings: st.settings,
    vip: isVIP(c, st.vipHash),
    vm: VM_MODE,
    quotes: data.quotes || {},
    quoteAttempts: data.quoteAttempts || {},
    pendingQuotes: [...quoteInflight],
    live: data.live || {},
    taiex: data.taiex || null,
    taiexQuality: indexQuality(data.taiex, now, { holidays, lastError: data.taiexError || '' }),
    holidays,
    updatedAt: data.at || null,
    error: configError || data.error || '',
    marketOpen: marketOpen(now, holidays),
    used: day.count,
    paymentURL: c?.payment_gateway_url || ''
  };
}

export async function poll() {
  const now = Date.now();
  if (VM_MODE || !marketOpen(now)) return; // VM mode never auto-generates trading signals.
  let c = null, configError = null;
  try { c = await remoteConfig(now); } catch (e) { configError = e; }
  const holidays = c?.market_holidays || await cachedHolidays();
  if (!marketOpen(now, holidays)) return;
  // 2.0: the index refresh no longer depends on alert settings or on the remote config fetch.
  if (taiexDue(await read('feedCache', null), now)) await refreshTaiexOnly(now).catch(() => null);
  const st = await state();
  if (!st.settings.daytrade) {
    const cache = await read('feedCache', null);
    if (st.stocks.length && (!cache?.watchAt || now - cache.watchAt >= TTL)) await refreshSymbolQuotes(st.stocks, now).catch(() => null);
    return;
  }
  if (configError) throw configError;
  const data = await feeds(now);
  safe(updateMarketStatusIcon(data, now));
  const allDaytrade = st.settings.allDaytradeAlerts !== false;
  const signals = [
    ...(st.settings.daytrade ? liveSignals(data, st.stocks, now, allDaytrade) : []),
    ...(st.settings.daytrade ? liveExitSignals(data, st.stocks, now, allDaytrade) : []),
    ...(st.settings.daytrade ? c.daytrade_strategy_signals.map(x => signal(x, 'daytrade', now)) : []),
  ].filter(Boolean);
  const vip = isVIP(c, st.vipHash);
  for (const s of signals) {
    if (!st.settings[s.strategy]) continue;
    const isLiveTrade = Boolean(s.action);
    const isExit = s.action === 'SELL';
    if (!isExit && !matchFilter(s.price, s.change_pct, st.settings)) {
      continue;
    }
    if (s.strategy === 'daytrade' && isLiveTrade && allDaytrade) {
      // 全市場當沖連動模式：即時買賣訊號直接發送
    } else if (!st.stocks.some(x => x.symbol === s.symbol && x.market === s.market && x.groups.includes(s.strategy))) {
      continue;
    }
    await notify(s, { vip, now });
  }
}
export async function processLiveData(live) {
  if (!plain(live)) return;
  const now = Date.now();
  const data = { quotes: {}, live };
  safe(updateMarketStatusIcon(data, now));
  const st = await state();
  if (!st.settings.daytrade) return;
  const allDaytrade = st.settings.allDaytradeAlerts !== false;
  const signals = [
    ...liveSignals(data, st.stocks, now, allDaytrade),
    ...liveExitSignals(data, st.stocks, now, allDaytrade)
  ];
  const c = await remoteConfig(now).catch(() => null);
  const vip = isVIP(c, st.vipHash);
  for (const s of signals) {
    const isExit = s.action === 'SELL';
    if (!isExit && !matchFilter(s.price, s.change_pct, st.settings)) {
      continue;
    }
    if (allDaytrade) {
      await notify(s, { vip, now });
    } else if (st.stocks.some(x => x.symbol === s.symbol && x.market === s.market && x.groups.includes(s.strategy))) {
      await notify(s, { vip, now });
    }
  }
}
// Read-only / network-only messages never enter the state mutation queue.
export const READ_ONLY_MESSAGES = new Set(['BOOTSTRAP', 'SNAPSHOT', 'AUTH_STATUS', 'FETCH_INTRADAY', 'FETCH_DAILY']);
export async function handle(message) {
  if (!plain(message)) throw new Error('訊息格式不正確');
  const st = await state();
  const beforeStocks = structuredClone(st.stocks);
  const changedSettings = [];
  let notice = '';
  let quoteTargets = [];
  switch (message.type) {
    case 'AUTH_STATUS': return snapshot(false, false, true);
    case 'BOOTSTRAP': return snapshot(false, false, true);
    case 'SNAPSHOT': return snapshot(message.refresh === true, message.taiexOnly === true, false);
    case 'ADD': {
      const row = stock(message.stock);
      const existing = st.stocks.find(x => x.symbol === row.symbol);
      if (existing) {
        const combined = [...new Set([...existing.groups, ...row.groups])];
        if (combined.length === existing.groups.length) {
          // Duplicate is a notice, not a failure, and does not write.
          return { ...(await snapshot()), notice: 'DUPLICATE' };
        }
        existing.groups = combined;
      } else {
        st.stocks = watchlist([...st.stocks, row]);
        quoteTargets = [row];
      }
      notice = 'ADDED';
      break;
    }
    case 'ADD_BATCH': {
      if (!Array.isArray(message.stocks) || !message.stocks.length) throw new Error('批次新增格式不正確');
      const valid = message.stocks.map(s => stock(s));
      let addedCount = 0;
      for (const item of valid) {
        const existing = st.stocks.find(x => x.symbol === item.symbol);
        if (existing) {
          const combined = [...new Set([...existing.groups, ...item.groups])];
          if (combined.length > existing.groups.length) {
            existing.groups = combined;
            addedCount++;
          }
        } else {
          st.stocks.push(item);
          quoteTargets.push(item);
          addedCount++;
        }
      }
      if (addedCount === 0) throw new Error('所有股票均已在自選名單中');
      st.stocks = watchlist(st.stocks);
      break;
    }
    case 'DELETE': st.stocks = st.stocks.filter(x => x.symbol !== message.symbol); break;
    case 'GROUP': {
      if (!GROUPS.includes(message.group) || typeof message.enabled !== 'boolean') throw new Error('群組格式不正確');
      const row = st.stocks.find(x => x.symbol === message.symbol);
      if (!row) throw new Error('找不到股票');
      row.groups = message.enabled ? [...new Set([...row.groups, message.group])] : row.groups.filter(x => x !== message.group);
      if (!row.groups.length) throw new Error('至少保留一個群組，或刪除此股票');
      break;
    }
    case 'SETTINGS': {
      const allowed = [...GROUPS, 'allDaytradeAlerts', 'filterMode', 'minPrice', 'maxPrice', 'minChangePct', 'darkMode', 'colorMode', 'pageSize', 'cardDensity', 'fontSize', 'windowHeight', 'showSparkline', 'preferredBroker', 'autoPageSize'];
      if (!allowed.includes(message.strategy)) throw new Error('開關格式不正確');
      const value = message.enabled !== undefined ? message.enabled : message.value;
      if (message.strategy === 'colorMode' && !COLOR_MODES.includes(value)) throw new Error('漲跌配色格式不正確');
      st.settings[message.strategy] = value;
      changedSettings.push(message.strategy);
      break;
    }
    case 'IMPORT': st.stocks = watchlist(message.stocks); quoteTargets = st.stocks; break;
    case 'VIP': {
      if (typeof message.key !== 'string' || !message.key.trim() || message.key.length > 128) throw new Error('授權碼格式不正確');
      const hash = await sha256(message.key.trim());
      const c = await remoteConfig();
      if (!c.vip_keys_hash.includes(hash)) throw new Error('授權碼無效；VIP888 僅供隔離 VM 版測試');
      st.vipHash = hash; break; // Never persist or log the plaintext key.
    }
    case 'TEST': {
      if (message.action === 'SELL') {
        const fakeExit = {
          symbol: '2330', name: '台積電', market: 'TW', price: 1025, exit_price: 1025, entry_price: 1000,
          pnl_pct: 2.5, mfe_pct: 3.0, mae_pct: -0.5, duration_seconds: 1800, exit_reason: '範例：量能轉弱',
          strategy: 'daytrade', action: 'SELL'
        };
        fakeExit.telegramText = formatTelegramExit(fakeExit);
        await notify(fakeExit, { test: true });
        return { sent: true };
      }
      if (message.strategy === 'daytrade') {
        const fakeEntry = {
          symbol: '2330', name: '台積電', market: 'TW', price: 1000, entry_price: 1000,
          entry_score: '0.88', entry_vwap: 996.5,
          entry_reasons: ['爆量突破五分K區間', '站在VWAP之上', '外資主力買超'],
          stop_price: 985.0, take_profit_price: 1030.0,
          strategy: 'daytrade', action: 'BUY', reason: '示例：爆量突破五分 K 區間'
        };
        fakeEntry.telegramText = formatTelegramEntry(fakeEntry);
        await notify(fakeEntry, { test: true });
        return { sent: true };
      }
      throw new Error('測試類型不正確');
    }
    case 'FETCH_INTRADAY': {
      const sym = String(message.symbol || '').toUpperCase();
      const mkt = String(message.market || 'TW').toUpperCase();
      return await fetchIntradayData(sym, mkt);
    }
    case 'FETCH_DAILY': {
      const sym = String(message.symbol || '').toUpperCase();
      const mkt = String(message.market || 'TW').toUpperCase();
      return await fetchDailyData(sym, mkt);
    }
    default: throw new Error('不支援的操作');
  }
  st.rev = (st.rev || 0) + 1;
  await write('state', st);
  // Local-first: record what changed for the cloud replica, then sync later (debounced, outside the queue).
  const meta = await readMeta();
  const now = Date.now();
  const touched = touchStocks(meta, beforeStocks, st.stocks, now) | touchSettings(meta, changedSettings, now);
  if (touched) { await write('syncMeta', meta); scheduleSync(); }
  // Saved first, shown first; the quote is fetched afterwards and pushed via QUOTES_UPDATED.
  if (quoteTargets.length) queueQuoteRefresh(quoteTargets);
  const result = await snapshot();
  return notice ? { ...result, notice } : result;
}

export async function fetchIntradayData(sym, mkt) {
  if (!sym) return { bars: [], previousClose: null, price: null };
  const ySym = mkt === 'TWO' ? `${sym}.TWO` : `${sym}.TW`;
  const urls = [
    `https://query1.finance.yahoo.com/v8/finance/chart/${ySym}?interval=1m&range=1d`,
    `https://query2.finance.yahoo.com/v8/finance/chart/${ySym}?interval=1m&range=1d`
  ];

  for (const url of urls) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 5000);
    try {
      const res = await fetch(url, { signal: controller.signal, cache: 'no-store' });
      if (!res.ok) continue;
      const json = await res.json();
      const result = json?.chart?.result?.[0];
      if (!result) continue;
      const meta = result.meta;
      const previousClose = finite(meta?.previousClose) ? meta.previousClose : (finite(meta?.chartPreviousClose) ? meta.chartPreviousClose : null);
      const regularPrice = finite(meta?.regularMarketPrice) ? meta.regularMarketPrice : null;
      const timestamps = result.timestamp;
      const quotes = result.indicators?.quote?.[0];
      if (!Array.isArray(timestamps) || !quotes) continue;

      const bars = [];
      let cumAmount = 0, cumVol = 0;
      // Minutes before the first real trade are skipped, not back-filled from the previous close.
      let lastValidPrice = null;

      for (let i = 0; i < timestamps.length; i++) {
        const ts = timestamps[i];
        let c = quotes.close?.[i];
        let o = quotes.open?.[i];
        let h = quotes.high?.[i];
        let l = quotes.low?.[i];
        let v = quotes.volume?.[i] || 0;

        if (!finite(c)) {
          if (!finite(lastValidPrice) || lastValidPrice <= 0) continue;
          c = lastValidPrice;
          o = c; h = c; l = c;
        } else {
          lastValidPrice = c;
        }
        if (!finite(o)) o = c;
        if (!finite(h)) h = Math.max(o, c);
        if (!finite(l)) l = Math.min(o, c);

        cumAmount += c * v;
        cumVol += v;
        const vwap = cumVol > 0 ? cumAmount / cumVol : c;
        const d = new Date(ts * 1000);
        const timeStr = d.toLocaleTimeString('zh-TW', { timeZone: 'Asia/Taipei', hour: '2-digit', minute: '2-digit', hour12: false });
        const dateStr = d.toLocaleDateString('en-CA', { timeZone: 'Asia/Taipei', year: 'numeric', month: '2-digit', day: '2-digit' });

        bars.push({
          timestamp: Number(ts),
          date: dateStr,
          time: timeStr,
          open: Number(o),
          high: Number(h),
          low: Number(l),
          close: Number(c),
          volume: Number(v),
          vwap: Number(vwap)
        });
      }

      return {
        bars,
        previousClose: previousClose || (bars[0] ? bars[0].open : regularPrice),
        price: regularPrice || (bars.at(-1)?.close ?? 0)
      };
    } catch (_) {
    } finally {
      clearTimeout(timer);
    }
  }

  // 若當日分時走勢暫無或失敗，從收盤/即時報價取得真實個股價格，絕對防止誤顯為 1000
  try {
    const qMap = await fetchStockClosingQuotes([sym]);
    const q = qMap[sym];
    if (q && finite(q.price) && q.price > 0) {
      return { bars: [], previousClose: q.previous_close || q.price, price: q.price };
    }
  } catch (_) {}

  return { bars: [], previousClose: null, price: null };
}

export async function fetchDailyData(sym, mkt) {
  if (!sym) return { bars: [] };
  const candidates = [
    mkt === 'TWO' ? `${sym}.TWO` : `${sym}.TW`,
    mkt === 'TWO' ? `${sym}.TW` : `${sym}.TWO`
  ];

  for (const ySym of candidates) {
    const urls = [
      `https://query1.finance.yahoo.com/v8/finance/chart/${ySym}?interval=1d&range=2y`,
      `https://query2.finance.yahoo.com/v8/finance/chart/${ySym}?interval=1d&range=2y`,
      `https://query1.finance.yahoo.com/v8/finance/chart/${ySym}?interval=1d&range=1y`
    ];
    for (const url of urls) {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 6000);
      try {
        const res = await fetch(url, { signal: controller.signal, cache: 'no-store' });
        if (!res.ok) continue;
        const json = await res.json();
        const result = json?.chart?.result?.[0];
        if (!result) continue;
        const timestamps = result.timestamp;
        const quotes = result.indicators?.quote?.[0];
        if (!Array.isArray(timestamps) || !quotes) continue;

        let bars = [];
        let lastValidPrice = null;
        for (let i = 0; i < timestamps.length; i++) {
          const ts = timestamps[i];
          let c = quotes.close?.[i];
          let o = quotes.open?.[i];
          let h = quotes.high?.[i];
          let l = quotes.low?.[i];
          let v = quotes.volume?.[i] || 0;

          if (!finite(c)) {
            if (!finite(lastValidPrice) || lastValidPrice <= 0) continue;
            c = lastValidPrice;
            o = c; h = c; l = c;
          } else {
            lastValidPrice = c;
          }
          if (!finite(o)) o = c;
          if (!finite(h)) h = Math.max(o, c);
          if (!finite(l)) l = Math.min(o, c);

          const d = new Date(ts * 1000);
          const dateStr = d.toLocaleDateString('zh-TW', { timeZone: 'Asia/Taipei', year: 'numeric', month: '2-digit', day: '2-digit' }).replace(/\//g, '-');
          bars.push({
            time: dateStr,
            open: Number(o),
            high: Number(h),
            low: Number(l),
            close: Number(c),
            volume: Number(v)
          });
        }
        if (bars.length > 0) {
          if (marketOpen(Date.now())) {
            try {
              const intraday = await fetchIntradayData(sym, mkt);
              const today = taipei(Date.now()).date;
              const partial = buildPartialDailyBar(intraday?.bars, today);
              if (partial) {
                bars = [...bars.filter(x => x.time !== today), partial].sort((x, y) => String(x.time).localeCompare(String(y.time)));
              }
            } catch (_) {}
          }
          return { bars };
        }
      } catch (_) {
      } finally {
        clearTimeout(timer);
      }
    }
  }
  return { bars: [] };
}

export async function fetchStockSparklines(stocks) {
  if (!Array.isArray(stocks) || !stocks.length) return {};
  const queryList = stocks.map(s => {
    const sym = typeof s === 'string' ? s : s.symbol;
    const m = (typeof s === 'object' && s.market) ? s.market : 'TW';
    return `${sym}.${m === 'TWO' ? 'TWO' : 'TW'}`;
  }).slice(0, 30);

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 4000);
  try {
    const url = `https://query1.finance.yahoo.com/v7/finance/spark?symbols=${queryList.join(',')}&range=1d&interval=15m`;
    const res = await fetch(url, { signal: controller.signal, cache: 'no-store' });
    if (!res.ok) return {};
    const json = await res.json();
    const results = json?.spark?.result;
    if (!Array.isArray(results)) return {};
    const map = {};
    for (const item of results) {
      if (!item?.symbol) continue;
      const rawSym = item.symbol.split('.')[0].toUpperCase();
      const response = item.response?.[0];
      const closes = response?.indicators?.quote?.[0]?.close;
      const timestamps = response?.timestamp;
      if (Array.isArray(closes)) {
        const validPoints = [];
        for (let i = 0; i < closes.length; i++) {
          const close = Number(closes[i]);
          if (!finite(close)) continue;
          const point = { close };
          const ts = Array.isArray(timestamps) ? Number(timestamps[i]) : NaN;
          if (finite(ts)) {
            point.timestamp = ts;
            const d = new Date(ts * 1000);
            point.date = d.toLocaleDateString('en-CA', { timeZone: 'Asia/Taipei', year: 'numeric', month: '2-digit', day: '2-digit' });
            point.time = d.toLocaleTimeString('zh-TW', { timeZone: 'Asia/Taipei', hour: '2-digit', minute: '2-digit', hour12: false });
          }
          validPoints.push(point);
        }
        if (validPoints.length > 0) map[rawSym] = validPoints;
      }
    }
    return map;
  } catch (_) {
    return {};
  } finally {
    clearTimeout(timer);
  }
}

async function clicked(id, button = 0) {
  const now = Date.now(), current = await read('ledger', null), route = current?.routes?.[id];
  if (!route || !SYMBOL.test(route.symbol) || !['TW', 'TWO'].includes(route.market)) return;
  if (button === 1) {
    // Ignore means suppress, not navigate. A test never mutes real alerts.
    if (!route.test && route.day === taipei(now).date) {
      const day = ledger(current, now); day.ignored[route.symbol] = true; await write('ledger', day);
    }
  } else if (button === 0) {
    const priceParam = (route.price && finite(route.price)) ? `&price=${encodeURIComponent(route.price)}` : '';
    const winUrl = chrome.runtime.getURL(`chart.html?symbol=${encodeURIComponent(route.symbol)}&market=${encodeURIComponent(route.market)}&name=${encodeURIComponent(route.name || route.symbol)}${priceParam}&strategy=${encodeURIComponent(route.strategy || '')}`);
    if (chrome.windows && typeof chrome.windows.create === 'function') {
      try {
        await chrome.windows.create({
          url: winUrl,
          type: 'popup',
          width: 960,
          height: 680,
          focused: true
        });
      } catch {
        await chrome.tabs.create({ url: winUrl });
      }
    } else {
      await chrome.tabs.create({ url: chartURL(route) });
    }
  }
  await chrome.notifications.clear(id);
}
async function ensureAlarm() {
  if (!(await chrome.alarms.get(ALARM))) await chrome.alarms.create(ALARM, { delayInMinutes: 0.5, periodInMinutes: 1 });
}
function safe(task) { task.catch(() => { /* No credential-bearing error logs. UI reports current source status. */ }); }
// Listener registration is synchronous, before any await, to survive MV3 suspension.
chrome.runtime.onMessage.addListener((message, sender, respond) => {
  if (sender.id !== chrome.runtime.id) return false;
  if (message.type === 'LIVE_DATA_SYNC') {
    safe(serial(() => processLiveData(message.live)));
    respond({ ok: true });
    return true;
  }
  const allowed = [chrome.runtime.getURL('popup.html'), chrome.runtime.getURL('chart.html')];
  if (!allowed.some(u => sender.url?.startsWith(u))) return false;
  const run = ACCOUNT_MESSAGES.has(message?.type) ? handleAccount(message)
    : (READ_ONLY_MESSAGES.has(message?.type) ? handle(message) : serial(() => handle(message)));
  run.then(value => respond({ ok: true, value }), e => respond({ ok: false, error: e.message || '操作失敗' }));
  return true;
});
chrome.alarms.onAlarm.addListener(a => {
  if (a.name !== ALARM) return;
  safe(serial(poll));
  // Offline queue / retry with backoff / 6-hourly pull. Outside the poll task to avoid queue deadlock.
  safe(periodicSync());
});
// 2.0 upgrade: keep what a 1.05 user had (incl. their dark theme); fresh installs start light.
export async function onInstalledMigration(details = {}) {
  await serial(async () => {
    const saved = await read('state', null);
    if (details.reason === 'update') {
      const migrated = migrateState(saved, { reason: 'update' });
      if (!saved || (saved.version ?? 1) < migrated.version) await write('state', migrated);
      if (!(await read('syncMeta', null))) await write('syncMeta', legacyMeta(migrated));
    } else if (details.reason === 'install' && !(await read('syncMeta', null))) {
      await write('syncMeta', emptyMeta());
    }
  });
}
chrome.runtime.onInstalled.addListener(details => {
  safe(onInstalledMigration(details));
  safe(ensureAlarm());
  safe(updateMarketStatusIcon(null));
});
chrome.runtime.onStartup.addListener(() => {
  safe(ensureAlarm());
  safe(updateMarketStatusIcon(null));
});
chrome.notifications.onClicked.addListener(id => safe(serial(() => clicked(id))));
chrome.notifications.onButtonClicked.addListener((id, index) => safe(serial(() => clicked(id, index))));
chrome.notifications.onClosed.addListener(id => safe(serial(async () => {
  const value = await read('ledger', null);
  if (value?.routes?.[id]) { delete value.routes[id]; await write('ledger', value); }
})));
safe(ensureAlarm());
safe(updateMarketStatusIcon(null));
