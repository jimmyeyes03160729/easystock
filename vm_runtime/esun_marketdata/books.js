'use strict';
// Shares the existing SDK socket with indices; no second login/connection.
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
class Books {
 constructor({directory,clock=Date.now,write,limit=160}) {
  this.directory=directory;this.clock=clock;this.write=write;this.limit=limit;
  this.records=new Map();this.quotes={};this.socket=null;this.epoch=null;this.connected=false;
 }
 start(socket){this.socket=socket;this.epoch=crypto.randomUUID();this.connected=true;this.records.clear();this.quotes={};this.flush();}
 stop(){this.connected=false;this.records.clear();this.quotes={};this.flush();this.socket=null;}
 reconcile(){
  let desired=[];
  try{
   const file=path.join(this.directory,'b-books-request.json');
   if(fs.statSync(file).size>32768)throw Error('oversized');
   const r=JSON.parse(fs.readFileSync(file,'utf8')),age=this.clock()-Date.parse(r.generated_at);
   if(r.schema_version!==1||!(age>=0&&age<=15000)||!Array.isArray(r.symbols)||!Array.isArray(r.pinned))throw Error('request_invalid');
   desired=[...new Set([...r.pinned,...r.symbols])].filter(s=>typeof s==='string'&&/^[1-9]\d{3}$/.test(s)).slice(0,this.limit);
  }catch(_){}
  if(!this.connected||!this.socket)return;
  for(const [symbol,r] of this.records)if(!desired.includes(symbol)){
   delete this.quotes[symbol];
   if(r.state==='pending')r.cancel=true;
   else if(r.state==='active')this.cancel(symbol,r);
  }
  for(const symbol of desired){
   if(this.records.has(symbol)||this.records.size>=this.limit)continue;
   this.records.set(symbol,{state:'pending'});
   try{this.socket.subscribe({channel:'books',symbol,intradayOddLot:false});}
   catch(_){/* Ambiguous transport retains reservation until disconnect/ACK. */}
  }
 }
 cancel(symbol,r){r.state='cancelling';delete this.quotes[symbol];try{this.socket.unsubscribe({id:r.id});}catch(_){} }
 message(m){
  if(!this.connected)return;
  if(m.event==='subscribed')for(const d of Array.isArray(m.data)?m.data:[m.data]){
   const r=this.records.get(d?.symbol);
   if(d?.channel==='books'&&r?.state==='pending'&&typeof d.id==='string'){
    r.id=d.id;r.state='active';if(r.cancel)this.cancel(d.symbol,r);
   }
  }
  if(m.event==='unsubscribed')for(const d of Array.isArray(m.data)?m.data:[m.data]){
   for(const [s,r]of this.records)if(r.state==='cancelling'&&r.id===d?.id){this.records.delete(s);delete this.quotes[s];}
  }
  if(m.event==='error'){this.stop();return;}
  const d=m.data,r=this.records.get(d?.symbol);
  if(m.event!=='data'||m.channel!=='books'||r?.state!=='active'||m.id!==r.id)return;
  const reject=()=>{delete this.quotes[d.symbol];};
  if(d.isTrial||d.isDelayedOpen||d.isDelayedClose){reject();return;}
  if(d.type!=='EQUITY'||!['TWSE','TPEX'].includes(d.exchange)){reject();return;}
  const at=d.time/1000,age=this.clock()-at;
  if(!Number.isSafeInteger(d.time)||!(age>=0&&age<=3000)){reject();return;}
  if(![d.bids,d.asks].every(a=>Array.isArray(a)&&a.length===5&&a.every(x=>x&&Number.isFinite(x.price)&&x.price>0&&Number.isFinite(x.size)&&x.size>=0))){reject();return;}
  const bp=d.bids.map(x=>x.price),ap=d.asks.map(x=>x.price);
  if(bp[0]>=ap[0]||bp.some((v,i)=>i&&bp[i-1]<=v)||ap.some((v,i)=>i&&ap[i-1]>=v)){reject();return;}
  if(this.quotes[d.symbol]&&Date.parse(this.quotes[d.symbol].datetime)>=at)return;
  const preciseTime=new Date(at).toISOString().replace(/(\.\d{3})Z$/,(_all,m)=>m+String(d.time%1000).padStart(3,'0')+'Z');
  this.quotes[d.symbol]={datetime:preciseTime,received_at:new Date(this.clock()).toISOString(),
   bid_price:bp,ask_price:ap,bid_volume:d.bids.map(x=>x.size),ask_volume:d.asks.map(x=>x.size),
   source:'esun',source_epoch:this.epoch,size_units:'provider_native_unverified',simtrade:false,suspend:false};
 }
 flush(){this.write(path.join(this.directory,'esun-books.json'),{schema_version:1,provider:'esun',
  generated_at:new Date(this.clock()).toISOString(),epoch:this.epoch,connected:this.connected,
  states:Object.fromEntries([...this.records].map(([s,r])=>[s,r.state])),books:this.connected?this.quotes:{}});}
}
module.exports={Books};
