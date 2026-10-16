// T34: the 2.0 toolbar icons decode, have the declared sizes, and are monochrome (no red / gradient colour).
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { inflateSync } from 'node:zlib';

function decodePng(buf) {
  assert.equal(buf.subarray(0, 8).toString('hex'), '89504e470d0a1a0a');
  let pos = 8, width = 0, height = 0, depth = 0, colorType = 0;
  const idat = [];
  while (pos < buf.length) {
    const len = buf.readUInt32BE(pos), type = buf.subarray(pos + 4, pos + 8).toString();
    const data = buf.subarray(pos + 8, pos + 8 + len);
    if (type === 'IHDR') { width = data.readUInt32BE(0); height = data.readUInt32BE(4); depth = data[8]; colorType = data[9]; }
    if (type === 'IDAT') idat.push(data);
    pos += 12 + len;
    if (type === 'IEND') break;
  }
  assert.equal(depth, 8); assert.equal(colorType, 6, 'RGBA');
  const raw = inflateSync(Buffer.concat(idat)), bpp = 4, stride = width * bpp;
  const out = Buffer.alloc(height * stride);
  for (let y = 0; y < height; y++) {
    const filter = raw[y * (stride + 1)];
    for (let x = 0; x < stride; x++) {
      const v = raw[y * (stride + 1) + 1 + x];
      const a = x >= bpp ? out[y * stride + x - bpp] : 0;
      const b = y > 0 ? out[(y - 1) * stride + x] : 0;
      const c = x >= bpp && y > 0 ? out[(y - 1) * stride + x - bpp] : 0;
      let pred = 0;
      if (filter === 1) pred = a; else if (filter === 2) pred = b; else if (filter === 3) pred = (a + b) >> 1;
      else if (filter === 4) { const p = a + b - c, pa = Math.abs(p - a), pb = Math.abs(p - b), pc = Math.abs(p - c); pred = pa <= pb && pa <= pc ? a : (pb <= pc ? b : c); }
      out[y * stride + x] = (v + pred) & 255;
    }
  }
  return { width, height, px: (x, y) => [...out.subarray(y * stride + x * 4, y * stride + x * 4 + 4)] };
}

test('T34 icon16/48/128 decode, match their size, monochrome with a light glyph on a dark tile', async () => {
  const manifest = JSON.parse(await readFile(new URL('../manifest.json', import.meta.url), 'utf8'));
  for (const size of [16, 48, 128]) {
    assert.equal(manifest.icons[size], `assets/icon${size}.png`);
    assert.equal(manifest.action.default_icon[size], `assets/icon${size}.png`);
    const img = decodePng(await readFile(new URL(`../assets/icon${size}.png`, import.meta.url)));
    assert.equal(img.width, size); assert.equal(img.height, size);
    let light = 0, dark = 0, maxChroma = 0;
    for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
      const [r, g, b, a] = img.px(x, y);
      if (a < 32) continue;
      maxChroma = Math.max(maxChroma, Math.max(r, g, b) - Math.min(r, g, b));
      const lum = (r + g + b) / 3;
      if (lum > 200) light++; else if (lum < 60) dark++;
    }
    assert.ok(maxChroma <= 16, `icon${size} must be black/white (max chroma ${maxChroma})`);
    assert.ok(light > size * size * 0.05, `icon${size} has a visible glyph`);
    assert.ok(dark > size * size * 0.2, `icon${size} has a dark tile`);
  }
  // 128 px follows the Web Store guidance of transparent padding around ~96 px artwork.
  const big = decodePng(await readFile(new URL('../assets/icon128.png', import.meta.url)));
  assert.equal(big.px(2, 2)[3], 0);
  assert.equal(big.px(125, 125)[3], 0);
});
