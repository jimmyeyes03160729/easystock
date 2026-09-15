// Repository policy checks for boolean allowlists, not a Firebase emulator.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const rules=JSON.parse(fs.readFileSync(path.join(__dirname,'../firebase.rules.json'),'utf8')).rules;
function allows(parts,operation){
  let node=rules;
  for(const part of [...parts.split('/').filter(Boolean),null]){
    if(node[operation]===true)return true;
    if(part===null)return false;
    const key=Object.hasOwn(node,part)?part:Object.keys(node).find(k=>k.startsWith('$'));
    if(!key)return false;
    node=node[key];
  }
}
const pub=['active_release','summary','meta','backtests','kline/2330','releases/test/summary','releases/test/meta','releases/test/backtests','releases/test/kline/2330','intraday_live','intraday_picks','premarket_brief','daytrade_learning_status','history_training_status','dual_review_status','public_feed'];
for(const p of pub)assert(allows('market_data/'+p,'.read'),p);
for(const p of ['','market_data','market_data/releases','market_data/releases/test','market_data/line_groups','market_data/paper_game','market_data/history','market_data/selection_history','market_data/overnight_history','market_data/daytrade_research','market_data/intraday_archive','market_data/unknown'])assert(!allows(p,'.read'),p);
function check(node){for(const [k,v] of Object.entries(node)){if(k==='.write')assert.equal(v,false);else if(v&&typeof v==='object')check(v);}}
check(rules);
for(const p of pub)assert(!allows('market_data/'+p,'.write'));
console.log('PASS Firebase policy: public endpoints allowed, parent/private/unknown paths denied, client writes denied');
