import { SYMBOL, GROUPS, finite, fresh, watchlist, chartURL, searchStocks, searchOnlineStocks, calcChangePct, fetchStockClosingQuotes } from './core.js';
import { icons } from './icons.js';

const $ = id => document.getElementById(id);
let view, group = 'watchlist', pending = false;
let searchDebounce = null;
let enriching = false;
const label = { daytrade: '當沖', rebound: '觸底反彈', watchlist: '自選' };

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

function openChartWindow(s, strategy = '') {
  const winUrl = chrome.runtime.getURL(`chart.html?symbol=${encodeURIComponent(s.symbol)}&market=${encodeURIComponent(s.market)}&name=${encodeURIComponent(s.name || s.symbol)}&strategy=${encodeURIComponent(strategy)}`);
  if (chrome.windows && typeof chrome.windows.create === 'function') {
    chrome.windows.create({ url: winUrl, type: 'popup', width: 960, height: 680, focused: true }).catch(() => {
      chrome.tabs.create({ url: winUrl });
    });
  } else {
    chrome.tabs.create({ url: winUrl });
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
  if (!bar || !view || group === 'ai_matrix' || group === 'watchlist') {
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
        return { symbol: sym, market: m, name: p.name || s?.name || sym, groups: ['watchlist'] };
      });
    }
  } else if (group === 'rebound') {
    title = '🛡️ 觸底反彈策略標的';
    targets = (view.bounce || []).map(b => ({
      symbol: b.symbol,
      market: b.market,
      name: b.name || b.symbol,
      groups: ['watchlist']
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

// 渲染自選看股清單 (單純看股，徹底拔除當沖/反彈勾選方塊)
function renderWatchlist(list, isCompact) {
  const rows = view.stocks || [];
  if (!rows.length) {
    list.append(el('p', '目前尚無自選股票，請於上方輸入代號或名稱新增。', 'text-xs text-slate-500 p-3'));
    return;
  }

  for (const s of rows) {
    const q = view.quotes?.[s.symbol], validPrice = finite(q?.price) && q.price > 0;
    const changePctVal = calcChangePct(q);
    const validPct = finite(changePctVal);
    const pct = validPct ? `${changePctVal >= 0 ? '+' : ''}${changePctVal.toFixed(2)}%` : '0.00% (結盤)';
    const pctColor = validPct ? (changePctVal >= 0 ? 'text-red-600' : 'text-emerald-600') : 'text-slate-400';

    const card = el('article', '', `stock-card border border-slate-200 rounded-lg ${isCompact ? 'p-2' : 'p-3'} bg-white space-y-1.5 shadow-2xs hover:border-slate-300 transition`);

    // 頂部列：代號 名稱 市場 系統訊號標籤 刪除
    const top = el('div', '', 'flex items-center justify-between gap-1');
    const headLine = el('div', '', 'flex items-center gap-1.5 flex-wrap min-w-0');
    headLine.append(el('h2', `${s.symbol} ${s.name}`, 'text-xs font-bold text-slate-900 truncate'));
    headLine.append(el('span', s.market === 'TWO' ? '上櫃' : '上市', 'text-[9px] text-slate-400 bg-slate-100 px-1 py-0.2 rounded shrink-0'));

    // 系統狀態提示標籤 (由系統模型決定，非自選勾選)
    const activePos = view.live?.open_positions?.[s.symbol];
    if (activePos && activePos.status === 'OPEN') {
      headLine.append(el('span', '⚡ 系統當沖中', 'px-1.5 py-0.2 bg-sky-100 text-sky-800 font-semibold rounded text-[9px] shrink-0'));
    }
    const isReboundTarget = view.bounce?.some(b => b.symbol === s.symbol);
    if (isReboundTarget) {
      headLine.append(el('span', '🛡️ 反彈觀察', 'px-1.5 py-0.2 bg-purple-100 text-purple-800 font-semibold rounded text-[9px] shrink-0'));
    }

    const remove = el('button', '×', 'text-slate-400 hover:text-red-600 px-1 font-bold text-sm leading-none shrink-0');
    remove.title = `從自選刪除 ${s.symbol}`;
    remove.setAttribute('aria-label', remove.title);
    remove.addEventListener('click', () => act({ type: 'DELETE', symbol: s.symbol }, `已刪除自選股票 ${s.symbol}`));

    top.append(headLine, remove);
    card.append(top);

    // 價格列
    const priceRow = el('div', '', 'flex items-center justify-between');
    const leftPrice = el('div', '', 'flex items-baseline gap-2');
    leftPrice.append(el('strong', validPrice ? `${q.price.toFixed(2)}` : '尚無報價', `card-price ${isCompact ? 'text-base' : 'text-lg'} font-bold text-slate-900`));
    if (validPrice) leftPrice.append(el('span', '元', 'text-[10px] text-slate-400 font-normal'));
    if (finite(q?.volume) && q.volume > 0) {
      leftPrice.append(el('span', `量 ${q.volume.toLocaleString()} 張`, 'card-meta text-[10px] text-slate-400 ml-1'));
    }
    priceRow.append(leftPrice);

    const rightPct = el('div', '', 'flex items-center gap-2');
    rightPct.append(el('span', pct, `text-xs font-bold ${pctColor}`));

    const chartBtn = el('a', '線圖 ↗', 'text-[11px] text-sky-700 cursor-pointer font-medium hover:underline shrink-0');
    chartBtn.href = chartURL(s);
    chartBtn.target = '_blank';
    chartBtn.rel = 'noopener noreferrer';
    chartBtn.addEventListener('click', e => {
      e.preventDefault();
      openChartWindow(s, activePos ? 'daytrade' : (isReboundTarget ? 'rebound' : ''));
    });
    rightPct.append(chartBtn);

    priceRow.append(rightPct);
    card.append(priceRow);

    // 非緊湊模式下顯示行情更新時間
    if (!isCompact) {
      const when = q?.updated_at && Number.isFinite(Date.parse(q.updated_at)) ? new Date(q.updated_at).toLocaleString('zh-TW', { timeZone: 'Asia/Taipei', hour12: false }) : '無資料';
      card.append(el('p', `${view.vm ? 'VM 示例 · ' : ''}${validPrice && fresh(q.updated_at, Date.now()) ? '最新行情' : '最後結盤'} ${when}`, 'card-meta text-[10px] text-slate-400'));
    }

    list.append(card);
  }
}

// 渲染系統當沖持倉部位 (獨立策略區塊)
function renderDaytrade(list, isCompact) {
  const pos = view.live?.open_positions;
  const openPositions = pos && typeof pos === 'object' ? Object.values(pos).filter(p => p?.status === 'OPEN') : [];

  if (!openPositions.length) {
    const emptyBox = el('div', '', 'p-4 text-center space-y-1 bg-white border border-slate-200 rounded-lg');
    emptyBox.append(el('div', '🎯', 'text-2xl mb-1'));
    emptyBox.append(el('h3', '目前系統尚無當沖開倉部位', 'text-xs font-bold text-slate-700'));
    emptyBox.append(el('p', '量化神經網絡持續微觀掃描全市場訂單流，爆量突破時將自動發送買進訊號推播。', 'text-[11px] text-slate-400 leading-relaxed'));
    list.append(emptyBox);
    return;
  }

  const existingSymbols = new Set(view.stocks.map(x => x.symbol));

  for (const p of openPositions) {
    const sym = String(p.symbol);
    const s = view.stocks.find(x => x.symbol === sym);
    const m = s?.market || ((sym.length === 4 && (sym.startsWith('5') || sym.startsWith('6') || sym.startsWith('8'))) ? 'TWO' : 'TW');
    const name = p.name || s?.name || sym;

    const q = view.quotes?.[sym];
    const curPrice = (q && finite(q.price) && q.price > 0) ? q.price : (finite(p.price) ? p.price : (finite(p.entry_price) ? p.entry_price : 0));
    const entryPrice = finite(p.entry_price) ? p.entry_price : curPrice;
    const pnlPct = entryPrice > 0 ? ((curPrice - entryPrice) / entryPrice) * 100 : (finite(p.pnl_pct) ? p.pnl_pct : 0);
    const isUp = pnlPct >= 0;
    const sign = isUp ? '+' : '';
    const pnlColor = isUp ? 'text-red-600' : 'text-emerald-600';

    const card = el('article', '', `stock-card border border-sky-200 bg-sky-50/30 rounded-lg ${isCompact ? 'p-2' : 'p-3'} space-y-1.5 shadow-2xs`);

    // 標題列
    const top = el('div', '', 'flex items-center justify-between gap-1');
    const leftTitle = el('div', '', 'flex items-center gap-1.5 min-w-0');
    leftTitle.append(el('h2', `${sym} ${name}`, 'text-xs font-bold text-slate-900 truncate'));
    leftTitle.append(el('span', '持倉中', 'text-[9px] bg-sky-600 text-white font-bold px-1.5 py-0.2 rounded shrink-0'));
    if (p.entry_score) {
      leftTitle.append(el('span', `分: ${p.entry_score}`, 'text-[9px] bg-sky-100 text-sky-800 px-1 py-0.2 rounded font-mono shrink-0'));
    }
    top.append(leftTitle);

    // 加入自選按鈕
    const inWatch = existingSymbols.has(sym);
    if (inWatch) {
      top.append(el('span', '✓ 已在自選', 'text-[10px] text-slate-400 bg-slate-100 px-1.5 py-0.5 rounded shrink-0'));
    } else {
      const addBtn = el('button', '＋加入自選', 'text-[10px] font-semibold text-sky-600 hover:text-sky-800 bg-white hover:bg-sky-50 border border-sky-200 px-1.5 py-0.5 rounded shrink-0 transition');
      addBtn.addEventListener('click', async () => {
        await act({ type: 'ADD', stock: { symbol: sym, market: m, name, groups: ['watchlist'] } }, `已將 ${sym} ${name} 加入自選`);
      });
      top.append(addBtn);
    }
    card.append(top);

    // 數據列：進場價、市價、損益
    const dataRow = el('div', '', 'flex items-center justify-between text-xs');
    const leftData = el('div', '', 'flex items-baseline gap-2');
    leftData.append(el('span', `成本 ${entryPrice.toFixed(2)}`, 'text-slate-500 text-[11px]'));
    leftData.append(el('strong', `現價 ${curPrice.toFixed(2)}`, 'font-bold text-slate-900'));
    dataRow.append(leftData);

    const rightData = el('div', '', 'flex items-center gap-2');
    rightData.append(el('span', `${sign}${pnlPct.toFixed(2)}%`, `font-bold ${pnlColor}`));

    const chartBtn = el('a', '線圖 ↗', 'text-[11px] text-sky-700 cursor-pointer font-medium hover:underline shrink-0');
    chartBtn.href = chartURL({ symbol: sym, market: m });
    chartBtn.target = '_blank';
    chartBtn.rel = 'noopener noreferrer';
    chartBtn.addEventListener('click', e => {
      e.preventDefault();
      openChartWindow({ symbol: sym, market: m, name }, 'daytrade');
    });
    rightData.append(chartBtn);

    dataRow.append(rightData);
    card.append(dataRow);

    // 進場理由
    const reasons = Array.isArray(p.entry_reasons) ? p.entry_reasons.join(' · ') : (p.reason || '動能突破');
    if (reasons) {
      card.append(el('p', `💡 ${reasons}`, 'text-[10px] text-slate-500 truncate'));
    }

    list.append(card);
  }
}

// 渲染系統觸底反彈清單 (獨立策略區塊)
function renderRebound(list, isCompact) {
  const bounceList = view.bounce || [];
  if (!bounceList.length) {
    const emptyBox = el('div', '', 'p-4 text-center space-y-1 bg-white border border-slate-200 rounded-lg');
    emptyBox.append(el('div', '🛡️', 'text-2xl mb-1'));
    emptyBox.append(el('h3', '目前無觸底反彈觀察標的', 'text-xs font-bold text-slate-700'));
    emptyBox.append(el('p', '系統後台定時掃描技術面支撐區、量能回升與超跌指標，出現訊號將自動推播。', 'text-[11px] text-slate-400 leading-relaxed'));
    list.append(emptyBox);
    return;
  }

  const existingSymbols = new Set(view.stocks.map(x => x.symbol));

  for (const b of bounceList) {
    const sym = b.symbol;
    const name = b.name || sym;
    const m = b.market || 'TW';
    const q = view.quotes?.[sym];
    const price = (q && finite(q.price) && q.price > 0) ? q.price : (finite(b.price) ? b.price : 0);
    const changePctVal = calcChangePct(q) ?? b.change_pct;
    const validPct = finite(changePctVal);
    const pct = validPct ? `${changePctVal >= 0 ? '+' : ''}${changePctVal.toFixed(2)}%` : '-';
    const pctColor = validPct ? (changePctVal >= 0 ? 'text-red-600' : 'text-emerald-600') : 'text-slate-400';

    const card = el('article', '', `stock-card border border-purple-200 bg-purple-50/20 rounded-lg ${isCompact ? 'p-2' : 'p-3'} space-y-1.5 shadow-2xs`);

    // 標題列
    const top = el('div', '', 'flex items-center justify-between gap-1');
    const leftTitle = el('div', '', 'flex items-center gap-1.5 min-w-0');
    leftTitle.append(el('h2', `${sym} ${name}`, 'text-xs font-bold text-slate-900 truncate'));
    leftTitle.append(el('span', m === 'TWO' ? '上櫃' : '上市', 'text-[9px] text-slate-400 bg-slate-100 px-1 py-0.2 rounded shrink-0'));
    leftTitle.append(el('span', '反彈觀察', 'text-[9px] bg-purple-100 text-purple-800 font-bold px-1.5 py-0.2 rounded shrink-0'));
    top.append(leftTitle);

    const inWatch = existingSymbols.has(sym);
    if (inWatch) {
      top.append(el('span', '✓ 已在自選', 'text-[10px] text-slate-400 bg-slate-100 px-1.5 py-0.5 rounded shrink-0'));
    } else {
      const addBtn = el('button', '＋加入自選', 'text-[10px] font-semibold text-purple-600 hover:text-purple-800 bg-white hover:bg-purple-50 border border-purple-200 px-1.5 py-0.5 rounded shrink-0 transition');
      addBtn.addEventListener('click', async () => {
        await act({ type: 'ADD', stock: { symbol: sym, market: m, name, groups: ['watchlist'] } }, `已將 ${sym} ${name} 加入自選`);
      });
      top.append(addBtn);
    }
    card.append(top);

    // 價格與漲跌
    const priceRow = el('div', '', 'flex items-center justify-between');
    const leftPrice = el('div', '', 'flex items-baseline gap-2');
    leftPrice.append(el('strong', price > 0 ? `${price.toFixed(2)} 元` : '尚無報價', 'font-bold text-slate-900 text-sm'));
    priceRow.append(leftPrice);

    const rightPct = el('div', '', 'flex items-center gap-2');
    rightPct.append(el('span', pct, `text-xs font-bold ${pctColor}`));

    const chartBtn = el('a', '線圖 ↗', 'text-[11px] text-sky-700 cursor-pointer font-medium hover:underline shrink-0');
    chartBtn.href = chartURL({ symbol: sym, market: m });
    chartBtn.target = '_blank';
    chartBtn.rel = 'noopener noreferrer';
    chartBtn.addEventListener('click', e => {
      e.preventDefault();
      openChartWindow({ symbol: sym, market: m, name }, 'rebound');
    });
    rightPct.append(chartBtn);

    priceRow.append(rightPct);
    card.append(priceRow);

    // 反彈理由
    if (b.reason) {
      card.append(el('p', `🛡️ ${b.reason}`, 'text-[10px] text-purple-700 bg-purple-50/80 px-1.5 py-0.5 rounded truncate'));
    }

    list.append(card);
  }
}

function render() {
  $('market-status-dot').className = `h-2 w-2 rounded-full ${view.marketOpen && !view.error ? 'bg-emerald-500' : 'bg-slate-400'}`;
  $('market-status-dot').title = view.vm ? 'VM 隔離示例；不自動交易推播' : view.marketOpen ? '盤中排程；報價時間請看個股' : '休市／非盤中時段';
  for (const key of GROUPS) {
    if ($(`toggle-${key}`)) $(`toggle-${key}`).checked = view.settings[key];
  }
  if ($('toggle-all-daytrade')) $('toggle-all-daytrade').checked = view.settings?.allDaytradeAlerts !== false;
  if ($('toggle-all-rebound')) $('toggle-all-rebound').checked = view.settings?.allReboundAlerts !== false;
  applyStealthMode(view.settings?.stealthMode);

  // 摸魚排版與每頁筆數同步
  const pageSize = Number(view.settings?.pageSize) || 5;
  const cardDensity = view.settings?.cardDensity || 'compact';
  const isCompact = cardDensity === 'compact';

  if ($('range-page-size')) {
    $('range-page-size').value = pageSize;
    if ($('range-page-size-val')) $('range-page-size-val').textContent = String(pageSize);
  }
  if ($('radio-density-normal') && $('radio-density-compact')) {
    $('radio-density-normal').checked = !isCompact;
    $('radio-density-compact').checked = isCompact;
  }
  if ($('density-status-tag')) {
    $('density-status-tag').textContent = `一頁 ${pageSize} 筆 (${isCompact ? '緊湊' : '標準'})`;
  }

  // 條件式推播過濾
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

  // Tabs 切換高亮
  document.querySelectorAll('.tab-btn').forEach(b => {
    b.setAttribute('aria-selected', String(b.dataset.group === group));
    b.classList.toggle('tab-active', b.dataset.group === group);
  });

  renderTaiex();
  renderStrategyBar();

  const list = $('stock-list-container');
  list.replaceChildren();
  list.classList.toggle('density-compact', isCompact);

  if (group === 'ai_matrix') {
    renderAiMatrix(list);
    return;
  }
  if (group === 'daytrade') {
    renderDaytrade(list, isCompact);
    return;
  }
  if (group === 'rebound') {
    renderRebound(list, isCompact);
    return;
  }
  // 預設為 'watchlist' 自選看股
  renderWatchlist(list, isCompact);

  const stamp = view.updatedAt ? new Date(view.updatedAt).toLocaleTimeString('zh-TW', { timeZone: 'Asia/Taipei', hour12: false }) : '尚未更新';
  status(view.error || `${view.vm ? 'VM 隔離測試' : view.marketOpen ? '盤中' : '休市'} · ${stamp}`, !!view.error);

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
      const addBtn = el('button', '＋加入自選', 'text-[11px] font-medium text-sky-600 hover:text-sky-800 shrink-0 px-1.5 py-0.5 bg-sky-50 hover:bg-sky-100 rounded');
      addBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        box.classList.add('hidden');
        $('input-search').value = '';
        await act({ type: 'ADD', stock: { symbol: item.symbol, market: item.market, name: item.name, groups: ['watchlist'] } }, `已新增 ${item.symbol} ${item.name} 至自選`);
      });
      row.append(addBtn);
    }

    row.addEventListener('click', async () => {
      box.classList.add('hidden');
      $('input-search').value = '';
      if (!isAdded) {
        await act({ type: 'ADD', stock: { symbol: item.symbol, market: item.market, name: item.name, groups: ['watchlist'] } }, `已新增 ${item.symbol} ${item.name} 至自選`);
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
      groups: ['watchlist']
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

for (const strategy of ['daytrade', 'rebound']) {
  $(`toggle-${strategy}`)?.addEventListener('change', async e => {
    await act({ type: 'SETTINGS', strategy, enabled: e.target.checked }); if (view) render();
  });
  $(`btn-test-${strategy}-notif`)?.addEventListener('click', () => act({ type: 'TEST', strategy }, '測試通知已交給 Chrome；音效由 VM 系統設定決定'));
}

$('toggle-all-daytrade')?.addEventListener('change', async e => {
  await act({ type: 'SETTINGS', strategy: 'allDaytradeAlerts', enabled: e.target.checked }); if (view) render();
});
$('toggle-all-rebound')?.addEventListener('change', async e => {
  await act({ type: 'SETTINGS', strategy: 'allReboundAlerts', enabled: e.target.checked }); if (view) render();
});

// 摸魚排版與卡片自定義監聽
$('range-page-size')?.addEventListener('input', e => {
  if ($('range-page-size-val')) $('range-page-size-val').textContent = e.target.value;
});
$('range-page-size')?.addEventListener('change', async e => {
  const val = Number(e.target.value);
  await act({ type: 'SETTINGS', strategy: 'pageSize', value: val });
  if (view) {
    if (!view.settings) view.settings = {};
    view.settings.pageSize = val;
    render();
  }
});
$('radio-density-normal')?.addEventListener('change', async e => {
  if (e.target.checked) {
    await act({ type: 'SETTINGS', strategy: 'cardDensity', value: 'normal' });
    if (view) {
      if (!view.settings) view.settings = {};
      view.settings.cardDensity = 'normal';
      render();
    }
  }
});
$('radio-density-compact')?.addEventListener('change', async e => {
  if (e.target.checked) {
    await act({ type: 'SETTINGS', strategy: 'cardDensity', value: 'compact' });
    if (view) {
      if (!view.settings) view.settings = {};
      view.settings.cardDensity = 'compact';
      render();
    }
  }
});

// 條件式過濾監聽
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

// 自選名單備份與還原
$('btn-export-stocks').addEventListener('click', () => {
  if (!view) return;
  const blob = new Blob([JSON.stringify({ version: 1, stocks: view.stocks }, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob), link = document.createElement('a');
  link.href = url; link.download = 'easystock-watchlist.json'; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000); status('已匯出自選名單');
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
  if ((e.key === 'b' || e.key === 'B') && !['INPUT', 'TEXTAREA'].includes(document.activeElement?.tagName) && $('settings-panel')?.inert) {
    toggleStealthMode();
    return;
  }
  if (e.key === 'Escape') { drawer(false); }
  if (e.key !== 'Tab') return;
  const panel = !$('settings-panel').inert ? $('settings-panel') : null;
  if (!panel) return;
  const nodes = [...panel.querySelectorAll('button,input,a')].filter(x => !x.disabled && x.type !== 'file');
  const first = nodes[0], last = nodes.at(-1);
  if (e.shiftKey && document.activeElement === first) { last.focus(); e.preventDefault(); }
  if (!e.shiftKey && document.activeElement === last) { first.focus(); e.preventDefault(); }
});

icons();
$('settings-panel').inert = true;
await act({ type: 'SNAPSHOT', refresh: true });
