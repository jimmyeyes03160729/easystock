const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(__dirname+'/assets/learning-status.js','utf8');
async function render(dual,networkFail=false){
 const nodes=new Map();
 function node(){
  const n={textContent:'',value:0,children:[],setAttribute(){},replaceChildren(){this.children=[]},appendChild(c){this.children.push(c)}};
  Object.defineProperty(n,'id',{set(v){assert(!nodes.has(v));nodes.set(v,n)}});
  Object.defineProperty(n,'innerHTML',{set(v){n.html=v;for(const m of v.matchAll(/id="([^"]+)"/g)){assert(!nodes.has(m[1]),m[1]);nodes.set(m[1],node())}}});
  return n;
 }
 const root=node();nodes.set('learningSection',root);
 const today=new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Taipei'}).format(new Date());
 const context={document:{getElementById:id=>nodes.get(id)||null,createElement:node,head:{appendChild(){}}},Intl,Date,Number,Math,Error,AbortController,
  FIREBASE_ROOT:'https://local.invalid',setTimeout(){return 1},clearTimeout(){},setInterval(){},fetch:async url=>{
   if(url.includes('dual_review'))return networkFail?{ok:false,status:403}:{ok:true,json:async()=>dual};
   if(url.includes('history_training'))return {ok:true,json:async()=>({schema_version:1,updated_at:new Date().toISOString(),run:{state:'completed',labeled_samples:1000},training:{}})};
   return {ok:true,json:async()=>({schema_version:1,updated_at:new Date().toISOString(),today:{date:today},totals:{learning_days:1},phase:'idle'})};
  }};
 vm.runInNewContext(source,context);for(let i=0;i<12;i++)await Promise.resolve();
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
