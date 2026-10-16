// Packages dist/production into a Chrome Web Store upload ZIP and validates it.
// Pure Node (no zip binary): DEFLATE entries, CRC32, central directory; then re-reads and checks the archive.
import { readFile, readdir, writeFile, stat } from 'node:fs/promises';
import { join, relative, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { deflateRawSync, inflateRawSync } from 'node:zlib';
import { createHash } from 'node:crypto';

const root = fileURLToPath(new URL('.', import.meta.url));
const dist = join(root, 'dist', 'production');
const manifest = JSON.parse(await readFile(join(dist, 'manifest.json'), 'utf8'));
const out = join(root, '..', `easystock-chrome-extension-v${manifest.version}.zip`);

const CRC_TABLE = Array.from({ length: 256 }, (_, n) => { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; return c >>> 0; });
const crc32 = buf => { let c = 0xffffffff; for (const b of buf) c = CRC_TABLE[(c ^ b) & 255] ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0; };

async function walk(dir) {
  const files = [];
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) files.push(...await walk(full)); else files.push(full);
  }
  return files.sort();
}

export function validatePackage(names, manifestJson) {
  const errors = [];
  const required = ['manifest.json', manifestJson.background?.service_worker, manifestJson.action?.default_popup, ...Object.values(manifestJson.icons || {}), 'auth.js', 'sync.js', 'core.js', 'assets/v2.css', 'assets/popup.css'];
  for (const r of required) if (!names.includes(r)) errors.push(`missing ${r}`);
  for (const n of names) {
    if (/(^|\/)(tests?|node_modules|\.git)\//.test(n) || /\.(test\.mjs|map|ps1|zip)$/.test(n) || ['vm-config.json', 'rebound-engine.js'].includes(n)) errors.push(`unexpected file ${n}`);
  }
  if (manifestJson.manifest_version !== 3) errors.push('manifest_version must be 3');
  if ('key' in manifestJson) errors.push('Web Store upload must not contain "key"');
  if (!/script-src 'self'/.test(manifestJson.content_security_policy?.extension_pages || '') || /unsafe-eval|https?:/.test(manifestJson.content_security_policy?.extension_pages || '')) errors.push('CSP must stay script-src self only');
  return errors;
}

const files = await walk(dist);
const entries = [];
const chunks = [];
let offset = 0;
const dosTime = 0, dosDate = (2026 - 1980) << 9 | 10 << 5 | 16; // fixed timestamp → reproducible ZIP
for (const file of files) {
  const name = relative(dist, file).split(sep).join('/');
  const data = await readFile(file);
  const compressed = deflateRawSync(data, { level: 9 });
  const crc = crc32(data);
  const nameBuf = Buffer.from(name, 'utf8');
  const local = Buffer.alloc(30);
  local.writeUInt32LE(0x04034b50, 0); local.writeUInt16LE(20, 4); local.writeUInt16LE(0x0800, 6); local.writeUInt16LE(8, 8);
  local.writeUInt16LE(dosTime, 10); local.writeUInt16LE(dosDate, 12); local.writeUInt32LE(crc, 14);
  local.writeUInt32LE(compressed.length, 18); local.writeUInt32LE(data.length, 22); local.writeUInt16LE(nameBuf.length, 26); local.writeUInt16LE(0, 28);
  chunks.push(local, nameBuf, compressed);
  entries.push({ name, nameBuf, crc, size: data.length, csize: compressed.length, offset });
  offset += local.length + nameBuf.length + compressed.length;
}
const central = [];
for (const e of entries) {
  const h = Buffer.alloc(46);
  h.writeUInt32LE(0x02014b50, 0); h.writeUInt16LE(20, 4); h.writeUInt16LE(20, 6); h.writeUInt16LE(0x0800, 8); h.writeUInt16LE(8, 10);
  h.writeUInt16LE(dosTime, 12); h.writeUInt16LE(dosDate, 14); h.writeUInt32LE(e.crc, 16); h.writeUInt32LE(e.csize, 20); h.writeUInt32LE(e.size, 24);
  h.writeUInt16LE(e.nameBuf.length, 28); h.writeUInt32LE(e.offset, 42);
  central.push(h, e.nameBuf);
}
const centralBuf = Buffer.concat(central);
const end = Buffer.alloc(22);
end.writeUInt32LE(0x06054b50, 0); end.writeUInt16LE(entries.length, 8); end.writeUInt16LE(entries.length, 10);
end.writeUInt32LE(centralBuf.length, 12); end.writeUInt32LE(offset, 16);
const zip = Buffer.concat([...chunks, centralBuf, end]);
await writeFile(out, zip);

// Re-read and verify every entry (CRC + size), then validate content rules.
const names = [];
let p = zip.readUInt32LE(zip.length - 22 + 16);
for (let i = 0; i < zip.readUInt16LE(zip.length - 22 + 10); i++) {
  const nameLen = zip.readUInt16LE(p + 28), localOff = zip.readUInt32LE(p + 42), crc = zip.readUInt32LE(p + 16), size = zip.readUInt32LE(p + 24), csize = zip.readUInt32LE(p + 20);
  const name = zip.subarray(p + 46, p + 46 + nameLen).toString('utf8');
  const lNameLen = zip.readUInt16LE(localOff + 26), lExtra = zip.readUInt16LE(localOff + 28);
  const data = inflateRawSync(zip.subarray(localOff + 30 + lNameLen + lExtra, localOff + 30 + lNameLen + lExtra + csize));
  if (data.length !== size || crc32(data) !== crc) throw new Error(`ZIP entry corrupt: ${name}`);
  names.push(name);
  p += 46 + nameLen;
}
const zipManifest = JSON.parse(inflateRawSync(zip.subarray(entries.find(e => e.name === 'manifest.json').offset + 30 + 'manifest.json'.length, entries.find(e => e.name === 'manifest.json').offset + 30 + 'manifest.json'.length + entries.find(e => e.name === 'manifest.json').csize)).toString('utf8'));
const errors = validatePackage(names, zipManifest);
if (errors.length) throw new Error(`Package validation failed:\n- ${errors.join('\n- ')}`);
const sha = createHash('sha256').update(zip).digest('hex');
await writeFile(join(root, 'dist', `${out.split(/[\\/]/).pop()}.sha256`), `${sha}  ${out.split(/[\\/]/).pop()}\n`);
console.log(JSON.stringify({ zip: out, bytes: (await stat(out)).size, files: names.length, version: zipManifest.version, version_name: zipManifest.version_name, oauth2: zipManifest.oauth2 ? 'configured' : 'not configured (BLOCKED_BY_OAUTH_CONFIGURATION)', sha256: sha }, null, 2));
