import assert from 'node:assert/strict';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { build } from '../frontend/node_modules/vite/dist/node/index.js';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const temporary = await mkdtemp(path.join(os.tmpdir(), 'keivotos-release-date-'));
try {
  const result = await build({
    root: path.join(root, 'frontend'), configFile: false, logLevel: 'silent',
    build: { write: false, minify: false, lib: { entry: path.join(root, 'frontend/src/lib/product.ts'), formats: ['es'] } },
  });
  const chunk = (Array.isArray(result) ? result[0] : result).output.find(item => item.type === 'chunk');
  const file = path.join(temporary, 'product.mjs');
  await writeFile(file, chunk.code);
  const { formatReleaseDate } = await import(pathToFileURL(file).href);
  assert.equal(formatReleaseDate('2026-11-02T10:43:17+09:00'), '2026/11/02 10/43 UTC+09:00');
  assert.equal(formatReleaseDate('2026-11-01T20:43:17-05:00'), '2026/11/01 20/43 UTC-05:00');
  assert.equal(formatReleaseDate('2026-11-02T01:43:17Z'), '2026/11/02 01/43 UTC');
  assert.equal(formatReleaseDate(''), null);
  console.log('PASS: release display keeps recorded calendar time and zone');
} finally {
  await rm(temporary, { recursive: true, force: true });
}
