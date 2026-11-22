import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {moduleTags, stamp} from '../../../tools/module_versions.mjs';

const root = fileURLToPath(new URL('../../..', import.meta.url));

test('every ?v= tag on an import of a web module is current', () => {
  assert.deepEqual(stamp(root), [], 'run node tools/module_versions.mjs --write');
});

test('the prompt form modules and their importers carry ?v= tags, so a form change reaches cached browsers', () => {
  const unversioned = ['h3c_prompt_form.mjs', 'h3c_prompt_fields.mjs', 'h3c_prompt_shots.mjs', 'h3c_timeline_editor.mjs'].flatMap(name =>
    [...fs.readFileSync(path.join(root, 'js', name), 'utf8').matchAll(/from '(\.\/h3c_[a-z_]+\.mjs)'/g)]
      .map(match => `${name}: ${match[1]}`)
      .filter(line => line.includes('h3c_prompt_')));
  assert.deepEqual(unversioned, []);
});

test('a change below a module changes the tags of every importer, through import cycles', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'h3c-versions-')), web = path.join(dir, 'js');
  const write = (name, text) => fs.writeFileSync(path.join(web, name), text);
  try {
    fs.mkdirSync(web);
    write('entry.js', "import {a} from './a.mjs?v=old';\n");
    write('a.mjs', "import {b} from './b.mjs?v=old';\nimport {c} from './c.mjs?v=old';\nexport const a = b + c;\n");
    write('b.mjs', 'export const b = 1;\n');
    write('c.mjs', "import {a} from './a.mjs?v=old';\nexport const c = () => a;\n");
    write('d.mjs', 'export const d = 1;\n');
    assert.equal(stamp(dir, {write: true}).length, 4);
    assert.deepEqual(stamp(dir), []);

    const before = moduleTags(web);
    write('b.mjs', 'export const b = 2;\n');
    const after = moduleTags(web);
    const changed = ['entry.js', 'a.mjs', 'b.mjs', 'c.mjs', 'd.mjs'].filter(name => before.get(path.join(web, name)) !== after.get(path.join(web, name)));
    assert.deepEqual(changed, ['entry.js', 'a.mjs', 'b.mjs', 'c.mjs']);
    assert.deepEqual(stamp(dir, {write: true}).map(line => line.split(' ')[0] + line.split(' ')[1].split('?')[0]),
      ['js/a.mjs:./b.mjs', 'js/a.mjs:./c.mjs', 'js/c.mjs:./a.mjs', 'js/entry.js:./a.mjs']);

    write('b.mjs', 'export const b = 2;\r\n');
    assert.deepEqual(moduleTags(web), after);
  } finally {
    fs.rmSync(dir, {recursive: true, force: true});
  }
});
