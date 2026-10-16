// Repository policy checks for firebase.rules.json. This is a rules SIMULATION, not the Firebase emulator:
// it models Realtime Database cascade semantics (a granting .read/.write on any ancestor applies to all
// descendants and cannot be revoked lower down) and evaluates only the auth expression used below.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const rules=JSON.parse(fs.readFileSync(path.join(__dirname,'../firebase.rules.json'),'utf8')).rules;
const OWNER_RULE='auth != null && auth.uid === $uid';
function evaluate(rule,vars,auth){
  if(rule===true||rule===false)return rule;
  if(rule===OWNER_RULE)return auth!=null&&auth.uid===vars.$uid;
  throw new Error(`unsupported rule expression in policy test: ${rule}`);
}
// Returns true when any node on the path (root → target) grants the operation.
function allows(parts,operation,auth=null){
  let node=rules; const vars={};
  for(const part of [...parts.split('/').filter(Boolean),null]){
    if(operation in node&&evaluate(node[operation],vars,auth))return true;
    if(part===null)return false;
    let key=Object.hasOwn(node,part)?part:null;
    if(!key){key=Object.keys(node).find(k=>k.startsWith('$'));if(key)vars[key]=part;}
    if(!key)return false;
    node=node[key];
  }
}
const pub=['active_release','summary','meta','backtests','rebound_feed','kline/2330','releases/test/summary','releases/test/meta','releases/test/backtests','releases/test/rebound_feed','releases/test/kline/2330','intraday_live','intraday_picks','premarket_brief','daytrade_learning_status','history_training_status','dual_review_status','public_feed'];
pub.push('provider_health','premarket_status');
const A={uid:'uidA'},B={uid:'uidB'};
// Public market data unchanged: readable anonymously and by signed-in users.
for(const p of pub){assert(allows('market_data/'+p,'.read'),p);assert(allows('market_data/'+p,'.read',A),p);}
for(const p of ['','market_data','market_data/releases','market_data/releases/test','market_data/line_groups','market_data/history','market_data/selection_history','market_data/overnight_history','market_data/daytrade_research','market_data/intraday_archive','market_data/provider_evidence','market_data/provider_evidence/fugle','market_data/unknown','users'])assert(!allows(p,'.read'),p);
// Root must stay closed: an open root (".read": true) would cascade into users/{uid}.
assert.equal(rules['.read'],false);assert.equal(rules['.write'],false);
// T30: user isolation.
assert(!allows('users/uidA','.read'),'anonymous cannot read a user');
assert(!allows('users/uidA/watchlist/2330','.read'),'anonymous cannot read a user child');
assert(!allows('users/uidA','.write'),'anonymous cannot write a user');
assert(allows('users/uidA','.read',A),'A reads own');
assert(allows('users/uidA/watchlist/2330','.write',A),'A writes own');
assert(!allows('users/uidB','.read',A),'A cannot read B');
assert(!allows('users/uidB/settings/darkMode','.read',A),'A cannot read B child');
assert(!allows('users/uidB','.write',A),'A cannot write B');
assert(!allows('users','.read',A),'no listing of all users');
assert(!allows('users','.write',A),'no write to the users root');
// T31: signed-in users cannot touch market data, admin or broker paths.
for(const p of ['','market_data','market_data/public_feed','market_data/intraday_live','market_data/summary','admin','live_broker','broker','vm_runtime','market_data/paper_ledger']){
  assert(!allows(p,'.write',A),'write '+p);
  assert(!allows(p,'.write'),'anon write '+p);
}
for(const p of ['admin','live_broker','broker','vm_runtime'])assert(!allows(p,'.read',A),'read '+p);
// Only the owner expression may grant writes; everything else stays false.
function check(node,trail){for(const [k,v] of Object.entries(node)){
  if(k==='.write'){if(trail.join('/')==='users/$uid')assert.equal(v,OWNER_RULE);else assert.equal(v,false,trail.join('/'));}
  else if(k==='.read'&&typeof v==='string')assert.equal(trail.join('/'),'users/$uid');
  else if(v&&typeof v==='object')check(v,[...trail,k]);}}
check(rules,[]);
// Unknown top-level keys under a user are rejected by validation; known sections are validated.
const u=rules.users.$uid;
assert.equal(u.$other['.validate'],false);
for(const k of ['profile','watchlist','alerts','settings','groups'])assert(u[k],k);
assert.match(u.watchlist.$symbol['.validate'],/\$symbol\.matches/);
console.log('PASS Firebase policy (simulation): public market data readable, users/{uid} owner-only, no client writes elsewhere, root closed');
