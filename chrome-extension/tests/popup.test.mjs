import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { JSDOM } from 'jsdom';
import * as core from '../core.js';

test('popup v1.03 renders safely and wires current controls', async () => {
  const html = await readFile(new URL('../popup.html', import.meta.url), 'utf8');
  const source = await readFile(new URL('../popup.js', import.meta.url), 'utf8');
  const dom = new JSDOM(html, { url: 'https://example.test', runScripts: 'outside-only' });
  const w = dom.window, messages = [];
  w.setInterval = () => 0;
  const state = { ...core.defaultState(), vm: true, quotes: {}, live: {}, taiex: null };
  state.settings.darkMode = false;
  state.stocks[0].name = '<img src=x onerror=alert(1)>';
  w.chrome = { storage: { local: { get: async () => ({ state }) } }, runtime: { onMessage: { addListener: () => {} }, sendMessage: async message => {
    messages.push(message);
    if (message.type === 'SETTINGS') state.settings[message.strategy] = message.enabled ?? message.value;
    return structuredClone(state);
  } }, tabs: { create: async () => {} } };
  for (const key of ['SYMBOL','GROUPS','QUOTE_FRESH_MS','finite','fresh','formatTaipeiQuoteTime','watchlist','chartURL','searchStocks','searchOnlineStocks','calcChangePct','fetchStockClosingQuotes','formatTelegramEntry','formatTelegramExit','BROKERS','getBroker']) w[key] = core[key];
  w.icons = () => {};
  await w.eval(`(async()=>{${source.replace(/^import .*;\r?\n/gm, '')}})()`);
  await new Promise(resolve => setTimeout(resolve, 10));
  assert.ok(w.document.getElementById('stock-list-container'));
  assert.equal(w.document.querySelectorAll('.stock-card img').length, 0);
  assert.equal(w.document.getElementById('brand-tag').textContent, 'v1.03');
  assert.ok(w.document.querySelector('[data-group="watchlist"]'));
  assert.ok(w.document.querySelector('[data-group="daytrade"]'));
  assert.ok(w.document.querySelector('[data-group="ai_matrix"]'));
  assert.ok(w.document.getElementById('btn-theme-toggle'));
  assert.ok(w.document.getElementById('btn-open-settings'));
  assert.ok(w.document.getElementById('settings-panel'));
  assert.ok(w.document.getElementById('stock-table-header'));
  assert.ok(w.document.getElementById('watchlist-pagination-bar'));
  dom.window.close();
});
