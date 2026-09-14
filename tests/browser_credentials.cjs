// UI contract with intercepted credentials: never access a user's OS vault.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const config = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
assert.match(config.home, /^\/tmp\/keivotos-picker-[^/]+\/metadata$/);
assert.ok(['localhost', '127.0.0.1'].includes(new URL(config.url).hostname));
(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  page.setDefaultTimeout(10000);
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const vaultError = 'Linux credential vault is unavailable, locked, or did not respond.';
  let fail = true, checks = 0, status = null;
  await page.route('**/api/suite/modules', async route => {
    const response = await route.fetch();
    await route.fulfill({ json: (await response.json()).map(row => ({ ...row, enabled: true })) });
  });
  await page.route('**/api/danbooru/credentials/check', async route => {
    checks++;
    await route.fulfill({ status: 400, json: { detail: 'Test must not call Danbooru' } });
  });
  await page.route('**/api/danbooru/credentials', async route => {
    if (fail) return route.fulfill({ status: 400, json: { detail: vaultError } });
    if (route.request().method() === 'PUT') {
      assert.deepEqual(route.request().postDataJSON(), { username: 'dummy-user', api_key: 'dummy-secret' });
      status = { username: 'dummy-user', has_api_key: true, has_saved_api_key: true,
        has_saved_credentials: true, configured: true, source: 'saved' };
    } else if (route.request().method() === 'DELETE') {
      status = { username: null, has_api_key: false, has_saved_api_key: false,
        has_saved_credentials: false, configured: false, source: 'none' };
    }
    await route.fulfill({ json: status });
  });
  try {
    await page.goto(config.url);
    assert.equal(await page.evaluate(async () => (await (await fetch('/api/storage')).json()).suite_home), config.home);
    await page.getByRole('button', { name: 'Open Keivotos menu' }).click();
    await page.getByRole('button', { name: 'Settings', exact: true }).click();
    const settings = page.getByRole('dialog', { name: 'Settings', exact: true });
    await settings.getByRole('button', { name: 'Account', exact: true }).click();
    await settings.locator('#setting-danbooru-access summary').click();
    await settings.getByText(vaultError, { exact: true }).waitFor();
    await settings.getByLabel('Username', { exact: true }).fill('dummy-user');
    await settings.getByLabel('API key', { exact: true }).fill('dummy-secret');
    await settings.getByRole('button', { name: 'Save securely', exact: true }).click();
    await settings.getByText(vaultError, { exact: true }).waitFor();
    assert.equal(await settings.getByLabel('API key', { exact: true }).inputValue(), 'dummy-secret');
    fail = false;
    await settings.getByRole('button', { name: 'Save securely', exact: true }).click();
    await settings.getByText('Credentials saved securely for this operating-system user.', { exact: true }).waitFor();
    assert.equal(await settings.getByLabel(/API key/).inputValue(), '');
    assert.equal(await settings.getByText(vaultError, { exact: true }).count(), 0);
    fail = true;
    page.once('dialog', dialog => dialog.accept());
    await settings.getByRole('button', { name: 'Remove saved', exact: true }).click();
    await settings.getByText(vaultError, { exact: true }).waitFor();
    fail = false;
    page.once('dialog', dialog => dialog.accept());
    await settings.getByRole('button', { name: 'Remove saved', exact: true }).click();
    await settings.getByText('Saved credentials removed.', { exact: true }).waitFor();
    assert.equal(await settings.getByRole('button', { name: 'Test connection', exact: true }).isDisabled(), true);
    assert.equal(checks, 0);
    assert.deepEqual(errors, []);
    console.log('PASS: Settings load/save/remove errors, retry, neutral success text, input clearing; no connection check or browser exceptions');
  } catch (error) {
    console.error('PAGE ERRORS', errors);
    throw error;
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
