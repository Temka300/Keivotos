// Check actual clients against requests captured before their ownership split.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { build } from '../frontend/node_modules/vite/dist/node/index.js';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const frontend = path.join(root, 'frontend');
const snapshot = JSON.parse(await fs.readFile(path.join(root, 'tests/snapshots/frontend_api.json'), 'utf8'));
const input = path.join(frontend, '__api_contract__.ts');
const entry = `export { api, thumbnailUrl, imageFileUrl } from './src/lib/api';
export { suiteDataApi } from './src/lib/suiteDataApi';
export { danbooruApi } from './src/modules/danbooru/api';`;
const result = await build({ root: frontend, configFile: false, logLevel: 'silent',
  plugins: [{ name: 'api-contract', resolveId: id => id === input ? id : null, load: id => id === input ? entry : null }],
  build: { write: false, minify: false, lib: { entry: input, formats: ['es'] } },
});
const output = (Array.isArray(result) ? result[0] : result).output.find(item => item.type === 'chunk');
const temporary = await fs.mkdtemp(path.join(os.tmpdir(), 'keivotos-api-contract-'));
globalThis.window = { location: { origin: 'http://fixture.invalid' } };
try {
  const bundle = path.join(temporary, 'api.mjs');
  await fs.writeFile(bundle, output.code);
  const { api, suiteDataApi, danbooruApi, thumbnailUrl, imageFileUrl } = await import(pathToFileURL(bundle).href);
  assert.deepEqual(Object.keys(api).sort(), [...new Set(snapshot.cases.map(c => c.name))].sort());
  assert.equal(Object.keys(suiteDataApi).length, 15);
  for (const [name, method] of Object.entries(api)) {
    assert.strictEqual(method, suiteDataApi[name] ?? danbooruApi[name], name + ' method identity');
  }
  for (const fixture of snapshot.cases) {
    const signal = new AbortController().signal;
    let calls = 0;
    globalThis.fetch = async (url, options = {}) => {
      calls++;
      assert.deepEqual({ url: String(url), method: options.method ?? 'GET', headers: options.headers ?? null,
        body: options.body ?? null, signal: !!options.signal }, fixture.request, fixture.name);
      if (fixture.request.signal) assert.strictEqual(options.signal, signal);
      return new Response('{"fixture":true}', { status: 200 });
    };
    assert.deepEqual(await api[fixture.name](...fixture.args.map(a => a?.$signal ? signal : a)), { fixture: true });
    assert.equal(calls, 1);
  }
  for (const fixture of snapshot.urls) {
    assert.equal(({ thumbnailUrl, imageFileUrl })[fixture.name](...fixture.args), fixture.value);
  }
  for (const call of [
    () => suiteDataApi.getUserSetting('profile_name'),
    () => suiteDataApi.createMetadataBackup({ user_database: true }),
    () => suiteDataApi.configureBackups({ user_database: true }),
    () => danbooruApi.deleteCollection(7),
  ]) {
    for (const [body, status, statusText, expected] of [
      ['{"detail":"fixture denied"}', 400, 'Bad Request', 'fixture denied'],
      ['{"detail":[{"msg":"invalid"}]}', 422, 'Unprocessable Content', '[{"msg":"invalid"}]'],
      ['not json', 503, 'Unavailable', 'API 503: Unavailable'],
    ]) {
      globalThis.fetch = async () => new Response(body, { status, statusText });
      await assert.rejects(call(), error => error.message === expected);
    }
    const networkError = new Error('fixture transport failure');
    globalThis.fetch = async () => { throw networkError; };
    await assert.rejects(call(), error => error === networkError);
  }
  const suiteBuild = await build({ root: frontend, configFile: false, logLevel: 'silent',
    build: { write: false, minify: false, lib: { entry: path.join(frontend, 'src/lib/suiteDataApi.ts'), formats: ['es'] } },
  });
  const suiteChunks = (Array.isArray(suiteBuild) ? suiteBuild[0] : suiteBuild).output.filter(item => item.type === 'chunk');
  assert(suiteChunks.every(chunk => chunk.moduleIds.every(id => !id.includes('/modules/danbooru/'))),
    'Suite preservation/settings client must not import Danbooru');
  console.log(`PASS: ${snapshot.cases.length} requests, ${snapshot.urls.length} URLs, 92 method identities, error semantics and suite isolation`);
} finally {
  await fs.rm(temporary, { recursive: true, force: true });
  delete globalThis.window;
}
