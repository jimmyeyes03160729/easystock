const test=require('node:test'),assert=require('node:assert/strict');
const S=require('../assets/short-term.js');

const waiting={rules_version:'revenue-sur-short-v1',generated_at:'2026-10-12T21:20:00+08:00',strategy:{hold_sessions:10},
  current:{month:'2026-09',status:'waiting_entry',deadline_session:'2026-10-12',entry_day:'2026-10-13',exit_day:'2026-10-27',
    positions:[{rank:1,symbol:'2330',name:'台積電',sur:3.21,rev_yoy_pct:45.2,deadline_close:1000,shares_est:100}]},
  history:[],record:{batches:0,wins:0,twd_per_1m_total:0},next:{deadline_session:'2026-11-10',entry_day:'2026-11-11'}};

test('waiting batch states entry, exit and the limit-up rule with weekdays',()=>{
  const text=S.summary(waiting);
  assert.match(text,/2026 年 9 月營收/);
  assert.match(text,/10\/13（二）開盤買進/);
  assert.match(text,/10\/27（二）收盤賣出/);
  assert.match(text,/漲停的不追/);
  const html=S.positions(waiting);
  assert.match(html,/2330 台積電/);assert.match(html,/\+45\.20%/);assert.match(html,/100 股/);assert.match(html,/待開盤/);
});

test('holding batch shows per-million figure, unfilled limit-up names and escapes names',()=>{
  const feed={...waiting,current:{...waiting.current,status:'holding',mark_day:'2026-10-20',net_pct:1.5,twd_per_1m:15000,universe_net_pct:.4,
    positions:[{rank:1,symbol:'1234',name:'<b>x</b>',filled:true,entry:50,mark:52,net_pct:3.62},{rank:2,symbol:'5678',name:'Y',filled:false}]}};
  assert.match(S.summary(feed),/每 100 萬 \+15,000 元/);
  const html=S.positions(feed);
  assert.match(html,/開盤漲停未買/);assert.match(html,/留現金/);assert(!html.includes('<b>x</b>'));assert.match(html,/&lt;b&gt;/);
});

test('closed record and next batch when nothing is held',()=>{
  const feed={...waiting,current:null,last_closed:{month:'2026-09',exit_day:'2026-10-27',net_pct:-2,twd_per_1m:-20000},
    history:[{month:'2026-09',entry_day:'2026-10-13',exit_day:'2026-10-27',n_filled:9,net_pct:-2,universe_net_pct:-1,excess_pct:-1,twd_per_1m:-20000}],
    record:{batches:1,wins:0,twd_per_1m_total:-20000}};
  assert.match(S.summary(feed),/-2\.00%.*-20,000 元.*11\/10（二）晚上選股/);
  assert.match(S.history(feed),/1 批，0 批賺錢/);
  assert.match(S.history(waiting),/尚無已出場批次/);
  assert.match(S.positions(feed),/目前沒有持股/);
});

test('stale feed is flagged after 36 hours',()=>{
  const at=Date.parse(waiting.generated_at);
  assert.equal(S.stale(waiting,at+3600000),false);
  assert.equal(S.stale(waiting,at+37*3600000),true);
  assert.equal(S.stale({},at),true);
});
