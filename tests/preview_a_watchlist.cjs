// Local synthetic visual QA. Every data fetch is mocked; no production writes.
const http=require('node:http'),fs=require('node:fs'),path=require('node:path');
const root=path.resolve(__dirname,'..');
const fixture=`<script>
window.fetch=async url=>{
 const at=new Date().toISOString(),today=new Date().toLocaleDateString('en-CA',{timeZone:'Asia/Taipei'});
 const meta={release_id:'SYNTHETIC',rule_version:'2.0.0',updated_at:today,published_at:at};
 const stocks={TEST:{symbol:'TEST',name:'合成轉強股票',price:101,updated_at:today,release_id:'SYNTHETIC'}};
 const live={scan_date:today,last_update_at:at,generated_at:at,session:'daytrade',config:{entry_mode:'rules'},
 market_risk:{checked_at:at,gate_action:'PASS'},a_candidates:{schema_version:1,kind:'watchlist',day:today,updated_at:at,rows:[
 {symbol:'TEST',name:'合成轉強股票（測試）',price:101,rule_score:75,model_score:.2592,execution:'not_filled',quote_at:at,state:'rule_ready',opening_recovery:true,reasons:['開低站回VWAP、低點墊高後放量轉強'],waits:[]},
 {symbol:'TEST2',name:'合成觀察股票（測試）',price:88,rule_score:65,model_score:null,execution:'not_filled',quote_at:at,state:'watch',reasons:['站上VWAP'],waits:['等待規則68分與兩項進場理由']}]}};
 const u=String(url);let data=null;
 if(u.endsWith('/active_release.json'))data='SYNTHETIC';else if(u.endsWith('/meta.json'))data=meta;
 else if(u.endsWith('/summary.json'))data=stocks;else if(u.endsWith('/intraday_live.json'))data=live;
 return {ok:true,json:async()=>data};
};
</script>`;
http.createServer((req,res)=>{
 const url=new URL(req.url,'http://127.0.0.1:8767');
 if(url.pathname==='/'||url.pathname==='/index.html'){
  res.setHeader('Content-Type','text/html; charset=utf-8');
  res.end(fs.readFileSync(path.join(root,'index.html'),'utf8').replace('<head>','<head>'+fixture));return;
 }
 const file=path.resolve(root,url.pathname.slice(1));
 if(!file.startsWith(root+path.sep)||!url.pathname.match(/^\/(assets|icon)\//)||!fs.existsSync(file)){res.writeHead(404);res.end();return;}
 res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'image/png');fs.createReadStream(file).pipe(res);
}).listen(8767,'127.0.0.1',()=>console.log('Synthetic A preview http://127.0.0.1:8767'));
