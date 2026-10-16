// HTML must request the exact current module bytes, not an old cached script.
const fs=require('node:fs'),crypto=require('node:crypto'),assert=require('node:assert');
const html=fs.readFileSync('index.html','utf8');
const logo='icon/BANNER-376.png';
assert(fs.existsSync(logo),'Optimized logo resource must exist');
const png=fs.readFileSync(logo);
assert(png.length>0 && png.length<250000,'Optimized logo should remain a reasonably sized PNG');
assert(html.includes('src="icon/BANNER-376.png?v=20261003"'),'HTML must cache-bust the optimized logo');
assert(/<img[^>]+BANNER-376\.png[^>]+width="188"[^>]+height="62"[^>]+fetchpriority="high"[^>]+decoding="async"/.test(html),'Logo must reserve layout and decode asynchronously');
assert(!/<img[^>]+BANNER-376\.png[^>]+loading="lazy"/.test(html),'Header logo must not lazy load');
for(const file of ['module-share.js','learning-status.js','dashboard-layout.js','intraday-chart.js','provider-health.js','mobile-nav.js','dashboard-ux.js','revenue-observation.js','eight-methods.js','b-lanes-replay.js','a-watchlist.js','glass-home.js']){
 const hash=crypto.createHash('sha256').update(fs.readFileSync('assets/'+file,'utf8').replace(/\r\n/g,'\n')).digest('hex').slice(0,12);
 assert(html.includes(`src="assets/${file}?v=${hash}"`), `【請將 ${file} 改為】?v=${hash}`);
}
console.log('PASS asset digests: HTML requests the current scripts');
const cssHash=crypto.createHash('sha256').update(fs.readFileSync('assets/dashboard-ux.css','utf8').replace(/\r\n/g,'\n')).digest('hex').slice(0,12);
assert(html.includes(`href="assets/dashboard-ux.css?v=${cssHash}"`),'Dashboard CSS must be versioned by content');
const glassHash=crypto.createHash('sha256').update(fs.readFileSync('assets/liquid-glass.css','utf8').replace(/\r\n/g,'\n')).digest('hex').slice(0,12);
assert(html.includes(`href="assets/liquid-glass.css?v=${glassHash}"`),`【請將 liquid-glass.css 改為】?v=${glassHash}`);
const homeHash=crypto.createHash('sha256').update(fs.readFileSync('assets/glass-home.css','utf8').replace(/\r\n/g,'\n')).digest('hex').slice(0,12);
assert(html.includes(`href="assets/glass-home.css?v=${homeHash}"`),'Approved homepage CSS must be content-versioned');
// Theme tokens must load after the inline legacy styles so equal-specificity rules resolve to the glass layer.
assert(html.indexOf('href="assets/liquid-glass.css')>html.lastIndexOf('</style>',html.indexOf('</head>')),'liquid-glass.css must follow the inline <style>');
