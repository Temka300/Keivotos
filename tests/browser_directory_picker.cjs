// Run with Node + an externally installed Playwright against the disposable
// server described in docs/build/source.md. No browser dependency is added.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const config = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
assert.match(config.fixture, /^\/tmp\/keivotos-picker-[^/]+\/Picker Media$/);
assert.match(config.home, /^\/tmp\/keivotos-picker-[^/]+\/metadata$/);
assert.ok(['localhost', '127.0.0.1'].includes(new URL(config.url).hostname));

(async () => {
  const browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {}) });
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  page.setDefaultTimeout(10000);
  const errors = [];
  const expectedHttpErrors = new Set();
  page.on('pageerror', e => errors.push(e.message));
  page.on('console', message => {
    if (message.type() !== 'error') return;
    if (expectedHttpErrors.has(message.location().url) && message.text().startsWith('Failed to load resource:')) return;
    errors.push(message.text());
  });
  const picker = page.getByRole('dialog', { name: 'Choose a folder', exact: true });
  const field = picker.getByRole('textbox', { name: 'Folder path' });
  const select = picker.getByRole('button', { name: 'Choose this folder' });
  const sources = () => page.evaluate(async () => (await fetch('/api/files/sources')).json());
  const unreadable = config.fixture + '/Unreadable folder';
  async function visit(path) {
    await field.fill(path);
    assert.equal(await select.isDisabled(), true, 'Edited path must be browsed before selection');
    await picker.getByRole('button', { name: 'Go', exact: true }).click();
    await page.waitForFunction(p => {
      const d = document.querySelector('dialog[open]');
      return d?.querySelector('input')?.value === p && !d.querySelector('footer button:last-child')?.disabled
        && d.querySelector('[aria-busy]')?.getAttribute('aria-busy') === 'false';
    }, path);
  }
  try {
    await page.goto(config.url);
    const storage = await page.evaluate(async () => (await fetch('/api/storage')).json());
    assert.equal(storage.suite_home, config.home, 'Refuse to test against a live application home');
    assert.deepEqual(await sources(), [], 'Use a fresh disposable library');

    await page.getByRole('button', { name: 'Add folder', exact: true }).click();
    await picker.waitFor();
    await visit(config.fixture);
    fs.mkdirSync(unreadable, { mode: 0o700 });
    fs.chmodSync(unreadable, 0o000);
    for (const [path, status, message] of [
      [config.fixture + '/Missing folder', 404, 'Folder not found'],
      [config.fixture + '/Upper/note.txt', 400, 'Choose a folder, not a file'],
      [unreadable, 403, 'Cannot read that folder: permission denied'],
    ]) {
      await field.fill(path);
      const responsePromise = page.waitForResponse(response => {
        const url = new URL(response.url());
        return url.pathname === '/api/files/fs' && url.searchParams.get('path') === path;
      });
      expectedHttpErrors.add(config.url + '/api/files/fs?' + new URLSearchParams({ path }));
      await picker.getByRole('button', { name: 'Go', exact: true }).click();
      assert.equal((await responsePromise).status(), status);
      await picker.getByRole('alert').filter({ hasText: message }).waitFor();
      assert.equal(await select.isDisabled(), true, 'Invalid folders cannot be selected');
      assert.deepEqual(await sources(), [], 'Failed browsing must not register anything');
      await visit(config.fixture);
      assert.equal(await picker.getByRole('alert').count(), 0, 'A valid retry clears the error');
    }
    fs.chmodSync(unreadable, 0o700);
    console.log('PASS: missing/file/permission errors prevent selection; valid retry recovers without registration');
    await picker.getByRole('button', { name: 'Upper', exact: true }).click();
    await page.waitForFunction(p => document.querySelector('dialog[open] input')?.value === p, config.fixture + '/Upper');
    await picker.getByRole('button', { name: '↑ Up' }).click();
    await picker.getByRole('button', { name: 'upper', exact: true }).click();
    await page.waitForFunction(p => document.querySelector('dialog[open] input')?.value === p, config.fixture + '/upper');
    for (let i = 0; i < 14; i++) {
      await page.keyboard.press('Tab');
      assert.equal(await picker.evaluate(d => d.contains(document.activeElement)), true, 'Focus must remain inside picker');
    }
    for (let i = 0; i < 14; i++) {
      await page.keyboard.press('Shift+Tab');
      assert.equal(await picker.evaluate(d => d.contains(document.activeElement)), true);
    }
    await page.keyboard.press('Escape');
    await picker.waitFor({ state: 'hidden' });
    assert.deepEqual(await sources(), []);
    assert.equal(await page.getByRole('button', { name: 'Add folder', exact: true }).evaluate(e => e === document.activeElement), true);
    console.log('PASS: navigation, case-sensitive paths, focus trap, Escape, focus restoration, cancellation');

    // Exercise two overlapping directory requests and cancellation while loading.
    await page.route('**/api/files/fs?**', async route => {
      if (new URL(route.request().url()).searchParams.get('path') === config.fixture + '/Upper') {
        const response = await route.fetch();
        await new Promise(resolve => setTimeout(resolve, 600));
        await route.fulfill({ response });
      } else await route.continue();
    });
    await page.getByRole('button', { name: 'Add folder', exact: true }).click();
    await picker.waitFor();
    await field.fill(config.fixture + '/Upper');
    await picker.getByRole('button', { name: 'Go', exact: true }).click();
    await visit(config.fixture + '/upper');
    await page.waitForTimeout(800);
    assert.equal(await field.inputValue(), config.fixture + '/upper');
    await field.fill(config.fixture + '/Upper');
    await picker.getByRole('button', { name: 'Go', exact: true }).click();
    await field.fill(config.fixture + '/unsubmitted draft');
    await page.waitForTimeout(800);
    assert.equal(await field.inputValue(), config.fixture + '/unsubmitted draft');
    assert.equal(await select.isDisabled(), true);
    await field.fill(config.fixture + '/Upper');
    await picker.getByRole('button', { name: 'Go', exact: true }).click();
    await picker.getByRole('button', { name: 'Cancel', exact: true }).click();
    await page.getByRole('button', { name: 'Add folder', exact: true }).click();
    await picker.waitFor();
    await page.waitForTimeout(800);
    assert.equal(await field.inputValue(), '');
    await page.unroute('**/api/files/fs?**');
    await visit(config.fixture + '/Upper');
    await select.click();
    await picker.waitFor({ state: 'hidden' });
    await page.waitForFunction(async p => (await (await fetch('/api/files/sources')).json()).some(s => s.path === p), config.fixture + '/Upper');
    await page.getByText('note.txt', { exact: true }).waitFor();
    console.log('PASS: stale responses ignored, cancel/reopen, actual registration and immediate file display');

    // Native Windows cancellation must not open the fallback or register a source.
    await page.route('**/api/files/pick', route => route.fulfill({ json: { native: true, path: null } }));
    await page.getByRole('button', { name: 'Add folder', exact: true }).click();
    await page.waitForTimeout(200);
    assert.equal(await picker.count(), 0);
    assert.equal((await sources()).length, 1);
    await page.unroute('**/api/files/pick');

    await page.getByRole('button', { name: 'Open Keivotos menu' }).click();
    await page.getByRole('button', { name: 'Settings', exact: true }).click();
    const settings = page.getByRole('dialog', { name: 'Settings', exact: true });
    await settings.getByRole('button', { name: 'Attachments', exact: true }).click();
    await settings.getByRole('button', { name: 'Choose a folder', exact: true }).click();
    const storeBefore = await page.evaluate(async () => (await fetch('/api/files/attachment-store')).json());
    await settings.getByRole('button', { name: 'Browse…', exact: true }).click();
    await picker.waitFor();
    await page.keyboard.press('Escape');
    await picker.waitFor({ state: 'hidden' });
    assert.equal(await settings.isVisible(), true, 'Escape closes the picker only');
    await settings.getByRole('button', { name: 'Browse…', exact: true }).click();
    await visit(config.fixture + '/Empty folder');
    await select.click();
    await picker.waitFor({ state: 'hidden' });
    assert.equal(await settings.locator('#setting-attachment-location input').inputValue(), config.fixture + '/Empty folder');
    assert.deepEqual(await page.evaluate(async () => (await fetch('/api/files/attachment-store')).json()), storeBefore, 'Picking only edits the draft');
    console.log('PASS: attachment draft selection, empty directory, Settings remains open, no implicit save');

    await page.route('**/api/files/pick', route => route.fulfill({ json: { native: true, path: 'C:\\Fixture\\Picked folder' } }));
    await settings.getByRole('button', { name: 'Browse…', exact: true }).click();
    await page.waitForFunction(() => document.querySelector('#setting-attachment-location input')?.value === 'C:\\Fixture\\Picked folder');
    assert.equal(await picker.count(), 0);
    await page.unroute('**/api/files/pick');
    console.log('PASS: native selection uses the returned Windows path without a fallback');

    // Present the disposable source as module-owned to exercise relocation UI;
    // intercept the mutation so this test never starts a Danbooru import.
    await page.route('**/api/files/sources', async route => {
      const response = await route.fetch();
      const rows = await response.json();
      await route.fulfill({ json: rows.map(row => ({ ...row, role: 'danbooru' })) });
    });
    let relocatedPath = null;
    await page.route('**/api/suite/folders/*/path', async route => {
      relocatedPath = route.request().postDataJSON().path;
      await route.fulfill({ json: { files_updated: 0 } });
    });
    await settings.getByRole('button', { name: 'Folders', exact: true }).click();
    await settings.getByLabel('Folder actions').click();
    await settings.getByRole('button', { name: 'Relocate…', exact: true }).click();
    await picker.waitFor();
    await picker.getByRole('button', { name: 'Cancel', exact: true }).click();
    assert.equal(relocatedPath, null);
    await settings.getByRole('button', { name: 'Relocate…', exact: true }).click();
    await visit(config.fixture + '/upper');
    await select.click();
    await settings.getByText(/Relocated Upper/).waitFor();
    assert.equal(relocatedPath, config.fixture + '/upper');
    console.log('PASS: relocation cancellation and exact selected path (mutation intercepted)');
    assert.deepEqual(errors, [], 'Browser errors');
    console.log('PASS: no browser errors');
  } finally {
    if (fs.existsSync(unreadable)) fs.chmodSync(unreadable, 0o700);
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
