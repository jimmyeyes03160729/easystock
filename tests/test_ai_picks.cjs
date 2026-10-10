const test=require('node:test'),assert=require('node:assert/strict');
const A=require('../assets/ai-picks.js');

const batch={day:'2026-10-12',frozen_at:'2026-10-12T08:04:11+08:00',status:'waiting_entry',exit_day:'2026-10-16',
  models:{openai:{model:'gpt-6.1-sol',ok:true,invalid:['9999'],picks:[{symbol:'2303',name:'聯電',reason:'9 月營收創高',filled:true},
    {symbol:'2409',name:'<b>友達</b>',reason:'面板報價回升',filled:true}]},
    claude:{model:'claude-sonnet-5-5',ok:true,invalid:[],picks:[{symbol:'2303',name:'聯電',reason:'法說會',filled:true}]}},
  groups:{openai:{net_pct:null},claude:{net_pct:null},consensus:{net_pct:null},hot10:{net_pct:null},random5:{net_pct:null}},
  consensus:[{symbol:'2303',name:'聯電'}]};
const feed={rules_version:A.RULES,generated_at:'2026-10-12T08:05:00+08:00',summary:{closed_batches:0,groups:{}},recent:[batch]};

test('waiting batch: when it was picked, counts, shared picks and exit day',()=>{
  const s=A.summary(feed);
  assert.match(s,/10\/12（一） 08:04 選出/);assert.match(s,/ChatGPT 2 檔、Claude 1 檔，兩家共同選 1 檔/);
  assert.match(s,/10\/16（五）收盤賣出/);
  const html=A.picks(feed);
  assert.match(html,/2303 聯電 <span[^>]*>★兩家都選/);assert.match(html,/9 月營收創高/);assert.match(html,/待開盤/);
  assert.match(html,/名單外、不計分：9999/);assert(!html.includes('<b>友達'));assert.match(html,/&lt;b&gt;/);
});

test('holding batch shows each group against the baselines, failures and unfilled names',()=>{
  const b={...batch,status:'holding',mark_day:'2026-10-14',
    models:{openai:{...batch.models.openai,picks:[{symbol:'2303',name:'聯電',reason:'',filled:true,net_pct:1.5},{symbol:'2409',name:'友達',reason:'',filled:false}]},
      claude:{model:'claude-sonnet-5-5',ok:false,error:'HTTP 529: overloaded',picks:[]}},
    groups:{openai:{net_pct:.75},claude:{net_pct:null},consensus:{net_pct:1.5},hot10:{net_pct:-.3},random5:{net_pct:.1}}};
  const f={...feed,recent:[b]};
  const s=A.summary(f);
  assert.match(s,/Claude 回覆失敗/);assert.match(s,/截至 10\/14（三）收盤：ChatGPT \+0\.75%｜Claude —｜兩家都選 \+1\.50%｜熱門股（對照） -0\.30%｜隨機股（對照） \+0\.10%/);
  const html=A.picks(f);
  assert.match(html,/\+1\.50%/);assert.match(html,/開盤漲停未買/);assert.match(html,/今天回覆失敗：HTTP 529/);
});

test('record compares groups per million and says when there is nothing yet',()=>{
  assert.match(A.record(feed),/尚無已出場批次/);
  const f={...feed,summary:{closed_batches:3,groups:{p200_openai:{batches:3,wins:2,mean_net_pct:.5,twd_per_1m_mean:5000,twd_per_1m_total:15000},
    p200_hot10:{batches:3,wins:1,mean_net_pct:-.2,twd_per_1m_mean:-2000,twd_per_1m_total:-6000}}}};
  const html=A.record(f);
  assert.match(html,/3 批已出場/);assert.match(html,/ChatGPT/);assert.match(html,/熱門股（對照）/);
  assert.match(html,/\+15,000 元/);assert.match(html,/-6,000 元/);
  assert.match(A.summary({recent:[]}),/第一批 10\/12/);
});

test('stale feed is flagged after 36 hours',()=>{
  const at=Date.parse(feed.generated_at);
  assert.equal(A.stale(feed,at+3600000),false);assert.equal(A.stale(feed,at+37*3600000),true);
});
