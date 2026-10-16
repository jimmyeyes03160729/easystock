// Local-only static server for the Liquid Glass prototype.
// node prototypes/liquid-glass/serve.cjs, then http://127.0.0.1:8767/prototypes/liquid-glass/
const http = require('node:http'), fs = require('node:fs'), path = require('node:path');
const root = path.resolve(__dirname, '..', '..');
const allowed = /^(prototypes\/liquid-glass|assets|icon|chrome-extension\/assets)\//;
const types = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.png': 'image/png', '.svg': 'image/svg+xml', '.json': 'application/json' };
http.createServer((req, res) => {
  const url = new URL(req.url, 'http://127.0.0.1:8767');
  let rel = decodeURIComponent(url.pathname).slice(1);
  if (rel === '' ) { res.writeHead(302, { Location: '/prototypes/liquid-glass/' }); res.end(); return; }
  if (rel.endsWith('/')) rel += 'index.html';
  const file = path.resolve(root, rel);
  if (!allowed.test(rel) || !file.startsWith(root + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) { res.writeHead(404); res.end(); return; }
  res.setHeader('Content-Type', types[path.extname(file)] || 'application/octet-stream');
  res.setHeader('Cache-Control', 'no-store');
  fs.createReadStream(file).pipe(res);
}).listen(8767, '127.0.0.1', () => console.log('Liquid Glass prototype: http://127.0.0.1:8767/prototypes/liquid-glass/'));
