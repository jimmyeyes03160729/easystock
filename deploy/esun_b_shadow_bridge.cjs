'use strict';
// Only this bounded child connection is opened; no live publisher or strategy API.
const {options,runProbe,validBook,quoteTime}=require('./probe_esun_b_books.cjs');
const emit=x=>process.stdout.write(JSON.stringify({...x,provider:'esun',received_at:new Date().toISOString()})+'\n');
function makeFactory(createClient,config,send=emit) {
  return ()=>{
    const emit=send;
    const sdk=createClient();
    // The installed SDK constructs a new websocket factory with the current
    // token on every access. Resolve and bind it only AFTER login succeeds.
    return {login:()=>sdk.login(),get websocketClient(){
    const stock=sdk.websocketClient.stock;
    stock.on('message',raw=>{
      let m;try{m=typeof raw==='string'?JSON.parse(raw):raw;}catch(_){return;}
      if(m?.event==='authenticated')emit({kind:'connected'});
      if(m?.event==='subscribed')for(const d of Array.isArray(m.data)?m.data:[m.data])
        if(d?.channel==='books'&&config.symbols.includes(d.symbol))emit({kind:'ack',symbol:d.symbol});
      const d=m?.data;
      if(m?.event==='data'&&m.channel==='books'&&config.symbols.includes(d?.symbol)&&
         !d.isTrial&&!d.isDelayedOpen&&!d.isDelayedClose&&validBook(d)){
        let at;try{at=quoteTime(d.time);}catch(_){return;}
        if(Date.now()-at<0||Date.now()-at>3000)return;
        emit({kind:'book',symbol:d.symbol,exchange_time_us:d.time,size_units:'provider_native_unverified',quote:{
          datetime:new Date(at).toISOString(),bid_price:d.bids.map(x=>x.price),ask_price:d.asks.map(x=>x.price),
          bid_volume:d.bids.map(x=>x.size),ask_volume:d.asks.map(x=>x.size),simtrade:false,suspend:false}});
      }
      if(m?.event==='error')emit({kind:'error',code:Number.isFinite(m.data?.code)?m.data.code:null});
    });
    stock.on('disconnect',()=>emit({kind:'disconnected'}));
    stock.on('error',()=>emit({kind:'error',code:null}));
    stock.on('unauthenticated',()=>emit({kind:'error',code:null}));
    return {stock};}};
  };
}
async function main(argv) {
  const config=options(argv);config.channels=['books'];
  const {createClient}=require(config.client);
  const factory=makeFactory(createClient,config);
  const report=await runProbe(config,{factory});emit({kind:'finished',report});
  process.exit(report.stop_reason?1:0);
}
if(require.main===module)main(process.argv.slice(2)).catch(()=>{emit({kind:'error',code:null});process.exit(1);});
module.exports={makeFactory};
