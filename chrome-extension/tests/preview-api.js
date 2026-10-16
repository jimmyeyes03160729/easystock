// UI-only fixture for the 2.0 popup. No native Chrome API, no network, no real notifications.
// Query: ?theme=dark|light &color=mono|redgreen &account=blocked|signedout|signedin
const q = new URLSearchParams(location.search);
const iso = ms => new Date(ms).toISOString();
// Pin the fixture clock to 11:00 Taipei today so sparkline points fall inside the 09:00–13:30 session.
const today = new Date(Date.now() + 8 * 3600000).toISOString().slice(0, 10);
const now = Math.min(Date.now(), Date.parse(`${today}T11:00:00+08:00`));
const fixture = {
  rev: 1,
  stocks: [
    { symbol: '2330', name: '台積電', market: 'TW', groups: ['watchlist'] },
    { symbol: '8299', name: '群聯', market: 'TWO', groups: ['watchlist'] },
    { symbol: '1102', name: '亞泥', market: 'TW', groups: ['watchlist'] },
    { symbol: '00878', name: '國泰永續高股息', market: 'TW', groups: ['watchlist'] }
  ],
  quotes: {
    '2330': { price: 2420, previous_close: 2440, change: -20, change_pct: -0.82, high: 2450, low: 2410, quote_at: iso(now - 60000), source: 'YAHOO_TW',
      spark: Array.from({ length: 12 }, (_, i) => ({ close: 2440 - i * 2 + (i % 3) * 3, timestamp: (now - (12 - i) * 900000) / 1000 })) },
    '8299': { price: 512, previous_close: 500, change: 12, change_pct: 2.4, high: 515, low: 498, quote_at: iso(now - 60000),
      spark: Array.from({ length: 12 }, (_, i) => ({ close: 500 + i, timestamp: (now - (12 - i) * 900000) / 1000 })) },
    '1102': { name: '1102', price: 37.4, updated_at: iso(now - 86400000) }
  },
  quoteAttempts: { '00878': { at: now, ok: false } },
  pendingQuotes: [],
  taiex: { price: 47111.26, change: 141.39, change_pct: 0.3, otc_price: 400.26, otc_change: 3.36, otc_change_pct: 0.85, quote_at: iso(now - 20000), source: 'TWSE_MIS' },
  taiexQuality: { status: 'LIVE', source: 'TWSE_MIS', age_seconds: 20, fresh: true },
  settings: { daytrade: true, allDaytradeAlerts: true, filterMode: 'all', pageSize: 5, darkMode: q.get('theme') === 'dark', colorMode: q.get('color') === 'mono' ? 'mono' : 'redgreen', fontSize: 'standard', windowHeight: 500, showSparkline: true, preferredBroker: 'observe' },
  holidays: [], used: 0, vip: false, vm: false, marketOpen: true, updatedAt: now, paymentURL: '', error: '', live: {}, bounce: [],
  account: q.get('account') === 'signedin'
    ? { configured: true, status: 'READY', missing: [], signedIn: true, email: 'demo.user@example.test', uidShort: 'aB3dE9…', sync: { status: 'synced', lastSyncAt: iso(now - 120000), lastError: '', pending: false } }
    : (q.get('account') === 'signedout'
      ? { configured: true, status: 'READY', missing: [], signedIn: false, sync: { status: 'signed_out' } }
      : { configured: false, status: 'BLOCKED_BY_OAUTH_CONFIGURATION', missing: ['oauth2.client_id', 'firebase_api_key'], signedIn: false, sync: { status: 'signed_out' } })
};
window.chrome = {
  storage: { local: { get: async () => ({ state: { version: 2, stocks: fixture.stocks, settings: fixture.settings } }) } },
  runtime: { onMessage: { addListener: () => {} }, sendMessage: async m => {
    if (m.type === 'TEST') return { ok: true, value: { sent: true } };
    if (m.type === 'ADD') { if (!fixture.stocks.some(s => s.symbol === m.stock.symbol)) { fixture.stocks.push(m.stock); fixture.rev += 1; fixture.pendingQuotes = [m.stock.symbol]; } }
    if (m.type === 'DELETE') { fixture.stocks = fixture.stocks.filter(s => s.symbol !== m.symbol); fixture.rev += 1; }
    if (m.type === 'SETTINGS') { fixture.settings[m.strategy] = m.enabled ?? m.value; fixture.rev += 1; }
    if (m.type === 'IMPORT') fixture.stocks = m.stocks;
    if (m.type === 'AUTH_SIGN_IN') return { ok: false, error: 'Google 登入待設定（BLOCKED_BY_OAUTH_CONFIGURATION）' };
    return { ok: true, value: structuredClone(fixture) };
  } },
  tabs: { create: async ({ url }) => window.open(url, '_blank', 'noopener') }
};
