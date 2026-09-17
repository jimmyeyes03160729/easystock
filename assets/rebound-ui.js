(() => {
'use strict';
const el = id => document.getElementById(id), money = n => Number(n).toFixed(2);
const FIREBASE_ROOT = 'https://easystock-c237a-default-rtdb.firebaseio.com/market_data';

function node(tag, text, cls) { 
    const e = document.createElement(tag); 
    if (text !== undefined) e.textContent = text; 
    if (cls) e.className = cls; 
    return e; 
}

function card(item, index) {
    const e = node('article', undefined, 'rebound-card');
    
    const header = node('div', undefined, 'rebound-card-head');
    header.append(node('span', `TOP ${index + 1}`, 'rebound-rank'), node('span', `13:15 波段確認`, 'text-sub'));
    e.append(header);

    const quote = node('div', undefined, 'rebound-quote');
    quote.append(node('h3', `${item.symbol} ${item.name || ''}`));
    const price = node('strong', money(item.price) + ' 元', 'rebound-price text-main');
    quote.append(price);
    e.append(quote);

    const details = node('details');
    details.open = true; 
    const summary = node('summary', '波段防守與目標價');
    details.append(summary);

    const grid = node('dl', undefined, 'rebound-levels');
    grid.append(node('dt', '防守價 (停損)'), node('dd', money(item.stop_loss)));
    grid.append(node('dt', '目標價 (月線)'), node('dd', money(item.target)));
    details.append(grid);

    details.append(node('p', '★ 突破昨高 · 收紅K · 近5日報酬轉正', 'rebound-pass'));
    e.append(details);

    const button = node('button', '查看日 K ↗', 'btn');
    button.type = 'button';
    button.addEventListener('click', () => {
        const mockStock = {
            symbol: item.symbol,
            rangeRebound: {
                stop_loss: item.stop_loss,
                target: item.target
            }
        };
        if (typeof openStockDetail === 'function') {
            openStockDetail(String(item.symbol), 'RANGE_REBOUND', mockStock);
        }
    });
    e.append(button);

    return e;
}

async function refresh() {
    const status = el('reboundStatus'), picks = el('reboundPicks'), watch = el('reboundWatch'), progress = el('reboundProgress');
    
    if (picks) picks.replaceChildren();
    if (watch) watch.replaceChildren();
    if (el('reboundWatchSection')) el('reboundWatchSection').hidden = true;
    if (el('reboundDiagnostics')) el('reboundDiagnostics').textContent = '';
    
    status.textContent = '正在載入本日 13:15 觸底反彈名單...';
    if (progress) progress.textContent = '由 Python 模型於雲端運算';

    const tpeTime = new Date(new Date().getTime() + (8 * 60 * 60 * 1000));
    const todayStr = tpeTime.toISOString().split('T')[0];

    try {
        const res = await fetch(`${FIREBASE_ROOT}/rebound_picks/${todayStr}.json`, { cache: 'no-store' });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();

        if (!data || !Array.isArray(data) || data.length === 0) {
            status.textContent = '本日 13:15 掃描完畢：沒有符合觸底反彈條件的股票。';
            return;
        }

        status.textContent = `本日 13:15 確認：共 ${data.length} 檔符合波段進場條件。`;
        data.forEach((item, i) => picks.append(card(item, i)));

    } catch (err) {
        status.textContent = '本日 13:15 尚未產生波段資料，或尚無選股結果。';
    }
}

window.RangeReboundUI = {
    refresh: refresh,
    chart: (stock, series) => {
        const r = stock.rangeRebound;
        if (!r) return;
        series.createPriceLine({ price: r.stop_loss, color: '#e74c3c', lineWidth: 2, lineStyle: 2, axisLabelVisible: true, title: '防守價' });
        series.createPriceLine({ price: r.target, color: '#2ecc71', lineWidth: 2, lineStyle: 2, axisLabelVisible: true, title: '目標價' });
    },
    detail: (stock) => {
        if(el('stockBacktest')) el('stockBacktest').textContent = '此為 13:15 盤中即時波段確認訊號。';
    }
};

if (el('reboundRetry')) {
    el('reboundRetry').addEventListener('click', refresh);
}

refresh();
})();
