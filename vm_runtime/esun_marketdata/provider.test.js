'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {Provider,normalize,BACKOFF,tpe}=require('./provider');
const mapping={symbol:'IX0001',name:'加權'},now=Date.parse('2026-09-30T10:00:00+08:00');
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
