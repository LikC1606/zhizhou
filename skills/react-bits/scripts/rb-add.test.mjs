import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

test('list includes supported UI variants and omits JS/TS-only Sound assets', () => {
  const registry = { items: [
    { name: 'BlurText-TS-TW', title: 'BlurText' },
    { name: 'BlurText-JS-CSS', title: 'BlurText' },
    { name: 'FlyingButton-TS-TW', title: 'FlyingButton' },
    { name: 'SoundClick-JS', title: 'SoundClick' },
    { name: 'SoundClick-TS', title: 'SoundClick' },
  ] };
  const mock = `globalThis.fetch = async () => ({ ok: true, status: 200, text: async () => ${JSON.stringify(JSON.stringify(registry))} });`;
  const result = spawnSync(process.execPath, [
    '--import', `data:text/javascript,${encodeURIComponent(mock)}`,
    fileURLToPath(new URL('./rb-add.mjs', import.meta.url)), '--list',
  ], { encoding: 'utf8', timeout: 10000 });
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.stdout.trim(), 'BlurText\nFlyingButton\n\n2 components');
});
