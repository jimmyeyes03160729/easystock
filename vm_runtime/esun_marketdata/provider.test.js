'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {Provider,normalize,BACKOFF,tpe}=require('./provider');
const mapping={symbol:'IX0001',name:'加權'},now=Date.parse('2026-09-30T10:00:00+08:00');
const {MarketContext,breadth}=require('./context');
const indices=require('./indices.json').indices;
function quotes(at=now){return Object.fromEntries(Object.entries(indices).map(([k,m],i)=>[k,normalize({symbol:m.symbol,index:100+i,changePercent:i,lastUpdated:at*1000},m,at)]));}
function snapshots(){return Object.fromEntries(['TSE','OTC'].map(market=>[market,{market,date:'2026-09-30',data:[1,-1,0].map((change,i)=>({symbol:String(2330+i),type:'EQUITY',change,closePrice:100,lastUpdated:now*1000}))}]));}
test('E1/E6/E7: seven verified indices, deterministic ranks and price-only rotation',()=>{
 const ctx=new MarketContext(),q=quotes();for(const [k,v]of Object.entries(q))ctx.observe(k,v);
 const a=ctx.build(q,snapshots(),now,true),b=ctx.build(Object.fromEntries(Object.entries(q).reverse()),snapshots(),now,true);
 assert.equal(a.sectors.status,'OK');assert.deepEqual(a.sectors.rows.map(r=>r.rank),b.sectors.rows.map(r=>r.rank));
 assert.equal(a.rotation.type,'sector_rotation_proxy');assert.equal(a.rotation.basis,'price_only');assert(!JSON.stringify(a).includes('capital_flow'));
 assert(a.sectors.rows.every(r=>r.return_day!==null&&r.return_1m===null&&r.valid&&r.source==='esun'&&r.quote_at));
});
test('point-in-time returns use preceding exchange history, never future or previous-day data',()=>{
 const ctx=new MarketContext(),q=quotes(now-900000);for(const [k,v]of Object.entries(q))ctx.observe(k,v);
 const current=quotes();current.electronics.price*=1.02;for(const [k,v]of Object.entries(current))ctx.observe(k,v);
 const r=ctx.build(current,{},now,true).sectors.rows.find(r=>r.key==='electronics');assert.equal(r.return_1m,null);assert(Math.abs(r.return_15m-2)<1e-8);
 ctx.observe('electronics',{...current.electronics,quote_at:tpe(now+60000),price:9999});assert.equal(ctx.build(current,{},now,true).sectors.rows.find(r=>r.key==='electronics').return_1m,null);
});
test('E2/E3: missing sector, expired quotes, closed/unknown calendar null out features',()=>{
 const ctx=new MarketContext(),q=quotes();delete q.shipping;
 const partial=ctx.build(q,{},now,true);assert.equal(partial.sectors.status,'DEGRADED');assert.equal(partial.sectors.rows.find(r=>r.key==='shipping').strength_score,null);assert.equal(partial.rotation.rotation_state,'UNKNOWN');
 for(const [at,open]of [[now+91000,true],[now,false],[now+86400000,true]]){
 const c=ctx.build(quotes(),snapshots(),at,open);assert.equal(c.sectors.status,'UNKNOWN');assert(c.sectors.rows.every(r=>r.return_day===null&&r.rank===null));assert.equal(c.breadth.advancers,null);
 }
});
test('E4/E5: real snapshot count and coverage; unsupported/stale/future/partial never fake all-market breadth',()=>{
 const c=breadth(snapshots(),now,true);assert.equal(c.advancers,2);assert.equal(c.decliners,2);assert.equal(c.unchanged,2);assert.equal(c.advance_decline_ratio,1);assert.equal(c.breadth_score,0);assert.equal(c.coverage,1);
 assert.equal(breadth({},now,true).status,'UNKNOWN');const p=snapshots();delete p.OTC;assert.equal(breadth(p,now,true).status,'DEGRADED');
 p.TSE.data[0].lastUpdated=(now+60000)*1000;assert.equal(breadth(p,now,true).valid_count,2);
 p.TSE.date='2026-09-29';assert.equal(breadth(p,now,true).advancers,null);
});
test('provider uses official stock.snapshot.quotes, and clears failed breadth instead of retaining yesterday',async()=>{
 const directory=fs.mkdtempSync(path.join(os.tmpdir(),'esun-context-'));let fail=false;const calls=[];
 try{
 const provider=new Provider({directory,clock:()=>now});provider.diagnostic.connected=true;provider.diagnostic.authenticated=true;
 fs.writeFileSync(path.join(directory,'public-health.json'),JSON.stringify({market_state:'OPEN',generated_at:tpe(now)}));
 const stock={intraday:{quote:async({symbol})=>({symbol,index:100,lastUpdated:now*1000,changePercent:1})},snapshot:{quotes:async({market})=>{calls.push(market);if(fail)throw Error('secret');return snapshots()[market];}}};
 await provider.poll({restClient:{stock}});let result=JSON.parse(fs.readFileSync(path.join(directory,'context.json')));assert.equal(result.breadth.advancers,2);assert.equal(result.sectors.status,'OK');assert.deepEqual(calls,['TSE','OTC']);
 fail=true;provider.lastBreadthPoll=-Infinity;await provider.poll({restClient:{stock}});result=JSON.parse(fs.readFileSync(path.join(directory,'context.json')));assert.equal(result.breadth.status,'UNKNOWN');assert.equal(result.breadth.advancers,null);
 assert(!JSON.stringify(result).includes('secret'));assert(fs.readFileSync(path.join(directory,'dataset','2026-09-30.jsonl'),'utf8').includes('sector_rotation_proxy'));
 }finally{fs.rmSync(directory,{recursive:true,force:true});}
});
test('normalize uses exchange timestamp and Taipei timezone',()=>{
  const row=normalize({symbol:'IX0001',index:100,lastUpdated:now*1000,change:1,changePercent:1},mapping,now);
  assert.equal(row.quote_at,'2026-09-30T10:00:00.000+08:00');assert.equal(row.fresh,true);
  assert.equal(row.return_1m,null);assert.equal(row.source,'esun');
  assert.equal(normalize({symbol:'IX0001',index:100,time:(now-600000)*1000},mapping,now).fresh,false);
});
test('invalid / future / unrelated quotes rejected',()=>{
  for(const row of [{symbol:'X',index:1,time:now},{symbol:'IX0001',index:NaN,time:now},
    {symbol:'IX0001',index:1,time:now+60000},{symbol:'IX0001',index:1}])assert.throws(()=>normalize(row,mapping,now));
});
test('stream change derived only from a real same-day reference',()=>{
  const base=normalize({symbol:'IX0001',closePrice:100,change:5,lastUpdated:now*1000},mapping,now);
  const row=normalize({symbol:'IX0001',index:101,time:now*1000},mapping,now,base);
  assert.equal(row.change,6);assert.equal(row.change_pct,6/95*100);
  assert.equal(normalize({symbol:'IX0001',index:101,time:now*1000},mapping,now).change_pct,null);
});
test('invalid messages do not crash; heartbeat alone is not data',()=>{
  const directory=fs.mkdtempSync(path.join(os.tmpdir(),'esun-provider-'));
  try{
    const provider=new Provider({directory,clock:()=>now});provider.message('not json');
    assert.equal(provider.diagnostic.parser_ok,false);provider.message(JSON.stringify({event:'heartbeat'}));
    assert.equal(provider.diagnostic.last_data_at,undefined);assert.equal(provider.diagnostic.last_heartbeat_at,tpe(now));
    provider.accept({symbol:'IX0001',index:100,time:now*1000});provider.flush();
    assert.equal(JSON.parse(fs.readFileSync(path.join(directory,'context.json'))).indices.taiex.price,100);
  }finally{fs.rmSync(directory,{recursive:true,force:true});}
});
test('repeated login failure actually waits with bounded backoff',async()=>{
  const directory=fs.mkdtempSync(path.join(os.tmpdir(),'esun-backoff-')),delays=[];
  let provider;
  try{
    provider=new Provider({directory,factory:()=>({login:async()=>{throw Error('secret password');}}),
      sleep:async ms=>{delays.push(ms);if(delays.length===8)provider.stop();}});
    await provider.run();assert.deepEqual(delays,[1000,2000,5000,10000,30000,60000,60000,60000]);
    assert.equal(provider.diagnostic.reconnect_count,8);
    assert(!JSON.stringify(provider.diagnostic).includes('secret'));
  }finally{fs.rmSync(directory,{recursive:true,force:true});}
});
