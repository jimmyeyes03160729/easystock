(function(global){
  'use strict';
  const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const num=x=>typeof x==='number'&&Number.isFinite(x);
  const value=x=>num(x)?x.toFixed(2):'—';
  const state={pass:'通過',fail:'未通過',insufficient:'資料不足'};
  const local=now=>new Date(now.getTime()+8*3600000).toISOString();
  function valid(feed,version,now=new Date()){
    if(!feed||feed.schema_version!==1||feed.version!==version||feed.day!==local(now).slice(0,10))return false;
    const age=now-new Date(feed.updated_at);return Number.isFinite(age)&&age>=0&&age<=90000;
  }
  function chart(row){
    const ps=row.prices;
    if(!Array.isArray(ps)||ps.length!==4||!ps.every(num))return '';
    const low=Math.min(...ps),span=Math.max(...ps)-low||1;
    const points=ps.map((p,i)=>`${10+i*60},${60-(p-low)/span*50}`).join(' ');
    return `<svg viewBox="0 0 200 80" role="img" aria-label="昨收至09:15三段價格"><polyline fill="none" stroke="currentColor" stroke-width="2" points="${points}"/></svg><p>昨收 / 09:05 / 09:10 / 09:15：${ps.map(value).join(' / ')}</p>`;
  }
  function openingRow(r,now=new Date()){
    const pending=local(now).slice(11,19)<'09:15:00';
    return `<article class="eight-card"><h3>${esc(r.symbol)} ${esc(r.name)}</h3><p>${pending?'09:15 前尚未完成':r.status==='classified'?`第 ${esc(r.method)} 法 · ${esc((r.directions||[]).map(d=>d==='U'?'漲':d==='D'?'跌':'平').join(' → '))}`:'未分類／資料不足'}</p><p>${esc(pending?'':r.reason)}</p>${pending?'':chart(r)}<small>成交時間：${esc(r.quote_at||'無行情')}</small></article>`;
  }
  function closingRow(r,now=new Date()){
    const clock=local(now).slice(11,19),ended=clock>='13:25:00',waiting=clock<'13:00:00';
    const stale=!Number.isFinite(Date.parse(r.quote_at))||now-new Date(r.quote_at)>30000||now<new Date(r.quote_at);
    const disabled=ended||waiting||stale;
    const cs=Array.isArray(r.conditions)?r.conditions:[];
    return `<article class="eight-card"><h3>${esc(r.symbol)} ${esc(r.name)}</h3><p>股價 ${value(r.price)} · 漲跌 ${value(r.gain_pct)}% · 符合 ${disabled?0:cs.filter(c=>c.state==='pass').length}/8</p><p>${ended?'連續交易訊號已截止；13:25～13:30 收盤集合競價':waiting?'等待 13:00':stale?'資料不足：行情過期':esc(r.reason)}</p><ul>${cs.map(c=>`<li>${esc(c.label)}：<strong>${disabled?'資料不足':state[c.state]||'資料不足'}</strong> ${esc(c.reason)}</li>`).join('')}</ul><small>成交時間：${esc(r.quote_at||'無行情')}</small></article>`;
  }
  const api={esc,valid,openingRow,closingRow,chart};
  if(typeof module!=='undefined')module.exports=api;
  if(!global.document)return;
  const get=id=>global.document.getElementById(id);
  if(!get('eightMethodsModule'))return;
  let feeds={},busy=false;
  function render(){
    const query=get('eightSearch').value.trim().toLowerCase(),now=new Date();
    let messages=[];
    for(const [key,version,container,renderRow] of [['opening_eight','OPENING_EIGHT_METHODS_V1','openingRows',openingRow],['closing_eight','CLOSING_EIGHT_METHODS_V1','closingRows',closingRow]]){
      const f=feeds[key],ok=valid(f,version,now)&&(key!=='closing_eight'||f.ruleset==='TW_XQ_SCRIPT_V1');
      if(!ok){get(container).innerHTML='<p>資料不足：今日觀察 feed 尚未發布或已過期。</p>';if(key==='opening_eight')get('openingMarkets').innerHTML='<p>加權／櫃買：資料不足，尚無有效指數成交時點。</p>';messages.push('資料不足／尚未發布');continue;}
      const rows=(Array.isArray(f.rows)?f.rows:[]).filter(r=>`${r.symbol} ${r.name}`.toLowerCase().includes(query));
      get(container).innerHTML=rows.map(r=>renderRow(r,now)).join('')||'<p>目前沒有符合搜尋的觀察資料。</p>';
      if(key==='opening_eight')get('openingMarkets').innerHTML=(f.markets||[]).map(r=>openingRow(r,now)).join('');
      messages.push(`${f.source||''} · 更新 ${f.updated_at} · ${f.scope||''} ${(f.diagnostics||[]).join('；')}`);
    }
    get('eightStatus').textContent=messages.join('｜');
  }
  function tab(name){for(const n of ['opening','closing']){const selected=n===name;get(n+'Tab').setAttribute('aria-selected',String(selected));get(n+'Tab').tabIndex=selected?0:-1;get(n+'Panel').hidden=!selected;}}
  for(const n of ['opening','closing']){get(n+'Tab').addEventListener('click',()=>tab(n));get(n+'Tab').addEventListener('keydown',e=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(e.key)){e.preventDefault();const next=e.key==='Home'?'opening':e.key==='End'?'closing':n==='opening'?'closing':'opening';tab(next);get(next+'Tab').focus();}});}
  get('eightSearch').addEventListener('input',render);
  async function load(){
    if(busy)return;busy=true;
    const root=String(global.FIREBASE_ROOT||'https://easystock-c237a-default-rtdb.firebaseio.com/market_data').replace(/\/$/,'');
    await Promise.all(['opening_eight','closing_eight'].map(async key=>{try{const response=await global.fetch(`${root}/public_feed/${key}.json`,{cache:'no-store'});if(!response.ok)throw Error('feed');feeds[key]=await response.json();}catch{feeds[key]=null;}}));
    busy=false;render();
  }
  load();global.setInterval(load,30000);global.setInterval(render,1000);
})(typeof window!=='undefined'?window:globalThis);
