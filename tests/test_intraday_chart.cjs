const {createDOM,settle}=require('./dom.cjs'),assert=require('node:assert/strict');
(async()=>{
 const {dom,w,run}=createDOM('<button data-trade-symbol="2330" data-trade-entry="2026-09-22T09:30:00+08:00">查看</button>');
 w.HTMLDialogElement.prototype.showModal=function(){this.open=true};w.HTMLDialogElement.prototype.close=function(){this.open=false;this.dispatchEvent(new w.Event('close'))};
 w.INTRADAY_LIVE={closed_trades:[{symbol:'2330',name:'台積電',entry_time:'2026-09-22T09:30:00+08:00',exit_time:'2026-09-22T09:45:00+08:00',entry_price:100,exit_price:101,pnl_pct:.4,entry_reasons:['<img src=x onerror=alert(1)>']}]};
 let date='2026-09-22';w.fetch=async()=>({ok:true,json:async()=>({date,updated_at:date+'T14:00:00+08:00',bars:[{time:date+'T09:30:00+08:00',open:100,high:102,low:99,close:101,volume:100}]})});
 run('assets/intraday-chart.js');w.document.querySelector('button').click();await settle();
 assert(w.document.querySelector('#tradeStatus').classList.contains('trade-closed'));assert(w.document.querySelector('#tradeChart svg'));assert.equal(w.document.querySelector('#tradeReasons img'),null);assert(w.document.querySelector('#tradeOutcome').textContent.includes('0.40%'));
 w.document.querySelector('#tradeDialog button').click();date='2026-09-21';w.document.querySelector('button').click();await settle();assert.equal(w.document.querySelector('#tradeChart svg'),null);assert(w.document.querySelector('#tradeChartNote').textContent.includes('尚無可用'));
 // A research-only signal must not read as a Paper buy; it names why Paper skipped.
 w.document.querySelector('#tradeDialog button').click();date='2026-09-22';
 Object.assign(w.INTRADAY_LIVE.closed_trades[0],{paper_execution:'SKIPPED',paper_skip_reason:'quote_unavailable',research_net_pnl_pct:-1.11,model_score:.649,model_threshold:.6,
  paper_skip_detail:{eligibility_detail:'day_trade=Yes category=24',quote_error:'snapshot_failed:TimeoutError'}});
 w.document.querySelector('button').click();await settle();
 const text=w.document.querySelector('#tradeOutcome').textContent;
 assert(text.startsWith('研究訊號進場')&&!text.includes('模擬買入'),text);
 assert(text.includes('扣成本報酬 -1.11%')&&text.includes('模擬帳本未成交：報價取得失敗（day_trade=Yes category=24，snapshot_failed:TimeoutError）'),text);
 assert(w.document.querySelector('#tradeModelReason').textContent.includes('未實際模擬成交'));
 const s=w.paperExecutionStatus;
 assert.equal(JSON.stringify(s({execution_kind:'paper_fill',shares:1000})),JSON.stringify({filled:true,label:'模擬已成交',text:'模擬帳本已成交 1,000 股。'}));
 assert.equal(s({paper_execution:'SKIPPED',paper_skip_reason:'daytrade_eligibility_unknown'}).text,'模擬帳本未成交：無法確認可否當沖。');
 assert.equal(s({}),null);
 dom.window.close();console.log('PASS trade chart: closed state, OHLC, entry/exit, escaped evidence, reject wrong session, research vs Paper status');
})().catch(e=>{console.error(e);process.exitCode=1});
