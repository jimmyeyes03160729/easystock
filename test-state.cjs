// Real DOM behavior, with only networking stubbed. No production reads or writes.
const assert=require('assert');
const {createDOM,settle}=require('./tests/dom.cjs');
async function setup(history,failHistory=false){
 const {dom,w,run}=createDOM();
 const daily={schema_version:1,updated_at:new Date().toISOString(),phase:'idle',today:{date:new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Taipei'}).format(new Date()),learned_stocks:2,labeled_count:7},totals:{learning_days:1,training_days:1,training_samples:488},model_application:{status:'not_applied'}};
 w.fetch=async url=>{
   if(url.includes('history_training')&&failHistory)return {ok:false,status:403};
   return {ok:true,json:async()=>url.includes('history_training')?history:daily};
  };
 run('assets/learning-status.js');
 await settle();
 const entries=[...w.document.querySelectorAll('[id]')].map(n=>[n.id,n]);
 assert.equal(new Set(entries.map(([id])=>id)).size,entries.length,'duplicate IDs');
 const nodes=new Map(entries),styles=[...w.document.querySelectorAll('style')].map(n=>n.textContent);
 const root={html:w.document.getElementById('learningSection').innerHTML};
 dom.window.close();
 return {nodes,styles,root};
}
(async()=>{
 const history={schema_version:1,updated_at:new Date().toISOString(),run:{state:'replaying',processed_files:500,archive_files:1187,labeled_samples:2000},training:{},archive:{archived_stock_days:1187,target_stock_days:6600,failed_stock_days:1,stop_reason:'quota_exhausted'},model_application:{status:'not_applied'}};
 let r=await setup(history);const text=id=>r.nodes.get(id).textContent;
 assert.equal(text('historyPhase'),'歷史重播中');assert.equal(text('learnDays'),'1');
 assert.equal(text('historySamples'),'2,000');assert.equal(text('historyDays'),'—');
 assert.equal(text('historyTestSamples'),'—');assert(r.root.html.indexOf('每日資料訓練')<r.root.html.indexOf('歷史資料訓練'));
 assert(r.styles.join('').includes('@media(max-width:900px)'));
 assert.equal((r.root.html.match(/class="learning-column"/g)||[]).length,2);
 r=await setup({...history,updated_at:new Date(Date.now()-600000).toISOString()});assert(text('historyPhase').includes('更新逾時'));
 r=await setup({...history,run:{...history.run,state:'completed'},training:{status:'experimental_candidate',test_samples:200,model_selected:{samples:0,positive_markout_rate:null,mean_net_markout_pct:null}}});
 assert(text('historyResult').includes('正報價表現率 —'));assert(!text('historyResult').includes('NaN'));
 r=await setup(history,true);assert(text('historyError').includes('未授權'));assert.equal(text('learnDays'),'1');
 r=await setup(null);assert(text('historyError').includes('等待 VM'));
 console.log('PASS: independent daily/history values, two-column markup, mobile CSS, no duplicate IDs, stale summary, null results, permission/missing states.');
})().catch(e=>{console.error(e);process.exit(1)});
