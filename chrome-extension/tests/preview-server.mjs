// UI-only fixture. No native Chrome API or real trading/notification side effects.
import http from 'node:http';
import { readFile } from 'node:fs/promises';
const allowed = new Set(['popup.html', 'popup.js', 'core.js', 'icons.js', 'assets/popup.css', 'assets/v2.css', 'assets/icon16.png', 'assets/icon48.png', 'assets/icon128.png', 'tests/preview-api.js']);
const types = { html: 'text/html; charset=utf-8', css: 'text/css', png: 'image/png', js: 'text/javascript' };
const root = new URL('../', import.meta.url);
const port = Number(process.env.PORT || 8765);
http.createServer(async (req, res) => {
  const path = new URL(req.url, 'http://127.0.0.1').pathname.slice(1) || 'popup.html';
  if (!allowed.has(path)) { res.writeHead(404); res.end(); return; }
  try {
    const ext = path.split('.').pop();
    let body = await readFile(new URL(path, root));
    if (path === 'popup.html') body = body.toString('utf8').replace('<script type="module" src="popup.js">', '<script src="tests/preview-api.js"></script><script type="module" src="popup.js">');
    res.writeHead(200, { 'Content-Type': types[ext] || 'application/octet-stream', 'Cache-Control': 'no-store' }); res.end(body);
  } catch { res.writeHead(500); res.end(); }
}).listen(port, '127.0.0.1', () => console.log(`UI-only fixture: http://127.0.0.1:${port}/popup.html`));
