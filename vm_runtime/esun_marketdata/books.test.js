'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {Books}=require('./books');
const now=Date.parse('2026-10-13T09:03:00+08:00');
function fixture(fn){
 const directory=fs.mkdtempSync(path.join(os.tmpdir(),'esun-dual-books-'));
 const sent=[],writes=[],socket={subscribe:x=>sent.push(['sub',x]),unsubscribe:x=>sent.push(['unsub',x])};
 const b=new Books({directory,clock:()=>now,write:(_p,x)=>writes.push(x),limit:2});
 const request=(symbols,pinned=[])=>fs.writeFileSync(path.join(directory,'b-books-request.json'),JSON.stringify({schema_version:1,generated_at:new Date(now).toISOString(),symbols,pinned}));
 try{b.start(socket);fn({b,request,sent,writes,socket});}
 finally{b.stop();fs.rmSync(directory,{recursive:true,force:true});}
}
const ack=(symbol,id)=>({event:'subscribed',data:{channel:'books',symbol,id}});
const book=(id='one')=>({event:'data',channel:'books',id,data:{symbol:'2330',type:'EQUITY',exchange:'TWSE',time:now*1000,
 bids:Array.from({length:5},(_,i)=>({price:100-i*.5,size:10})),asks:Array.from({length:5},(_,i)=>({price:100.5+i*.5,size:10}))}});
test('one shared socket and ACK-specific books, never snapshot or wrong id',()=>fixture(({b,request,sent})=>{
 request(['2330']);b.reconcile();assert.equal(sent.length,1);
 b.message(book());assert.equal(b.quotes['2330'],undefined);
 b.message(ack('2330','one'));b.message({...book(),event:'snapshot'});b.message(book('wrong'));
 assert.equal(b.quotes['2330'],undefined);b.message(book());assert.equal(b.quotes['2330'].size_units,'provider_native_unverified');
}));
test('pending cancel waits subscribe ACK and cancelling reserves quota until its unsubscribe ACK',()=>fixture(({b,request,sent})=>{
 request(['2330','2317']);b.reconcile();request(['2884']);b.reconcile();assert.equal(sent.length,2);
 b.message(ack('2330','one'));assert.equal(sent[2][0],'unsub');b.reconcile();assert.equal(sent.length,3);
 b.message({event:'unsubscribed',data:{id:'wrong'}});b.reconcile();assert.equal(sent.length,3);
 b.message({event:'unsubscribed',data:{id:'one'}});b.reconcile();assert.equal(sent[3][1].symbol,'2884');
}));
test('disconnect clears cache and reconnect epoch; late pre-ACK data cannot revive it',()=>fixture(({b,request,socket})=>{
 request(['2330']);b.reconcile();b.message(ack('2330','one'));b.message(book());const epoch=b.epoch;
 b.stop();assert.deepEqual(b.quotes,{});b.start(socket);assert.notEqual(b.epoch,epoch);b.message(book());assert.deepEqual(b.quotes,{});
}));
test('invalid partial crossed trial and future data are not accepted',()=>fixture(({b,request})=>{
 request(['2330']);b.reconcile();b.message(ack('2330','one'));
 for(const mutate of [x=>x.data.bids.pop(),x=>x.data.asks[0].price=99,x=>x.data.isTrial=true,x=>x.data.time+=1e6]){
  const x=book();mutate(x);b.message(x);assert.equal(b.quotes['2330'],undefined);
 }
}));
test('pin order and hard cap do not open another connection',()=>fixture(({b,request,sent})=>{
 request(['2330','2317','2884'],['2884']);b.reconcile();assert.equal(sent.length,2);assert.equal(sent[0][1].symbol,'2884');
}));
test('transport exception never frees unconfirmed reservation',()=>fixture(({b,request,socket})=>{
 socket.subscribe=()=>{throw Error('uncertain');};request(['2330']);b.reconcile();assert.equal(b.records.size,1);assert.equal(b.records.get('2330').state,'pending');
}));
test('invalid current partial book invalidates previous cached depth',()=>fixture(({b,request})=>{
 request(['2330']);b.reconcile();b.message(ack('2330','one'));b.message(book());assert(b.quotes['2330']);
 const bad=book();bad.data.bids.pop();b.message(bad);assert.equal(b.quotes['2330'],undefined);
}));
test('exchange microseconds survive export for exact native-unit comparison',()=>fixture(({b,request})=>{
 request(['2330']);b.reconcile();b.message(ack('2330','one'));
 const x=book();x.data.time-=123;b.message(x);
 assert.equal(b.quotes['2330'].datetime,'2026-10-13T01:02:59.999877Z');
}));
