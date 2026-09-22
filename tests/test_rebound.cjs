const assert=require('node:assert/strict');
const {test}=require('node:test');
const R=require('../assets/rebound-engine.js');
function fixture(){return Array.from({length:162},(_,i)=>{
 let c=10+5*(1-Math.abs((i%40)-20)/20),o=c;
 if(i===161){c=10.5;o=10.05;}
 return {time:new Date(Date.UTC(2026,0,1+i)).toISOString().slice(0,10),open:o,high:c+.1,low:Math.min(c,o)-.1,close:c};
});}
const run=rows=>R.technical(rows,rows.at(-1).time,rows.at(-1).close);
const finance=()=>({rev_yoy:-15,eps:1,operating_margin:4,debt_ratio:68,revenue_period:'202605',field_meta:Object.fromEntries(['rev_yoy','eps','operating_margin','debt_ratio'].map(k=>[k,{source:'official-api',as_of:'2026-06-11'}]))});
const fin=x=>R.financial(x,'2026-06-11');
test('confirmed range passes, with conservative cost adjustment and no claimed validation',()=>{
 const r=run(fixture());assert(r.eligible);assert.equal(r.confirmation,'breakout');assert(r.netRR<r.rr);assert(r.netRR>=1.5);assert.equal(r.validated,false);
 assert(Math.abs(r.netRR-(r.target-10.5-10.5*.006)/(10.5-r.invalid+10.5*.006))<1e-9);
});
test('90 bars eligible, 89 rejected; cannot require 120 in UI',()=>{assert(run(fixture().slice(-90)).eligible);assert(!run(fixture().slice(-89)).eligible);});
test('breakout remains eligible next day while holding breakout',()=>{
 const r=fixture();r.push({time:'2026-06-12',open:10.48,high:10.55,low:10.3,close:10.45});const t=run(r);assert(t.eligible,JSON.stringify(t));assert.equal(t.confirmation,'breakout');
});
test('early rebound requires two rising closes, red candle and strong close',()=>{
 const r=fixture();Object.assign(r.at(-3),{open:10.2,close:10.1,high:10.7,low:9.95});Object.assign(r.at(-2),{open:10.05,close:10.15,high:10.6,low:9.95});Object.assign(r.at(-1),{open:10.05,close:10.3,high:10.4,low:9.95});
 assert.equal(run(r).confirmation,'early');r.at(-1).close=10.1;assert(!run(r).eligible);
});
test('fresh falling knife and historic broken support are rejected',()=>{
 const r=fixture();Object.assign(r.at(-1),{open:10.1,close:9.7,low:9.6,high:10.2});assert(!run(r).eligible);
 const b=fixture();Object.assign(b.at(-2),{open:10,close:9.2,low:9.1,high:10.1});assert(!run(b).eligible);
});
test('upper range, malformed candles, stale dates and price mismatch are rejected',()=>{
 const r=fixture();assert(!run(r.slice(0,141)).eligible);
 const bad=structuredClone(r);bad[50].low=100;assert(!run(bad).eligible);
 assert(!R.technical(r,'2026-06-12',10.5).eligible);assert(!R.technical(r,r.at(-1).time,20).eligible);
});
test('future bars cannot leak into results; duplicate dates and corporate-action jumps rejected',()=>{
 const r=fixture();assert.deepEqual(R.technical([...r,{time:'2027-01-01',open:1,high:1,low:1,close:1}],r.at(-1).time,10.5),run(r));
 const d=structuredClone(r);d[50].time=d[49].time;assert(!run(d).eligible);
 const g=structuredClone(r);g[50]={...g[50],open:5,high:5,low:5,close:5};assert(!run(g).eligible);
});
test('relaxed revenue and debt bounds retain positive profits and explicit financial sector veto',()=>{
 assert.equal(fin(finance()).status,'passed');for(const [k,v] of [['rev_yoy',-20.01],['debt_ratio',70],['eps',0],['operating_margin',-1]])assert.equal(fin({...finance(),[k]:v}).status,'failed');
 assert.equal(fin({...finance(),rev_yoy:-20}).status,'passed');assert.equal(fin({...finance(),category:'17'}).status,'unsupported');assert.equal(fin({...finance(),name:'某某銀行',category:'上櫃'}).status,'unsupported');
});
test('missing data, old/future source and stale revenue remain incomplete',()=>{
 assert.equal(fin({...finance(),eps:null}).status,'incomplete');assert.equal(fin({...finance(),revenue_period:'202501'}).status,'incomplete');
 for(const as_of of ['2026-01-01','2026-06-12']){const f=finance();f.field_meta.eps.as_of=as_of;assert.equal(fin(f).status,'incomplete');}
 const f=finance();f.field_meta.eps.source='unknown';assert.equal(fin(f).status,'incomplete');
 assert.equal(fin({...finance(),legacy_fallback_fields:['eps']}).status,'incomplete');
});
test('optional FCF and absent quarter labels do not fake completeness or block valid official values',()=>{
 assert.equal(fin({...finance(),fcf:null}).status,'passed');assert.equal(fin(finance()).checks.length,4);
});
test('nearby resistance cannot be skipped to inflate upside',()=>{
 const r=fixture();for(const center of [80,120])for(let i=center-3;i<=center+3;i++)Object.assign(r[i],{open:10.1,close:10.1,low:i===center?9.9:10,high:i===center?10.7:10.2});
 const t=run(r);assert(!t.eligible);assert(t.reason.includes('壓力觸及不足或區間小於 10%'),JSON.stringify(t));
});
