import { SYMBOL, GROUPS, finite, fresh, watchlist, chartURL } from './core.js';
import { icons } from './icons.js';

const $ = id => document.getElementById(id);
let view, group = 'all', pending = false;
const label = { daytrade: '當沖監控', rebound: '觸底反彈' };
function el(tag, text, className = '') {
  const node = document.createElement(tag); node.textContent = text; node.className = className; return node;
}
function status(text, error = false) {
  $('update-timestamp').textContent = text;
  $('update-timestamp').title = text;
  $('update-timestamp').classList.toggle('text-red-600', error);
  $('action-message').textContent = text;
  $('action-message').classList.toggle('text-red-600', error);
}
async function send(message) {
  const response = await chrome.runtime.sendMessage(message);
  if (!response?.ok) throw new Error(response?.error || '背景服務沒有回應，請重新載入擴充功能');
  return response.value;
}
async function act(message, success = '') {
  if (pending) return;
  pending = true; document.body.setAttribute('aria-busy', 'true');
  try {
    const result = await send(message);
    if (result.stocks) { view = result; render(); }
    if (success) status(success);
    return result;
  } catch (e) { status(e.message, true); }
  finally { pending = false; document.body.removeAttribute('aria-busy'); }
}
function render() {
  $('vip-status-badge').classList.toggle('hidden', !view.vip);
  $('market-status-dot').className = `h-2 w-2 rounded-full ${view.marketOpen && !view.error ? 'bg-emerald-500' : 'bg-slate-400'}`;
  $('market-status-dot').title = view.vm ? 'VM 隔離示例；不自動交易推播' : view.marketOpen ? '盤中排程；報價時間請看個股' : '休市／非盤中時段';
  for (const key of GROUPS) $(`toggle-${key}`).checked = view.settings[key];
  if ($('toggle-all-daytrade')) $('toggle-all-daytrade').checked = view.settings?.allDaytradeAlerts !== false;
  document.querySelectorAll('.tab-btn').forEach(b => {
    b.setAttribute('aria-selected', String(b.dataset.group === group));
    b.classList.toggle('tab-active', b.dataset.group === group);
  });
  const list = $('stock-list-container'); list.replaceChildren();
  const rows = view.stocks.filter(s => group === 'all' || s.groups.includes(group));
  if (!rows.length) list.append(el('p', '此群組尚無自選股票，請輸入代號新增。', 'text-xs text-slate-500 p-3'));
  for (const s of rows) {
    const q = view.quotes?.[s.symbol], validPrice = finite(q?.price) && q.price > 0;
    const card = el('article', '', 'stock-card border border-slate-200 rounded-lg p-3 bg-white space-y-2');
    const top = el('div', '', 'flex items-start justify-between gap-2');
    const title = el('div', '', 'min-w-0');
    title.append(el('h2', `${s.symbol} ${s.name}`, 'text-xs font-bold text-slate-900 break-words'));
    title.append(el('p', `${s.market === 'TWO' ? '上櫃' : '上市'} · ${s.groups.map(g => label[g]).join(' / ')}`, 'text-[10px] text-slate-400 mt-1'));
    const remove = el('button', '×', 'text-slate-400 hover:text-red-600 px-1');
    remove.title = `刪除 ${s.symbol}`; remove.setAttribute('aria-label', remove.title);
    remove.addEventListener('click', () => act({ type: 'DELETE', symbol: s.symbol }, '已刪除自選股票'));
    top.append(title, remove); card.append(top);
    const price = el('div', '', 'flex items-center justify-between');
    price.append(el('strong', validPrice ? `${q.price.toFixed(2)} 元` : '尚無報價', 'text-lg font-bold text-slate-900'));
    const pct = finite(q?.change_pct) ? `${q.change_pct >= 0 ? '+' : ''}${q.change_pct.toFixed(2)}%` : '漲跌幅未提供';
    price.append(el('span', pct, `text-[11px] ${finite(q?.change_pct) ? q.change_pct >= 0 ? 'text-red-600' : 'text-emerald-600' : 'text-slate-400'}`));
    card.append(price);
    const when = q?.updated_at && Number.isFinite(Date.parse(q.updated_at)) ? new Date(q.updated_at).toLocaleString('zh-TW', { timeZone: 'Asia/Taipei', hour12: false }) : '無資料';
    card.append(el('p', `${view.vm ? 'VM 示例 · ' : ''}${validPrice && fresh(q.updated_at, Date.now()) ? '報價' : '非即時'} ${when}`, 'text-[10px] text-slate-400'));
    const bottom = el('div', '', 'flex items-center justify-between gap-2');
    const groups = el('div', '', 'flex gap-2 text-[10px] text-slate-500');
    for (const g of GROUPS) {
      const item = el('label', '', 'flex items-center gap-1');
      const check = document.createElement('input'); check.type = 'checkbox'; check.checked = s.groups.includes(g);
      check.addEventListener('change', async () => {
        await act({ type: 'GROUP', symbol: s.symbol, group: g, enabled: check.checked }); render();
      });
      item.append(check, document.createTextNode(label[g])); groups.append(item);
    }
    const chart = el('a', '線圖 ↗', 'text-[11px] text-sky-700');
    chart.href = chartURL(s); chart.target = '_blank'; chart.rel = 'noopener noreferrer';
    bottom.append(groups, chart); card.append(bottom);
    const bounce = view.bounce.find(x => x.symbol === s.symbol && x.market === s.market);
    if (bounce) card.append(el('p', `反彈觀察：${bounce.reason}`, 'text-[10px] text-purple-700'));
    list.append(card);
  }
  const stamp = view.updatedAt ? new Date(view.updatedAt).toLocaleTimeString('zh-TW', { timeZone: 'Asia/Taipei', hour12: false }) : '尚未更新';
  status(view.error || `${view.vm ? 'VM 隔離測試' : view.marketOpen ? '盤中' : '休市'} · ${stamp} · ${view.vip ? 'VIP' : `今日 ${view.used}/3`}`, !!view.error);
  $('vip-msg').textContent = view.vip ? 'VIP 已開通；每次配置更新重新檢查授權。' : view.vm ? 'VM 測試碼：VIP888（不適用正式版）' : '正式授權碼請向管理員取得；不會保存明文。';
}
async function add() {
  if (!view) return;
  const input = $('input-search').value.trim();
  const match = /^(\d{4,6}[A-Za-z]?)(?:\.(TW|TWO))?$/i.exec(input);
  let symbol, market = 'TW';
  if (match) { symbol = match[1].toUpperCase(); market = (match[2] || 'TW').toUpperCase(); }
  else {
    const found = Object.entries(view.quotes || {}).filter(([, q]) => q.name === input);
    if (found.length === 1) symbol = found[0][0];
  }
  if (!symbol || !SYMBOL.test(symbol)) { status('請輸入代號；上櫃請加 .TWO，例如 8299.TWO', true); return; }
  const q = view.quotes?.[symbol];
  const result = await act({ type: 'ADD', stock: { symbol, market, name: q?.name || symbol, groups: [group === 'rebound' ? 'rebound' : 'daytrade'] } }, '已新增；可勾選卡片上的群組');
  if (result) $('input-search').value = '';
}
function drawer(open) {
  $('settings-panel').classList.toggle('translate-x-full', !open);
  $('settings-panel').inert = !open;
  $('settings-panel').setAttribute('aria-hidden', String(!open));
  document.querySelectorAll('header,nav,main,footer').forEach(x => { x.inert = open; });
  (open ? $('btn-close-settings') : $('btn-open-settings')).focus();
}
function payment(open) {
  $('payment-modal').classList.toggle('hidden', !open);
  document.querySelectorAll('header,nav,main,footer').forEach(x => { x.inert = open || !$('settings-panel').classList.contains('translate-x-full'); });
  if (open) $('btn-close-payment').focus(); else $('btn-upgrade').focus();
}
$('btn-open-settings').addEventListener('click', () => drawer(true));
$('btn-close-settings').addEventListener('click', () => drawer(false));
$('btn-add').addEventListener('click', add);
$('input-search').addEventListener('keydown', e => { if (e.key === 'Enter') add(); });
$('input-search').placeholder = '代號／名稱，上櫃例 8299.TWO';
$('input-search').maxLength = 60;
$('group-tabs').addEventListener('click', e => {
  const button = e.target.closest('[data-group]');
  if (button && view) { group = button.dataset.group; render(); }
});
$('btn-refresh').addEventListener('click', () => act({ type: 'SNAPSHOT', refresh: true }));
for (const strategy of GROUPS) {
  $(`toggle-${strategy}`).addEventListener('change', async e => {
    await act({ type: 'SETTINGS', strategy, enabled: e.target.checked }); if (view) render();
  });
  $(`btn-test-${strategy}-notif`).addEventListener('click', () => act({ type: 'TEST', strategy }, '測試通知已交給 Chrome；音效由 VM 系統設定決定'));
}
$('toggle-all-daytrade')?.addEventListener('change', async e => {
  await act({ type: 'SETTINGS', strategy: 'allDaytradeAlerts', enabled: e.target.checked }); if (view) render();
});
$('btn-test-exit-notif')?.addEventListener('click', () => act({ type: 'TEST', action: 'SELL' }, '測試賣出通知已交給 Chrome；音效由 VM 系統設定決定'));
$('btn-activate-vip').addEventListener('click', async () => {
  const key = $('input-vip-key').value; $('input-vip-key').value = '';
  await act({ type: 'VIP', key }, 'VIP 已開通');
});
$('input-vip-key').type = 'password'; $('input-vip-key').maxLength = 128;
$('btn-export-stocks').addEventListener('click', () => {
  if (!view) return;
  const blob = new Blob([JSON.stringify({ version: 1, stocks: view.stocks }, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob), link = document.createElement('a');
  link.href = url; link.download = 'easystock-watchlist.json'; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000); status('已匯出自選名單（不含 VIP 與個人金鑰）');
});
$('btn-import-stocks').addEventListener('click', () => $('file-import').click());
$('file-import').addEventListener('change', async e => {
  const file = e.target.files?.[0]; e.target.value = '';
  if (!file) return;
  try {
    if (file.size > 100000) throw new Error('備份檔案不可超過 100 KB');
    const data = JSON.parse(await file.text());
    if (data.version !== 1) throw new Error('不支援此備份版本');
    const stocks = watchlist(data.stocks);
    if (!confirm(`將取代目前自選清單，共 ${stocks.length} 檔。確定匯入？`)) return;
    await act({ type: 'IMPORT', stocks }, '自選名單匯入完成');
  } catch (err) { status(err.message, true); }
});
$('btn-upgrade').addEventListener('click', () => payment(true));
$('btn-close-payment').addEventListener('click', () => payment(false));
$('btn-checkout-now').addEventListener('click', async () => {
  try {
    const current = await send({ type: 'SNAPSHOT' });
    if (!current.paymentURL) { payment(false); drawer(true); status('管理員尚未設定付款通道；測試碼僅限 VM 版。', true); return; }
    if (confirm(`即將開啟管理員設定的付款網站：\n${new URL(current.paymentURL).hostname}\n付款不會自動開通，仍須取得授權碼。`)) await chrome.tabs.create({ url: current.paymentURL });
  } catch (e) { status(e.message, true); }
});
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') { if (!$('payment-modal').classList.contains('hidden')) payment(false); else drawer(false); }
  if (e.key !== 'Tab') return;
  const panel = !$('payment-modal').classList.contains('hidden') ? $('payment-modal') : !$('settings-panel').inert ? $('settings-panel') : null;
  if (!panel) return;
  const nodes = [...panel.querySelectorAll('button,input,a')].filter(x => !x.disabled && x.type !== 'file');
  const first = nodes[0], last = nodes.at(-1);
  if (e.shiftKey && document.activeElement === first) { last.focus(); e.preventDefault(); }
  if (!e.shiftKey && document.activeElement === last) { first.focus(); e.preventDefault(); }
});
icons(); $('settings-panel').inert = true;
await act({ type: 'SNAPSHOT', refresh: true });
