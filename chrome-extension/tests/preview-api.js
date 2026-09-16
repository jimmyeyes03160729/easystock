const fixture = {
  stocks: [{ symbol: '2330', name: '台積電', market: 'TW', groups: ['daytrade'] }, { symbol: '8299', name: '群聯', market: 'TWO', groups: ['rebound'] }],
  quotes: { '2330': { price: 1000, change_pct: 1.25, updated_at: new Date().toISOString() }, '8299': { price: 500, change_pct: -0.8, updated_at: new Date().toISOString() } },
  settings: { daytrade: true, rebound: true }, bounce: [], used: 0, vip: false, vm: true, marketOpen: false, updatedAt: Date.now(), paymentURL: '', error: ''
};
window.chrome = {
  runtime: { sendMessage: async m => {
    if (m.type === 'TEST') return { ok: true, value: { sent: true } };
    if (m.type === 'ADD') fixture.stocks.push(m.stock);
    if (m.type === 'DELETE') fixture.stocks = fixture.stocks.filter(s => s.symbol !== m.symbol);
    if (m.type === 'SETTINGS') fixture.settings[m.strategy] = m.enabled;
    if (m.type === 'GROUP') { const s = fixture.stocks.find(s => s.symbol === m.symbol); s.groups = m.enabled ? [...new Set([...s.groups, m.group])] : s.groups.filter(g => g !== m.group); }
    if (m.type === 'VIP') { if (m.key !== 'VIP888') return { ok: false, error: '測試碼不正確' }; fixture.vip = true; }
    if (m.type === 'IMPORT') fixture.stocks = m.stocks;
    return { ok: true, value: structuredClone(fixture) };
  } },
  tabs: { create: async ({ url }) => window.open(url, '_blank', 'noopener') }
};
