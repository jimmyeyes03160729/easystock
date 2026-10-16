import { mkdir, readFile, writeFile, copyFile } from 'node:fs/promises';
import { resolve, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { deflateSync } from 'node:zlib';
import { createHash } from 'node:crypto';

const root = fileURLToPath(new URL('.', import.meta.url));
// Supplied brand raster assets are checked in; fallback generation only runs when an asset is missing.
function crc32(bytes) {
  let crc = 0xffffffff;
  for (const byte of bytes) { crc ^= byte; for (let j = 0; j < 8; j++) crc = (crc >>> 1) ^ ((crc & 1) ? 0xedb88320 : 0); }
  return (crc ^ 0xffffffff) >>> 0;
}
function chunk(type, data) {
  const name = Buffer.from(type), size = Buffer.alloc(4), crc = Buffer.alloc(4);
  size.writeUInt32BE(data.length); crc.writeUInt32BE(crc32(Buffer.concat([name, data])));
  return Buffer.concat([size, name, data, crc]);
}
function icon(size) {
  const pixels = Buffer.alloc(size * (size * 4 + 1));
  const line = [[0.18, 0.72], [0.38, 0.50], [0.55, 0.59], [0.81, 0.25]];
  function distance(x, y, a, b) {
    const dx = b[0] - a[0], dy = b[1] - a[1];
    const t = Math.max(0, Math.min(1, ((x - a[0]) * dx + (y - a[1]) * dy) / (dx * dx + dy * dy)));
    return Math.hypot(x - a[0] - t * dx, y - a[1] - t * dy);
  }
  for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
    const on = line.slice(1).some((b, i) => distance(x / size, y / size, line[i], b) < 0.035);
    const i = y * (size * 4 + 1) + 1 + x * 4;
    pixels.set(on ? [56, 189, 248, 255] : [15, 23, 42, 255], i);
  }
  const hdr = Buffer.alloc(13); hdr.writeUInt32BE(size); hdr.writeUInt32BE(size, 4); hdr[8] = 8; hdr[9] = 6;
  return Buffer.concat([Buffer.from([137,80,78,71,13,10,26,10]), chunk('IHDR', hdr), chunk('IDAT', deflateSync(pixels)), chunk('IEND', Buffer.alloc(0))]);
}
await mkdir(join(root, 'assets'), { recursive: true });
try {
  await copyFile(join(root, 'node_modules/tailwindcss/LICENSE'), join(root, 'assets/TAILWIND-LICENSE.txt'));
} catch (e) {
  if (!await readFile(join(root, 'assets/TAILWIND-LICENSE.txt')).catch(() => null)) throw e;
}
for (const size of [16, 48, 128]) {
  const iconPath = join(root, `assets/icon${size}.png`);
  const existing = await readFile(iconPath).catch(() => null);
  if (!existing || existing.length === 0) await writeFile(iconPath, icon(size));
}
const files = ['manifest.json', 'popup.html', 'popup.js', 'chart.html', 'chart.js', 'background.js', 'rebound-engine.js', 'content-script.js', 'core.js', 'auth.js', 'sync.js', 'auth-config.json', 'environment.js', 'icons.js', 'config.json', 'github_config_schema.json', 'README.md', 'assets/popup.css', 'assets/v2.css', 'assets/TAILWIND-LICENSE.txt', 'assets/icon16.png', 'assets/icon48.png', 'assets/icon128.png', 'assets/icon.svg'];
// Tolerate a UTF-8 BOM (Windows editors add one when the Owner fills in the client ID).
const authCfg = JSON.parse((await readFile(join(root, 'auth-config.json'), 'utf8')).replace(/^﻿/, ''));
const CLIENT_ID = /^[0-9]+-[a-z0-9]+\.apps\.googleusercontent\.com$/;
for (const mode of ['production', 'vm']) {
  const out = resolve(root, 'dist', mode);
  await mkdir(join(out, 'assets'), { recursive: true });
  for (const file of files) await copyFile(join(root, file), join(out, file));
  if (mode === 'production') {
    // OAuth is injected only with a real Chrome-extension OAuth client ID; otherwise the build stays
    // installable and the popup reports BLOCKED_BY_OAUTH_CONFIGURATION instead of pretending.
    const manifest = JSON.parse(await readFile(join(root, 'manifest.json'), 'utf8'));
    if (CLIENT_ID.test(String(authCfg.oauth_client_id || ''))) {
      manifest.oauth2 = { client_id: authCfg.oauth_client_id, scopes: ['openid', 'email', 'profile'] };
    }
    // Optional: pin an unpacked test build to the Web Store extension ID (the OAuth client is bound to it).
    // Never set for the Web Store upload ZIP (the store rejects a "key" field).
    if (process.env.EASYSTOCK_PIN_KEY === '1' && /^[A-Za-z0-9+/=]{200,}$/.test(String(authCfg.extension_public_key || ''))) manifest.key = authCfg.extension_public_key;
    await writeFile(join(out, 'manifest.json'), JSON.stringify(manifest, null, 2) + '\n');
  }
  if (mode === 'vm') {
    const manifest = JSON.parse(await readFile(join(root, 'manifest.json'), 'utf8'));
    manifest.permissions = manifest.permissions.filter(p => p !== 'identity');
    manifest.name = 'EasyStock VM 隔離測試'; manifest.host_permissions = [];
    await writeFile(join(out, 'manifest.json'), JSON.stringify(manifest, null, 2) + '\n');
    await writeFile(join(out, 'environment.js'), "export const VM_MODE = true;\nexport const CONFIG_URL = '';\nexport const FIREBASE_ROOT = '';\n");
    const cfg = JSON.parse(await readFile(join(root, 'config.json'), 'utf8'));
    cfg.vip_keys_hash = [createHash('sha256').update('VIP888').digest('hex')];
    await writeFile(join(out, 'vm-config.json'), JSON.stringify(cfg, null, 2) + '\n');
  }
}
console.log('Built dist/production and dist/vm. VM build has no network host permissions.');
