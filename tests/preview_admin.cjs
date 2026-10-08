// Loopback-only synthetic visual fixture; no authentication or production API.
// node tests/preview_admin.cjs then /?panel=market or /?panel=manual
const http=require('node:http'),fs=require('node:fs'),path=require('node:path');
const {JSDOM}=require('jsdom'),marketFixture=require('./admin_market_fixture.cjs');
const root=path.resolve(__dirname,'..'),assets=path.join(root,'easystock_admin/static');
http.createServer((req,res)=>{
  const url=new URL(req.url,'http://127.0.0.1:8767');
  if(url.pathname==='/'){
    const dom=new JSDOM(fs.readFileSync(path.join(assets,'index.html'),'utf8')),d=dom.window.document;
    d.querySelectorAll('script').forEach(n=>n.remove());
    d.documentElement.dataset.theme=url.searchParams.get('theme')==='light'?'light':'dark';
    d.getElementById('login').hidden=true;d.getElementById('workspace').hidden=false;
    d.querySelector('.title').hidden=true;d.querySelector('.identity').hidden=true;
    const manual=url.searchParams.get('panel')==='manual';
    d.querySelectorAll('.admin-tab-panel').forEach(n=>{n.hidden=n.id!==(manual?'manualOrderPanel':'healthPanel');});
    const health=d.getElementById('healthPanel'),title=d.getElementById('marketContextTitle');
    [...health.children].forEach(n=>{n.hidden=![title,title.nextElementSibling,d.getElementById('marketContext')].includes(n);});
    const order=d.getElementById('manualOrderPanel'),conditions=d.querySelector('.order-entry-fields').parentElement;
    [...order.children].forEach(n=>{n.hidden=n!==conditions;});
    d.querySelectorAll('button').forEach(n=>{n.disabled=true;});
    d.querySelectorAll('a').forEach(n=>n.removeAttribute('href'));
    const banner=d.createElement('p');banner.className='hint';banner.textContent='合成資料預覽 · 不登入、不連券商、不送單';d.querySelector('main').prepend(banner);
    const nav=d.querySelector('.admin-section-nav');nav.hidden=true;
    const fixture=d.createElement('script');fixture.textContent=`
      window.api=async(path,options)=>{if(path!=='api/market-context'||options)throw Error('Preview denies API calls');return ${JSON.stringify(marketFixture())};};
      document.addEventListener('DOMContentLoaded',()=>window.loadMarketContext());
    `;d.head.append(fixture);
    const script=d.createElement('script');script.src='/admin/assets/live-console.js';script.defer=true;d.head.append(script);
    res.setHeader('Content-Type','text/html; charset=utf-8');res.end(dom.serialize());dom.window.close();return;
  }
  const filename=url.pathname.slice('/admin/assets/'.length);
  if(!url.pathname.startsWith('/admin/assets/')||!['admin.css','live-console.js'].includes(filename)){res.writeHead(404);res.end();return;}
  res.setHeader('Content-Type',filename.endsWith('.css')?'text/css':'text/javascript');fs.createReadStream(path.join(assets,filename)).pipe(res);
}).listen(8767,'127.0.0.1',()=>console.log('Synthetic Admin UI: http://127.0.0.1:8767/?panel=market (or manual; theme=light)'));
