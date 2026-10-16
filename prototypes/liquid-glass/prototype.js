// Liquid Glass prototype: synthetic data only. No fetch, no Firebase, no trading calls.
(() => {
  const $ = id => document.getElementById(id);
  const esc = x => String(x ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const cls = v => v > 0 ? 'lg-up' : v < 0 ? 'lg-down' : 'lg-flat';
  const pct = v => (v > 0 ? '+' : '') + v.toFixed(2) + '%';

  // ---------- Synthetic stocks (clearly not real tickers) ----------
  const STOCKS = {
    T101: { name: '合成半導體', price: 128.5, chg: 3.62, entry: 126.0, stop: 124.5, target: 131.0, tags: ['VWAP 突破', '量比 2.4'], time: '09:41', lane: 'A 轉強' },
    T102: { name: '合成光電', price: 57.3, chg: 1.24, entry: 57.0, stop: 56.4, target: 58.5, tags: ['大盤未出貨'], time: '10:02', lane: 'A 突破' },
    T201: { name: '合成網通', price: 86.4, chg: 2.13, entry: 85.9, stop: 85.7, target: 86.9, tags: ['五檔失衡 0.18', '同業 3/4 同向'], time: '09:04', lane: 'B1 做多' },
    T202: { name: '合成航運', price: 44.15, chg: -1.89, entry: 44.4, stop: 44.5, target: 44.25, tags: ['主動賣量 71%'], time: '09:07', lane: 'B1 做空' },
    T301: { name: '合成電機', price: 172.0, chg: 0.88, entry: 171.5, stop: 170.0, target: 174.0, tags: ['突破前 2 根高點'], time: '10:20', lane: 'B3 做多' },
  };
  const pick = sym => {
    const s = STOCKS[sym];
    return `<button type="button" class="stock glass-tile" data-symbol="${sym}" aria-label="${esc(sym + ' ' + s.name)}，開啟股票詳情">
      <div class="stock-top">
        <div class="stock-id"><b>${esc(s.name)}</b><span>${sym}</span></div>
        <div class="stock-px"><strong class="${cls(s.chg)}">${s.price.toFixed(2)}</strong><span class="lg-delta ${cls(s.chg)}">${pct(s.chg)}</span></div>
      </div>
      <div class="stock-levels">
        <div class="glass-well"><small>模擬進場</small><b>${s.entry.toFixed(2)}</b></div>
        <div class="glass-well"><small>停損</small><b class="lg-down">${s.stop.toFixed(2)}</b></div>
        <div class="glass-well"><small>停利</small><b class="lg-up">${s.target.toFixed(2)}</b></div>
      </div>
      <div class="stock-tags"><span class="lg-chip lg-chip--interactive">${esc(s.lane)}</span>${s.tags.map(t => `<span class="lg-chip">${esc(t)}</span>`).join('')}<time>${s.time}</time></div>
    </button>`;
  };
  $('aPicks').innerHTML = pick('T101') + pick('T102');
  $('b1Picks').innerHTML = pick('T201') + pick('T202');
  $('b3Picks').innerHTML = pick('T301');

  // ---------- Revenue observation ----------
  const rev = [['T401 合成食品', '10-14', 0.85, 2.31, -0.42, 1.73], ['T402 合成生技', '10-14', -0.66, 0.40, -2.18, -1.52], ['T403 合成材料', '10-13', 1.92, 4.05, 0.31, 3.40], ['T404 合成電子', '10-13', 0, 1.12, -1.36, -0.45]];
  $('revRows').innerHTML = rev.map(([n, d, ...v]) => `<tr><td>${esc(n)}</td><td>${d}</td>${v.map(x => `<td class="${cls(x)}">${pct(x)}</td>`).join('')}</tr>`).join('');

  // ---------- 開盤八法 ----------
  const DIR = { U: ['漲', 'lg-up'], D: ['跌', 'lg-down'] };
  const dirs = ds => `<span class="dirs" aria-label="${ds.map(d => DIR[d][0]).join('、')}">${ds.map(d => `<i class="${DIR[d][1]}">${DIR[d][0]}</i>`).join('')}</span>`;
  $('openingMarkets').innerHTML = [['加權指數', 'TAIEX · 第 4 法', 22841.6, 0.74, ['D', 'U', 'U']], ['櫃買指數', 'TPEx · 第 1 法', 251.32, 1.12, ['U', 'U', 'U']]]
    .map(([n, sub, v, c, ds]) => `<div class="market glass-tile"><div><b>${n}</b><small>${sub}</small><div style="margin-top:6px">${dirs(ds)}</div></div><div style="text-align:right"><strong class="${cls(c)}">${v.toLocaleString('en-US', { minimumFractionDigits: 2 })}</strong><div class="lg-delta ${cls(c)}">${pct(c)}</div></div></div>`).join('');

  const METHOD = { UUU: 1, UUD: 2, UDD: 3, DUU: 4, DDU: 5, DDD: 6, DUD: 7, UDU: 8 };
  const names = ['合成記憶體', '合成散熱', '合成機殼', '合成被動元件', '合成伺服器', '合成面板', '合成鋼鐵', '合成金控', '合成觀光', '合成電池', '合成車用', '合成通路', '合成軟體', '合成營建', '合成紡織'];
  const rows = names.map((name, i) => {
    let p = 40 + i * 9.7, prices = [p];
    const ds = [];
    for (let k = 0; k < 3; k++) { const up = ((i * 7 + k * 3) % 5) > 1; ds.push(up ? 'U' : 'D'); p = +(p * (1 + (up ? 1 : -1) * (0.004 + ((i + k) % 4) * 0.003))).toFixed(2); prices.push(p); }
    return { symbol: 'T' + (500 + i), name, ds, prices, method: METHOD[ds.join('')] };
  });
  const spark = r => {
    const lo = Math.min(...r.prices), span = Math.max(...r.prices) - lo || 1;
    const pts = r.prices.map((p, i) => [12 + i * 58.6, 54 - (p - lo) / span * 44]);
    const c = r.prices[3] >= r.prices[0] ? 'var(--up)' : 'var(--down)';
    return `<svg viewBox="0 0 200 64" role="img" aria-label="昨收至09:15三段價格"><line x1="12" x2="188" y1="${pts[0][1]}" y2="${pts[0][1]}" stroke="var(--glass-hairline)" stroke-dasharray="3 4"/><polyline fill="none" stroke="${c}" stroke-width="2.25" stroke-linejoin="round" points="${pts.map(p => p.join(',')).join(' ')}"/>${pts.map(p => `<circle cx="${p[0]}" cy="${p[1]}" r="3" fill="${c}"/>`).join('')}</svg>`;
  };
  let page = 0; const PER = 5, pages = Math.ceil(rows.length / PER);
  const renderPage = () => {
    $('openingRows').innerHTML = rows.slice(page * PER, page * PER + PER).map(r => {
      const chg = (r.prices[3] / r.prices[0] - 1) * 100;
      return `<article class="eight-card glass-tile"><h3>${esc(r.name)}<span>${r.symbol}</span></h3><p><span class="method">第 ${r.method} 法</span> · ${dirs(r.ds)}</p>${spark(r)}<p class="mono">${r.prices.map(v => v.toFixed(2)).join(' / ')} <span class="${cls(chg)}">(${pct(chg)})</span></p><small>成交時間：09:14:58</small></article>`;
    }).join('');
    $('pageStatus').textContent = `${page + 1} / ${pages}`;
    document.querySelectorAll('[data-page]').forEach(b => { const d = +b.dataset.page; b.disabled = page + d < 0 || page + d >= pages; });
  };
  document.querySelectorAll('[data-page]').forEach(b => b.addEventListener('click', () => { page = Math.min(pages - 1, Math.max(0, page + +b.dataset.page)); renderPage(); }));
  renderPage();

  // Tabs: arrow keys move between tabs (WAI-ARIA tabs pattern)
  const tabs = [$('openingTab'), $('closingTab')];
  const selectTab = t => tabs.forEach(x => { const on = x === t; x.setAttribute('aria-selected', on); x.tabIndex = on ? 0 : -1; $(x.getAttribute('aria-controls')).hidden = !on; });
  tabs.forEach((t, i) => {
    t.addEventListener('click', () => selectTab(t));
    t.addEventListener('keydown', e => { if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') { const n = tabs[(i + (e.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length]; selectTab(n); n.focus(); } });
  });

  // Price quick filter (visual only)
  document.querySelectorAll('[data-price]').forEach(b => b.addEventListener('click', () => document.querySelectorAll('[data-price]').forEach(x => x.setAttribute('aria-pressed', x === b))));
  document.querySelectorAll('[data-sync]').forEach(b => b.addEventListener('click', () => { $('dataStatusText').lastChild.textContent = '合成資料已重新整理 · ' + new Date().toLocaleTimeString('zh-TW', { hour12: false }); }));

  // ---------- Theme ----------
  const themeBtn = $('themeToggle');
  const syncThemeBtn = () => {
    const dark = document.documentElement.dataset.theme === 'dark';
    $('themeIcon').textContent = dark ? 'light_mode' : 'dark_mode';
    $('themeLabel').textContent = dark ? '淺色模式' : '深色模式';
    themeBtn.setAttribute('aria-pressed', dark);
  };
  themeBtn.addEventListener('click', () => {
    const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem('LG_PROTO_THEME', next); } catch (_) {}
    syncThemeBtn();
    if (chart) applyChartTheme();
  });
  syncThemeBtn();

  // ---------- Scroll spy for top nav + bottom nav ----------
  const navs = [...document.querySelectorAll('.lg-topnav a[href^="#"], .lg-bottom-nav a[href^="#"]')];
  const targets = [...new Set(navs.map(a => a.getAttribute('href')))].map(h => ({ h, node: document.querySelector(h) })).filter(x => x.node);
  const select = h => navs.forEach(a => a.getAttribute('href') === h ? a.setAttribute('aria-current', 'location') : a.removeAttribute('aria-current'));
  let queued = false;
  const spy = () => {
    queued = false;
    const line = parseFloat(getComputedStyle(document.documentElement).scrollPaddingTop) + 24;
    const passed = targets.filter(t => t.node.getBoundingClientRect().top <= line);
    select((passed.at(-1) || targets[0]).h);
  };
  addEventListener('scroll', () => { if (!queued) { queued = true; requestAnimationFrame(spy); } }, { passive: true });
  spy();

  // ---------- Stock detail modal ----------
  const modal = $('stockDetailModal');
  let lastFocus = null, chart = null, candles = null, volume = null;
  const css = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const series = (sym) => {
    let seed = [...sym].reduce((a, c) => a + c.charCodeAt(0), 0);
    const rnd = () => (seed = (seed * 9301 + 49297) % 233280) / 233280;
    const out = []; let close = STOCKS[sym].price * 0.86; const d = new Date(Date.UTC(2026, 6, 1));
    while (out.length < 70) {
      d.setUTCDate(d.getUTCDate() + 1); if (d.getUTCDay() % 6 === 0) continue;
      const open = close * (1 + (rnd() - .48) * .02); close = open * (1 + (rnd() - .46) * .035);
      const high = Math.max(open, close) * (1 + rnd() * .012), low = Math.min(open, close) * (1 - rnd() * .012);
      out.push({ time: d.toISOString().slice(0, 10), open, high, low, close, value: Math.round(2000 + rnd() * 9000) });
    }
    // Rescale so the last close matches the card's synthetic price.
    const k = STOCKS[sym].price / out.at(-1).close, r2 = v => +(v * k).toFixed(2);
    return out.map(c => ({ ...c, open: r2(c.open), high: r2(c.high), low: r2(c.low), close: r2(c.close) }));
  };
  const applyChartTheme = () => {
    const up = css('--up'), down = css('--down');
    chart.applyOptions({ layout: { background: { type: 'solid', color: 'transparent' }, textColor: css('--lg-sub'), fontFamily: 'JetBrains Mono, monospace' }, grid: { vertLines: { color: css('--glass-hairline') }, horzLines: { color: css('--glass-hairline') } }, rightPriceScale: { borderColor: css('--glass-hairline') }, timeScale: { borderColor: css('--glass-hairline') }, crosshair: { vertLine: { labelBackgroundColor: css('--lg-interactive') }, horzLine: { labelBackgroundColor: css('--lg-interactive') } } });
    candles.applyOptions({ upColor: up, downColor: down, borderUpColor: up, borderDownColor: down, wickUpColor: up, wickDownColor: down });
    volume.setData(volume._data.map(v => ({ ...v, color: (v.up ? up : down) + '59' })));
  };
  const openModal = (sym, opener) => {
    const s = STOCKS[sym]; lastFocus = opener;
    $('modalTitle').textContent = `${s.name} ${sym}`;
    $('modalCategory').textContent = s.lane;
    $('modalSub').textContent = `合成資料 · ${s.time} 觸發 · 現價 ${s.price.toFixed(2)} (${pct(s.chg)})`;
    $('modalYahoo').href = '#';
    $('modalKv').innerHTML = [['現價', s.price.toFixed(2), cls(s.chg)], ['漲跌', pct(s.chg), cls(s.chg)], ['模擬進場', s.entry.toFixed(2), ''], ['停損', s.stop.toFixed(2), 'lg-down'], ['停利', s.target.toFixed(2), 'lg-up'], ['量比', '2.4', '']]
      .map(([k, v, c]) => `<div class="glass-well"><small>${k}</small><b class="${c}">${v}</b></div>`).join('');
    $('modalReasons').innerHTML = s.tags.map(t => `<li>${esc(t)}</li>`).join('');
    $('modalRisk').textContent = '仍需設定停損並注意盤中突發量價反轉';
    modal.hidden = false;
    document.body.style.overflow = 'hidden';
    $('modalClose').focus();
    const data = series(sym), last = data.at(-1);
    $('chartLegend').innerHTML = `<span>日K · 70 根</span><span>O ${last.open}</span><span>H ${last.high}</span><span>L ${last.low}</span><span class="${cls(last.close - last.open)}">C ${last.close}</span>`;
    if (!window.LightweightCharts) { $('chartContainer').innerHTML = '<div class="empty">K 線元件載入中…</div>'; return; }
    const el = $('chartContainer'); el.innerHTML = '';
    chart = LightweightCharts.createChart(el, { width: el.clientWidth, height: el.clientHeight, timeScale: { timeVisible: false }, rightPriceScale: { scaleMargins: { top: .08, bottom: .24 } } });
    candles = chart.addCandlestickSeries();
    candles.setData(data.map(({ value, ...k }) => k));
    volume = chart.addHistogramSeries({ priceFormat: { type: 'volume' }, priceScaleId: '', lastValueVisible: false, priceLineVisible: false });
    volume.priceScale().applyOptions({ scaleMargins: { top: .8, bottom: 0 } });
    volume._data = data.map(k => ({ time: k.time, value: k.value, up: k.close >= k.open }));
    applyChartTheme();
    chart.timeScale().fitContent();
  };
  const closeModal = () => {
    modal.hidden = true; document.body.style.overflow = '';
    if (chart) { chart.remove(); chart = null; }
    lastFocus?.focus();
  };
  document.addEventListener('click', e => { const b = e.target.closest('.stock'); if (b) openModal(b.dataset.symbol, b); });
  $('modalClose').addEventListener('click', closeModal);
  modal.addEventListener('click', e => { if (e.target === modal) closeModal(); });
  document.addEventListener('keydown', e => {
    if (modal.hidden) return;
    if (e.key === 'Escape') { closeModal(); return; }
    if (e.key === 'Tab') {
      const f = [...modal.querySelectorAll('a[href],button:not([disabled])')];
      if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f.at(-1).focus(); }
      else if (!e.shiftKey && document.activeElement === f.at(-1)) { e.preventDefault(); f[0].focus(); }
    }
  });
  addEventListener('resize', () => { if (chart) chart.applyOptions({ width: $('chartContainer').clientWidth, height: $('chartContainer').clientHeight }); });

  // Review hooks for screenshots: ?open=T101 opens the modal, ?details=1 expands 資料與模型細節.
  const q = new URLSearchParams(location.search);
  if (q.get('details')) document.querySelector('.data-details').open = true;
  if (q.get('open') && STOCKS[q.get('open')]) addEventListener('load', () => openModal(q.get('open'), null));
})();
