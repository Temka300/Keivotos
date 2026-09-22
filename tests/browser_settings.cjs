// Owner Settings baseline with real preferences and explicit metadata-only fixtures.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const config = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
assert.match(config.home, /[/\\]keivotos-modularization-[^/\\]+[/\\]home$/);
const report = { checks: [], errors: [], requests: [] };
(async () => {
 const browser = await chromium.launch({ headless:true,channel:process.env.PLAYWRIGHT_CHANNEL });
 const context = await browser.newContext({ viewport:{width:1440,height:1000} });
 await context.tracing.start({ screenshots:true,snapshots:true });
 const page = await context.newPage();
 page.setDefaultTimeout(10000);
 page.on('pageerror', e=>report.errors.push(e.message));
 page.on('console', m=>{if(m.type()==='error')report.errors.push(m.text());});
 page.on('response', r=>{if(r.status()>=400)report.errors.push(`${r.status()} ${r.url()}`);});
 let credentialReads=0;
 let toolFixture=false, toolState="running";
 await page.route('**/*',route=>{
  const u=new URL(route.request().url());
  if(u.origin!==config.url){report.errors.push('External request '+u.href);return route.abort();}
  report.requests.push(`${route.request().method()} ${u.pathname}`);
  if(toolFixture){
   const folder={name:'Fixture root',selector:'fixture',root_id:'fixture',path:config.home+'/fixture',count:3,registered:true};
   if(u.pathname==='/api/tools')return route.fulfill({json:[
    {id:'sync',name:'Sync',description:'Fixture sync',status:toolState},
    {id:'sqlite',name:'Rebuild',description:'Fixture rebuild',status:'idle'},
    {id:'clean-sidecars',name:'Clean',description:'Fixture clean',status:'idle'},
   ]});
   if(u.pathname==='/api/tools/sync/status')return route.fulfill({json:{status:toolState,output:'Fixture task',progress:1,total:3}});
   if(u.pathname==='/api/folders')return route.fulfill({json:[folder]});
   if(u.pathname==='/api/folders/fixture/removal-preview')return route.fulfill({json:{...folder,indexed_files:3,sidecar_files:2,sidecar_bytes:100,external_images_affected:0,sidecar_history_preserved:true}});
  }

  if(u.pathname==='/api/danbooru/credentials'){
   assert.equal(route.request().method(),'GET');credentialReads++;
   return route.fulfill({json:{configured:false,source:'none',username:null,has_api_key:false}});
  }
  return route.continue();
 });
 const check=s=>{report.checks.push(s);console.log('PASS: '+s);};
 const dialog=page.getByRole('dialog',{name:'Settings',exact:true});
 const section=s=>dialog.getByRole('navigation',{name:'Settings sections'}).getByRole('button',{name:s,exact:true}).last();
 async function open(){await page.getByRole('button',{name:'Open Keivotos menu',exact:true}).click();await page.getByRole('button',{name:'Settings',exact:true}).click();await dialog.waitFor();}
 try{
  await page.goto(config.url);
  await open();
  assert.equal(await section('Account').count(),0);
  for(const name of ['Startup','Data & storage','Backup','Folders','Attachments','Appearance'])await section(name).click();
  assert.equal(credentialReads,0);
  await page.getByRole('button',{name:'Close settings',exact:true}).click();
  await page.getByRole('button', {name:'Settings',exact:true}).click();
  await page.getByRole('navigation', {name:'Settings sections'}).getByRole('button', {name:'Modules',exact:true}).click();
  await page.getByRole('switch', {name:'Danbooru module',exact:true}).click();
  await page.waitForFunction(() => document.querySelector('[data-module-id="danbooru"] [role="switch"]')?.getAttribute('aria-checked') === 'true');
  await page.getByRole('button', {name:'Close settings',exact:true}).click();
  await page.getByRole('dialog', {name:'Settings',exact:true}).waitFor({state:'detached'});
  await page.locator('.app-drawer').getByRole('button', {name:'Danbooru',exact:true}).click();
  await open();
  assert.deepEqual(await dialog.locator('nav button').allTextContents(),['Modules','Appearance','Startup','Data & storage','Backup','Advanced','Folders','Attachments','Account','Browsing','Display','Library','Advanced']);
  await section('Account').click();
  await dialog.locator('#setting-danbooru-access > summary').click();
  await dialog.getByRole('textbox',{name:'Username',exact:true}).fill('unsaved_fixture');
  await section('Appearance').click();
  await section('Account').click();
  await dialog.locator('#setting-danbooru-access > summary').click();
  assert.equal(await dialog.getByRole('textbox',{name:'Username',exact:true}).inputValue(),'unsaved_fixture');
  assert.equal(credentialReads,1);
  check('owner section order, disabled visibility, lazy account loading and draft persistence');
  await section('Browsing').click();
  await page.locator('#setting-home-layout').getByRole('button',{name:'Classic',exact:true}).click();
  await section('Display').click();
  await page.locator('#setting-media-playback').getByRole('button',{name:'Always',exact:true}).click();
  await section('Appearance').click();
  await page.locator('#setting-motion').getByRole('button',{name:'Reduced',exact:true}).click();
  assert.equal(await page.evaluate(()=>JSON.parse(localStorage.getItem('keivotos:home-layout'))),'classic');
  assert.equal(await page.evaluate(()=>JSON.parse(localStorage.getItem('keivotos:media-autoplay'))),'always');
  check('General and Danbooru preferences retain their existing storage keys');
  for(const name of ['Library','Advanced','Folders','Attachments','Data & storage','Backup']) {await section(name).click();await page.waitForTimeout(150);}
  await dialog.getByRole('searchbox').fill('animated media');
  await dialog.getByRole('button').filter({hasText:'Animated media'}).click();
  await page.locator('#setting-media-playback.setting-flash').waitFor();
  await page.waitForTimeout(1500);
  assert.equal(await page.locator('.setting-flash').count(),0);
  await section('Folders').click();
  await dialog.getByRole('button',{name:'Manage folders…',exact:true}).click();
  // The folder manager is a separate overlay and must escape the scroll pane.
  const manager=page.getByRole('dialog',{name:'Manage folders',exact:true});
  await manager.waitFor();
  assert.equal(await manager.evaluate(n=>!!n.closest('.settings-scroll')),false);
  await manager.getByRole('button',{name:'Cancel',exact:true}).click();
  await dialog.waitFor();
  check('all owner sections render, module search highlight expires, folder overlay stays outside scroll containment');
  await page.getByRole('button',{name:'Close settings',exact:true}).click();
  assert.equal(await page.evaluate(()=>document.documentElement.dataset.settingsOpen),undefined);
  await page.keyboard.press('Escape');
  await page.locator('.app-drawer').waitFor({state:'detached'});
  toolFixture=true;
  // Exercise the presentation resume hook without downloading/decoding media.
  await page.evaluate(()=>{
   const video=document.createElement('video');video.id='presentation-fixture';
   let paused=false;video.dataset.plays='0';video.dataset.pauses='0';
   Object.defineProperty(video,'paused',{get:()=>paused});
   video.pause=()=>{paused=true;video.dataset.pauses=String(Number(video.dataset.pauses)+1);};
   video.play=()=>{paused=false;video.dataset.plays=String(Number(video.dataset.plays)+1);return Promise.resolve();};
   document.querySelector('#app').appendChild(video);
  });
  await open();
  await section('Library').click();
  await dialog.getByText('Fixture task',{exact:true}).waitFor();
  await section('Backup').click();
  await page.waitForFunction(()=>[...document.querySelectorAll('button')].some(b=>b.textContent.trim()==='Back up now'&&b.disabled));
  toolState='done';
  await page.waitForFunction(()=>[...document.querySelectorAll('button')].some(b=>b.textContent.trim()==='Back up now'&&!b.disabled));
  check('module polling survives section changes and releases shared backup busy controls');
  await section('Advanced').click();
  await dialog.getByRole('button',{name:'Delete sidecars…',exact:true}).click();
  const removal=page.getByRole('dialog',{name:'What should be removed?',exact:true});
  await removal.getByText('External images affected: 0',{exact:true}).waitFor();
  await removal.getByRole('button',{name:/^Un-index only/}).waitFor();
  assert.equal(await removal.getByRole('button',{name:/^Un-index only/}).isEnabled(),true);
  assert.equal(await removal.evaluate(n=>!!n.closest('.settings-scroll')),false);
  await page.keyboard.press('Escape');
  await removal.waitFor({state:'detached'});await dialog.waitFor();
  await page.getByRole('button',{name:'Close settings',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#presentation-fixture').dataset.plays==='1');
  assert.equal(await page.locator('#presentation-fixture').getAttribute('data-pauses'),'1');
  assert.equal(await page.getByRole('dialog',{name:'What should be removed?',exact:true}).count(),0);
  assert(!report.requests.some(r=>r.startsWith('DELETE ')));
  check('module removal overlay keeps its warning, Escape leaves Settings open, media resume hook survives cleanup');

  assert.deepEqual(report.errors,[]);
  check('presentation cleanup and clean browser/API logs');
 }catch(e){report.failure=e.stack;await page.screenshot({path:path.join(config.output,'failure.png')});throw e;}
 finally{fs.writeFileSync(path.join(config.output,'report.json'),JSON.stringify(report,null,2));await context.tracing.stop({path:path.join(config.output,'trace.zip')});await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
