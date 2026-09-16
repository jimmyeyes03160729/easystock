import { VM_MODE, CONFIG_URL, FIREBASE_ROOT } from './environment.js';
import { TTL, SYMBOL, GROUPS, plain, finite, config, stock, watchlist, sha256, isVIP, taipei, marketOpen, fresh, signal, chartURL, ledger, canNotify, defaultState } from './core.js';

const ALARM = 'easystock-five-minutes';
let tail = Promise.resolve();
// All mutations, including simultaneous alarms/messages/clicks, share one queue.
export function serial(fn) {
  const task = tail.then(fn);
  tail = task.catch(() => {});
  return task;
}
async function read(key, fallback) { return (await chrome.storage.local.get(key))[key] ?? fallback; }
async function write(key, value) { await chrome.storage.local.set({ [key]: value }); }
async function state() { return read('state', defaultState()); }
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
async function feeds(now, forced = false) {
  const cache = await read('feedCache', null);
  if (cache && now >= cache.at && now - cache.at < TTL) return cache;
  const at = await read('feedAttempt', 0);
  if (at && now >= at && now - at < TTL) return { ...(cache || { quotes: {}, live: {} }), error: '行情暫時無法更新' };
  if (!forced && !marketOpen(now)) return cache || { quotes: {}, live: {} };
  await write('feedAttempt', now);
  try {
    const [quotes, live] = VM_MODE ? [{ '2330': { name: '台積電（VM 示例）', price: 1000, change_pct: 1.25, updated_at: new Date(now).toISOString() } }, {}] :
      await Promise.all([json(`${FIREBASE_ROOT}/public_feed.json`), json(`${FIREBASE_ROOT}/intraday_live.json`)]);
    if (!plain(quotes) || !plain(live)) throw new Error('行情格式不符');
    const value = { at: now, quotes, live };
    await write('feedCache', value);
    return value;
  } catch { return { ...(cache || { quotes: {}, live: {} }), error: '行情暫時無法更新；舊報價僅供檢視' }; }
}
export function liveSignals(data, stocks, now) {
  // A radar candidate is NOT an entry. Only confirmed OPEN signal positions qualify.
  const positions = data.live?.open_positions;
  if (!plain(positions)) return [];
  return stocks.flatMap(s => {
    const p = positions[s.symbol], q = data.quotes?.[s.symbol];
    if (p?.status !== 'OPEN' || !q || !fresh(p.entry_time, now) || !fresh(q.updated_at, now)) return [];
    // Current public feed may lack previous close/change. Never invent a percentage.
    const pct = finite(q.change_pct) ? q.change_pct : finite(q.previous_close) && q.previous_close > 0 ? (q.price / q.previous_close - 1) * 100 : null;
    const result = signal({ id: `entry:${s.symbol}:${p.entry_time}`, symbol: s.symbol, market: s.market,
      name: s.name, price: q.price, change_pct: pct, generated_at: p.entry_time, quote_at: q.updated_at,
      reason: Array.isArray(p.entry_reasons) ? p.entry_reasons.join('；').slice(0, 200) : '' }, 'daytrade', now, true);
    return result ? [result] : [];
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
  next.routes[id] = { symbol: s.symbol, market: s.market, day: next.day, test, at: now };
  const routes = Object.entries(next.routes).sort((a, b) => b[1].at - a[1].at).slice(0, 500);
  next.routes = Object.fromEntries(routes);
  await write('ledger', next);
  try {
    await chrome.notifications.create(id, {
      type: 'basic', iconUrl: chrome.runtime.getURL('assets/icon128.png'),
      title: `${test ? '【VM 測試】' : ''}【${s.strategy === 'daytrade' ? '當沖多方訊號' : '觸底反彈訊號'}】${s.symbol} ${s.name}`,
      message: `現價 ${s.price.toFixed(2)} 元｜${finite(s.change_pct) ? `${s.change_pct >= 0 ? '+' : ''}${s.change_pct.toFixed(2)}%` : '漲跌幅未提供'}\n${s.reason}${test ? '\n示例數字，非交易訊號、不計額度。' : ''}`,
      buttons: [{ title: '查看線圖' }, { title: '今日忽略' }], priority: 1, silent: false
    });
    return true;
  } catch (e) { await write('ledger', original); throw e; }
}
async function snapshot(refresh = false) {
  const now = Date.now(), st = await state();
  let c = null, configError = '';
  try { c = await remoteConfig(now); } catch (e) { configError = e.message; }
  const data = refresh ? await feeds(now, true) : await read('feedCache', { quotes: {}, live: {} });
  const day = ledger(await read('ledger', null), now);
  return { stocks: st.stocks, settings: st.settings, vip: isVIP(c, st.vipHash), vm: VM_MODE,
    quotes: data.quotes, updatedAt: data.at || null, error: configError || data.error || '',
    marketOpen: marketOpen(now, c?.market_holidays), used: day.count,
    bounce: (c?.bounce_strategy_signals || []).map(x => signal(x, 'rebound', now)).filter(Boolean),
    paymentURL: c?.payment_gateway_url || '' };
}
export async function poll() {
  const now = Date.now();
  if (VM_MODE || !marketOpen(now)) return; // VM mode never auto-generates trading signals.
  const st = await state();
  if (!st.settings.daytrade && !st.settings.rebound) return;
  const c = await remoteConfig(now);
  if (!marketOpen(now, c.market_holidays)) return;
  const data = await feeds(now);
  const signals = [
    ...liveSignals(data, st.stocks, now),
    ...c.daytrade_strategy_signals.map(x => signal(x, 'daytrade', now)),
    ...c.bounce_strategy_signals.map(x => signal(x, 'rebound', now))
  ].filter(Boolean);
  const vip = isVIP(c, st.vipHash);
  for (const s of signals) {
    if (!st.settings[s.strategy] || !st.stocks.some(x => x.symbol === s.symbol && x.market === s.market && x.groups.includes(s.strategy))) continue;
    await notify(s, { vip, now });
  }
}
export async function handle(message) {
  if (!plain(message)) throw new Error('訊息格式不正確');
  const st = await state();
  switch (message.type) {
    case 'SNAPSHOT': return snapshot(message.refresh === true);
    case 'ADD': {
      const row = stock(message.stock);
      if (st.stocks.some(x => x.symbol === row.symbol)) throw new Error('此股票已在自選清單');
      st.stocks = watchlist([...st.stocks, row]); break;
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
      if (!GROUPS.includes(message.strategy) || typeof message.enabled !== 'boolean') throw new Error('開關格式不正確');
      st.settings[message.strategy] = message.enabled; break;
    }
    case 'IMPORT': st.stocks = watchlist(message.stocks); break;
    case 'VIP': {
      if (typeof message.key !== 'string' || !message.key.trim() || message.key.length > 128) throw new Error('授權碼格式不正確');
      const hash = await sha256(message.key.trim());
      const c = await remoteConfig();
      if (!c.vip_keys_hash.includes(hash)) throw new Error('授權碼無效；VIP888 僅供隔離 VM 版測試');
      st.vipHash = hash; break; // Never persist or log the plaintext key.
    }
    case 'TEST': {
      if (!GROUPS.includes(message.strategy)) throw new Error('測試類型不正確');
      await notify({ symbol: '2330', name: '台積電', market: 'TW', price: 1000, change_pct: 1.25,
        strategy: message.strategy, reason: message.strategy === 'daytrade' ? '示例：爆量突破五分 K 區間' : '示例：支撐區反彈、量能回升' }, { test: true });
      return { sent: true };
    }
    default: throw new Error('不支援的操作');
  }
  await write('state', st);
  return snapshot();
}
async function clicked(id, button = 0) {
  const now = Date.now(), current = await read('ledger', null), route = current?.routes?.[id];
  if (!route || !SYMBOL.test(route.symbol) || !['TW', 'TWO'].includes(route.market)) return;
  if (button === 1) {
    // Ignore means suppress, not navigate. A test never mutes real alerts.
    if (!route.test && route.day === taipei(now).date) {
      const day = ledger(current, now); day.ignored[route.symbol] = true; await write('ledger', day);
    }
  } else if (button === 0) await chrome.tabs.create({ url: chartURL(route) });
  await chrome.notifications.clear(id);
}
async function ensureAlarm() {
  if (!(await chrome.alarms.get(ALARM))) await chrome.alarms.create(ALARM, { delayInMinutes: 1, periodInMinutes: 5 });
}
function safe(task) { task.catch(() => { /* No credential-bearing error logs. UI reports current source status. */ }); }
// Listener registration is synchronous, before any await, to survive MV3 suspension.
chrome.runtime.onMessage.addListener((message, sender, respond) => {
  if (sender.id !== chrome.runtime.id || sender.url !== chrome.runtime.getURL('popup.html')) return false;
  serial(() => handle(message)).then(value => respond({ ok: true, value }), e => respond({ ok: false, error: e.message || '操作失敗' }));
  return true;
});
chrome.alarms.onAlarm.addListener(a => { if (a.name === ALARM) safe(serial(poll)); });
chrome.runtime.onInstalled.addListener(() => safe(ensureAlarm()));
chrome.runtime.onStartup.addListener(() => safe(ensureAlarm()));
chrome.notifications.onClicked.addListener(id => safe(serial(() => clicked(id))));
chrome.notifications.onButtonClicked.addListener((id, index) => safe(serial(() => clicked(id, index))));
chrome.notifications.onClosed.addListener(id => safe(serial(async () => {
  const value = await read('ledger', null);
  if (value?.routes?.[id]) { delete value.routes[id]; await write('ledger', value); }
})));
safe(ensureAlarm());
