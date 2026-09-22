const {createDOM,settle}=require('./dom.cjs'),assert=require('node:assert/strict');
(async()=>{
 const {dom,w,run}=createDOM('<button data-trade-symbol="2330" data-trade-entry="2026-09-22T09:30:00+08:00">查看</button>');
 w.HTMLDialogElement.prototype.showModal=function(){this.open=true};w.HTMLDialogElement.prototype.close=function(){this.open=false;this.dispatchEvent(new w.Event('close'))};
 w.INTRADAY_LIVE={closed_trades:[{symbol:'2330',name:'台積電',entry_time:'2026-09-22T09:30:00+08:00',exit_time:'2026-09-22T09:45:00+08:00',entry_price:100,exit_price:101,pnl_pct:.4,entry_reasons:['<img src=x onerror=alert(1)>']}]};
 let date='2026-09-22';w.fetch=async()=>({ok:true,json:async()=>({date,updated_at:date+'T14:00:00+08:00',bars:[{time:date+'T09:30:00+08:00',open:100,high:102,low:99,close:101,volume:100}]})});
 run('assets/intraday-chart.js');w.document.querySelector('button').click();await settle();
 assert(w.document.querySelector('#tradeStatus').classList.contains('trade-closed'));assert(w.document.querySelector('#tradeChart svg'));assert.equal(w.document.querySelector('#tradeReasons img'),null);assert(w.document.querySelector('#tradeOutcome').textContent.includes('0.40%'));
 w.document.querySelector('#tradeDialog button').click();date='2026-09-21';w.document.querySelector('button').click();await settle();assert.equal(w.document.querySelector('#tradeChart svg'),null);assert(w.document.querySelector('#tradeChartNote').textContent.includes('尚無可用'));
 dom.window.close();console.log('PASS trade chart: closed state, OHLC, entry/exit, escaped evidence, reject wrong session');
})().catch(e=>{console.error(e);process.exitCode=1});
