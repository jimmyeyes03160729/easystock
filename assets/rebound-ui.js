(() => {
'use strict';
const el = id => document.getElementById(id), money = n => Number(n).toFixed(2);

function node(tag, text, cls) { 
    const e = document.createElement(tag); 
    if (text !== undefined) e.textContent = text; 
    if (cls) e.className = cls; 
    return e; 
}

// 建立波段觸底反彈的專屬卡片
function card(item, index) {
    const e = node('article', undefined, 'rebound-card');
    
    // 標題區
    const header = node('div', undefined, 'rebound-card-head');
    header.append(node('span', `TOP ${index + 1}`, 'rebound-rank'), node('span', `13:15 波段確認`, 'text-sub'));
    e.append(header);

    // 價格區
    const quote = node('div', undefined, 'rebound-quote');
    quote.append(node('h3', `${item.symbol} ${item.name || ''}`));
    const price = node('strong', money(item.price) + ' 元', 'rebound-price text-main');
    quote.append(price);
    e.append(quote);

    // 策略詳細數據 (預設展開)
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

    // 查看日 K 按鈕 (保留與你原本圖表功能的串接)
    const button = node('button', '查看日 K ↗', 'btn');
    button.type = 'button';
    button.addEventListener('click', () => {
        // 封裝一個符合舊版格式的物件，讓你的 K 線圖能畫出輔助線
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

// 從 Firebase 讀取今日 Python 算好的名單
async function refresh() {
    const status = el('reboundStatus'), picks = el('reboundPicks'), watch = el('reboundWatch'), progress = el('reboundProgress');
    
    // 清空舊畫面
    if (picks) picks.replaceChildren();
    if (watch) watch.replaceChildren();
    if (el('reboundWatchSection')) el('reboundWatchSection').hidden = true;
    if (el('reboundDiagnostics')) el('reboundDiagnostics').textContent = '';
    
    status.textContent = '正在載入本日 13:15 觸底反彈確認名單...';
    if (progress) progress.textContent = '由 Python 模型於雲端運算';

    // 取得台灣時間的今日日期 (YYYY-MM-DD)
    const tpeTime = new Date(new Date().getTime() + (8 * 60 * 60 * 1000));
    const todayStr = tpeTime.toISOString().split('T')[0];

    try {
        // 直接讀取我們 Python 寫入的新節點
        const snapshot = await firebase.database().ref(`market_data/rebound_picks/${todayStr}`).once('value');
        const data = snapshot.val();

        if (!data || !Array.isArray(data) || data.length === 0) {
            status.textContent = '本日 13:15 掃描完畢：沒有符合觸底反彈條件的股票。';
            return;
        }

        status.textContent = `本日 13:15 確認：共 ${data.length} 檔符合波段進場條件。`;
        data.forEach((item, i) => picks.append(card(item, i)));

    } catch (err) {
        console.error("讀取 Firebase 失敗:", err);
        status.textContent = '讀取資料失敗，請確認網路連線。';
    }
}

// 綁定到全域變數供主程式呼叫
window.RangeReboundUI = {
    refresh: refresh,
    
    // 配合新的資料結構畫出 K 線圖上的輔助線
    chart: (stock, series) => {
        const r = stock.rangeRebound;
        if (!r) return;
        const color = getComputedStyle(document.documentElement).getPropertyValue('--main').trim() || '#888888';
        
        series.createPriceLine({ price: r.stop_loss, color: '#e74c3c', lineWidth: 2, lineStyle: 2, axisLabelVisible: true, title: '防守價' });
        series.createPriceLine({ price: r.target, color: '#2ecc71', lineWidth: 2, lineStyle: 2, axisLabelVisible: true, title: '目標價' });
    },
    
    // 簡化細節面板 (因為運算都在 Python 做完了)
    detail: (stock) => {
        if(el('stockBacktest')) el('stockBacktest').textContent = '此為 13:15 盤中即時波段確認訊號。';
    }
};

// 綁定重新整理按鈕
if (el('reboundRetry')) {
    el('reboundRetry').addEventListener('click', refresh);
}

// 等待 Firebase 初始化後自動載入
const autoLoad = setInterval(() => {
    if (typeof firebase !== 'undefined' && firebase.database) {
        clearInterval(autoLoad);
        refresh();
    }
}, 500);

})();
