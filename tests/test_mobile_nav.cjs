const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs');
const {createDOM}=require('./dom.cjs');
test('Chrome install CTA reuses the extension manifest logo at a fixed undistorted size',()=>{
  const {w}=createDOM(fs.readFileSync('index.html','utf8'));
  const manifest=JSON.parse(fs.readFileSync('chrome-extension/manifest.json','utf8'));
  const logo=w.document.querySelector('#chrome-tools .extension-cta .extension-icon img');
  assert.equal(logo.getAttribute('src'),'chrome-extension/'+manifest.icons['128']);
  assert.equal(manifest.action.default_icon['128'],manifest.icons['128']);
  assert(fs.existsSync(logo.getAttribute('src')));
  assert.equal(logo.width,32);assert.equal(logo.height,32);assert.equal(logo.alt,'');
  assert.equal(logo.parentElement.getAttribute('aria-hidden'),'true');
  assert.match(fs.readFileSync('index.html','utf8'),/\.extension-cta \.extension-icon img\s*\{[^}]*object-fit:contain/);
  w.close();
});
test('M1-M7: real anchors, five labels, desktop/mobile safe-area, active and guarded admin route',()=>{
  const html=fs.readFileSync('index.html','utf8'),{w,run}=createDOM(html);
  const nav=w.document.querySelector('.mobile-bottom-nav'),links=[...nav.querySelectorAll('a')];
  assert.equal(links.length,5);
  assert.deepEqual(links.map(a=>a.getAttribute('aria-label')),['盤中摸魚','底部反彈','牛馬 AI','小工具','社畜後台']);
  assert.match(html,/\.mobile-bottom-nav\s*\{ display:none;/);
  assert.match(html,/@media\(max-width:768px\)/);
  assert.match(html,/body\s*\{ padding-bottom:calc\(68px \+ env\(safe-area-inset-bottom/);
  assert.match(html,/grid-template-columns:repeat\(5,minmax\(0,1fr\)\)/);
  assert.match(html,/:focus-visible/);
  for(const a of links.slice(0,4))assert(w.document.querySelector(a.getAttribute('href')));
  assert(w.document.querySelector('#chrome-tools .extension-cta[href^="https://chromewebstore.google.com/"]'));
  assert.equal(links[4].pathname,'/admin');assert(!links[4].search);
  assert.equal(w.document.querySelectorAll('.section-nav.hidden.lg\\:flex').length,1);
  const ids=[...w.document.querySelectorAll('[id]')].map(n=>n.id);assert.equal(new Set(ids).size,ids.length);
  run('assets/mobile-nav.js');links[1].dispatchEvent(new w.MouseEvent('click',{bubbles:true,cancelable:true}));
  assert.equal(links[1].getAttribute('aria-current'),'location');assert(!links[0].hasAttribute('aria-current'));
  w.location.hash='#learningSection';w.dispatchEvent(new w.Event('hashchange'));assert.equal(links[2].getAttribute('aria-current'),'location');
  w.close();
});

// Control animation frames and time so intermediate scroll positions cannot be skipped.
function navigationFixture(t,{productionLayout=false}={}){
  const {w,run}=createDOM(fs.readFileSync('index.html','utf8'));
  t.after(()=>w.close());
  const nav=w.document.querySelector('.mobile-bottom-nav');
  const links=[...nav.querySelectorAll('a[href^="#"]')];
  const positions={'#intraday-strategies':100,'#bottom-rebound':900,'#learningSection':1700,'#chrome-tools':-2000};
  for(const [href,top] of Object.entries(positions))w.document.querySelector(href).getBoundingClientRect=()=>({top:positions[href]});
  w.document.querySelector('header.fixed').getBoundingClientRect=()=>({bottom:64});
  Object.defineProperty(w.document.documentElement,'scrollHeight',{value:10000});
  w.innerHeight=600;w.scrollY=1000;
  let now=0,nextTimer=0,frames=[];
  const timers=new Map();
  w.setTimeout=(callback,delay)=>{const id=++nextTimer;timers.set(id,{callback,at:now+delay});return id;};
  w.clearTimeout=id=>timers.delete(id);
  w.requestAnimationFrame=callback=>frames.push(callback);
  const flush=()=>{const pending=frames;frames=[];pending.forEach(callback=>callback(now));};
  const advance=ms=>{
    const end=now+ms;
    while(true){
      const due=[...timers].filter(([,timer])=>timer.at<=end).sort((a,b)=>a[1].at-b[1].at)[0];
      if(!due)break;
      now=due[1].at;timers.delete(due[0]);due[1].callback();
    }
    now=end;
  };
  // jsdom has no native scrolling. Preserve normal click handling, then model its hash change.
  w.document.addEventListener('click',event=>event.preventDefault());
  const click=href=>{
    links.find(link=>link.getAttribute('href')===href).querySelector('span').dispatchEvent(new w.MouseEvent('click',{bubbles:true,cancelable:true}));
    w.history.replaceState(null,'',href);
    w.dispatchEvent(new w.Event('hashchange'));
  };
  const scroll=values=>{Object.assign(positions,values);w.dispatchEvent(new w.Event('scroll'));flush();};
  const active=href=>{
    assert.deepEqual(links.filter(link=>link.hasAttribute('aria-current')).map(link=>link.getAttribute('href')),[href]);
    assert.equal(links.find(link=>link.getAttribute('href')===href).getAttribute('aria-current'),'location');
  };
  const scrollend=()=>w.dispatchEvent(new w.Event('scrollend'));
  if(productionLayout)run('assets/dashboard-layout.js');
  run('assets/mobile-nav.js');advance(200);
  return {w,click,scroll,active,advance,scrollend,flush};
}

test('CASE 1-2: rebound stays selected while smooth scrolling past intraday',t=>{
  const f=navigationFixture(t);
  f.click('#bottom-rebound');f.active('#bottom-rebound');
  f.scroll({'#intraday-strategies':80,'#bottom-rebound':600});
  f.active('#bottom-rebound');assert.equal(f.w.location.hash,'#bottom-rebound');
});

test('CASE 3-7: AI stays selected through the entire path; scrollend restores manual spy',t=>{
  const f=navigationFixture(t);
  f.click('#learningSection');f.active('#learningSection');
  for(const positions of [
    {'#intraday-strategies':80,'#bottom-rebound':700,'#learningSection':1400},
    {'#intraday-strategies':-600,'#bottom-rebound':100,'#learningSection':800},
    {'#intraday-strategies':-1300,'#bottom-rebound':-600,'#learningSection':100}
  ]){
    f.scroll(positions);f.advance(120);f.active('#learningSection');
  }
  assert.equal(f.w.location.hash,'#learningSection');
  f.scrollend();f.active('#learningSection');
  f.scroll({'#bottom-rebound':100,'#learningSection':800});f.active('#bottom-rebound');
  f.scroll({'#intraday-strategies':100,'#bottom-rebound':800});f.active('#intraday-strategies');
});

test('fallback waits for scroll inactivity even when animation takes longer than 300ms',t=>{
  const f=navigationFixture(t);
  f.click('#learningSection');
  for(let step=0;step<10;step++){
    f.scroll({'#intraday-strategies':-600,'#bottom-rebound':100,'#learningSection':800});
    f.advance(120);f.active('#learningSection');
  }
  f.scroll({'#bottom-rebound':-600,'#learningSection':100});
  f.advance(200);f.active('#learningSection');
  f.scroll({'#bottom-rebound':100,'#learningSection':800});f.active('#bottom-rebound');
  f.scroll({'#intraday-strategies':100,'#bottom-rebound':800});f.active('#intraday-strategies');
});

test('CASE 8: hashchange locks AI through intermediate positions and settles on AI',t=>{
  const f=navigationFixture(t);
  f.w.history.replaceState(null,'','#learningSection');f.w.dispatchEvent(new f.w.Event('hashchange'));
  f.active('#learningSection');
  f.scroll({'#intraday-strategies':-600,'#bottom-rebound':100,'#learningSection':800});f.active('#learningSection');
  f.scroll({'#bottom-rebound':-600,'#learningSection':100});f.scrollend();f.active('#learningSection');
  assert.equal(f.w.location.hash,'#learningSection');
});

test('rapid clicks ignore the cancelled previous scrollend and keep the latest destination',t=>{
  const f=navigationFixture(t);
  f.click('#bottom-rebound');
  f.scroll({'#intraday-strategies':-600,'#bottom-rebound':100,'#learningSection':800});
  f.click('#learningSection');f.scrollend();
  f.scroll({});f.active('#learningSection');
  f.scroll({'#bottom-rebound':-600,'#learningSection':100});f.scrollend();f.active('#learningSection');
});

test('intraday click stays selected while scrolling upwards through rebound',t=>{
  const f=navigationFixture(t);
  f.click('#intraday-strategies');f.active('#intraday-strategies');
  f.scroll({'#intraday-strategies':-600,'#bottom-rebound':100,'#learningSection':800});f.active('#intraday-strategies');
  f.scroll({'#intraday-strategies':100,'#bottom-rebound':800,'#learningSection':1500});
  f.scrollend();f.active('#intraday-strategies');
});

test('already-visible anchors and bottom-clamped destinations release the lock',t=>{
  const f=navigationFixture(t);
  f.click('#intraday-strategies');f.advance(200);
  f.scroll({'#intraday-strategies':-600,'#bottom-rebound':100});f.active('#bottom-rebound');
  f.click('#learningSection');f.w.scrollY=9400;
  f.scroll({'#bottom-rebound':-300,'#learningSection':400});f.scrollend();f.active('#learningSection');
  f.scroll({'#bottom-rebound':100,'#learningSection':800});f.active('#bottom-rebound');
});

test('touch, wheel and keyboard scrolling can interrupt a navigation lock',t=>{
  const f=navigationFixture(t);
  for(const event of [new f.w.Event('touchmove',{bubbles:true}),new f.w.Event('wheel',{bubbles:true}),new f.w.KeyboardEvent('keydown',{key:'PageUp',bubbles:true})]){
    f.click('#learningSection');f.scroll({'#intraday-strategies':-600,'#bottom-rebound':100,'#learningSection':800});
    f.w.document.body.dispatchEvent(event);f.flush();f.active('#bottom-rebound');
  }
});

test('manual spy follows the actual scroll padding and fixed header active line',t=>{
  const f=navigationFixture(t);
  f.w.document.documentElement.style.scrollPaddingTop='160px';
  f.scroll({'#intraday-strategies':-600,'#bottom-rebound':180,'#learningSection':800});f.active('#bottom-rebound');
  f.w.document.documentElement.style.scrollPaddingTop='40px';
  f.scroll({'#intraday-strategies':-600,'#bottom-rebound':85});f.active('#intraday-strategies');
  f.scroll({'#bottom-rebound':84});f.active('#bottom-rebound');
});

test('production rebound scroll-margin remains selected when a queued spy runs after scrollend',t=>{
  const f=navigationFixture(t,{productionLayout:true});
  assert.equal(f.w.getComputedStyle(f.w.document.querySelector('#bottom-rebound')).scrollMarginTop,'90px');
  f.click('#bottom-rebound');
  // Native anchor alignment adds html scroll-padding (100) and section scroll-margin (90).
  f.scroll({'#intraday-strategies':-600,'#bottom-rebound':190,'#learningSection':800});
  f.w.dispatchEvent(new f.w.Event('scroll')); // Spy still pending at scrollend.
  f.scrollend();f.flush();f.active('#bottom-rebound');
  f.scroll({'#bottom-rebound':189});f.active('#bottom-rebound');
  assert.equal(f.w.location.hash,'#bottom-rebound');
});

test('production rebound scroll-margin is included in fallback settle and manual spy boundaries',t=>{
  const f=navigationFixture(t,{productionLayout:true});
  f.click('#bottom-rebound');
  f.scroll({'#intraday-strategies':-600,'#bottom-rebound':190,'#learningSection':800});
  f.advance(200);f.scroll({});f.active('#bottom-rebound');
  f.scroll({'#bottom-rebound':211});f.active('#intraday-strategies');
  f.scroll({'#bottom-rebound':210});f.active('#bottom-rebound');
  f.scroll({'#bottom-rebound':-600,'#learningSection':100});f.active('#learningSection');
});

test('CASE 9-10: banner uses scoped responsive CSS, its original ratio and desktop dimensions',t=>{
  const html=fs.readFileSync('index.html','utf8'),{w}=createDOM(html);
  t.after(()=>w.close());
  const logo=w.document.querySelector('header.fixed .brand-link .brand-logo');
  assert(logo);assert.match(logo.getAttribute('src'),/BANNER-376\.png/);
  assert.equal(logo.width,188);assert.equal(logo.height,62);
  assert(logo.classList.contains('w-[188px]'));assert(logo.classList.contains('h-[62px]'));
  assert(!html.includes('header.fixed a[aria-label] img'));
  const mobileRules=[...w.document.styleSheets].flatMap(sheet=>[...sheet.cssRules])
    .filter(rule=>rule.conditionText==='(max-width:768px)').flatMap(rule=>[...rule.cssRules]);
  const logoRule=mobileRules.find(rule=>rule.selectorText==='header.fixed .brand-logo');
  assert(logoRule);assert.equal(logoRule.style.height,'auto');
  assert.equal(logoRule.style.width,'clamp(128px,42vw,188px)');assert.equal(logoRule.style.getPropertyValue('max-width'),'100%');
  assert.equal(logoRule.style.getPropertyValue('border-radius'),'');
  const brandRule=mobileRules.find(rule=>rule.selectorText==='header.fixed .brand-link');
  assert.equal(brandRule.style.width,'auto');assert.equal(brandRule.style.getPropertyValue('min-width'),'0');
  const png=fs.readFileSync('icon/BANNER-376.png');
  // The PNG's intrinsic ratio is authoritative on mobile; desktop keeps its 188x62 box.
  assert(png.readUInt32BE(16)>png.readUInt32BE(20));
});
