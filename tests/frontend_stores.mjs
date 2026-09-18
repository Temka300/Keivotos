// Run with Node and the frontend's existing Vite dependency. No new dependency.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { build } from '../frontend/node_modules/vite/dist/node/index.js';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const frontend = path.join(root, 'frontend');
const facadePath = path.join(frontend, 'src/lib/stores.ts');
const facade = await fs.readFile(facadePath, 'utf8');
const names = [], imports = [];
for (const match of facade.matchAll(/export \{([^}]+)\} from '([^']+)';/g)) {
  const members = match[1].split(',').map(x => x.trim());
  names.push(...members);
  const owner = path.resolve(path.dirname(facadePath), match[2] + '.ts');
  imports.push(`import { ${members.map(n => `${n} as direct_${n}`).join(', ')} } from ${JSON.stringify(owner)};`);
}
const input = path.join(frontend, '__store_contract__.ts');
const code = `${imports.join('\n')}
import { ${names.join(', ')} } from ${JSON.stringify(facadePath)};
import { suiteDataApi as api } from ${JSON.stringify(path.join(frontend, 'src/lib/suiteDataApi.ts'))};
export { api };
export const compatibility = { ${names.join(', ')} };
export const owners = { ${names.map(n => `${n}: direct_${n}`).join(', ')} };`;
const result = await build({ root: frontend, configFile: false, logLevel: 'silent',
  plugins: [{ name: 'store-contract', resolveId: id => id === input ? id : null, load: id => id === input ? code : null }],
  build: { write: false, minify: false, lib: { entry: input, formats: ['es'] } },
});
const output = (Array.isArray(result) ? result[0] : result).output.find(item => item.type === 'chunk');
const temporary = await fs.mkdtemp(path.join(os.tmpdir(), 'keivotos-store-contract-'));
const values = new Map(Object.entries({
  'danbooru:image-size': JSON.stringify('huge'),
  'danbooru:profile-name': JSON.stringify('Legacy Curator'),
  'keivotos:files-grid-size': JSON.stringify('invalid'),
  'keivotos:sidebar-handle-position': JSON.stringify(63.9315),
  'keivotos:active-rating': JSON.stringify(['e', 'g']),
  'keivotos:media-autoplay': 'false',
  'keivotos:startup-view': JSON.stringify('last'),
  'keivotos:last-view': JSON.stringify('tags'),
  'keivotos:interface-scale': '{broken',
}));
const writes = [];
globalThis.localStorage = {
  get length() { return values.size; }, key: i => [...values.keys()][i] ?? null,
  getItem: key => values.get(key) ?? null,
  setItem: (key, value) => { writes.push(key); values.set(key, value); },
  removeItem: key => values.delete(key),
};
globalThis.fetch = () => { throw Error('Store imports must not start network work'); };
const get = store => { let value; const unsubscribe = store.subscribe(v => { value = v; }); unsubscribe(); return value; };
try {
  const bundle = path.join(temporary, 'stores.mjs');
  await fs.writeFile(bundle, output.code);
  const { compatibility: c, owners: o, api } = await import(pathToFileURL(bundle).href);
  for (const name of names) assert.strictEqual(c[name], o[name], name + ' must be the same object');
  for (const key of new Set(writes)) {
    assert.equal(writes.filter(x => x === key).length, key === 'keivotos:image-size' ? 2 : 1,
      key + ' must initialize only once (plus its legacy-key migration)');
  }
  assert.equal(get(c.imageSize), 'huge');
  assert.equal(get(c.filesGridSize), 'medium');
  assert.equal(get(c.sidebarHandlePosition), 63.9);
  assert.equal(get(c.activeRating), 'g,e');
  assert.equal(get(c.mediaPlayback), 'hover');
  assert.equal(get(c.interfaceScale), 'default');
  assert.equal(get(c.viewMode), 'tags');
  c.viewMode.set('collection-detail');
  assert.equal(JSON.parse(values.get('keivotos:last-view')), 'collections');
  c.filesGridSize.set('absurd');
  assert.equal(get(c.imageSize), 'huge');
  c.activeTags.set(['landscape', 'sky']);
  assert.equal(get(c.searchString), 'landscape sky');
  c.imageRefreshToken.update(n => n + 1);
  assert.equal(get(o.imageRefreshToken), 1);
  assert.deepEqual(c.ratingSelectionValues('eg'), ['g', 'e']);
  assert.equal(c.toggleRatingSelection('g,e', 'e'), 'g');
  assert.deepEqual([128, 300, 301, 600, 601].map(c.thumbnailTierFor), [300, 300, 600, 600, 1200]);
  let reads = 0, saves = [];
  api.getUserSetting = async () => { reads++; return { value: 'Keivotos' }; };
  api.putUserSetting = async (key, value) => { saves.push([key, value]); return { value }; };
  assert.deepEqual(await Promise.all([c.profileName.load(), o.profileName.load()]), ['Legacy Curator', 'Legacy Curator']);
  assert.equal(reads, 1);
  assert.deepEqual(saves, [['profile_name', 'Legacy Curator']]);
  assert.equal(values.has('keivotos:profile-name'), false);
  api.putUserSetting = async () => { throw Error('fixture failure'); };
  await assert.rejects(c.profileName.set('Unsaved'), /fixture failure/);
  assert.equal(get(o.profileName), 'Legacy Curator');
  assert.equal(values.get('danbooru:profile-name'), JSON.stringify('Legacy Curator'));
  for (const [owner, expected] of [
    ['filesStores', ['keivotos:files-grid-size']],
    ['suiteStores', ['keivotos:startup-module', 'keivotos:active-module', 'keivotos:motion-preference', 'keivotos:interface-scale']],
  ]) {
    const built = await build({ root: frontend, configFile: false, logLevel: 'silent',
      build: { write: false, minify: false, lib: { entry: path.join(frontend, 'src/lib', owner + '.ts'), formats: ['es'] } },
    });
    const chunk = (Array.isArray(built) ? built[0] : built).output.find(item => item.type === 'chunk');
    const target = path.join(temporary, owner + '.mjs');
    await fs.writeFile(target, chunk.code);
    values.clear(); writes.length = 0;
    await import(pathToFileURL(target).href);
    assert.deepEqual(writes.sort(), expected.sort(), owner + ' must not initialize Danbooru state');
  }
  console.log(`PASS: ${names.length} identical exports; single initialization, legacy keys, normalization, derived state and profile rollback`);
} finally {
  await fs.rm(temporary, { recursive: true, force: true });
  delete globalThis.localStorage;
}
