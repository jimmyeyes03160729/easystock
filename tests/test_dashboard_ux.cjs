const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {createDOM}=require('./dom.cjs');
const html=fs.readFileSync('index.html','utf8');
const main=[...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)].map(m=>m[1]).find(s=>s.includes('function taiwanDay('));
function setup(t,{stored,blocked=false,writeBlocked=false,withMain=false}={}) {
  const env=createDOM(html),{w,run,dom}=env;
  t.after(()=>w.close());
  w.fetch=async()=>{throw Error('test forbids network');};
  if(stored) w.localStorage.setItem('EASYSTOCK_WATCHLIST_V1',stored);
  if(blocked) Object.defineProperty(w,'localStorage',{get(){throw Error('blocked');}});
  if(writeBlocked) w.Storage.prototype.setItem=()=>{throw Error('quota');};
  run('assets/dashboard-ux.js');
  if(withMain){vm.runInContext(main,dom.getInternalVMContext());w.onload=null;}
  const evalCode=code=>vm.runInContext(code,dom.getInternalVMContext());
  return {...env,evalCode,ux:w.DashboardUX};
}
const stock=(symbol,name='測試股票')=>({symbol,name,price:100,updated_at:'2026-10-01'});
function search(w,q){const el=w.document.getElementById('stockSearch');el.value=q;el.dispatchEvent(new w.Event('input'));}
function click(w,label){const btn=[...w.document.querySelectorAll('#stockExplorer button')].find(b=>b.textContent===label);assert(btn,label);btn.click();}

test('truthful overview: independent daily/live validity, no claimed Live switches, measured request success/failure',t=>{
  const {w,ux}=setup(t);
  ux.update({stocks:[],meta:{updated_at:'2026-10-01'},live:{session:'closed',last_update_at:'2026-10-01T05:00:00Z'},health:{current:true},dailyValid:false});
  assert.match(w.document.getElementById('overviewSession').textContent,/歷史快照/);
  assert.match(w.document.getElementById('overviewValidity').textContent,/失效.*非即時/);
  assert.match(w.document.getElementById('dashboardOverview').textContent,/無法確認實盤開關/);
  ux.update({stocks:[],health:{label:'連線失敗',current:false,message:'保留最後成功快照'},dailyValid:true,dailyFetchState:'failed'});
  assert.match(w.document.getElementById('overviewValidity').textContent,/符合既有.*失效/);
  assert.match(w.document.getElementById('overviewValidity').textContent,/最近讀取失敗，保留最後快照/);
  ux.requestFinished(123.4,true);assert.match(w.document.getElementById('requestTiming').textContent,/123 ms/);
  ux.requestFinished(2000,false);assert.match(w.document.getElementById('footerRequestTiming').textContent,/失敗.*2000 ms.*非行情延遲/);
  assert(!html.includes('24ms'));assert(!html.includes('實盤當沖學習版本'));assert(!html.includes('TERMINAL_HUD_ONLINE'));
  assert(!w.document.querySelector('.dashboard-data-details').open);
  assert(w.document.querySelector('#dashboardOverview .ux-overview-grid'));
});

test('empty reasons use fresh backend evidence; unknown, stale, session, filters and model do not invent causes',t=>{
  const {ux}=setup(t),now=Date.parse('2026-10-01T02:00:00Z');
  const health={current:true};
  const base={health,now,live:{session:'daytrade'}};
  assert.match(ux.emptyReason(base),/目前沒有 OPEN.*不能由空清單推定/);
  assert.match(ux.emptyReason({...base,health:{current:false,message:'快照逾時'}}),/快照逾時/);
  assert.match(ux.emptyReason({...base,filtered:true}),/篩選隱藏/);
  for(const [session,label] of [['preopen','開盤前'],['closed','歷史'],['no_new_entry','停止新進場'],['force_exit','強制出場'],['unknown','待確認']])
    assert(ux.emptyReason({...base,live:{session}}).includes(label));
  const market_risk={checked_at:new Date(now-1000).toISOString(),gate_action:'BLOCK',gate_reason:'market_risk_red'};
  assert.match(ux.emptyReason({...base,live:{...base.live,market_risk}}),/市場風險紅燈/);
  market_risk.gate_reason='market_data_unavailable';assert.match(ux.emptyReason({...base,live:{...base.live,market_risk}}),/市場資料不可用/);
  market_risk.gate_reason='<script>untrusted</script>';assert.match(ux.emptyReason({...base,live:{...base.live,market_risk}}),/具體原因待確認/);
  for(const checked_at of ['bad',new Date(now-91000).toISOString(),new Date(now+61000).toISOString()])
    assert.match(ux.emptyReason({...base,live:{...base.live,market_risk:{...market_risk,checked_at,gate_reason:'market_risk_red'}}}),/不能由空清單推定/);
  assert.match(ux.emptyReason({...base,live:{session:'daytrade',config:{entry_mode:'model',model_ready:false}}}),/模型未就緒/);
});

test('mobile fields remain visible, 1000-share budget/range affect display only, clear restores all',t=>{
  const {w,evalCode}=setup(t,{withMain:true});
  for(const id of ['priceMin','priceMax','budgetInput']){
    const input=w.document.getElementById(id);
    assert(!input.parentElement.classList.contains('hidden'));assert(input.getAttribute('aria-label'));
  }
  assert.match(html,/每股價格快選（元）/);
  evalCode("COMPUTED_STOCKS=[{symbol:'A',price:40},{symbol:'B',price:100}];");
  w.document.getElementById('budgetInput').value='50000';evalCode('setBudget()');
  assert.equal(evalCode('priceFilteredStocks().map(s=>s.symbol).join()'),'A');
  w.document.getElementById('priceMin').value='200';w.document.getElementById('priceMax').value='50';evalCode('setPriceRange()');
  assert.match(w.document.getElementById('priceFilterStatus').textContent,/最低股價高於最高股價/);
  evalCode('clearDisplayFilters()');assert.equal(evalCode('priceFilteredStocks().length'),2);
  assert.equal(w.document.getElementById('budgetInput').value,'');
  assert.equal(w.localStorage.getItem('MOHREN_BUDGET_MAX'),null);
});

test('search by name/code, watch add/remove/reload and unavailable symbols; no HTML execution or eligibility fallback',t=>{
  const {w,ux}=setup(t,{stored:JSON.stringify({version:1,symbols:['OUT','OUT']})});
  const opened=[],stocks=[stock('2330','台積電'),stock('T1','<img src=x onerror=evil()>')];
  ux.update({stocks,meta:{updated_at:'2026-10-01'},openStock:s=>opened.push(s)});
  search(w,'台積');assert.match(w.document.getElementById('stockSearchResults').textContent,/2330/);
  click(w,'查看 2330');assert.deepEqual(opened,['2330']);
  click(w,'加入自選 2330');assert.equal(w.document.activeElement.textContent,'移除自選 2330');
  assert.deepEqual(JSON.parse(w.localStorage.getItem('EASYSTOCK_WATCHLIST_V1')).symbols,['OUT','2330']);
  assert.match(w.document.getElementById('stockWatchlist').textContent,/OUT.*不在目前股票池/);
  assert(![...w.document.querySelectorAll('#stockWatchlist button')].some(b=>b.textContent==='查看 OUT'));
  search(w,'T1');assert.equal(w.document.querySelector('#stockSearchResults img'),null);
  assert.match(w.document.getElementById('stockSearchResults').textContent,/<img/);
  search(w,'not-found');assert.match(w.document.getElementById('stockSearchStatus').textContent,/不代表股票不存在/);
  click(w,'移除自選 2330');assert.deepEqual(JSON.parse(w.localStorage.getItem('EASYSTOCK_WATCHLIST_V1')).symbols,['OUT']);
  search(w,'');assert.equal(w.document.getElementById('stockSearchResults').children.length,0);
  assert.equal(stocks.length,2);
});

test('watchlist reloads persisted selection, caps search, preserves focus across periodic live updates',t=>{
  const {w,ux}=setup(t,{stored:JSON.stringify({version:1,symbols:['T1']})});
  const stocks=Array.from({length:25},(_,i)=>stock('T'+i));
  ux.update({stocks,meta:{updated_at:'2026-10-01'}});search(w,'T');
  assert.equal(w.document.getElementById('stockSearchResults').children.length,20);
  assert.match(w.document.getElementById('stockSearchStatus').textContent,/25 檔.*前 20/);
  const button=w.document.querySelector('#stockSearchResults button');button.focus();
  ux.update({stocks,meta:{updated_at:'2026-10-01'},live:{session:'daytrade'},health:{current:true}});
  assert.equal(w.document.activeElement,button);
  assert.match(w.document.getElementById('stockWatchlist').textContent,/T1/);
});

test('100-symbol capacity is enforced; malformed/blocked/quota storage keeps memory-only fail-safe',t=>{
  const full=setup(t,{stored:JSON.stringify({version:1,symbols:Array.from({length:100},(_,i)=>'T'+i)})});
  full.ux.update({stocks:[stock('NEW')]});search(full.w,'NEW');click(full.w,'加入自選 NEW');
  assert.match(full.w.document.getElementById('watchlistStorageStatus').textContent,/已達 100/);
  assert.equal(JSON.parse(full.w.localStorage.getItem('EASYSTOCK_WATCHLIST_V1')).symbols.length,100);
  for(const options of [{stored:'{bad'}, {blocked:true}, {writeBlocked:true}]) {
    const {w,ux}=setup(t,options);ux.update({stocks:[stock('T')]});search(w,'T');click(w,'加入自選 T');
    assert.match(w.document.getElementById('stockWatchlist').textContent,/T/);
    assert.match(w.document.getElementById('watchlistStorageStatus').textContent,/記憶體/);
    if(options.stored) assert.equal(w.localStorage.getItem('EASYSTOCK_WATCHLIST_V1'),'{bad');
  }
});

test('production renderer integration retains offline historical warning, fresh-gate empty reason, no fake closed validity',async t=>{
  const {w,evalCode}=setup(t,{withMain:true});
  evalCode("INTRADAY_LIVE={last_update_at:new Date().toISOString(),session:'daytrade',market_risk:{checked_at:new Date().toISOString(),gate_action:'BLOCK',gate_reason:'market_risk_red'}};renderLiveIntraday();");
  assert.match(w.document.getElementById('intradayPickList').textContent,/市場風險紅燈/);
  evalCode("INTRADAY_LIVE.open_positions={OLD:{symbol:'OLD',entry_time:'2026-01-01T09:30:00+08:00',entry_price:100}};LIVE_FETCH_ERROR='offline';renderLiveIntraday();");
  assert.match(w.document.getElementById('intradayHealth').textContent,/讀取失敗.*並非今日訊號/);
  evalCode("LIVE_FETCH_ERROR='';INTRADAY_LIVE={last_update_at:'bad',session:'closed'};");
  assert.equal(evalCode('liveDataState().current'),false);
  evalCode("INTRADAY_LIVE={last_update_at:new Date(Date.now()+120000).toISOString(),session:'closed'};");
  assert.equal(evalCode('liveDataState().current'),false);
  w.fetch=async()=>({ok:true,json:async()=>({})});await evalCode("fetchJson('https://synthetic.invalid/summary')");
  assert.match(w.document.getElementById('requestTiming').textContent,/\d+ ms/);
  w.fetch=async()=>{throw Error('offline');};await assert.rejects(evalCode("fetchJson('https://synthetic.invalid/summary')"));
  assert.match(w.document.getElementById('requestTiming').textContent,/失敗/);
});
