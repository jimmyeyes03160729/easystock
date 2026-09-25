import { SYMBOL, GROUPS, finite, fresh, watchlist, chartURL, searchStocks, searchOnlineStocks, calcChangePct, fetchStockClosingQuotes } from './core.js';
import { icons } from './icons.js';

const $ = id => document.getElementById(id);
let view, group = 'all', pending = false;
let searchDebounce = null;
let enriching = false;
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
function renderTaiex() {
  const tInfo = view?.taiex;
  const banner = $('taiex-banner');
  if (!tInfo || !finite(tInfo.price)) {
    $('taiex-price').textContent = '-';
    $('taiex-price').className = 'font-bold text-slate-900';
    $('taiex-change').textContent = '-';
    $('otc-price').textContent = '-';
    $('otc-price').className = 'font-medium text-slate-700';
    $('otc-change').textContent = '-';
    if (banner) banner.className = 'flex items-center justify-between px-3 py-1.5 bg-slate-50 border-b border-slate-100 text-[11px]';
    return;
  }
  const isUp = tInfo.change >= 0;
  const sign = isUp ? '+' : '';
  const arrow = isUp ? '▲ ' : '▼ ';
  const colorClass = isUp ? 'text-red-600' : 'text-emerald-600';

  $('taiex-price').textContent = tInfo.price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  $('taiex-price').className = `font-bold ${colorClass}`;
  $('taiex-change').textContent = `${arrow}${sign}${tInfo.change.toFixed(2)} (${sign}${tInfo.change_pct.toFixed(2)}%)`;
  $('taiex-change').className = `font-semibold ${colorClass}`;

  if (finite(tInfo.otc_price)) {
    const otcUp = tInfo.otc_change >= 0;
    const oSign = otcUp ? '+' : '';
    const oArrow = otcUp ? '▲ ' : '▼ ';
    const oColorClass = otcUp ? 'text-red-600' : 'text-emerald-600';

    $('otc-price').textContent = tInfo.otc_price.toFixed(2);
    $('otc-price').className = `font-medium ${oColorClass}`;
    $('otc-change').textContent = `${oArrow}${oSign}${tInfo.otc_change.toFixed(2)}%`;
    $('otc-change').className = `font-medium ${oColorClass}`;
  }

  if (banner) {
    const bgClass = isUp ? 'bg-red-50/40 border-red-100' : 'bg-emerald-50/40 border-emerald-100';
    banner.className = `flex items-center justify-between px-3 py-1.5 ${bgClass} border-b text-[11px] transition-colors cursor-pointer`;
    banner.title = '點擊查看 Yahoo 大盤加權指數即時走勢';
    banner.onclick = () => {
      chrome.tabs.create({ url: 'https://tw.stock.yahoo.com/quote/%5ETWII' });
    };
  }
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
function applyStealthMode(enabled) {
  document.body.classList.toggle('stealth-mode', !!enabled);
  const brand = $('brand-title');
  const tag = $('brand-tag');
  const btnLabel = $('stealth-btn-label');
  const toggleCheckbox = $('toggle-stealth');
  if (toggleCheckbox) toggleCheckbox.checked = !!enabled;
  if (enabled) {
    if (brand) brand.textContent = 'SysMonitor · Cluster Metrics';
    if (tag) tag.textContent = 'Running';
    if (btnLabel) btnLabel.textContent = '搬磚中';
  } else {
    if (brand) brand.textContent = 'EasyStock · 牛馬自救終端';
    if (tag) tag.textContent = '摸魚中';
    if (btnLabel) btnLabel.textContent = '摸魚';
  }
}

function renderAiMatrix(list) {
  const wrap = el('div', '', 'space-y-2.5 text-xs pb-2');

  const headerCard = el('div', '', 'p-3 bg-slate-900 text-white rounded-lg shadow-sm space-y-1');
  const badge = el('div', '', 'flex items-center justify-between');
  badge.append(el('span', 'EASYSTOCK QUANT ENGINE', 'text-[10px] font-mono tracking-wider text-sky-400 font-bold'));
  badge.append(el('span', 'v4.2 PROD', 'text-[9px] bg-slate-800 px-1.5 py-0.5 rounded text-slate-300 font-mono'));
  headerCard.append(badge);
  headerCard.append(el('h2', '當沖量化神經網絡與每日自適應遷移學習', 'text-xs font-bold text-white'));
  headerCard.append(el('p', '高頻微觀訂單流 · 多因子非線性特徵矩陣 · 每日盤後雲端 OOS 增量訓練自我演進', 'text-[10px] text-slate-300 leading-relaxed'));
  wrap.append(headerCard);

  const card1 = el('article', '', 'border border-slate-200 rounded-lg p-2.5 bg-white space-y-1.5 shadow-2xs');
  card1.append(el('h3', '🎯 多維動態選股指標 & 微觀結構過濾', 'font-bold text-slate-900 text-xs flex items-center gap-1'));
  const ul1 = el('ul', '', 'space-y-1 text-[11px] text-slate-600');
  ul1.innerHTML = `
    <li><strong class="text-slate-800">全市場流動性閥值過濾：</strong>開盤即時錨定全市場成交額前 15% 活絡池，自動剔除掛單稀疏與高滑點死水股。</li>
    <li><strong class="text-slate-800">VWAP 瞬時動態偏離矩陣：</strong>即時運算 5 分鐘高頻成交量加權平均價，建立 Z-Score 偏離通道，精確捕捉主力機構吸籌與突破動能。</li>
    <li><strong class="text-slate-800">Tick 級訂單流失衡偵測：</strong>微觀撮合深度剖析，辨識主動性大單連發與急遽爆量（Volume Spurt），排除洗盤虛單誘多。</li>
  `;
  card1.append(ul1);
  wrap.append(card1);

  const card2 = el('article', '', 'border border-slate-200 rounded-lg p-2.5 bg-white space-y-1.5 shadow-2xs');
  card2.append(el('h3', '🧠 雙階類神經網絡 & 每日盤後自我演進', 'font-bold text-slate-900 text-xs flex items-center gap-1'));
  const ul2 = el('ul', '', 'space-y-1 text-[11px] text-slate-600');
  ul2.innerHTML = `
    <li><strong class="text-slate-800">非線性多因子特徵工程：</strong>聚合即時波動率、ATR 振幅擠壓 (Volatility Squeeze)、多時框均線發散斜率與動能擴散指標。</li>
    <li><strong class="text-slate-800">每日雲端 OOS 遷移自學習：</strong>每日 14:00 收盤後，Oracle VM 算力自動提取全市場百萬筆 Tick 撮合數據進行增量微調，動態校準權重閥值，徹底避免傳統靜態指標之鈍化與過擬合。</li>
    <li><strong class="text-slate-800">自適應市場 Regime 切換：</strong>自動辨識大盤處於「高波動趨勢」、「區間震盪洗盤」或「極端崩跌」，動態切換多空靈敏度。</li>
  `;
  card2.append(ul2);
  wrap.append(card2);

  const card3 = el('article', '', 'border border-slate-200 rounded-lg p-2.5 bg-white space-y-1.5 shadow-2xs');
  card3.append(el('h3', '🛡️ 毫秒級量化風控 & 尾盤清倉鐵律', 'font-bold text-slate-900 text-xs flex items-center gap-1'));
  const ul3 = el('ul', '', 'space-y-1 text-[11px] text-slate-600');
  ul3.innerHTML = `
    <li><strong class="text-slate-800">自適應 ATR 移動停利：</strong>波段獲利啟動後，止盈防守點自動隨波動度動態階梯式上移，鎖定波段最大化利潤。</li>
    <li><strong class="text-slate-800">剛性清倉鐵律：</strong>嚴守 -1.5% ~ -2.0% 硬性停損防線，且於 13:15 前無條件強制平倉，落實當沖「零留夜、零跳空風險」原則。</li>
  `;
  card3.append(ul3);
  wrap.append(card3);

  const card4 = el('article', '', 'border border-sky-200 bg-sky-50/60 rounded-lg p-3 space-y-2 shadow-2xs');
  const portalTitle = el('div', '', 'flex items-center justify-between');
  portalTitle.append(el('h3', '🐮 打工牛馬量化救贖傳送門', 'font-bold text-sky-950 text-xs'));
  portalTitle.append(el('span', '上班安心搬磚', 'text-[10px] text-sky-700 bg-sky-100 px-1.5 py-0.5 rounded font-medium'));
  card4.append(portalTitle);
  card4.append(el('p', '專為上班打工牛馬量身打造！告別盯盤焦慮，查看完整即時戰情室、歷史訓練日誌與量化回測報表：', 'text-[11px] text-slate-600 leading-relaxed'));

  const linkBtn = el('a', '', 'flex items-center justify-center gap-1.5 w-full py-2 bg-slate-900 hover:bg-slate-800 text-white rounded-md text-xs font-bold tracking-wide transition shadow-sm cursor-pointer');
  linkBtn.href = 'https://jimmyeyes.com/easystock';
  linkBtn.target = '_blank';
  linkBtn.rel = 'noopener noreferrer';
  linkBtn.innerHTML = `<span>🚀 前往 EasyStock 量化中樞 (jimmyeyes.com/easystock)</span> <span class="text-sky-400">↗</span>`;
  linkBtn.addEventListener('click', (e) => {
    e.preventDefault();
    if (chrome.tabs?.create) {
      chrome.tabs.create({ url: 'https://jimmyeyes.com/easystock' });
    } else {
      window.open('https://jimmyeyes.com/easystock', '_blank');
    }
  });
  card4.append(linkBtn);
  wrap.append(card4);

  list.append(wrap);
}

function renderStrategyBar() {
  const bar = $('strategy-bar');
  if (!bar || !view || group === 'ai_matrix') {
    if (bar) bar.classList.add('hidden');
    return;
  }
  let targets = [];
  let title = '';

  if (group === 'daytrade') {
    title = '🎯 當沖策略即時標的';
    const pos = view.live?.open_positions;
    if (pos && typeof pos === 'object') {
      targets = Object.values(pos).filter(p => p?.status === 'OPEN').map(p => {
        const sym = String(p.symbol);
        const s = view.stocks.find(x => x.symbol === sym);
        const m = s?.market || ((sym.length === 4 && (sym.startsWith('5') || sym.startsWith('6') || sym.startsWith('8'))) ? 'TWO' : 'TW');
        return { symbol: sym, market: m, name: p.name || s?.name || sym, groups: ['daytrade'] };
      });
    }
  } else if (group === 'rebound') {
    title = '🛡️ 觸底反彈策略標的';
    targets = (view.bounce || []).map(b => ({
      symbol: b.symbol,
      market: b.market,
      name: b.name || b.symbol,
      groups: ['rebound']
    }));
  }

  if (!targets.length) {
    bar.classList.add('hidden');
    return;
  }

  bar.classList.remove('hidden');
  $('strategy-bar-title').textContent = title;
  $('strategy-bar-count').textContent = `${targets.length} 檔`;

  const existingSymbols = new Set(view.stocks.map(x => x.symbol));
  const missingTargets = targets.filter(t => !existingSymbols.has(t.symbol));

  const btn = $('btn-batch-add');
  const btnText = $('btn-batch-add-text');
  if (!missingTargets.length) {
    btn.disabled = true;
    btn.className = 'px-2 py-0.5 bg-slate-300 text-slate-500 rounded text-[11px] font-medium flex items-center gap-1 shrink-0 cursor-not-allowed';
    btnText.textContent = '已全部加入自選';
    btn.onclick = null;
  } else {
    btn.disabled = false;
    btn.className = 'px-2 py-0.5 bg-sky-600 hover:bg-sky-700 text-white rounded text-[11px] font-semibold flex items-center gap-1 shrink-0 transition cursor-pointer';
    btnText.textContent = `⚡ 一鍵全部加入 (${missingTargets.length})`;
    btn.onclick = async () => {
      await act({ type: 'ADD_BATCH', stocks: missingTargets }, `已將 ${missingTargets.length} 檔策略標的加入自選名單`);
    };
  }
}
function render() {
  $('vip-status-badge').classList.toggle('hidden', !view.vip);
  $('market-status-dot').className = `h-2 w-2 rounded-full ${view.marketOpen && !view.error ? 'bg-emerald-500' : 'bg-slate-400'}`;
  $('market-status-dot').title = view.vm ? 'VM 隔離示例；不自動交易推播' : view.marketOpen ? '盤中排程；報價時間請看個股' : '休市／非盤中時段';
  for (const key of GROUPS) $(`toggle-${key}`).checked = view.settings[key];
  if ($('toggle-all-daytrade')) $('toggle-all-daytrade').checked = view.settings?.allDaytradeAlerts !== false;
  if ($('toggle-all-rebound')) $('toggle-all-rebound').checked = view.settings?.allReboundAlerts !== false;
  applyStealthMode(view.settings?.stealthMode);
  if ($('radio-filter-all') && $('radio-filter-custom')) {
    const isCustom = view.settings?.filterMode === 'custom';
    $('radio-filter-all').checked = !isCustom;
    $('radio-filter-custom').checked = isCustom;
    if ($('input-min-price') && document.activeElement !== $('input-min-price')) {
      $('input-min-price').value = finite(view.settings?.minPrice) ? view.settings.minPrice : '';
    }
    if ($('input-max-price') && document.activeElement !== $('input-max-price')) {
      $('input-max-price').value = finite(view.settings?.maxPrice) ? view.settings.maxPrice : '';
    }
    if ($('input-min-pct') && document.activeElement !== $('input-min-pct')) {
      $('input-min-pct').value = finite(view.settings?.minChangePct) ? view.settings.minChangePct : '';
    }
    if ($('filter-status-tag')) {
      $('filter-status-tag').textContent = isCustom ? '條件過濾中' : '全開模式';
      $('filter-status-tag').className = `text-[10px] px-1 rounded ${isCustom ? 'text-amber-600 bg-amber-50' : 'text-sky-600 bg-sky-50'}`;
    }
  }
  document.querySelectorAll('.tab-btn').forEach(b => {
    b.setAttribute('aria-selected', String(b.dataset.group === group));
    b.classList.toggle('tab-active', b.dataset.group === group);
  });
  renderTaiex();
  renderStrategyBar();
  const list = $('stock-list-container'); list.replaceChildren();
  if (group === 'ai_matrix') {
    renderAiMatrix(list);
    return;
  }
  const rows = view.stocks.filter(s => group === 'all' || s.groups.includes(group));
  if (!rows.length) list.append(el('p', '此群組尚無自選股票，請輸入代號或名稱新增。', 'text-xs text-slate-500 p-3'));
  for (const s of rows) {
    const q = view.quotes?.[s.symbol], validPrice = finite(q?.price) && q.price > 0;
    const card = el('article', '', 'stock-card border border-slate-200 rounded-lg p-3 bg-white space-y-2');
    const top = el('div', '', 'flex items-start justify-between gap-2');
    const title = el('div', '', 'min-w-0 flex-1');
    const headLine = el('div', '', 'flex items-center gap-1.5 flex-wrap');
    headLine.append(el('h2', `${s.symbol} ${s.name}`, 'text-xs font-bold text-slate-900 break-words'));
    const activePos = view.live?.open_positions?.[s.symbol];
    if (activePos && activePos.status === 'OPEN') {
      headLine.append(el('span', `⚡ 當沖持倉 (成本 ${activePos.entry_price ? activePos.entry_price.toFixed(2) : '-'})`, 'px-1.5 py-0.2 bg-sky-100 text-sky-800 font-semibold rounded text-[10px]'));
    }
    title.append(headLine);
    title.append(el('p', `${s.market === 'TWO' ? '上櫃' : '上市'} · ${s.groups.map(g => label[g]).join(' / ')}`, 'text-[10px] text-slate-400 mt-1'));
    const remove = el('button', '×', 'text-slate-400 hover:text-red-600 px-1');
    remove.title = `刪除 ${s.symbol}`; remove.setAttribute('aria-label', remove.title);
    remove.addEventListener('click', () => act({ type: 'DELETE', symbol: s.symbol }, '已刪除自選股票'));
    top.append(title, remove); card.append(top);

    const price = el('div', '', 'flex items-center justify-between');
    const leftPrice = el('div', '', 'flex items-baseline gap-2');
    leftPrice.append(el('strong', validPrice ? `${q.price.toFixed(2)} 元` : '尚無報價', 'text-lg font-bold text-slate-900'));
    if (finite(q?.volume) && q.volume > 0) {
      leftPrice.append(el('span', `量 ${q.volume.toLocaleString()} 張`, 'text-[10px] text-slate-400'));
    }
    price.append(leftPrice);

    const changePctVal = calcChangePct(q);
    const validPct = finite(changePctVal);
    const pct = validPct ? `${changePctVal >= 0 ? '+' : ''}${changePctVal.toFixed(2)}%` : '0.00% (結盤)';
    const pctColor = validPct ? (changePctVal >= 0 ? 'text-red-600' : 'text-emerald-600') : 'text-slate-400';
    price.append(el('span', pct, `text-xs font-semibold ${pctColor}`));
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
    const chart = el('a', '線圖 ↗', 'text-[11px] text-sky-700 cursor-pointer font-medium hover:underline');
    chart.href = chartURL(s); chart.target = '_blank'; chart.rel = 'noopener noreferrer';
    chart.addEventListener('click', async e => {
      if (chrome.windows && typeof chrome.windows.create === 'function') {
        e.preventDefault();
        const winUrl = chrome.runtime.getURL(`chart.html?symbol=${encodeURIComponent(s.symbol)}&market=${encodeURIComponent(s.market)}&name=${encodeURIComponent(s.name)}`);
        try {
          await chrome.windows.create({ url: winUrl, type: 'popup', width: 960, height: 680, focused: true });
        } catch {
          await chrome.tabs.create({ url: winUrl });
        }
      }
    });
    bottom.append(groups, chart); card.append(bottom);

    const bounce = view.bounce?.find(x => x.symbol === s.symbol && x.market === s.market);
    if (bounce) card.append(el('p', `🛡️ 反彈觀察：${bounce.reason}`, 'text-[10px] text-purple-700 bg-purple-50 px-1.5 py-0.5 rounded'));
    list.append(card);
  }
  const stamp = view.updatedAt ? new Date(view.updatedAt).toLocaleTimeString('zh-TW', { timeZone: 'Asia/Taipei', hour12: false }) : '尚未更新';
  status(view.error || `${view.vm ? 'VM 隔離測試' : view.marketOpen ? '盤中' : '休市'} · ${stamp} · ${view.vip ? 'VIP' : `今日 ${view.used}/3`}`, !!view.error);
  $('vip-msg').textContent = view.vip ? 'VIP 已開通；每次配置更新重新檢查授權。' : view.vm ? 'VM 測試碼：VIP888（不適用正式版）' : '正式授權碼請向管理員取得；不會保存明文。';
  if (!view.vm && view.stocks?.length) {
    enrichMissingQuotes();
  }
}
async function enrichMissingQuotes() {
  if (!view || enriching || view.vm) return;
  const missing = view.stocks.filter(s => {
    const q = view.quotes?.[s.symbol];
    return !q || !finite(calcChangePct(q)) || !finite(q.price);
  });
  if (!missing.length) return;
  enriching = true;
  try {
    const closingMap = await fetchStockClosingQuotes(missing);
    if (closingMap && Object.keys(closingMap).length > 0) {
      if (!view.quotes) view.quotes = {};
      let updated = false;
      for (const [sym, item] of Object.entries(closingMap)) {
        if (!view.quotes[sym] || !finite(view.quotes[sym].price)) {
          view.quotes[sym] = item;
          updated = true;
        } else if (!finite(calcChangePct(view.quotes[sym]))) {
          view.quotes[sym].change_pct = item.change_pct;
          view.quotes[sym].change = item.change;
          view.quotes[sym].previous_close = item.previous_close;
          updated = true;
        }
      }
      if (updated && !pending) render();
    }
  } catch (_) {}
  finally { enriching = false; }
}
function renderSuggestionItems(list) {
  const box = $('search-suggestions');
  if (!box || !view) return;
  box.replaceChildren();
  if (!list.length) {
    box.append(el('div', '查無相符股票', 'p-2 text-slate-400 text-center text-[11px]'));
    box.classList.remove('hidden');
    return;
  }
  box.classList.remove('hidden');
  for (const item of list) {
    const isAdded = view.stocks.some(x => x.symbol === item.symbol);
    const row = el('div', '', 'px-3 py-1.5 hover:bg-slate-100 flex items-center justify-between cursor-pointer border-b border-slate-50 last:border-0');
    const left = el('div', '', 'flex items-center gap-2 min-w-0');
    left.append(el('span', item.symbol, 'font-bold text-slate-900'));
    left.append(el('span', item.name, 'text-slate-700 truncate'));
    left.append(el('span', item.market === 'TWO' ? '上櫃' : '上市', 'text-[10px] text-slate-400'));
    row.append(left);

    if (isAdded) {
      row.append(el('span', '已在自選', 'text-[10px] text-slate-400 bg-slate-100 px-1.5 py-0.5 rounded shrink-0'));
    } else {
      const addBtn = el('button', '＋加入', 'text-[11px] font-medium text-sky-600 hover:text-sky-800 shrink-0 px-1.5 py-0.5 bg-sky-50 hover:bg-sky-100 rounded');
      addBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        box.classList.add('hidden');
        $('input-search').value = '';
        await act({ type: 'ADD', stock: { symbol: item.symbol, market: item.market, name: item.name, groups: [group === 'rebound' ? 'rebound' : 'daytrade'] } }, `已新增 ${item.symbol} ${item.name}`);
      });
      row.append(addBtn);
    }

    row.addEventListener('click', async () => {
      box.classList.add('hidden');
      $('input-search').value = '';
      if (!isAdded) {
        await act({ type: 'ADD', stock: { symbol: item.symbol, market: item.market, name: item.name, groups: [group === 'rebound' ? 'rebound' : 'daytrade'] } }, `已新增 ${item.symbol} ${item.name}`);
      }
    });
    box.append(row);
  }
}
function updateSuggestions() {
  const box = $('search-suggestions');
  if (!box || !view) return;
  const q = $('input-search').value.trim();
  if (!q) {
    box.classList.add('hidden');
    box.replaceChildren();
    return;
  }
  const localList = searchStocks(q, view.quotes || {});
  renderSuggestionItems(localList);

  clearTimeout(searchDebounce);
  searchDebounce = setTimeout(async () => {
    const cur = $('input-search').value.trim();
    if (cur !== q || !cur) return;
    const onlineList = await searchOnlineStocks(cur);
    if ($('input-search').value.trim() === cur) {
      const merged = searchStocks(cur, view.quotes || {});
      renderSuggestionItems(merged);
    }
  }, 180);
}
async function add() {
  if (!view) return;
  const input = $('input-search').value.trim();
  if (!input) return;
  $('search-suggestions')?.classList.add('hidden');

  let matches = searchStocks(input, view.quotes || {});
  let target = matches.find(m => m.symbol === input.toUpperCase() || m.name === input);

  if (!target && !/^\d+$/.test(input)) {
    const onlineMatches = await searchOnlineStocks(input);
    target = onlineMatches.find(m => m.symbol === input.toUpperCase() || m.name === input) || onlineMatches[0];
  }
  if (!target) target = matches[0];

  let symbol, market = 'TW', name;
  if (target) {
    symbol = target.symbol;
    market = target.market;
    name = target.name;
  } else {
    const match = /^(\d{4,6}[A-Za-z]?)(?:\.(TW|TWO))?$/i.exec(input);
    if (match) {
      symbol = match[1].toUpperCase();
      market = (match[2] || (symbol.length === 4 && (symbol.startsWith('5') || symbol.startsWith('6') || symbol.startsWith('8')) ? 'TWO' : 'TW')).toUpperCase();
      name = view.quotes?.[symbol]?.name || symbol;
    }
  }

  if (!symbol || !SYMBOL.test(symbol)) {
    status('請輸入代號或名稱，例: 2330 或 台積電', true);
    return;
  }
  const result = await act({
    type: 'ADD',
    stock: {
      symbol,
      market,
      name: name || symbol,
      groups: [group === 'rebound' ? 'rebound' : 'daytrade']
    }
  }, `已新增 ${symbol} ${name || ''} 至自選`);
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
$('input-search').addEventListener('input', updateSuggestions);
$('input-search').addEventListener('focus', updateSuggestions);
document.addEventListener('click', e => {
  if (!e.target.closest('#input-search') && !e.target.closest('#search-suggestions')) {
    $('search-suggestions')?.classList.add('hidden');
  }
});
$('input-search').placeholder = '代號／中文，例 2330 或 台積電';
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
$('toggle-all-rebound')?.addEventListener('change', async e => {
  await act({ type: 'SETTINGS', strategy: 'allReboundAlerts', enabled: e.target.checked }); if (view) render();
});
$('radio-filter-all')?.addEventListener('change', async e => {
  if (e.target.checked) {
    await act({ type: 'SETTINGS', strategy: 'filterMode', value: 'all' });
    if (view) render();
  }
});
$('radio-filter-custom')?.addEventListener('change', async e => {
  if (e.target.checked) {
    await act({ type: 'SETTINGS', strategy: 'filterMode', value: 'custom' });
    if (view) render();
  }
});
$('btn-save-filter')?.addEventListener('click', async () => {
  const minP = $('input-min-price').value.trim() ? Number($('input-min-price').value) : null;
  const maxP = $('input-max-price').value.trim() ? Number($('input-max-price').value) : null;
  const minPct = $('input-min-pct').value.trim() ? Number($('input-min-pct').value) : null;
  await act({ type: 'SETTINGS', strategy: 'minPrice', value: minP });
  await act({ type: 'SETTINGS', strategy: 'maxPrice', value: maxP });
  await act({ type: 'SETTINGS', strategy: 'minChangePct', value: minPct });
  await act({ type: 'SETTINGS', strategy: 'filterMode', value: 'custom' });
  status('條件過濾設定已儲存');
  if (view) render();
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
async function toggleStealthMode() {
  if (!view) return;
  const current = !!view.settings?.stealthMode;
  const next = !current;
  await act({ type: 'SETTINGS', strategy: 'stealthMode', enabled: next });
  if (view) {
    if (!view.settings) view.settings = {};
    view.settings.stealthMode = next;
    applyStealthMode(next);
  }
  status(next ? '🐮 已切換為牛馬摸魚模式 (低飽和偽裝已啟用)' : '已還原一般彩色看盤模式');
}
$('btn-stealth-toggle')?.addEventListener('click', toggleStealthMode);
$('toggle-stealth')?.addEventListener('change', async e => {
  await act({ type: 'SETTINGS', strategy: 'stealthMode', enabled: e.target.checked });
  if (view) {
    if (!view.settings) view.settings = {};
    view.settings.stealthMode = e.target.checked;
    applyStealthMode(e.target.checked);
  }
  status(e.target.checked ? '🐮 已切換為牛馬摸魚模式 (低飽和偽裝已啟用)' : '已還原一般彩色看盤模式');
});
document.addEventListener('keydown', e => {
  if ((e.key === 'b' || e.key === 'B') && !['INPUT', 'TEXTAREA'].includes(document.activeElement?.tagName) && $('settings-panel')?.inert && $('payment-modal')?.classList.contains('hidden')) {
    toggleStealthMode();
    return;
  }
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
