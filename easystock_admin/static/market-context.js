'use strict';
// Read-only market diagnostics for the health page. Unknown/stale values never become zero.
(() => {
  const byId = id => document.getElementById(id);
  const contextNumber = value => typeof value === 'number' && Number.isFinite(value) ? value : null;
  function contextTime(value) {
    const at = typeof value === 'string' ? Date.parse(value) : NaN;
    return Number.isFinite(at) ? new Date(at).toLocaleString('zh-TW', {timeZone:'Asia/Taipei',hour12:false}) : '時間待確認';
  }
  function contextValue(value, suffix = '', signed = false) {
    const n = contextNumber(value);
    if (n === null) return '—';
    const rounded = Math.round(n * 100) / 100;
    return (signed && rounded > 0 ? '+' : '') + rounded.toFixed(2) + suffix;
  }
  function contextNode(tag, content, className) {
    const node = document.createElement(tag);
    if (content !== undefined) node.textContent = content;
    if (className) node.className = className;
    return node;
  }
  function contextMetric(root, label, value, className = '') {
    const box = contextNode('div', undefined, 'market-context-metric');
    box.append(contextNode('span', label), contextNode('strong', value, className));
    root.append(box);
  }
  function contextTone(value) {
    const n = contextNumber(value);
    return n === null || n === 0 ? '' : n > 0 ? 'context-up' : 'context-down';
  }
  function renderMarketContext(c) {
    const root = byId('marketContext');root.replaceChildren();
    const current = c?.current === true, breadth = c?.breadth || {}, rotation = c?.rotation || {};
    const breadthValid = current && breadth.valid === true && breadth.fresh === true;
    const states = {OK:'有效快照',DEGRADED:'部分資料可用',UNKNOWN:'待確認',MARKET_CLOSED:'休市／盤後'};
    const rotations = {SHIPPING_LEADING:'航運領先',ELECTRONICS_LEADING:'電子領先',SEMICONDUCTOR_LEADING:'半導體領先',FINANCIAL_LEADING:'金融領先',ELECTRONIC_COMPONENTS_LEADING:'電子零組件領先',MIXED:'類股走勢分歧',UNKNOWN:'待確認'};
    const summary = contextNode('div', undefined, 'market-context-summary');
    contextMetric(summary, '市場廣度', breadthValid ? (states[breadth.status] || '狀態待確認') : '待確認');
    const count = value => Number.isInteger(value) && value >= 0 ? value.toLocaleString('zh-TW') : '—';
    contextMetric(summary, '上漲 / 下跌 / 持平', breadthValid ? [breadth.advancers,breadth.decliners,breadth.unchanged].map(count).join(' / ') : '— / — / —');
    const coverage = breadthValid ? contextNumber(breadth.coverage) : null;
    contextMetric(summary, '快照有效覆蓋率', coverage !== null && coverage >= 0 && coverage <= 1 ? contextValue(coverage * 100, '%') : '—');
    contextMetric(summary, '價格輪動代理', current && rotation.valid === true && rotation.fresh === true ? (rotations[rotation.rotation_state] || '待確認') : '待確認');
    root.append(summary, contextNode('p', '資料更新：' + contextTime(c?.generated_at) + '（台北） · 覆蓋率僅針對 API 回傳快照，不代表全市場覆蓋率。', 'market-context-updated'));
    const rows = Array.isArray(c?.sectors?.rows) ? c.sectors.rows : [];
    if (!rows.length) {root.append(contextNode('p', '尚未取得類股資料；不代表各類股漲跌為零。', 'hint'));return;}
    const grid = contextNode('div', undefined, 'market-sector-grid');
    for (const s of rows) {
      const valid = current && s?.valid === true && s?.fresh === true;
      const value = valid ? contextNumber(s.return_day) : null, relative = valid ? contextNumber(s.relative_to_taiex) : null;
      const card = contextNode('article', undefined, 'market-sector-card');
      const head = contextNode('div', undefined, 'market-sector-head');
      head.append(contextNode('h4', s?.name || '未命名類股'), contextNode('span', valid && Number.isInteger(s.rank) && s.rank > 0 ? '排名 ' + s.rank : '未排名', 'market-context-badge'));
      card.append(head, contextNode('strong', contextValue(value, '%', true), 'market-sector-return ' + contextTone(value)));
      const detail = contextNode('div', undefined, 'market-sector-detail');
      detail.append(contextNode('span', '當日漲跌'), contextNode('span', '相對大盤 ' + contextValue(relative, ' pp', true), contextTone(relative)));
      card.append(detail, contextNode('span', valid ? '最新快照' : s?.fresh === false ? '過期／待更新' : '有效性待確認', 'market-context-badge'));
      card.append(contextNode('p', '報價 ' + contextTime(s?.quote_at) + '（台北）', 'market-sector-time'));
      grid.append(card);
    }
    root.append(grid);
  }
  async function market() {
    try { renderMarketContext(await api('api/market-context')); }
    catch (e) { const root = byId('marketContext');root.replaceChildren(contextNode('p', '市場情境讀取失敗，狀態待確認：' + e.message, 'error')); }
  }
  window.loadMarketContext=market;
  document.addEventListener('easystock:owner-ready',market);
})();
