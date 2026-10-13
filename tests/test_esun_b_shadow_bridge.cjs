const test=require('node:test'),assert=require('node:assert/strict');
const {EventEmitter}=require('node:events');
const {makeFactory}=require('../deploy/esun_b_shadow_bridge.cjs');
test('resolve exactly one websocket only after authentication token is ready',async()=>{
  let loggedIn=false,accesses=0;const stock=new EventEmitter(),seen=[];
  const sdk={login:async()=>{loggedIn=true;},get websocketClient(){
    assert.equal(loggedIn,true);accesses++;return {stock};}};
  const proxy=makeFactory(()=>sdk,{symbols:['2330']},x=>seen.push(x))();
  assert.equal(accesses,0);await proxy.login();assert.equal(proxy.websocketClient.stock,stock);
  stock.emit('message',{event:'subscribed',data:{symbol:'2330',channel:'books',id:'test'}});
  stock.emit('message',{event:'snapshot',channel:'books',data:{symbol:'2330'}});
  assert.equal(accesses,1);assert.deepEqual(seen,[{kind:'ack',symbol:'2330'}]);
});
