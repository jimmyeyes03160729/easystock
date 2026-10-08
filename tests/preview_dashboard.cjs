// Local-only visual QA with synthetic data. Never forwards a data fetch to Firebase.
// node tests/preview_dashboard.cjs, then http://127.0.0.1:8766
const http=require('node:http'),fs=require('node:fs'),path=require('node:path');
const root=path.resolve(__dirname,'..');
const fixture=`<script>
window.fetch=async url=>{
 const today=new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Taipei'}).format(new Date());
 const meta={release_id:'SYNTHETIC',rule_version:'2.0.0',updated_at:today,published_at:new Date().toISOString()};
 const stocks=Object.fromEntries([['TEST1','合成科技',40],['TEST2','合成金融',100]].map(([symbol,name,price])=>[symbol,{symbol,name,price,updated_at:today,release_id:'SYNTHETIC'}]));
 const u=String(url);let data=null;
 if(u.endsWith('/active_release.json'))data='SYNTHETIC';
 else if(u.endsWith('/meta.json'))data=meta;
 else if(u.endsWith('/summary.json'))data=stocks;
 else if(u.endsWith('/intraday_live.json'))data={last_update_at:new Date().toISOString(),session:'daytrade',config:{entry_mode:'rules'},market_risk:{checked_at:new Date().toISOString(),gate_action:'BLOCK',gate_reason:'market_risk_red'}};
 return {ok:true,json:async()=>data};
};
</script>`;
http.createServer((req,res)=>{
 const url=new URL(req.url,'http://127.0.0.1:8766');
 if(url.pathname==='/' || url.pathname==='/index.html') {
   let html=fs.readFileSync(path.join(root,'index.html'),'utf8').replace('<head>','<head>'+fixture);
   // An isolated 360px viewport fixture; it contains the same page and CSS.
   if(url.searchParams.has('narrow')) html='<!DOCTYPE html><style>body{margin:0;background:#ddd}iframe{display:block;width:360px;height:900px;border:0;margin:auto}</style><iframe title="360px synthetic preview" src="/index.html"></iframe>';
   res.setHeader('Content-Type','text/html; charset=utf-8');res.end(html);return;
 }
 const relative=url.pathname.slice(1),file=path.resolve(root,relative);
 if(!/^(assets|icon)\//.test(relative)||!file.startsWith(root+path.sep)||!fs.existsSync(file)||!fs.statSync(file).isFile()){res.writeHead(404);res.end();return;}
 const types={'.js':'text/javascript','.css':'text/css','.png':'image/png','.svg':'image/svg+xml'};
 res.setHeader('Content-Type',types[path.extname(file)]||'application/octet-stream');fs.createReadStream(file).pipe(res);
}).listen(8766,'127.0.0.1',()=>console.log('Synthetic UI preview: http://127.0.0.1:8766 (360px: /?narrow)'));
