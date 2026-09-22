/* Same-session candles and recorded model evidence for simulated trades. */
(() => {
 const style=document.createElement('style');style.textContent=`
 .trade-open{color:#047857!important;background:#d1fae5;border-color:#059669!important}.trade-closed{color:#1d4ed8!important;background:#dbeafe;border-color:#3b82f6!important}
 .trade-detail-card{cursor:pointer}.trade-detail-card:hover,.trade-detail-card:focus-visible{outline:2px solid var(--main);outline-offset:2px}
 #tradeDialog{width:min(920px,94vw);max-height:90vh;overflow:auto;background:var(--bg,#141414);color:var(--main,#eee);border:1px solid var(--border,#555);border-radius:14px;padding:22px}#tradeDialog::backdrop{background:#0009}
 #tradeDialog header{display:flex;align-items:start;justify-content:space-between;gap:16px}#tradeDialog h2{font-size:20px;font-weight:800;margin-bottom:10px}#tradeDialog p,#tradeDialog li{font-size:13px;line-height:1.8}#tradeDialog ul{padding-left:20px;list-style:disc}#tradeDialog svg{width:100%;height:auto;min-width:560px}#tradeChart{overflow-x:auto;margin:14px 0}#tradeDialog button{padding:7px 12px;border:1px solid var(--border,#555);border-radius:6px}#tradeDialog .trade-status{padding:4px 9px;border-radius:5px;display:inline-block}#tradeDialog h3{font-weight:750;margin:14px 0 6px}
 `;document.head.append(style);
 const dialog=document.createElement('dialog');dialog.id='tradeDialog';dialog.setAttribute('aria-labelledby','tradeTitle');
 dialog.innerHTML='<header><div><h2 id="tradeTitle"></h2><span id="tradeStatus" class="trade-status"></span></div><button type="button" aria-label="關閉當日K線">關閉 ✕</button></header><p id="tradeOutcome"></p><p id="tradeChartNote" role="status"></p><div id="tradeChart"></div><h3>為什麼選入這檔？</h3><p id="tradeModelReason"></p><ul id="tradeReasons"></ul><p>圖中紅 K 為上漲、綠 K 為下跌；只顯示已完成的 5 分 K，進出場以模擬成交紀錄為準。</p>';
 document.body.append(dialog);dialog.querySelector('button').onclick=()=>dialog.close();
 let selected=null,generation=0,controller=null;
 dialog.addEventListener('close',()=>{selected=null;generation++;controller?.abort();});
 const put=(id,v)=>document.getElementById(id).textContent=v;
 const number=v=>v!==null&&v!==undefined&&v!==''&&Number.isFinite(Number(v))?Number(v):null;
 const price=v=>number(v)===null?'未提供':Number(v).toFixed(2);
 const day=v=>{const t=Date.parse(v);return Number.isFinite(t)?new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Taipei'}).format(new Date(t)):'';};
 const clock=v=>new Date(v).toLocaleTimeString('zh-TW',{timeZone:'Asia/Taipei',hour:'2-digit',minute:'2-digit',hour12:false});
 function trades(){return [...Object.values(INTRADAY_LIVE?.open_positions||{}).map(x=>({...x,open:true})),...Object.values(INTRADAY_LIVE?.closed_trades||{}).map(x=>({...x,open:false}))];}
 function evidence(t){
  const e=t.model_evidence||{},f=e.features||{},score=number(e.score??t.entry_score),threshold=number(e.threshold);
  put('tradeModelReason',threshold!==null&&score!==null?`進場時模型分數 ${score.toFixed(4)}，達到門檻 ${threshold.toFixed(4)}，通過報價與資金檢查後模擬買入。分數不是勝率。`:'此筆未保存完整模型門檻；以下僅列原始進場紀錄，不推測模型因果。');
  const lines=[];
  for(const [key,label,suffix] of [['gain_pct','相對昨收','%'],['return_5m_pct','近 5 分鐘報酬','%'],['volume_ratio','成交量比',' 倍'],['buy_ratio_60s','近 60 秒主動買入比',''],['vwap_distance_pct','偏離成交量加權均價','%']]){
   if(number(f[key])!==null)lines.push(`${label}：${Number(f[key]).toFixed(2)}${suffix}`);
  }
  if(e.model_version)lines.push(`模型版本：${e.model_version}`);
  if(!lines.length)lines.push(...(Array.isArray(t.entry_reasons)?t.entry_reasons.map(String):[]));
  const list=document.getElementById('tradeReasons');list.replaceChildren();for(const line of lines.length?lines:['尚無可用的進場依據']){const li=document.createElement('li');li.textContent=line;list.append(li);}
 }
 function draw(payload,t){
  const target=document.getElementById('tradeChart');target.replaceChildren();const wanted=day(t.entry_time);
  const bars=(Array.isArray(payload?.bars)?payload.bars:[]).filter(b=>day(b.time)===wanted&&['open','high','low','close','volume'].every(k=>number(b[k])!==null)&&b.low>0&&b.volume>=0&&b.low<=Math.min(b.open,b.close)&&b.high>=Math.max(b.open,b.close)).sort((a,b)=>Date.parse(a.time)-Date.parse(b.time));
  if(payload?.date!==wanted||!bars.length){put('tradeChartNote',`${wanted||'該交易日'} 尚無可用的當日K線，等待永豐行情同步。`);return;}
  const age=Date.now()-Date.parse(payload.updated_at),stale=!Number.isFinite(age)||age>180000;
  put('tradeChartNote',`${wanted} · 永豐行情 · 5 分 K · 更新 ${Number.isFinite(Date.parse(payload.updated_at))?clock(payload.updated_at):'時間未提供'}${t.open&&stale?' · 資料延遲，以下為最後快照':!t.open?' · 已平倉交易紀錄':''}`);
  const W=800,H=350,left=58,right=690,top=20,bottom=250,range=[...bars.flatMap(b=>[Number(b.low),Number(b.high)]),...['entry_price','exit_price'].map(k=>number(t[k])).filter(x=>x!==null)];
  let lo=Math.min(...range),hi=Math.max(...range),pad=Math.max((hi-lo)*.08,hi*.001);lo-=pad;hi+=pad;
  const start=Date.parse(`${wanted}T09:00:00+08:00`),span=270*60000,x=time=>left+(Date.parse(time)-start)/span*(right-left),y=p=>bottom-(p-lo)/(hi-lo)*(bottom-top),barWidth=7;
  const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox',`0 0 ${W} ${H}`);svg.setAttribute('role','img');svg.setAttribute('aria-label',`${t.symbol} ${wanted} 五分鐘K線與進出場位置`);
  function add(tag,attrs,text){const el=document.createElementNS(ns,tag);for(const [k,v]of Object.entries(attrs))el.setAttribute(k,String(v));if(text!==undefined)el.textContent=text;svg.append(el);return el;}
  for(let i=0;i<5;i++){const p=lo+(hi-lo)*i/4;add('line',{x1:left,x2:right,y1:y(p),y2:y(p),stroke:'currentColor',opacity:.12});add('text',{x:3,y:y(p)+4,fill:'currentColor','font-size':11},p.toFixed(2));}
  const maxVol=Math.max(1,...bars.map(b=>Number(b.volume)));
  for(const b of bars){const color=b.close>=b.open?'#f87171':'#34d399',cx=x(b.time)+barWidth/2;add('line',{x1:cx,x2:cx,y1:y(b.high),y2:y(b.low),stroke:color});const rect=add('rect',{x:cx-barWidth/2,y:Math.min(y(b.open),y(b.close)),width:barWidth,height:Math.max(1,Math.abs(y(b.open)-y(b.close))),fill:color});const title=document.createElementNS(ns,'title');title.textContent=`${clock(b.time)} 開 ${b.open} 高 ${b.high} 低 ${b.low} 收 ${b.close} 量 ${b.volume}`;rect.append(title);add('rect',{x:cx-barWidth/2,y:310-b.volume/maxVol*42,width:barWidth,height:b.volume/maxVol*42,fill:color,opacity:.5});}
  for(const time of ['09:00','10:00','11:00','12:00','13:00','13:30'])add('text',{x:x(`${wanted}T${time}:00+08:00`),y:335,fill:'currentColor','font-size':11,'text-anchor':'middle'},time);
  for(const [key,when,label,color]of [['entry_price','entry_time','買入','#fbbf24'],['exit_price','exit_time','賣出','#60a5fa']])if(number(t[key])!==null&&day(t[when])===wanted){add('line',{x1:left,x2:right,y1:y(Number(t[key])),y2:y(Number(t[key])),stroke:color,'stroke-dasharray':'4 4'});add('circle',{cx:x(t[when]),cy:y(Number(t[key])),r:5,fill:color});add('text',{x:right+5,y:y(Number(t[key]))+4,fill:color,'font-size':11},`${label} ${price(t[key])}`);}
  target.append(svg);
 }
 async function refresh(t){const mine=++generation;controller?.abort();controller=new AbortController();const timer=setTimeout(()=>controller.abort(),12000);try{
  const response=await fetch(`${FIREBASE_ROOT}/intraday_live/charts/${encodeURIComponent(t.symbol)}.json`,{cache:'no-store',signal:controller.signal});if(!response.ok)throw Error('讀取失敗');const payload=await response.json();if(mine===generation){const status=document.getElementById('tradeStatus');status.textContent=t.open?'OPEN · 持倉中':'CLOSE · 已平倉';status.className=`trade-status ${t.open?'trade-open':'trade-closed'}`;put('tradeOutcome',t.open?`模擬買入 ${price(t.entry_price)} 元 · 持倉損益尚未實現。`:`模擬買入 ${price(t.entry_price)} 元 → 賣出 ${price(t.exit_price)} 元 · 成本後報酬 ${price(t.pnl_pct)}% · ${t.exit_reason||'已平倉'}`);draw(payload,t);}
 }catch(e){if(mine===generation)put('tradeChartNote','當日K線暫時無法讀取，請稍後重新開啟。');}finally{clearTimeout(timer);}}
 function open(card){const t=trades().find(r=>String(r.symbol)===card.dataset.tradeSymbol&&String(r.entry_time||'')===card.dataset.tradeEntry);if(!t)return;selected=t;
  put('tradeTitle',`${t.symbol} ${t.name||''} · 當日K線`);const status=document.getElementById('tradeStatus');status.textContent=t.open?'OPEN · 持倉中':'CLOSE · 已平倉';status.className=`trade-status ${t.open?'trade-open':'trade-closed'}`;
  put('tradeOutcome',t.open?`模擬買入 ${price(t.entry_price)} 元 · 持倉損益尚未實現。`:`模擬買入 ${price(t.entry_price)} 元 → 賣出 ${price(t.exit_price)} 元 · 成本後報酬 ${price(t.pnl_pct)}% · ${t.exit_reason||'已平倉'}`);
  evidence(t);document.getElementById('tradeChart').replaceChildren();put('tradeChartNote','讀取當日K線…');if(!dialog.open)dialog.showModal();refresh(t);
 }
 document.addEventListener('click',e=>{const card=e.target.closest('[data-trade-symbol]');if(card)open(card);});
 document.addEventListener('keydown',e=>{if((e.key==='Enter'||e.key===' ')&&e.target.matches('[data-trade-symbol]')){e.preventDefault();open(e.target);}});
 setInterval(()=>{if(selected&&dialog.open){const latest=trades().find(t=>t.symbol===selected.symbol&&t.entry_time===selected.entry_time);if(latest)selected=latest;refresh(selected);}},60000);
})();
