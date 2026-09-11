/* Experimental daily range-rebound rules. No model fitting or live orders. */
(function(root){
'use strict';
const num=x=>typeof x==='number'&&Number.isFinite(x)?x:null;
const median=a=>{const b=[...a].sort((x,y)=>x-y);return b.length?b[Math.floor(b.length/2)]:null;};
const dayNumber=x=>/^\d{4}-\d{2}-\d{2}$/.test(String(x))?Date.parse(x+'T00:00:00Z')/86400000:NaN;
function financial(s,asof){
 const missing=[],failed=[],checks=[];
 const rules=[['rev_yoy','單月營收年增',v=>v>=-10],['eps','每股盈餘',v=>v>0],['operating_margin','營業利益率',v=>v>0],['debt_ratio','負債比',v=>v>=0&&v<65],['fcf','自由現金流',v=>v>0]];
 if(/金融|銀行|保險|證券/.test(String(s.category||'')))return {status:'unsupported',missing:[],failed:['金融業需另訂財務門檻'],checks};
 for(const [key,label,pass] of rules){
  const meta=s.field_meta?.[key],value=num(s[key]),age=dayNumber(asof)-dayNumber(meta?.as_of);
  if(value===null||!meta||!['official-api','official-filings'].includes(meta.source)||!(age>=0&&age<=45)||(s.legacy_fallback_fields||[]).includes(key))missing.push(label);
  else if(!pass(value))failed.push(label+'未達初篩');
  else checks.push({key,label,value,observed_at:meta.as_of,period:meta.period??null});
 }
 // Observation dates are not filing dates; require an identifiable period too.
 const rev=String(s.revenue_period||'').replace(/[^0-9]/g,'');
 let yr,mo;if(rev.length===5){yr=Number(rev.slice(0,3))+1911;mo=Number(rev.slice(3));}else if(rev.length===6){yr=Number(rev.slice(0,4));mo=Number(rev.slice(4));}
 const a=new Date(asof+'T00:00:00Z'),gap=yr&&mo>=1&&mo<=12?(a.getUTCFullYear()-yr)*12+a.getUTCMonth()+1-mo:NaN;
 if(!(gap>=1&&gap<=2))missing.push('近期營收月份');
 for(const key of ['eps','operating_margin','debt_ratio','fcf']){
  const period=String(s.field_meta?.[key]?.period||'');
  // Legacy payload with only quarter number cannot prove the fiscal year.
  const m=period.match(/^(\d{4})[- ]?Q([1-4])$/i);
  if(!m){missing.push('財報年度與季度');break;}
  const end=Date.UTC(+m[1],+m[2]*3,0)/86400000,age=dayNumber(asof)-end;
  if(!(age>=0&&age<=200)){missing.push('有效財報期間');break;}
 }
 return {status:failed.length?'failed':missing.length?'incomplete':'passed',missing:[...new Set(missing)],failed,checks};
}
function clusters(points,tol){
 const groups=[];
 for(const p of points){let g=groups.find(g=>Math.abs(p.v/median(g.map(x=>x.v))-1)<=tol);if(!g){g=[];groups.push(g);}if(!g.length||p.i-g.at(-1).i>=10)g.push(p);}
 return groups.filter(g=>g.length>=2&&g.at(-1).i-g[0].i>=20).map(g=>({price:median(g.map(x=>x.v)),touches:g.length,last:g.at(-1).i,points:g}));
}
function technical(rows,asof,price){
 const fail=reason=>({eligible:false,reason});
 if(!Array.isArray(rows))return fail('缺少日 K');
 const bars=rows.filter(b=>Number.isFinite(dayNumber(b.time))&&b.time<=asof).slice(-252);
 if(bars.length<120)return fail('日 K 少於 120 個交易日');
 if(bars.at(-1).time!==asof)return fail('K 線與行情日期不一致');
 for(let i=0;i<bars.length;i++){
  const b=bars[i];if(['open','high','low','close'].some(k=>num(b[k])===null||b[k]<=0)||b.high<Math.max(b.open,b.close,b.low)||b.low>Math.min(b.open,b.close)||i&&b.time<=bars[i-1].time)return fail('K 線結構或日期異常');
  if(i&&Math.abs(b.open/bars[i-1].close-1)>.12)return fail('價格跳空過大，需核對除權息與資料');
 }
 const last=bars.at(-1),prev=bars.at(-2);
 if(num(price)===null||Math.abs(price/last.close-1)>.005)return fail('最新價與日 K 不一致');
 const atr=bars.slice(-20).reduce((sum,b)=>sum+b.high-b.low,0)/20;
 const tol=Math.min(.04,Math.max(.02,atr/price));
 const lows=[],highs=[];
 // Pivots only become known after three following completed daily bars.
 for(let i=3;i<bars.length-3;i++){
  const neighbours=bars.slice(i-3,i+4).filter((_,j)=>j!==3);
  if(neighbours.every(b=>bars[i].low<=b.low)&&neighbours.some(b=>bars[i].low<b.low))lows.push({i,v:bars[i].low});
  if(neighbours.every(b=>bars[i].high>=b.high)&&neighbours.some(b=>bars[i].high>b.high))highs.push({i,v:bars[i].high});
 }
 const supports=clusters(lows,tol).filter(g=>g.last>=bars.length-100&&price>=g.price*(1-tol)&&price<=g.price*1.08).sort((a,b)=>b.price-a.price);
 for(const support of supports){
  const resistance=clusters(highs,tol).filter(g=>g.price/support.price>=1.15&&g.price>price&&g.last>=bars.length-120).sort((a,b)=>a.price-b.price)[0];
  if(!resistance)continue;
  const floor=support.price*(1-tol),ceiling=support.price*(1+tol);
  if(bars.slice(support.last+1).some(b=>b.close<floor*.98))continue;
  if((price-support.price)/(resistance.price-support.price)>.25)continue;
  const recent=bars.slice(-5);
  if(!recent.some(b=>b.low<=ceiling&&b.low>=floor*.98))continue;
  if(!(last.close>prev.high&&last.close>last.open&&last.low>=Math.min(...bars.slice(-6,-1).map(b=>b.low))*.995))continue;
  const invalid=floor-Math.max(atr*.5,price*.01),target=resistance.price*(1-tol);
  const rr=(target-price)/(price-invalid);if(rr<2||target<=price)continue;
  const score=Math.min(95,Math.round(55+Math.min(support.touches,4)*4+Math.min(resistance.touches,4)*3+Math.min(rr,5)*2));
  return {eligible:true,score,dailyChangePct:(last.close/prev.close-1)*100,support:[floor,ceiling],resistance:[resistance.price*(1-tol),resistance.price*(1+tol)],invalid,target,rr,touches:support.touches,pressureTouches:resistance.touches,reasons:['多次回測支撐','近期回測未破低','收盤突破前一日高點'],rule_version:'range-rebound-0.1',validated:false};
 }
 return fail('尚未同時符合區間底部與止跌條件');
}
root.RangeRebound={financial,technical,dayNumber};
if(typeof module!=='undefined')module.exports=root.RangeRebound;
})(typeof window!=='undefined'?window:globalThis);
