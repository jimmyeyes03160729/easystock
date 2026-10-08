/* Presentation only: no orders, strategy changes, Firebase writes or private reads. */
(() => {
  'use strict';
  const get = id => document.getElementById(id);
  const STORAGE_KEY = 'EASYSTOCK_WATCHLIST_V1';
  const validSymbol = x => typeof x === 'string' && /^[A-Za-z0-9_-]{1,20}$/.test(x);
  let saved = [], storageMessage = '', snapshot = {}, lastStocks, lastDate;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const data = JSON.parse(raw);
      if (data?.version !== 1 || !Array.isArray(data.symbols) || data.symbols.length > 100 || !data.symbols.every(validSymbol)) throw Error('invalid');
      saved = [...new Set(data.symbols)];
    }
  } catch (_) { storageMessage = '無法讀取本機自選資料；本次只保留於記憶體，不覆寫原資料。'; }
  let persistAllowed = !storageMessage;
  const setText = (id, value) => { const el = get(id); if (el) el.textContent = value; };
  function timeText(at) {
    const ms = Date.parse(at);
    return Number.isFinite(ms) ? new Date(ms).toLocaleString('zh-TW', {timeZone:'Asia/Taipei', hour12:false}) + '（台北）' : '尚未取得有效時間';
  }
  function emptyReason({live = {}, health = {}, filtered = false, now = Date.now()} = {}) {
    if (!health.current) return health.message || '尚無有效快照，無法確認訊號原因。';
    if (filtered) return '目前紀錄被股價 / 單張預算篩選隱藏；請清除篩選。篩選不會改變交易設定。';
    if (live.session === 'closed') return '當沖已結束；目前為收盤 / 歷史快照，不代表今日有新訊號。';
    if (live.session === 'preopen') return '開盤前待命；尚未進入盤中訊號時段。';
    if (live.session === 'no_new_entry') return '已停止新進場；現有模擬部位仍依原規則監控。';
    if (live.session === 'force_exit') return '強制出場階段，不產生新的進場訊號。';
    if (live.session !== 'daytrade') return '盤中階段待確認；不以缺少紀錄推測市場休市。';
    const gate = live.market_risk || {};
    const age = now - Date.parse(gate.checked_at || gate.received_at);
    const freshGate = Number.isFinite(age) && age >= -60000 && age <= 90000;
    if (freshGate && gate.gate_action === 'BLOCK') {
      if (gate.gate_reason === 'market_risk_red') return '市場風險紅燈：後端目前阻擋新進場，不調整風控門檻。';
      if (gate.gate_reason === 'market_data_unavailable') return '市場資料不可用：後端目前阻擋新進場，等待有效行情。';
      return '後端風控目前阻擋新進場；具體原因待確認。';
    }
    if (live.config?.entry_mode === 'model' && live.config.model_ready === false) return '模型未就緒，禁止新進場；不切換策略或放寬條件。';
    return '目前沒有 OPEN 部位或今日完成交易。尚無可顯示紀錄；是否未符合條件或被其他門檻阻擋，需等待後端證據，不能由空清單推定。';
  }
  function requestFinished(ms, success) {
    const label = Number.isFinite(ms) && ms >= 0
      ? `最近完成的資料請求${success ? '' : '（失敗）'} ${Math.round(ms)} ms`
      : '資料請求耗時未知';
    setText('requestTiming', label);
    setText('footerRequestTiming', label + ' · 含下載與解析，非行情延遲');
  }
  function save() {
    if (persistAllowed) {
      try { localStorage.setItem(STORAGE_KEY, JSON.stringify({version:1, symbols:saved})); }
      catch (_) { persistAllowed = false; storageMessage = '本機儲存不可用；本次自選只保留於記憶體，重新載入後可能消失。'; }
    }
    renderExplorer();
  }
  function button(label, action) {
    const el = document.createElement('button');
    el.type = 'button'; el.textContent = label; el.addEventListener('click', action);
    return el;
  }
  function stockRow(symbol, stock, isSaved) {
    const li = document.createElement('li'), label = document.createElement('span');
    const price = typeof stock?.price === 'number' && Number.isFinite(stock.price) ? `${stock.price} 元/股` : '股價未知';
    label.textContent = stock ? `${symbol} ${stock.name || ''} · 日線 ${stock.updated_at || snapshot.meta?.updated_at || '日期未知'} · ${price}` : `${symbol} · 不在目前股票池，無法確認報價`; li.append(label);
    if (stock) li.append(button(`查看 ${symbol}`, () => snapshot.openStock?.(symbol)));
    const toggle = button(`${isSaved ? '移除自選' : '加入自選'} ${symbol}`, () => {
      if (saved.includes(symbol)) saved = saved.filter(x => x !== symbol);
      else if (saved.length < 100) saved.push(symbol);
      else { setText('watchlistStorageStatus', '自選已達 100 檔，請先移除標的。'); return; }
      save();
      // Rebuilt rows must retain a usable keyboard focus target.
      const target = [...document.querySelectorAll('#stockExplorer button')].find(x => x.textContent === `${saved.includes(symbol) ? '移除自選' : '加入自選'} ${symbol}`);
      (target || get('stockSearch'))?.focus();
    });
    li.append(toggle); return li;
  }
  function renderExplorer() {
    const results = get('stockSearchResults'), watch = get('stockWatchlist');
    if (!results || !watch) return;
    const pool = Array.isArray(snapshot.stocks) ? snapshot.stocks : [];
    const bySymbol = new Map(pool.filter(s => validSymbol(String(s.symbol))).map(s => [String(s.symbol), s]));
    const query = (get('stockSearch')?.value || '').trim().toLocaleLowerCase();
    results.replaceChildren(); watch.replaceChildren();
    const matches = query ? [...bySymbol.values()].filter(s => String(s.symbol).toLocaleLowerCase().includes(query) || String(s.name || '').toLocaleLowerCase().includes(query)) : [];
    matches.slice(0, 20).forEach(s => results.append(stockRow(String(s.symbol), s, saved.includes(String(s.symbol)))));
    setText('stockSearchStatus', !pool.length ? '目前股票池尚未載入或不可用；不代表全市場沒有標的。' : !query ? `可搜尋目前股票池 ${bySymbol.size} 檔；請輸入代號或名稱。` : !matches.length ? '目前股票池找不到符合標的；不代表股票不存在。' : `找到 ${matches.length} 檔${matches.length > 20 ? '，顯示前 20 檔；請縮小搜尋' : ''}。資料有效性請看上方狀態。`);
    saved.forEach(symbol => watch.append(stockRow(symbol, bySymbol.get(symbol), true)));
    if (!saved.length) { const li = document.createElement('li'); li.textContent = '尚無自選；搜尋後按「加入自選」。'; watch.append(li); }
    setText('watchlistStorageStatus', storageMessage || '不會上傳帳號或同步其他裝置；最多 100 檔。');
  }
  function update(data) {
    snapshot = data;
    const live = data.live || {}, health = data.health || {}, meta = data.meta || {};
    const labels = {preopen:'開盤前',daytrade:'盤中模擬監控',no_new_entry:'停止新進場',force_exit:'強制出場階段',closed:'收盤 / 歷史快照'};
    setText('overviewSession', health.current ? (labels[live.session] || '階段待確認') : (health.label || '待確認'));
    const dailyConnection = data.dailyFetchState === 'failed' ? '最近讀取失敗，保留最後快照；' : data.dailyFetchState === 'loading' ? '正在讀取；' : '';
    setText('overviewValidity', `日線：${dailyConnection}${data.dailyValid ? '符合既有版本 / 日期檢查（非即時）' : '待確認或失效，不產生資格推薦'} · 盤中：${health.current ? live.session === 'closed' ? '收盤 / 歷史快照，非即時' : '快照通過時效檢查' : '待確認 / 失效'}`);
    setText('overviewUpdated', `日線 ${meta.updated_at || '未知'} · 盤中 ${timeText(live.last_update_at || live.generated_at)}`);
    setText('overviewNotice', health.message || '此處的「盤中」是模擬資料服務階段，不是交易所開市或實盤執行證明。');
    if (lastStocks !== data.stocks || lastDate !== meta.updated_at) {
      lastStocks = data.stocks; lastDate = meta.updated_at; renderExplorer();
    }
  }
  get('stockSearch')?.addEventListener('input', renderExplorer);
  window.DashboardUX = {update, emptyReason, requestFinished};
  renderExplorer();
})();
