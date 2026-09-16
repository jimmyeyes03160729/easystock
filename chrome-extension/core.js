export const TTL = 5 * 60 * 1000;
export const COOLDOWN = 30 * 60 * 1000;
export const SYMBOL = /^\d{4,6}[A-Z]?$/;
export const GROUPS = ['daytrade', 'rebound'];
export const plain = v => !!v && typeof v === 'object' && !Array.isArray(v);
export const finite = v => typeof v === 'number' && Number.isFinite(v);
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
export function defaultState() {
  return { version: 1, stocks: [stock({ symbol: '2330', name: '台積電', market: 'TW', groups: ['daytrade'] })],
    settings: { daytrade: true, rebound: true }, vipHash: '' };
}
