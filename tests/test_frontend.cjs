const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(require('node:path').join(__dirname,'../index.html'),'utf8');
assert(!source.includes('id="topPicksModule"'));
assert(!source.includes('id="topPickList"'));
assert(!source.includes('function renderTopPicks('));
const scripts=[...source.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)].map(x=>x[1]);
for(const script of scripts)new vm.Script(script);
const nodes=new Map();
const el=id=>{if(!nodes.has(id))nodes.set(id,{innerHTML:'',textContent:'',value:'',dataset:{},setAttribute(k,v){this[k]=v},classList:{add(){},remove(){}},replaceChildren(){this.innerHTML='';this.textContent=''},append(n){this.textContent+=n.textContent||''},style:{setProperty(){}}});return nodes.get(id)};
const doc={documentElement:{dataset:{theme:'dark'}},getElementById:el,createElement:()=>({textContent:'',className:''}),querySelectorAll:()=>[]};
const palette={dark:{'--panel':'#151515','--surface':'#1e1e1e','--sub':'#b0b0b0','--border':'#3d3d3d','--up':'#ff7b86','--down':'#62d69a'},light:{'--panel':'#ffffff','--surface':'#f5f5f3','--sub':'#595959','--border':'#ccccca','--up':'#b91c32','--down':'#137342'}};
const ctx=vm.createContext({document:doc,window:{addEventListener(){}},console,Date,Intl,AbortController,setTimeout,clearTimeout,localStorage:{getItem(){return null},setItem(){},removeItem(){}},getComputedStyle:()=>({getPropertyValue:key=>palette[doc.documentElement.dataset.theme][key]}),setInterval(){}});
// External script tags contain no inline source. Select the application by its
// required function rather than its position among share/learning/rebound assets.
const mainScripts=scripts.filter(script=>/function\s+taiwanDay\s*\(/.test(script));
assert.equal(mainScripts.length,1,'Expected exactly one inline application script with taiwanDay');
vm.runInContext(mainScripts[0],ctx);
vm.runInContext(`
const today=taiwanDay();META={updated_at:today,rule_version:RULE_VERSION};
function fixture(symbol,category,price=100){return {symbol,name:symbol,category,price,sma20:90,sma60:80,momo20:1.1,updated_at:today,dataQuality:90,selection:{version:RULE_VERSION,as_of:today,strategies:{SWING:{eligible:true,score:85,reasons:['passed'],holding_period:'10D'},LONG:{eligible:false,score:99}}}};}
const weak=fixture('weak','a');weak.selection.strategies.SWING.eligible=false;
if(bestStrategyFor(weak)!==null)throw Error('Unqualified fallback returned');
const old=fixture('old','b');old.selection.version='1.0';if(bestStrategyFor(old)!==null)throw Error('Legacy rules accepted');
const missing=fixture('missing','c');delete missing.selection;if(bestStrategyFor(missing)!==null)throw Error('Missing backend decision accepted');
if(qualified(fixture('long','d'),'LONG'))throw Error('Ineligible LONG accepted');
const all=Array.from({length:40},(_,i)=>fixture('T'+i,'sector'+(i%3),i%2?200:40));
COMPUTED_STOCKS=all;renderAllSections();const before=document.getElementById('marketSignalText').textContent;
PRICE_MAX=50;renderAllSections();if(document.getElementById('marketSignalText').textContent!==before)throw Error('Budget changed market');
const longOnly=fixture('long-only','d');longOnly.selection.strategies.SWING.eligible=false;longOnly.selection.strategies.LONG.eligible=true;
if(bestStrategyFor(longOnly)!==null)throw Error('Removed LONG strategy recommended');
const yesterday=new Date(Date.now()-86400000);
INTRADAY={scan_date:taiwanDay(yesterday),generated_at:yesterday.toISOString(),session:'close',overnight:[{symbol:'OLD'}]};renderIntradayPicks();
if(document.getElementById('overnightPickList').innerHTML.includes('OLD') || document.getElementById('overnightPickList').textContent.includes('OLD'))throw Error('Yesterday picks shown');
if(!document.getElementById('overnightPickList').textContent.includes('今天尚未收到'))throw Error('Missing stale-data explanation');
currentChart={applyOptions(x){globalThis.chartApplied=x}};currentSeries={applyOptions(x){globalThis.candleApplied=x}};
setTheme('light');if(chartApplied.layout.background.color!=='#ffffff'||candleApplied.upColor!=='#b91c32')throw Error('Light chart');
setTheme('dark');if(candleApplied.downColor!=='#62d69a')throw Error('Dark chart');
if(marketClass(1)!=='market-up'||marketClass(-1)!=='market-down')throw Error('Taiwan colors');
for(const x of ['',true,Infinity])if(n(x)!==null)throw Error('Invalid number accepted');
`,ctx);
(async()=>{
  // Split reads must reject a mixture of two publication batches.
  ctx.responses={};
  vm.runInContext(`fetchJson=async url=>{if(url.endsWith('active_release.json'))return null;if(url.endsWith('meta.json'))return {release_id:'A',rule_version:RULE_VERSION,updated_at:taiwanDay()};if(url.endsWith('summary.json'))return {T:{release_id:'B'}};return {};};`,ctx);
  await assert.rejects(vm.runInContext('loadSplitSchema()',ctx),/正在更新/);
  vm.runInContext(`fetchJson=async url=>{if(url.endsWith('active_release.json'))return 'A';if(url.endsWith('meta.json'))return {release_id:'A',rule_version:RULE_VERSION,updated_at:taiwanDay()};if(url.endsWith('summary.json'))return {T:{release_id:'A'}};return {};};`,ctx);
  assert.equal((await vm.runInContext('loadSplitSchema()',ctx)).length,1);
  console.log('PASS frontend: no fallback, full-market regime, stale overnight, theme colors, finite numbers, snapshot consistency');
})().catch(e=>{console.error(e);process.exitCode=1});
