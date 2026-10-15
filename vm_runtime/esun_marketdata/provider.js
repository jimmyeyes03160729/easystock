'use strict';
// Only marketdata REST / WebSocket methods are exposed by this adapter.
const fs = require('node:fs');
const path = require('node:path');
const { createClient } = require('./client');
const configured = require('./indices.json').indices;
const { MarketContext } = require('./context');
const { Books } = require('./books');
const { project:equitySnapshot } = require('./equity_snapshot');
const BACKOFF = [1000, 2000, 5000, 10000, 30000, 60000];
const tpe = ms => new Date(ms + 8 * 3600000).toISOString().replace('Z', '+08:00');
function timestamp(raw) {
  const n = typeof raw === 'number' ? raw : Number(raw);
  if (!Number.isFinite(n) || n <= 0) throw Error('invalid_timestamp');
  return n / (n >= 1e17 ? 1e6 : n >= 1e14 ? 1e3 : n >= 1e11 ? 1 : .001);
}
function finite(raw) { return raw !== null && raw !== undefined && raw !== '' && Number.isFinite(Number(raw)) ? Number(raw) : null; }
function normalize(payload, mapping, now = Date.now(), previous = null) {
  if (!payload || payload.symbol !== mapping.symbol) throw Error('invalid_symbol');
  const at = timestamp(payload.lastUpdated ?? payload.time ?? payload.lastTrade?.time ?? payload.closeTime);
  if (at > now + 2000) throw Error('future_timestamp');
  const price = finite(payload.index ?? payload.lastPrice ?? payload.closePrice ?? payload.price);
  if (price === null || price <= 0) throw Error('invalid_price');
  // Index streaming events omit daily change; derive only from a verified same-day REST base.
  let change = finite(payload.change), changePct = finite(payload.changePercent);
  const previousClose = finite(payload.previousClose) ?? (change !== null ? price - change : null) ??
    (previous?.quote_at?.slice(0,10) === tpe(at).slice(0,10) ? previous.previous_close : null);
  if (change === null && previousClose > 0) change = price - previousClose;
  if (changePct === null && previousClose > 0) changePct = change / previousClose * 100;
  const age = Math.max(0, (now - at) / 1000);
  return { schema_version: 1, source: 'esun', instrument_type: 'index', symbol: mapping.symbol,
    name: mapping.name, price, change, change_pct: changePct, previous_close: previousClose,
    quote_at: tpe(at), received_at: tpe(now), age_seconds: Math.round(age),
    fresh: age <= 90 && tpe(at).slice(0,10) === tpe(now).slice(0,10),
    return_1m: null, return_5m: null, return_15m: null };
}
function atomic(filename, value) {
  fs.mkdirSync(path.dirname(filename), {recursive:true, mode:0o700});
  const temp = filename + '.' + process.pid + '.tmp';
  fs.writeFileSync(temp, JSON.stringify(value), {mode:0o600});
  fs.renameSync(temp, filename);
}
function deadline(promise, ms = 15000) {
  let timer;
  return Promise.race([promise, new Promise((_, reject) => {timer=setTimeout(()=>reject(Error('timeout')),ms);})])
    .finally(()=>clearTimeout(timer));
}
class Provider {
  constructor({factory = createClient, directory = process.env.EASYSTOCK_MARKET_DATA_DIR || '/home/ubuntu/easystock-market-data', clock = Date.now,
    sleep = ms => new Promise(resolve=>setTimeout(resolve,ms))} = {}) {
    this.factory=factory;this.directory=directory;this.clock=clock;this.sleep=sleep;this.quotes={};this.stopped=false;
    this.diagnostic={source:'esun',provider_version:'1',connected:false,authenticated:false,
      subscribed:false,parser_ok:true,reconnect_count:0,consecutive_failures:0,reconnect_state:'idle'};
    this.wanted=Object.entries(configured).filter(([,value])=>value.enabled);
    this.acks=new Set();this.lastArchive=0;this.lastPoll=0;this.inFlight=false;
    this.marketContext=new MarketContext();this.breadthSnapshots={};this.breadthReceivedAt={};this.lastBreadthPoll=-Infinity;
    this.openingBoundaryDay=null;this.openingBoundarySeen=new Set();
    this.books=new Books({directory:this.directory,clock:this.clock,write:atomic});
  }
  error(code) {
    this.diagnostic.error_code=code;this.diagnostic.last_error_at=tpe(this.clock());
    this.diagnostic.consecutive_failures++;this.flush();
  }
  accept(payload) {
    const entry=this.wanted.find(([,mapping])=>mapping.symbol===payload?.symbol);
    if (!entry) return;
    try {
      const [key,mapping]=entry, quote=normalize(payload,mapping,this.clock(),this.quotes[key]);
      if (this.quotes[key] && quote.quote_at < this.quotes[key].quote_at) return;
      this.quotes[key]=quote;this.diagnostic.parser_ok=true;
      this.marketContext.observe(key,quote);
      this.diagnostic.last_data_at=quote.received_at;this.diagnostic.quote_at=this.quotes.taiex?.quote_at || quote.quote_at;
      this.diagnostic.last_ok_at=quote.received_at;this.diagnostic.consecutive_failures=0;
      this.diagnostic.error_code=null;
    } catch (_) { this.diagnostic.parser_ok=false;this.error('parser_invalid'); }
  }
  message(raw) {
    try {
      const message=typeof raw==='string'?JSON.parse(raw):raw;
      if (!message || typeof message.event !== 'string') throw Error('invalid_event');
      this.books.message(message);
      this.diagnostic.last_event_at=tpe(this.clock());
      if (['heartbeat','pong'].includes(message.event)) this.diagnostic.last_heartbeat_at=tpe(this.clock());
      else if (message.event==='subscribed') {
        for (const item of Array.isArray(message.data)?message.data:[message.data]) if(item?.channel==='indices'&&item?.symbol)this.acks.add(item.symbol);
        this.diagnostic.subscription_count=this.acks.size;
        this.diagnostic.subscribed=this.wanted.every(([,m])=>this.acks.has(m.symbol));
      } else if (['data','snapshot'].includes(message.event)) this.accept(message.data);
      else if(message.event==='error') this.error('subscription_error');
    } catch (_) {this.books.stop();this.diagnostic.parser_ok=false;this.error('parser_invalid');}
  }
  flush() {
    const now=this.clock();
    this.captureOpeningBoundaries(now);
    this.diagnostic.checked_at=tpe(now);
    const quotes=Object.fromEntries(Object.entries(this.quotes).map(([key,quote])=>[key,{...quote,
      age_seconds:Math.max(0,Math.round((now-Date.parse(quote.quote_at))/1000)),
      fresh:now-Date.parse(quote.quote_at)<=90000 && quote.quote_at.slice(0,10)===tpe(now).slice(0,10)}]));
    atomic(path.join(this.directory,'esun.json'),this.diagnostic);
    // Reuse the Python publisher's trading-calendar decision. Missing/stale decision fails closed.
    let health={};try{health=JSON.parse(fs.readFileSync(path.join(this.directory,'public-health.json'),'utf8'));}catch(_){}
    const checked=Date.parse(health.generated_at), hour=tpe(now).slice(11,16);
    const open=health.market_state==='OPEN' && now>=checked && now-checked<=120000 &&
      tpe(checked).slice(0,10)===tpe(now).slice(0,10) && hour>='09:00' && hour<='13:30' &&
      this.diagnostic.connected && this.diagnostic.authenticated && this.diagnostic.parser_ok;
    const context={schema_version:1,generated_at:tpe(now),source:'esun',indices:quotes,
      ...this.marketContext.build(quotes,this.breadthSnapshots,now,!!open),
      features:{market_return_1m:null,market_return_5m:null,market_return_15m:null,
        sector_return_1m:null,sector_return_5m:null,sector_return_15m:null,sector_vs_market_strength:null,market_regime:null}};
    atomic(path.join(this.directory,'context.json'),context);
    atomic(path.join(this.directory,'equity-snapshot.json'),equitySnapshot(this.breadthSnapshots,now,this.breadthReceivedAt));
    // Dataset snapshots: only fresh exchange data; keep receipt time separate, no invented returns.
    if(now-this.lastArchive>=60000 && Object.values(quotes).some(q=>q.fresh)) {
      const dir=path.join(this.directory,'dataset');fs.mkdirSync(dir,{recursive:true,mode:0o700});
      fs.appendFileSync(path.join(dir,tpe(now).slice(0,10)+'.jsonl'),JSON.stringify({received_at:tpe(now),...context})+'\n',{mode:0o600});
      this.lastArchive=now;
    }
  }
  captureOpeningBoundaries(now) {
    const day=tpe(now).slice(0,10);
    if(this.openingBoundaryDay!==day){this.openingBoundaryDay=day;this.openingBoundarySeen.clear();}
    for(const minute of ['05','10','15']) {
      const boundary=Date.parse(day+'T09:'+minute+':00+08:00');
      if(now<boundary||now-boundary>65000)continue;
      for(const key of ['taiex','otc']) {
        const id=key+minute;if(this.openingBoundarySeen.has(id))continue;
        const row=(this.marketContext.history[key]||[]).filter(q=>q.at<=boundary&&boundary-q.at<=30000).at(-1);
        if(!row)continue;
        const dir=path.join(this.directory,'opening-index-boundaries');fs.mkdirSync(dir,{recursive:true,mode:0o700});
        fs.appendFileSync(path.join(dir,day+'.jsonl'),JSON.stringify({received_at:tpe(now),
          indices:{[key]:{price:row.price,quote_at:tpe(row.at),received_at:tpe(now)}}})+'\n',{mode:0o600});
        this.openingBoundarySeen.add(id);
      }
    }
  }
  closingWindow() {
    const clock=tpe(this.clock()).slice(11,19);
    return clock>='13:00:00' && clock<'13:25:00';
  }
  async poll(client) {
    if(this.inFlight)return;this.inFlight=true;
    try {
      for(const [,mapping] of this.wanted) {
        try {this.accept(await deadline(client.restClient.stock.intraday.quote({symbol:mapping.symbol}),6000));}
        catch(_){this.error('quote_request_failed');}
      }
      if(this.clock()-this.lastBreadthPoll>=(this.closingWindow()?15000:60000)) {
        for(const market of ['TSE','OTC']) {
          try {this.breadthSnapshots[market]=await deadline(client.restClient.stock.snapshot.quotes({market}),6000);this.breadthReceivedAt[market]=this.clock();}
          catch(_) {delete this.breadthSnapshots[market];delete this.breadthReceivedAt[market];}
        }
        this.lastBreadthPoll=this.clock();
      }
    } finally {this.inFlight=false;this.lastPoll=this.clock();this.flush();}
  }
  async session() {
    const client=this.factory();await deadline(client.login());
    const stock=client.websocketClient.stock;this.stock=stock;this.acks.clear();
    const sessionToken=Symbol('esun-session');this.sessionToken=sessionToken;
    const current=()=>this.sessionToken===sessionToken;
    delete this.diagnostic.last_heartbeat_at;
    this.diagnostic.subscription_count=0;
    let sessionError=null;
    let booksStarted=false;
    stock.on('message',raw=>{if(!current())return;this.message(raw);if(booksStarted&&!this.books.connected&&!this.stopped)sessionError='websocket_error';});
    stock.on('authenticated',()=>{if(current())this.diagnostic.authenticated=true;});
    stock.on('unauthenticated',()=>{if(current()){sessionError='authentication_failed';this.books.stop();}});
    stock.on('disconnect',()=>{if(current()){sessionError='disconnected';this.diagnostic.connected=false;this.books.stop();}});
    stock.on('error',()=>{if(current()){sessionError='websocket_error';this.books.stop();}});
    await deadline(stock.connect());
    if(this.stopped||sessionError)throw Error(sessionError||'stopped');
    this.diagnostic.connected=true;this.diagnostic.authenticated=true;this.diagnostic.reconnect_state='connected';
    this.books.start(stock);
    booksStarted=true;
    const bookTimer=setInterval(()=>{try{this.books.reconcile();this.books.flush();}catch(_){sessionError='storage_error';this.books.stop();}},500);
    const sessionStarted=this.clock();
    try {
      for(const [,m] of this.wanted)stock.subscribe({channel:'indices',symbol:m.symbol});
      await this.poll(client);this.flush();
      while(!this.stopped && !sessionError) {
        await this.sleep(5000);
        if(this.stopped)break;
        if(this.clock()-(Date.parse(this.diagnostic.last_heartbeat_at)||sessionStarted)>90000) {sessionError='heartbeat_timeout';break;}
        stock.ping({});
        if(this.clock()-this.lastPoll>=(this.closingWindow()?15000:30000)) await this.poll(client);
        this.flush();
      }
      if(sessionError && !this.stopped)throw Error(sessionError);
    } finally { clearInterval(bookTimer);this.books.stop();try{stock.disconnect();}catch(_){} this.diagnostic.connected=false;this.diagnostic.authenticated=false;this.diagnostic.subscribed=false;this.flush(); }
  }
  async run() {
    let attempt=0;
    while(!this.stopped) {
      try {await this.session();attempt=0;}
      catch(error) {
        if(this.stopped)break;
        const codes=['authentication_failed','disconnected','websocket_error','heartbeat_timeout','timeout'];
        this.error(codes.includes(error.message)?error.message:'connection_failed');
        try{this.stock?.disconnect();}catch(_){}
        this.diagnostic.connected=false;this.diagnostic.authenticated=false;this.diagnostic.subscribed=false;
        const delay=BACKOFF[Math.min(attempt++,BACKOFF.length-1)];
        this.diagnostic.reconnect_count++;this.diagnostic.reconnect_state='backoff';this.diagnostic.retry_after_seconds=delay/1000;this.flush();
        console.log('[ESUN] reconnect '+this.diagnostic.error_code+' delay='+delay/1000+'s');
        await this.sleep(delay);
      }
    }
  }
  stop(){this.stopped=true;try{this.stock?.disconnect();}catch(_){} }
}
if(require.main===module){const provider=new Provider();for(const signal of ['SIGINT','SIGTERM'])process.on(signal,()=>provider.stop());provider.run().catch(()=>{console.error('[ESUN] storage_unavailable');process.exitCode=1;});}
module.exports={Provider,normalize,timestamp,BACKOFF,tpe};
