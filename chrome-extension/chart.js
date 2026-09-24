import { VM_MODE, FIREBASE_ROOT } from './environment.js';
import { chartURL, finite } from './core.js';

const params = new URLSearchParams(window.location.search);
const symbol = (params.get('symbol') || '2330').toUpperCase();
const market = (params.get('market') || 'TW').toUpperCase();
let stockName = params.get('name') || symbol;
const strategyType = params.get('strategy') || '';

const canvas = document.getElementById('kline-canvas');
const ctx = canvas.getContext('2d');
const wrap = document.getElementById('chart-wrap');
const loadingMask = document.getElementById('loading-mask');

let klineData = [];
let hoverIndex = -1;
let currentStockInfo = { price: 0, change_pct: 0, vwap: null, reason: '' };

// 初始化頂部基本資訊
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

document.getElementById('btn-refresh').addEventListener('click', () => loadData(true));

// 計算移動平均線
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

// 產生模擬資料 (VM 或無網路時 fallback)
function generateMockKlines(basePrice = 1000) {
  const bars = [];
  let cur = basePrice;
  const now = new Date();
  for (let i = 90; i >= 0; i--) {
    const d = new Date(now.getTime() - i * 86400000);
    if (d.getDay() === 0 || d.getDay() === 6) continue;
    const change = (Math.random() - 0.48) * (cur * 0.03);
    const open = Math.round((cur + (Math.random() - 0.5) * 5) * 100) / 100;
    const close = Math.round((cur + change) * 100) / 100;
    const high = Math.round((Math.max(open, close) + Math.random() * 8) * 100) / 100;
    const low = Math.round((Math.min(open, close) - Math.random() * 8) * 100) / 100;
    const vol = Math.floor(1000 + Math.random() * 15000);
    const timeStr = d.toISOString().slice(0, 10);
    bars.push({ time: timeStr, open, high, low, close, volume: vol });
    cur = close;
  }
  return bars;
}

// 從 Firebase RTDB 載入真實 K 線與當沖狀態
async function loadData(force = false) {
  loadingMask.classList.remove('hidden');
  document.getElementById('txt-status-desc').textContent = '資料載入中…';

  try {
    if (VM_MODE) {
      klineData = generateMockKlines(1000);
      currentStockInfo = { price: 1000, change_pct: 1.25, vwap: 996.5, reason: 'VM 隔離示例數據' };
      renderInfo();
      draw();
      document.getElementById('txt-status-desc').textContent = '狀態：VM 示例離線資料';
      return;
    }

    // 平行抓取 kline 與 intraday_live
    const [klineRes, liveRes] = await Promise.all([
      fetch(`${FIREBASE_ROOT}/kline/${encodeURIComponent(symbol)}.json`).catch(() => null),
      fetch(`${FIREBASE_ROOT}/intraday_live.json`).catch(() => null)
    ]);

    let bars = null;
    if (klineRes && klineRes.ok) {
      bars = await klineRes.json();
    }

    if (!Array.isArray(bars) || !bars.length) {
      // 嘗試從 releases 抓取
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
      klineData = bars.map(b => ({
        time: b.time || b.date,
        open: Number(b.open),
        high: Number(b.high),
        low: Number(b.low),
        close: Number(b.close),
        volume: Number(b.volume || b.amount || 0)
      })).filter(b => finite(b.open) && finite(b.close) && b.time);
    } else {
      klineData = generateMockKlines(100);
    }

    // 處理即時狀態
    if (liveRes && liveRes.ok) {
      const live = await liveRes.json();
      const openPos = live?.open_positions?.[symbol];
      const closedTrades = live?.closed_trades;
      const closedTrade = Array.isArray(closedTrades)
        ? closedTrades.find(t => t?.symbol === symbol)
        : (closedTrades?.[symbol] || null);

      if (openPos && openPos.status === 'OPEN') {
        currentStockInfo.price = openPos.entry_price || klineData.at(-1)?.close || 0;
        currentStockInfo.change_pct = openPos.pnl_pct || 0;
        currentStockInfo.vwap = openPos.entry_vwap || null;
        currentStockInfo.reason = Array.isArray(openPos.entry_reasons) ? openPos.entry_reasons.join('、') : (openPos.reason || '當沖進場持倉中');
        if (openPos.name) stockName = openPos.name;
      } else if (closedTrade) {
        currentStockInfo.price = closedTrade.exit_price || klineData.at(-1)?.close || 0;
        currentStockInfo.change_pct = closedTrade.pnl_pct || 0;
        currentStockInfo.reason = `已出場：${closedTrade.exit_reason || '平倉'} (報酬: ${closedTrade.pnl_pct > 0 ? '+' : ''}${Number(closedTrade.pnl_pct).toFixed(2)}%)`;
        if (closedTrade.name) stockName = closedTrade.name;
      } else {
        const last = klineData.at(-1);
        const prev = klineData.at(-2);
        currentStockInfo.price = last ? last.close : 0;
        currentStockInfo.change_pct = (last && prev && prev.close > 0) ? ((last.close - prev.close) / prev.close) * 100 : 0;
        currentStockInfo.reason = '無當沖持倉';
      }
    } else {
      const last = klineData.at(-1);
      const prev = klineData.at(-2);
      currentStockInfo.price = last ? last.close : 0;
      currentStockInfo.change_pct = (last && prev && prev.close > 0) ? ((last.close - prev.close) / prev.close) * 100 : 0;
    }

    renderInfo();
    draw();
    document.getElementById('txt-status-desc').textContent = `資料更新：${new Date().toLocaleTimeString('zh-TW', { hour12: false })}`;
  } catch (err) {
    document.getElementById('txt-status-desc').textContent = `連線提示：${err.message || '使用暫存資料'}`;
    if (!klineData.length) klineData = generateMockKlines(100);
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
}

// 繪製 K 線圖 Canvas
function draw() {
  const dpr = window.devicePixelRatio || 1;
  const width = wrap.clientWidth;
  const height = wrap.clientHeight;

  if (width <= 0 || height <= 0 || !klineData.length) return;

  canvas.width = width * dpr;
  canvas.height = height * dpr;
  canvas.style.width = `${width}px`;
  canvas.style.height = `${height}px`;

  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.scale(dpr, dpr);

  // 繪製背景
  ctx.fillStyle = '#0b0c10';
  ctx.fillRect(0, 0, width, height);

  // 計算版面
  const paddingRight = 65; // Y軸價格標籤空間
  const paddingBottom = 24; // X軸時間標籤空間
  const mainHeight = Math.floor((height - paddingBottom) * 0.72);
  const volTop = mainHeight + 10;
  const volHeight = height - paddingBottom - volTop;
  const plotWidth = width - paddingRight;

  // 均線計算
  const ma5 = calculateMA(klineData, 5);
  const ma10 = calculateMA(klineData, 10);
  const ma20 = calculateMA(klineData, 20);

  // 取得可見範圍 (預設最新 80 根，或全部)
  const maxBars = 90;
  const sliceStart = Math.max(0, klineData.length - maxBars);
  const visible = klineData.slice(sliceStart);
  const vMA5 = ma5.slice(sliceStart);
  const vMA10 = ma10.slice(sliceStart);
  const vMA20 = ma20.slice(sliceStart);

  const n = visible.length;
  if (!n) return;

  // 計算價格最高、最低
  let minPrice = Infinity;
  let maxPrice = -Infinity;
  let maxVol = 0;

  for (let i = 0; i < n; i++) {
    const b = visible[i];
    if (b.low < minPrice) minPrice = b.low;
    if (b.high > maxPrice) maxPrice = b.high;
    if (b.volume > maxVol) maxVol = b.volume;
    if (vMA5[i] && vMA5[i] < minPrice) minPrice = vMA5[i];
    if (vMA5[i] && vMA5[i] > maxPrice) maxPrice = vMA5[i];
  }

  // 預留上下邊距
  const priceMargin = (maxPrice - minPrice) * 0.08 || 1;
  minPrice -= priceMargin;
  maxPrice += priceMargin;
  const priceRange = maxPrice - minPrice;

  // 座標轉換函式
  const barWidth = Math.max(2, Math.floor((plotWidth / n) * 0.75));
  const barStep = plotWidth / n;
  const getX = i => Math.floor(i * barStep + barStep / 2);
  const getY = price => Math.floor(mainHeight - ((price - minPrice) / priceRange) * mainHeight);
  const getVolY = vol => Math.floor(height - paddingBottom - (maxVol > 0 ? (vol / maxVol) * volHeight : 0));

  // 繪製水平網格線與 Y 軸刻度
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

  // 副圖網格線
  ctx.beginPath();
  ctx.moveTo(0, volTop);
  ctx.lineTo(plotWidth, volTop);
  ctx.stroke();

  // 繪製成交量最大值標記
  ctx.fillText(`量: ${Math.floor(maxVol)}`, plotWidth + 6, volTop + 12);

  // 繪製 K 棒與成交量
  for (let i = 0; i < n; i++) {
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

  // 繪製均線函式
  function drawLine(arr, color) {
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    let started = false;
    for (let i = 0; i < n; i++) {
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

  // 繪製 X 軸時間標籤
  ctx.fillStyle = '#64748b';
  ctx.textAlign = 'center';
  const labelInterval = Math.max(1, Math.floor(n / 6));
  for (let i = 0; i < n; i += labelInterval) {
    const b = visible[i];
    const x = getX(i);
    const label = b.time ? b.time.slice(5) : '';
    ctx.fillText(label, x, height - 6);
  }

  // 十字游標與懸浮指標更新
  if (hoverIndex >= 0 && hoverIndex < n) {
    const cur = visible[hoverIndex];
    const curX = getX(hoverIndex);
    const curY = getY(cur.close);

    ctx.strokeStyle = '#94a3b8';
    ctx.setLineDash([4, 4]);
    ctx.lineWidth = 1;

    // 垂直線
    ctx.beginPath();
    ctx.moveTo(curX, 0);
    ctx.lineTo(curX, height - paddingBottom);
    ctx.stroke();

    // 水平線
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
    // 預設顯示最後一根
    const last = visible[n - 1];
    if (last) {
      document.getElementById('m-date').textContent = last.time || '--';
      document.getElementById('m-open').textContent = last.open.toFixed(2);
      document.getElementById('m-high').textContent = last.high.toFixed(2);
      document.getElementById('m-low').textContent = last.low.toFixed(2);
      document.getElementById('m-close').textContent = last.close.toFixed(2);
      const prevClose = n > 1 ? visible[n - 2].close : last.open;
      const diffPct = prevClose > 0 ? ((last.close - prevClose) / prevClose) * 100 : 0;
      const pSign = diffPct > 0 ? '+' : '';
      document.getElementById('m-pct').textContent = `${pSign}${diffPct.toFixed(2)}%`;
      document.getElementById('m-pct').style.color = diffPct > 0 ? '#ef4444' : (diffPct < 0 ? '#22c55e' : '#f1f5f9');
      document.getElementById('m-vol').textContent = Math.floor(last.volume);

      document.getElementById('m-ma5').textContent = vMA5[n - 1] ? vMA5[n - 1].toFixed(2) : '--';
      document.getElementById('m-ma10').textContent = vMA10[n - 1] ? vMA10[n - 1].toFixed(2) : '--';
      document.getElementById('m-ma20').textContent = vMA20[n - 1] ? vMA20[n - 1].toFixed(2) : '--';
    }
  }
}

// 滑鼠互動
wrap.addEventListener('mousemove', e => {
  const rect = canvas.getBoundingClientRect();
  const x = e.clientX - rect.left;
  const paddingRight = 65;
  const plotWidth = wrap.clientWidth - paddingRight;

  const maxBars = 90;
  const sliceStart = Math.max(0, klineData.length - maxBars);
  const n = klineData.slice(sliceStart).length;

  if (x >= 0 && x <= plotWidth && n > 0) {
    const barStep = plotWidth / n;
    const idx = Math.floor(x / barStep);
    if (idx >= 0 && idx < n) {
      hoverIndex = idx;
      draw();
      return;
    }
  }
  if (hoverIndex !== -1) {
    hoverIndex = -1;
    draw();
  }
});

wrap.addEventListener('mouseleave', () => {
  hoverIndex = -1;
  draw();
});

window.addEventListener('resize', () => {
  draw();
});

loadData();
