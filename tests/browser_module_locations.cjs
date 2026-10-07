const assert = require('node:assert/strict');
const fs = require('node:fs');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const config = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));

(async () => {
  const browser = await chromium.launch({ headless: true, channel: process.env.PLAYWRIGHT_CHANNEL });
  const context = await browser.newContext({ viewport: { width: 1280, height: 850 } });
  const page = await context.newPage();
  page.setDefaultTimeout(15000);
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  async function api(url, method = 'GET', body) {
    return page.evaluate(async ({ url, method, body }) => {
      const response = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      return { status: response.status, data: await response.json() };
    }, { url, method, body });
  }
  async function show(sourceId, relativePath) {
    await page.evaluate(({ sourceId, relativePath }) => window.__showInFiles(sourceId, relativePath), { sourceId, relativePath });
  }
  async function selected(name) {
    const exactTile = page.locator(`[data-files-entry-path="${name}"]`);
    await exactTile.waitFor();
    await page.waitForFunction(path => {
      const tile = [...document.querySelectorAll('[data-files-entry-path]')].find(node => node.dataset.filesEntryPath === path);
      return tile && tile === document.activeElement && tile.className.includes('border-purple-500/60');
    }, name);
  }
  try {
    await page.goto(config.url);
    const outer = await api('/api/files/sources', 'POST', { path: config.media, display_name: 'Outer' });
    assert.equal(outer.status, 200, JSON.stringify(outer));
    const inner = await api('/api/files/sources', 'POST', { path: config.media + '/Nested', display_name: 'Inner' });
    assert.equal(inner.status, 200, JSON.stringify(inner));
    assert.equal((await api(`/api/files/sources/${outer.data.source_id}/scan`, 'POST')).status, 200);
    await page.reload();
    await page.getByRole('navigation', { name: 'Current folder' }).getByRole('button', { name: 'Outer' }).waitFor();

    await show(outer.data.source_id, 'Deep/子/same.txt');
    await selected('Deep/子/same.txt');
    assert.equal(await page.getByRole('navigation', { name: 'Current folder' }).getByRole('button', { name: '子' }).count(), 1);
    console.log('PASS: mounted Files opens a deep Unicode parent and focuses the exact file');

    await show(inner.data.source_id, 'same.txt');
    await selected('same.txt');
    assert.equal(await page.getByRole('navigation', { name: 'Current folder' }).getByRole('button', { name: 'Inner' }).count(), 1);
    console.log('PASS: duplicate name resolves through the requested nested source');

    await show(outer.data.source_id, 'Deep/子');
    await page.getByRole('navigation', { name: 'Current folder' }).getByRole('button', { name: '子' }).waitFor();
    assert.equal(await page.getByRole('navigation', { name: 'Current folder' }).getByRole('button', { name: '子' }).evaluate(node => node === document.activeElement), true);
    console.log('PASS: folder destination opens itself and focuses its breadcrumb');

    await show(outer.data.source_id, 'missing.txt');
    await page.getByText('This item is no longer available in its Files folder.').waitFor();
    assert.equal(await page.getByRole('navigation', { name: 'Current folder' }).getByRole('button', { name: '子' }).count(), 1);
    console.log('PASS: missing target is rejected without a fallback jump');

    assert.equal((await api('/api/suite/modules/video/enable', 'POST')).status, 200);
    await page.reload();
    await page.getByRole('button', { name: 'Open Keivotos menu' }).click();
    await page.locator('.app-drawer').getByRole('button', { name: 'Video', exact: true }).click();
    await show(inner.data.source_id, 'same.txt');
    await selected('same.txt');
    console.log('PASS: unmounted Files consumes a one-use request after sources load');

    const hide = await api('/api/suite/folders/apply', 'POST', { folders: [{
      source_id: inner.data.source_id, path: config.media + '/Nested',
      display_name: 'Inner', role: 'files', visible: false, forget: false,
    }] });
    assert.equal(hide.status, 200, JSON.stringify(hide));
    await show(inner.data.source_id, 'same.txt');
    await page.getByText('This item’s folder is no longer visible in Files.').waitFor();
    await show('no-such-source', 'same.txt');
    await page.getByText('This item’s folder is no longer visible in Files.').waitFor();
    assert.equal(await page.getByRole('navigation', { name: 'Current folder' }).getByRole('button', { name: 'Inner' }).count(), 1);
    console.log('PASS: hidden or removed source is rejected without selecting another source');

    assert.deepEqual(errors, []);
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
