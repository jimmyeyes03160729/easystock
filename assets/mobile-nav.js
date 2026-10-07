(() => {
  const nav=document.querySelector('.mobile-bottom-nav');
  if(!nav) return;
  const links=[...nav.querySelectorAll('a[href^="#"]')];
  const select=href=>links.forEach(link=>{
    if(link.getAttribute('href')===href) link.setAttribute('aria-current','location');
    else link.removeAttribute('aria-current');
  });
  nav.addEventListener('click',event=>{const link=event.target.closest('a');if(links.includes(link))select(link.getAttribute('href'));});
  window.addEventListener('hashchange',()=>select(location.hash || '#intraday-strategies'));
  let queued=false;
  window.addEventListener('scroll',()=>{
    if(queued) return; queued=true;
    requestAnimationFrame(()=>{
      queued=false;
      const candidates=links.map(link=>({link,node:document.querySelector(link.getAttribute('href'))})).filter(x=>x.node);
      const passed=candidates.filter(x=>x.node.getBoundingClientRect().top<=130);
      passed.sort((a,b)=>b.node.getBoundingClientRect().top-a.node.getBoundingClientRect().top);
      if(passed.length)select(passed[0].link.getAttribute('href'));
    });
  },{passive:true});
  select(location.hash || '#intraday-strategies');
})();
