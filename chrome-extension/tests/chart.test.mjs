import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
test('1.05 daily chart unwraps service-worker payload and keeps dated intraday bars', async () => {
  const source = await readFile(new URL('../chart.js', import.meta.url), 'utf8');
  assert.match(source, /const dailyPayload = bgDaily\?\.value \?\? bgDaily/);
  assert.match(source, /buildPartialDailyBar\(rows, session\.date\)/);
  assert.match(source, /timestamp: Number\(ts\)/);
  assert.match(source, /date: dateStr/);
});
