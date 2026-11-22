import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';

const web = fileURLToPath(new URL('../../../js', import.meta.url));

// Modules that need the browser are never imported by these tests, so a syntax error in one would only show in ComfyUI.
test('every web module parses', () => {
  const broken = fs.readdirSync(web).filter(name => /\.m?js$/.test(name)).flatMap(name => {
    const result = spawnSync(process.execPath, ['--check', path.join(web, name)], {encoding: 'utf8'});
    return result.status === 0 ? [] : [`${name}: ${result.stderr.split('\n').slice(0, 3).join(' ')}`];
  });
  assert.deepEqual(broken, []);
});
