import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { JSDOM } from 'jsdom';
import * as core from '../core.js';

test('popup v2.0 renders safely and wires current controls', async () => {
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
    return { ok: true, value: structuredClone(state) };
  } }, tabs: { create: async () => {} } };
  for (const [key, value] of Object.entries(core)) w[key] = value;
  w.icons = () => {};
  await w.eval(`(async()=>{${source.replace(/^import .*;\r?\n/gm, '')}})()`);
  await new Promise(resolve => setTimeout(resolve, 10));
  assert.ok(w.document.getElementById('stock-list-container'));
  assert.equal(w.document.querySelectorAll('.stock-card img').length, 0);
  assert.equal(w.document.getElementById('brand-tag').textContent, 'v2.0');
  // Five watchlist group tabs (default names 1–5) replace the single 自選 tab.
  assert.deepEqual([...w.document.querySelectorAll('[data-group="watchlist"][data-list]')].map(b => b.textContent), ['1', '2', '3', '4', '5']);
  assert.ok(w.document.querySelector('[data-group="daytrade"]'));
  assert.ok(w.document.querySelector('[data-group="ai_matrix"]'));
  assert.ok(w.document.getElementById('btn-theme-toggle'));
  assert.ok(w.document.getElementById('btn-open-settings'));
  assert.ok(w.document.getElementById('settings-panel'));
  assert.ok(w.document.getElementById('stock-table-header'));
  assert.ok(w.document.getElementById('watchlist-pagination-bar'));
  dom.window.close();
});


test('2.0 removes 觸底反彈 from Chrome: no tab, no render path, no rebound downloads', async () => {
  const html = await readFile(new URL('../popup.html', import.meta.url), 'utf8');
  const source = await readFile(new URL('../popup.js', import.meta.url), 'utf8');
  const bg = await readFile(new URL('../background.js', import.meta.url), 'utf8');
  const build = await readFile(new URL('../build.mjs', import.meta.url), 'utf8');
  assert.doesNotMatch(html, /data-group="rebound"|觸底反彈/);
  assert.doesNotMatch(source, /renderRebound|view\.bounce/);
  assert.doesNotMatch(bg, /rebound_feed\.json|rebound-engine|RangeRebound|summary\.json/);
  assert.doesNotMatch(build, /rebound-engine\.js/);
});
