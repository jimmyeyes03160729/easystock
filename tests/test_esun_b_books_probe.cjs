'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {EventEmitter}=require('node:events');
const {options,Metrics,runProbe}=require('../deploy/probe_esun_b_books.cjs');
const now=Date.now();
function book(at=now){return {event:'data',channel:'books',data:{symbol:'2330',time:at*1000,
  bids:Array.from({length:5},(_,i)=>({price:100-i,size:5})),
  asks:Array.from({length:5},(_,i)=>({price:101+i,size:6}))}};}
test('probe is bounded and stock-only',()=>{
  assert.throws(()=>options(['--symbols','IX0001']));
  assert.throws(()=>options(['--seconds','1000']));
  assert.throws(()=>options(['--client','relative.js']));
});
test('snapshots, stale data, malformed levels and duplicates are not fresh continuous books',()=>{
  const m=new Metrics(['2330']);let q=book();q.event='snapshot';m.message(q,now);
  m.message(book(now-4000),now);m.message(book(),now);m.message(book(),now);
  q=book(now+1);q.data.asks.pop();m.message(q,now);
  assert.equal(m.rows['2330'].snapshots,1);assert.equal(m.rows['2330'].books,2);
  assert.equal(m.rows['2330'].fresh_books,1);assert.equal(m.invalid.invalid_five_levels,1);
  q=book(now+2);q.data.bids[0]=null;assert.doesNotThrow(()=>m.message(q,now));
  assert.equal(m.invalid.invalid_five_levels,2);
});
test('future, trial and wrong-symbol callbacks cannot count as usable books',()=>{
  const m=new Metrics(['2330']);m.message(book(now+3000),now);
  const trial=book();trial.data.isTrial=true;m.message(trial,now);
  const other=book();other.data.symbol='2317';m.message(other,now);
  assert.equal(m.rows['2330'].books,0);
});
test('no connection is created while the existing provider is unhealthy',async()=>{
  let calls=0;const r=await runProbe({symbols:['2330']},{factory:()=>{calls++;},checkHealth:()=>false});
  assert.equal(calls,0);assert.equal(r.stop_reason,'existing_provider_not_healthy');
});
test('provider errors abort without retries, unsubscribe only own IDs and never log secrets',async()=>{
  const stock=new EventEmitter(),sent=[];let logins=0;
  stock.connect=async()=>{};
  stock.subscribe=async cmd=>{sent.push(cmd);stock.emit('message',{event:'subscribed',data:{symbol:'2330',channel:cmd.channel,id:cmd.channel}});
    stock.emit('message',{event:'error',data:{code:1001,message:'secret credential'}});};
  stock.unsubscribe=async cmd=>sent.push(cmd);stock.disconnect=async()=>{};
  const r=await runProbe({symbols:['2330'],seconds:15},{checkHealth:()=>true,
    factory:()=>({login:async()=>{logins++;},websocketClient:{stock}})});
  assert.equal(logins,1);assert.equal(r.stop_reason,'provider_error');
  assert.equal(r.production_changed,false);assert.equal(r.deployment_allowed,false);
  assert.ok(!JSON.stringify(r).includes('secret'));assert.ok(sent.some(x=>x.ids));
  assert.equal(sent.filter(x=>x.channel).length,1);
});
test('our own disconnect is cleanup, not a spontaneous provider failure',async()=>{
  const stock=new EventEmitter();stock.connect=async()=>{};stock.subscribe=async()=>{};
  stock.unsubscribe=async()=>{};stock.disconnect=async()=>stock.emit('disconnect');
  const r=await runProbe({symbols:['2330'],seconds:0},{checkHealth:()=>true,
    factory:()=>({login:async()=>{},websocketClient:{stock}})});
  assert.equal(r.stop_reason,null);assert.equal(r.existing_provider_healthy_after,true);
});
