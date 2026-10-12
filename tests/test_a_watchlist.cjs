const test=require('node:test'),assert=require('node:assert/strict');
const A=require('../assets/a-watchlist.js');
const now=Date.parse('2026-10-13T10:00:00+08:00');
const row={symbol:'TEST',name:'<script>bad</script>',price:101,rule_score:75,model_score:.2592,
  execution:'not_filled',quote_at:'2026-10-13T10:00:00+08:00',state:'rule_ready',reasons:['站上VWAP'],waits:[]};
const live={a_candidates:{schema_version:1,kind:'watchlist',day:'2026-10-13',updated_at:row.quote_at,rows:[row]}};
test('visible rule candidates never masquerade as filled trades or calibrated win rates',()=>{
  const value=A.view(live,{current:true},now),html=A.cards(value);
  assert.equal(value.rows.length,1);assert.match(html,/等待成交確認/);
  assert.match(html,/非已驗證勝率/);assert(!html.includes('<script>bad'));
  assert.match(html,/&lt;script&gt;/);
});
test('stale, cross-day, future and disconnected snapshots do not show recommendations',()=>{
  assert.equal(A.view(live,{current:true},now+31000).rows.length,0);
  assert.equal(A.view(live,{current:true},now-1000).rows.length,0);
  assert.equal(A.view({...live,a_candidates:{...live.a_candidates,day:'2026-10-12'}},{current:true},now).rows.length,0);
  assert.equal(A.view(live,{current:false},now).rows.length,0);
});
