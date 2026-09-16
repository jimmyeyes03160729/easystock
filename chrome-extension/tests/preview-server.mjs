// UI-only fixture. No native Chrome API or real trading/notification side effects.
import http from 'node:http';
import { readFile } from 'node:fs/promises';
const allowed = new Set(['popup.html', 'popup.js', 'core.js', 'icons.js', 'assets/popup.css', 'tests/preview-api.js']);
const root = new URL('../', import.meta.url);
http.createServer(async (req, res) => {
  const path = new URL(req.url, 'http://127.0.0.1').pathname.slice(1) || 'popup.html';
  if (!allowed.has(path)) { res.writeHead(404); res.end(); return; }
  try {
    let body = await readFile(new URL(path, root), 'utf8');
    if (path === 'popup.html') body = body.replace('<script type="module" src="popup.js">', '<script src="tests/preview-api.js"></script><script type="module" src="popup.js">');
    res.writeHead(200, { 'Content-Type': path.endsWith('.html') ? 'text/html; charset=utf-8' : path.endsWith('.css') ? 'text/css' : 'text/javascript', 'Cache-Control': 'no-store' }); res.end(body);
  } catch { res.writeHead(500); res.end(); }
}).listen(8765, '127.0.0.1', () => console.log('UI-only fixture: http://127.0.0.1:8765/popup.html'));
