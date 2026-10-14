'use strict';
const finite=v=>typeof v==='number'&&Number.isFinite(v);
const tpe=ms=>new Date(ms+28800000).toISOString().replace('Z','+08:00');
// Quantity scale is checked from turnover/VWAP bounds in the same snapshot.
// Turnover is a quality check only; selection ranks cumulative shares, not money.
function project(snapshots,now,receivedAt={}) {
 const rows={},diagnostics={};
 for(const market of ['TSE','OTC']) {
  const s=snapshots[market];
  const received=receivedAt[market];
  if(!finite(received)||received>now){diagnostics[market]='missing_receipt_time';continue;}
  if(!s||s.date!==tpe(now).slice(0,10)||!Array.isArray(s.data)){diagnostics[market]='missing_same_day_snapshot';continue;}
  for(const r of s.data) {
   if(r.type!=='EQUITY'||!/^\d{4}$/.test(r.symbol)||r.symbol.startsWith('0'))continue;
   const at=r.lastUpdated/1000;
   if(!Number.isSafeInteger(r.lastUpdated)||at>received||tpe(at).slice(0,10)!==s.date)continue;
   if(![r.closePrice,r.highPrice,r.lowPrice].every(v=>finite(v)&&v>0)||r.closePrice<r.lowPrice||r.closePrice>r.highPrice)continue;
   const factors=[1,1000].filter(f=>finite(r.tradeVolume)&&r.tradeVolume>0&&finite(r.tradeValue)&&r.tradeValue>0&&
    r.tradeValue/(r.tradeVolume*f)>=r.lowPrice-1e-8&&r.tradeValue/(r.tradeVolume*f)<=r.highPrice+1e-8);
   rows[r.symbol]={symbol:r.symbol,name:r.name,exchange:market==='TSE'?'TWSE':'TPEX',
    price:r.closePrice,day_high:r.highPrice,quote_at:tpe(at),received_at:tpe(received),
    day_volume:factors.length===1?r.tradeVolume*factors[0]:null,raw_trade_volume:r.tradeVolume,
    volume_scale:factors.length===1?factors[0]:null,
    quantity_check:factors.length===1?'same_snapshot_turnover_price_bounds':'unverified',
    source:'esun_snapshot_quotes'};
  }
 }
 return {schema_version:1,generated_at:tpe(now),day:tpe(now).slice(0,10),rows,diagnostics};
}
module.exports={project};
