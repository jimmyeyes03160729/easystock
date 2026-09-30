import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { inflateSync } from 'node:zlib';
import { sha256 } from '../core.js';
test('packaged VM has no host access, public test key only, all assets present', async () => {
  const root = new URL('../dist/vm/', import.meta.url);
  const m = JSON.parse(await readFile(new URL('manifest.json', root)));
  assert.deepEqual(m.host_permissions, []);
  const env = await readFile(new URL('environment.js', root), 'utf8');
  assert.match(env, /VM_MODE = true/); assert.doesNotMatch(env, /https?:/);
  const cfg = JSON.parse(await readFile(new URL('vm-config.json', root)));
  assert.equal(cfg.vip_keys_hash.includes(await sha256('VIP888')), true);
  for (const path of [m.background.service_worker, m.action.default_popup, ...Object.values(m.icons), 'assets/popup.css', 'core.js', 'icons.js']) assert.ok((await readFile(new URL(path, root))).length > 0);
  function crc32(buf) {
    let crc = 0xffffffff;
    for (const byte of buf) {
      crc ^= byte;
      for (let i = 0; i < 8; i++) crc = (crc >>> 1) ^ ((crc & 1) ? 0xedb88320 : 0);
    }
    return (crc ^ 0xffffffff) >>> 0;
  }
  function validateRgbaPng(png, expectedSize) {
    assert.equal(png.subarray(0, 8).toString('hex'), '89504e470d0a1a0a');
    let pos = 8, width = 0, height = 0, colorType = -1;
    const idat = [];
    while (pos + 12 <= png.length) {
      const len = png.readUInt32BE(pos);
      const type = png.subarray(pos + 4, pos + 8);
      const data = png.subarray(pos + 8, pos + 8 + len);
      const storedCrc = png.readUInt32BE(pos + 8 + len);
      assert.equal(crc32(Buffer.concat([type, data])), storedCrc, `bad PNG CRC in ${type.toString()}`);
      if (type.toString() === 'IHDR') {
        width = data.readUInt32BE(0); height = data.readUInt32BE(4);
        assert.equal(data[8], 8); colorType = data[9];
      } else if (type.toString() === 'IDAT') idat.push(data);
      pos += 12 + len;
      if (type.toString() === 'IEND') break;
    }
    assert.equal(width, expectedSize); assert.equal(height, expectedSize);
    assert.equal(colorType, 6, 'icon must be RGBA PNG with alpha');
    const raw = inflateSync(Buffer.concat(idat));
    assert.equal(raw.length, height * (1 + width * 4));
  }
  for (const size of [16, 48, 128]) {
    const png = await readFile(new URL(`assets/icon${size}.png`, root));
    validateRgbaPng(png, size);
  }
});
