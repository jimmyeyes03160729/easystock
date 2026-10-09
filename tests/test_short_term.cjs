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

test('full-universe line and table list every company with fill reasons and search',()=>{
  assert.equal(S.fullLine(waiting),'');
  const pending={...waiting,current:{...waiting.current,full_summary:{n_companies:1979,n_scored:1850}}};
  assert.match(S.fullLine(pending),/已收錄 1,979 家（1850 家有驚喜分數）/);
  const held={...waiting,current:{...waiting.current,full_summary:{n_companies:1979,n_scored:1850,all:{net_pct:.5},top10:{net_pct:2},top_decile:{net_pct:1.2},bottom_decile:{net_pct:-.8},no_score:{net_pct:null}}}};
  assert.match(S.fullLine(held),/不設成交額門檻，1,979 家.*全部平均 \+0\.50%｜分數前 10 名 \+2\.00%｜分數前 10%.*後 10% -0\.80%｜無分數 —/);
  const full={status:'holding',rows:[{rank:1,symbol:'1234',name:'甲',market:'上市',sur:2.1,rev_yoy_pct:30,fill:'filled',entry:10,mark:11,net_pct:9.6},
    {rank:2,symbol:'5678',name:'乙',market:'上櫃',sur:1.9,rev_yoy_pct:20,fill:'limit_up'},{rank:null,symbol:'9999',name:'丙',market:'上櫃',sur:null,rev_yoy_pct:null,fill:'no_trade'}]};
  const html=S.fullTable(full,'');
  assert.match(html,/1234 甲/);assert.match(html,/開盤漲停/);assert.match(html,/當日無成交/);assert.match(html,/上櫃/);
  assert(!S.fullTable(full,'乙').includes('1234'));
  assert.match(S.fullTable(full,'沒有這檔'),/沒有符合/);
  assert.match(S.fullTable({status:'waiting_entry',rows:[{rank:1,symbol:'1234',name:'甲',market:'上市',sur:2,rev_yoy_pct:1,deadline_close:12.3}]},''),/截止日收盤.*12\.30/s);
});
