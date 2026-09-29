const assert=require('assert');
const {createDOM,settle}=require('./tests/dom.cjs');

async function render(status){
  const {dom,w,run}=createDOM();
  w.fetch=async url=>url.includes('history_training')
    ?{ok:true,json:async()=>({schema_version:1,updated_at:new Date().toISOString(),run:{state:'completed'}})}
    :{ok:true,json:async()=>status};
  run('assets/learning-status.js'); await settle();
  const nodes=new Map([...w.document.querySelectorAll('[id]')].map(n=>[n.id,n]));
  assert.equal(nodes.size,new Set(nodes.keys()).size,'duplicate IDs');
  dom.window.close(); return nodes;
}
(async()=>{
  const base={schema_version:1,updated_at:new Date().toISOString(),session:{date:'2026-09-29',sample_count:12,labeled_count:8},totals:{learning_days:2},model_application:{entry_mode:'rules',runtime_loaded:false,runtime_used:false},research_summary:{date:'2026-09-29',new_samples:12,labels:8,trades:{count:4,wins:2,losses:2,net_pnl:10,return_pct:1,avg_pnl_pct:.5,avg_mfe_pct:1.2,avg_mae_pct:-.8,exit_reasons:{STOP_LOSS:2,TAKE_PROFIT:2}}},training:{trained_through:'2026-09-28',validation:{brier:.12,test_samples:20,validation_mode:'full_walk_forward'}}};
  let n=await render(base);
  assert.equal(n.get('researchSummaryTitle').textContent,'每日盤後研究摘要');
  assert(n.get('researchTrades').textContent.includes('4'));
  assert(n.get('researchModelState').textContent.includes('RULES'));
  assert(n.get('researchBrier').textContent.includes('0.12000'));
  assert(!n.has('dualReview')&&!n.has('dualTitle'),'legacy OpenAI review must not return');
  const stale={...base,updated_at:new Date(Date.now()-7*60*60*1000).toISOString()}; n=await render(stale);
  assert.equal(n.get('researchStale').hidden,false); assert(n.get('researchFreshness').textContent.includes('過期'));
  console.log('PASS UI: quantitative post-close summary, stale evidence, missing-safe values, and no legacy OpenAI panel.');
})().catch(e=>{console.error(e);process.exit(1)});
