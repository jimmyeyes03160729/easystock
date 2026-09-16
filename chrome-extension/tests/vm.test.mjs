import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
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
  const png = await readFile(new URL('assets/icon128.png', root)); assert.equal(png.readUInt32BE(16), 128);
});
