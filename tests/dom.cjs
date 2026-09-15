const {JSDOM}=require('jsdom');
const fs=require('node:fs'),path=require('node:path');
const vm=require('node:vm');

function createDOM(html='<section id="learningSection"></section>') {
  const dom=new JSDOM(html,{url:'https://local.invalid/',runScripts:'outside-only'});
  const w=dom.window;
  w.FIREBASE_ROOT='https://local.invalid/market_data';
  w.setInterval=()=>0;
  const run=file=>vm.runInContext(fs.readFileSync(path.join(__dirname,'..',file),'utf8'),dom.getInternalVMContext());
  return {dom,w,run};
}
const settle=()=>new Promise(resolve=>setImmediate(resolve));
module.exports={createDOM,settle};
