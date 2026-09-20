// Real elapsed Chromium interactions against the disposable runner only.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const config = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
assert.match(config.home, /[/\\]keivotos-modularization-[^/\\]+[/\\]home$/);
assert.equal(new URL(config.url).hostname, '127.0.0.1');
const report = { checks: [], timings: {}, errors: [], requests: [] };

(async () => {
  const browser = await chromium.launch({ headless: true, channel: process.env.PLAYWRIGHT_CHANNEL });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, reducedMotion: 'no-preference' });
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
  const wait = ms => page.waitForTimeout(ms); // Intentional: these checks measure elapsed motion.
  const menu = () => page.getByRole('button', { name: 'Open Keivotos menu', exact: true });
  const drawer = page.locator('.app-drawer');
  const dock = page.locator('.sidebar-dock');
  const grip = page.locator('[data-sidebar-grip]');
  const settings = page.getByRole('dialog', { name: 'Settings', exact: true });
  async function openDrawer() {
    await menu().click();
    await drawer.waitFor();
    await wait(300);
  }
  async function stored(suffix) { return page.evaluate(key => JSON.parse(localStorage.getItem('keivotos:' + key)), suffix); }
  async function sample(selector, duration) {
    return page.evaluate(async ({ selector, duration }) => {
      const start = performance.now(), points = [];
      while (performance.now() - start < duration) {
        const node = document.querySelector(selector);
        const rect = node?.getBoundingClientRect();
        points.push({ t: performance.now() - start, x: rect?.x, width: rect?.width,
          opacity: node ? Number(getComputedStyle(node).opacity) : null });
        await new Promise(requestAnimationFrame);
      }
      return points;
    }, { selector, duration });
  }
  try {
    await page.goto(config.url);
    assert.equal(await page.evaluate(async () => (await (await fetch('/api/storage')).json()).suite_home), config.home);
    await menu().waitFor();
    await menu().click();
    const entrance = await sample('.app-drawer', 330);
    report.timings.drawerEntrance = entrance;
    assert(entrance.some(p => p.x < -1), 'Drawer must have intermediate entry frames');
    assert(Math.abs(entrance.at(-1).x) < 1);
    await page.getByRole('button', { name: 'Close menu', exact: true }).click();
    report.timings.drawerExit = await sample('.app-drawer', 250);
    assert(report.timings.drawerExit.some(p => p.x < -1), 'Drawer exit must animate');
    await drawer.waitFor({ state: 'detached' });
    await openDrawer();
    await page.mouse.click(1000, 450);
    await drawer.waitFor({ state: 'detached' });
    await openDrawer();
    await page.keyboard.press('Escape');
    await drawer.waitFor({ state: 'detached' });
    check('suite drawer has timed entry/exit and button/backdrop/Escape dismissal');

    await openDrawer();
    await page.getByRole('button', { name: 'Settings', exact: true }).click();
    await settings.waitFor();
    assert.equal(await settings.getByRole('button', { name: 'Account', exact: true }).count(), 0);
    assert.equal(await settings.getByRole('button', { name: 'Appearance', exact: true }).count(), 1);
    await page.getByRole('button', { name: 'Close settings', exact: true }).click();
    await page.keyboard.press('Escape');
    await drawer.waitFor({ state: 'detached' });
    check('disabled Danbooru Settings are absent while suite Settings remain');

    await page.getByRole('button', { name: 'Size', exact: true }).click();
    await page.getByRole('button', { name: 'Small', exact: true }).click();
    assert.equal(await stored('files-grid-size'), 'small');
    await openDrawer();
    await page.getByRole('button', {name:'Settings',exact:true}).click();
  await page.getByRole('navigation', {name:'Settings sections'}).getByRole('button', {name:'Modules',exact:true}).click();
  await page.getByRole('switch', {name:'Danbooru module',exact:true}).click();
  await page.waitForFunction(() => document.querySelector('[data-module-id="danbooru"] [role="switch"]')?.getAttribute('aria-checked') === 'true');
  await page.getByRole('button', {name:'Close settings',exact:true}).click();
  await page.getByRole('dialog', {name:'Settings',exact:true}).waitFor({state:'detached'});
  await page.locator('.app-drawer').getByRole('button', {name:'Danbooru',exact:true}).click();
    await drawer.waitFor({ state: 'detached' });
    const browse = page.getByRole('button', { name: 'Browse', exact: true });
    await browse.waitFor();
    // Observe before the trigger: visibility polling can miss the short entry
    // transition when the browser and driver run on different operating systems.
    const sidebarEntrance = sample('.sidebar-dock', 1000);
    await browse.click();
    report.timings.sidebarEntrance = await sidebarEntrance;
    await dock.waitFor();
    assert(report.timings.sidebarEntrance.some(p => p.width > 1 && p.width < 250), 'Browse entry must animate');
    assert.equal(await dock.count(), 1);
    assert((await dock.boundingBox()).width > 250);
    await page.getByRole('button', { name: 'Size', exact: true }).click();
    await page.getByRole('button', { name: 'Large', exact: true }).click();
    assert.equal(await stored('image-size'), 'large');
    assert.equal(await stored('files-grid-size'), 'small');
    check('Files and Danbooru grid sizes persist independently');

    // Hold the original element across reversals; duplication/remounting is a failure.
    const original = await dock.elementHandle();
    await grip.click();
    report.timings.sidebarClose = await sample('.sidebar-dock', 350);
    assert(report.timings.sidebarClose.some(p => p.width > 1 && p.width < 250));
    assert((await dock.boundingBox()).width < 1);
    await grip.click();
    await wait(45);
    // Keyboard activation avoids chasing a grip that is itself moving during
    // the transition, and does not wait for animation stability between toggles.
    await grip.focus();
    report.timings.rapidReversal = [];
    for (let i = 0; i < 5; i++) {
      await page.keyboard.press('Enter');
      await wait(40);
      assert.equal(await dock.count(), 1);
      assert.equal(await stored('sidebar-open'), i % 2 === 1);
      report.timings.rapidReversal.push(await dock.boundingBox());
    }
    await wait(350);
    assert(await original.evaluate(node => node === document.querySelector('.sidebar-dock')));
    assert.equal(await stored('sidebar-open'), false);
    assert((await dock.boundingBox()).width < 1);
    check('sidebar closes with intermediate frames and survives rapid reversals without remounting');

    await page.mouse.move(800, 500);
    await grip.evaluate(node => node.blur());
    await wait(1450);
    const visual = page.locator('.sidebar-grip-visual');
    assert(Number(await visual.evaluate(n => getComputedStyle(n).opacity)) < .05);
    await grip.hover();
    await wait(220);
    assert(Number(await visual.evaluate(n => getComputedStyle(n).opacity)) > .95);
    await page.mouse.move(800, 500);
    await wait(220);
    assert(Number(await visual.evaluate(n => getComputedStyle(n).opacity)) < .05);
    check('grip delayed hide, hover reveal and hover return');
    await grip.hover();
    const box = await grip.boundingBox();
    await page.mouse.move(box.x + 10, box.y + box.height / 2);
    await page.mouse.down();
    await page.mouse.move(box.x + 10, box.y + 150, { steps: 12 });
    await page.mouse.up();
    const position = await stored('sidebar-handle-position');
    assert(position > 55 && position <= 90);
    assert.equal(await stored('sidebar-open'), false, 'Drag must not toggle the panel');
    await page.evaluate(() => localStorage.setItem('keivotos:startup-view', JSON.stringify('gallery')));
    await page.reload();
    await grip.waitFor();
    await wait(350);
    const restoredPosition = await stored('sidebar-handle-position');
    assert(Math.abs(restoredPosition - position) <= .051, 'Reload keeps position rounded to one decimal');
    assert.equal(await stored('sidebar-open'), false);
    assert.equal(await stored('image-size'), 'large');
    assert.equal(await stored('files-grid-size'), 'small');
    await grip.focus();
    await page.keyboard.press('ArrowUp');
    assert.equal(await stored('sidebar-handle-position'), restoredPosition - 5);
    check('grip drag and keyboard positioning persist across reload without toggling');

    await grip.click();
    await wait(350);
    await page.setViewportSize({ width: 1440, height: 420 });
    const sidebar = page.locator('.sidebar-scroll');
    assert(await sidebar.evaluate(n => n.scrollHeight > n.clientHeight));
    await sidebar.hover();
    await page.mouse.wheel(0, 600);
    await wait(250);
    assert(await sidebar.evaluate(n => n.scrollTop > 0));
    assert.equal(await page.evaluate(() => document.documentElement.scrollTop), 0);
    await page.setViewportSize({ width: 1440, height: 900 });
    check('sidebar scrolls within the viewport');

    await openDrawer();
    await page.getByRole('button', { name: 'Settings', exact: true }).click();
    await settings.waitFor();
    assert.equal(await settings.getByRole('button', { name: 'Account', exact: true }).count(), 1);
    assert.equal(await page.locator('html').getAttribute('data-settings-open'), 'true');
    await settings.getByRole('searchbox', { name: 'Search settings' }).fill('motion');
    await settings.getByRole('button').filter({ hasText: 'Interface motion' }).click();
    await settings.locator('#setting-motion').waitFor();
    await wait(450);
    assert(await settings.locator('#setting-motion').evaluate(n => n.getBoundingClientRect().top >= 0));
    assert(await settings.locator('#setting-motion').evaluate(n => n.classList.contains('setting-flash')));
    await wait(1200);
    assert.equal(await settings.locator('#setting-motion').evaluate(n => n.classList.contains('setting-flash')), false);
    await settings.getByRole('button', { name: 'Reduced', exact: true }).click();
    assert.equal(await page.locator('html').getAttribute('data-motion'), 'reduced');
    await page.getByRole('button', { name: 'Close settings', exact: true }).click();
    await settings.waitFor({ state: 'detached' });
    assert.equal(await page.locator('html').getAttribute('data-settings-open'), null);
    await page.keyboard.press('Escape');
    await drawer.waitFor({ state: 'detached' });
    await grip.click();
    await wait(40);
    assert((await dock.boundingBox()).width < 1, 'Reduced motion settles without the normal slide');
    check('enabled Settings, timed search highlight, presentation cleanup and reduced-motion sidebar');
    await page.getByRole('button', { name: 'Tags', exact: true }).click();
    await dock.waitFor({ state: 'attached' });
    await page.getByTitle('Go Home', { exact: true }).click();
    await dock.waitFor({ state: 'detached' });
    check('sidebar belongs to Browse/Tags and is absent from Home');
    await page.screenshot({ path: path.join(config.output, 'baseline.png') });
    assert.deepEqual(report.errors, []);
    check('no browser errors or nonfixture requests');
  } catch (error) {
    report.failure = error.stack;
    await page.screenshot({ path: path.join(config.output, 'failure.png') }).catch(() => {});
    throw error;
  } finally {
    fs.writeFileSync(path.join(config.output, 'report.json'), JSON.stringify(report, null, 2));
    await context.tracing.stop({ path: path.join(config.output, 'trace.zip') });
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
