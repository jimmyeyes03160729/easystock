const {JSDOM}=require('jsdom');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const html=fs.readFileSync(path.join(__dirname,'../index.html'),'utf8');
const main=[...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)].map(m=>m[1]).find(s=>s.includes('function taiwanDay('));
const dom=new JSDOM(html,{url:'https://local.invalid/',runScripts:'outside-only'}),w=dom.window;
const ctx=dom.getInternalVMContext(),run=code=>vm.runInContext(code,ctx);
w.setInterval=()=>0;
// No network, including from the learning panels.
w.fetch=async()=>({ok:true,json:async()=>null});
run(main);w.onload=null;

(async()=>{
  run(`
    INTRADAY_LIVE={last_update_at:new Date().toISOString(),session:'daytrade',open_positions:{TEST:{symbol:'TEST',name:'TEST',entry_time:taiwanDay()+'T09:30:00+08:00',entry_price:100,current_price:101}}};
    renderLiveIntraday();
  `);
  assert(w.document.getElementById('intradayStamp').textContent.includes('即時監控'));
  run(`INTRADAY_LIVE.last_update_at=new Date(Date.now()-120000).toISOString();renderLiveIntraday();updateSystemStatus();`);
  assert(w.document.getElementById('intradayStamp').textContent.includes('更新逾時'));
  assert(w.document.getElementById('intradayPickList').textContent.includes('TEST'));
  assert(w.document.getElementById('metaTracking').textContent.includes('更新逾時'));

  // Failed/null reads must not become a fictitious empty portfolio. Recovery clears errors.
  w.fetch=async()=>{throw Error('offline');};
  await run('refreshLiveData()');
  assert(w.document.getElementById('intradayStamp').textContent.includes('連線失敗'));
  assert(w.document.getElementById('intradayPickList').textContent.includes('TEST'));
  w.fetch=async()=>({ok:true,json:async()=>null});
  await run('refreshLiveData()');
  assert.equal(run('INTRADAY_LIVE.open_positions.TEST.symbol'),'TEST');
  w.fetch=async url=>({ok:true,json:async()=>url.includes('intraday_live')?{last_update_at:new Date().toISOString(),session:'daytrade',open_positions:{}}:null});
  await run('refreshLiveData()');
  assert(w.document.getElementById('intradayPickList').textContent.includes('目前沒有 OPEN'));
  run(`INTRADAY_LIVE={last_update_at:taiwanDay()+'T13:00:00+08:00',session:'closed'};`);
  assert.equal(run(`liveDataState(Date.parse(taiwanDay()+'T20:00:00+08:00')).label`),'當沖已結束');

  // Daily source remains independently refreshable when overnight is inaccessible.
  run(`META={release_id:'old'};globalThis.reloadCount=0;fetchMarketData=async()=>{reloadCount++;};`);
  w.fetch=async url=>{if(url.includes('intraday_picks'))throw Error('denied');return {ok:true,json:async()=>'new'};};
  await run('refreshDailyAndOvernight()');assert.equal(w.reloadCount,1);

  // A published kline contract pins both same-day corrections and subsequent days.
  w.fetch=async url=>({ok:true,json:async()=>url.endsWith('active_release.json')?'A':url.endsWith('meta.json')?{release_id:'A',rule_version:'2.0.0',kline_schema_version:1,updated_at:'2026-09-15'}:url.endsWith('summary.json')?{T:{symbol:'T',release_id:'A'}}:{}});
  const rows=await run('loadSplitSchema()');w.testStock=rows[0];
  assert(run('stockKlineUrl(testStock)').includes('/releases/A/kline/T.json'));
  run("META.release_id='B'");assert(run('stockKlineUrl(testStock)').includes('/releases/A/'));
  assert(run("stockKlineUrl({symbol:'T'})").endsWith('/market_data/kline/T.json'));

  // Full DOM composition in production order, without a monkey-patched renderer.
  const renderer=run('renderLinePickList');
  w.fetch=async()=>({ok:true,json:async()=>null});
  for(const file of ['learning-status.js','rebound-engine.js','rebound-ui.js','dashboard-layout.js'])
    run(fs.readFileSync(path.join(__dirname,'../assets',file),'utf8'));
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(run('renderLinePickList'),renderer);
  assert(!w.document.getElementById('overnightModule'));
  assert(w.document.getElementById('recommendationPair').contains(w.document.getElementById('reboundModule')));
  const watchDetails=w.document.querySelector('#reboundWatchSection>details');
  assert(watchDetails&&!watchDetails.open,'technical watchlist collapsed by default');
  run('renderIntradayPicks()');
  const ids=[...w.document.querySelectorAll('[id]')].map(n=>n.id);
  assert.equal(ids.length,new Set(ids).size,'duplicate IDs after layout');
  console.log('PASS dashboard: stale/offline/recovered snapshots, independent refresh, pinned K-lines, full module DOM composition');
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(()=>w.close());
