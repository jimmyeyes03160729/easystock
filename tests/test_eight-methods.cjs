const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs');
const {JSDOM}=require('jsdom');
const E=require('../assets/eight-methods.js');
const now=new Date('2026-10-13T13:10:00+08:00');
test('frozen next-session pool has dated empty reason and never claims live picks',()=>{
 const p={target_day:'2026-10-14',frozen_at:'2026-10-13T13:25:00+08:00',symbols:[],status:'EMPTY_DATA_OR_NO_MATCH',reason:'資料不足，不補選'};
 assert.match(E.poolText(p,new Date('2026-10-13T14:00:00+08:00')),/2026-10-14.*資料不足，不補選.*共用既有五檔額度/);
 assert.match(E.poolText(p,now),/尚未凍結/);
});
test('XSS escapes names, times, reasons and condition labels; numeric chart rejects strings',()=>{
 const r={symbol:'2330',name:'<img src=x onerror=alert(1)>',reason:'<script>x</script>',quote_at:now.toISOString(),conditions:[{label:'<svg>',state:'pass',reason:'<img>'}],prices:[100,101,102,103]};
 for(const html of [E.openingRow(r,now),E.closingRow(r,now)]){assert(!html.includes('<img'));assert(!html.includes('<script'));assert(html.includes('&lt;img'));}
 assert(E.chart(r).includes('<polyline'));assert.equal(E.chart({...r,prices:[100,'<svg>',102,103]}),'');
 assert(E.openingRow({...r,status:'classified',method:1},new Date('2026-10-13T09:14:59+08:00')).includes('尚未完成'));
 assert(E.closingRow(r,new Date('2026-10-13T13:25:00+08:00')).includes('訊號已截止'));
});
test('stale, future and wrong version feed rejected',()=>{
 const f={schema_version:1,version:'OPENING_EIGHT_METHODS_V1',day:'2026-10-13',updated_at:now.toISOString()};
 assert(E.valid(f,f.version,now));assert(!E.valid(f,'old',now));assert(!E.valid(f,f.version,new Date(+now+91000)));assert(!E.valid(f,f.version,new Date(+now-1)));
});
test('tabs, complete stock list, source freshness and isolated requests in production DOM',async()=>{
 const dom=new JSDOM(fs.readFileSync('index.html','utf8'),{runScripts:'outside-only'}),w=dom.window;
 const paths=[];w.fetch=async url=>{paths.push(url);const opening=url.includes('opening_eight');const time=new Date();const day=new Date(+time+8*3600000).toISOString().slice(0,10);return {ok:true,json:async()=>({schema_version:1,version:opening?'OPENING_EIGHT_METHODS_V1':'CLOSING_EIGHT_METHODS_V1',ruleset:'TW_CLOSING_RULES_V1',day,updated_at:time.toISOString(),rows:[{symbol:'2330',name:'台積電',status:'classified',method:1,prices:[100,101,102,103],directions:['U','U','U'],quote_at:time.toISOString(),conditions:[]}],markets:[]})};};
 w.eval(fs.readFileSync('assets/eight-methods.js','utf8'));await new Promise(r=>setImmediate(r));
 assert.equal(paths.length,2);assert(paths.every(p=>/public_feed\/(opening|closing)_eight\.json$/.test(p)));
 w.document.getElementById('closingTab').click();assert(w.document.getElementById('openingPanel').hidden);assert(!w.document.getElementById('closingPanel').hidden);
 assert.equal(w.document.querySelector('#eightMethodsModule input[type=search]'),null);assert(w.document.getElementById('closingRows').textContent.includes('2330'));
 assert(!/XQ|xq\.com/.test(w.document.getElementById('eightMethodsModule').outerHTML));
 w.document.getElementById('openingTab').dispatchEvent(new w.KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}));assert.equal(w.document.getElementById('closingTab').getAttribute('aria-selected'),'true');
 assert(fs.readFileSync('index.html','utf8').includes('grid-template-columns:1fr'));w.close();
});
test('old UI publisher and scheduler entrypoints retired; shared helpers independent',()=>{
 for(const f of ['assets/short-term.js','short_term/feed.py','deploy/install_short_term.sh','deploy/easystock-short-term.timer','deploy/easystock-short-term.service'])assert(!fs.existsSync(f));
 for(const f of ['index.html','assets/dashboard-layout.js','assets/eight-methods.js'])assert(!/short_term|shortTerm|short-term|short_term_full|REVENUE_SHORT_V1/.test(fs.readFileSync(f,'utf8')),f);
 assert(fs.existsSync('docs/research_governance/preregistrations/REVENUE_SHORT_V1.yaml'));
});

test('missing inputs are distinct from evaluated failures and historical coverage remains explicit',()=>{
 const r={symbol:'2330',quote_at:now.toISOString(),conditions:[{state:'insufficient',label:'量',reason:'缺資料'}]};
 assert.match(E.closingRow(r,now),/資料不足，尚未完成八項判定/);
 assert(!E.closingRow(r,now).includes('通過 0/8'));
 assert.match(E.closingRow({...r,conditions:[{state:'fail',label:'量'}]},now),/完整判定/);
 assert.match(E.observationText({observed_at:now.toISOString(),observed:328,insufficient:328,complete:0,all_pass:0,failed:0}),/資料不足 328 檔.*完整判定 0 檔/);
});
