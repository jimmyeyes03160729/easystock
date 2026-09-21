const assert=require('assert');
const {createDOM,settle}=require('./tests/dom.cjs');

// Exercise the current OpenAI-only daily review. The previous paired
// Gemini/OpenAI contract was retired; do not restore its DOM to satisfy tests.
async function render(review,networkFail=false){
 const {dom,w,run}=createDOM();
 const today=new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Taipei'}).format(new Date());
 w.fetch=async url=>{
   if(url.includes('dual_review'))return networkFail?{ok:false,status:403}:{ok:true,json:async()=>review};
   if(url.includes('history_training'))return {ok:true,json:async()=>({schema_version:1,updated_at:new Date().toISOString(),run:{state:'completed',labeled_samples:1000},training:{}})};
   return {ok:true,json:async()=>({schema_version:1,updated_at:new Date().toISOString(),today:{date:today},totals:{learning_days:1},phase:'idle'})};
 };
 run('assets/learning-status.js');
 await settle();
 const entries=[...w.document.querySelectorAll('[id]')].map(n=>[n.id,n]);
 assert.equal(new Set(entries.map(([id])=>id)).size,entries.length,'duplicate IDs');
 const nodes=new Map(entries);
 dom.window.close();
 return nodes;
}
(async()=>{
 const base={
   schema_version:1,
   date:'2026-09-21',
   updated_at:new Date().toISOString(),
   status:'complete',
   facts:{sample_count:7430,labeled_count:488,downloaded:464,requested:465},
   providers:{openai:{
     status:'ok',model:'gpt-5.6-luna',source:'cache',
     review:{
       summary:'資料仍需驗證',
       hypotheses:[{id:'vwap_filter',stance:'hold',reason:'仍須獨立驗證'}]
     }
   }},
   verification:{observations:[{title:'樣本是否完整',verdict:'no'}]}
 };
 let n=await render(base);
 assert.equal(n.get('learnDays').textContent,'1');
 assert.equal(n.get('historySamples').textContent,'1,000');
 assert.equal(n.get('dualPhase').textContent,'OpenAI 復盤完成');
 assert.equal(n.get('dualTitle').textContent,'OpenAI 每日復盤');
 assert.equal(n.get('dualOpenaiSummary').textContent,'資料仍需驗證');
 assert(n.get('dualOpenaiMeta').textContent.includes('沿用同資料快取'));
 assert(n.get('dualOpenaiIdeas').children[0].textContent.includes('VWAP 條件：暫不優先'));
 assert(n.get('dualChecks').children[0].textContent.includes('樣本是否完整 → 否'));
 assert(n.get('dualFacts').textContent.includes('7,430'));
 assert(!n.has('dualGeminiMeta'),'obsolete Gemini panel must not return');
 assert(!n.has('dualDisagreement'),'obsolete dual-provider comparison must not return');

 const partial=JSON.parse(JSON.stringify(base));
 partial.status='partial';
 partial.providers.openai={status:'monthly_limit'};
 partial.verification={observations:[]};
 n=await render(partial);
 assert.equal(n.get('dualPhase').textContent,'復盤未完成');
 assert(n.get('dualOpenaiSummary').textContent.includes('本月'));
 assert(n.get('dualChecks').children[0].textContent.includes('等待資料'));

 const waiting=JSON.parse(JSON.stringify(base));
 waiting.status='waiting_report';
 n=await render(waiting);
 assert.equal(n.get('dualPhase').textContent,'等待當日資料');

 n=await render(base,true);
 assert(n.get('dualError').textContent.includes('未授權'));
 assert.equal(n.get('dualPhase').textContent,'連線待確認');

 n=await render(null);
 assert(n.get('dualError').textContent.includes('第一份 OpenAI'));

 const unsafe=JSON.parse(JSON.stringify(base));
 unsafe.providers.openai.review.summary='<img src=x onerror=alert(1)>';
 unsafe.providers.openai.review.hypotheses[0].reason='<script>alert(1)</script>';
 n=await render(unsafe);
 assert.equal(n.get('dualOpenaiSummary').textContent,unsafe.providers.openai.review.summary);
 assert.equal(n.get('dualOpenaiIdeas').children[0].textContent.includes('<script>alert(1)</script>'),true);
 assert.equal(n.get('dualReview').querySelector('img'),null);
 assert.equal(n.get('dualReview').querySelector('script'),null);

 console.log('PASS UI: OpenAI-only review, daily/history panels, statuses, caching, checks, permissions, missing data, and safe text.');
})().catch(e=>{console.error(e);process.exit(1)});
