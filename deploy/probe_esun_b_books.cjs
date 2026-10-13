'use strict';
// Bounded market-data-only experiment. Never feeds LaneSuite or writes live state.
const fs = require('node:fs');
const path = require('node:path');

function options(argv) {
  const out = {seconds:60, symbols:['2330','2317','2881'],
    client:'/home/ubuntu/easystock/vm_runtime/esun_marketdata/client.js',
    health:'/home/ubuntu/easystock-market-data/esun.json'};
  for(let i=0;i<argv.length;i+=2) {
    const key=argv[i], value=argv[i+1];
    if(value===undefined) throw Error('invalid_arguments');
    if(key==='--symbols') out.symbols=value.split(',');
    else if(key==='--seconds') out.seconds=Number(value);
    else if(key==='--client') out.client=value;
    else if(key==='--health-file') out.health=value;
    else throw Error('invalid_arguments');
  }
  out.symbols=[...new Set(out.symbols)];
  if(!Number.isInteger(out.seconds)||out.seconds<15||out.seconds>90||
     !out.symbols.length||out.symbols.length>40||
     out.symbols.some(s=>!(/^[1-9][0-9]{3}$/.test(s)))||
     !path.isAbsolute(out.client)||!path.isAbsolute(out.health)) throw Error('invalid_arguments');
  return out;
}
function deadline(promise,ms) {
  let timer; return Promise.race([promise,new Promise((_,reject)=>{
    timer=setTimeout(()=>reject(Error('timeout')),ms);
  })]).finally(()=>clearTimeout(timer));
}
function healthy(filename,now=Date.now()) {
  try {
    const h=JSON.parse(fs.readFileSync(filename,'utf8')),age=now-Date.parse(h.checked_at);
    return !!(h.connected&&h.authenticated&&h.parser_ok&&Number.isFinite(age)&&age>=0&&age<=20000);
  } catch(_) {return false;}
}
function quoteTime(value) {
  if(typeof value!=='number'||!Number.isFinite(value)||value<=0) throw Error('invalid_time');
  return value/(value>=1e17?1e6:value>=1e14?1e3:value>=1e11?1:.001);
}
function validBook(d) {
  const ok=levels=>Array.isArray(levels)&&levels.length===5&&levels.every(x=>x&&
    typeof x.price==='number'&&Number.isFinite(x.price)&&x.price>0&&
    typeof x.size==='number'&&Number.isFinite(x.size)&&x.size>=0);
  return ok(d.bids)&&ok(d.asks)&&d.bids[0].price<d.asks[0].price&&
    d.bids.every((x,i)=>!i||x.price<d.bids[i-1].price)&&
    d.asks.every((x,i)=>!i||x.price>d.asks[i-1].price);
}
class Metrics {
  constructor(symbols) {
    this.symbols=new Set(symbols);this.acks=new Map();this.errors=[];this.invalid={};
    this.rows=Object.fromEntries(symbols.map(s=>[s,{symbol:s,books:0,trades:0,
      fresh_books:0,fresh_trades:0,snapshots:0,book_span_ms:0,latencies:[],last_book_time:null,
      first_book_time:null,last_trade_serial:null,invalid_book_count:0,first_invalid_book_shape:null}]));
  }
  reject(reason) {this.invalid[reason]=(this.invalid[reason]||0)+1;}
  message(raw,now=Date.now()) {
    let m;try {m=typeof raw==='string'?JSON.parse(raw):raw;}catch(_){this.reject('invalid_json');return;}
    if(!m||typeof m.event!=='string'){this.reject('invalid_event');return;}
    if(m.event==='error') {this.errors.push({event:'error',code:Number.isFinite(m.data?.code)?m.data.code:null});return;}
    if(m.event==='subscribed') {
      for(const d of Array.isArray(m.data)?m.data:[m.data])
        if(d&&this.symbols.has(d.symbol)&&['books','trades'].includes(d.channel)&&typeof d.id==='string')
          this.acks.set(d.channel+':'+d.symbol,d.id);
      return;
    }
    if(!['data','snapshot'].includes(m.event))return;
    const d=m.data,row=this.rows[d?.symbol],channel=m.channel;
    if(!row||!['books','trades'].includes(channel))return;
    if(d.isTrial||d.isDelayedOpen||d.isDelayedClose){this.reject('trial_or_delayed');return;}
    let at;try{at=quoteTime(d.time);}catch(_){this.reject('invalid_time');return;}
    const age=now-at;
    if(age < -2000){this.reject('future_time');return;}
    if(channel==='books'&&!validBook(d)){
      row.invalid_book_count++;
      row.first_invalid_book_shape??={bids_count:Array.isArray(d.bids)?d.bids.length:null,
        asks_count:Array.isArray(d.asks)?d.asks.length:null,
        bids_zero_price:Array.isArray(d.bids)?d.bids.some(x=>x?.price===0):null,
        asks_zero_price:Array.isArray(d.asks)?d.asks.some(x=>x?.price===0):null};
      this.reject('invalid_five_levels');return;
    }
    if(channel==='trades'&&(!Number.isFinite(d.price)||d.price<=0||!Number.isFinite(d.size)||d.size<=0||
       !Number.isSafeInteger(d.serial)||d.serial<0)){this.reject('invalid_trade');return;}
    // A last snapshot is never evidence of continuous live observations.
    if(m.event==='snapshot'){row.snapshots++;return;}
    if(channel==='books') {
      if(row.last_book_time!==null&&at<=row.last_book_time){this.reject('duplicate_or_old_book');return;}
      row.last_book_time=at;row.books++;
      if(age<=3000){row.fresh_books++;row.first_book_time??=at;
        row.book_span_ms=at-row.first_book_time;}
    } else {
      if(row.last_trade_serial!==null&&d.serial<=row.last_trade_serial){this.reject('duplicate_or_old_trade');return;}
      row.last_trade_serial=d.serial;row.trades++;if(age<=3000)row.fresh_trades++;
    }
    if(row.latencies.length<10000)row.latencies.push(Math.max(0,age));
  }
  summary() {
    const percentile=(a,p)=>a.length?a.slice().sort((x,y)=>x-y)[Math.ceil(a.length*p)-1]:null;
    return {acknowledged_channels:this.acks.size,errors:this.errors,invalid:this.invalid,
      rows:Object.values(this.rows).map(({latencies,...r})=>({...r,
        latency_p50_ms:percentile(latencies,.5),latency_p95_ms:percentile(latencies,.95)}))};
  }
}
async function runProbe(config,{factory,checkHealth=()=>healthy(config.health),sleep=ms=>
  new Promise(resolve=>setTimeout(resolve,ms))}={}) {
  const metrics=new Metrics(config.symbols),started=new Date().toISOString();
  let stock,stopReason=null,monitor,disconnected=false,closing=false;
  if(!checkHealth())return {started_at:started,stop_reason:'existing_provider_not_healthy',production_changed:false};
  try {
    const sdk=(factory||require(config.client).createClient)();
    await deadline(Promise.resolve(sdk.login()),15000);
    stock=sdk.websocketClient.stock;
    stock.on('message',raw=>{metrics.message(raw);if(metrics.errors.length)stopReason='provider_error';});
    stock.on('error',()=>{stopReason='socket_error';});
    stock.on('disconnect',()=>{disconnected=true;if(!closing)stopReason??='socket_disconnected';});
    stock.on('unauthenticated',()=>{stopReason='authentication_failed';});
    await deadline(Promise.resolve(stock.connect()),15000);
    if(!stopReason) {
      for(const channel of (config.channels||['books','trades'])) {
        if(stopReason)break;
        await deadline(Promise.resolve(stock.subscribe({channel,symbols:config.symbols})),3000);
      }
      const until=Date.now()+config.seconds*1000;
      monitor=setInterval(()=>{if(!checkHealth())stopReason='existing_provider_health_changed';},5000);
      while(!stopReason&&Date.now()<until)await sleep(Math.min(1000,until-Date.now()));
    }
  } catch(_) {stopReason??='connection_or_subscription_failed';}
  finally {
    closing=true;
    clearInterval(monitor);
    if(stock) {
      try {const ids=[...metrics.acks.values()];if(ids.length&&!disconnected)
        await deadline(Promise.resolve(stock.unsubscribe({ids})),2000);}catch(_){metrics.reject('cleanup_unsubscribe_uncertain');}
      try{await deadline(Promise.resolve(stock.disconnect()),2000);}catch(_){metrics.reject('cleanup_disconnect_uncertain');}
    }
  }
  const summary=metrics.summary();
  return {schema_version:1,provider:'esun',started_at:started,ended_at:new Date().toISOString(),
    requested_symbols:config.symbols.length,requested_channels:config.symbols.length*(config.channels||['books','trades']).length,
    configured_observation_seconds:config.seconds,stop_reason:stopReason,
    existing_provider_healthy_after:checkHealth(),...summary,
    deployment_allowed:false,production_changed:false,
    caveats:['bounded_intraday_sample_not_opening_session','no_lane_signals_or_fills_generated',
      'trade_aggressor_direction_not_verified','not_a_full_300_subscription_capacity_test']};
}
if(require.main===module) {
  let config;try{config=options(process.argv.slice(2));}catch(_){process.stderr.write('invalid_arguments\n');process.exit(2);}
  runProbe(config).then(result=>{process.stdout.write(JSON.stringify(result)+'\n');process.exit(result.stop_reason?1:0);})
    .catch(()=>{process.stderr.write('probe_failed\n');process.exit(1);});
}
module.exports={options,healthy,quoteTime,validBook,Metrics,runProbe};
