const {JSDOM}=require('jsdom'),fs=require('node:fs'),assert=require('node:assert/strict');
const ids=['reboundStatus','reboundPicks','reboundWatch','reboundProgress','reboundWatchSection','reboundDiagnostics','reboundRetry'];
const dom=new JSDOM(ids.map(x=>`<div id="${x}"></div>`).join(''),{runScripts:'outside-only',url:'https://test.invalid/'}),w=dom.window;
const rows=Array.from({length:162},(_,i)=>{let c=10+5*(1-Math.abs((i%40)-20)/20),o=c;if(i===161){c=10.5;o=10.05;}return {time:new Date(Date.UTC(2026,0,1+i)).toISOString().slice(0,10),open:o,high:c+.1,low:Math.min(c,o)-.1,close:c};});
const day=rows.at(-1).time;
w.taiwanDay=()=>day;w.stockKlineUrl=s=>'/pinned/'+s.symbol;w.openStockDetail=()=>{};
w.eval(fs.readFileSync('assets/rebound-engine.js','utf8'));
w.eval(fs.readFileSync('assets/rebound-ui.js','utf8'));
const stock={symbol:'1234',name:'TEST',price:10.5,updated_at:day,amount:1e7,kline_count:162,rev_yoy:5,eps:1,operating_margin:5,debt_ratio:40,revenue_period:'202605',field_meta:Object.fromEntries(['rev_yoy','eps','operating_margin','debt_ratio'].map(k=>[k,{source:'official-api',as_of:day}]))};
const txt=id=>w.document.getElementById(id).textContent;
(async()=>{
 await w.RangeReboundUI.refresh([],{});assert(txt('reboundStatus').includes('等待'));
 let calls=0;w.fetch=async url=>{calls++;assert(url.startsWith('/pinned/'));return {ok:true,json:async()=>rows};};
 await w.RangeReboundUI.refresh([stock],{updated_at:day,release_id:'A'});assert(txt('reboundPicks').includes('觀察 1'));assert(txt('reboundPicks').includes('突破確認'));assert.equal(calls,1);
 await w.RangeReboundUI.refresh([stock],{updated_at:day,release_id:'A'});assert.equal(calls,1);
 assert(w.localStorage.getItem('niuma-rebound-0.3'));w.eval(fs.readFileSync('assets/rebound-ui.js','utf8'));await w.RangeReboundUI.refresh([stock],{updated_at:day,release_id:'A'});assert.equal(calls,1,'reload reuses versioned local cache');
 await w.RangeReboundUI.refresh([{...stock,eps:null}],{updated_at:day,release_id:'B'});assert.equal(txt('reboundPicks'),'');assert(txt('reboundWatch').includes('基本面待補'));
 w.fetch=async()=>({ok:false,status:403});await w.RangeReboundUI.refresh([stock],{updated_at:day,release_id:'C'});assert(txt('reboundStatus').includes('未讀取'));assert(txt('reboundDiagnostics').includes('K 線讀取失敗 1 檔'));
 w.fetch=async()=>({ok:true,json:async()=>rows});await w.RangeReboundUI.refresh([stock],{updated_at:day,release_id:'D'});assert(txt('reboundPicks').includes('觀察 1'));
 await w.RangeReboundUI.refresh([],{updated_at:day,release_id:'D'});assert.equal(txt('reboundPicks'),'');assert(txt('reboundStatus').includes('沒有股票'));
 // 已發布 feed：只抓一次，換篩選或重新載入都不再掃 K 線。
 w.FIREBASE_ROOT='https://fb.invalid/market_data';
 const feed={schema_version:1,release_id:'E',as_of:day,strategy_version:'range-rebound-0.3',signals:[{symbol:'1234',technical:{score:80,confirmation:'breakout',reasons:['x'],support:[9,9.5],resistance:[12,12.5],invalid:8.8,target:12,costPct:.006,netRR:2,rr:2.2,dailyChangePct:1},financial:{status:'passed',checks:[],missing:[],optional:[]}}],pending:[]};
 const seen=[];w.fetch=async url=>{seen.push(url);if(url.endsWith('/releases/E/rebound_feed.json'))return {ok:true,json:async()=>feed};return {ok:false,status:403};};
 await w.RangeReboundUI.refresh([stock],{updated_at:day,release_id:'E'});assert(txt('reboundPicks').includes('觀察 1'));assert.deepEqual(seen,['https://fb.invalid/market_data/releases/E/rebound_feed.json']);
 await w.RangeReboundUI.refresh([stock,{...stock,symbol:'5678'}],{updated_at:day,release_id:'E'});assert.equal(seen.length,1,'filter change reuses feed');
 await w.RangeReboundUI.refresh([{...stock,symbol:'5678'}],{updated_at:day,release_id:'E'});
 assert(txt('reboundStatus').includes('價格篩選範圍內'));assert(!txt('reboundStatus').includes('今天沒有符合'));
 assert(txt('reboundProgress').includes('正式發布 1 檔 / 目前顯示 0 檔'));
 w.eval(fs.readFileSync('assets/rebound-ui.js','utf8'));await w.RangeReboundUI.refresh([stock],{updated_at:day,release_id:'E'});assert.equal(seen.length,1,'reload reuses stored feed');
 // feed 被擋：同一 release 不重複打 feed，也不重複抓已計算的 K 線。
 seen.length=0;w.fetch=async url=>{seen.push(url);return url.startsWith('/pinned/')?{ok:true,json:async()=>rows}:{ok:false,status:403};};
 await w.RangeReboundUI.refresh([stock],{updated_at:day,release_id:'F'});assert(txt('reboundPicks').includes('觀察 1'));const first=seen.length;
 w.eval(fs.readFileSync('assets/rebound-ui.js','utf8'));await w.RangeReboundUI.refresh([stock],{updated_at:day,release_id:'F'});
 assert.equal(seen.filter(u=>u.startsWith('/pinned/')).length,1,'blocked feed falls back once per release');assert(seen.length<=first+2);
 console.log('PASS rebound UI: waiting, pinned K-line, cache, incomplete fundamentals, read failure, recovery, published feed cache');
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(()=>dom.window.close());
