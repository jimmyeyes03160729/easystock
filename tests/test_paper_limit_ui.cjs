const assert=require('node:assert'),fs=require('node:fs');
const {createDOM,settle}=require('./dom.cjs');
(async()=>{
  const html=fs.readFileSync('easystock_admin/static/index.html','utf8');
  assert(!html.includes('模擬起始本金'));
  assert(!html.includes('目前可用資金'));
  const {w,run}=createDOM(html);
  w.document.getElementById('workspace').hidden=false;
  const writes=[];
  const state={settings:{daily_buy_limit:1000000,daily_buy_used:650000,daily_buy_remaining:350000,
    realized_pnl:1000,fees:80,tax:152,net_pnl:768,cumulative_net_pnl:83500,equity:1083500,
    return_pct:0.118,status:'running',start_date:'2026-10-01'},positions:[],events:[],logs:[]};
  w.fetch=async(url,options={})=>{
    if (options.method==='POST') {
      writes.push(JSON.parse(options.body));
      state.settings.daily_buy_limit=writes[0].daily_buy_limit;
      state.settings.daily_buy_remaining=state.settings.daily_buy_limit-state.settings.daily_buy_used;
    }
    return {ok:true,json:async()=>url==='/admin/session'?{csrf:'fixture-csrf'}:state};
  };
  run('easystock_admin/static/paper-trade.js');await settle();
  assert.equal(w.document.getElementById('simRemaining').textContent,'350,000 元');
  assert.equal(w.document.getElementById('simUsed').textContent,'650,000 元');
  assert.equal(w.document.getElementById('simNetPnl').textContent,'768 元');
  assert.equal(w.document.getElementById('simEquity').textContent,'1,083,500 元');
  assert.equal(w.document.getElementById('simDailyLimitInput').value,'1000000');
  w.document.getElementById('simDailyLimitInput').value='2000000';
  w.document.getElementById('paperTradeForm').dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));
  await settle();
  assert.deepEqual(writes,[{daily_buy_limit:2000000}]);
  assert.equal(w.document.getElementById('simRemaining').textContent,'1,350,000 元');
  assert.equal(w.document.getElementById('simUsed').textContent,'650,000 元');
  w.close();console.log('PASS paper limit UI: usage, fees, equity and daily-limit payload');
})().catch(e=>{console.error(e);process.exitCode=1;});
