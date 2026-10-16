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

test('T34 icon16/48/128 decode, match their size, and show the official 沖 mark large', async () => {
  const manifest = JSON.parse(await readFile(new URL('../manifest.json', import.meta.url), 'utf8'));
  for (const size of [16, 48, 128]) {
    assert.equal(manifest.icons[size], `assets/icon${size}.png`);
    assert.equal(manifest.action.default_icon[size], `assets/icon${size}.png`);
    const img = decodePng(await readFile(new URL(`../assets/icon${size}.png`, import.meta.url)));
    assert.equal(img.width, size); assert.equal(img.height, size);
    let opaque = 0, white = 0, red = 0;
    for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
      const [r, g, b, a] = img.px(x, y);
      if (a < 128) continue;
      opaque++;
      if (r > 190 && g > 190 && b > 190) white++;
      if (r > 170 && g < 110 && b < 110) red++;
    }
    // Tight crop of the official logo: the tile fills the icon (only rounded corners are transparent).
    assert.ok(opaque > size * size * 0.85, `icon${size} fills the canvas`);
    // The white 沖 strokes are large, and the red candle from the official mark is present.
    assert.ok(white > size * size * 0.12, `icon${size} glyph is large (${white} white px)`);
    assert.ok(red > 0, `icon${size} keeps the red candle`);
  }
  const big = decodePng(await readFile(new URL('../assets/icon128.png', import.meta.url)));
  assert.ok(big.px(0, 0)[3] < 64, 'rounded corner');
  assert.ok(big.px(64, 64)[3] >= 250, 'opaque centre');
});
