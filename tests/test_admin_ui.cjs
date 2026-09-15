const assert=require('node:assert'),fs=require('node:fs');
const {createDOM,settle}=require('./dom.cjs');
(async()=>{
 const {w,run}=createDOM(fs.readFileSync('vm_runtime/easystock_admin/static/index.html','utf8'));
 let state={groups:[{id:'abc',platform:'line',kind:'group',label:'<img src=x onerror=alert(1)>',replies:true,push:true,version:1},{id:'configured',platform:'telegram',kind:'group',label:'Telegram 群組',configured:true,push:true,version:1}],deliveries:[]};
 const writes=[];
 w.fetch=async(url,options)=>{
  let data=url.endsWith('/session')?{email:'test@example.test',csrf:'test-csrf'}:url.endsWith('/settings')?{values:{min_price:1,max_price:100,max_gain_pct:5},version:1}:url.endsWith('/line-usage')?{used:197,limit:200,remaining:3}:state;
  if(options.method==='PUT'){writes.push({url,options});const values=JSON.parse(options.body),platform=url.split('/').at(-2);state={...state,groups:state.groups.map(g=>g.platform===platform?{...g,...values,version:g.version+1}:g)};data=state;}
  return {ok:true,json:async()=>data};
 };
 run('vm_runtime/easystock_admin/static/admin.js');await settle();
 assert(!w.document.getElementById('workspace').hidden);
 assert(!w.document.getElementById('bind'));
 assert.equal(w.document.querySelectorAll('#conversationList input[type=checkbox]').length,4);
 assert.equal(w.document.querySelectorAll('#conversationList img').length,0);
 const toggle=w.document.querySelector('[data-platform=telegram]');toggle.checked=false;
 toggle.closest('form').dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));await settle();
 assert(writes[0].url.endsWith('/notification-groups/telegram/configured'));
 assert.equal(writes[0].options.headers['X-CSRF-Token'],'test-csrf');
 assert.deepEqual(JSON.parse(writes[0].options.body),{push:false,replies:false,version:1});
 assert(w.document.querySelector('[data-platform=line]').checked);
 w.document.querySelector('[data-platform=line]').closest('form').dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));await settle();
 assert.deepEqual(JSON.parse(writes[1].options.body),{push:true,version:1,replies:true});
 w.document.getElementById('checkUsage').click();await settle();
 assert(w.document.getElementById('lineUsage').textContent.includes('197 / 200'));
 state={groups:[{...state.groups[1],configured:false}],deliveries:[{channel:'telegram',status:'unknown',at:1}]};
 w.document.getElementById('reloadLine').click();await settle();
 assert(w.document.querySelector('[data-platform=telegram]').disabled);
 assert(w.document.getElementById('deliveryStatus').textContent.includes('結果不明'));
 w.close();console.log('PASS admin UI: group-only, independent switches, safe labels, CSRF, quota/status display');
})().catch(e=>{console.error(e);process.exitCode=1;});
