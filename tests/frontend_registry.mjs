// Exercise real Vite contribution discovery in disposable source trees.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { build } from '../frontend/node_modules/vite/dist/node/index.js';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const frontend = path.join(root, 'frontend');
const temporary = await fs.mkdtemp(path.join(os.tmpdir(), 'keivotos-registry-contract-'));
const get = store => { let value; const stop = store.subscribe(v => value = v); stop(); return value; };
globalThis.fetch = () => { throw Error('Registration must not make requests'); };
try {
  for (const mode of ['installed', 'absent', 'additional']) {
    const project = path.join(temporary, mode);
    await fs.mkdir(project);
    await fs.cp(path.join(frontend, 'src'), path.join(project, 'src'), { recursive: true });
    await fs.symlink(path.join(frontend, 'node_modules'), path.join(project, 'node_modules'), 'dir');
    if (mode === 'absent') await fs.rm(path.join(project, 'src/modules/danbooru'), { recursive: true });
    if (mode === 'additional') {
      const extra = path.join(project, 'src/modules/fixture');
      await fs.mkdir(extra);
      await fs.writeFile(path.join(extra, 'ui.ts'), `export default {
        slug: 'fixture', iconSrc: '/fixture.svg', drawerActions: [{ id: 'inspect', label: 'Inspect',
          iconSrc: '/fixture.svg', run: () => globalThis.fixtureAction = true }],
        activate: () => globalThis.fixtureActivated = true,
      };`);
      await fs.writeFile(path.join(extra, 'surface.ts'), "export default { owner: 'fixture' };");
    }
    const entry = path.join(project, 'entry.ts');
    await fs.writeFile(entry, `export { moduleUi, activateModule } from './src/modules/registry';
export { surfaceComponent } from './src/modules/surfaces';
export { activeModule } from './src/lib/suiteStores';
${mode !== 'absent' ? "export { activeCollectionId, selectedImageId, viewMode } from './src/modules/danbooru/stores';" : ''}`);
    const writes = [];
    const values = new Map();
    globalThis.localStorage = { get length() { return values.size; }, key: i => [...values.keys()][i] ?? null,
      getItem: key => values.get(key) ?? null, removeItem: key => values.delete(key),
      setItem: (key, value) => { writes.push(key); values.set(key, value); } };
    const result = await build({ root: project, configFile: false, logLevel: 'silent',
      // Component rendering is covered by the real browser suites. Here a stable
      // constructor stand-in isolates registry discovery from mixed Settings imports.
      plugins: [{ name: 'surface-constructor-fixture', load: id => id.endsWith('.svelte')
        ? `export default { owner: ${JSON.stringify(path.basename(id))} };` : null }],
      build: { write: false, minify: false, lib: { entry, formats: ['es'] } },
    });
    const chunk = (Array.isArray(result) ? result[0] : result).output.find(x => x.type === 'chunk');
    const bundle = path.join(project, 'registry.mjs');
    await fs.writeFile(bundle, chunk.code);
    const registry = await import(pathToFileURL(bundle).href);
    const { moduleUi, surfaceComponent, activateModule, activeModule } = registry;
    assert.equal(moduleUi('files').slug, 'files');
    assert.deepEqual(moduleUi('files').drawerActions, []);
    assert.equal(surfaceComponent('files').owner, 'FilesView.svelte');
    assert.strictEqual(surfaceComponent('unknown'), surfaceComponent('files'));
    assert.deepEqual(moduleUi('unknown'), { slug: 'unknown', iconSrc: null, drawerActions: [] });
    activateModule('files');
    assert.equal(get(activeModule), 'files');
    if (mode === 'absent') {
      assert.equal(moduleUi('danbooru').iconSrc, null);
      assert.deepEqual(moduleUi('danbooru').drawerActions, []);
      assert.strictEqual(surfaceComponent('danbooru'), surfaceComponent('files'));
      assert(!Object.keys(chunk.modules).some(id => id.includes('/danbooru/')));
      assert(!writes.includes('keivotos:image-size'), 'absent module must not initialize stores');
    } else {
      const { activeCollectionId, selectedImageId, viewMode } = registry;
      activeCollectionId.set(123); selectedImageId.set(456); viewMode.set('tags');
      activateModule('danbooru');
      assert.equal(get(activeModule), 'danbooru');
      assert.equal(get(activeCollectionId), null); assert.equal(get(selectedImageId), null);
      assert.equal(get(viewMode), 'home');
      assert.equal(surfaceComponent('danbooru').owner, 'DanbooruSurface.svelte');
      const ui = moduleUi('danbooru');
      assert.equal(ui.iconSrc, '/logo.svg');
      assert.equal(ui.drawerActions.length, 1);
      assert.deepEqual(Object.fromEntries(Object.entries(ui.drawerActions[0]).filter(([key]) => key !== 'run')),
        { id: 'profile', label: 'Profile', iconSrc: '/profile-avatar.svg' });
      activeModule.set('files'); activeCollectionId.set(123); selectedImageId.set(456);
      ui.drawerActions[0].run();
      assert.equal(get(activeModule), 'danbooru'); assert.equal(get(viewMode), 'profile');
      assert.equal(get(activeCollectionId), null); assert.equal(get(selectedImageId), null);
      activateModule('files');
      assert.equal(get(viewMode), 'profile', 'switching to Files preserves module state');
    }
    if (mode === 'additional') {
      assert.equal(surfaceComponent('fixture').owner, 'fixture');
      activateModule('fixture');
      assert.equal(get(activeModule), 'fixture'); assert.equal(globalThis.fixtureActivated, true);
      moduleUi('fixture').drawerActions[0].run(); assert.equal(globalThis.fixtureAction, true);
    }
    console.log(`PASS: ${mode} contributions, surfaces, actions, activation and fallback`);
  }
} finally {
  await fs.rm(temporary, { recursive: true, force: true });
  delete globalThis.localStorage;
  delete globalThis.fetch;
  delete globalThis.fixtureAction;
  delete globalThis.fixtureActivated;
}
