/* Reuse the live snapshot; watchlist entries are never presented as fills. */
(function(global) {
  const escape = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const day = now => new Date(now).toLocaleDateString('en-CA', {timeZone:'Asia/Taipei'});
  function view(live, health, now=Date.now()) {
    const feed=live?.a_candidates;
    if (!health?.current) return {message:health?.message || '等待當日有效行情', rows:[]};
    const age=now-Date.parse(feed?.updated_at);
    if (!feed || feed.schema_version!==1 || feed.kind!=='watchlist' || feed.day!==day(now) || !Number.isFinite(age) || age<0 || age>90000)
      return {message:'等待當日候選更新；無候選不等於沒有市場機會。',rows:[]};
    const rows=(Array.isArray(feed.rows)?feed.rows:[]).filter(r=>{
      const q=now-Date.parse(r.quote_at);
      return r.execution==='not_filled' && Number.isFinite(q) && q>=0 && q<=30000;
    }).slice(0,5);
    return {message:'A 候選觀察｜候選尚未成交，進場仍須通過風控與模擬帳檢查。',rows};
  }
  function cards(result) {
    return `<p class="text-xs text-[#94A3B8]">${escape(result.message)}</p>`+result.rows.map(r=>{
      const score=Number.isFinite(r.model_score)?`模型分數 ${r.model_score.toFixed(3)}（非已驗證勝率）`:'模型分數待資料';
      const state=r.state==='rule_ready'?'規則條件已齊，等待成交確認':`觀察中：${(r.waits||[]).join('、')}`;
      return `<article class="rounded-lg border border-cyan-500/30 p-3 text-xs"><div>${escape(r.symbol)} ${escape(r.name)} · ${escape(r.price)} · 規則 ${escape(r.rule_score)} 分</div><div class="text-[#94A3B8] mt-1">${escape(score)}</div><div class="mt-1">${escape((r.reasons||[]).join('、'))}</div><div class="text-[#F59E0B] mt-1">${escape(state)}${r.opening_recovery?' · 開低轉強型態':''}</div></article>`;
    }).join('');
  }
  const api={view,cards,render(live,health){
    const el=global.document?.getElementById('aCandidateList');if(el)el.innerHTML=cards(view(live,health));
    const disclosure=global.document?.getElementById('aPolicyDisclosure');
    if(disclosure) disclosure.textContent='候選為觀察結果，非成交；以實際模擬帳本狀態為準。';
  }};
  if (typeof module!=='undefined' && module.exports) module.exports=api;
  global.AWatchlist=api;
})(typeof window!=='undefined'?window:globalThis);
