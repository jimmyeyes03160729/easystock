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
    const title=get('reboundTitle');if(title)title.textContent='底部反彈觀察標的 · 有支撐，也要等站穩';
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

  const style=document.createElement('style');style.id='simpleHomeStyle';
  style.textContent=`
  #reboundLayout{display:grid;grid-template-columns:minmax(0,1fr);gap:18px;align-items:start;margin:22px 0 30px}
  #reboundLayout>.panel{min-width:0;padding:20px;margin:0;height:auto;align-self:start}
  #reboundLayout h2{font-size:14px;font-weight:700;line-height:1.5;margin:0}
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
  #learningSection [role=status]:empty{display:none}
  @media(max-width:900px){
    #reboundLayout{grid-template-columns:1fr}
    #reboundLayout .rebound-grid{grid-template-columns:1fr}
  }
  @media(max-width:480px){#reboundLayout>.panel{padding:16px}}
  `;
  document.head.append(style);
})();
