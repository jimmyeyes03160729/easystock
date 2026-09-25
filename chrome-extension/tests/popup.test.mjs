import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { JSDOM } from 'jsdom';
import * as core from '../core.js';

test('popup preserves IDs, safe rendering, groups, controls and message wiring', async () => {
  const html = await readFile(new URL('../popup.html', import.meta.url), 'utf8');
  const source = await readFile(new URL('../popup.js', import.meta.url), 'utf8');
  const dom = new JSDOM(html, { url: 'https://example.test', runScripts: 'outside-only' });
  const w = dom.window, messages = [];
  const state = { ...core.defaultState(), vip: false, vm: true, quotes: {}, bounce: [], used: 0, marketOpen: false, paymentURL: '' };
  state.stocks.push({ symbol: '8299', market: 'TWO', name: '<img src=x onerror=alert(1)>', groups: ['rebound'] });
  state.bounce.push({ symbol: '8299', market: 'TWO', name: '群聯', price: 500, reason: '支撐區反彈' });
  w.chrome = { runtime: { sendMessage: async m => {
    messages.push(m);
    if (m.type === 'SETTINGS') {
      state.settings[m.strategy] = m.enabled !== undefined ? m.enabled : m.value;
    }
    return { ok: true, value: m.type === 'TEST' ? { sent: true } : structuredClone(state) };
  } }, tabs: { create: async () => {} } };
  for (const key of ['SYMBOL', 'GROUPS', 'finite', 'fresh', 'watchlist', 'chartURL', 'searchStocks', 'searchOnlineStocks', 'calcChangePct', 'fetchStockClosingQuotes', 'formatTelegramEntry', 'formatTelegramExit', 'formatTelegramRebound']) w[key] = core[key];
  w.icons = () => {};
  state.taiex = { price: 22800.5, change: 150.2, change_pct: 0.66, otc_price: 270.1, otc_change: 1.2, otc_change_pct: 0.45 };
  await w.eval(`(async()=>{${source.replace(/^import .*;\r?\n/gm, '')}})()`);
  assert.equal(w.document.querySelectorAll('.stock-card').length, 2);
  assert.equal(w.document.querySelectorAll('.stock-card img').length, 0);
  assert.match(w.document.getElementById('stock-list-container').textContent, /<img src=x/);
  assert.match(w.document.getElementById('taiex-price').textContent, /22,800\.50/);
  assert.ok(w.document.getElementById('taiex-price').classList.contains('text-red-600'));
  assert.match(w.document.getElementById('taiex-change').textContent, /▲\s*\+150\.20/);
  assert.equal(w.document.getElementById('stock-list-container').textContent.includes('漲跌幅未提供'), false);
  w.document.querySelector('[data-group="rebound"]').click();
  assert.equal(w.document.querySelectorAll('.stock-card').length, 1);

  // Test search suggestions for Chinese name
  const searchInput = w.document.getElementById('input-search');
  const suggestBox = w.document.getElementById('search-suggestions');
  assert.ok(suggestBox);
  searchInput.value = '台積電';
  searchInput.dispatchEvent(new w.Event('input'));
  assert.equal(suggestBox.classList.contains('hidden'), false);
  assert.match(suggestBox.textContent, /2330/);
  assert.match(suggestBox.textContent, /台積電/);

  // Test strategy bar and batch add
  state.live = {
    open_positions: {
      '2454': { symbol: '2454', name: '聯發科', status: 'OPEN', entry_price: 1200 }
    }
  };
  w.document.getElementById('btn-refresh').click();
  await new Promise(r => setTimeout(r, 0));
  w.document.querySelector('[data-group="daytrade"]').click();
  const stratBar = w.document.getElementById('strategy-bar');
  assert.ok(stratBar);
  assert.equal(stratBar.classList.contains('hidden'), false);
  assert.match(w.document.getElementById('strategy-bar-title').textContent, /當沖策略即時標的/);
  const batchBtn = w.document.getElementById('btn-batch-add');
  assert.ok(batchBtn);
  batchBtn.click();
  await new Promise(r => setTimeout(r, 0));
  assert.equal(messages.at(-1).type, 'ADD_BATCH');
  assert.equal(messages.at(-1).stocks[0].symbol, '2454');

  // Test AI Matrix tab rendering
  w.document.querySelector('[data-group="ai_matrix"]').click();
  const listContainer = w.document.getElementById('stock-list-container');
  assert.match(listContainer.textContent, /當沖量化神經網絡與每日自適應遷移學習/);
  assert.match(listContainer.textContent, /全市場流動性閥值過濾/);
  assert.match(listContainer.textContent, /每日雲端 OOS 遷移自學習/);
  assert.match(listContainer.textContent, /jimmyeyes\.com\/easystock/);
  assert.equal(stratBar.classList.contains('hidden'), true);

  // Test stealth mode (牛馬上班摸魚模式)
  const stealthBtn = w.document.getElementById('btn-stealth-toggle');
  assert.ok(stealthBtn);
  stealthBtn.click();
  await new Promise(r => setTimeout(r, 0));
  assert.equal(messages.at(-1).type, 'SETTINGS');
  assert.equal(messages.at(-1).strategy, 'stealthMode');
  assert.equal(messages.at(-1).enabled, true);
  assert.equal(w.document.body.classList.contains('stealth-mode'), true);
  assert.match(w.document.getElementById('brand-title').textContent, /OA企業門戶/);
  assert.equal(w.document.getElementById('stealth-btn-label').textContent, '搬磚中');

  stealthBtn.click();
  await new Promise(r => setTimeout(r, 0));
  assert.equal(messages.at(-1).enabled, false);
  assert.equal(w.document.body.classList.contains('stealth-mode'), false);
  assert.match(w.document.getElementById('brand-title').textContent, /牛馬自救終端/);
  assert.equal(w.document.getElementById('stealth-btn-label').textContent, '摸魚');

  w.document.getElementById('btn-open-settings').click();
  assert.equal(w.document.getElementById('settings-panel').inert, false);
  w.document.getElementById('btn-test-daytrade-notif').click();
  await new Promise(r => setTimeout(r, 0));
  assert.equal(messages.at(-1).type, 'TEST');
  assert.match(w.document.getElementById('action-message').textContent, /Chrome/);
  
  // Test page density settings
  const rangePageSize = w.document.getElementById('range-page-size');
  assert.ok(rangePageSize);
  rangePageSize.value = '8';
  rangePageSize.dispatchEvent(new w.Event('change'));
  await new Promise(r => setTimeout(r, 0));
  assert.equal(messages.at(-1).type, 'SETTINGS');
  assert.equal(messages.at(-1).strategy, 'pageSize');
  assert.equal(messages.at(-1).value, 8);

  // Test window height slider (圖片1效果)
  const rangeHeight = w.document.getElementById('range-window-height');
  assert.ok(rangeHeight);
  rangeHeight.value = '680';
  rangeHeight.dispatchEvent(new w.Event('input'));
  assert.equal(w.document.body.style.height, '680px');
  rangeHeight.dispatchEvent(new w.Event('change'));
  await new Promise(r => setTimeout(r, 0));
  assert.equal(messages.at(-1).type, 'SETTINGS');
  assert.equal(messages.at(-1).strategy, 'windowHeight');
  assert.equal(messages.at(-1).value, 680);

  // Test font size selector (圖片1效果)
  const radioLarge = w.document.getElementById('radio-size-large');
  assert.ok(radioLarge);
  radioLarge.checked = true;
  radioLarge.dispatchEvent(new w.Event('change'));
  await new Promise(r => setTimeout(r, 0));
  assert.equal(messages.at(-1).type, 'SETTINGS');
  assert.equal(messages.at(-1).strategy, 'fontSize');
  assert.equal(messages.at(-1).value, 'large');
  assert.ok(w.document.getElementById('stock-list-container').classList.contains('size-large'));

  // Test sparkline toggle (圖片1效果)
  const toggleSpark = w.document.getElementById('toggle-sparkline');
  assert.ok(toggleSpark);
  toggleSpark.checked = false;
  toggleSpark.dispatchEvent(new w.Event('change'));
  await new Promise(r => setTimeout(r, 0));
  assert.equal(messages.at(-1).type, 'SETTINGS');
  assert.equal(messages.at(-1).strategy, 'showSparkline');
  assert.equal(messages.at(-1).enabled, false);

  // Test Table Header (圖片2排版)
  const tableHeader = w.document.getElementById('stock-table-header');
  assert.ok(tableHeader);
  assert.match(tableHeader.textContent, /個股/);
  assert.match(tableHeader.textContent, /今價/);
  assert.match(tableHeader.textContent, /漲跌/);
  assert.match(tableHeader.textContent, /高 \/ 低/);
  assert.match(tableHeader.textContent, /時間/);

  w.document.getElementById('btn-close-settings').click();
  assert.equal(w.document.getElementById('settings-panel').inert, true);
  dom.window.close();
});
