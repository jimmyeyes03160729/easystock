/* Experimental daily range-rebound rules. No model fitting or live orders. */
(function(root){
'use strict';
const num=x=>typeof x==='number'&&Number.isFinite(x)?x:null;
const median=a=>{const b=[...a].sort((x,y)=>x-y);return b.length?b[Math.floor(b.length/2)]:null;};
const RULES=Object.freeze({minBars:90,minTouchGap:7,minTouchSpan:14,minRange:.10,maxRangePosition:.35,maxAboveSupport:.10,minNetRR:1.5,costPct:.006});
const dayNumber=x=>/^\d{4}-\d{2}-\d{2}$/.test(String(x))?Date.parse(x+'T00:00:00Z')/86400000:NaN;
function financial(s,asof){
 const missing=[],failed=[],checks=[];
 // FCF is deliberately not mandatory here. update_market currently cannot obtain a
 // stable official consolidated FCF field, so requiring it would block every stock.
 const rules=[['rev_yoy','單月營收年增',v=>v>=-20],['eps','每股盈餘',v=>v>0],['operating_margin','營業利益率',v=>v>0],['debt_ratio','負債比',v=>v>=0&&v<70]];
 if(String(s.category||'').trim()==='17'||/金融|銀行|保險|證券/.test(String(s.category||''))||/金控|銀行|證券|產險|壽險/.test(String(s.name||'')))return {status:'unsupported',missing:[],failed:['金融業需另訂財務門檻'],checks,optional:[]};
 for(const [key,label,pass] of rules){
  const meta=s.field_meta?.[key],value=num(s[key]),age=dayNumber(asof)-dayNumber(meta?.as_of);
  if(value===null||!meta||!['official-api','official-filings'].includes(meta.source)||!(age>=0&&age<=45)||(s.legacy_fallback_fields||[]).includes(key))missing.push(label);
  else if(!pass(value))failed.push(label+'未達初篩');
  else checks.push({key,label,value,observed_at:meta.as_of,period:meta.period??null});
 }
 // FCF is supporting information only until the publisher supplies a stable,
 // period-identifiable official field. A trustworthy negative value is shown but
 // does not silently turn missing data into a pass/fail gate.
 const optional=[];
 const fcfMeta=s.field_meta?.fcf,fcfValue=num(s.fcf),fcfAge=dayNumber(asof)-dayNumber(fcfMeta?.as_of);
 const fcfUsable=fcfValue!==null&&fcfMeta&&['official-api','official-filings'].includes(fcfMeta.source)&&fcfAge>=0&&fcfAge<=200&&!(s.legacy_fallback_fields||[]).includes('fcf');
 optional.push({key:'fcf',label:'自由現金流',status:fcfUsable?(fcfValue>0?'positive':'negative'):'unavailable',value:fcfUsable?fcfValue:null,observed_at:fcfUsable?fcfMeta.as_of:null,period:fcfUsable?(fcfMeta.period??null):null});
 // Keep the monthly revenue period check because it determines whether the
 // revenue figure is current. Quarterly labels are optional metadata: some
 // official payloads provide trustworthy EPS/margin/debt values and dates but
 // omit a normalized YYYY-Qn label. Missing that label alone must not turn an
 // otherwise valid company into "基本面待補".
 const rev=String(s.revenue_period||'').replace(/[^0-9]/g,'');
 let yr,mo;if(rev.length===5){yr=Number(rev.slice(0,3))+1911;mo=Number(rev.slice(3));}else if(rev.length===6){yr=Number(rev.slice(0,4));mo=Number(rev.slice(4));}
 const a=new Date(asof+'T00:00:00Z'),gap=yr&&mo>=1&&mo<=12?(a.getUTCFullYear()-yr)*12+a.getUTCMonth()+1-mo:NaN;
 if(!(gap>=1&&gap<=2))missing.push('近期營收月份');
 return {status:failed.length?'failed':missing.length?'incomplete':'passed',missing:[...new Set(missing)],failed,checks,optional};
}
function clusters(points,tol){
 const groups=[];
 for(const p of points){let g=groups.find(g=>Math.abs(p.v/median(g.map(x=>x.v))-1)<=tol);if(!g){g=[];groups.push(g);}if(!g.length||p.i-g.at(-1).i>=RULES.minTouchGap)g.push(p);}
 return groups.filter(g=>g.length>=2&&g.at(-1).i-g[0].i>=RULES.minTouchSpan).map(g=>({price:median(g.map(x=>x.v)),touches:g.length,last:g.at(-1).i,points:g}));
}
function technical(rows,asof,price){
 const fail=reason=>({eligible:false,reason});
 if(!Array.isArray(rows))return fail('缺少日 K');
 const bars=rows.filter(b=>Number.isFinite(dayNumber(b.time))&&b.time<=asof).slice(-252);
 if(bars.length<RULES.minBars)return fail('日 K 少於 90 個交易日');
 if(bars.at(-1).time!==asof)return fail('K 線與行情日期不一致');
 for(let i=0;i<bars.length;i++){
  const b=bars[i];if(['open','high','low','close'].some(k=>num(b[k])===null||b[k]<=0)||b.high<Math.max(b.open,b.close,b.low)||b.low>Math.min(b.open,b.close)||i&&b.time<=bars[i-1].time)return fail('K 線結構或日期異常');
  if(i&&Math.abs(b.open/bars[i-1].close-1)>.12)return fail('價格跳空過大，需核對除權息與資料');
 }
 const last=bars.at(-1),prev=bars.at(-2);
 if(num(price)===null||Math.abs(price/last.close-1)>.005)return fail('最新價與日 K 不一致');
 const atr=bars.slice(-20).reduce((sum,b,j)=>{const previous=bars[bars.length-21+j].close;return sum+Math.max(b.high-b.low,Math.abs(b.high-previous),Math.abs(b.low-previous));},0)/20;
 const tol=Math.min(.04,Math.max(.02,atr/price));
 const lows=[],highs=[];
 for(let i=3;i<bars.length-3;i++){
  const neighbours=bars.slice(i-3,i+4).filter((_,j)=>j!==3);
  if(neighbours.every(b=>bars[i].low<=b.low)&&neighbours.some(b=>bars[i].low<b.low))lows.push({i,v:bars[i].low});
  if(neighbours.every(b=>bars[i].high>=b.high)&&neighbours.some(b=>bars[i].high>b.high))highs.push({i,v:bars[i].high});
 }
 const supports=clusters(lows,tol).filter(g=>g.last>=bars.length-100&&price>=g.price*(1-tol)&&price<=g.price*(1+RULES.maxAboveSupport)).sort((a,b)=>b.price-a.price);
 const rejected=new Set();
 for(const support of supports){
  const resistance=clusters(highs,tol).filter(g=>g.price>price&&g.last>=bars.length-120).sort((a,b)=>a.price-b.price)[0];
  if(!resistance||resistance.price/support.price<1+RULES.minRange){rejected.add('壓力觸及不足或區間小於 10%');continue;}
  const floor=support.price*(1-tol),ceiling=support.price*(1+tol);
  if(bars.slice(support.last+1).some(b=>b.close<floor*.98)){rejected.add('支撐曾收盤跌破');continue;}
  if((price-support.price)/(resistance.price-support.price)>RULES.maxRangePosition){rejected.add('已離開區間底部 35%');continue;}
  const recent=bars.slice(-8);
  if(!recent.some(b=>b.low<=ceiling&&b.low>=floor*.98)){rejected.add('近 8 日未回測支撐');continue;}
  // Confirmation may occur on any of the last three completed sessions. A
  // later close must hold that breakout, and today's low must not make a new low.
  const confirmed=bars.slice(-3).some((b,j)=>{
   const i=bars.length-3+j,prior=bars[i-1];
   return b.close>prior.high&&b.close>b.open&&bars.slice(i).every(x=>x.close>=prior.high);
  });
  const early=last.close>prev.close&&prev.close>bars.at(-3).close&&last.close>last.open&&
   last.high>last.low&&(last.close-last.low)/(last.high-last.low)>=.65;
  if(last.low<Math.min(...bars.slice(-6,-1).map(b=>b.low))*.995||(!confirmed&&!early)){
   rejected.add('尚未確認突破或連兩日止跌');continue;
  }
  const invalid=floor-Math.max(atr*.5,price*.01),target=resistance.price*(1-tol);
  const risk=price-invalid,reward=target-price,cost=price*RULES.costPct;
  const rr=reward/risk,netRR=(reward-cost)/(risk+cost);
  if(!(risk>0&&reward>cost&&netRR>=RULES.minNetRR)){rejected.add('扣假設成本後空間不足 1.5 倍');continue;}
  const score=Math.min(95,Math.round(55+Math.min(support.touches,4)*4+Math.min(resistance.touches,4)*3+Math.min(netRR,5)*2+(confirmed?3:0)));
  return {eligible:true,score,dailyChangePct:(last.close/prev.close-1)*100,support:[floor,ceiling],resistance:[resistance.price*(1-tol),resistance.price*(1+tol)],invalid,target,rr,netRR,costPct:RULES.costPct,confirmation:confirmed?'breakout':'early',touches:support.touches,pressureTouches:resistance.touches,reasons:['多次回測支撐','近 8 日回測、今日未破近期低點',confirmed?'近 3 日突破昨高並守穩':'連兩日收高、收紅且位於當日上緣'],rule_version:'range-rebound-0.3',validated:false};
 }
 return fail(supports.length?([...rejected].join('；')||'型態尚未成立'):'未形成重複支撐或距支撐超過 10%');
}
root.RangeRebound={financial,technical,dayNumber,RULES};
if(typeof module!=='undefined')module.exports=root.RangeRebound;
})(typeof window!=='undefined'?window:globalThis);
