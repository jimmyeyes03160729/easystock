/* Home layout only. Learning/data modules do not own other dashboard sections. */
(() => {
  const get=id=>document.getElementById(id);
  if(get('simpleHomeStyle'))return;
  const overnight=get('overnightModule');
  if(overnight){const wrapper=overnight.closest('.recommendation-section');(wrapper||overnight).remove();}
  get('overnight-strategies')?.remove();
  document.querySelectorAll('.section-nav a[href="#overnight-strategies"]').forEach(n=>n.remove());

  const rebound=get('reboundModule');
  if(rebound){
    const layout=document.createElement('section');layout.id='reboundLayout';layout.setAttribute('aria-label','底部反彈');
    rebound.before(layout);layout.append(rebound);
    get('bottom-rebound')?.remove();
    const anchor=document.createElement('span');anchor.id='bottom-rebound';rebound.prepend(anchor);
    const title=get('reboundTitle');if(title)title.textContent='底部反彈 TOP 3';
    const watch=get('reboundWatchSection');
    if(watch){
      const details=document.createElement('details'),summary=document.createElement('summary');
      summary.textContent='展開技術觀察名單（非推薦）';details.append(summary);
      while(watch.firstChild)details.append(watch.firstChild);
      watch.append(details);
    }
    const nav=document.querySelector('.section-nav a[href="#bottom-rebound"]');
    if(nav)nav.textContent='02 底部反彈';
  }

  const root=get('learningSection');if(!root)return;
  function disclosure(parent,label){
    const details=document.createElement('details'),summary=document.createElement('summary');
    details.className='compact-details';summary.textContent=label;details.append(summary);parent.append(details);return details;
  }
  function move(ids,parent){for(const id of ids){const n=get(id);if(n)parent.append(n);}}
  root.querySelector('.learning-head .eyebrow')?.remove();
  for(const [index,column] of [...root.querySelectorAll('.learning-column')].entries()){
    column.querySelector('.learning-column-head p')?.remove();
    const oldExplanation=column.querySelector(':scope > details');
    const detail=disclosure(column,'詳細數據與說明');
    const numbers=column.querySelector('.learning-numbers');
    const extra=document.createElement('div');extra.className='compact-extra-stats';
    const cells=numbers?[...numbers.children]:[];
    // Keep dates + stocks on the left; processed stock-days + dates on the right.
    cells.slice(2).forEach(n=>extra.append(n));detail.append(extra);
    cells.slice(0,2).forEach(n=>n.querySelectorAll('small').forEach(s=>detail.append(s)));
    const bottom=column.querySelector('.learning-bottom');
    if(index===0){
      move(['learnAI','learnUpdated','learnLastReport'],detail);
      move(['learnError'],column);
    }else{
      const results=column.querySelector('.learning-results');if(results)detail.append(results);
      move(['historyDownload','historyRunNote'],detail);
      move(['historyError'],column);
    }
    if(oldExplanation){
      const text=document.createElement('div');
      [...oldExplanation.children].filter(n=>n.tagName!=='SUMMARY').forEach(n=>text.append(n));
      detail.append(text);oldExplanation.remove();
    }
    if(bottom)[...bottom.children].filter(n=>!n.children.length&&!n.textContent.trim()).forEach(n=>n.remove());
  }
  const dual=get('dualReview');
  if(dual){
    dual.querySelector('.eyebrow')?.remove();
    const detail=disclosure(dual,'展開 OpenAI 每日復盤分析');
    move(['dualFacts'],detail);
    const cards=dual.querySelector('.dual-grid'),compare=dual.querySelector('.dual-compare');
    if(cards)detail.append(cards);if(compare)detail.append(compare);
    move(['dualNotice'],detail);
    const note=document.createElement('p');note.className='compact-review-note';note.textContent='復盤完成不等於模型已套用；同步狀態請看上方。';
    detail.before(note);
  }
  const style=document.createElement('style');style.id='simpleHomeStyle';
  style.textContent=`
  #reboundLayout{display:grid;grid-template-columns:minmax(0,1fr);gap:18px;align-items:start;margin:22px 0 30px}
  #reboundLayout>.panel{min-width:0;padding:20px;margin:0;height:auto;align-self:start}
  #reboundLayout h2{font-size:18px;line-height:1.6}
  #reboundLayout .rebound-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}
  #reboundLayout .share-btn{font-size:11px;white-space:nowrap}
  #reboundLayout .rebound-module-head{flex-wrap:wrap;gap:8px}
  #reboundLayout .rebound-card{padding:12px 14px}
  #reboundLayout .rebound-card h3{margin:7px 0 4px;font-size:16px}
  #reboundLayout .rebound-price{font-size:21px}
  #reboundLayout .rebound-quote{display:flex;justify-content:space-between;align-items:baseline;gap:12px;margin:6px 0}
  #reboundLayout .rebound-quote h3{min-width:0;overflow-wrap:anywhere;margin:0}
  #reboundLayout .rebound-quote .rebound-price{white-space:nowrap;flex-shrink:0}
  #reboundLayout .rebound-card>.btn{padding:4px 8px;font-size:11px;min-height:0}
  #reboundLayout .rebound-card p{margin:5px 0;line-height:1.5}
  #reboundLayout .rebound-card details{margin:7px 0}
  #reboundLayout .rebound-warning,#reboundLayout .rebound-pass{padding:5px 7px}
  #reboundLayout #reboundWatchSection{margin-top:12px;font-size:12px}
  #reboundLayout #reboundWatchSection>details>h3{display:none}
  #bottom-rebound{display:block;scroll-margin-top:90px}
  #learningSection{padding:18px 22px}
  #learningSection .learning-head{margin-bottom:12px}
  #learningSection .learning-head h2{font-size:22px;margin:0}
  #learningSection .learning-column{padding:14px 18px 0 0}
  #learningSection .learning-column+.learning-column{padding:14px 0 0 18px}
  #learningSection .learning-column-head{margin-bottom:10px;align-items:center}
  #learningSection .learning-column h3{font-size:16px;margin:0}
  #learningSection .phase-badge{padding:5px 9px;font-size:11px;line-height:1.5}
  #learningSection .learning-numbers>div{padding:10px;border-bottom:0}
  #learningSection .learning-numbers strong{font-size:26px;line-height:1.4;margin:3px 0}
  #learningSection .learning-numbers span{font-size:12px}
  #learningSection .learning-bottom{padding-top:10px;gap:0}
  #learningSection .learning-bottom b{font-size:12px}
  #learningSection .learning-bottom p{font-size:12px;margin:4px 0}
  #learningSection progress{height:5px;margin:8px 0}
  #learningSection .compact-details{margin-top:10px;padding-top:9px;font-size:12px}
  #learningSection summary{cursor:pointer;color:var(--main);line-height:1.8}
  #learningSection summary:focus-visible{outline:2px solid var(--main);outline-offset:3px}
  #learningSection .compact-extra-stats{display:grid;grid-template-columns:1fr 1fr;gap:12px;padding:10px 0}
  #learningSection .compact-extra-stats span,#learningSection .compact-extra-stats small{display:block;color:var(--sub);font-size:12px}
  #learningSection .compact-extra-stats strong{display:block;font-size:20px}
  #learningSection .compact-details>small{display:block;color:var(--sub);line-height:1.7}
  #learningSection #dualReview{margin-top:14px;padding-top:12px;border-top:1px solid var(--border)}
  #learningSection #dualReview h3{font-size:16px;margin:0}
  #learningSection #dualReview .dual-head{align-items:center}
  #learningSection #dualDate{font-size:11px;margin:3px 0}
  #learningSection #dualReview .compact-review-note{font-size:11px;margin:4px 0}
  #learningSection [role=status]:empty{display:none}
  @media(max-width:900px){
    #reboundLayout{grid-template-columns:1fr}
    #reboundLayout .rebound-grid{grid-template-columns:1fr}
    #learningSection .learning-column{padding:12px 0}
    #learningSection .learning-column+.learning-column{padding:12px 0 0}
    #learningSection #dualReview .dual-head{flex-direction:row;flex-wrap:wrap;gap:8px}
  }
  @media(max-width:480px){#learningSection{padding:16px}#reboundLayout>.panel{padding:16px}}
  `;
  document.head.append(style);
})();
