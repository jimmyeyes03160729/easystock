const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs');
const {createDOM,settle}=require('./dom.cjs');
const html=fs.readFileSync('easystock_admin/static/index.html','utf8');
function fixture(t){
  const {w,run}=createDOM(html);t.after(()=>w.close());
  const get=id=>w.document.getElementById(id),calls=[];
  const state={ordering_guard:true,broker_fresh:true,broker:{authenticated:true,complete:true,account:{account_id:'***6543'},updated_at:'2026-10-07T09:00:00+08:00',
    positions:[{symbol:'2330',name:'<img src=x onerror=alert(1)>',quantity:2000,available_to_sell:1000,average_price:100,current_price:101,unrealized_pnl:2000}],
    orders:[{symbol:'2330',side:'BUY',qty:1000,filled_qty:500,status:'PartFilled'}],deals:[{symbol:'2330',side:'BUY',qty:500,price:100}]}};
  let outcome={ok:true,trade:{order_id:'ORDER1',status:'Submitted'}},status=200,networkError=false,unauthorized=false;
  w.csrf='test-csrf';w.confirm=()=>true;
  w.fetch=async(url,options={})=>{
    const body=options.body?JSON.parse(options.body):undefined;calls.push({url,options,body});
    if(networkError)throw Error('offline');
    if(unauthorized)return {ok:false,status:401,json:async()=>({error:'請先使用 Google 登入。'})};
    const data=url.endsWith('/sell-verify')?{verification_id:'ticket',expires_in:60,available_to_sell:1000,account:{account_id:'***6543'}}:
      url.endsWith('/place')?outcome:url.endsWith('/quote')?{ok:true,quote:{symbol:'2330',name:'Test',close:100,change_pct:0,bids:[{price:99,volume:1}],asks:[{price:100,volume:2}]}}:state;
    const code=url.endsWith('/place')?status:200;
    return {ok:code<400,status:code,json:async()=>data};
  };
  run('easystock_admin/static/order.js');
  const login=async()=>{get('workspace').hidden=false;w.document.dispatchEvent(new w.Event('easystock:owner-ready'));await settle();};
  const input=(id,value)=>{get(id).value=value;get(id).dispatchEvent(new w.Event('input',{bubbles:true}));};
  const fill=()=>{input('orderSymbol','2330');input('orderPrice',100);input('orderQty',10);input('orderCaPasswd','fake-test-password');};
  return {w,run,get,calls,state,login,input,fill,setOutcome:(value,code=200)=>{outcome=value;status=code;},failNetwork:()=>{networkError=true;},expireSession:()=>{unauthorized=true;}};
}
test('manual ordering is inside login workspace, after notifications and before live console',async t=>{
  const f=fixture(t);
  assert.equal(f.get('openOrderModal'),null);assert.equal(f.get('orderModal'),null);
  assert(f.get('workspace').contains(f.get('manualOrderPanel')));assert(f.get('workspace').hidden);assert(f.get('manualOrderPanel').hidden);
  assert(f.get('btnOrderSubmit').disabled);assert.equal(f.calls.length,0);
  f.w.showAdminTab=()=>{};f.w.api=async()=>f.state;f.run('easystock_admin/static/live-console.js');
  assert.deepEqual([...f.w.document.querySelectorAll('[data-admin-tab]')].slice(-3).map(n=>n.dataset.adminTab),['conversationPanel','manualOrderPanel','liveConsolePanel']);
  f.get('btnOrderVerify').click();assert.equal(f.calls.length,0);
});
test('holdings and broker order/fill results are read only and safely rendered after login',async t=>{
  const f=fixture(t);await f.login();
  assert(f.get('orderPositions').textContent.includes('2000'));assert(f.get('orderPositions').textContent.includes('1000'));
  assert.equal(f.get('orderPositions').querySelectorAll('img').length,0);
  assert(f.get('orderOrders').textContent.includes('部分成交'));assert(f.get('orderDeals').textContent.includes('500'));
  assert(f.calls.every(c=>!c.url.endsWith('/place')));
  f.state.broker.complete=false;await f.w.loadManualOrders();
  assert.match(f.get('orderPositions').textContent,/尚未完整同步/);assert.equal(f.get('orderPositions').querySelectorAll('button').length,0);
});
test('BUY sends exactly once with CSRF, clears password and distinguishes accepted from filled',async t=>{
  const f=fixture(t);await f.login();f.fill();
  f.get('btnOrderSubmit').click();f.get('btnOrderSubmit').click();await settle();
  const submitted=f.calls.filter(c=>c.url.endsWith('/place'));assert.equal(submitted.length,1);
  assert.equal(submitted[0].body.action,'BUY');assert.equal(submitted[0].body.quantity,10);assert.equal(submitted[0].options.headers['X-CSRF-Token'],'test-csrf');
  assert.match(f.get('orderResult').textContent,/買進委託：已受理，等待成交/);assert.equal(f.get('orderCaPasswd').value,'');
  assert(f.calls.filter(c=>c.url.endsWith('/live-console')).length>=2);
});
test('holding SELL uses existing server verification and exact confirmed order fields',async t=>{
  const f=fixture(t);await f.login();f.get('orderPositions').querySelector('button').click();
  assert.equal(f.get('orderSymbol').value,'2330');assert.equal(f.get('orderQty').value,'999');assert(!f.get('orderSellVerification').hidden);assert(f.get('btnOrderSubmit').disabled);
  f.input('orderQty',10);f.get('btnOrderSellVerify').click();await settle();
  const verified=f.calls.find(c=>c.url.endsWith('/sell-verify'));
  assert.equal(verified.body.action,'SELL');assert(!('ca_passwd' in verified.body));
  f.input('orderSellConfirm','SELL');f.input('orderSellAccount','***6543');f.input('orderCaPasswd','fake-test-password');
  assert(!f.get('btnOrderSubmit').disabled);f.get('btnOrderSubmit').click();await settle();
  const sent=f.calls.find(c=>c.url.endsWith('/place')).body;
  assert.equal(sent.action,'SELL');assert.equal(sent.sell_verification_id,'ticket');assert.equal(sent.confirm_sell,'SELL');assert.equal(sent.confirm_account,'***6543');assert.equal(sent.client_order_id,verified.body.client_order_id);
  assert.match(f.get('orderResult').textContent,/賣出委託：已受理/);assert.equal(f.get('orderCaPasswd').value,'');
});
test('SELL is invalidated by changing its price, symbol, unit or quick quantity',async t=>{
  const f=fixture(t);await f.login();f.fill();f.get('btnOrderSell').click();
  for(const change of [()=>f.input('orderPrice',101),()=>f.input('orderSymbol','2330'),()=>f.get('btnUnitSheet').click(),()=>f.get('quickQtyBtns').querySelector('button').click()]){
    f.get('btnOrderSellVerify').click();await settle();f.input('orderSellConfirm','SELL');f.input('orderSellAccount','***6543');f.input('orderCaPasswd','fake-test-password');assert(!f.get('btnOrderSubmit').disabled);
    change();assert(f.get('btnOrderSubmit').disabled);assert.equal(f.get('orderCaPasswd').value,'');
  }
  assert(!f.calls.some(c=>c.url.endsWith('/place')));
});
test('broker rejection and ambiguous submission show distinct results; unknown outcomes cannot be retried',async t=>{
  const f=fixture(t);await f.login();f.fill();f.setOutcome({ok:true,trade:{order_id:'ORDER1',status:'Failed'}});
  f.get('btnOrderSubmit').click();await settle();assert.match(f.get('orderResult').textContent,/委託失敗／拒絕/);assert(f.get('orderResult').classList.contains('error'));
  f.fill();f.setOutcome({ok:false,message:'委託結果尚未確認，請對帳，勿重送。'},400);
  f.get('btnOrderSubmit').click();await settle();assert.match(f.get('orderResult').textContent,/尚未確認/);assert(f.get('btnOrderSubmit').disabled);assert.equal(f.get('orderCaPasswd').value,'');
  const count=f.calls.filter(c=>c.url.endsWith('/place')).length;f.get('btnOrderSubmit').click();await settle();assert.equal(f.calls.filter(c=>c.url.endsWith('/place')).length,count);
});
test('failed reads clear old holdings; logout clears private data and certificate password',async t=>{
  const f=fixture(t);await f.login();f.failNetwork();await f.w.loadManualOrders();
  assert.equal(f.get('orderPositions').children.length,0);assert(f.get('btnOrderSubmit').disabled);
  f.input('orderCaPasswd','fake-test-password');f.get('logout').click();assert.equal(f.get('orderCaPasswd').value,'');
  assert.equal(f.get('orderPositions').children.length,0);assert(f.get('btnOrderSubmit').disabled);
});
test('actual filled response reports completion; cancelling confirmation never submits',async t=>{
  const f=fixture(t);await f.login();f.fill();f.w.confirm=()=>false;
  f.get('btnOrderSubmit').click();await settle();assert(!f.calls.some(c=>c.url.endsWith('/place')));
  f.w.confirm=()=>true;f.setOutcome({ok:true,trade:{order_id:'ORDER1',status:'Status.Filled'}});
  f.get('btnOrderSubmit').click();await settle();assert.match(f.get('orderResult').textContent,/全部成交/);
});
test('expired Google session hides the trading workspace and clears private information',async t=>{
  const f=fixture(t);await f.login();f.fill();f.expireSession();await f.w.loadManualOrders();
  assert(f.get('workspace').hidden);assert(!f.get('login').hidden);assert(!f.get('retryLogin').hidden);
  assert.equal(f.get('orderCaPasswd').value,'');assert.equal(f.get('orderPositions').children.length,0);assert(f.get('btnOrderSubmit').disabled);
});
