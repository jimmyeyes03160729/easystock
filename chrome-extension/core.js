export const TTL = 5 * 60 * 1000;
export const COOLDOWN = 30 * 60 * 1000;
export const SYMBOL = /^\d{4,6}[A-Z]?$/;
export const GROUPS = ['daytrade', 'rebound', 'watchlist'];
export const plain = v => !!v && typeof v === 'object' && !Array.isArray(v);
export const finite = v => typeof v === 'number' && Number.isFinite(v);

export const BUILTIN_STOCKS = [
  { symbol: '2330', name: '台積電', market: 'TW' },
  { symbol: '2317', name: '鴻海', market: 'TW' },
  { symbol: '2454', name: '聯發科', market: 'TW' },
  { symbol: '2308', name: '台達電', market: 'TW' },
  { symbol: '2382', name: '廣達', market: 'TW' },
  { symbol: '2303', name: '聯電', market: 'TW' },
  { symbol: '2603', name: '長榮', market: 'TW' },
  { symbol: '2609', name: '陽明', market: 'TW' },
  { symbol: '2615', name: '萬海', market: 'TW' },
  { symbol: '3008', name: '大立光', market: 'TW' },
  { symbol: '2412', name: '中華電', market: 'TW' },
  { symbol: '2881', name: '富邦金', market: 'TW' },
  { symbol: '2882', name: '國泰金', market: 'TW' },
  { symbol: '2891', name: '中信金', market: 'TW' },
  { symbol: '2886', name: '兆豐金', market: 'TW' },
  { symbol: '2884', name: '玉山金', market: 'TW' },
  { symbol: '3231', name: '緯創', market: 'TW' },
  { symbol: '2376', name: '技嘉', market: 'TW' },
  { symbol: '2357', name: '華碩', market: 'TW' },
  { symbol: '2356', name: '英業達', market: 'TW' },
  { symbol: '6669', name: '緯穎', market: 'TW' },
  { symbol: '3661', name: '世芯-KY', market: 'TW' },
  { symbol: '3443', name: '創意', market: 'TW' },
  { symbol: '3035', name: '智原', market: 'TW' },
  { symbol: '5274', name: '信驊', market: 'TWO' },
  { symbol: '3529', name: '力旺', market: 'TWO' },
  { symbol: '6488', name: '環球晶', market: 'TWO' },
  { symbol: '8299', name: '群聯', market: 'TWO' },
  { symbol: '1519', name: '華城', market: 'TW' },
  { symbol: '1513', name: '中興電', market: 'TW' },
  { symbol: '1503', name: '士電', market: 'TW' },
  { symbol: '1514', name: '亞力', market: 'TW' },
  { symbol: '2345', name: '智邦', market: 'TW' },
  { symbol: '3037', name: '欣興', market: 'TW' },
  { symbol: '2368', name: '金像電', market: 'TW' },
  { symbol: '6274', name: '台燿', market: 'TWO' },
  { symbol: '2383', name: '台光電', market: 'TW' },
  { symbol: '2002', name: '中鋼', market: 'TW' },
  { symbol: '1301', name: '台塑', market: 'TW' },
  { symbol: '1303', name: '南亞', market: 'TW' },
  { symbol: '1326', name: '台化', market: 'TW' },
  { symbol: '2618', name: '長榮航', market: 'TW' },
  { symbol: '2610', name: '華航', market: 'TW' },
  { symbol: '3293', name: '鈊象', market: 'TWO' },
  { symbol: '2327', name: '國巨', market: 'TW' },
  { symbol: '3711', name: '日月光投控', market: 'TW' },
  { symbol: '2409', name: '友達', market: 'TW' },
  { symbol: '3481', name: '群創', market: 'TW' },
  { symbol: '2353', name: '宏碁', market: 'TW' },
  { symbol: '2324', name: '仁寶', market: 'TW' },
  { symbol: '4938', name: '和碩', market: 'TW' },
  { symbol: '8069', name: '元太', market: 'TWO' },
  { symbol: '3017', name: '奇鋐', market: 'TW' },
  { symbol: '3324', name: '雙鴻', market: 'TWO' },
  { symbol: '3653', name: '健策', market: 'TW' },
  { symbol: '2059', name: '川湖', market: 'TW' },
  { symbol: '4763', name: '材料-KY', market: 'TW' },
  { symbol: '6446', name: '藥華藥', market: 'TWO' },
  { symbol: '6472', name: '保瑞', market: 'TW' },
  { symbol: '1795', name: '美時', market: 'TW' },
  { symbol: '3131', name: '弘塑', market: 'TWO' },
  { symbol: '3583', name: '辛耘', market: 'TW' },
  { symbol: '5483', name: '中美晶', market: 'TWO' },
  { symbol: '3105', name: '穩懋', market: 'TWO' },
  { symbol: '5347', name: '世界', market: 'TWO' },
  { symbol: '2379', name: '瑞昱', market: 'TW' },
  { symbol: '2344', name: '華邦電', market: 'TW' },
  { symbol: '2408', name: '南亞科', market: 'TW' },
  { symbol: '2337', name: '旺宏', market: 'TW' },
  { symbol: '1605', name: '華新', market: 'TW' },
  { symbol: '6869', name: '雲豹能源', market: 'TW' },
  { symbol: '6806', name: '森崴能源', market: 'TW' },
  { symbol: '9958', name: '世紀鋼', market: 'TW' },
  { symbol: '2912', name: '統一超', market: 'TW' }
];

const DYNAMIC_STOCKS = new Map();

export function registerStocks(stocks) {
  if (Array.isArray(stocks)) {
    for (const s of stocks) {
      if (s?.symbol && s?.market && s?.name) {
        const existing = DYNAMIC_STOCKS.get(s.symbol);
        if (existing?.market === 'TW' && s.market === 'TWO') continue;
        DYNAMIC_STOCKS.set(s.symbol, { symbol: s.symbol, market: s.market, name: s.name });
      }
    }
  }
}

export function calcChangePct(q) {
  if (!q) return null;
  if (finite(q.change_pct)) return q.change_pct;
  if (finite(q.change) && finite(q.price) && (q.price - q.change) > 0) {
    return (q.change / (q.price - q.change)) * 100;
  }
  if (finite(q.price) && finite(q.previous_close) && q.previous_close > 0) {
    return ((q.price - q.previous_close) / q.previous_close) * 100;
  }
  if (finite(q.last_close_change_pct)) return q.last_close_change_pct;
  return null;
}

export function searchStocks(query, extraQuotes = {}) {
  const q = String(query || '').trim().toUpperCase();
  const pool = new Map();
  for (const s of BUILTIN_STOCKS) pool.set(s.symbol, { ...s });
  for (const [sym, s] of DYNAMIC_STOCKS.entries()) {
    const existing = pool.get(sym);
    if (existing?.market === 'TW' && s.market === 'TWO') continue;
    pool.set(sym, { ...s });
  }
  if (plain(extraQuotes)) {
    for (const [sym, item] of Object.entries(extraQuotes)) {
      if (!pool.has(sym)) {
        const m = (sym.length === 4 && (sym.startsWith('5') || sym.startsWith('6') || sym.startsWith('8'))) ? 'TWO' : 'TW';
        pool.set(sym, { symbol: sym, name: item?.name || sym, market: m });
      } else if (item?.name && pool.get(sym).name === sym) {
        pool.get(sym).name = item.name;
      }
    }
  }
  const rawAll = [...pool.values()];
  // 排除 5 碼可轉債 (如 68621)；若存在上市 (TW)，不保留上櫃 (TWO)
  const all = rawAll.filter(s => {
    if (s.symbol.length === 5 && !s.symbol.startsWith('00') && /^\d+$/.test(s.symbol)) return false;
    if (s.market === 'TWO') {
      const base4 = s.symbol.slice(0, 4);
      if (rawAll.some(other => other.market === 'TW' && (other.symbol === s.symbol || other.symbol === base4))) return false;
    }
    return true;
  });

  if (!q) return all.slice(0, 8);

  const exactSym = all.filter(s => s.symbol === q);
  const exactName = all.filter(s => s.name.toUpperCase() === q && !exactSym.includes(s));
  const startSym = all.filter(s => s.symbol.startsWith(q) && !exactSym.includes(s));
  const startName = all.filter(s => s.name.toUpperCase().startsWith(q) && !exactName.includes(s));
  const hasName = all.filter(s => s.name.toUpperCase().includes(q) && !exactName.includes(s) && !startName.includes(s));
  const hasSym = all.filter(s => s.symbol.includes(q) && !exactSym.includes(s) && !startSym.includes(s));

  const results = [...exactSym, ...exactName, ...startName, ...startSym, ...hasName, ...hasSym];

  const match = /^(\d{4,6}[A-Z]?)(?:\.(TW|TWO))?$/i.exec(q);
  if (match) {
    const rawSym = match[1];
    const m = (match[2] || (rawSym.length === 4 && (rawSym.startsWith('5') || rawSym.startsWith('6') || rawSym.startsWith('8')) ? 'TWO' : 'TW')).toUpperCase();
    if (!results.some(x => x.symbol === rawSym)) {
      results.unshift({ symbol: rawSym, name: rawSym, market: m });
    }
  }
  return results.slice(0, 15);
}

export async function searchOnlineStocks(query) {
  const q = String(query || '').trim();
  if (!q) return [];
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 4000);
  try {
    const url = `https://tw.stock.yahoo.com/_td-stock/api/resource/AutocompleteService;query=${encodeURIComponent(q)}`;
    const res = await fetch(url, { signal: controller.signal, cache: 'no-store' });
    if (!res.ok) return [];
    const json = await res.json();
    const rawList = json?.ResultSet?.Result;
    if (!Array.isArray(rawList)) return [];

    const results = [];
    const seen = new Set();
    for (const item of rawList) {
      if (!item?.symbol) continue;
      const m = /^(\d{4,6}[A-Z]?)\.(TW|TWO)$/i.exec(item.symbol);
      if (!m) continue;
      const sym = m[1].toUpperCase();
      const market = m[2].toUpperCase();

      // 排除 5 碼純數字之可轉債 (如 68621 三集瑞一KY)，僅保留 4 碼股票、特別股 (如 2881A) 與 00 開頭之 ETF (如 0050, 00919)
      if (sym.length === 5 && !sym.startsWith('00') && /^\d+$/.test(sym)) continue;
      if (sym.length > 5 && !sym.startsWith('00')) continue;
      if (item.typeDisp === '認購' || item.typeDisp === '認售' || item.typeDisp === '債券') continue;

      const base4 = sym.slice(0, 4);
      // 「有上市的就不要多個上櫃」：同一標的若已有上市 (TW)，不保留上櫃 (TWO)
      if (market === 'TWO') {
        const hasTw = results.some(r => r.market === 'TW' && (r.symbol === sym || r.symbol === base4));
        if (hasTw) continue;
      } else if (market === 'TW') {
        const twoIdx = results.findIndex(r => r.market === 'TWO' && (r.symbol === sym || r.symbol.startsWith(base4)));
        if (twoIdx !== -1) results.splice(twoIdx, 1);
      }

      if (seen.has(sym)) continue;
      seen.add(sym);
      results.push({
        symbol: sym,
        market,
        name: String(item.name || sym).trim()
      });
    }
    if (results.length > 0) registerStocks(results);
    return results.slice(0, 15);
  } catch {
    return [];
  } finally {
    clearTimeout(timer);
  }
}

export async function fetchStockClosingQuotes(symbols) {
  if (!Array.isArray(symbols) || !symbols.length) return {};
  const queryList = symbols.map(s => {
    if (typeof s === 'string') return s.includes('.') ? s : `${s}.TW`;
    return `${s.symbol}.${s.market || 'TW'}`;
  }).slice(0, 40);

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 4000);
  try {
    const url = `https://tw.stock.yahoo.com/_td-stock/api/resource/StockServices.stockList;symbols=${queryList.join(',')}`;
    const res = await fetch(url, { signal: controller.signal, cache: 'no-store' });
    if (!res.ok) return {};
    const list = await res.json();
    if (!Array.isArray(list)) return {};
    const map = {};
    for (const item of list) {
      if (!item?.symbol) continue;
      const sym = item.symbol.split('.')[0].toUpperCase();
      const price = finite(item.price?.sort) ? item.price.sort : (finite(item.regularMarketPreviousClose?.sort) ? item.regularMarketPreviousClose.sort : null);
      const prev = finite(item.regularMarketPreviousClose?.sort) ? item.regularMarketPreviousClose.sort : null;
      let change = finite(item.change?.sort) ? item.change.sort : (price !== null && prev !== null ? price - prev : 0);
      let change_pct = null;
      if (typeof item.changePercent === 'string') {
        const parsed = parseFloat(item.changePercent.replace('%', ''));
        if (Number.isFinite(parsed)) change_pct = parsed;
      }
      const high = finite(item.regularMarketDayHigh?.sort) ? item.regularMarketDayHigh.sort : (price !== null ? price : 0);
      const low = finite(item.regularMarketDayLow?.sort) ? item.regularMarketDayLow.sort : (price !== null ? price : 0);
      const open = finite(item.regularMarketOpen?.sort) ? item.regularMarketOpen.sort : (prev !== null ? prev : price);
      let timeStr = '';
      if (item.regularMarketTime) {
        const tMatch = String(item.regularMarketTime).match(/(\d{2}:\d{2})/);
        timeStr = tMatch ? tMatch[1] : String(item.regularMarketTime).slice(0, 5);
      }
      map[sym] = {
        name: item.symbolName || sym,
        price: price || 0,
        change: change || 0,
        change_pct: change_pct !== null ? change_pct : 0,
        previous_close: prev,
        high: high || 0,
        low: low || 0,
        open: open || 0,
        time: timeStr || '13:30',
        volume: finite(item.volume) ? Math.round(item.volume / 1000) : 0,
        updated_at: item.regularMarketTime || new Date().toISOString()
      };
    }
    return map;
  } catch {
    return {};
  } finally {
    clearTimeout(timer);
  }
}
export function taipei(now = Date.now()) {
  const d = new Date(now + 8 * 3600000);
  return { date: d.toISOString().slice(0, 10), weekday: d.getUTCDay(), minute: d.getUTCHours() * 60 + d.getUTCMinutes() };
}
export function marketOpen(now, holidays = []) {
  const t = taipei(now);
  return t.weekday > 0 && t.weekday < 6 && t.minute >= 540 && t.minute < 810 && !holidays.includes(t.date);
}
export function fresh(stamp, now, age = TTL) {
  if (typeof stamp !== 'string' || !/(Z|[+-]\d{2}:\d{2})$/.test(stamp)) return false;
  const n = Date.parse(stamp);
  return Number.isFinite(n) && n <= now && now - n <= age && taipei(n).date === taipei(now).date;
}
export function stock(raw) {
  if (!plain(raw) || typeof raw.symbol !== 'string' || !SYMBOL.test(raw.symbol)) throw new Error('股票代號格式不正確');
  if (!['TW', 'TWO'].includes(raw.market)) throw new Error('市場必須是 TW 或 TWO');
  if (typeof raw.name !== 'string' || !raw.name.trim() || raw.name.length > 60) throw new Error('股票名稱需為 1–60 字');
  if (!Array.isArray(raw.groups) || !raw.groups.length || raw.groups.some(x => !GROUPS.includes(x))) throw new Error('群組格式不正確');
  return { symbol: raw.symbol, market: raw.market, name: raw.name.trim(), groups: [...new Set(raw.groups)] };
}
export function watchlist(value) {
  if (!Array.isArray(value) || value.length > 100) throw new Error('最多可匯入 100 檔股票');
  const rows = value.map(stock);
  if (new Set(rows.map(x => x.symbol)).size !== rows.length) throw new Error('清單有重複代號');
  return rows;
}
export function config(value) {
  if (!plain(value) || value.schema_version !== 1 || typeof value.global_vip_switch !== 'boolean') throw new Error('遠端設定格式或版本不符');
  if (!Array.isArray(value.vip_keys_hash) || value.vip_keys_hash.length > 1000 || value.vip_keys_hash.some(x => typeof x !== 'string' || !/^[a-f0-9]{64}$/.test(x))) throw new Error('VIP 設定格式錯誤');
  if (!Array.isArray(value.bounce_strategy_signals) || value.bounce_strategy_signals.length > 100) throw new Error('反彈設定格式錯誤');
  const daytrade = value.daytrade_strategy_signals ?? [];
  if (!Array.isArray(daytrade) || daytrade.length > 100) throw new Error('當沖設定格式錯誤');
  const holidays = value.market_holidays ?? [];
  if (!Array.isArray(holidays) || holidays.length > 400 || holidays.some(x => typeof x !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(x))) throw new Error('休市設定格式錯誤');
  let payment = '';
  if (value.payment_gateway_url) {
    const url = new URL(value.payment_gateway_url);
    if (url.protocol !== 'https:' || url.username || url.password) throw new Error('付款連結僅允許 HTTPS');
    payment = url.href;
  }
  return { schema_version: 1, global_vip_switch: value.global_vip_switch, vip_keys_hash: value.vip_keys_hash,
    bounce_strategy_signals: value.bounce_strategy_signals, daytrade_strategy_signals: daytrade,
    payment_gateway_url: payment, market_holidays: holidays };
}
export async function sha256(text) {
  return [...new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text)))].map(v => v.toString(16).padStart(2, '0')).join('');
}
export function isVIP(c, hash) { return !!c && (c.global_vip_switch || (typeof hash === 'string' && c.vip_keys_hash.includes(hash))); }
export function signal(raw, strategy, now, allowMissingChange = false) {
  if (!plain(raw) || !GROUPS.includes(strategy) || typeof raw.symbol !== 'string' || !SYMBOL.test(raw.symbol) || !['TW', 'TWO'].includes(raw.market)) return null;
  if (typeof raw.id !== 'string' || !raw.id || raw.id.length > 120 || !finite(raw.price) || raw.price <= 0 || (!finite(raw.change_pct) && !(allowMissingChange && raw.change_pct === null))) return null;
  if (!fresh(raw.generated_at, now) || !fresh(raw.quote_at, now)) return null;
  if (typeof raw.name !== 'string' || !raw.name || raw.name.length > 60 || typeof raw.reason !== 'string' || !raw.reason || raw.reason.length > 200) return null;
  return { id: raw.id, symbol: raw.symbol, market: raw.market, name: raw.name, price: raw.price,
    change_pct: raw.change_pct, reason: raw.reason, generated_at: raw.generated_at, quote_at: raw.quote_at, strategy };
}
export const chartURL = s => `https://tw.stock.yahoo.com/quote/${s.symbol}.${s.market}`;
export function ledger(value, now) {
  const day = taipei(now).date;
  return value?.day === day ? value : { day, count: 0, last: {}, seen: {}, ignored: {}, routes: {} };
}
export function canNotify(s, state, now, vip) {
  return !state.ignored[s.symbol] && !state.seen[`${s.strategy}:${s.id}`] &&
    (!state.last[s.symbol] || now - state.last[s.symbol] >= COOLDOWN) && (vip || state.count < 3);
}
export function formatTelegramEntry(p) {
  const symbol = p.symbol || '';
  const name = p.name || symbol;
  const price = finite(p.entry_price) ? p.entry_price.toFixed(2) : (finite(p.price) ? p.price.toFixed(2) : '-');
  const score = p.entry_score ?? p.score ?? '-';
  const vwap = finite(p.entry_vwap) ? p.entry_vwap.toFixed(2) : (p.entry_vwap || '-');
  const stop = finite(p.stop_price) ? p.stop_price.toFixed(2) : '-';
  const tp = finite(p.take_profit_price) ? p.take_profit_price.toFixed(2) : '-';
  const reasons = Array.isArray(p.entry_reasons)
    ? p.entry_reasons.map(r => `✓ ${r}`).join('\n')
    : (p.reason ? `✓ ${p.reason}` : '');

  return [
    `🚀【當沖進場訊號】`,
    ``,
    `${symbol} ${name}`,
    `訊號價：${price}`,
    `分數：${score}`,
    `VWAP：${vwap}`,
    reasons ? `\n${reasons}` : '',
    `停損參考：${stop}`,
    `停利參考：${tp}`,
    ``,
    `狀態：OPEN`
  ].filter(line => line !== null && line !== undefined).join('\n');
}

export function formatTelegramExit(t) {
  const symbol = t.symbol || '';
  const name = t.name || symbol;
  const entryPrice = finite(t.entry_price) ? t.entry_price.toFixed(2) : '-';
  const exitPrice = finite(t.exit_price) ? t.exit_price.toFixed(2) : (finite(t.price) ? t.price.toFixed(2) : '-');
  const pnl = finite(t.pnl_pct) ? t.pnl_pct : 0;
  const sign = pnl >= 0 ? '+' : '';
  const mfe = finite(t.mfe_pct) ? `${t.mfe_pct >= 0 ? '+' : ''}${t.mfe_pct.toFixed(2)}%` : '-';
  const mae = finite(t.mae_pct) ? `${t.mae_pct >= 0 ? '+' : ''}${t.mae_pct.toFixed(2)}%` : '-';
  const durSec = t.duration_seconds;
  const durText = finite(durSec) ? `${Math.floor(durSec / 60)}分${durSec % 60}秒` : '-';
  const reason = t.exit_reason || '平倉出場';

  return [
    `✅【當沖出場】`,
    ``,
    `${symbol} ${name}`,
    ``,
    `訊號進場：${entryPrice}`,
    `訊號出場：${exitPrice}`,
    ``,
    `報酬：${sign}${pnl.toFixed(2)}%`,
    `最高浮盈：${mfe}`,
    `最大浮虧：${mae}`,
    `持有時間：${durText}`,
    ``,
    `出場原因：${reason}`
  ].join('\n');
}

export function formatTelegramRebound(s) {
  const symbol = s.symbol || '';
  const name = s.name || symbol;
  const price = finite(s.price) ? s.price.toFixed(2) : '-';
  const pct = finite(s.change_pct) ? `${s.change_pct >= 0 ? '+' : ''}${s.change_pct.toFixed(2)}%` : '-';
  const reason = s.reason || '技術面觸底反彈訊號，量能回升';

  return [
    `🛡️【觸底反彈訊號】`,
    ``,
    `${symbol} ${name}`,
    `現價：${price} 元｜漲跌：${pct}`,
    ``,
    `反彈觀察理由：`,
    `✓ ${reason}`,
    ``,
    `狀態：REBOUND (觀察中)`
  ].join('\n');
}

export function matchFilter(price, changePct, settings) {
  if (!settings || settings.filterMode === 'all') return true;
  if (finite(settings.minPrice) && (!finite(price) || price < settings.minPrice)) return false;
  if (finite(settings.maxPrice) && (!finite(price) || price > settings.maxPrice)) return false;
  if (finite(settings.minChangePct) && (!finite(changePct) || changePct < settings.minChangePct)) return false;
  return true;
}

export function defaultState() {
  return { version: 1, stocks: [stock({ symbol: '2330', name: '台積電', market: 'TW', groups: ['watchlist'] })],
    settings: {
      daytrade: true,
      rebound: true,
      allDaytradeAlerts: true,
      allReboundAlerts: true,
      filterMode: 'all',
      minPrice: null,
      maxPrice: null,
      minChangePct: null,
      pageSize: 5,
      cardDensity: 'compact',
      stealthMode: false,
      fontSize: 'standard',
      windowHeight: 600,
      showSparkline: true
    }, vipHash: '' };
}
