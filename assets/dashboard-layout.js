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
  #eightMethodsModule{min-width:0;padding:20px;margin:22px 0 30px;height:auto}
  #eightMethodsModule .share-btn{font-size:11px;white-space:nowrap}
  #eightMethodsModule .eight-module-head{flex-wrap:wrap;gap:8px}
  #eight-methods{display:block;scroll-margin-top:90px}
  #learningSection [role=status]:empty{display:none}
  @media(max-width:480px){#eightMethodsModule{padding:16px}}
  `;
  document.head.append(style);
})();
