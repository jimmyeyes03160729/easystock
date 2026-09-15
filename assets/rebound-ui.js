(() => {
'use strict';
const el=id=>document.getElementById(id),money=n=>Number(n).toFixed(2);
let generation=0,lastKey='',cache=new Map();
function node(tag,text,cls){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;}
function card(r,index,watch){
 const s=r.stock,t=r.technical,f=r.financial,e=node('article',undefined,'rebound-card');
 const header=node('div',undefined,'rebound-card-head');header.append(node('span',watch?'技術觀察':`TOP ${index+1}`,'rebound-rank'),node('span',`排序 ${t.score} 分 · 非勝率`,'text-sub'));e.append(header);
 const quote=node('div',undefined,'rebound-quote');
 quote.append(node('h3',`${s.symbol} ${s.name||''}`));
 const price=node('strong',money(s.price)+' 元','rebound-price');
 price.classList.add(t.dailyChangePct>0?'market-up':t.dailyChangePct<0?'market-down':'text-main');
 quote.append(price);e.append(quote);
 const details=node('details'),summary=node('summary','支撐、風險與檢查數據');details.append(summary);
 details.append(node('p',t.reasons.join(' · '),'text-sub'));
 const grid=node('dl',undefined,'rebound-levels');
 for(const [label,value] of [['支撐帶',t.support.map(money).join('～')],['壓力帶',t.resistance.map(money).join('～')],['策略失效價',money(t.invalid)],['觀察目標',money(t.target)]]){grid.append(node('dt',label),node('dd',value));}
 details.append(grid,node('p',`價格空間／失效距離 ${t.rr.toFixed(1)} 倍（未扣成本）`,'text-sub'));
 e.append(node('p',watch?'基本面待補：'+f.missing.join('、'):'營收、獲利與負債初篩通過；FCF 為輔助資訊',watch?'rebound-warning':'rebound-pass'));
 for(const c of f.checks)details.append(node('p',`${c.label}：${c.value} · ${c.period||'期間待確認'} · 取得 ${c.observed_at}`));
 const fcf=(f.optional||[]).find(x=>x.key==='fcf');
 if(fcf?.status==='positive')details.append(node('p',`自由現金流：${fcf.value}（輔助正向，不作必要門檻）`));
 else if(fcf?.status==='negative')details.append(node('p',`自由現金流：${fcf.value}（輔助警示，不作必要門檻）`));
 else details.append(node('p','自由現金流：目前來源未提供可靠欄位，不作淘汰條件。'));
 details.append(node('p','只檢查最新可用資料，尚未驗證歷史勝率。'));e.append(details);
 const button=node('button','查看日 K ↗','btn');button.type='button';button.addEventListener('click',()=>{s.rangeRebound=r;openStockDetail(String(s.symbol),'RANGE_REBOUND');});e.append(button);
 return e;
}
async function fetchBars(stock){
 const ctrl=new AbortController(),timeout=setTimeout(()=>ctrl.abort(),10000);
 try {const r=await fetch(stockKlineUrl(stock),{cache:'no-store',signal:ctrl.signal});if(!r.ok)throw new Error('kline');return await r.json();}
 finally{clearTimeout(timeout);}
}
async function refresh(pool,meta){
 const asof=meta.updated_at,key=[meta.release_id,asof,...pool.map(s=>s.symbol)].join('|');
 if(key===lastKey)return;lastKey=key;const mine=++generation;
 const status=el('reboundStatus'),picks=el('reboundPicks'),watch=el('reboundWatch'),progress=el('reboundProgress');
 picks.replaceChildren();watch.replaceChildren();el('reboundWatchSection').hidden=true;
 const age=RangeRebound.dayNumber(taiwanDay())-RangeRebound.dayNumber(asof);
 if(!(age>=0&&age<=7)){status.textContent='等待有效的日線資料，暫不推薦。';progress.textContent='';return;}
 const tally={failed:0,incomplete:0,missing:0,technical:0,short:0,illiquid:0};
 const jobs=[];const rows=[];
 for(const stock of pool){
  if(!/^\d{4}$/.test(String(stock.symbol))||stock.updated_at!==asof){tally.short++;continue;}
  if(typeof stock.amount!=='number'||stock.amount<5000000){tally.illiquid++;continue;}
  const f=RangeRebound.financial(stock,asof);
  if(['failed','unsupported'].includes(f.status)){tally.failed++;continue;}
  if(f.status==='incomplete')tally.incomplete++;
  if(Number.isFinite(stock.kline_count)&&stock.kline_count<120){tally.short++;continue;}
  jobs.push({stock,financial:f});
 }
 status.textContent='正在檢查支撐、止跌與基本面…';
 let next=0,done=0;
 const update=()=>{progress.textContent=`資料 ${asof} · 已檢查 ${done} / ${jobs.length} 檔 · 股票池 ${pool.length} 檔`;};update();
 async function worker(){
  while(next<jobs.length&&mine===generation){
   const r=jobs[next++],cacheKey=`${meta.release_id||asof}:${r.stock.symbol}`;
   try{
    let t=cache.get(cacheKey);
    if(!t){const b=Array.isArray(r.stock.kline)&&r.stock.kline.length?r.stock.kline:await fetchBars(r.stock);if(mine!==generation)return;t=RangeRebound.technical(b,asof,r.stock.price);cache.set(cacheKey,t);}
    r.technical=t;if(t.eligible)rows.push(r);else tally.technical++;
   }catch(e){tally.missing++;}
   done++;if(mine===generation)update();
  }
 }
 await Promise.all([worker(),worker(),worker()]);if(mine!==generation)return;
 const ranked=rows.sort((a,b)=>b.technical.score-a.technical.score||String(a.stock.symbol).localeCompare(String(b.stock.symbol)));
 const selected=ranked.filter(r=>r.financial.status==='passed').slice(0,3),pending=ranked.filter(r=>r.financial.status==='incomplete').slice(0,3);
 if(selected.length)status.textContent=`本次 ${selected.length} 檔通過試行規則；最多三檔。`;
 else if(pending.length)status.textContent='有股票形成底部止跌型態，但基本面資料仍不完整，暫不列入正式推薦。';
 else status.textContent='今天沒有同時形成支撐、止跌突破與基本面合格的股票，不硬湊三檔。';
 selected.forEach((r,i)=>picks.append(card(r,i,false)));
 if(pending.length){el('reboundWatchSection').hidden=false;pending.forEach((r,i)=>watch.append(card(r,i,true)));}
 el('reboundDiagnostics').textContent=`基本面未達門檻或產業不適用 ${tally.failed} 檔；基本面資料待補 ${tally.incomplete} 檔；日 K／日期不足 ${tally.short} 檔；成交金額不足 ${tally.illiquid} 檔；型態尚未成立 ${tally.technical} 檔；K 線讀取失敗 ${tally.missing} 檔。`;
 if(tally.missing)status.textContent+=' 部分行情未讀取，本次排序不完整。';
 if(cache.size>2000)cache.clear();
}
window.RangeReboundUI={refresh:(pool,meta)=>refresh(pool,meta).catch(()=>{el('reboundStatus').textContent='底部反彈檢查暫時失敗，請重新整理。';lastKey='';}),
 detail(stock){
  const r=stock.rangeRebound;if(!r)return;
  el('scoreValue').textContent=r.technical.score;el('scoreLabel').textContent=r.financial.status==='passed'?'底部反彈候選':'基本面待確認';
  el('scoreQuality').textContent='規則試行 · 排序分不是勝率';el('scoreCircle').style.setProperty('--score',r.technical.score+'%');
  el('factorGrid').replaceChildren(node('p','支撐 '+r.technical.support.map(money).join('～')+' 元'),node('p','壓力 '+r.technical.resistance.map(money).join('～')+' 元'),node('p','基本面：'+(r.financial.status==='passed'?'營收、獲利、負債初篩通過':r.financial.missing.join('、')+'待確認')));
  el('modalReason').replaceChildren(...r.technical.reasons.map(x=>node('p','• '+x)));
  el('stockBacktest').replaceChildren(node('p','底部反彈策略尚無獨立回測與訓練結果，不沿用其他策略的勝率。'));
 },
 chart(stock,series){
  const r=stock.rangeRebound;if(!r)return;
  const color=getComputedStyle(document.documentElement).getPropertyValue('--main').trim()||'#888888';
  for(const [title,price] of [['支撐下緣',r.technical.support[0]],['支撐上緣',r.technical.support[1]],['壓力',r.technical.target],['失效',r.technical.invalid]])series.createPriceLine({price,color,lineWidth:1,lineStyle:2,axisLabelVisible:true,title});
 }
};
el('reboundRetry').addEventListener('click',()=>{lastKey='';cache.clear();window.RangeReboundUI.refresh(priceFilteredStocks(),META);});
if(typeof priceFilteredStocks==='function')window.RangeReboundUI.refresh(priceFilteredStocks(),META);
})();
