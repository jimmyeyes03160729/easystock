// Screenshots + audits for the Liquid Glass review, via headless Chrome DevTools Protocol.
// Needs both local servers running:
//   node tests/preview_dashboard.cjs              (before: current main, synthetic data, :8766)
//   node prototypes/liquid-glass/serve.cjs        (after: prototype, :8767)
// Then: node prototypes/liquid-glass/capture.cjs
const { spawn } = require('node:child_process');
const fs = require('node:fs'), path = require('node:path'), os = require('node:os');

const CHROME = process.env.CHROME || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const OUT = path.join(__dirname, 'screenshots');
const PORT = 9333;
const BEFORE = 'http://127.0.0.1:8766/';
const AFTER = 'http://127.0.0.1:8767/prototypes/liquid-glass/';
const VIEWPORTS = {
  desktop: { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false },
  mobile: { width: 390, height: 844, deviceScaleFactor: 2, mobile: true },
  narrow: { width: 320, height: 640, deviceScaleFactor: 2, mobile: true },
};
const sleep = ms => new Promise(r => setTimeout(r, ms));

// Runs inside the page. Text contrast is measured against the composited
// background-color chain (glass rgba over the canvas color). Gradient-image
// backgrounds cannot be resolved this way and are counted as "manual".
const AUDIT = `(() => {
  const parse = c => {
    if (!c) return null;
    let m = c.match(/^rgba?\\(([^)]+)\\)/);
    if (m) { const p = m[1].split(/[\\s,\\/]+/).filter(Boolean).map(Number); return { r: p[0], g: p[1], b: p[2], a: p[3] ?? 1 }; }
    m = c.match(/^color\\(srgb ([^)]+)\\)/);
    if (m) { const p = m[1].split(/[\\s\\/]+/).filter(Boolean).map(Number); return { r: p[0] * 255, g: p[1] * 255, b: p[2] * 255, a: p[3] ?? 1 }; }
    return null;
  };
  const over = (t, b) => { const a = t.a + b.a * (1 - t.a); return { r: (t.r * t.a + b.r * b.a * (1 - t.a)) / a, g: (t.g * t.a + b.g * b.a * (1 - t.a)) / a, b: (t.b * t.a + b.b * b.a * (1 - t.a)) / a, a }; };
  const lum = c => { const f = v => { v /= 255; return v <= .03928 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4; }; return .2126 * f(c.r) + .7152 * f(c.g) + .0722 * f(c.b); };
  const ratio = (x, y) => { const a = lum(x), b = lum(y); return (Math.max(a, b) + .05) / (Math.min(a, b) + .05); };
  const hex = c => '#' + [c.r, c.g, c.b].map(v => Math.round(v).toString(16).padStart(2, '0')).join('');
  let canvas = parse(getComputedStyle(document.documentElement).backgroundColor);
  if (!canvas || canvas.a === 0) canvas = parse(getComputedStyle(document.body).backgroundColor);
  if (!canvas || canvas.a === 0) canvas = { r: 255, g: 255, b: 255, a: 1 };
  canvas = over(canvas, { r: 255, g: 255, b: 255, a: 1 });
  const visible = el => { const r = el.getBoundingClientRect(); if (!r.width || !r.height) return false; for (let n = el; n; n = n.parentElement) { const s = getComputedStyle(n); if (s.display === 'none' || s.visibility === 'hidden' || n.hidden) return false; } return true; };
  const results = []; let manual = 0;
  for (const el of document.body.querySelectorAll('*')) {
    if (el.closest('.material-symbols-outlined,svg,script,style,noscript,iframe,[aria-hidden="true"]')) continue;
    const own = [...el.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent.trim()).join(' ').trim();
    if (!own || !visible(el)) continue;
    const chain = []; for (let n = el; n && n !== document.documentElement; n = n.parentElement) chain.push(n);
    if (chain.some(n => n !== document.body && /gradient|url\\(/.test(getComputedStyle(n).backgroundImage))) { manual++; continue; }
    let bg = canvas;
    for (const n of chain.reverse()) { const b = parse(getComputedStyle(n).backgroundColor); if (b && b.a > 0) bg = over(b, bg); }
    const s = getComputedStyle(el); let fg = parse(s.color); if (!fg) continue;
    if (fg.a < 1) fg = over(fg, bg);
    const size = parseFloat(s.fontSize), weight = +s.fontWeight || 400;
    const large = size >= 24 || (size >= 18.66 && weight >= 700);
    const r = ratio(fg, bg);
    results.push({ text: own.slice(0, 28), ratio: +r.toFixed(2), fg: hex(fg), bg: hex(bg), size, need: large ? 3 : 4.5 });
  }
  const fails = results.filter(x => x.ratio < x.need).sort((a, b) => a.ratio - b.ratio);
  const vw = innerWidth;
  const offenders = [...document.body.querySelectorAll('*')].filter(el => {
    if (!visible(el)) return false;
    for (let n = el.parentElement; n; n = n.parentElement) { const o = getComputedStyle(n).overflowX; if (o === 'auto' || o === 'scroll' || o === 'hidden') return false; }
    return el.getBoundingClientRect().right > vw + 1;
  }).slice(0, 10).map(el => el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + (el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\\s+/).slice(0, 2).join('.') : ''));
  const blurred = [...document.querySelectorAll('*')].filter(el => { const s = getComputedStyle(el); const f = s.backdropFilter || s.webkitBackdropFilter; return f && f !== 'none' && visible(el); });
  return {
    theme: document.documentElement.dataset.theme, viewport: vw,
    textChecked: results.length, manualGradient: manual,
    minRatio: results.length ? Math.min(...results.map(x => x.ratio)) : null,
    contrastFailures: fails.length, worst: fails.slice(0, 12),
    scrollWidth: document.documentElement.scrollWidth, horizontalOverflow: document.documentElement.scrollWidth > vw, overflowOffenders: offenders,
    backdropFilterLayers: blurred.length, backdropFilterTargets: blurred.map(el => el.tagName.toLowerCase() + '.' + String(el.className).split(/\\s+/)[0]).slice(0, 30),
  };
})()`;

async function main() {
  fs.mkdirSync(OUT, { recursive: true });
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'lg-capture-'));
  const proc = spawn(CHROME, ['--headless=new', `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`, '--hide-scrollbars', '--no-first-run', '--no-default-browser-check', '--force-color-profile=srgb', 'about:blank'], { stdio: 'ignore' });
  let page;
  for (let i = 0; i < 60 && !page; i++) {
    try { page = (await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json()).find(t => t.type === 'page'); } catch (_) {}
    if (!page) await sleep(250);
  }
  if (!page) throw new Error('Chrome DevTools endpoint did not start');
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise(r => ws.addEventListener('open', r, { once: true }));
  let seq = 0; const pending = new Map(), listeners = new Set();
  ws.addEventListener('message', e => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) { const p = pending.get(m.id); pending.delete(m.id); m.error ? p.rej(new Error(m.error.message)) : p.res(m.result); }
    else listeners.forEach(l => l(m));
  });
  const send = (method, params = {}) => new Promise((res, rej) => { const id = ++seq; pending.set(id, { res, rej }); ws.send(JSON.stringify({ id, method, params })); });
  const evaluate = async expression => (await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true })).result.value;
  const navigate = async url => {
    const loaded = new Promise(r => { const l = m => { if (m.method === 'Page.loadEventFired') { listeners.delete(l); r(); } }; listeners.add(l); });
    await send('Page.navigate', { url }); await loaded; await sleep(2200);
  };
  await send('Page.enable'); await send('Runtime.enable');

  const setViewport = async vp => {
    await send('Emulation.setDeviceMetricsOverride', vp);
    await send('Emulation.setTouchEmulationEnabled', vp.mobile ? { enabled: true, maxTouchPoints: 5 } : { enabled: false });
  };
  const shot = async (file, full) => {
    const params = { format: full ? 'jpeg' : 'png', quality: full ? 82 : undefined, captureBeyondViewport: !!full };
    if (full) { const h = await evaluate('document.documentElement.scrollHeight'); const w = await evaluate('innerWidth'); params.clip = { x: 0, y: 0, width: w, height: Math.min(h, 16000), scale: 1 }; }
    const { data } = await send('Page.captureScreenshot', params);
    fs.writeFileSync(path.join(OUT, file), Buffer.from(data, 'base64'));
    console.log('saved', file);
  };
  const open = async (side, theme, query = '') => {
    if (side === 'before') {
      await navigate(BEFORE);
      await evaluate(`localStorage.setItem('MOHREN_THEME', '${theme}')`);
      await navigate(BEFORE);
    } else {
      await navigate(`${AFTER}?theme=${theme}${query}`);
    }
  };

  const audit = {};
  for (const side of ['before', 'after']) for (const theme of ['light', 'dark']) for (const vpName of ['desktop', 'mobile']) {
    await setViewport(VIEWPORTS[vpName]);
    await open(side, theme);
    const tag = `${side}-${vpName}-${theme}`;
    await shot(`${tag}.png`, false);
    await shot(`${tag}-full.jpg`, true);
    audit[tag] = await evaluate(AUDIT);
  }
  // Prototype-only states: details expanded, detail modal, 320px narrow phone.
  for (const theme of ['light', 'dark']) {
    await setViewport(VIEWPORTS.desktop);
    await open('after', theme, '&open=T201');
    await sleep(800);
    await shot(`after-desktop-${theme}-modal.png`, false);
    audit[`after-desktop-${theme}-modal`] = await evaluate(AUDIT);
    await setViewport(VIEWPORTS.mobile);
    await open('after', theme, '&open=T201');
    await sleep(800);
    await shot(`after-mobile-${theme}-modal.png`, false);
    await setViewport(VIEWPORTS.narrow);
    await open('after', theme, '&details=1');
    await shot(`after-narrow320-${theme}-full.jpg`, true);
    audit[`after-narrow320-${theme}`] = await evaluate(AUDIT);
    await open('before', theme);
    audit[`before-narrow320-${theme}`] = await evaluate(AUDIT);
  }
  fs.writeFileSync(path.join(OUT, 'audit.json'), JSON.stringify(audit, null, 2));
  for (const [k, v] of Object.entries(audit)) console.log(k.padEnd(28), `contrast fails ${String(v.contrastFailures).padStart(3)} / ${v.textChecked}  min ${v.minRatio}  overflow ${v.horizontalOverflow}  blur layers ${v.backdropFilterLayers}`);
  ws.close(); proc.kill();
}
main().catch(e => { console.error(e); process.exit(1); });
