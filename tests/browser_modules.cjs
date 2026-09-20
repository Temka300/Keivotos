const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const config = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const report = {checks: [], errors: []};
(async () => {
 const browser = await chromium.launch({headless:true, channel:process.env.PLAYWRIGHT_CHANNEL});
 const context = await browser.newContext({viewport:{width:1440,height:1000}});
 await context.tracing.start({screenshots:true,snapshots:true});
 const page = await context.newPage();
 page.setDefaultTimeout(12000);
 page.on('pageerror', e => report.errors.push(e.message));
 let opened = [], experimental = false;
 await page.route('**/*', async route => {
  const url = new URL(route.request().url());
  if(url.origin !== config.url) {report.errors.push('Unexpected external request');return route.abort();}
  if(url.pathname.startsWith('/api/diagnostics/open/')) {
   opened.push(url.pathname.split('/').pop()); return route.fulfill({json:{status:'opened'}});
  }
  if(experimental && url.pathname === '/api/suite/modules' && route.request().method() === 'GET') {
   const response = await route.fetch(); const modules = await response.json();
   modules.push({id:'fixture',slug:'fixture',name:'Fixture experimental',description:'Fixture only',experimental:true,enabled:false,disableable:true,is_base:false,api_prefix:'/api/fixture'});
   return route.fulfill({json:modules});
  }
  if(url.pathname === '/api/suite/modules/fixture/status') return route.fulfill({json:{id:'fixture',state:'disabled',error:null}});
  return route.continue();
 });
 const dialog = page.getByRole('dialog',{name:'Settings',exact:true});
 const section = name => dialog.getByRole('navigation',{name:'Settings sections'}).getByRole('button',{name,exact:true}).first();
 const check = text => { report.checks.push(text); console.log('PASS: '+text); };
 async function openModules() {
  await page.getByRole('button',{name:'Open Keivotos menu',exact:true}).click();
  await page.getByRole('button',{name:'Manage modules',exact:true}).click();
  await dialog.waitFor();
 }
 async function toggle(expected) {
  await page.getByRole('switch',{name:'Danbooru module',exact:true}).click();
  await page.waitForFunction(value => document.querySelector('[data-module-id="danbooru"] [role="switch"]')?.getAttribute('aria-checked') === value, expected);
 }
 try {
  await page.goto(config.url); await openModules();
  assert.equal(await page.getByRole('switch',{name:'Files module',exact:true}).isDisabled(),true);
  await toggle('true');
  await page.getByRole('button',{name:'Close settings',exact:true}).click();
  await dialog.waitFor({state:'detached'});
  await page.locator('.app-drawer').getByRole('button',{name:'Danbooru',exact:true}).click();
  await page.locator('.app-drawer').waitFor({state:'detached'});
  await page.getByTitle('User menu',{exact:true}).click();
  await page.getByRole('menuitem',{name:'Settings',exact:true}).click();
  await dialog.waitFor(); await section('Modules').click(); await toggle('false');
  await page.waitForTimeout(400);
  assert.equal(await dialog.isVisible(),true);
  assert.equal(await section('Account').count(),0);
  assert.equal(await page.title(),'Keivotos');
  check('Files stays required; disabling the active module preserves Settings and returns to Files');
  await section('Advanced').click();
  for(const name of ['Open data folder','Open logs folder','Open application log','Open request log']) {
   await page.getByRole('button',{name,exact:true}).click();
  }
  assert.deepEqual(opened,['data','logs','runtime','access']);
  await page.getByRole('switch',{name:'Verbose logging',exact:true}).click();
  await page.waitForFunction(async () => (await (await fetch('/api/diagnostics')).json()).verbose_logging);
  check('Advanced selects fixed log/data targets and saves verbose logging');
  experimental = true;
  await section('Modules').click();
  await page.getByRole('switch',{name:'Danbooru module'}).waitFor();
  assert.equal(await page.getByRole('switch',{name:'Fixture experimental module'}).count(),0);
  await section('Advanced').click();
  await page.getByRole('switch',{name:'Show experimental modules',exact:true}).click();
  await page.waitForFunction(async () => (await (await fetch('/api/diagnostics')).json()).show_experimental_modules);
  await section('Modules').click();
  await page.getByRole('switch',{name:'Fixture experimental module'}).waitFor();
  await page.reload(); await openModules();
  await page.getByRole('switch',{name:'Fixture experimental module'}).waitFor();
  assert.equal(await page.getByRole('switch',{name:'Danbooru module'}).getAttribute('aria-checked'),'false');
  check('experimental visibility and module enablement survive reload independently');
  await page.screenshot({path:path.join(config.output,'modules.png')});
  assert.deepEqual(report.errors,[]);
 } finally {
  await context.tracing.stop({path:path.join(config.output,'trace.zip')});
  fs.writeFileSync(path.join(config.output,'report.json'),JSON.stringify(report,null,2));
  await browser.close();
 }
})().catch(e=>{console.error(e);process.exitCode=1;});
