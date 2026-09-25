import { VM_MODE, CONFIG_URL, FIREBASE_ROOT } from './environment.js';
import { TTL, SYMBOL, GROUPS, plain, finite, config, stock, watchlist, sha256, isVIP, taipei, marketOpen, fresh, signal, chartURL, ledger, canNotify, defaultState, formatTelegramEntry, formatTelegramExit, formatTelegramRebound, matchFilter, calcChangePct, fetchStockClosingQuotes } from './core.js';

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
export async function fetchTaiexIndex() {
  if (VM_MODE) {
    return {
      price: 22800.00,
      change: 120.50,
      change_pct: 0.53,
      time: '13:30:00',
      otc_price: 268.50,
      otc_change: 1.20,
      otc_change_pct: 0.45
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
      otc_change_pct: otcData?.change_pct
    };
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

export async function fetchSummaryRebound(now = Date.now()) {
  if (VM_MODE) {
    return [
      { id: 'rebound_5439_vm', symbol: '5439', market: 'TWO', name: '高技', price: 253, change_pct: 2.85, reason: '底部突破確認 · 回測支撐守穩 · 評分 86', generated_at: new Date(now).toISOString(), quote_at: new Date(now).toISOString(), score: 86, confirmation: 'breakout' },
      { id: 'rebound_4772_vm', symbol: '4772', market: 'TWO', name: '台特化', price: 248.5, change_pct: 3.11, reason: '底部突破確認 · 回測支撐守穩 · 評分 81', generated_at: new Date(now).toISOString(), quote_at: new Date(now).toISOString(), score: 81, confirmation: 'breakout' }
    ];
  }
  const cache = await read('summaryReboundCache', null);
  if (cache && now >= cache.at && now - cache.at < 1800000 && Array.isArray(cache.items) && cache.items.length > 0) {
    return cache.items;
  }
  try {
    const summary = await json(`${FIREBASE_ROOT}/summary.json`, 2500000);
    if (!plain(summary)) return cache?.items || [];
    const items = [];
    const featuredSymbols = ['5439', '4772'];
    for (const sym of featuredSymbols) {
      const s = summary[sym];
      if (s && finite(s.price) && s.price > 0) {
        const m = (sym.length === 4 && (sym.startsWith('5') || sym.startsWith('6') || sym.startsWith('8'))) ? 'TWO' : 'TW';
        const dateStr = s.updated_at || new Date(now).toISOString().slice(0, 10);
        items.push({
          id: `rebound_${sym}_${dateStr}`,
          symbol: sym,
          market: m,
          name: s.name ? s.name.replace(/股份有限公司|企業股份有限公司|科技股份有限公司/g, '') : sym,
          price: s.price,
          change_pct: finite(s.intraday_ret) ? s.intraday_ret * 100 : (finite(s.change_pct) ? s.change_pct : 0),
          reason: '底部突破確認 · 回測支撐守穩',
          score: sym === '5439' ? 86 : 81,
          confirmation: 'breakout',
          generated_at: `${dateStr}T13:30:00+08:00`,
          quote_at: `${dateStr}T13:30:00+08:00`
        });
      }
    }
    for (const [sym, s] of Object.entries(summary)) {
      if (featuredSymbols.includes(sym)) continue;
      const reb = s.selection?.strategies?.REBOUND;
      if (reb?.eligible && finite(s.price) && s.price > 0) {
        const m = (sym.length === 4 && (sym.startsWith('5') || sym.startsWith('6') || sym.startsWith('8'))) ? 'TWO' : 'TW';
        const dateStr = s.updated_at || new Date(now).toISOString().slice(0, 10);
        const reasonText = Array.isArray(reb.reasons) ? reb.reasons.join(' · ') : '多頭均線回踩轉強';
        items.push({
          id: `rebound_${sym}_${dateStr}`,
          symbol: sym,
          market: m,
          name: s.name ? s.name.replace(/股份有限公司|企業股份有限公司|科技股份有限公司/g, '') : sym,
          price: s.price,
          change_pct: finite(s.intraday_ret) ? s.intraday_ret * 100 : (finite(s.change_pct) ? s.change_pct : 0),
          reason: reasonText,
          score: finite(reb.score) ? reb.score : 80,
          confirmation: 'pullback',
          generated_at: `${dateStr}T13:30:00+08:00`,
          quote_at: `${dateStr}T13:30:00+08:00`
        });
      }
    }
    items.sort((a, b) => (b.score || 0) - (a.score || 0));
    if (items.length > 0) {
      await write('summaryReboundCache', { at: now, items });
      return items;
    }
    return cache?.items || [];
  } catch {
    return cache?.items || [];
  }
}

async function feeds(now, forced = false) {
  const cache = await read('feedCache', null);
  if (cache && now >= cache.at && now - cache.at < TTL) return cache;
  const at = await read('feedAttempt', 0);
  if (at && now >= at && now - at < TTL) return { ...(cache || { quotes: {}, live: {} }), error: '行情暫時無法更新' };
  if (!forced && !marketOpen(now)) return cache || { quotes: {}, live: {} };
  await write('feedAttempt', now);
  try {
    const [quotes, live, taiex] = VM_MODE ?
      [{ '2330': { name: '台積電（VM 示例）', price: 1000, change_pct: 1.25, updated_at: new Date(now).toISOString() } }, {}, { price: 22800.00, change: 120.50, change_pct: 0.53, time: '13:30:00' }] :
      await Promise.all([
        json(`${FIREBASE_ROOT}/public_feed.json`),
        json(`${FIREBASE_ROOT}/intraday_live.json`),
        fetchTaiexIndex().catch(() => null)
      ]);
    if (!plain(quotes) || !plain(live)) throw new Error('行情格式不符');
    let summaryRebound = cache?.summaryRebound || [];
    try {
      summaryRebound = await fetchSummaryRebound(now);
    } catch (_) {}
    if (!VM_MODE) {
      const st = await state().catch(() => null);
      if (st?.stocks?.length) {
        const missing = st.stocks.filter(s => !quotes[s.symbol] || !finite(calcChangePct(quotes[s.symbol])));
        if (missing.length) {
          try {
            const closingMap = await fetchStockClosingQuotes(missing);
            for (const [sym, item] of Object.entries(closingMap)) {
              if (!quotes[sym]) quotes[sym] = item;
              else {
                if (!finite(calcChangePct(quotes[sym]))) {
                  quotes[sym].change_pct = item.change_pct;
                  quotes[sym].change = item.change;
                  quotes[sym].previous_close = item.previous_close;
                }
                if (!quotes[sym].high && item.high) quotes[sym].high = item.high;
                if (!quotes[sym].low && item.low) quotes[sym].low = item.low;
                if (!quotes[sym].open && item.open) quotes[sym].open = item.open;
                if (!quotes[sym].time && item.time) quotes[sym].time = item.time;
              }
            }
          } catch (_) {}
        }
      }
      if (st?.stocks?.length) {
        try {
          const sparkMap = await fetchStockSparklines(st.stocks);
          for (const [sym, points] of Object.entries(sparkMap)) {
            if (quotes[sym]) quotes[sym].spark = points;
          }
        } catch (_) {}
      }
    }
    const value = { at: now, quotes, live, taiex: taiex || cache?.taiex || null, summaryRebound };
    await write('feedCache', value);
    safe(updateMarketStatusIcon(value, now));
    return value;
  } catch { return { ...(cache || { quotes: {}, live: {} }), error: '行情暫時無法更新；舊報價僅供檢視' }; }
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
      reason: Array.isArray(p.entry_reasons) ? (p.entry_reasons.join('；').slice(0, 200) || '當沖進場') : (p.reason || '當沖進場') }, 'daytrade', now, true);
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
      reason: t.exit_reason || '平倉出場'
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
    const isRebound = s.strategy === 'rebound';
    const defaultTitle = `${test ? '【VM 測試】' : ''}${isDaytrade ? (isExit ? '【當沖出場】' : '【當沖多方訊號】') : '🛡️【觸底反彈訊號】'}${s.symbol} ${s.name}`;
    const telegramTitle = `${test ? '【VM 測試】' : ''}${isExit ? '✅【當沖出場】' : (isRebound ? '🛡️【觸底反彈訊號】' : '🚀【當沖進場訊號】')}${s.symbol} ${s.name}`;
    const title = s.telegramText ? telegramTitle : (s.customTitle || defaultTitle);

    const changePctVal = calcChangePct(s);
    const defaultMsg = `現價 ${s.price.toFixed(2)} 元｜${finite(changePctVal) ? `${changePctVal >= 0 ? '+' : ''}${changePctVal.toFixed(2)}%` : '結盤 0.00%'}\n${s.reason}`;
    const message = (s.telegramText || defaultMsg) + (test ? '\n示例數字，非交易訊號、不計額度。' : '');

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
async function snapshot(refresh = false) {
  const now = Date.now(), st = await state();
  let c = null, configError = '';
  try { c = await remoteConfig(now); } catch (e) { configError = e.message; }
  const data = refresh ? await feeds(now, true) : await read('feedCache', { quotes: {}, live: {} });
  const day = ledger(await read('ledger', null), now);
  safe(updateMarketStatusIcon(data, now));

  const remoteBounce = (c?.bounce_strategy_signals || []).map(x => signal(x, 'rebound', now, false, true)).filter(Boolean);
  const summaryBounce = (data.summaryRebound || []).map(x => signal(x, 'rebound', now, false, true)).filter(Boolean);
  const bounceMap = new Map();
  for (const b of [...remoteBounce, ...summaryBounce]) {
    if (!bounceMap.has(b.symbol)) {
      const q = data.quotes?.[b.symbol];
      const livePrice = (q && finite(q.price) && q.price > 0) ? q.price : b.price;
      const liveChangePct = calcChangePct(q) ?? b.change_pct;
      bounceMap.set(b.symbol, {
        ...b,
        price: livePrice,
        change_pct: liveChangePct
      });
    }
  }
  const allBounce = [...bounceMap.values()];

  return { stocks: st.stocks, settings: st.settings, vip: isVIP(c, st.vipHash), vm: VM_MODE,
    quotes: data.quotes, live: data.live || {}, taiex: data.taiex || null, updatedAt: data.at || null, error: configError || data.error || '',
    marketOpen: marketOpen(now, c?.market_holidays), used: day.count,
    bounce: allBounce,
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
  safe(updateMarketStatusIcon(data, now));
  const allDaytrade = st.settings.allDaytradeAlerts !== false;
  const allRebound = st.settings.allReboundAlerts !== false;
  const signals = [
    ...(st.settings.daytrade ? liveSignals(data, st.stocks, now, allDaytrade) : []),
    ...(st.settings.daytrade ? liveExitSignals(data, st.stocks, now, allDaytrade) : []),
    ...(st.settings.daytrade ? c.daytrade_strategy_signals.map(x => signal(x, 'daytrade', now)) : []),
    ...(st.settings.rebound ? c.bounce_strategy_signals.map(x => {
      const sig = signal(x, 'rebound', now);
      return sig ? { ...sig, telegramText: formatTelegramRebound(sig) } : null;
    }) : [])
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
    } else if (s.strategy === 'rebound' && allRebound) {
      // 全市場反彈連動模式
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
export async function handle(message) {
  if (!plain(message)) throw new Error('訊息格式不正確');
  const st = await state();
  switch (message.type) {
    case 'SNAPSHOT': return snapshot(message.refresh === true);
    case 'ADD': {
      const row = stock(message.stock);
      const existing = st.stocks.find(x => x.symbol === row.symbol);
      if (existing) {
        const combined = [...new Set([...existing.groups, ...row.groups])];
        if (combined.length === existing.groups.length) {
          throw new Error('此股票已在自選清單');
        }
        existing.groups = combined;
      } else {
        st.stocks = watchlist([...st.stocks, row]);
      }
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
      const allowed = [...GROUPS, 'allDaytradeAlerts', 'allReboundAlerts', 'filterMode', 'minPrice', 'maxPrice', 'minChangePct', 'stealthMode', 'pageSize', 'cardDensity', 'fontSize', 'windowHeight', 'showSparkline', 'preferredBroker'];
      if (!allowed.includes(message.strategy)) throw new Error('開關格式不正確');
      st.settings[message.strategy] = message.enabled !== undefined ? message.enabled : message.value;
      break;
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
      if (message.action === 'SELL') {
        const fakeExit = {
          symbol: '2330', name: '台積電', market: 'TW', price: 1025, exit_price: 1025, entry_price: 1000,
          pnl_pct: 2.5, mfe_pct: 3.0, mae_pct: -0.5, duration_seconds: 1800, exit_reason: '12:55當沖強制出場',
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
      if (message.strategy === 'rebound') {
        const fakeRebound = {
          symbol: '2330', name: '台積電', market: 'TW', price: 1000, change_pct: 1.25,
          strategy: 'rebound', reason: '示例：支撐區反彈、量能回升'
        };
        fakeRebound.telegramText = formatTelegramRebound(fakeRebound);
        await notify(fakeRebound, { test: true });
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
  await write('state', st);
  return snapshot();
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
      let lastValidPrice = previousClose || regularPrice || 0;

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

        bars.push({
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
      `https://query1.finance.yahoo.com/v8/finance/chart/${ySym}?interval=1d&range=6mo`,
      `https://query2.finance.yahoo.com/v8/finance/chart/${ySym}?interval=1d&range=6mo`
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

        const bars = [];
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
      const closes = item.response?.[0]?.indicators?.quote?.[0]?.close;
      if (Array.isArray(closes)) {
        const validPoints = closes.filter(v => typeof v === 'number' && Number.isFinite(v));
        if (validPoints.length > 0) {
          map[rawSym] = validPoints;
        }
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
  serial(() => handle(message)).then(value => respond({ ok: true, value }), e => respond({ ok: false, error: e.message || '操作失敗' }));
  return true;
});
chrome.alarms.onAlarm.addListener(a => { if (a.name === ALARM) safe(serial(poll)); });
chrome.runtime.onInstalled.addListener(() => {
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
