// Backup settings against disposable real storage; labeled response fixtures
// cover unavailable-owner and preserved-history presentation without live data.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const config = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
assert.match(config.home, /[/\\]keivotos-modularization-[^/\\]+[/\\]home$/);
assert.equal(new URL(config.url).hostname, '127.0.0.1');
(async () => {
  const browser = await chromium.launch({ headless: true, channel: process.env.PLAYWRIGHT_CHANNEL });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  await context.tracing.start({ screenshots: true, snapshots: true });
  const page = await context.newPage();
  page.setDefaultTimeout(10000);
  const report = { checks: [], errors: [], restoreRequests: 0 };
  const check = text => { report.checks.push(text); console.log('PASS: ' + text); };
  page.on('pageerror', e => report.errors.push(e.message));
  page.on('console', m => { if (m.type() === 'error') report.errors.push(m.text()); });
  page.on('response', r => { if (r.status() >= 400) report.errors.push(`${r.status()} ${r.url()}`); });
  await page.route('**/*', route => {
    if (new URL(route.request().url()).origin !== config.url) {
      report.errors.push('Nonfixture request');
      return route.abort();
    }
    if (new URL(route.request().url()).pathname === '/api/backups/restore') report.restoreRequests++;
    return route.continue();
  });
  const settings = page.getByRole('dialog', { name: 'Settings', exact: true });
  async function openBackup() {
    await page.getByRole('button', { name: 'Open Keivotos menu', exact: true }).click();
    await page.getByRole('button', { name: 'Settings', exact: true }).click();
    await settings.getByRole('button', { name: 'Backup', exact: true }).click();
    await settings.getByRole('checkbox').first().waitFor();
  }
  try {
    await page.goto(config.url);
    assert.equal(await page.evaluate(async () => (await (await fetch('/api/storage')).json()).suite_home), config.home);
    await openBackup();
    assert.equal(await settings.getByRole('checkbox').count(), 6);
    assert.match(await settings.getByRole('checkbox', { name: /User database/ }).innerText(), /Keivotos/);
    assert.match(await settings.getByRole('checkbox', { name: /File attachments/ }).innerText(), /Files/);
    assert.match(await settings.getByRole('checkbox', { name: /Library database/ }).innerText(), /Danbooru/);
    await settings.getByText(/Browser preferences such as grid size/).waitFor();
    check('owner labels, browser exclusions and disabled-owner eligibility');

    // Deliver estimate replies out of order: older selection must not win.
    let estimateCalls = 0;
    await page.route('**/api/backups/estimate', async route => {
      const call = ++estimateCalls;
      const response = await route.fetch();
      const value = await response.json();
      value.estimated_compressed_display = call === 1 ? 'old selection' : 'latest selection';
      await new Promise(resolve => setTimeout(resolve, call === 1 ? 450 : 20));
      await route.fulfill({ json: value });
    });
    const history = settings.getByRole('checkbox', { name: /Sidecar history/ });
    await history.click();
    await history.click();
    await settings.getByText('Estimated compressed size: latest selection', { exact: true }).waitFor();
    await page.waitForTimeout(550);
    assert.equal(await settings.getByText('Estimated compressed size: old selection', { exact: true }).count(), 0);
    await page.unroute('**/api/backups/estimate');
    check('delayed estimate fixture: latest selection wins');
    await page.route('**/api/backups', async route => {
      const response = await route.fetch();
      await new Promise(resolve => setTimeout(resolve, 350));
      await route.fulfill({ response });
    });
    await settings.getByRole('button', { name: 'Save selection', exact: true }).click();
    assert.equal(await history.isDisabled(), true);
    await settings.getByText('Backup contents saved.', { exact: true }).waitFor();
    assert.equal(await history.isDisabled(), false);
    await page.unroute('**/api/backups');
    check('real selection save locks edits until the response is applied');

    await settings.getByRole('button', { name: /Create (another )?backup/, exact: true }).click();
    await settings.getByText(/Created backup_.*Unavailable components were omitted/).waitFor();
    assert.match(await settings.locator('[aria-live="polite"]').innerText(), /library database/);
    const select = settings.getByRole('combobox', { name: 'Backup to restore' });
    const backup = await select.inputValue();
    assert.match(backup, /\.keivotosbk$/);
    // Explicit inspection uses the same real backend bundle just created.
    await select.selectOption('');
    await select.selectOption(backup);
    await settings.getByText(/Restores the whole shared user database/).waitFor();
    await settings.getByText(/Omitted when created:/).waitFor();
    check('real backup creation reports omissions and inspection shows actual coverage');

    let confirmation = '';
    page.once('dialog', async dialog => { confirmation = dialog.message(); await dialog.dismiss(); });
    await settings.getByRole('button', { name: 'Restore', exact: true }).click();
    await page.waitForFunction(() => !document.querySelector('#setting-restore button').disabled);
    assert.match(confirmation, /whole shared user database/);
    assert.match(confirmation, /Files origin notes/);
    assert.match(confirmation, /Keivotos will preserve/);
    assert.match(confirmation, /Browser preferences will not be restored/);
    assert.equal(report.restoreRequests, 0);
    check('restore confirmation explains whole-database scope; cancel performs no restore');
    await page.evaluate(() => localStorage.setItem('keivotos:files-grid-size', JSON.stringify('absurd')));
    page.once('dialog', dialog => dialog.accept());
    await settings.getByRole('button', { name: 'Restore', exact: true }).click();
    await settings.getByText(/Metadata restored and verified/).waitFor();
    await settings.getByText(/Attachments: 0 restored/).waitFor();
    assert.equal(report.restoreRequests, 1);
    assert.equal(await page.evaluate(() => JSON.parse(localStorage.getItem('keivotos:files-grid-size'))), 'absurd');
    check('real scratch restore displays rollback and attachment results; browser state stays separate');
    await page.screenshot({ path: path.join(config.output, 'backup-restored.png') });

    // Response fixtures exercise future/absent owners without changing registry code.
    await page.route('**/api/backups', async route => {
      const response = await route.fetch();
      const value = await response.json();
      value.components = { user_database: true, file_attachments: true, extra_archive: false };
      value.estimate.details = {
        user_database: value.estimate.details.user_database,
        file_attachments: value.estimate.details.file_attachments,
        extra_archive: { owner: 'example', exists: false, files: 0, bytes: 0, display_size: '0 B', enabled: false },
      };
      await route.fulfill({ json: value });
    });
    await page.route('**/api/local-recovery', async route => {
      const response = await route.fetch();
      await route.fulfill({ json: { ...await response.json(), preserved_count: 3, preserved_directory: '/fixture/preserved' } });
    });
    await page.reload();
    await openBackup();
    assert.equal(await settings.getByRole('checkbox').count(), 3);
    assert.equal(await settings.getByRole('checkbox', { name: /Library database/ }).count(), 0);
    await settings.getByRole('checkbox', { name: /extra archive/ }).waitFor();
    await settings.getByText(/3 legacy checkpoints/).waitFor();
    check('response fixture: absent owner hidden, additional component and preserved history displayed');
    assert.deepEqual(report.errors, []);
    check('no browser errors or nonfixture requests');
  } catch (error) {
    report.failure = error.stack;
    await page.screenshot({ path: path.join(config.output, 'failure.png') });
    throw error;
  } finally {
    fs.writeFileSync(path.join(config.output, 'report.json'), JSON.stringify(report, null, 2));
    await context.tracing.stop({ path: path.join(config.output, 'trace.zip') });
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
