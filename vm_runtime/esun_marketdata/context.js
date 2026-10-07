'use strict';
// Price-only diagnostics, never an ENTRY/EXIT or risk veto. No historical backfill.
const mappings = require('./indices.json').indices;
const sectorKeys = Object.keys(mappings).filter(k => !['taiex', 'otc'].includes(k));
const tpe = ms => new Date(ms + 28800000).toISOString().replace('Z', '+08:00');
const finite = n => n !== null && n !== undefined && n !== '' && Number.isFinite(Number(n)) ? Number(n) : null;
function fresh(at, now) {
  return Number.isFinite(at) && at <= now && now - at <= 90000 && tpe(at).slice(0, 10) === tpe(now).slice(0, 10);
}
function exchangeTime(n) {
  n = finite(n);
  return n === null ? NaN : n / (n >= 1e17 ? 1e6 : n >= 1e14 ? 1e3 : n >= 1e11 ? 1 : .001);
}
class MarketContext {
  constructor() { this.history = {}; this.previous = null; }
  observe(key, quote) {
    const at = Date.parse(quote.quote_at), rows = this.history[key] || [];
    if (!Number.isFinite(at) || (rows.length && at <= rows.at(-1).at)) return;
    this.history[key] = [...rows.filter(r => at - r.at <= 1200000 && tpe(at).slice(0,10) === tpe(r.at).slice(0,10)), {at, price: quote.price}];
  }
  windowReturn(key, quote, minutes) {
    const target = Date.parse(quote.quote_at) - minutes * 60000;
    const row = (this.history[key] || []).filter(r => r.at <= target && target - r.at <= 90000).at(-1);
    return row ? (quote.price / row.price - 1) * 100 : null;
  }
  build(quotes, snapshots, now, open) {
    const usable = q => open && q?.source === 'esun' && fresh(Date.parse(q.quote_at), now) && finite(q.change_pct) !== null;
    const rows = sectorKeys.map(key => {
      const q = quotes[key], valid = usable(q);
      const day = valid ? q.change_pct : null;
      const relative = base => valid && usable(quotes[base]) ? day - quotes[base].change_pct : null;
      return {key, source: 'esun', symbol: mappings[key].symbol, name: mappings[key].name,
        quote_at: q?.quote_at || null, received_at: q?.received_at || null,
        age_seconds: q ? Math.max(0, (now - Date.parse(q.quote_at)) / 1000) : null,
        fresh: !!valid, valid: !!valid, return_day: day,
        return_1m: valid ? this.windowReturn(key, q, 1) : null,
        return_5m: valid ? this.windowReturn(key, q, 5) : null,
        return_15m: valid ? this.windowReturn(key, q, 15) : null,
        relative_to_taiex: relative('taiex'), relative_to_otc: relative('otc'),
        strength_score: relative('taiex'), rank: null, rank_transition: null};
    });
    const ranked = rows.filter(r => r.strength_score !== null).sort((a,b) => b.strength_score - a.strength_score || a.symbol.localeCompare(b.symbol));
    ranked.forEach((r,i) => {
      r.rank = i + 1;
      const previous = this.previous;
      if (previous && fresh(previous.at, now) && previous.ranks[r.key]) r.rank_transition = previous.ranks[r.key] - r.rank;
    });
    const complete = ranked.length === sectorKeys.length && usable(quotes.otc);
    const status = ranked.length ? (complete ? 'OK' : 'DEGRADED') : 'UNKNOWN';
    // Do not let repeated five-second publication erase the preceding rank transition.
    const signature = ranked.map(r => r.quote_at).join('|');
    if (complete && signature !== this.previous?.signature) this.previous = {at: now, signature, ranks: Object.fromEntries(ranked.map(r => [r.key,r.rank]))};
    if (!open) this.previous = null;
    return {breadth: breadth(snapshots, now, open), sectors: {status, score_definition: 'day return minus TAIEX, percentage points', rows},
      rotation: {source: 'esun', type: 'sector_rotation_proxy', basis: 'price_only', status,
        rotation_state: complete ? (ranked[0].strength_score > 0 ? ranked[0].key.toUpperCase() + '_LEADING' : 'MIXED') : 'UNKNOWN',
        leaders: complete ? ranked.slice(0,2).map(r => r.key) : [], laggards: complete ? ranked.slice(-2).map(r => r.key) : [],
        quote_at: complete ? ranked.map(r => r.quote_at).sort()[0] : null, received_at: tpe(now),
        age_seconds: complete ? Math.max(...ranked.map(r => r.age_seconds)) : null, fresh: complete, valid: complete}};
  }
}
function breadth(snapshots, now, open) {
  const result = {source: 'esun', symbol: 'TSE+OTC', scope: 'snapshot EQUITY tickers (may include ETFs); not certified exchange universe',
    api_status: Object.fromEntries(['TSE','OTC'].map(m => [m, snapshots[m]?.market === m && Array.isArray(snapshots[m]?.data) ? 'available' : 'unavailable'])),
    api_returned_count: Object.fromEntries(['TSE','OTC'].map(m => [m, Array.isArray(snapshots[m]?.data) ? snapshots[m].data.length : null])),
    status: 'UNKNOWN', quote_at: null, received_at: tpe(now), age_seconds: null, fresh: false, valid: false,
    markets: [], returned_count: 0, valid_count: 0, coverage: null,
    advancers: null, decliners: null, unchanged: null, advance_decline_ratio: null, advance_pct: null, decline_pct: null, breadth_score: null};
  if (!open) return result;
  let up = 0, down = 0, unchanged = 0, oldest = now;
  for (const market of ['TSE','OTC']) {
    const snapshot = snapshots[market];
    if (!snapshot || snapshot.market !== market || snapshot.date !== tpe(now).slice(0,10) || !Array.isArray(snapshot.data) || snapshot.data.length === 0) continue;
    result.markets.push(market); const seen = new Set();
    for (const row of snapshot.data) {
      result.returned_count++;
      const at = exchangeTime(row.lastUpdated), change = finite(row.change);
      if (row.type !== 'EQUITY' || !/^\d{4,6}[A-Z]?$/.test(row.symbol) || seen.has(row.symbol) || !fresh(at,now) || change === null || !(finite(row.closePrice) > 0)) continue;
      seen.add(row.symbol); oldest = Math.min(oldest, at); result.valid_count++;
      if (change > 0) up++; else if (change < 0) down++; else unchanged++;
    }
  }
  const n = result.valid_count;
  if (!n) return result;
  return {...result, status: result.markets.length === 2 && n === result.returned_count ? 'OK' : 'DEGRADED',
    quote_at: tpe(oldest), age_seconds: (now-oldest)/1000, fresh: true, valid: true,
    coverage: n/result.returned_count, advancers: up, decliners: down, unchanged,
    advance_decline_ratio: down ? up/down : null, advance_pct: up/n*100, decline_pct: down/n*100, breadth_score: (up-down)/n};
}
module.exports = {MarketContext, breadth};
