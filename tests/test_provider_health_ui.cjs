const test=require('node:test'),assert=require('node:assert/strict');
const {createDOM,settle}=require('./dom.cjs');
const fs=require('node:fs');
const html='<section id="providerHealthCard"><span id="providerHealthChecked"></span><div id="providerHealthRows"></div></section>';
for(const status of ['UNKNOWN','MARKET_CLOSED','ONLINE'])test('public health renders '+status+' with a fixed provider allowlist',async()=>{
  const {w,run}=createDOM(html);w.AbortController=AbortController;
  w.fetch=async()=>({ok:true,json:async()=>({schema_version:1,generated_at:new Date().toISOString(),providers:{
    esun:{status},shioaji:{status},fugle:{status},firebase:{status},line:{status:'ONLINE'},telegram:{status:'ONLINE'},
    '<img onerror=alert(1)>':{status:'ONLINE'}}})});
  run('assets/provider-health.js');await settle();
  assert.equal(w.document.querySelectorAll('.provider-health-row').length,6);
  assert.equal(w.document.querySelector('[data-provider=esun]').dataset.status,status);
  assert(!w.document.getElementById('providerHealthRows').textContent.match(/LINE|Telegram|onerror/i));
  assert.equal(w.document.querySelectorAll('img').length,0);w.close();
});
test('expired or future summary cannot show a false ONLINE',async()=>{
  for(const generated of [new Date(Date.now()-600000).toISOString(),new Date(Date.now()+600000).toISOString()]){
    const {w,run}=createDOM(html);w.AbortController=AbortController;w.fetch=async()=>({ok:true,json:async()=>({schema_version:1,generated_at:generated,providers:{esun:{status:'ONLINE'}}})});
    run('assets/provider-health.js');await settle();assert.equal(w.document.querySelector('[data-provider=esun]').dataset.status,'UNKNOWN');w.close();
  }
});
test('authenticated admin renderer shows safe diagnostics as text',async()=>{
  const {w,run}=createDOM(fs.readFileSync('easystock_admin/static/index.html','utf8'));
  w.fetch=async url=>{
    let data={groups:[],deliveries:[]};
    if(url.endsWith('/session'))data={email:'test@example.test',csrf:'test-csrf'};
    if(url.endsWith('/settings'))data={values:{min_price:1,max_price:100,max_gain_pct:5},version:1};
    if(url.endsWith('/health'))data={signals:[],generated_at:new Date().toISOString(),provider_health:{market_state:'OPEN',
      market_data:{usable:true},providers:{esun:{status:'ONLINE',latency_ms:12,reconnect_count:2,
        error_code:'<img src=x onerror=alert(1)>',connected:true,subscribed:true},
        fugle:{status:'UNKNOWN',error_code:'not_configured',configured:false}},
      market_gate:{status:'current',market_level:'GREEN',data_health:'DEGRADED',selected_source:'esun',
        model_ready:true,radar_candidate_count:3,entry_block_evaluations:{market_data_unavailable:8},
        sources:{esun:{age_seconds:5},shioaji:{age_seconds:90}}}}};
    return {ok:true,json:async()=>data};
  };
  run('easystock_admin/static/admin.js');await settle();await settle();
  const target=w.document.getElementById('providerHealthDetails');
  assert(target.textContent.includes('延遲 ms 12'));assert(target.textContent.includes('重連次數 2'));
  assert(target.textContent.includes('未設定探測金鑰'));
  assert(target.textContent.includes('當沖市場閘門'));
  assert(target.textContent.includes('資料不可用攔截 8'));
  assert.equal(target.querySelectorAll('img').length,0);w.close();
});
