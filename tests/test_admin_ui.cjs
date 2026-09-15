const assert=require('node:assert'),fs=require('node:fs');
const {createDOM,settle}=require('./dom.cjs');
(async()=>{
 const {w,run}=createDOM(fs.readFileSync('vm_runtime/easystock_admin/static/index.html','utf8'));
 const values={replies:true,groups:true,users:true,trade_push:true,other_push:false};
 let policy={values,version:1,conversations:[{id:'abc',kind:'group',label:'<img src=x onerror=alert(1)>',replies:1,push:1,version:1}]};
 const writes=[];
 w.fetch=async(url,options)=>{
  let data=url.endsWith('/session')?{email:'test@example.test',csrf:'test-csrf'}:url.endsWith('/settings')?{values:{min_price:1,max_price:100,max_gain_pct:5},version:1}:url.endsWith('/line-usage')?{used:197,limit:200,remaining:3}:policy;
  if(options.method==='PUT'){writes.push({url,options});data=policy={...policy,...JSON.parse(options.body),version:2};}
  return {ok:true,json:async()=>data};
 };
 run('vm_runtime/easystock_admin/static/admin.js');await settle();
 assert(!w.document.getElementById('workspace').hidden);
 assert.equal(w.document.querySelectorAll('[data-policy]').length,5);
 assert.equal(w.document.querySelectorAll('#conversationList img').length,0);
 const other=w.document.querySelector('[data-policy=other_push]');assert(!other.checked);
 const form=w.document.getElementById('linePolicyForm');
 form.dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));await settle();
 assert.equal(writes[0].options.headers['X-CSRF-Token'],'test-csrf');
 assert.equal(JSON.parse(writes[0].options.body).values.other_push,false);
 w.document.getElementById('checkUsage').click();await settle();
 assert(w.document.getElementById('lineUsage').textContent.includes('197 / 200'));
 w.close();console.log('PASS admin UI: authenticated settings, safe labels, switches, CSRF, quota display');
})().catch(e=>{console.error(e);process.exitCode=1;});
