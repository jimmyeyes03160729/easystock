const assert=require('assert');
const {createDOM,settle}=require('./tests/dom.cjs');
async function render(dual,networkFail=false){
 const {dom,w,run}=createDOM();
 const today=new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Taipei'}).format(new Date());
 w.fetch=async url=>{
   if(url.includes('dual_review'))return networkFail?{ok:false,status:403}:{ok:true,json:async()=>dual};
   if(url.includes('history_training'))return {ok:true,json:async()=>({schema_version:1,updated_at:new Date().toISOString(),run:{state:'completed',labeled_samples:1000},training:{}})};
   return {ok:true,json:async()=>({schema_version:1,updated_at:new Date().toISOString(),today:{date:today},totals:{learning_days:1},phase:'idle'})};
  };
 run('assets/learning-status.js');await settle();
 const entries=[...w.document.querySelectorAll('[id]')].map(n=>[n.id,n]);
 assert.equal(new Set(entries.map(([id])=>id)).size,entries.length,'duplicate IDs');
 const nodes=new Map(entries);dom.window.close();
 return nodes;
}
(async()=>{
 const base={schema_version:1,date:'2026-09-11',updated_at:new Date().toISOString(),status:'complete',facts:{sample_count:7430,labeled_count:488,downloaded:464,requested:465},
 providers:{gemini:{status:'ok',model:'gemini-3.6-flash',source:'cache',review:{summary:'僅限研究',hypotheses:[]}},openai:{status:'ok',model:'gpt-5.6-luna',source:'api',review:{summary:'資料仍需驗證',hypotheses:[]}}},
 comparison:{status:'compared',agreements:[{title:'資料品質',stance:'test'}],disagreements:[{title:'VWAP',gemini:'test',openai:'hold'}],insufficient:[],verified_observations:[{title:'是否完整',verdict:'no'}]}};
 let n=await render(base);
 assert.equal(n.get('learnDays').textContent,'1');assert.equal(n.get('historySamples').textContent,'1,000');
 assert(n.get('dualPhase').textContent.includes('已比對'));assert(n.get('dualGeminiMeta').textContent.includes('快取'));
 assert(n.get('dualDisagreement').children[0].textContent.includes('OpenAI 暫不優先'));
 const partial=JSON.parse(JSON.stringify(base));partial.status='partial';partial.providers.openai={status:'monthly_limit'};partial.comparison={status:'incomplete'};
 n=await render(partial);assert(n.get('dualOpenaiSummary').textContent.includes('本月'));assert(n.get('dualAgreement').children[0].textContent.includes('尚未'));
 n=await render(base,true);assert(n.get('dualError').textContent.includes('未授權'));
 n=await render(null);assert(n.get('dualError').textContent.includes('第一份'));
 const text=JSON.parse(JSON.stringify(base));text.providers.openai.review.summary='<img src=x onerror=alert(1)>';
 n=await render(text);assert.equal(n.get('dualOpenaiSummary').textContent,text.providers.openai.review.summary);
 console.log('PASS: existing daily/history panels preserved; paired/partial/cache/limits/permission/missing states; generated prose rendered as text.');
})().catch(e=>{console.error(e);process.exit(1)});
