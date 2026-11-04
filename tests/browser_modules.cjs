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
 let opened = [], experimental = false, startupDelay = 0, startupFailOnce = false;
 await page.route('**/*', async route => {
  const url = new URL(route.request().url());
  if(url.origin !== config.url) {report.errors.push('Unexpected external request');return route.abort();}
  if(url.pathname.startsWith('/api/diagnostics/open/')) {
   opened.push(url.pathname.split('/').pop()); return route.fulfill({json:{status:'opened'}});
  }
  if(url.pathname === '/api/suite/modules' && route.request().method() === 'GET') {
   if(startupDelay) await new Promise(resolve=>setTimeout(resolve,startupDelay));
   if(startupFailOnce){startupFailOnce=false;return route.fulfill({status:503,json:{detail:'Fixture module failure'}});}
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
  if(!await page.locator('.app-drawer').count())await page.getByRole('button',{name:'Open Keivotos menu',exact:true}).click();
  await page.getByRole('button', {name:'Settings',exact:true}).click();
  await page.getByRole('navigation', {name:'Settings sections'}).getByRole('button', {name:'Modules',exact:true}).click();
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
  await toggle('true');
  await page.getByRole('button',{name:'Close settings',exact:true}).click();
  await page.locator('.app-drawer').getByRole('button',{name:'Danbooru',exact:true}).click();
  await page.evaluate(()=>localStorage.setItem('keivotos:startup-module',JSON.stringify('last')));
  await page.addInitScript(()=>{
   window.__filesMounts=0;
   document.addEventListener('DOMContentLoaded',()=>new MutationObserver(()=>{
    if(document.querySelector('input[placeholder="Search this folder…"]'))window.__filesMounts++;
   }).observe(document,{childList:true,subtree:true}));
  });
  startupDelay=500;
  await page.reload({waitUntil:'domcontentloaded'});
  await page.getByText('Opening Keivotos…').waitFor();
  assert.equal(await page.getByPlaceholder('Search this folder…').count(),0);
  await page.waitForFunction(()=>document.title==='Keivotos - Danbooru');
  assert.equal(await page.evaluate(()=>window.__filesMounts),0);
  startupDelay=0;
  startupFailOnce=true;
  await page.reload({waitUntil:'domcontentloaded'});
  await page.getByRole('alert').filter({hasText:'Could not load modules'}).getByRole('button',{name:'Retry'}).click();
  await page.waitForFunction(()=>document.title==='Keivotos - Danbooru');
  assert.equal(await page.evaluate(()=>JSON.parse(localStorage.getItem('keivotos:active-module'))),'danbooru');
  check('delayed and failed module loading never mounts Files or erases the remembered module');
  experimental=false;
  assert.match(config.home,/[/\\]keivotos-modularization-[^/\\]+[/\\]home$/);
  async function ostRequest(url,method='GET',body){return page.evaluate(async({url,method,body})=>{
   const response=await fetch(url,{method,headers:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});
   return {status:response.status,data:await response.json()};
  },{url,method,body});}
  const initialOst=(await ostRequest('/api/suite/modules')).data.find(module=>module.id==='ost');
  assert.equal(initialOst.experimental,true);assert.equal(initialOst.enabled,false);assert.equal(initialOst.accepts_folders,true);
  assert.equal((await ostRequest('/api/ost/folders')).status,409);
  assert.equal((await ostRequest('/api/ost/library')).status,409);
  const local=config.mediaLocal||config.media;
  fs.mkdirSync(path.join(local,'Album 2'),{recursive:true});fs.mkdirSync(path.join(local,'Album 10'));
  fs.writeFileSync(path.join(local,'Track 2.mp3'),'generated-only-audio-fixture');
  fs.writeFileSync(path.join(local,'Track 10.mp3'),'generated-only-audio-fixture');
  const beforeSources=(await ostRequest('/api/files/sources')).data;
  const blocked=await ostRequest('/api/suite/folders/apply','POST',{folders:[{path:config.media,display_name:'OST discovery fixture',role:'ost'}]});
  assert.equal(blocked.status,409);
  assert.deepEqual((await ostRequest('/api/files/sources')).data,beforeSources);
  await openModules();await section('Advanced').click();
  await page.getByRole('switch',{name:'Show experimental modules',exact:true}).click();
  await page.waitForFunction(async()=>!(await(await fetch('/api/diagnostics')).json()).show_experimental_modules);
  await section('Modules').click();
  assert.equal(await page.getByRole('switch',{name:'OST module',exact:true}).count(),0);
  await section('Advanced').click();await page.getByRole('switch',{name:'Show experimental modules',exact:true}).click();
  await page.waitForFunction(async()=>(await(await fetch('/api/diagnostics')).json()).show_experimental_modules);
  await section('Modules').click();
  const ostSwitch=page.getByRole('switch',{name:'OST module',exact:true});
  await ostSwitch.click();
  await page.waitForFunction(()=>document.querySelector('[data-module-id="ost"] [role="switch"]')?.getAttribute('aria-checked')==='true');
  await page.getByRole('button',{name:'Close settings',exact:true}).click();
  await page.locator('.app-drawer').getByRole('button',{name:'OST',exact:true}).click();
  await page.getByText('Assign folders to the OST role in Settings → Files → Folders.',{exact:true}).waitFor();
  check('OST is optional, experimental and disabled by default; disabled routes/assignment are guarded and Advanced gates its switch');

  const registered=await ostRequest('/api/suite/folders/apply','POST',{folders:[{path:config.media,display_name:'OST discovery fixture',role:'files'}]});
  assert.equal(registered.status,200,JSON.stringify(registered));
  const ostSource=registered.data.sources.find(source=>source.display_name==='OST discovery fixture');
  await openModules();await section('Folders').click();
  await dialog.getByRole('button',{name:'Manage folders…',exact:true}).click();
  const manager=page.getByRole('dialog',{name:'Manage folders',exact:true});
  const displayNames=manager.getByRole('textbox',{name:'Folder display name'});
  let folderIndex=-1;
  for(let i=0;i<await displayNames.count();i++)if(await displayNames.nth(i).inputValue()==='OST discovery fixture')folderIndex=i;
  assert.ok(folderIndex>=0);
  await manager.getByRole('combobox',{name:'Folder role'}).nth(folderIndex).selectOption('ost');
  await manager.getByRole('button',{name:'Save',exact:true}).click();
  await manager.waitFor({state:'detached'});
  await page.getByRole('button',{name:'Close settings',exact:true}).click();
  await page.getByRole('list',{name:'OST folders'}).getByText('OST discovery fixture',{exact:true}).waitFor();
  const catalog=(await ostRequest(`/api/ost/library?source_id=${ostSource.source_id}`)).data;
  assert.equal(catalog.total,4);
  assert.deepEqual(catalog.items.map(item=>item.name),['Album 2','Album 10','Track 2.mp3','Track 10.mp3']);
  assert.ok(catalog.items.every(item=>item.available));
  const paged=await ostRequest(`/api/ost/library?source_id=${ostSource.source_id}&offset=2&limit=2`);
  assert.deepEqual(paged.data.items,catalog.items.slice(2));
  assert.equal((await ostRequest(`/api/ost/library?source_id=${ostSource.source_id}&parent=..`)).status,400);
  assert.equal((await ostRequest(`/api/ost/library?source_id=${ostSource.source_id}&limit=0`)).status,422);
  const mediaResponse=await context.request.get(`${config.url}/api/files/file?source_id=${ostSource.source_id}&path=Track%202.mp3`,{headers:{Range:'bytes=0-7'}});
  assert.equal(mediaResponse.status(),206);assert.match(mediaResponse.headers()['content-type'],/audio\/mpeg/);
  assert.equal((await mediaResponse.body()).toString(),'generate');
  const storage=(await ostRequest('/api/storage/usage')).data;
  assert.equal(storage.library_files.categories.find(category=>category.id==='ost').files,2);
  await page.screenshot({path:path.join(config.output,'ost-sources.png')});
  check('native folder manager offers OST, assignment refreshes its surface, paginated natural discovery and shared audio ranges/storage work');

  await openModules();
  await section('Advanced').click();await page.getByRole('switch',{name:'Show experimental modules',exact:true}).click();
  await page.waitForFunction(async()=>!(await(await fetch('/api/diagnostics')).json()).show_experimental_modules);
  await section('Modules').click();assert.equal(await ostSwitch.count(),1);
  await ostSwitch.click();
  await page.waitForFunction(()=>!document.querySelector('[data-module-id="ost"] [role="switch"]'));
  assert.equal(await dialog.isVisible(),true);assert.equal(await page.locator('.ost-surface').count(),0);
  assert.equal((await ostRequest('/api/ost/folders')).status,409);
  const retained=(await ostRequest('/api/files/sources')).data.find(source=>source.source_id===ostSource.source_id);
  assert.equal(retained.role,'ost');assert.equal(fs.readFileSync(path.join(local,'Track 2.mp3'),'utf8'),'generated-only-audio-fixture');
  const baseListing=await ostRequest(`/api/files/browse?source_id=${ostSource.source_id}`);
  assert.equal(baseListing.status,200);assert.ok(baseListing.data.some(item=>item.name==='Track 2.mp3'));
  await section('Advanced').click();await page.getByRole('switch',{name:'Show experimental modules',exact:true}).click();
  await page.waitForFunction(async()=>(await(await fetch('/api/diagnostics')).json()).show_experimental_modules);
  await section('Modules').click();await ostSwitch.click();
  await page.waitForFunction(()=>document.querySelector('[data-module-id="ost"] [role="switch"]')?.getAttribute('aria-checked')==='true');
  await page.getByRole('button',{name:'Close settings',exact:true}).click();
  await page.getByRole('button',{name:'Open Keivotos menu',exact:true}).click();
  await page.locator('.app-drawer').getByRole('button',{name:'OST',exact:true}).click();
  await page.getByRole('list',{name:'OST folders'}).getByText('OST discovery fixture',{exact:true}).waitFor();
  await page.reload();await page.getByRole('list',{name:'OST folders'}).waitFor();
  check('enabled OST remains visible when experiments hide; disable preserves Settings, sources/media and Files access; re-enable/reload rediscovers folders');

  let delayedStarted;
  const delayed=new Promise(resolve=>{delayedStarted=resolve;});
  const delayedRoute=async route=>{delayedStarted();await new Promise(resolve=>setTimeout(resolve,450));await route.continue();};
  await page.route('**/api/ost/folders',delayedRoute);
  await page.reload({waitUntil:'domcontentloaded'});await delayed;
  await page.getByRole('button',{name:'Open Keivotos menu',exact:true}).click();
  await page.locator('.app-drawer').getByRole('button',{name:'Files',exact:true}).click();
  await page.waitForTimeout(550);
  assert.equal(await page.locator('.ost-surface').count(),0);
  await page.unroute('**/api/ost/folders',delayedRoute);
  check('leaving OST during delayed discovery aborts its request and ignores late completion');
  await page.screenshot({path:path.join(config.output,'modules.png')});
  assert.deepEqual(report.errors,[]);
 } finally {
  await context.tracing.stop({path:path.join(config.output,'trace.zip')});
  fs.writeFileSync(path.join(config.output,'report.json'),JSON.stringify(report,null,2));
  await browser.close();
 }
})().catch(e=>{console.error(e);process.exitCode=1;});
