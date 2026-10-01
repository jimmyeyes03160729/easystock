const assert=require('node:assert'),fs=require('node:fs');
const {createDOM,settle}=require('./dom.cjs');
(async()=>{
 const {w,run}=createDOM(fs.readFileSync('vm_runtime/easystock_admin/static/index.html','utf8'));
 let state={version:1,line:{configured:true,trade:true,summary:false},telegram:{configured:true,trade:false,summary:true},deliveries:[{channel:'line',kind:'trade',status:'sent',at:1}]};
 const writes=[];
 w.fetch=async(url,options={})=>{
   let data={};
   if(url.endsWith('/session'))data={email:'test@example.test',csrf:'test-csrf'};
   else if(url.endsWith('/settings'))data={values:{min_price:1,max_price:100,max_gain_pct:5,max_recommendations:30},version:1};
   else if(url.endsWith('/notifications'))data=state;
   else if(url.endsWith('/line-quota'))data={used:35,limit:200,remaining:165,checked_at:1};
   else if(url.includes('pipeline-settings'))data={values:{history_target_symbols:100,history_symbols:[],history_max_pairs:5,history_weekends:false,history_window_start:'14:00',history_window_end:'22:00',learning_enabled:true,learning_time:'16:10',min_training_dates:101,min_training_samples:1000,min_class_samples:30,holdout_days:20,model_retrain_every_days:5,forward_observe_days:20,formal_candidate_for_live:false,model_threshold:.6,fee_rate:.0015,sell_tax_rate:.003,slippage_bps:10,shares:1000},version:1};
   if(options.method==='PUT'&&url.endsWith('/notifications')){const body=JSON.parse(options.body);writes.push({url,options,body});state={version:2,line:{configured:true,trade:body.line_trade,summary:body.line_summary},telegram:{configured:true,trade:body.telegram_trade,summary:body.telegram_summary},deliveries:[]};data=state;}
   return {ok:true,json:async()=>data};
 };
 run('vm_runtime/easystock_admin/static/admin.js');await settle();
 assert(!w.document.getElementById('workspace').hidden);
 assert.equal(w.document.querySelectorAll('#notificationForm input[type=checkbox]').length,4);
 assert(w.document.getElementById('lineTrade').checked);
 assert(w.document.getElementById('telegramSummary').checked);
 w.document.getElementById('lineSummary').checked=true;
 w.document.getElementById('notificationForm').dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));await settle();
 assert.equal(writes[0].options.headers['X-CSRF-Token'],'test-csrf');
 assert.deepEqual(writes[0].body,{line_trade:true,line_summary:true,telegram_trade:false,telegram_summary:true,version:1});
 w.document.getElementById('checkUsage').click();await settle();
 assert(w.document.getElementById('lineUsage').textContent.includes('剩餘：165'));
 assert(!w.document.body.textContent.includes('群組'));
 w.close();console.log('PASS admin UI: personal notification switches and quota');
})().catch(e=>{console.error(e);process.exitCode=1;});
