const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {createDOM,settle}=require('./dom.cjs');
const html=fs.readFileSync('index.html','utf8');
const main=[...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)].map(m=>m[1]).find(s=>s.includes('function taiwanDay('));
function setup(t){
 const env=createDOM(html),{w,run,dom}=env;t.after(async()=>{await settle();w.close();});
 w.fetch=async()=>({ok:true,json:async()=>null});
 vm.runInContext(main,dom.getInternalVMContext());w.onload=null;
 run('assets/dashboard-ux.js');run('assets/learning-status.js');run('assets/dashboard-layout.js');run('assets/glass-home.js');
 return {...env,eval:code=>vm.runInContext(code,dom.getInternalVMContext())};
}
test('production presentation preserves chart nodes, all sections and truthful unloaded summaries',t=>{
 const {w}=setup(t),d=w.document;
 for(const id of ['intradayPickList','runwayV2PickList','runwayB2PickList','runwayB3PickList','aCandidateList','bReplayRows','dashboardOverview','overviewNotice','learningSection'])assert(d.getElementById(id),id);
 assert.equal(d.getElementById('homeResearchCount').textContent,'—');
 assert.equal(d.getElementById('homeResearchPnl').textContent,'—');
 assert(d.querySelector('.dashboard-data-details #dashboardOverview'));
 const ids=[...d.querySelectorAll('[id]')].map(e=>e.id);assert.equal(ids.length,new Set(ids).size);
 assert.equal(d.querySelectorAll('.home-strategy-pane:not([hidden])').length,1);
 assert.equal(d.querySelector('.home-strategy-pane:not([hidden])').id,'homePaneA');
});
test('tabs work with keyboard and retain every record handler without truncating source data',async t=>{
 const {w}=setup(t),d=w.document,list=d.getElementById('runwayB2PickList');
 for(let i=0;i<8;i++){const c=d.createElement('div');c.className='trade-detail-card';c.dataset.homePrice='100';c.dataset.homeStatus=i<6?'OPEN':'CLOSED';c.dataset.tradeSymbol='TEST'+i;list.append(c);}
 await settle();
 d.getElementById('homeTabB2').click();assert(!d.getElementById('homePaneB2').hidden);
 assert.equal(list.children.length,8);assert.equal(list.querySelectorAll('[hidden]').length,2,'never hide open positions to meet the five-row limit');
 d.getElementById('homeMoreB2').click();assert.equal(list.querySelectorAll('[hidden]').length,0);
 d.getElementById('homeTabB2').dispatchEvent(new w.KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}));
 assert.equal(d.getElementById('homeTabB3').getAttribute('aria-selected'),'true');assert.equal(d.activeElement.id,'homeTabB3');
 assert.equal(list.firstElementChild.dataset.tradeSymbol,'TEST0');
});
test('price/budget filters apply to B presentation and restore rows without editing records',async t=>{
 const {w}=setup(t),d=w.document,list=d.getElementById('runwayV2PickList');
 list.innerHTML='<div class="trade-detail-card" data-home-price="40" data-home-status="CLOSED" data-trade-symbol="LOW"></div><div class="trade-detail-card" data-home-price="100" data-home-status="CLOSED" data-trade-symbol="HIGH"></div>';
 d.getElementById('priceMax').value='50';d.getElementById('priceMax').dispatchEvent(new w.Event('input',{bubbles:true}));await settle();
 assert(!list.children[0].hidden);assert(list.children[1].hidden);
 assert.equal(list.children.length,2);
 d.getElementById('priceMax').value='';w.HomePresentation.refreshLists();assert(!list.children[1].hidden);
});
test('summary follows actual learning fields and never claims missing or invalid coverage is zero/success',async t=>{
 const {w}=setup(t),d=w.document;
 for(const [id,value] of Object.entries({researchTrades:'研究交易：7',researchClosed:'研究完成：7',researchPaperFilled:'Paper 成交：1',researchPaperSkipped:'Paper 略過：6',researchPnl:'研究淨報酬合計：-2.21%',learnCoverage:'309 / 312',researchSummaryDate:'最近交易日：2026-10-16'}))d.getElementById(id).textContent=value;
 await settle();assert.equal(d.getElementById('homeResearchCount').textContent,'7');assert.equal(d.getElementById('homePaperFilled').textContent,'1');
 assert.equal(d.getElementById('homeResearchPnl').textContent,'-2.21%');assert.equal(d.getElementById('homeCoveragePercent').textContent,'99.0%');
 assert.match(d.getElementById('homeResearchDate').textContent,/2026-10-16/);
 d.getElementById('learnCoverage').textContent='0 / 0';await settle();assert.equal(d.getElementById('homeCoveragePercent').textContent,'—');
 w.DashboardUX.update({live:{session:'closed',open_positions:{X:{}}},health:{current:false,label:'連線失敗'},meta:{}});
 assert.equal(d.getElementById('homeOpenCount').textContent,'—');
});

test('inactive strategy panels stay visually hidden despite legacy flex styles and live refreshes',async t=>{
 const {w}=setup(t),d=w.document;
 const styles=d.createElement('style');
 styles.textContent='#daytradeModule .home-strategy-pane{display:flex}\n'+fs.readFileSync('assets/glass-home.css','utf8');d.head.append(styles);
 const check=selected=>{
  for(const lane of ['A','B1','B2','B3']){
   const pane=d.getElementById('homePane'+lane),display=w.getComputedStyle(pane).display;
   assert.equal(pane.hidden,lane!==selected,lane+' hidden state');
   assert.equal(display==='none',lane!==selected,lane+' actual CSS visibility while '+selected+' selected');
  }
 };
 for(const lane of ['A','B1','B2','B3','A']){
  d.getElementById('homeTab'+lane).click();check(lane);
  w.HomePresentation.update({live:{session:'closed'},health:{current:true}});
  const record=d.createElement('div');record.className='trade-detail-card';record.dataset.homePrice='100';record.dataset.homeStatus='CLOSED';
  d.getElementById('intradayPickList').append(record);await settle();check(lane);
 }
});
