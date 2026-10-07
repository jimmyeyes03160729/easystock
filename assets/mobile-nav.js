(() => {
  const nav=document.querySelector('.mobile-bottom-nav');
  if(!nav) return;
  const links=[...nav.querySelectorAll('a[href^="#"]')];
  const candidates=links.map(link=>({href:link.getAttribute('href'),node:document.querySelector(link.getAttribute('href'))})).filter(x=>x.node);
  const select=href=>links.forEach(link=>{
    if(link.getAttribute('href')===href) link.setAttribute('aria-current','location');
    else link.removeAttribute('aria-current');
  });
  const scrollPadding=()=>parseFloat(getComputedStyle(document.documentElement).scrollPaddingTop) || 0;
  let navigationTarget=null,settleTimer=null,queued=false;
  const finishNavigation=()=>{
    clearTimeout(settleTimer);
    // Keep the clicked destination selected; only a subsequent manual scroll runs the spy.
    navigationTarget=null;
  };
  const waitForIdle=()=>{
    clearTimeout(settleTimer);
    // This is a quiet period after the LAST scroll event, not a limit on animation duration.
    settleTimer=setTimeout(finishNavigation,180);
  };
  const navigate=href=>{
    if(!candidates.some(x=>x.href===href)) return;
    navigationTarget=href;
    select(href);
    waitForIdle(); // Also releases the lock when clicking an already-visible anchor.
  };
  const updateFromViewport=()=>{
    if(navigationTarget) return;
    const headerBottom=document.querySelector('header.fixed')?.getBoundingClientRect().bottom || 0;
    const activeLine=Math.max(scrollPadding(),headerBottom)+20;
    const passed=candidates.map(x=>({...x,top:x.node.getBoundingClientRect().top})).filter(x=>x.top<=activeLine);
    passed.sort((a,b)=>b.top-a.top);
    if(passed.length) select(passed[0].href);
    else if(candidates.length) select(candidates[0].href);
  };
  const queueSpy=()=>{
    if(queued) return;
    queued=true;
    requestAnimationFrame(()=>{
      queued=false;
      updateFromViewport();
    });
  };
  nav.addEventListener('click',event=>{
    const link=event.target.closest('a');
    if(!event.defaultPrevented && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey && links.includes(link)) navigate(link.getAttribute('href'));
  });
  window.addEventListener('hashchange',()=>navigate(location.hash || '#intraday-strategies'));
  window.addEventListener('scroll',()=>{
    if(navigationTarget) waitForIdle();
    queueSpy();
  },{passive:true});
  window.addEventListener('scrollend',()=>{
    if(!navigationTarget) return;
    const node=candidates.find(x=>x.href===navigationTarget).node;
    const margin=parseFloat(getComputedStyle(node).scrollMarginTop) || 0;
    const maxScroll=Math.max(0,document.documentElement.scrollHeight-window.innerHeight);
    const destination=Math.min(maxScroll,Math.max(0,window.scrollY+node.getBoundingClientRect().top-scrollPadding()-margin));
    // A cancelled previous scroll can emit scrollend after a new click. Ignore it en route.
    if(Math.abs(window.scrollY-destination)<=2) finishNavigation();
  });
  const interruptNavigation=()=>{
    if(!navigationTarget) return;
    finishNavigation();
    queueSpy();
  };
  window.addEventListener('wheel',interruptNavigation,{passive:true});
  window.addEventListener('touchmove',interruptNavigation,{passive:true});
  window.addEventListener('keydown',event=>{
    if(event.target.closest('input,textarea,select,[contenteditable="true"]')) return;
    if(['ArrowUp','ArrowDown','PageUp','PageDown','Home','End',' '].includes(event.key)) interruptNavigation();
  });
  navigate(location.hash || '#intraday-strategies');
})();
