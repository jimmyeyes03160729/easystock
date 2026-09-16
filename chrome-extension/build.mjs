import { mkdir, readFile, writeFile, copyFile } from 'node:fs/promises';
import { resolve, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { deflateSync } from 'node:zlib';
import { createHash } from 'node:crypto';

const root = fileURLToPath(new URL('.', import.meta.url));
// Deterministic self-authored raster icon, no external asset licensing/network.
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
await copyFile(join(root, 'node_modules/tailwindcss/LICENSE'), join(root, 'assets/TAILWIND-LICENSE.txt'));
for (const size of [16, 48, 128]) await writeFile(join(root, `assets/icon${size}.png`), icon(size));
const files = ['manifest.json', 'popup.html', 'popup.js', 'background.js', 'core.js', 'environment.js', 'icons.js', 'config.json', 'github_config_schema.json', 'README.md', 'assets/popup.css', 'assets/TAILWIND-LICENSE.txt', 'assets/icon16.png', 'assets/icon48.png', 'assets/icon128.png'];
for (const mode of ['production', 'vm']) {
  const out = resolve(root, 'dist', mode);
  await mkdir(join(out, 'assets'), { recursive: true });
  for (const file of files) await copyFile(join(root, file), join(out, file));
  if (mode === 'vm') {
    const manifest = JSON.parse(await readFile(join(root, 'manifest.json'), 'utf8'));
    manifest.name = 'EasyStock VM 隔離測試'; manifest.host_permissions = [];
    await writeFile(join(out, 'manifest.json'), JSON.stringify(manifest, null, 2) + '\n');
    await writeFile(join(out, 'environment.js'), "export const VM_MODE = true;\nexport const CONFIG_URL = '';\nexport const FIREBASE_ROOT = '';\n");
    const cfg = JSON.parse(await readFile(join(root, 'config.json'), 'utf8'));
    cfg.vip_keys_hash = [createHash('sha256').update('VIP888').digest('hex')];
    await writeFile(join(out, 'vm-config.json'), JSON.stringify(cfg, null, 2) + '\n');
  }
}
console.log('Built dist/production and dist/vm. VM build has no network host permissions.');
