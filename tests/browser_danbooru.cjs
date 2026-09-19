// Populated, real-API baseline. Artwork and every mutation belong to the scratch home.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const config = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
assert.match(config.home, /[/\\]keivotos-modularization-[^/\\]+[/\\]home$/);
assert.equal(new URL(config.url).hostname, '127.0.0.1');
const report = { checks: [], timings: {}, errors: [], requests: [] };
(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  await context.tracing.start({ screenshots: true, snapshots: true });
  const page = await context.newPage();
  page.setDefaultTimeout(10000);
  page.on('pageerror', e => report.errors.push(e.message));
  page.on('console', m => { if (m.type() === 'error') report.errors.push(m.text()); });
  page.on('response', r => { if (r.status() >= 400) report.errors.push(`${r.status()} ${r.url()}`); });
  await page.route('**/*', route => {
    const url = new URL(route.request().url());
    if (url.origin !== config.url) {
      report.errors.push(`Blocked nonfixture request: ${url.href}`);
      return route.abort();
    }
    if (url.pathname.startsWith('/api/')) report.requests.push(`${route.request().method()} ${url.pathname}`);
    return route.continue();
  });
  const check = label => { report.checks.push(label); console.log(`PASS: ${label}`); };
  const wait = ms => page.waitForTimeout(ms);
  const lane = page.locator('.home-lane');
  const track = page.locator('.home-lane-track');
  const overlay = page.locator('div.fixed.inset-0.z-50');
  const transform = loc => loc.evaluate(n => getComputedStyle(n).transform);
  async function closeDetail() {
    await page.getByTitle('Close', { exact: true }).click();
    await overlay.waitFor({ state: 'detached' });
  }
  try {
    await page.goto(config.url);
    assert.equal(await page.evaluate(async () => (await (await fetch('/api/storage')).json()).suite_home), config.home);
    await page.getByRole('button', { name: 'Open Keivotos menu', exact: true }).click();
    await page.getByRole('button', { name: 'Enable', exact: true }).click();
    await page.locator('.spotlight-peek.is-active').waitFor();
    await track.nth(2).waitFor();
    await page.waitForFunction(() => [...document.querySelectorAll('.spotlight-peek img')].every(n => n.complete && n.naturalWidth));
    assert.equal(await page.locator('.spotlight-peek').count(), 5);
    const active = () => page.locator('.spotlight-peek.is-active').getAttribute('aria-label');
    const before = await active();
    const started = Date.now();
    await page.waitForFunction(label => document.querySelector('.spotlight-peek.is-active')?.getAttribute('aria-label') !== label, before, { timeout: 12000 });
    report.timings.spotlightAdvanceMs = Date.now() - started;
    assert(report.timings.spotlightAdvanceMs > 6500);
    const pick = page.locator('.spotlight-peek.is-far').first();
    const picked = await pick.getAttribute('aria-label');
    await pick.click();
    assert.equal(await active(), picked);
    await wait(700);
    assert.equal(await active(), picked);
    check('populated spotlight decodes images, advances after nine seconds and accepts selection');

    await lane.first().scrollIntoViewIfNeeded();
    await page.mouse.move(1400, 20);
    const moving = await transform(track.first());
    await wait(250);
    assert.notEqual(await transform(track.first()), moving);
    await lane.first().hover();
    const paused = await transform(track.first());
    const other = await transform(track.nth(1));
    await wait(250);
    assert.equal(await transform(track.first()), paused);
    assert.notEqual(await transform(track.nth(1)), other);
    await page.mouse.move(1400, 20);
    await lane.first().locator('button').first().focus();
    const focused = await transform(track.first());
    await wait(250);
    assert.equal(await transform(track.first()), focused);
    await page.keyboard.press('Enter');
    await page.getByTitle('Close', { exact: true }).waitFor();
    await closeDetail();
    const resumed = await transform(track.first());
    await wait(250);
    assert.notEqual(await transform(track.first()), resumed);
    check('Home lanes move independently, pause on hover/focus and resume after detail closes');

    await page.getByRole('button', { name: 'Browse', exact: true }).click();
    const card = page.getByRole('button', { name: /^fixture-\d+\.jpg$/ }).first();
    await card.waitFor();
    const filename = await card.getAttribute('aria-label');
    await card.click();
    const image = overlay.locator('img').first();
    await image.waitFor();
    await page.waitForFunction(() => document.querySelector('div.fixed.inset-0.z-50 img')?.naturalWidth > 0);
    await image.click();
    // Wait for the actual rendered transform: a fixed sleep can sample the
    // first CSS-transition frame when multiple browser suites share the CPU.
    await page.waitForFunction(() => new DOMMatrix(getComputedStyle(
      document.querySelector('div.fixed.inset-0.z-50 img')).transform).a > 1.9);
    const box = await image.boundingBox();
    await page.mouse.move(Math.max(100, box.x + box.width / 2), 400);
    await page.mouse.down();
    await page.mouse.move(450, 460, { steps: 8 });
    await page.mouse.up();
    assert.equal(await overlay.count(), 1);
    await page.getByRole('button', { name: 'Favorite', exact: true }).click();
    await page.getByRole('button', { name: 'Favorited', exact: true }).waitFor();
    await page.keyboard.press('Escape');
    await overlay.waitFor({ state: 'detached' });
    await page.getByTitle('User menu', { exact: true }).click();
    await page.getByRole('menuitem', { name: 'Favorites', exact: true }).click();
    await page.getByRole('button', { name: filename, exact: true }).waitFor();
    check('grid opens decoded detail, zoom/drag keeps it open, favorite reconciles into Favorites');

    await page.getByTitle('User menu', { exact: true }).click();
    await page.getByRole('menuitem', { name: 'Profile', exact: true }).click();
    await page.getByText('Keivotos', { exact: true }).first().waitFor();
    await page.getByTitle('User menu', { exact: true }).click();
    await page.getByRole('menuitem', { name: 'Collections', exact: true }).click();
    await page.getByTitle('Go Home').click();
    await page.getByRole('button', { name: 'Challenge', exact: true }).click();
    await page.getByRole('button', { name: 'Back to Home', exact: true }).click();
    await page.getByRole('button', { name: 'Tags', exact: true }).click();
    await page.waitForTimeout(400);
    check('populated Profile, Collections, Challenge and Tags remain reachable');
    await page.screenshot({ path: path.join(config.output, 'populated-tags.png') });
    assert.deepEqual(report.errors, []);
    check('no browser, HTTP or external-request errors');
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
