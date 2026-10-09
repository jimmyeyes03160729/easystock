(function(global){
  'use strict';
  const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const num=x=>typeof x==='number'&&Number.isFinite(x)?x.toLocaleString('zh-TW',{maximumFractionDigits:2}):'—';
  const pct=x=>typeof x==='number'&&Number.isFinite(x)?`${x.toFixed(2)}%`:'—';
  function render(data){
    const summary=data?.summary||{};
    let html='<div style="overflow-x:auto"><table class="w-full text-xs" style="min-width:860px;text-align:left"><thead><tr>'+['跑道','有效／排除／待平倉日','交易筆數','費後勝率','費後淨損益','已實現最大回撤','延遲0.5秒','延遲1秒','雙邊各多1檔'].map(x=>`<th style="padding:8px">${x}</th>`).join('')+'</tr></thead><tbody>';
    for(const lane of ['B1','B2','B3']){
      const s=summary[lane]||{},m=s.scenarios?.baseline||{};
      const stress=k=>{const v=s.scenarios?.[k]||{};return `${num(v.net_pnl)} 元<br>${num(v.days)} 日／${num(v.trades)} 筆`;};
      html+=`<tr style="border-top:1px solid var(--border,#334155)"><td style="padding:8px">${lane}</td><td>${num(s.valid_days)}／${num(s.excluded_days)}／${num(s.pending_days)}</td><td>${num(m.trades)}</td><td>${pct(m.win_rate)}</td><td>${num(m.net_pnl)} 元</td><td>${num(m.max_realized_drawdown)} 元</td><td>${stress('delay500')}</td><td>${stress('delay1000')}</td><td>${stress('extra1tick')}</td></tr>`;
    }
    html+='</tbody></table></div>';
    html+='<details class="text-xs text-sub mt-3"><summary class="cursor-pointer">成交資料與每日核對</summary>';
    for(const lane of ['B1','B2','B3']){
      const s=summary[lane]||{},r=s.execution_rates||{};
      html+=`<p class="mt-2">${lane}：出場報價過期 ${pct(r.stale_exit_pct)}；出場深度不足 ${pct(r.thin_exit_pct)}；進場深度不足 ${pct(r.thin_entry_pct)}。檢查涵蓋 ${num(s.execution_days)} 日，包含待平倉日；比例依判斷時鐘的檢查／重試次數計算，並非獨立委託比例。</p>`;
    }
    const rows=Array.isArray(data?.daily)?data.daily:Object.values(data?.daily||{});
    if(!rows.length) html+='<p class="mt-2">尚未發現可盤點的日期。</p>';
    html+='<ul class="mt-3">'+rows.slice().reverse().slice(0,20).map(day=>{
      const status=Object.entries(day.lanes||{}).map(([lane,s])=>`${lane}：${s.status==='complete'?'完成':s.status==='pending'?'待平倉':'排除'}${s.reasons?.length?'（'+s.reasons.join('、')+'）':''}`).join('；');
      const c=day.comparison;
      const proof=c?`；回放時鐘不一致 ${c.clock_mismatches} 次，錄製帳本 ${c.recorded_final_match?'一致':'未確認'}，持久帳本 ${c.persisted_live_match===true?'一致':c.persisted_live_match===false?'不一致':'尚無資料'}`:'';
      return `<li class="mt-2">${esc(day.day)}｜${esc(status+proof)}</li>`;
    }).join('')+'</ul><p class="mt-3">列出最近20個資料日期；完整報告保存於 VM。沒有完整資料的日子不計零損益；仍未平倉的日期也不計完整日績效。</p></details>';
    return html;
  }
  if(typeof module!=='undefined'&&module.exports) module.exports={render};
  if(!global.document)return;
  let busy=false;
  async function refresh(){
    const box=global.document.getElementById('bReplayRows'),stamp=global.document.getElementById('bReplayStatus');
    if(!box||!stamp||busy)return;
    busy=true;
    try{
      const root=typeof FIREBASE_ROOT!=='undefined'?FIREBASE_ROOT:null;
      if(!root)throw new Error('source');
      const response=await fetch(`${root}/public_feed/b_lanes_replay.json`,{cache:'no-store'});
      if(!response.ok)throw new Error('source');
      const data=await response.json();
      if(data?.schema!=='b-lanes-replay-v1')throw new Error('schema');
      const days=Object.values(data.summary||{}).reduce((n,x)=>n+(x.valid_days||0),0);
      const age=Date.now()-Date.parse(data.generated_at);
      stamp.textContent=`${days?'已有可核對的回放紀錄':'目前沒有完整資料可產生有效新版回測'}。範圍 ${data.since}～${data.until}；更新 ${data.generated_at}${!Number.isFinite(age)||age>36*3600000?'（更新已延遲）':''}`;
      box.innerHTML=render(data);
    }catch(_){stamp.textContent='回放報告暫時無法取得，待資料盤點完成後更新。';}
    finally{busy=false;}
  }
  refresh();global.setInterval(refresh,10*60000);
})(typeof window!=='undefined'?window:globalThis);
