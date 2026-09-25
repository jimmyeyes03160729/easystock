import { VM_MODE, FIREBASE_ROOT } from './environment.js';
import { chartURL, finite } from './core.js';

const params = new URLSearchParams(window.location.search);
const symbol = (params.get('symbol') || '2330').toUpperCase();
const market = (params.get('market') || 'TW').toUpperCase();
let stockName = params.get('name') || symbol;
const strategyType = params.get('strategy') || '';
const initPrice = parseFloat(params.get('price'));

const canvas = document.getElementById('kline-canvas');
const ctx = canvas.getContext('2d');
const wrap = document.getElementById('chart-wrap');
const loadingMask = document.getElementById('loading-mask');

let currentMode = 'intraday'; // 'intraday' (當日分時 1分K) 或 'daily' (歷史日K)
let intradayData = [];
let dailyData = [];
let previousClose = null;
let currentStockInfo = {
  price: (finite(initPrice) && initPrice > 0) ? initPrice : 0,
  change_pct: 0,
  vwap: null,
  reason: ''
};
if (currentStockInfo.price > 0 && document.getElementById('txt-price')) {
  document.getElementById('txt-price').textContent = currentStockInfo.price.toFixed(2);
}

// 視野與拖曳縮放狀態
let viewBarsCount = 80;
let viewOffset = 0; // 0 表示停留在最新資料，> 0 表示向左平移查看歷史
let isDragging = false;
let dragStartX = 0;
let dragStartOffset = 0;
let hoverIndex = -1;
let autoRefreshTimer = null;

// 初始化頂部資訊
document.getElementById('txt-symbol').textContent = symbol;
document.getElementById('txt-name').textContent = stockName;
document.getElementById('badge-market').textContent = market === 'TWO' ? '上櫃' : '上市';
if (strategyType) {
  const stBadge = document.getElementById('badge-strategy');
  stBadge.textContent = strategyType === 'daytrade' ? '當沖策略' : (strategyType === 'rebound' ? '觸底反彈' : strategyType);
  stBadge.style.display = 'inline-block';
} else {
  document.getElementById('badge-strategy').style.display = 'none';
}

const yahooBtn = document.getElementById('btn-yahoo');
yahooBtn.href = chartURL({ symbol, market });

// 模式切換按鈕監聽
const tabIntraday = document.getElementById('tab-intraday');
const tabDaily = document.getElementById('tab-daily');

tabIntraday.addEventListener('click', () => {
  if (currentMode === 'intraday') return;
  currentMode = 'intraday';
  tabIntraday.classList.add('active');
  tabDaily.classList.remove('active');
  viewBarsCount = 120;
  viewOffset = 0;
  hoverIndex = -1;
  loadData();
});

tabDaily.addEventListener('click', () => {
  if (currentMode === 'daily') return;
  currentMode = 'daily';
  tabDaily.classList.add('active');
  tabIntraday.classList.remove('active');
  viewBarsCount = 60;
  viewOffset = 0;
  hoverIndex = -1;
  loadData();
});

document.getElementById('btn-refresh').addEventListener('click', () => loadData(true));

// 計算均線 MA
function calculateMA(bars, period) {
  const result = [];
  for (let i = 0; i < bars.length; i++) {
    if (i < period - 1) {
      result.push(null);
    } else {
      let sum = 0;
      for (let j = 0; j < period; j++) sum += bars[i - j].close;
      result.push(sum / period);
    }
  }
  return result;
}

// 產生模擬當日 1分K 分時資料 (僅在無網路或離線時 fallback，底價嚴格採用個股真實現價)
function generateMockIntraday(base = (currentStockInfo.price > 0 ? currentStockInfo.price : 50)) {
  const list = [];
  let cur = base;
  if (!previousClose || previousClose <= 0) {
    previousClose = Math.round((base * 0.99) * 100) / 100;
  }
  let cumAmount = 0;
  let cumVol = 0;
  const startMinute = 9 * 60; // 09:00
  const endMinute = 13 * 60 + 30; // 13:30

  for (let m = startMinute; m <= endMinute; m++) {
    const hh = String(Math.floor(m / 60)).padStart(2, '0');
    const mm = String(m % 60).padStart(2, '0');
    const change = (Math.random() - 0.48) * (base * 0.003);
    cur = Math.round((cur + change) * 100) / 100;
    const vol = Math.floor(20 + Math.random() * 150);
    cumAmount += cur * vol;
    cumVol += vol;
    const vwap = Math.round((cumAmount / cumVol) * 100) / 100;

    list.push({
      time: `${hh}:${mm}`,
      open: cur,
      high: Math.round((cur + Math.random() * 0.5) * 100) / 100,
      low: Math.round((cur - Math.random() * 0.5) * 100) / 100,
      close: cur,
      volume: vol,
      vwap
    });
  }
  return list;
}

// 產生模擬歷史日K資料 (底價嚴格採用個股真實現價)
function generateMockDaily(basePrice = (currentStockInfo.price > 0 ? currentStockInfo.price : 50)) {
  const bars = [];
  let cur = basePrice;
  const now = new Date();
  for (let i = 90; i >= 0; i--) {
    const d = new Date(now.getTime() - i * 86400000);
    if (d.getDay() === 0 || d.getDay() === 6) continue;
    const change = (Math.random() - 0.48) * (cur * 0.03);
    const open = Math.round((cur + (Math.random() - 0.5) * 2) * 100) / 100;
    const close = Math.round((cur + change) * 100) / 100;
    const high = Math.round((Math.max(open, close) + Math.random() * 2) * 100) / 100;
    const low = Math.round((Math.min(open, close) - Math.random() * 2) * 100) / 100;
    const vol = Math.floor(1000 + Math.random() * 15000);
    const timeStr = d.toISOString().slice(0, 10);
    bars.push({ time: timeStr, open, high, low, close, volume: vol });
    cur = close;
  }
  return bars;
}

// 抓取 Yahoo 當日 1分K 走勢 API (直接調用備用路徑)
async function fetchYahooIntradayDirect() {
  const ySym = market === 'TWO' ? `${symbol}.TWO` : `${symbol}.TW`;
  const url = `https://query1.finance.yahoo.com/v8/finance/chart/${ySym}?interval=1m&range=1d`;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 6000);
  try {
    const res = await fetch(url, { signal: controller.signal, cache: 'no-store' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const json = await res.json();
    const result = json?.chart?.result?.[0];
    if (!result) throw new Error('查無當日分時數據');

    const meta = result.meta;
    const prevClose = finite(meta?.previousClose) ? meta.previousClose : (finite(meta?.chartPreviousClose) ? meta.chartPreviousClose : null);
    const regularPrice = finite(meta?.regularMarketPrice) ? meta.regularMarketPrice : null;

    const timestamps = result.timestamp;
    const quotes = result.indicators?.quote?.[0];
    if (!Array.isArray(timestamps) || !quotes) throw new Error('分時數據格式不符');

    const bars = [];
    let cumAmount = 0;
    let cumVol = 0;
    let lastValidPrice = prevClose || regularPrice || 0;

    for (let i = 0; i < timestamps.length; i++) {
      const ts = timestamps[i];
      let o = quotes.open?.[i];
      let h = quotes.high?.[i];
      let l = quotes.low?.[i];
      let c = quotes.close?.[i];
      let v = quotes.volume?.[i] || 0;

      if (!finite(c)) {
        if (!finite(lastValidPrice) || lastValidPrice <= 0) continue;
        c = lastValidPrice;
        o = c; h = c; l = c;
      } else {
        lastValidPrice = c;
      }
      if (!finite(o)) o = c;
      if (!finite(h)) h = Math.max(o, c);
      if (!finite(l)) l = Math.min(o, c);

      cumAmount += c * v;
      cumVol += v;
      const vwap = cumVol > 0 ? cumAmount / cumVol : c;

      const d = new Date(ts * 1000);
      const timeStr = d.toLocaleTimeString('zh-TW', { timeZone: 'Asia/Taipei', hour: '2-digit', minute: '2-digit', hour12: false });

      bars.push({
        time: timeStr,
        open: Number(o),
        high: Number(h),
        low: Number(l),
        close: Number(c),
        volume: Number(v),
        vwap: Number(vwap)
      });
    }

    return {
      bars,
      previousClose: prevClose || (bars[0] ? bars[0].open : regularPrice),
      price: regularPrice || (bars.at(-1)?.close ?? null)
    };
  } finally {
    clearTimeout(timer);
  }
}

// 載入資料
async function loadData(force = false) {
  loadingMask.classList.remove('hidden');
  document.getElementById('txt-status-desc').textContent = '資料載入中…';

  try {
    if (VM_MODE) {
      const base = currentStockInfo.price > 0 ? currentStockInfo.price : 50;
      if (currentMode === 'intraday') {
        intradayData = generateMockIntraday(base);
        currentStockInfo = { price: base, change_pct: 1.25, vwap: base * 0.996, reason: 'VM 隔離示例數據' };
      } else {
        dailyData = generateMockDaily(base);
        currentStockInfo = { price: base, change_pct: 1.25, vwap: null, reason: 'VM 隔離示例歷史日K' };
      }
      renderInfo();
      draw();
      document.getElementById('txt-status-desc').textContent = '狀態：VM 示例離線資料';
      return;
    }

    // 當前為當日分時模式
    if (currentMode === 'intraday') {
      let fetched = null;
      // 優先向具有完整 host_permissions 的 Service Worker 請求分時走勢，避免頁面受到 CORS 限制
      if (typeof chrome !== 'undefined' && chrome.runtime?.sendMessage) {
        try {
          const resp = await chrome.runtime.sendMessage({ type: 'FETCH_INTRADAY', symbol, market });
          if (resp?.ok && resp.value) fetched = resp.value;
        } catch (_) {}
      }
      if (!fetched || !fetched.bars || !fetched.bars.length) {
        try {
          fetched = await fetchYahooIntradayDirect();
        } catch (_) {}
      }

      if (fetched && Array.isArray(fetched.bars) && fetched.bars.length > 0) {
        intradayData = fetched.bars;
        if (finite(fetched.previousClose) && fetched.previousClose > 0) {
          previousClose = fetched.previousClose;
        }
        if (finite(fetched.price) && fetched.price > 0) {
          currentStockInfo.price = fetched.price;
        } else if (intradayData.length > 0) {
          currentStockInfo.price = intradayData.at(-1).close;
        }
        if (previousClose && previousClose > 0 && currentStockInfo.price > 0) {
          currentStockInfo.change_pct = ((currentStockInfo.price - previousClose) / previousClose) * 100;
        }
        currentStockInfo.vwap = intradayData.at(-1)?.vwap || null;
      } else {
        // 若完全無法取得分時 K 線，使用個股真實現價生成適應性走勢，絕對不使用硬編碼 1000 元
        const realBase = (fetched?.price && fetched.price > 0) ? fetched.price :
                         (currentStockInfo.price > 0 ? currentStockInfo.price : (previousClose > 0 ? previousClose : 50));
        intradayData = generateMockIntraday(realBase);
        currentStockInfo.price = realBase;
        if (previousClose && previousClose > 0) {
          currentStockInfo.change_pct = ((realBase - previousClose) / previousClose) * 100;
        }
      }
    } else {
      // 當前為歷史日K模式
      let bars = null;
      try {
        const klineRes = await fetch(`${FIREBASE_ROOT}/kline/${encodeURIComponent(symbol)}.json`).catch(() => null);
        if (klineRes && klineRes.ok) bars = await klineRes.json();
      } catch (_) {}

      if (!Array.isArray(bars) || !bars.length) {
        try {
          const activeRes = await fetch(`${FIREBASE_ROOT}/active_release.json`);
          const releaseId = await activeRes.json();
          if (releaseId) {
            const relKlineRes = await fetch(`${FIREBASE_ROOT}/releases/${releaseId}/kline/${encodeURIComponent(symbol)}.json`);
            if (relKlineRes.ok) bars = await relKlineRes.json();
          }
        } catch (_) {}
      }

      if (Array.isArray(bars) && bars.length) {
        dailyData = bars.map(b => ({
          time: b.time || b.date,
          open: Number(b.open),
          high: Number(b.high),
          low: Number(b.low),
          close: Number(b.close),
          volume: Number(b.volume || b.amount || 0)
        })).filter(b => finite(b.open) && finite(b.close) && b.time);
      } else {
        const realBase = currentStockInfo.price > 0 ? currentStockInfo.price : (previousClose > 0 ? previousClose : 50);
        dailyData = generateMockDaily(realBase);
      }

      if (dailyData.length > 0) {
        const last = dailyData.at(-1);
        const prev = dailyData.at(-2);
        currentStockInfo.price = last.close;
        currentStockInfo.change_pct = (prev && prev.close > 0) ? ((last.close - prev.close) / prev.close) * 100 : 0;
      }
    }

    // 檢查當沖/反彈即時持倉資訊
    try {
      const liveRes = await fetch(`${FIREBASE_ROOT}/intraday_live.json`).catch(() => null);
      if (liveRes && liveRes.ok) {
        const live = await liveRes.json();
        const openPos = live?.open_positions?.[symbol];
        if (openPos && openPos.status === 'OPEN') {
          currentStockInfo.reason = Array.isArray(openPos.entry_reasons) ? openPos.entry_reasons.join('、') : (openPos.reason || '當沖進場持倉中');
          if (openPos.name) stockName = openPos.name;
        }
      }
    } catch (_) {}

    renderInfo();
    draw();
    document.getElementById('txt-status-desc').textContent = `更新時間：${new Date().toLocaleTimeString('zh-TW', { hour12: false })}`;
  } catch (err) {
    document.getElementById('txt-status-desc').textContent = `連線提示：${err.message || '暫存中'}`;
    draw();
  } finally {
    loadingMask.classList.add('hidden');
  }
}

function renderInfo() {
  document.getElementById('txt-name').textContent = stockName;
  const pEl = document.getElementById('txt-price');
  const dEl = document.getElementById('txt-diff');
  const p = currentStockInfo.price;
  const pct = currentStockInfo.change_pct;

  pEl.textContent = finite(p) ? p.toFixed(2) : '--';
  const sign = pct > 0 ? '+' : '';
  dEl.textContent = finite(pct) ? `${sign}${pct.toFixed(2)}%` : '--';

  const cls = pct > 0 ? 'market-up' : (pct < 0 ? 'market-down' : 'market-flat');
  pEl.className = `price-main ${cls}`;
  dEl.className = `price-diff ${cls}`;

  const noteEl = document.getElementById('txt-signal-note');
  let note = currentStockInfo.reason ? `訊號：${currentStockInfo.reason}` : '';
  if (currentStockInfo.vwap) note += ` ｜ VWAP: ${Number(currentStockInfo.vwap).toFixed(2)}`;
  noteEl.textContent = note;

  // 更新圖例標籤
  const legend = document.getElementById('chart-legend');
  if (currentMode === 'intraday') {
    legend.innerHTML = `
      <span class="legend-item"><span class="dot dot-vwap"></span>VWAP 均價: <span id="m-vwap" class="metric-val">--</span></span>
      <span class="legend-item" style="color:#64748b">--- 昨收: <span id="m-prev" class="metric-val">${previousClose ? previousClose.toFixed(2) : '--'}</span></span>
    `;
  } else {
    legend.innerHTML = `
      <span class="legend-item"><span class="dot dot-ma5"></span>MA5: <span id="m-ma5" class="metric-val">--</span></span>
      <span class="legend-item"><span class="dot dot-ma10"></span>MA10: <span id="m-ma10" class="metric-val">--</span></span>
      <span class="legend-item"><span class="dot dot-ma20"></span>MA20: <span id="m-ma20" class="metric-val">--</span></span>
    `;
  }
}

// 總繪製進入點
function draw() {
  const dpr = window.devicePixelRatio || 1;
  const width = wrap.clientWidth;
  const height = wrap.clientHeight;

  if (width <= 0 || height <= 0) return;

  canvas.width = width * dpr;
  canvas.height = height * dpr;
  canvas.style.width = `${width}px`;
  canvas.style.height = `${height}px`;

  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.scale(dpr, dpr);

  ctx.fillStyle = '#0b0c10';
  ctx.fillRect(0, 0, width, height);

  if (currentMode === 'intraday') {
    drawIntraday(width, height);
  } else {
    drawDaily(width, height);
  }
}

// 繪製當日分時走勢圖 (折線 + 漸層面積 + 均價線 + 昨收線)
function drawIntraday(width, height) {
  const data = intradayData;
  if (!data || !data.length) return;

  const paddingRight = 65;
  const paddingBottom = 24;
  const plotWidth = width - paddingRight;
  const mainHeight = Math.floor((height - paddingBottom) * 0.72);
  const volTop = mainHeight + 10;
  const volHeight = height - paddingBottom - volTop;

  // 計算可見範圍 (支援拖曳平移與滾輪縮放)
  const total = data.length;
  const n = Math.min(total, Math.max(15, viewBarsCount));
  const maxOffset = Math.max(0, total - n);
  viewOffset = Math.min(Math.max(0, viewOffset), maxOffset);

  const startIdx = Math.max(0, total - n - viewOffset);
  const endIdx = startIdx + n;
  const visible = data.slice(startIdx, endIdx);
  const visibleCount = visible.length;
  if (!visibleCount) return;

  // 計算最高價、最低價、最大成交量
  let minPrice = previousClose || visible[0].close;
  let maxPrice = previousClose || visible[0].close;
  let maxVol = 1;

  for (let i = 0; i < visibleCount; i++) {
    const b = visible[i];
    if (b.high > maxPrice) maxPrice = b.high;
    if (b.low < minPrice) minPrice = b.low;
    if (b.close > maxPrice) maxPrice = b.close;
    if (b.close < minPrice) minPrice = b.close;
    if (b.vwap && b.vwap > maxPrice) maxPrice = b.vwap;
    if (b.vwap && b.vwap < minPrice) minPrice = b.vwap;
    if (b.volume > maxVol) maxVol = b.volume;
  }

  // 昨收線盡量置於中間或有充足上下邊距
  const priceMargin = Math.max((maxPrice - minPrice) * 0.12, 0.5);
  minPrice -= priceMargin;
  maxPrice += priceMargin;
  const priceRange = maxPrice - minPrice;

  // 座標映射
  const barStep = plotWidth / (visibleCount - 1 || 1);
  const getX = i => i * barStep;
  const getY = p => Math.floor(mainHeight - ((p - minPrice) / priceRange) * mainHeight);
  const getVolY = v => Math.floor(height - paddingBottom - (maxVol > 0 ? (v / maxVol) * volHeight : 0));

  // 繪製水平網格線與 Y 軸價格刻度
  ctx.strokeStyle = '#1b202a';
  ctx.lineWidth = 1;
  ctx.fillStyle = '#64748b';
  ctx.font = '11px sans-serif';
  ctx.textAlign = 'left';

  const gridSteps = 4;
  for (let s = 0; s <= gridSteps; s++) {
    const p = minPrice + (priceRange * s) / gridSteps;
    const y = getY(p);
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(plotWidth, y);
    ctx.stroke();

    const diffPct = previousClose ? ((p - previousClose) / previousClose) * 100 : 0;
    const sign = diffPct >= 0 ? '+' : '';
    ctx.fillText(`${p.toFixed(2)} (${sign}${diffPct.toFixed(1)}%)`, plotWidth + 4, y + 4);
  }

  // 繪製昨收基準虛線
  if (previousClose && previousClose >= minPrice && previousClose <= maxPrice) {
    const prevY = getY(previousClose);
    ctx.strokeStyle = '#475569';
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(0, prevY);
    ctx.lineTo(plotWidth, prevY);
    ctx.stroke();
    ctx.setLineDash([]);

    ctx.fillStyle = '#94a3b8';
    ctx.fillText(`昨收 ${previousClose.toFixed(2)}`, plotWidth + 4, prevY + 4);
  }

  // 副圖分隔線
  ctx.strokeStyle = '#1e2430';
  ctx.beginPath();
  ctx.moveTo(0, volTop);
  ctx.lineTo(plotWidth, volTop);
  ctx.stroke();
  ctx.fillStyle = '#64748b';
  ctx.fillText(`量: ${Math.floor(maxVol)}`, plotWidth + 4, volTop + 12);

  // 判斷當日漲跌主色
  const lastClose = visible.at(-1)?.close || previousClose || 0;
  const isUp = previousClose ? (lastClose >= previousClose) : true;
  const mainLineColor = isUp ? '#ef4444' : '#22c55e';
  const fillColorTop = isUp ? 'rgba(239, 68, 68, 0.25)' : 'rgba(34, 197, 94, 0.25)';

  // 繪製走勢折線與漸層面積
  ctx.beginPath();
  ctx.moveTo(getX(0), getY(visible[0].close));
  for (let i = 1; i < visibleCount; i++) {
    ctx.lineTo(getX(i), getY(visible[i].close));
  }
  ctx.strokeStyle = mainLineColor;
  ctx.lineWidth = 1.8;
  ctx.stroke();

  // 漸層填充
  ctx.lineTo(getX(visibleCount - 1), mainHeight);
  ctx.lineTo(getX(0), mainHeight);
  ctx.closePath();
  const grad = ctx.createLinearGradient(0, 0, 0, mainHeight);
  grad.addColorStop(0, fillColorTop);
  grad.addColorStop(1, 'rgba(11, 12, 16, 0)');
  ctx.fillStyle = grad;
  ctx.fill();

  // 繪製均價線 (VWAP)
  ctx.beginPath();
  let vwapStarted = false;
  for (let i = 0; i < visibleCount; i++) {
    if (visible[i].vwap) {
      const vx = getX(i);
      const vy = getY(visible[i].vwap);
      if (!vwapStarted) { ctx.moveTo(vx, vy); vwapStarted = true; }
      else { ctx.lineTo(vx, vy); }
    }
  }
  ctx.strokeStyle = '#38bdf8';
  ctx.lineWidth = 1.2;
  ctx.stroke();

  // 繪製成交量柱
  const volBarWidth = Math.max(1, Math.floor(barStep * 0.7));
  for (let i = 0; i < visibleCount; i++) {
    const b = visible[i];
    const x = getX(i);
    const vY = getVolY(b.volume);
    const vH = Math.max(1, height - paddingBottom - vY);
    const barUp = previousClose ? b.close >= previousClose : true;
    ctx.fillStyle = barUp ? 'rgba(239, 68, 68, 0.6)' : 'rgba(34, 197, 94, 0.6)';
    ctx.fillRect(Math.floor(x - volBarWidth / 2), vY, volBarWidth, vH);
  }

  // 繪製 X 軸時間標籤
  ctx.fillStyle = '#64748b';
  ctx.textAlign = 'center';
  const labelInterval = Math.max(1, Math.floor(visibleCount / 6));
  for (let i = 0; i < visibleCount; i += labelInterval) {
    const b = visible[i];
    const x = getX(i);
    ctx.fillText(b.time || '', x, height - 6);
  }

  // 十字游標
  if (hoverIndex >= 0 && hoverIndex < visibleCount) {
    const cur = visible[hoverIndex];
    const curX = getX(hoverIndex);
    const curY = getY(cur.close);

    ctx.strokeStyle = '#94a3b8';
    ctx.setLineDash([4, 4]);
    ctx.lineWidth = 1;

    ctx.beginPath();
    ctx.moveTo(curX, 0);
    ctx.lineTo(curX, height - paddingBottom);
    ctx.stroke();

    ctx.beginPath();
    ctx.moveTo(0, curY);
    ctx.lineTo(plotWidth, curY);
    ctx.stroke();

    ctx.setLineDash([]);

    // 更新指標列文字
    document.getElementById('m-date').textContent = cur.time || '--';
    document.getElementById('m-open').textContent = cur.open.toFixed(2);
    document.getElementById('m-high').textContent = cur.high.toFixed(2);
    document.getElementById('m-low').textContent = cur.low.toFixed(2);
    document.getElementById('m-close').textContent = cur.close.toFixed(2);

    const diffPct = previousClose ? ((cur.close - previousClose) / previousClose) * 100 : 0;
    const pSign = diffPct > 0 ? '+' : '';
    document.getElementById('m-pct').textContent = `${pSign}${diffPct.toFixed(2)}%`;
    document.getElementById('m-pct').style.color = diffPct > 0 ? '#ef4444' : (diffPct < 0 ? '#22c55e' : '#f1f5f9');
    document.getElementById('m-vol').textContent = Math.floor(cur.volume);

    const vwapEl = document.getElementById('m-vwap');
    if (vwapEl) vwapEl.textContent = cur.vwap ? cur.vwap.toFixed(2) : '--';
  } else {
    // 預設顯示最後一筆
    const last = visible[visibleCount - 1];
    if (last) {
      document.getElementById('m-date').textContent = last.time || '--';
      document.getElementById('m-open').textContent = last.open.toFixed(2);
      document.getElementById('m-high').textContent = last.high.toFixed(2);
      document.getElementById('m-low').textContent = last.low.toFixed(2);
      document.getElementById('m-close').textContent = last.close.toFixed(2);

      const diffPct = previousClose ? ((last.close - previousClose) / previousClose) * 100 : 0;
      const pSign = diffPct > 0 ? '+' : '';
      document.getElementById('m-pct').textContent = `${pSign}${diffPct.toFixed(2)}%`;
      document.getElementById('m-pct').style.color = diffPct > 0 ? '#ef4444' : (diffPct < 0 ? '#22c55e' : '#f1f5f9');
      document.getElementById('m-vol').textContent = Math.floor(last.volume);

      const vwapEl = document.getElementById('m-vwap');
      if (vwapEl) vwapEl.textContent = last.vwap ? last.vwap.toFixed(2) : '--';
    }
  }
}

// 繪製歷史日 K 線圖 (K棒 + MA5/10/20 + 成交量)
function drawDaily(width, height) {
  const data = dailyData;
  if (!data || !data.length) return;

  const paddingRight = 65;
  const paddingBottom = 24;
  const plotWidth = width - paddingRight;
  const mainHeight = Math.floor((height - paddingBottom) * 0.72);
  const volTop = mainHeight + 10;
  const volHeight = height - paddingBottom - volTop;

  const ma5 = calculateMA(data, 5);
  const ma10 = calculateMA(data, 10);
  const ma20 = calculateMA(data, 20);

  const total = data.length;
  const n = Math.min(total, Math.max(15, viewBarsCount));
  const maxOffset = Math.max(0, total - n);
  viewOffset = Math.min(Math.max(0, viewOffset), maxOffset);

  const startIdx = Math.max(0, total - n - viewOffset);
  const endIdx = startIdx + n;
  const visible = data.slice(startIdx, endIdx);
  const vMA5 = ma5.slice(startIdx, endIdx);
  const vMA10 = ma10.slice(startIdx, endIdx);
  const vMA20 = ma20.slice(startIdx, endIdx);
  const visibleCount = visible.length;
  if (!visibleCount) return;

  let minPrice = Infinity;
  let maxPrice = -Infinity;
  let maxVol = 1;

  for (let i = 0; i < visibleCount; i++) {
    const b = visible[i];
    if (b.low < minPrice) minPrice = b.low;
    if (b.high > maxPrice) maxPrice = b.high;
    if (b.volume > maxVol) maxVol = b.volume;
    if (vMA5[i] && vMA5[i] < minPrice) minPrice = vMA5[i];
    if (vMA5[i] && vMA5[i] > maxPrice) maxPrice = vMA5[i];
  }

  const priceMargin = (maxPrice - minPrice) * 0.08 || 1;
  minPrice -= priceMargin;
  maxPrice += priceMargin;
  const priceRange = maxPrice - minPrice;

  const barStep = plotWidth / visibleCount;
  const barWidth = Math.max(2, Math.floor(barStep * 0.75));
  const getX = i => Math.floor(i * barStep + barStep / 2);
  const getY = p => Math.floor(mainHeight - ((p - minPrice) / priceRange) * mainHeight);
  const getVolY = v => Math.floor(height - paddingBottom - (maxVol > 0 ? (v / maxVol) * volHeight : 0));

  // 水平格線
  ctx.strokeStyle = '#1b202a';
  ctx.lineWidth = 1;
  ctx.fillStyle = '#64748b';
  ctx.font = '11px sans-serif';
  ctx.textAlign = 'left';

  const gridSteps = 5;
  for (let s = 0; s <= gridSteps; s++) {
    const p = minPrice + (priceRange * s) / gridSteps;
    const y = getY(p);
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(plotWidth, y);
    ctx.stroke();
    ctx.fillText(p.toFixed(2), plotWidth + 6, y + 4);
  }

  // 副圖線
  ctx.beginPath();
  ctx.moveTo(0, volTop);
  ctx.lineTo(plotWidth, volTop);
  ctx.stroke();
  ctx.fillText(`量: ${Math.floor(maxVol)}`, plotWidth + 6, volTop + 12);

  // 繪製 K 棒
  for (let i = 0; i < visibleCount; i++) {
    const b = visible[i];
    const x = getX(i);
    const openY = getY(b.open);
    const closeY = getY(b.close);
    const highY = getY(b.high);
    const lowY = getY(b.low);

    const isUp = b.close >= b.open;
    const color = isUp ? '#ef4444' : '#22c55e';

    ctx.strokeStyle = color;
    ctx.fillStyle = color;

    // 影線
    ctx.beginPath();
    ctx.moveTo(x, highY);
    ctx.lineTo(x, lowY);
    ctx.stroke();

    // 實體
    const rectTop = Math.min(openY, closeY);
    const rectHeight = Math.max(2, Math.abs(closeY - openY));
    ctx.fillRect(Math.floor(x - barWidth / 2), rectTop, barWidth, rectHeight);

    // 成交量柱
    const vY = getVolY(b.volume);
    const vH = Math.max(1, height - paddingBottom - vY);
    ctx.fillStyle = isUp ? 'rgba(239, 68, 68, 0.65)' : 'rgba(34, 197, 94, 0.65)';
    ctx.fillRect(Math.floor(x - barWidth / 2), vY, barWidth, vH);
  }

  // 均線
  function drawLine(arr, color) {
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    let started = false;
    for (let i = 0; i < visibleCount; i++) {
      const v = arr[i];
      if (v === null) continue;
      const x = getX(i);
      const y = getY(v);
      if (!started) { ctx.moveTo(x, y); started = true; }
      else { ctx.lineTo(x, y); }
    }
    ctx.stroke();
  }

  drawLine(vMA5, '#f59e0b');
  drawLine(vMA10, '#06b6d4');
  drawLine(vMA20, '#a855f7');

  // X 軸標籤
  ctx.fillStyle = '#64748b';
  ctx.textAlign = 'center';
  const labelInterval = Math.max(1, Math.floor(visibleCount / 6));
  for (let i = 0; i < visibleCount; i += labelInterval) {
    const b = visible[i];
    const x = getX(i);
    const label = b.time ? b.time.slice(5) : '';
    ctx.fillText(label, x, height - 6);
  }

  // 十字游標
  if (hoverIndex >= 0 && hoverIndex < visibleCount) {
    const cur = visible[hoverIndex];
    const curX = getX(hoverIndex);
    const curY = getY(cur.close);

    ctx.strokeStyle = '#94a3b8';
    ctx.setLineDash([4, 4]);
    ctx.lineWidth = 1;

    ctx.beginPath();
    ctx.moveTo(curX, 0);
    ctx.lineTo(curX, height - paddingBottom);
    ctx.stroke();

    ctx.beginPath();
    ctx.moveTo(0, curY);
    ctx.lineTo(plotWidth, curY);
    ctx.stroke();

    ctx.setLineDash([]);

    document.getElementById('m-date').textContent = cur.time || '--';
    document.getElementById('m-open').textContent = cur.open.toFixed(2);
    document.getElementById('m-high').textContent = cur.high.toFixed(2);
    document.getElementById('m-low').textContent = cur.low.toFixed(2);
    document.getElementById('m-close').textContent = cur.close.toFixed(2);

    const prevClose = hoverIndex > 0 ? visible[hoverIndex - 1].close : cur.open;
    const diffPct = prevClose > 0 ? ((cur.close - prevClose) / prevClose) * 100 : 0;
    const pSign = diffPct > 0 ? '+' : '';
    document.getElementById('m-pct').textContent = `${pSign}${diffPct.toFixed(2)}%`;
    document.getElementById('m-pct').style.color = diffPct > 0 ? '#ef4444' : (diffPct < 0 ? '#22c55e' : '#f1f5f9');
    document.getElementById('m-vol').textContent = Math.floor(cur.volume);

    document.getElementById('m-ma5').textContent = vMA5[hoverIndex] ? vMA5[hoverIndex].toFixed(2) : '--';
    document.getElementById('m-ma10').textContent = vMA10[hoverIndex] ? vMA10[hoverIndex].toFixed(2) : '--';
    document.getElementById('m-ma20').textContent = vMA20[hoverIndex] ? vMA20[hoverIndex].toFixed(2) : '--';
  } else {
    const last = visible[visibleCount - 1];
    if (last) {
      document.getElementById('m-date').textContent = last.time || '--';
      document.getElementById('m-open').textContent = last.open.toFixed(2);
      document.getElementById('m-high').textContent = last.high.toFixed(2);
      document.getElementById('m-low').textContent = last.low.toFixed(2);
      document.getElementById('m-close').textContent = last.close.toFixed(2);

      const prevClose = visibleCount > 1 ? visible[visibleCount - 2].close : last.open;
      const diffPct = prevClose > 0 ? ((last.close - prevClose) / prevClose) * 100 : 0;
      const pSign = diffPct > 0 ? '+' : '';
      document.getElementById('m-pct').textContent = `${pSign}${diffPct.toFixed(2)}%`;
      document.getElementById('m-pct').style.color = diffPct > 0 ? '#ef4444' : (diffPct < 0 ? '#22c55e' : '#f1f5f9');
      document.getElementById('m-vol').textContent = Math.floor(last.volume);

      document.getElementById('m-ma5').textContent = vMA5[visibleCount - 1] ? vMA5[visibleCount - 1].toFixed(2) : '--';
      document.getElementById('m-ma10').textContent = vMA10[visibleCount - 1] ? vMA10[visibleCount - 1].toFixed(2) : '--';
      document.getElementById('m-ma20').textContent = vMA20[visibleCount - 1] ? vMA20[visibleCount - 1].toFixed(2) : '--';
    }
  }
}

// 滑鼠互動：拖曳平移 (Drag to pan)、滾輪縮放 (Zoom) 與十字游標
wrap.addEventListener('mousedown', e => {
  if (e.button !== 0) return;
  isDragging = true;
  dragStartX = e.clientX;
  dragStartOffset = viewOffset;
  wrap.classList.add('dragging');
});

window.addEventListener('mousemove', e => {
  const rect = canvas.getBoundingClientRect();
  const paddingRight = 65;
  const plotWidth = wrap.clientWidth - paddingRight;

  if (isDragging) {
    const dx = e.clientX - dragStartX;
    const currentData = currentMode === 'intraday' ? intradayData : dailyData;
    const total = currentData.length;
    const n = Math.min(total, Math.max(15, viewBarsCount));
    const maxOffset = Math.max(0, total - n);
    const barStep = plotWidth / (n || 1);
    const shiftBars = Math.round(dx / barStep);

    // 往右拉是看過去的歷史 (offset 增加)；往左拉是看最新資料 (offset 減少)
    viewOffset = Math.min(maxOffset, Math.max(0, dragStartOffset + shiftBars));
    draw();
    return;
  }

  // 懸浮十字游標計算
  const x = e.clientX - rect.left;
  const currentData = currentMode === 'intraday' ? intradayData : dailyData;
  const total = currentData.length;
  const n = Math.min(total, Math.max(15, viewBarsCount));

  if (x >= 0 && x <= plotWidth && n > 0) {
    const barStep = plotWidth / (n || 1);
    const idx = Math.floor(x / barStep);
    if (idx >= 0 && idx < n) {
      if (hoverIndex !== idx) {
        hoverIndex = idx;
        draw();
      }
      return;
    }
  }
  if (hoverIndex !== -1) {
    hoverIndex = -1;
    draw();
  }
});

window.addEventListener('mouseup', () => {
  if (isDragging) {
    isDragging = false;
    wrap.classList.remove('dragging');
  }
});

wrap.addEventListener('mouseleave', () => {
  if (hoverIndex !== -1) {
    hoverIndex = -1;
    draw();
  }
});

// 滑鼠滾輪縮放 (Zoom)
wrap.addEventListener('wheel', e => {
  e.preventDefault();
  const zoomIn = e.deltaY < 0;
  const step = 8;
  const currentData = currentMode === 'intraday' ? intradayData : dailyData;
  const maxBars = Math.max(30, currentData.length);

  if (zoomIn) {
    viewBarsCount = Math.max(15, viewBarsCount - step);
  } else {
    viewBarsCount = Math.min(maxBars, viewBarsCount + step);
  }
  draw();
}, { passive: false });

window.addEventListener('resize', () => {
  draw();
});

// 自動排程更新（盤中每 30 秒自動刷新分時）
autoRefreshTimer = setInterval(() => {
  if (currentMode === 'intraday') {
    loadData(false);
  }
}, 30000);

loadData();
