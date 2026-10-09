/* Home layout only. Learning/data modules do not own other dashboard sections. */
(() => {
  const get=id=>document.getElementById(id);
  if(get('simpleHomeStyle'))return;
  const overnight=get('overnightModule');
  if(overnight){const wrapper=overnight.closest('.recommendation-section');(wrapper||overnight).remove();}
  get('overnight-strategies')?.remove();
  document.querySelectorAll('.section-nav a[href="#overnight-strategies"]').forEach(n=>n.remove());

  const style=document.createElement('style');style.id='simpleHomeStyle';
  style.textContent=`
  #shortTermModule{min-width:0;padding:20px;margin:22px 0 30px;height:auto}
  #shortTermModule .share-btn{font-size:11px;white-space:nowrap}
  #shortTermModule .short-module-head{flex-wrap:wrap;gap:8px}
  #short-term{display:block;scroll-margin-top:90px}
  #learningSection [role=status]:empty{display:none}
  @media(max-width:480px){#shortTermModule{padding:16px}}
  `;
  document.head.append(style);
})();
