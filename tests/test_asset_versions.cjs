// HTML must request the exact current module bytes, not an old cached script.
const fs=require('node:fs'),crypto=require('node:crypto'),assert=require('node:assert');
const html=fs.readFileSync('index.html','utf8');
for(const file of ['rebound-engine.js','module-share.js','learning-status.js','rebound-ui.js','dashboard-layout.js']){
 const hash=crypto.createHash('sha256').update(fs.readFileSync('assets/'+file,'utf8').replace(/\r\n/g,'\n')).digest('hex').slice(0,12);
 assert(html.includes(`src="assets/${file}?v=${hash}"`),`${file}: update the HTML asset digest after editing the script`);
}
console.log('PASS asset digests: HTML requests the current scripts');
