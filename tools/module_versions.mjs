// Stamps every import of a js/ module with ?v=<tag>, where the tag hashes that module and every module it imports,
// directly or not. ComfyUI sends Cache-Control only for .js files, so a browser may keep a cached .mjs until its URL
// changes: a change anywhere below a module has to change its tag and the tags of all its importers.
// Vendored: upstream scanned web/; the modules now live in js/ next to this pack's own widgets.
// Usage: node tools/module_versions.mjs            lists stale tags (exit 1 if any)
//        node tools/module_versions.mjs --write    rewrites them
import {createHash} from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const SPECIFIER = /(['"])(\.\.?\/[^'"?\s]+\.m?js)\?v=([\w.-]*)\1/g;

function scripts(folder) {
  if (!fs.existsSync(folder)) return [];
  return fs.readdirSync(folder, {withFileTypes: true}).sort((a, b) => a.name < b.name ? -1 : 1).flatMap(entry => {
    const file = path.join(folder, entry.name);
    if (entry.isDirectory()) return entry.name === 'node_modules' ? [] : scripts(file);
    return /\.m?js$/.test(entry.name) ? [file] : [];
  });
}

// Tag of every script in `web`, by path. Line endings and the ?v= tags themselves are left out of the hash, so a
// checkout with other line endings gets the same tags and stamping never changes a tag.
export function moduleTags(web) {  // `web` is the module dir (js/ in this repo)
  const plain = new Map(), deps = new Map();
  for (const file of scripts(web)) {
    const text = fs.readFileSync(file, 'utf8').replace(/\r\n/g, '\n');
    plain.set(file, text.replace(SPECIFIER, '$1$2$1'));
    deps.set(file, [...text.matchAll(SPECIFIER)].map(match => path.resolve(path.dirname(file), match[2])));
  }
  const tags = new Map();
  for (const file of plain.keys()) {
    const closure = new Set([file]);
    for (const member of closure) for (const dep of deps.get(member)) if (plain.has(dep)) closure.add(dep);
    const named = [...closure].map(member => [path.relative(web, member).split(path.sep).join('/'), member]).sort(([a], [b]) => a < b ? -1 : 1);
    const hash = createHash('sha256');
    for (const [name, member] of named) hash.update(`${name}\0${plain.get(member)}\0`);
    tags.set(file, hash.digest('hex').slice(0, 12));
  }
  return tags;
}

// Imports in js/ and tests/ whose ?v= tag is not the imported module's tag; `write` fixes them in place.
export function stamp(root, {write = false} = {}) {
  root = path.resolve(root);
  const web = path.join(root, 'js'), tags = moduleTags(web), stale = [];
  for (const file of [...scripts(web), ...scripts(path.join(root, 'tests'))]) {
    const text = fs.readFileSync(file, 'utf8');
    const next = text.replace(SPECIFIER, (match, quote, specifier, tag) => {
      const want = tags.get(path.resolve(path.dirname(file), specifier));
      if (!want || want === tag) return match;
      stale.push(`${path.relative(root, file).split(path.sep).join('/')}: ${specifier}?v=${tag} -> ${want}`);
      return `${quote}${specifier}?v=${want}${quote}`;
    });
    if (write && next !== text) fs.writeFileSync(file, next);
  }
  return stale;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const write = process.argv.includes('--write');
  const stale = stamp(fileURLToPath(new URL('../..', import.meta.url)), {write});
  if (!stale.length) console.log('Every ?v= tag is current.');
  else console.log(`${write ? 'Stamped' : 'Stale'} ${stale.length} import tags:\n${stale.join('\n')}`);
  if (stale.length && !write) {
    console.log('Run node tools/module_versions.mjs --write');
    process.exitCode = 1;
  }
}
