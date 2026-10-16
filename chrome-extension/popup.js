import { SYMBOL, GROUPS, finite, formatTaipeiQuoteTime, watchlist, chartURL, searchStocks, searchOnlineStocks, calcChangePct, formatTelegramEntry, formatTelegramExit, BROKERS, getBroker, sparklineSessionX, quoteStatus, quoteStampMs, sparkForQuote, taipei, migrateState, resolveStockInput } from './core.js';
import { icons } from './icons.js';

const $ = id => (typeof document !== 'undefined' && document ? document.getElementById(id) : null);
let view, group = 'watchlist';
let searchDebounce = null;
let toastTimer = null;
let feedbackTimer = null;
let currentWatchlistPage = 1;
let busy = 0;
// Rows shown immediately after "新增" while the background confirms the save.
const optimistic = new Map();
const inflight = new Map();

// Up / down / flat as CSS classes; the actual colors come from the colorMode theme (v2.css).
function tone(value) {
  return finite(value) && value > 0 ? 'es-up' : (finite(value) && value < 0 ? 'es-down' : 'es-flat');
}

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

// Time column: HH:MM for today's quotes, MM/DD for an earlier session, "資料過期" when stale.
function quoteTimeCell(q, qs, now = Date.now()) {
  if (qs.state === 'loading' || qs.state === 'unavailable') return '--:--';
  if (qs.state === 'stale') return '資料過期';
  const ms = quoteStampMs(q);
  if (!finite(ms)) return '--:--';
  const day = taipei(ms).date;
  if (day !== taipei(now).date) return `${day.slice(5, 7)}/${day.slice(8, 10)}`;
  return formatTaipeiQuoteTime(new Date(ms).toISOString());
}

function quoteTitle(q, qs) {
  const ms = quoteStampMs(q);
  const when = finite(ms) ? new Date(ms).toLocaleString('zh-TW', { timeZone: 'Asia/Taipei', hour12: false }) : '無來源時間';
  return `${qs.label}｜報價時間 ${when}（台北）${q?.source ? `｜來源 ${q.source}` : ''}`;
}

// 即時 In-App 彈窗通知 (雙重保險：即使 Windows 吃掉通知，小工具內也絕對能看見彈窗！)
function showInAppToast({ badgeText, badgeColor = 'bg-sky-500', titleText, bodyText, symbol = '', market = 'TW', name = '', strategy = '' }) {
  const toast = $('in-app-toast');
  if (!toast) return;
  clearTimeout(toastTimer);

  const bEl = $('toast-badge');
  const tEl = $('toast-title');
  const bodyEl = $('toast-body');
  const chartBtn = $('toast-chart-btn');

  if (bEl) {
    bEl.textContent = badgeText;
    bEl.className = `px-1.5 py-0.5 rounded text-[10px] font-bold text-white shrink-0 whitespace-nowrap ${badgeColor}`;
  }
  if (tEl) tEl.textContent = titleText;
  if (bodyEl) bodyEl.textContent = bodyText;

  if (chartBtn) {
    if (symbol) {
      chartBtn.style.display = 'inline-flex';
      chartBtn.onclick = () => {
        openChartWindow({ symbol, market, name: name || symbol }, strategy);
      };
    } else {
      chartBtn.style.display = 'none';
    }
  }

  toast.style.zIndex = '99999';
  toast.style.display = 'block';
  toast.classList.remove('hidden');
  toastTimer = setTimeout(() => {
    toast.classList.add('hidden');
    toast.style.display = 'none';
  }, 10000);
}

$('btn-close-toast')?.addEventListener('click', () => {
  const toast = $('in-app-toast');
  if (toast) {
    toast.classList.add('hidden');
    toast.style.display = 'none';
  }
  clearTimeout(toastTimer);
});

// 監聽後台發送的即時訊號廣播，即時在小工具頂部滑出彈窗
if (typeof chrome !== 'undefined' && chrome.runtime?.onMessage) {
  chrome.runtime.onMessage.addListener(msg => {
    if (msg?.type === 'LIVE_SIGNAL' && msg.signal) {
      const s = msg.signal;
      const isExit = s.action === 'SELL' || s.id?.startsWith('exit:');
      showInAppToast({
        badgeText: isExit ? '▼ 量減退守' : '▲ 量多進攻',
        badgeColor: isExit ? 'bg-emerald-600' : 'bg-sky-600',
        titleText: s.title || `${s.symbol} ${s.name || ''}`,
        bodyText: s.telegramText || `${s.symbol} ${s.name || ''} 現價 ${s.price} 元\n${s.reason || ''}`,
        symbol: s.symbol,
        market: s.market || 'TW',
        name: s.name || s.symbol,
        strategy: s.strategy || 'daytrade'
      });
    }
  });
}

function taiexTimeText(tInfo) {
  const ms = quoteStampMs(tInfo);
  if (finite(ms)) return new Date(ms).toLocaleTimeString('zh-TW', { timeZone: 'Asia/Taipei', hour12: false });
  return String(tInfo?.time || '').match(/\b\d{1,2}:\d{2}(?::\d{2})?\b/)?.[0] || '--:--:--';
}

function renderTaiex() {
  const tInfo = view?.taiex;
  const quality = view?.taiexQuality || null;
  const banner = $('taiex-banner');
  const timeEl = $('taiex-data-time');
  if (!tInfo || !finite(tInfo.price)) {
    $('taiex-price').textContent = '-';
    $('taiex-price').className = 'font-bold es-flat';
    $('taiex-change').textContent = quality?.status === 'UNAVAILABLE' && view?.marketOpen ? '暫無資料' : '-';
    $('otc-price').textContent = '-';
    $('otc-price').className = 'font-medium es-flat';
    $('otc-change').textContent = '-';
    if (timeEl) { timeEl.textContent = '資料時間 --:--:--'; timeEl.className = 'text-[9px] font-mono shrink-0 es-muted'; }
    if (banner) banner.className = 'flex items-center justify-between px-3 py-1.5 border-b border-slate-100 text-[11px] es-banner';
    return;
  }
  const isUp = tInfo.change > 0;
  const isDown = tInfo.change < 0;
  const arrow = isUp ? '▲ ' : (isDown ? '▼ ' : '');
  const sign = isUp ? '+' : '';
  const colorClass = tone(tInfo.change);

  // Index data quality: an old value stays visible but is never presented as live.
  const stale = quality?.status === 'STALE';
  if (timeEl) {
    timeEl.textContent = `${stale ? '資料過期 ' : (quality?.status === 'CLOSE' ? '收盤 ' : '資料時間 ')}${taiexTimeText(tInfo)}`;
    timeEl.className = `text-[9px] font-mono shrink-0 ${stale ? 'es-stale' : 'es-muted'}`;
    timeEl.title = [
      `來源 ${quality?.source || tInfo.source || 'TWSE_MIS'}`,
      quality?.age_seconds != null ? `資料年齡 ${quality.age_seconds} 秒` : '',
      quality?.lastError || ''
    ].filter(Boolean).join(' · ');
  }
  $('taiex-price').textContent = tInfo.price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  $('taiex-price').className = `font-bold ${colorClass}`;
  $('taiex-change').textContent = `${arrow}${sign}${tInfo.change.toFixed(2)} (${sign}${tInfo.change_pct.toFixed(2)}%)`;
  $('taiex-change').className = `font-semibold ${colorClass}`;

  if (finite(tInfo.otc_price)) {
    const otcUp = tInfo.otc_change > 0;
    const otcDown = tInfo.otc_change < 0;
    const oArrow = otcUp ? '▲ ' : (otcDown ? '▼ ' : '');
    const oSign = otcUp ? '+' : (otcDown ? '-' : '');
    const oColorClass = tone(tInfo.otc_change);
    const oPct = finite(tInfo.otc_change_pct) ? Math.abs(tInfo.otc_change_pct) : Math.abs(tInfo.otc_change);

    $('otc-price').textContent = tInfo.otc_price.toFixed(2);
    $('otc-price').className = `font-medium ${oColorClass}`;
    $('otc-change').textContent = `${oArrow}${oSign}${oPct.toFixed(2)}%`;
    $('otc-change').className = `font-medium ${oColorClass}`;
  }

  if (banner) {
    banner.className = `flex items-center justify-between px-3 py-1.5 border-b text-[11px] transition-colors cursor-pointer es-banner ${isUp ? 'es-banner-up' : (isDown ? 'es-banner-down' : '')}`;
    banner.title = '點擊查看 Yahoo 大盤加權指數即時走勢';
    banner.onclick = () => {
      chrome.tabs.create({ url: 'https://tw.stock.yahoo.com/quote/%5ETWII' });
    };
  }
}

async function send(message) {
  let response;
  try {
    response = await chrome.runtime.sendMessage(message);
  } catch (e) {
    // A suspended MV3 worker can miss the first message while it restarts; retry once.
    await new Promise(resolve => setTimeout(resolve, 150));
    response = await chrome.runtime.sendMessage(message);
  }
  if (!response?.ok) throw new Error(response?.error || '背景服務沒有回應，請重新載入擴充功能');
  return response.value;
}

const MARKET_FIELDS = ['quotes', 'quoteAttempts', 'pendingQuotes', 'live', 'taiex', 'taiexQuality', 'holidays', 'updatedAt', 'error', 'marketOpen', 'used'];
function withOptimistic(stocks) {
  const rows = [...(stocks || [])];
  for (const [symbol, row] of optimistic) if (!rows.some(x => x.symbol === symbol)) rows.push(row);
  return rows;
}
// Responses can arrive out of order. A snapshot taken before a newer state revision only
// contributes market data, so an older watchlist can never replace a just-added stock.
function applyResult(result) {
  if (!result || !Array.isArray(result.stocks)) return;
  if (view && (result.rev ?? 0) < (view.rev ?? 0)) {
    for (const key of MARKET_FIELDS) if (key in result) view[key] = result[key];
  } else {
    view = { ...result };
  }
  view.stocks = withOptimistic(view.stocks);
  render();
}

// Never silently drops a request (1.05 ignored clicks while any request was pending).
// Identical read requests share one in-flight promise; errors are shown, not thrown.
async function act(message, success = '') {
  const readKey = ['SNAPSHOT', 'BOOTSTRAP'].includes(message.type) ? JSON.stringify(message) : '';
  if (readKey && inflight.has(readKey)) return inflight.get(readKey);
  const task = (async () => {
    busy += 1; document.body.setAttribute('aria-busy', 'true');
    try {
      const result = await send(message);
      applyResult(result);
      if (success) status(success);
      return result;
    } catch (e) {
      status(e.message, true);
      return null;
    } finally {
      busy -= 1;
      if (!busy) document.body.removeAttribute('aria-busy');
    }
  })();
  if (readKey) {
    inflight.set(readKey, task);
    task.finally(() => inflight.delete(readKey));
  }
  return task;
}

function addFeedback(text, kind = 'ok') {
  const node = $('add-feedback');
  if (!node) { status(text, kind === 'error'); return; }
  clearTimeout(feedbackTimer);
  node.textContent = text;
  node.className = `add-feedback ${kind === 'error' ? 'es-error' : (kind === 'info' ? 'es-muted' : 'es-ok')}`;
  node.hidden = false;
  feedbackTimer = setTimeout(() => { node.hidden = true; node.textContent = ''; }, kind === 'error' ? 6000 : 3500);
}

// 黑暗 / 光明主題模式
function applyDarkMode(enabled) {
  document.body.classList.toggle('dark-mode', !!enabled);
  const tag = $('brand-tag');
  const btnLabel = $('theme-btn-label');
  const btnIcon = $('theme-btn-icon');
  const toggleCheckbox = $('toggle-dark-mode');
  if (toggleCheckbox) toggleCheckbox.checked = !!enabled;
  if ($('theme-light')) $('theme-light').checked = !enabled;
  if ($('theme-dark')) $('theme-dark').checked = !!enabled;
  if (tag) tag.textContent = APP_VERSION_TAG;
  if (btnIcon) btnIcon.textContent = enabled ? '☀' : '☾';
  if (btnLabel) btnLabel.textContent = enabled ? '白色' : '深色';
  $('btn-theme-toggle')?.setAttribute('aria-label', enabled ? '切換為白色主題' : '切換為深色主題');
}

const APP_VERSION_TAG = 'v2.0';
// Price colours are independent of the theme: red/green or monochrome, both keep ▲▼ and +/-.
function applyColorMode(mode) {
  const value = mode === 'mono' ? 'mono' : 'redgreen';
  document.body.classList.toggle('color-mono', value === 'mono');
  document.body.classList.toggle('color-redgreen', value !== 'mono');
  if ($('color-redgreen')) $('color-redgreen').checked = value !== 'mono';
  if ($('color-mono')) $('color-mono').checked = value === 'mono';
}

const SYNC_LABELS = { synced: '已同步', syncing: '同步中…', error: '同步失敗', offline: '離線，稍後補同步', reauth: '需要重新登入', blocked: '待設定', signed_out: '未登入', idle: '待同步' };
function renderAccount() {
  const acc = view?.account;
  const badge = $('sync-badge'), email = $('account-email'), meta = $('account-meta'), btn = $('btn-auth'), syncBtn = $('btn-sync-now');
  if (!badge || !btn) return;
  meta?.classList.remove('es-wrap');
  if (view?.vm) {
    badge.textContent = 'VM 不提供'; email.textContent = 'VM 隔離版不提供 Google 登入'; meta.textContent = '';
    btn.hidden = true; if (syncBtn) syncBtn.hidden = true; return;
  }
  if (!acc?.configured && !acc?.signedIn) {
    badge.textContent = '待設定'; badge.className = 'es-sync-badge es-stale';
    email.textContent = 'Google 登入尚未就緒（本機自選照常使用）';
    // Full sentence, wrapped (not truncated), so the reason is readable.
    meta.textContent = acc?.blockedMessage || (acc?.missing?.length ? `缺少 ${acc.missing.join('、')}` : '');
    meta.title = meta.textContent;
    meta.classList.add('es-wrap');
    btn.disabled = true; btn.textContent = '使用 Google 登入'; btn.hidden = false;
    if (syncBtn) syncBtn.hidden = true;
    return;
  }
  btn.disabled = false; btn.hidden = false;
  if (!acc.signedIn) {
    badge.textContent = '未登入'; badge.className = 'es-sync-badge es-muted';
    email.textContent = '未登入（自選股僅存在本機）';
    meta.textContent = '登入後可在不同電腦同步自選股、提醒與介面偏好';
    btn.textContent = '使用 Google 登入'; btn.setAttribute('aria-label', '使用 Google 帳號登入');
    btn.className = 'es-btn es-btn-primary';
    if (syncBtn) syncBtn.hidden = true;
    return;
  }
  const s = acc.sync || {};
  badge.textContent = SYNC_LABELS[s.status] || '待同步';
  badge.className = `es-sync-badge ${s.status === 'synced' ? 'es-ok' : (['error', 'reauth', 'blocked'].includes(s.status) ? 'es-error' : 'es-muted')}`;
  email.textContent = acc.email || acc.displayName || acc.uidShort;
  email.title = acc.email || '';
  const last = s.lastSyncAt ? new Date(s.lastSyncAt).toLocaleString('zh-TW', { timeZone: 'Asia/Taipei', hour12: false }) : '尚未同步';
  meta.textContent = [`最後同步 ${last}`, s.pending ? '有待上傳變更' : '', s.lastError || ''].filter(Boolean).join(' · ');
  meta.title = meta.textContent;
  btn.textContent = '登出'; btn.setAttribute('aria-label', '登出 Google 帳號'); btn.className = 'es-btn';
  if (syncBtn) syncBtn.hidden = false;
}

function openChartWindow(s, strategy = '') {
  const priceParam = (s.price && Number.isFinite(Number(s.price))) ? `&price=${encodeURIComponent(s.price)}` : '';
  const winUrl = chrome.runtime.getURL(`chart.html?symbol=${encodeURIComponent(s.symbol)}&market=${encodeURIComponent(s.market)}&name=${encodeURIComponent(s.name || s.symbol)}${priceParam}&strategy=${encodeURIComponent(strategy)}`);
  if (chrome.windows && typeof chrome.windows.create === 'function') {
    chrome.windows.create({ url: winUrl, type: 'popup', width: 960, height: 680, focused: true }).catch(() => {
      chrome.tabs.create({ url: winUrl });
    });
  } else {
    chrome.tabs.create({ url: winUrl });
  }
}

function openBrokerOrder(symbol, market = 'TW', name = '') {
  const brokerId = view?.settings?.preferredBroker || 'sinopac';
  const broker = getBroker(brokerId);
  const targetUrl = typeof broker.url === 'function' ? broker.url(symbol) : '';

  // 1. 自動複製股票代號至剪貼簿（雙重保險）
  try {
    if (navigator?.clipboard?.writeText) {
      navigator.clipboard.writeText(symbol).catch(() => {});
    }
  } catch (_) {}

  // 2. 開啟對應頁面（若有 URL 則開新分頁；純觀察無 URL 則不開新分頁）
  if (targetUrl) {
    if (typeof chrome !== 'undefined' && chrome.tabs?.create) {
      chrome.tabs.create({ url: targetUrl });
    } else {
      window.open(targetUrl, '_blank');
    }
  }

  // 3. 顯示即時 In-App 彈窗與狀態列提示（依模式區分提示文案）
  if (broker.id === 'observe') {
    showInAppToast({
      badgeText: `👀 純觀察模式`,
      badgeColor: 'bg-slate-700',
      titleText: `${symbol} ${name || ''} 觀察標的`,
      bodyText: `已為您自動複製股票代號「${symbol}」。（純觀察模式，不跳轉任何外部網頁）`,
      symbol,
      market,
      name: name || symbol
    });
    status(`已複製代號 ${symbol}（純觀察模式）`);
  } else if (broker.isObserve) {
    showInAppToast({
      badgeText: `${broker.icon || '📈'} ${broker.name}`,
      badgeColor: broker.badgeColor || 'bg-purple-700',
      titleText: `${symbol} ${name || ''} 看盤分析跳轉`,
      bodyText: `已為您自動複製股票代號「${symbol}」，並開啟 ${broker.name} 走勢分析頁面。`,
      symbol,
      market,
      name: name || symbol
    });
    status(`已複製代號 ${symbol} 並跳轉至 ${broker.name}`);
  } else {
    showInAppToast({
      badgeText: `${broker.icon || '🚀'} ${broker.name}`,
      badgeColor: broker.badgeColor || 'bg-red-600',
      titleText: `${symbol} ${name || ''} 前往券商官網`,
      bodyText: `已為您自動複製股票代號「${symbol}」，並為您開啟 ${broker.name}（${broker.appDesc || ''}）官方頁面。`,
      symbol,
      market,
      name: name || symbol
    });
    status(`已複製代號 ${symbol} 並跳轉至 ${broker.name}`);
  }
}

// 迷你走勢圖：只畫真實分時點（同一台北交易日、至少 2 點），沒有就顯示「—」，不再用 OHLC 捏造折線。
function createSparklineSvg(sparkPoints, trendClass) {
  const w = 56, h = 20;
  const rows = (Array.isArray(sparkPoints) ? sparkPoints : []).map(item => ({
    value: Number(item?.close),
    x: sparklineSessionX(item, w, 2)
  })).filter(row => finite(row.value) && finite(row.x));
  if (rows.length < 2) return null;
  const minVal = Math.min(...rows.map(row => row.value));
  const maxVal = Math.max(...rows.map(row => row.value));
  const span = Math.max(0.01, maxVal - minVal);
  const getY = val => Math.max(2, Math.min(h - 2, (h - 2) - ((val - minVal) / span) * (h - 6)));
  const pts = rows.map(row => ({ x: Number(row.x.toFixed(1)), y: Number(getY(row.value).toFixed(1)) }));
  const lastPt = pts.at(-1);
  const pathD = `M ${pts[0].x} ${pts[0].y} ` + pts.slice(1).map(p => `L ${p.x} ${p.y}`).join(' ');
  const areaD = `${pathD} L ${lastPt.x} ${h} L ${pts[0].x} ${h} Z`;
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', `0 0 ${w} ${h}`); svg.setAttribute('width', String(w)); svg.setAttribute('height', String(h));
  svg.setAttribute('class', `overflow-visible inline-block es-spark ${trendClass}`);
  svg.setAttribute('role', 'img'); svg.setAttribute('aria-label', '當日真實分時走勢');
  const area = document.createElementNS(ns, 'path'); area.setAttribute('d', areaD); area.setAttribute('class', 'es-spark-area');
  const path = document.createElementNS(ns, 'path'); path.setAttribute('d', pathD); path.setAttribute('class', 'es-spark-line'); path.setAttribute('fill', 'none'); path.setAttribute('stroke-width', '1.5'); path.setAttribute('stroke-linecap', 'round'); path.setAttribute('stroke-linejoin', 'round');
  const dot = document.createElementNS(ns, 'circle'); dot.setAttribute('cx', String(lastPt.x)); dot.setAttribute('cy', String(lastPt.y)); dot.setAttribute('r', '2'); dot.setAttribute('class', 'es-spark-dot');
  svg.append(area, path, dot); return svg;
}

// 動態列表高度設定 (真實改變整體視窗尺寸：同時設定 html, body 與 container，預設 500px 即 +20px，上限至 +100px 即 580px)
function applyWindowHeight(h) {
  const val = Math.max(380, Math.min(580, Number(h) || 500));
  if (document.documentElement) document.documentElement.style.height = `${val}px`;
  if (document.body) document.body.style.height = `${val}px`;
  const container = $('popup-container');
  if (container) {
    container.style.height = `${val}px`;
    container.style.minHeight = `${val}px`;
    container.style.maxHeight = `${val}px`;
  }
  const diff = val - 480;
  const tagText = diff === 0 ? '預設 (0px)' : (diff > 0 ? `+${diff}px` : `${diff}px`);
  if ($('window-height-val')) $('window-height-val').textContent = tagText;
  if ($('density-status-tag')) $('density-status-tag').textContent = tagText;
  if ($('range-window-height') && document.activeElement !== $('range-window-height')) {
    $('range-window-height').value = String(val);
  }
}

// 顯示文字大小設定 (Stitch 設計：小 / 標準 / 大，字重與字級從小到大階梯顯著清晰，支援膠囊按鈕與預覽列)
function applyFontSize(size) {
  let validSize = size;
  if (size === 'medium') validSize = 'standard';
  if (!['small', 'standard', 'large'].includes(validSize)) validSize = 'standard';
  
  // 全域套用字級模式 (body, popup-container, stock-list-container, settings-panel)
  const targets = [document.documentElement, document.body, $('popup-container'), $('stock-list-container'), $('settings-panel')].filter(Boolean);
  targets.forEach(el => {
    el.classList.remove('size-small', 'size-standard', 'size-medium', 'size-large');
    el.classList.add(`size-${validSize}`);
  });
  const preview = $('font-size-preview-box');
  const tag = $('preview-size-tag');
  if (tag) {
    tag.textContent = validSize === 'small' ? '小 (緊湊)' : (validSize === 'large' ? '大 (清晰)' : '標準 (推薦)');
  }
  if (preview) {
    const symSpan = preview.querySelector('.preview-sym');
    const nameSpan = preview.querySelector('.preview-name');
    const priceSpan = preview.querySelector('.preview-price');
    const chgSpan = preview.querySelector('.preview-chg');
    if (validSize === 'small') {
      if (symSpan) symSpan.className = 'preview-sym font-bold font-mono text-sky-600 text-[11px]';
      if (nameSpan) nameSpan.className = 'preview-name text-slate-700 font-medium text-[10px]';
      if (priceSpan) priceSpan.className = 'preview-price font-bold font-mono es-up text-[12px]';
      if (chgSpan) chgSpan.className = 'preview-chg font-mono font-semibold es-up es-chip-up text-[9.5px] border px-1 py-0.2 rounded';
    } else if (validSize === 'standard') {
      if (symSpan) symSpan.className = 'preview-sym font-bold font-mono text-sky-600 text-[12.5px]';
      if (nameSpan) nameSpan.className = 'preview-name text-slate-700 font-medium text-[11px]';
      if (priceSpan) priceSpan.className = 'preview-price font-bold font-mono es-up text-[13.5px]';
      if (chgSpan) chgSpan.className = 'preview-chg font-mono font-semibold es-up es-chip-up text-[10px] border px-1.5 py-0.5 rounded';
    } else if (validSize === 'large') {
      if (symSpan) symSpan.className = 'preview-sym font-bold font-mono text-sky-600 text-[14.5px]';
      if (nameSpan) nameSpan.className = 'preview-name text-slate-700 font-medium text-[12px]';
      if (priceSpan) priceSpan.className = 'preview-price font-bold font-mono es-up text-[15.5px]';
      if (chgSpan) chgSpan.className = 'preview-chg font-mono font-semibold es-up es-chip-up text-[11px] border px-1.5 py-0.5 rounded';
    }
  }
  ['small', 'standard', 'large'].forEach(s => {
    const radio = $(`radio-size-${s}`);
    const lbl = radio?.closest('.size-pill-label');
    if (lbl) {
      if (s === validSize) {
        lbl.classList.add('bg-white', 'text-sky-700', 'shadow-xs', 'font-bold');
        lbl.classList.remove('text-slate-600');
      } else {
        lbl.classList.remove('bg-white', 'text-sky-700', 'shadow-xs', 'font-bold');
        lbl.classList.add('text-slate-600');
      }
    }
  });
  if ($(`radio-size-${validSize}`)) $(`radio-size-${validSize}`).checked = true;
}

function renderAiMatrix(list) {
  const wrap = el('div', '', 'space-y-2.5 text-xs pb-2 p-3');

  const headerCard = el('div', '', 'p-3 bg-slate-900 text-white rounded-lg shadow-sm space-y-1');
  const badge = el('div', '', 'flex items-center justify-between');
  badge.append(el('span', 'EASYSTOCK QUANT ENGINE', 'text-[10px] font-mono tracking-wider text-sky-400 font-bold'));
  badge.append(el('span', 'v4.2 PROD', 'text-[9px] bg-slate-800 px-1.5 py-0.5 rounded text-slate-300 font-mono'));
  headerCard.append(badge);
  headerCard.append(el('h2', '架構', 'text-xs font-bold text-white'));
  headerCard.setAttribute('aria-label', '架構');
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
    <li><strong class="text-slate-800">風控邏輯：</strong>研究模型內建 -1.5% ~ -2.0% 的回撤上限，並於 13:15 前結束當日觀察；僅描述模型設計，非操作建議。</li>
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
    title = '量多進攻觀察清單';
    const pos = view.live?.open_positions;
    const closed = view.live?.closed_trades;
    const openTargets = (pos && typeof pos === 'object') ? Object.values(pos).filter(p => p?.status === 'OPEN') : [];
    const closedTargets = (closed && typeof closed === 'object') ? Object.values(closed).filter(Boolean) : [];
    const combined = openTargets.length ? openTargets : closedTargets;
    targets = combined.map(p => {
      const sym = String(p.symbol);
      const s = view.stocks.find(x => x.symbol === sym);
      const m = s?.market || ((sym.length === 4 && (sym.startsWith('5') || sym.startsWith('6') || sym.startsWith('8'))) ? 'TWO' : 'TW');
      return { symbol: sym, market: m, name: p.name || s?.name || sym, groups: ['watchlist'] };
    });
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
      const result = await act({ type: 'ADD_BATCH', stocks: missingTargets });
      group = 'watchlist';
      render();
      if (result) addFeedback(`已將 ${missingTargets.length} 檔加入自選`, 'ok');
    };
  }
}

// 渲染自選看股清單 (圖片2精緻表格列：個股 | 今價 | 漲跌 | 高 / 低 | 走勢 | 時間)
function renderWatchlist(list, isCompact, pageSize) {
  const allRows = view.stocks || [];
  if (!allRows.length) {
    list.append(el('p', '目前尚無自選股票，請於上方輸入代號或名稱新增。', 'text-xs text-slate-500 p-3'));
    return;
  }

  // 分頁邏輯
  const totalCount = allRows.length;
  const totalPages = Math.max(1, Math.ceil(totalCount / pageSize));
  if (currentWatchlistPage > totalPages) currentWatchlistPage = totalPages;
  if (currentWatchlistPage < 1) currentWatchlistPage = 1;

  const startIdx = (currentWatchlistPage - 1) * pageSize;
  const rows = allRows.slice(startIdx, startIdx + pageSize);
  const showSparkline = view.settings?.showSparkline !== false;
  const header = $('stock-table-header');
  if (header) {
    if (showSparkline) header.classList.remove('no-sparkline');
    else header.classList.add('no-sparkline');
  }

  const now = Date.now();
  const pendingSet = new Set(view.pendingQuotes || []);
  for (const s of rows) {
    const q = view.quotes?.[s.symbol];
    const neverTried = !view.quoteAttempts?.[s.symbol];
    const qs = quoteStatus(q, now, { holidays: view.holidays || [], pending: pendingSet.has(s.symbol) || optimistic.has(s.symbol) || neverTried });
    const validPrice = qs.state !== 'loading' && qs.state !== 'unavailable';
    const changePctVal = validPrice ? calcChangePct(q) : null;
    const validPct = finite(changePctVal);
    const isUp = validPct && changePctVal > 0;
    const isDown = validPct && changePctVal < 0;
    const arrow = isUp ? '▲ ' : (isDown ? '▼ ' : '');
    const pctPrefix = isUp ? '+' : (isDown ? '-' : '');
    const pct = validPct ? `${pctPrefix}${Math.abs(changePctVal).toFixed(2)}%` : '--';
    const pctColor = validPct ? tone(changePctVal) : 'es-muted';

    const card = el('article', '', `stock-row stock-card stock-table-grid ${showSparkline ? '' : 'no-sparkline'} quote-${qs.state}`);
    card.dataset.symbol = s.symbol;
    card.dataset.quoteState = qs.state;

    // 系統狀態提示標籤
    const activePos = view.live?.open_positions?.[s.symbol];

    // 欄位 1：個股 (代號可點開分時線圖 + 中文名稱)
    const col1 = el('div', '', 'text-left min-w-0 pr-1 flex flex-col justify-center');
    const symLink = el('a', s.symbol, 'stock-sym font-bold font-mono text-sky-600 hover:text-sky-700 hover:underline cursor-pointer block leading-tight');
    symLink.href = chartURL(s);
    symLink.title = `點擊查看 ${s.symbol} 分時走勢圖`;
    symLink.onclick = (e) => {
      e.preventDefault();
      openChartWindow(s, activePos ? 'daytrade' : '');
    };
    const nameRow = el('div', '', 'flex items-center gap-1 min-w-0');
    const nameSpan = el('span', s.name, 'stock-name text-slate-700 truncate font-medium leading-tight');
    nameRow.append(nameSpan);
    if (activePos && activePos.status === 'OPEN') {
      nameRow.append(el('span', '⚡', 'text-[9px] text-sky-600 shrink-0 font-bold'));
    }
    col1.append(symLink, nameRow);
    card.append(col1);

    // 欄位 2：今價 (等寬對齊、大字清晰)
    // Quote unavailable is not an add failure: the row stays, with a truthful status instead of a price.
    const col2 = el('div', '', `text-right font-mono font-bold stock-price pr-1 ${validPrice ? pctColor : 'es-muted quote-status-text'}`);
    col2.textContent = validPrice ? (q.price >= 1000 ? q.price.toLocaleString('en-US', { minimumFractionDigits: 1, maximumFractionDigits: 2 }) : q.price.toFixed(2)) : qs.label;
    card.append(col2);

    // 欄位 3：漲跌 (雙行：上為標準箭頭與點數，下為百分比)
    const col3 = el('div', '', 'text-right font-mono flex flex-col justify-center pr-1');
    const chgVal = finite(q?.change) ? Math.abs(q.change).toFixed(2) : (validPct && validPrice ? Math.abs(q.price * changePctVal / 100).toFixed(2) : '0.00');
    const chgSpan = el('span', validPct ? `${arrow}${chgVal}` : '--', `stock-sub font-bold leading-tight ${pctColor}`);
    const pctSpan = el('span', pct, `stock-sub font-semibold leading-tight ${pctColor}`);
    col3.append(chgSpan, pctSpan);
    card.append(col3);

    // 欄位 4：高 / 低 (雙行：上為最高價，下為最低價)
    const col4 = el('div', '', 'text-right font-mono flex flex-col justify-center pr-1');
    const highVal = validPrice && finite(q?.high) && q.high > 0 ? (q.high >= 1000 ? q.high.toFixed(1) : q.high.toFixed(2)) : '--';
    const lowVal = validPrice && finite(q?.low) && q.low > 0 ? (q.low >= 1000 ? q.low.toFixed(1) : q.low.toFixed(2)) : '--';
    const highSpan = el('span', highVal, 'stock-sub font-medium text-slate-700 leading-tight');
    const lowSpan = el('span', lowVal, 'stock-sub font-medium text-slate-500 leading-tight');
    col4.append(highSpan, lowSpan);
    card.append(col4);

    // 欄位 5：走勢 (迷你 SVG Sparkline，優先傳入真實 spark 陣列)
    const col5 = el('div', '', 'col-sparkline flex items-center justify-center');
    if (showSparkline) {
      const spark = validPrice ? createSparklineSvg(sparkForQuote(q), tone(changePctVal)) : null;
      if (spark) col5.append(spark);
      else {
        const none = el('span', '—', 'es-nospark es-muted');
        none.title = '暫無真實分時資料';
        col5.append(none);
      }
    }
    card.append(col5);

    // 欄位 6：時間 (平時顯示時間，Hover 時切換為紅色刪除按鈕，空間互斥絕不重疊)
    const col6 = el('div', '', 'text-right flex items-center justify-end relative pr-0.5');
    const timeSpan = el('span', quoteTimeCell(q, qs, now), `col-time-text stock-sub font-mono ${qs.state === 'stale' ? 'es-stale' : 'es-muted'}`);
    timeSpan.title = quoteTitle(q, qs);
    const delBtn = el('button', '×', 'btn-row-delete text-slate-400 hover:text-red-600 font-bold text-base px-1 leading-none cursor-pointer bg-slate-100 hover:bg-red-50 rounded');
    delBtn.title = `從自選刪除 ${s.symbol}`;
    delBtn.onclick = (e) => {
      e.stopPropagation();
      act({ type: 'DELETE', symbol: s.symbol }, `已刪除自選股票 ${s.symbol}`);
    };
    col6.append(timeSpan, delBtn);
    card.append(col6);

    list.append(card);
  }

  // 自選分頁控制列 (固定置於休市狀態列正上方，不再隨清單筆數飄移在中間)
  const paginationBar = $('watchlist-pagination-bar');
  if (paginationBar) {
    if (totalPages > 1) {
      paginationBar.classList.remove('hidden');
      const pageInfo = $('watchlist-page-info');
      if (pageInfo) pageInfo.textContent = `第 ${currentWatchlistPage} / ${totalPages} 頁 (共 ${totalCount} 檔)`;
      const prevBtn = $('btn-page-prev');
      const nextBtn = $('btn-page-next');
      if (prevBtn) {
        prevBtn.className = `px-2 py-0.5 rounded text-[11px] border border-slate-200 ${currentWatchlistPage > 1 ? 'hover:bg-slate-100 text-slate-700 cursor-pointer' : 'opacity-40 cursor-not-allowed'}`;
        prevBtn.disabled = currentWatchlistPage <= 1;
        prevBtn.onclick = () => { if (currentWatchlistPage > 1) { currentWatchlistPage--; render(); } };
      }
      if (nextBtn) {
        nextBtn.className = `px-2 py-0.5 rounded text-[11px] border border-slate-200 ${currentWatchlistPage < totalPages ? 'hover:bg-slate-100 text-slate-700 cursor-pointer' : 'opacity-40 cursor-not-allowed'}`;
        nextBtn.disabled = currentWatchlistPage >= totalPages;
        nextBtn.onclick = () => { if (currentWatchlistPage < totalPages) { currentWatchlistPage++; render(); } };
      }
    } else {
      paginationBar.classList.add('hidden');
    }
  }
}

// 渲染系統當沖持倉部位與平倉紀錄 (獨立策略區塊，同步 jimmyeyes.com/easystock 完整動態)
function renderDaytrade(list, isCompact) {
  const pos = view.live?.open_positions;
  const openPositions = pos && typeof pos === 'object' ? Object.values(pos).filter(p => p?.status === 'OPEN') : [];

  const closed = view.live?.closed_trades;
  const closedTrades = closed && typeof closed === 'object'
    ? Object.values(closed).filter(Boolean).sort((a, b) => (Date.parse(b.exit_time || '') || 0) - (Date.parse(a.exit_time || '') || 0))
    : [];

  if (!openPositions.length && !closedTrades.length) {
    const emptyBox = el('div', '', 'p-4 text-center space-y-1 bg-white border border-slate-200 rounded-lg');
    emptyBox.append(el('div', '🎯', 'text-2xl mb-1'));
    emptyBox.append(el('h3', '目前沒有量多進攻／量減退守觀察紀錄', 'text-xs font-bold text-slate-700'));
    emptyBox.append(el('p', '盤中量能觀察結果會自動同步；僅為行情描述，非買賣建議。', 'text-[11px] text-slate-400 leading-relaxed'));
    list.append(emptyBox);
    return;
  }

  const existingSymbols = new Set(view.stocks.map(x => x.symbol));
  const scanDate = view.live?.scan_date || '';
  const totalCount = openPositions.length + closedTrades.length;

  // 頂部狀態橫條
  const headerSummary = el('div', '', 'flex items-center justify-between text-[11px] text-slate-600 bg-slate-100/90 px-2.5 py-1.5 rounded-lg border border-slate-200');
  headerSummary.append(el('span', `📅 ${scanDate ? `交易日 ${scanDate}` : '量能觀察'} · 共 ${totalCount} 筆`, 'font-semibold text-slate-700'));
  headerSummary.append(el('span', openPositions.length ? `▲ 量多進攻 ${openPositions.length} 檔` : '今日觀察已結束', `text-[10px] font-bold ${openPositions.length ? 'text-sky-700' : 'text-slate-500'}`));
  list.append(headerSummary);

  // 1. 渲染持倉中部位 (OPEN)
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
    const pnlColor = tone(pnlPct);

    const card = el('article', '', `stock-card border border-sky-300 bg-sky-50/40 rounded-lg ${isCompact ? 'p-2' : 'p-3'} space-y-1.5 shadow-2xs`);

    // 標題列
    const top = el('div', '', 'flex items-center justify-between gap-1');
    const leftTitle = el('div', '', 'flex items-center gap-1.5 min-w-0');
    leftTitle.append(el('h2', `${sym} ${name}`, 'text-xs font-bold text-slate-900 truncate'));
    leftTitle.append(el('span', '▲ 量多進攻', 'text-[9px] bg-sky-600 text-white font-bold px-1.5 py-0.2 rounded shrink-0'));
    if (p.entry_score) {
      leftTitle.append(el('span', `分: ${p.entry_score}`, 'text-[9px] bg-sky-100 text-sky-800 px-1 py-0.2 rounded font-mono shrink-0'));
    }
    top.append(leftTitle);

    // 加入自選按鈕
    const inWatch = existingSymbols.has(sym);
    if (inWatch) {
      top.append(el('span', '✓ 已在自選', 'text-[10px] text-slate-400 bg-slate-100 px-1.5 py-0.5 rounded shrink-0'));
    } else {
      const addBtn = el('button', '＋加入自選', 'text-[10px] font-semibold text-sky-600 hover:text-sky-800 bg-white hover:bg-sky-50 border border-sky-200 px-1.5 py-0.5 rounded shrink-0 transition cursor-pointer');
      addBtn.addEventListener('click', async () => {
        await handleAddStock({ symbol: sym, market: m, name });
      });
      top.append(addBtn);
    }
    card.append(top);

    // 數據列：進場價、市價、損益
    const dataRow = el('div', '', 'flex items-center justify-between text-xs');
    const leftData = el('div', '', 'flex items-baseline gap-2');
    leftData.append(el('span', `起點 ${entryPrice.toFixed(2)}`, 'text-slate-500 text-[11px]'));
    leftData.append(el('strong', `現價 ${curPrice.toFixed(2)}`, 'font-bold text-slate-900'));
    dataRow.append(leftData);

    const rightData = el('div', '', 'flex items-center gap-2');
    rightData.append(el('span', `${sign}${pnlPct.toFixed(2)}%`, `font-bold ${pnlColor}`));

    const chartBtn = el('a', '線圖 ↗', 'text-[11px] text-sky-700 cursor-pointer font-medium hover:underline shrink-0');
    chartBtn.href = chartURL({ symbol: sym, market: m });
    chartBtn.target = '_blank';
    chartBtn.onclick = (e) => {
      e.preventDefault();
      openChartWindow({ symbol: sym, market: m, name }, 'daytrade');
    };
    rightData.append(chartBtn);

    const broker = getBroker(view.settings?.preferredBroker);
    const orderBtnText = broker.id === 'observe'
      ? '👀 觀察中'
      : (broker.isObserve ? `${broker.icon || '📈'} ${broker.shortName}看盤 ↗` : `${broker.shortName} 官網 ↗`);
    const orderBtnTitle = broker.id === 'observe'
      ? `點擊複製 ${sym}（純觀察模式，不跳轉網頁）`
      : (broker.isObserve ? `點擊複製 ${sym} 並前往 ${broker.name} 看盤` : `點擊複製 ${sym} 並前往 ${broker.name} 官網`);
    const orderBtn = el('button', orderBtnText, `btn-broker-order text-[11px] ${broker.badgeColor || 'bg-red-600'} hover:opacity-90 text-white font-bold px-2 py-0.5 rounded shadow-2xs transition cursor-pointer shrink-0`);
    orderBtn.title = orderBtnTitle;
    orderBtn.onclick = (e) => {
      e.preventDefault();
      openBrokerOrder(sym, m, name);
    };
    rightData.append(orderBtn);

    dataRow.append(rightData);
    card.append(dataRow);

    // 進場理由
    const reasons = Array.isArray(p.entry_reasons) ? p.entry_reasons.join(' · ') : (p.reason || '動能突破');
    if (reasons) {
      card.append(el('p', `💡 ${reasons}`, 'text-[10px] text-slate-500 truncate'));
    }

    list.append(card);
  }

  // 2. 渲染已平倉交易 (CLOSED)
  for (const c of closedTrades) {
    const sym = String(c.symbol);
    const s = view.stocks.find(x => x.symbol === sym);
    const m = s?.market || ((sym.length === 4 && (sym.startsWith('5') || sym.startsWith('6') || sym.startsWith('8'))) ? 'TWO' : 'TW');
    const name = c.name || s?.name || sym;

    const entryPrice = finite(c.entry_price) ? c.entry_price : (finite(c.signal_entry_price) ? c.signal_entry_price : 0);
    const exitPrice = finite(c.exit_price) ? c.exit_price : (finite(c.signal_exit_price) ? c.signal_exit_price : 0);
    const pnlPct = finite(c.pnl_pct) ? c.pnl_pct : (entryPrice > 0 ? ((exitPrice - entryPrice) / entryPrice) * 100 : 0);
    const isUp = pnlPct >= 0;
    const sign = isUp ? '+' : '';
    const pnlColor = tone(pnlPct);

    let exitTimeStr = '';
    if (c.exit_time) {
      const match = String(c.exit_time).match(/(\d{2}:\d{2})/);
      exitTimeStr = match ? match[1] : '';
    }

    const card = el('article', '', `stock-card border border-slate-200 bg-white hover:bg-slate-50/60 rounded-lg ${isCompact ? 'p-2' : 'p-3'} space-y-1.5 shadow-2xs transition`);

    // 標題列
    const top = el('div', '', 'flex items-center justify-between gap-1');
    const leftTitle = el('div', '', 'flex items-center gap-1.5 min-w-0');
    leftTitle.append(el('h2', `${sym} ${name}`, 'text-xs font-bold text-slate-900 truncate'));
    leftTitle.append(el('span', '▼ 量減退守', 'text-[9px] bg-slate-200 text-slate-700 font-semibold px-1.5 py-0.2 rounded shrink-0'));
    if (exitTimeStr) {
      leftTitle.append(el('span', `${exitTimeStr} 轉弱`, 'text-[9px] text-slate-400 font-mono shrink-0'));
    }
    top.append(leftTitle);

    // 加入自選按鈕
    const inWatch = existingSymbols.has(sym);
    if (inWatch) {
      top.append(el('span', '✓ 已在自選', 'text-[10px] text-slate-400 bg-slate-100 px-1.5 py-0.5 rounded shrink-0'));
    } else {
      const addBtn = el('button', '＋加入自選', 'text-[10px] font-semibold text-slate-600 hover:text-slate-800 bg-white hover:bg-slate-100 border border-slate-300 px-1.5 py-0.5 rounded shrink-0 transition cursor-pointer');
      addBtn.addEventListener('click', async () => {
        await handleAddStock({ symbol: sym, market: m, name });
      });
      top.append(addBtn);
    }
    card.append(top);

    // 數據列：進場價、出場價、已實現報酬率
    const dataRow = el('div', '', 'flex items-center justify-between text-xs');
    const leftData = el('div', '', 'flex items-baseline gap-2');
    leftData.append(el('span', `起點 ${entryPrice.toFixed(2)}`, 'text-slate-500 text-[11px]'));
    leftData.append(el('strong', `終點 ${exitPrice.toFixed(2)}`, 'font-bold text-slate-800'));
    dataRow.append(leftData);

    const rightData = el('div', '', 'flex items-center gap-2');
    rightData.append(el('span', `${sign}${pnlPct.toFixed(2)}%`, `font-bold ${pnlColor}`));

    const chartBtn = el('a', '線圖 ↗', 'text-[11px] text-sky-700 cursor-pointer font-medium hover:underline shrink-0');
    chartBtn.href = chartURL({ symbol: sym, market: m });
    chartBtn.target = '_blank';
    chartBtn.onclick = (e) => {
      e.preventDefault();
      openChartWindow({ symbol: sym, market: m, name }, 'daytrade');
    };
    rightData.append(chartBtn);

    const broker = getBroker(view.settings?.preferredBroker);
    const orderBtnText = broker.id === 'observe'
      ? '👀 已觀察'
      : (broker.isObserve ? `${broker.icon || '📈'} ${broker.shortName} ↗` : `${broker.icon || '🚀'} ${broker.shortName} ↗`);
    const orderBtn = el('button', orderBtnText, 'btn-broker-order text-[11px] bg-slate-700 hover:bg-slate-800 text-white font-semibold px-2 py-0.5 rounded shadow-2xs transition cursor-pointer shrink-0');
    orderBtn.title = broker.id === 'observe' ? `點擊複製 ${sym}（純觀察模式）` : `點擊複製 ${sym} 並前往 ${broker.name} 查看`;
    orderBtn.onclick = (e) => {
      e.preventDefault();
      openBrokerOrder(sym, m, name);
    };
    rightData.append(orderBtn);

    dataRow.append(rightData);
    card.append(dataRow);

    // 理由與平倉說明
    const reasons = Array.isArray(c.entry_reasons) ? c.entry_reasons[0] : (c.reason || '');
    const exitReason = c.exit_reason || '';
    if (reasons || exitReason) {
      const reasonRow = el('div', '', 'text-[10px] text-slate-500 space-y-0.5');
      if (reasons) reasonRow.append(el('p', `量多：${reasons}`, 'truncate'));
      if (exitReason) reasonRow.append(el('p', `量減：${exitReason}`, 'text-slate-400 truncate'));
      card.append(reasonRow);
    }

    list.append(card);
  }
}

function renderBrokerSelector() {
  const currentId = view?.settings?.preferredBroker || 'sinopac';
  const currentBroker = getBroker(currentId);

  const badge = $('current-broker-badge');
  if (badge) {
    badge.textContent = `${currentBroker.icon || '🚀'} ${currentBroker.name}`;
    badge.className = `text-[10px] px-2 py-0.5 rounded font-bold text-white shadow-2xs ${currentBroker.badgeColor || 'bg-red-600'}`;
  }

  const select = $('select-preferred-broker');
  if (select && select.value !== currentId) {
    select.value = currentId;
  }

  const hintText = $('broker-hint-text');
  if (hintText) {
    if (currentBroker.id === 'observe') {
      hintText.textContent = '【純觀察模式】：點擊卡片動作按鈕時僅自動複製股票代號至剪貼簿，絕不開啟任何外部網頁。';
    } else if (currentBroker.isObserve) {
      hintText.textContent = `【看盤分析】：點擊卡片將自動複製代號，並開啟 ${currentBroker.name}（${currentBroker.appDesc || ''}）行情走勢頁面。`;
    } else {
      hintText.textContent = `【券商官網】：點擊卡片將自動複製代號，並開啟 ${currentBroker.name}（${currentBroker.appDesc || ''}）官方頁面。`;
    }
  }
}

function render() {
  renderBrokerSelector();
  $('market-status-dot').className = `h-2 w-2 rounded-full ${view.marketOpen && !view.error ? 'bg-emerald-500' : 'bg-slate-400'}`;
  $('market-status-dot').title = view.vm ? 'VM 隔離示例；不自動交易推播' : view.marketOpen ? '盤中排程；報價時間請看個股' : '休市／非盤中時段';
  for (const key of GROUPS) {
    if ($(`toggle-${key}`)) $(`toggle-${key}`).checked = view.settings[key];
  }
  if ($('toggle-all-daytrade')) $('toggle-all-daytrade').checked = view.settings?.allDaytradeAlerts !== false;
  applyDarkMode(view.settings?.darkMode);
  applyColorMode(view.settings?.colorMode);
  renderAccount();

  // 視窗高度自定義 (比照截圖：預設 500px 即 +20px)
  const windowHeight = Number(view.settings?.windowHeight) || 500;
  applyWindowHeight(windowHeight);

  // 顯示大小自定義 (圖片1效果)
  const fontSize = view.settings?.fontSize || 'standard';
  applyFontSize(fontSize);

  // 列表走勢開關 (圖片1效果)
  const showSparkline = view.settings?.showSparkline !== false;
  if ($('toggle-sparkline')) $('toggle-sparkline').checked = showSparkline;

  // 顯示排版與每頁筆數同步
  const pageSize = Math.max(3, Math.min(10, Number(view.settings?.pageSize) || 5));
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

  // 常用下單券商同步
  if ($('select-preferred-broker')) {
    $('select-preferred-broker').value = view.settings?.preferredBroker || 'sinopac';
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
      $('filter-status-tag').className = `text-[10px] px-1.5 py-0.2 rounded font-medium ${isCustom ? 'text-amber-700 bg-amber-100' : 'text-sky-700 bg-sky-100'}`;
    }
  }

  // Tabs 切換高亮
  document.querySelectorAll('.tab-btn').forEach(b => {
    b.setAttribute('aria-selected', String(b.dataset.group === group));
    b.classList.toggle('tab-active', b.dataset.group === group);
  });

  renderTaiex();
  renderStrategyBar();

  // 表頭狀態控制 (圖片2排版)
  const header = $('stock-table-header');
  if (header) {
    header.classList.toggle('hidden', group === 'ai_matrix');
    header.classList.toggle('no-sparkline', !showSparkline);
  }

  const list = $('stock-list-container');
  list.replaceChildren();
  list.classList.toggle('density-compact', isCompact);

  const paginationBar = $('watchlist-pagination-bar');
  if (paginationBar) paginationBar.classList.add('hidden');

  if (group === 'ai_matrix') {
    renderAiMatrix(list);
    return;
  }
  if (group === 'daytrade') {
    renderDaytrade(list, isCompact);
    return;
  }
  // 預設為 'watchlist' 自選看股
  renderWatchlist(list, isCompact, pageSize);

  const stamp = view.updatedAt ? new Date(view.updatedAt).toLocaleTimeString('zh-TW', { timeZone: 'Asia/Taipei', hour12: false }) : '尚未更新';
  status(view.error || `${view.vm ? 'VM 隔離測試' : view.marketOpen ? '盤中' : '休市'} · ${stamp}`, !!view.error);
  // 2.0: quotes are fetched and persisted by the background worker only (no popup-memory-only
  // enrichment that vanished when the popup closed).
}

// 搜尋建議清單渲染：深色背景、鮮明高對比、點擊保證加入自選
function renderSuggestionItems(list) {
  const box = $('search-suggestions');
  if (!box || !view) return;
  box.replaceChildren();
  if (!list.length) {
    box.append(el('div', '查無相符股票', 'p-3 text-slate-400 text-center text-xs'));
    box.classList.remove('hidden');
    return;
  }
  box.classList.remove('hidden');
  for (const item of list) {
    const isAdded = view.stocks.some(x => x.symbol === item.symbol);
    const row = el('div', '', 'px-3 py-2 hover:bg-slate-800 flex items-center justify-between cursor-pointer border-b border-slate-800/80 last:border-0 transition');
    const left = el('div', '', 'flex items-center gap-2 min-w-0');
    left.append(el('span', item.symbol, 'font-bold text-sky-400 text-xs font-mono'));
    left.append(el('span', item.name, 'text-slate-100 font-semibold truncate text-xs'));
    left.append(el('span', item.market === 'TWO' ? '上櫃' : '上市', 'text-[10px] text-slate-400 bg-slate-800 px-1 py-0.2 rounded shrink-0'));
    row.append(left);

    if (isAdded) {
      row.append(el('span', '✓ 已在自選', 'text-[10px] text-slate-400 bg-slate-800 px-2 py-0.5 rounded font-medium shrink-0'));
    } else {
      const addBtn = el('button', '＋加入自選', 'text-[11px] font-bold text-white bg-sky-600 hover:bg-sky-500 px-2.5 py-1 rounded shadow-xs shrink-0 transition cursor-pointer');
      addBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        box.classList.add('hidden');
        $('input-search').value = '';
        await handleAddStock(item);
      });
      row.append(addBtn);
    }

    row.addEventListener('click', async () => {
      box.classList.add('hidden');
      $('input-search').value = '';
      await handleAddStock(item);
    });
    box.append(row);
  }
}

// 新增即生效：先顯示（本機確認中），背景寫入 chrome.storage.local 後確認；行情另外載入。
// 不跳確認視窗；重複顯示「已在自選」，錯誤以 inline 訊息呈現。
async function handleAddStock(item) {
  if (!view) return;
  const symbol = String(item?.symbol || '').trim().toUpperCase();
  if (!SYMBOL.test(symbol)) { addFeedback('股票代號格式不正確，例: 2330 或 00878', 'error'); return; }
  group = 'watchlist';
  if ((view.stocks || []).some(x => x.symbol === symbol)) {
    addFeedback(`${symbol} 已在自選`, 'info');
    render();
    return;
  }
  const row = { symbol, market: item.market === 'TWO' ? 'TWO' : 'TW', name: String(item.name || symbol).trim().slice(0, 60) || symbol, groups: ['watchlist'] };
  optimistic.set(symbol, row);
  view.stocks = [...(view.stocks || []), row];
  const pageSize = Math.max(3, Math.min(10, Number(view.settings?.pageSize) || 5));
  currentWatchlistPage = Math.ceil(view.stocks.length / pageSize);
  render();
  try {
    const result = await send({ type: 'ADD', stock: row });
    optimistic.delete(symbol);
    applyResult(result);
    addFeedback(result?.notice === 'DUPLICATE' ? `${symbol} 已在自選` : `已加入 ${symbol} ${row.name}`, result?.notice === 'DUPLICATE' ? 'info' : 'ok');
  } catch (err) {
    optimistic.delete(symbol);
    view.stocks = (view.stocks || []).filter(x => x !== row);
    render();
    addFeedback(`${symbol} 未加入：${err.message}`, 'error');
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
    const inputEl = $('input-search');
    if (!inputEl) return;
    const cur = inputEl.value.trim();
    if (cur !== q || !cur) return;
    const onlineList = await searchOnlineStocks(cur);
    if ($('input-search')?.value.trim() === cur) {
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

  // Only real Taiwan stocks: unknown codes (e.g. "1000") are rejected after an online check.
  const resolved = await resolveStockInput(input, view.quotes || {});
  if (resolved.status === 'notFound' || !resolved.stock || !SYMBOL.test(resolved.stock.symbol)) {
    addFeedback(resolved.status === 'unverified'
      ? '暫時無法查詢股票名稱，請輸入股票代號，例: 2330 或 00878'
      : `查無此台股：${input}`, 'error');
    return;
  }
  $('input-search').value = '';
  const { symbol, market, name } = resolved.stock;
  await handleAddStock({ symbol, market, name: name || symbol });
  if (resolved.status === 'unverified') addFeedback(`已加入 ${symbol}（目前無法連線驗證代號，行情載入後確認）`, 'info');
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

for (const strategy of ['daytrade']) {
  $(`toggle-${strategy}`)?.addEventListener('change', async e => {
    await act({ type: 'SETTINGS', strategy, enabled: e.target.checked }); if (view) render();
  });
}

// 系統推播測試按鈕：同時發送 Chrome 系統通知與觸發 In-App 即時彈窗
$('btn-test-daytrade-notif')?.addEventListener('click', async () => {
  const fakeEntry = {
    symbol: '2330', name: '台積電', market: 'TW', price: 1000, entry_price: 1000,
    entry_score: '0.88', entry_vwap: 996.5,
    entry_reasons: ['爆量突破五分K區間', '站穩VWAP之上', '微觀主力大單吸籌'],
    stop_price: 985.0, take_profit_price: 1030.0,
    strategy: 'daytrade', action: 'BUY', reason: '示例：爆量突破五分 K 區間'
  };
  const telegramText = formatTelegramEntry(fakeEntry);
  showInAppToast({
    badgeText: '▲ 量多進攻（範例）',
    badgeColor: 'bg-sky-600',
    titleText: '2330 台積電（範例通知）',
    bodyText: telegramText,
    symbol: '2330',
    market: 'TW',
    name: '台積電',
    strategy: 'daytrade'
  });
  await act({ type: 'TEST', strategy: 'daytrade' }, '已發送「量多進攻」範例通知');
});

$('btn-test-exit-notif')?.addEventListener('click', async () => {
  const fakeExit = {
    symbol: '2330', name: '台積電', market: 'TW', price: 1025, exit_price: 1025, entry_price: 1000,
    pnl_pct: 2.5, mfe_pct: 3.0, mae_pct: -0.5, duration_seconds: 1800, exit_reason: '範例：量能轉弱',
    strategy: 'daytrade', action: 'SELL'
  };
  const telegramText = formatTelegramExit(fakeExit);
  showInAppToast({
    badgeText: '▼ 量減退守（範例）',
    badgeColor: 'bg-emerald-600',
    titleText: '2330 台積電（範例通知）',
    bodyText: telegramText,
    symbol: '2330',
    market: 'TW',
    name: '台積電',
    strategy: 'daytrade'
  });
  await act({ type: 'TEST', action: 'SELL' }, '已發送「量減退守」範例通知');
});

$('toggle-all-daytrade')?.addEventListener('change', async e => {
  await act({ type: 'SETTINGS', strategy: 'allDaytradeAlerts', enabled: e.target.checked }); if (view) render();
});

// 視窗高度滑桿監聽 (圖片1效果：即時拉動調整 body 高度與儲存)
$('range-window-height')?.addEventListener('input', e => {
  const val = Number(e.target.value);
  if (view?.settings) view.settings.windowHeight = val;
  applyWindowHeight(val);
});
$('range-window-height')?.addEventListener('change', async e => {
  const val = Number(e.target.value);
  if (view?.settings) view.settings.windowHeight = val;
  applyWindowHeight(val);
  await act({ type: 'SETTINGS', strategy: 'windowHeight', value: val });
  if (view?.settings) view.settings.windowHeight = val;
  applyWindowHeight(val);
});

// 顯示大小單選監聽 (小 / 標準 / 大 + 預覽)
for (const size of ['small', 'standard', 'large']) {
  $(`radio-size-${size}`)?.addEventListener('change', async e => {
    if (e.target.checked) {
      if (view?.settings) view.settings.fontSize = size;
      applyFontSize(size);
      await act({ type: 'SETTINGS', strategy: 'fontSize', value: size });
      if (view?.settings) view.settings.fontSize = size;
      applyFontSize(size);
    }
  });
}

// 列表走勢圖開關監聽 (圖片1效果)
$('toggle-sparkline')?.addEventListener('change', async e => {
  const enabled = e.target.checked;
  if (view?.settings) view.settings.showSparkline = enabled;
  await act({ type: 'SETTINGS', strategy: 'showSparkline', enabled });
  if (view?.settings) view.settings.showSparkline = enabled;
  render();
});

// 顯示排版與卡片自定義監聽 (拉動滑桿即時反應)
$('range-page-size')?.addEventListener('input', e => {
  const val = Number(e.target.value);
  if ($('range-page-size-val')) $('range-page-size-val').textContent = String(val);
  if (view) {
    if (!view.settings) view.settings = {};
    view.settings.pageSize = val;
    render();
  }
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

// 常用下單券商監聽
$('select-preferred-broker')?.addEventListener('change', async e => {
  const brokerId = e.target.value;
  if (view?.settings) view.settings.preferredBroker = brokerId;
  await act({ type: 'SETTINGS', strategy: 'preferredBroker', value: brokerId });
  if (view?.settings) view.settings.preferredBroker = brokerId;
  render();
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
  showInAppToast({
    badgeText: '⚙️ 設定已保存',
    badgeColor: 'bg-slate-700',
    titleText: '條件過濾設定',
    bodyText: `價格區間：${minP ?? '無'} ~ ${maxP ?? '無'} 元\n漲幅門檻：${minPct ? minPct + '%' : '全開'}`
  });
});

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
    currentWatchlistPage = 1;
    group = 'watchlist';
    render();
  } catch (err) { status(err.message, true); }
});

async function toggleDarkMode() {
  if (!view) return;
  const current = !!view.settings?.darkMode;
  const next = !current;
  await act({ type: 'SETTINGS', strategy: 'darkMode', enabled: next });
  if (view) {
    if (!view.settings) view.settings = {};
    view.settings.darkMode = next;
    applyDarkMode(next);
  }
  status(next ? '已切換為深色主題' : '已切換為白色主題');
}
$('btn-theme-toggle')?.addEventListener('click', toggleDarkMode);
async function setTheme(dark) {
  if (!view) return;
  applyDarkMode(dark);
  await act({ type: 'SETTINGS', strategy: 'darkMode', enabled: dark });
  if (view?.settings) view.settings.darkMode = dark;
  applyDarkMode(dark);
  status(dark ? '已切換為深色主題' : '已切換為白色主題');
}
$('theme-light')?.addEventListener('change', e => { if (e.target.checked) void setTheme(false); });
$('theme-dark')?.addEventListener('change', e => { if (e.target.checked) void setTheme(true); });
$('toggle-dark-mode')?.addEventListener('change', e => { void setTheme(e.target.checked); });
async function setColorMode(mode) {
  if (!view) return;
  applyColorMode(mode);
  await act({ type: 'SETTINGS', strategy: 'colorMode', value: mode });
  if (view?.settings) view.settings.colorMode = mode;
  render();
  status(mode === 'mono' ? '漲跌配色：黑白（低調）' : '漲跌配色：紅綠');
}
$('color-redgreen')?.addEventListener('change', e => { if (e.target.checked) void setColorMode('redgreen'); });
$('color-mono')?.addEventListener('change', e => { if (e.target.checked) void setColorMode('mono'); });

// Google 帳號：登入／登出／立即同步。登入失敗或取消不影響本機自選。
$('btn-auth')?.addEventListener('click', async () => {
  if (!view?.account) return;
  const btn = $('btn-auth');
  btn.disabled = true;
  try {
    if (view.account.signedIn) {
      const result = await send({ type: 'AUTH_SIGN_OUT' });
      applyResult(result);
      status('已登出；雲端資料保留，本機自選照常可用');
    } else {
      btn.textContent = '登入中…';
      const result = await send({ type: 'AUTH_SIGN_IN' });
      applyResult(result);
      status(result?.syncResult?.ok ? '已登入並完成同步' : `已登入；${result?.syncResult?.message || '同步稍後重試'}`, !result?.syncResult?.ok);
    }
  } catch (e) {
    status(e.message, true);
  } finally {
    btn.disabled = false;
    renderAccount();
  }
});
$('btn-sync-now')?.addEventListener('click', async () => {
  try {
    const result = await send({ type: 'SYNC_NOW' });
    applyResult(result);
    status(result?.syncResult?.ok ? '同步完成' : (result?.syncResult?.message || '同步失敗，稍後自動重試'), !result?.syncResult?.ok);
  } catch (e) { status(e.message, true); }
});

document.addEventListener('keydown', e => {
  if ((e.key === 'd' || e.key === 'D') && !['INPUT', 'TEXTAREA'].includes(document.activeElement?.tagName) && $('settings-panel')?.inert) {
    toggleDarkMode();
    return;
  }
  if (e.key === 'Escape') {
    if (!$('in-app-toast')?.classList.contains('hidden')) {
      $('in-app-toast').classList.add('hidden');
      return;
    }
    drawer(false);
  }
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

// Render saved theme/layout and cached market data immediately, then refresh in the background.
try {
  const saved = await chrome.storage.local.get('state');
  // Same rules as the worker: new installs light, saved (incl. 1.05) preferences kept.
  const settings = migrateState(saved?.state).settings;
  applyDarkMode(settings.darkMode === true);
  applyColorMode(settings.colorMode);
  applyWindowHeight(Number(settings.windowHeight) || 500);
} catch (_) {
  applyDarkMode(false);
  applyColorMode('redgreen');
  applyWindowHeight(500);
}
// Background pushes: a new stock's quote arrived, or a guessed market/name was corrected.
if (typeof chrome !== 'undefined' && chrome.runtime?.onMessage) {
  chrome.runtime.onMessage.addListener(msg => {
    if (msg?.type === 'QUOTES_UPDATED' || msg?.type === 'STATE_UPDATED') void act({ type: 'BOOTSTRAP' });
  });
}

await act({ type: 'BOOTSTRAP' });
void act({ type: 'SNAPSHOT', refresh: true });

// Index data is intentionally refreshed more often than the broad five-minute feed, and is not
// blocked by other in-flight requests (identical requests are de-duplicated instead).
const taiexRefreshTimer = setInterval(() => {
  if (view?.marketOpen) void act({ type: 'SNAPSHOT', taiexOnly: true });
}, 30000);
window.addEventListener('unload', () => clearInterval(taiexRefreshTimer));
