const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs');
const {createDOM}=require('./dom.cjs'),marketFixture=require('./admin_market_fixture.cjs');
const html=fs.readFileSync('easystock_admin/static/index.html','utf8');
function fixture(t,data=marketFixture()){
  const {w,run}=createDOM(html);t.after(()=>w.close());const calls=[];
  let error=null;
  w.api=async(path,options)=>{calls.push({path,options});assert.equal(path,'api/market-context');assert.equal(options,undefined);if(error)throw error;return data;};
  run('easystock_admin/static/live-console.js');
  assert.equal(calls.length,0);
  return {w,data,calls,root:w.document.getElementById('marketContext'),load:()=>w.loadMarketContext(),fail:()=>{error=Error('<img src=x onerror=alert(1)>');}};
}
test('market summary and sector cards format source values without changing ranks',async t=>{
  const f=fixture(t);await f.load();
  assert.equal(f.root.querySelectorAll('.market-context-metric').length,4);
  assert.equal(f.root.querySelectorAll('.market-sector-card').length,5);
  assert.match(f.root.textContent,/航運領先/);
  assert.match(f.root.textContent,/-0\.83%/);assert.match(f.root.textContent,/-0\.08 pp/);
  assert.match(f.root.textContent,/\+0\.75%/);assert.match(f.root.textContent,/\+1\.49 pp/);
  assert(!f.root.textContent.includes('826558436'));assert(!f.root.textContent.includes('fresh true'));
  assert(!f.root.textContent.includes('T11:17:45'));assert.match(f.root.textContent,/台北/);
  assert.deepEqual([...f.root.querySelectorAll('.market-sector-head .market-context-badge')].map(n=>n.textContent),['排名 2','排名 3','排名 5','排名 4','排名 1']);
  assert.deepEqual(f.calls.map(c=>c.path),['api/market-context']);
});
test('coverage is a bounded ratio and valid zero counts are distinct from missing counts',async t=>{
  const f=fixture(t);f.data.breadth={status:'DEGRADED',valid:true,fresh:true,advancers:0,decliners:1000,unchanged:null,coverage:.87654321};await f.load();
  const values=()=>[...f.root.querySelectorAll('.market-context-metric strong')].map(n=>n.textContent);
  assert.deepEqual(values(),['部分資料可用','0 / 1,000 / —','87.65%','航運領先']);
  for(const invalid of [null,undefined,'0.9',Infinity,NaN,-.1,1.01]){f.data.breadth.coverage=invalid;await f.load();assert.equal(values()[2],'—');}
  f.data.breadth.coverage=0;await f.load();assert.equal(values()[2],'0.00%');
});
test('stale context and rows suppress old values instead of pretending to be zero',async t=>{
  const f=fixture(t);f.data.current=false;await f.load();
  assert([...f.root.querySelectorAll('.market-sector-return')].every(n=>n.textContent==='—'));
  assert(!/航運領先|排名 \d|最新快照/.test(f.root.textContent));
  f.data.current=true;f.data.sectors.rows[0].fresh=false;f.data.sectors.rows[1].valid=false;f.data.sectors.rows[2].return_day=null;
  await f.load();assert.equal(f.root.querySelector('.market-sector-return').textContent,'—');assert.match(f.root.textContent,/過期／待更新/);
  assert.equal(f.root.querySelectorAll('.market-sector-return')[2].textContent,'—');
  f.data.sectors.rows[2].return_day=0;await f.load();assert.equal(f.root.querySelectorAll('.market-sector-return')[2].textContent,'0.00%');
});
test('empty, malformed and failed market reads are safe and clear earlier cards',async t=>{
  const f=fixture(t);f.data.sectors.rows[0].name='<img src=x onerror=alert(1)>';await f.load();
  assert.equal(f.root.querySelectorAll('img').length,0);assert.match(f.root.textContent,/<img/);
  f.data.sectors.rows=[];await f.load();assert.match(f.root.textContent,/不代表各類股漲跌為零/);
  f.data.sectors.rows='invalid';f.data.generated_at='invalid';await f.load();assert.match(f.root.textContent,/時間待確認/);
  f.fail();await f.load();assert.equal(f.root.querySelectorAll('.market-sector-card').length,0);assert.equal(f.root.querySelectorAll('img').length,0);assert.match(f.root.textContent,/讀取失敗，狀態待確認/);
});
test('manual price and quantity use equivalent label rows with quick quantity below the input',t=>{
  const {w}=createDOM(html);t.after(()=>w.close());
  const fields=w.document.querySelectorAll('.order-entry-fields .field-group');assert.equal(fields.length,2);
  for(const [i,id] of ['orderPrice','orderQty'].entries()){
    const label=fields[i].querySelector('.field-header label');assert.equal(label.htmlFor,id);
    assert.equal(fields[i].querySelector('.field-header button'),null);
    assert.equal(fields[i].children[1].id,id);
  }
  const quick=w.document.getElementById('quickQtyBtns');assert.equal(quick.previousElementSibling.id,'orderQty');
  assert.equal(quick.getAttribute('role'),'group');assert.equal(quick.getAttribute('aria-label'),'快捷委託數量');
  assert.deepEqual([...quick.querySelectorAll('button')].map(n=>n.dataset.qty),['1','10','100']);
});
test('all modified Admin static assets retain byte-identical VM mirrors',()=>{
  for(const name of ['admin.css','admin.js','index.html','live-console.js'])assert.deepEqual(fs.readFileSync('easystock_admin/static/'+name),fs.readFileSync('vm_runtime/easystock_admin/static/'+name));
});
