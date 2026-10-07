'use strict';
(() => {
  const root=document.getElementById('guardianPanel'),nav=document.querySelector('.admin-section-nav');
  if(!root||!nav)return;
  const tab=document.createElement('button');tab.type='button';tab.dataset.adminTab='guardianPanel';tab.textContent='AI 系統健檢';
  tab.addEventListener('click',()=>showAdminTab('guardianPanel'));nav.append(tab);
  const byId=id=>document.getElementById(id);
  let generation=0;
  function reset(){generation++;byId('guardianStatus').textContent='UNKNOWN · 尚未讀取私人報告';for(const id of ['guardianCounts','guardianCommit','guardianReview'])byId(id).textContent='';byId('guardianFindings').replaceChildren();byId('guardianResolved').replaceChildren();}
  function renderCards(id,rows){
    const target=byId(id);target.replaceChildren();
    if(!rows?.length){target.textContent='沒有已記錄項目；UNKNOWN 不代表安全。';return;}
    for(const row of rows){
      const card=document.createElement('article');card.className='health-card';
      const title=document.createElement('h3');title.textContent=`${row.severity} · ${row.title}`;card.append(title);
      for(const value of [`影響：${row.impact}`,`建議：${row.recommendation}`,row.blocks_live_auto?'GUARDIAN BLOCKING CONDITION（僅提示，不改 LIVE AUTO）':'僅供審查',`首次：${row.first_seen} · 最近：${row.last_seen}`]){const p=document.createElement('p');p.textContent=value;card.append(p);}
      for(const e of row.evidence||[]){const p=document.createElement('p');p.textContent=`${e.path}:${e.line} · ${e.detail}`;card.append(p);}
      if(row.resolved_at){const p=document.createElement('p');p.textContent='已解決：'+row.resolved_at;card.append(p);}
      target.append(card);
    }
  }
  window.loadGuardian=async()=>{
    if(byId('workspace').hidden)return;
    const request=++generation;
    try{
      const data=await api('api/guardian');
      if(request!==generation||byId('workspace').hidden)return;
      byId('guardianStatus').textContent=`${data.overall_status} · ${data.report_status} · 最後檢查 ${data.generated_at||'未知'}`;
      byId('guardianCounts').textContent=['critical','high','medium','low'].map(k=>`${k.toUpperCase()} ${data.counts?.[k]??0}`).join(' / ');
      byId('guardianCommit').textContent='最近 commit：'+(data.commit||'未知');
      byId('guardianReview').textContent=(data.review_required?'需要架構審查：':'最近報告的高風險變更：')+(data.changed_critical_files||[]).join('、');
      renderCards('guardianFindings',data.findings);renderCards('guardianResolved',data.resolved_findings);
    }catch(e){if(request!==generation)return;reset();byId('guardianStatus').textContent='UNKNOWN · 無法讀取私人報告';}
  };
  byId('guardianRefresh').addEventListener('click',window.loadGuardian);
  document.addEventListener('easystock:owner-ready',window.loadGuardian);
  document.addEventListener('easystock:owner-ended',reset);
  byId('logout').addEventListener('click',reset);
})();
