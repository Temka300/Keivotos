const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const config=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
assert.match(config.home,/[/\\]keivotos-modularization-[^/\\]+[/\\]home$/);
const report={checks:[],errors:[],covers:[],timings:{}};
(async()=>{
 const browser=await chromium.launch({headless:true,channel:process.env.PLAYWRIGHT_CHANNEL});
 const context=await browser.newContext({viewport:{width:1440,height:1000}});
 await context.tracing.start({screenshots:true,snapshots:true});
 const page=await context.newPage();page.setDefaultTimeout(15000);
 page.on('pageerror',error=>report.errors.push(error.message));
 let expectedFailures=0;
 page.on('response',response=>{
  if(response.status()<500)return;
  if(response.status()===503&&new URL(response.url()).pathname==='/api/ost/library'&&expectedFailures>0){expectedFailures--;return;}
  report.errors.push(`${response.status()} ${response.url()}`);
 });
 await page.route('**/*',route=>{
  const url=new URL(route.request().url());
  if(url.origin!==config.url){report.errors.push('Unexpected external request');return route.abort();}
  if(url.pathname==='/api/ost/cover')report.covers.push(url.searchParams.get('path'));
  if(url.pathname==='/api/files/file')report.errors.push('Discovery unexpectedly requested audio playback');
  return route.continue();
 });
 const check=message=>{report.checks.push(message);console.log('PASS: '+message);};
 const row=relative=>page.getByRole('list',{name:'OST folder contents'}).locator(`[data-ost-entry-path=${JSON.stringify(relative)}]`);
 const root=id=>page.getByRole('list',{name:'OST folders'}).locator(`[data-ost-source=${JSON.stringify(id)}]`);
 async function api(url,method='GET',body){return page.evaluate(async({url,method,body})=>{
  const response=await fetch(url,{method,headers:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});
  return {status:response.status,data:await response.json()};
 },{url,method,body});}
 async function chooseModule(){
  await page.getByRole('button',{name:'Open Keivotos menu',exact:true}).click();
  await page.locator('.app-drawer').getByRole('button',{name:'OST',exact:true}).click();
  await page.getByRole('list',{name:'OST folders'}).waitFor();
 }
 async function openFolder(relative){await row(relative).click();await page.getByRole('heading',{name:path.posix.basename(relative),exact:true}).waitFor();await page.waitForFunction(()=>document.querySelector('.ost-surface main')?.getAttribute('aria-busy')==='false');}
 async function back(){await page.locator('.ost-surface .back').click();await page.waitForFunction(()=>document.querySelector('.ost-surface main')?.getAttribute('aria-busy')==='false');}
 async function pixel(button){const image=button.locator('img');await image.waitFor();await page.waitForFunction(element=>element?.complete&&element.naturalWidth>0,await image.elementHandle());return image.evaluate(image=>{const canvas=document.createElement('canvas');canvas.width=1;canvas.height=1;const draw=canvas.getContext('2d');draw.drawImage(image,0,0);return [...draw.getImageData(0,0,1,1).data].slice(0,3);});}
 async function returnToRoots(){await page.getByRole('navigation',{name:'OST location'}).getByRole('button',{name:'Soundtrack folders',exact:true}).click();await page.getByRole('list',{name:'OST folders'}).waitFor();}
 try{
  await page.goto(config.url);
  assert.equal((await api('/api/ost/cover')).status,409);
  assert.equal((await api('/api/suite/modules/ost/enable','POST')).status,200);
  const registration=await api('/api/suite/folders/apply','POST',{folders:[{path:config.media,display_name:'Soundtracks',role:'ost'}]});
  assert.equal(registration.status,200,JSON.stringify(registration));
  const owner=registration.data.sources.find(source=>source.role==='ost');
  await page.reload();await chooseModule();await root(owner.source_id).click();
  await row('Root track.wav').waitFor();
  assert.deepEqual(await page.getByRole('list',{name:'OST folder contents'}).locator('.name').allTextContents(),['Album 2','Album 10','Corrupt art','Empty','Large library','No art','Root track.wav']);
  await openFolder('Album 2');
  assert.deepEqual(await page.getByRole('list',{name:'OST folder contents'}).locator('.name').allTextContents(),['Deep','00 - Opening.flac','A long soundtrack title with quiet rain and a distant train that wraps across two rows while its complete name remains readable 曲 2.wav','Track 2.wav','Track 10.wav']);
  const embedded=await pixel(row('Album 2/00 - Opening.flac'));
  const fallback=await pixel(row('Album 2/Track 2.wav'));
  assert(embedded[0]>embedded[2]+20);assert(fallback[2]>fallback[0]+20);
  await row('Album 2/Track 2.wav').click();assert.equal(await row('Album 2/Track 2.wav').getAttribute('aria-pressed'),'true');
  const cover=await context.request.get(`${config.url}/api/ost/cover?source_id=${owner.source_id}&path=Album%202%2FTrack%202.wav`);
  assert.equal(cover.status(),200);assert.equal(cover.headers()['content-type'],'image/webp');assert.match(cover.headers()['cache-control'],/immutable/);
  check('actual hierarchy, mixed folders, natural names, local/embedded precedence and immutable WebP covers; tracks select without audio requests');

  await openFolder('Album 2/Deep');
  await row('Album 2/Deep/曲 2.wav').locator('img').waitFor({state:'detached'});
  await back();await row('Album 2/Deep').waitFor();
  assert.equal(await row('Album 2/Deep').evaluate(element=>document.activeElement===element),true);
  assert.equal(await row('Album 2/Track 2.wav').getAttribute('aria-pressed'),'true');
  await back();await openFolder('Corrupt art');
  const recovered=await pixel(row('Corrupt art/Track 2.wav'));assert(recovered[0]>recovered[1]+15);
  await back();await openFolder('Empty');
  await page.getByRole('status').filter({hasText:'No folders or supported audio files here.'}).waitFor();
  await back();await openFolder('No art');
  await row('No art/Track 2.wav').locator('img').waitFor({state:'detached'});
  assert.equal(await row('No art/unsupported.aac').count(),0);
  assert.equal(await row('No art/note.txt').count(),0);
  await row('No art/broken.mp3').click();assert.equal(await row('No art/broken.mp3').getAttribute('aria-pressed'),'true');
  check('nested Unicode, ancestor-only Back, focus/selection restoration, corrupt-art fallback, empty folders and neutral no-art/unsupported states');

  await back();await openFolder('Large library');
  await page.getByText('120 / 260 items',{exact:true}).waitFor();
  assert.equal(await page.getByRole('list',{name:'OST folder contents'}).locator('li').count(),120);
  await page.waitForTimeout(200);
  const firstPageCovers=report.covers.filter(value=>/^Large library\/Track /.test(value));
  assert(firstPageCovers.length<=120);
  const scroller=page.locator('.ost-surface main');
  await scroller.evaluate(element=>element.scrollTop=element.scrollHeight);
  const before=await scroller.evaluate(element=>element.scrollTop);
  report.timings.largeFolderSavedScroll=before;
  await page.getByRole('button',{name:'Load more',exact:true}).click();
  await page.getByText('240 / 260 items',{exact:true}).waitFor();
  report.timings.largeFolderMoreScroll=await scroller.evaluate(element=>element.scrollTop);
  assert(Math.abs(await scroller.evaluate(element=>element.scrollTop)-before)<3);
  const navigateAt=Date.now();await back();await openFolder('Large library');
  await page.getByText('240 / 260 items',{exact:true}).waitFor();
  report.timings.largeFolderReturnScroll=await scroller.evaluate(element=>element.scrollTop);
  assert(Math.abs(await scroller.evaluate(element=>element.scrollTop)-before)<3);
  report.timings.largeFolderReturnMs=Date.now()-navigateAt;
  await page.getByRole('button',{name:'Load more',exact:true}).click();await page.getByText('260 / 260 items',{exact:true}).waitFor();
  assert.equal(await page.getByRole('button',{name:'Load more',exact:true}).count(),0);
  assert.equal(await page.getByRole('list',{name:'OST folder contents'}).locator('li').count(),260);
  report.timings.firstPageCoverRequests=firstPageCovers.length;
  check('260-track folder paginates 120/240/260; images stay within loaded pages; Load more and Back retain count and scroll');

  await back();await openFolder('Album 2');
  const backButton=page.locator('.ost-surface .back');await page.mouse.move(1000,800);await page.waitForTimeout(230);
  assert(Math.abs((await backButton.boundingBox()).width-40)<1);
  await backButton.hover();await page.waitForTimeout(60);const middle=(await backButton.boundingBox()).width;assert(middle>40&&middle<56);
  await page.waitForTimeout(190);assert(Math.abs((await backButton.boundingBox()).width-56)<1);
  await page.mouse.move(1000,800);await page.waitForTimeout(230);assert(Math.abs((await backButton.boundingBox()).width-40)<1);
  await page.evaluate(()=>document.documentElement.dataset.motion='reduced');await backButton.hover();
  assert(await backButton.evaluate(element=>parseFloat(getComputedStyle(element).transitionDuration)<=.001));
  await page.evaluate(()=>delete document.documentElement.dataset.motion);
  const longTrack=page.getByRole('button',{name:/^Select track A long soundtrack title/});
  for(const width of [1440,720,360]){
   await page.setViewportSize({width,height:1000});await page.waitForTimeout(120);
   assert.equal(await longTrack.getAttribute('title'),'A long soundtrack title with quiet rain and a distant train that wraps across two rows while its complete name remains readable 曲 2.wav');
   assert.equal(await longTrack.locator('.name').evaluate(element=>getComputedStyle(element).webkitLineClamp),'2');
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));
   await page.screenshot({path:path.join(config.output,`ost-album-${width}.png`)});
  }
  await page.setViewportSize({width:1440,height:1000});
  check('Back expands/reverses with real timing and reduced motion; long names and rows fit desktop, 720px and 360px');

  let revealed,resolveReveal;const revealStarted=new Promise(resolve=>resolveReveal=resolve);
  const reveal=async route=>{revealed=route.request().postDataJSON();resolveReveal();await route.fulfill({json:{status:'revealed'}});};
  await page.route('**/api/files/reveal',reveal);
  const track=row('Album 2/Track 2.wav');await track.focus();await track.press('Shift+F10');
  let menu=page.getByRole('menu',{name:'Location for Track 2.wav'});
  assert.deepEqual(await menu.getByRole('menuitem').allTextContents(),['Show in Files','Open in Explorer']);
  await menu.getByRole('menuitem',{name:'Show in Files'}).waitFor({state:'visible'});
  await page.waitForFunction(()=>document.querySelector('[role="menu"] [role="menuitem"]')?.disabled===false);
  await page.waitForFunction(()=>document.activeElement?.textContent==='Show in Files');
  await page.keyboard.press('ArrowDown');
  await page.waitForFunction(()=>document.activeElement?.textContent==='Open in Explorer');
  await page.keyboard.press('Enter');await revealStarted;
  assert.deepEqual(revealed,{source_id:owner.source_id,path:'Album 2/Track 2.wav'});
  await track.click({button:'right'});await menu.getByRole('menuitem',{name:'Show in Files'}).click();
  const shown=page.locator('[data-files-entry-path="Album 2/Track 2.wav"]');await shown.waitFor();
  assert.equal(await shown.evaluate(element=>document.activeElement===element),true);
  await chooseModule();await root(owner.source_id).click();await row('Album 2').click({button:'right'});
  await page.getByRole('menu',{name:'Location for Album 2'}).getByRole('menuitem',{name:'Show in Files'}).click();
  await page.locator('[data-files-breadcrumb-path="Album 2"]').waitFor();
  await chooseModule();await root(owner.source_id).click();await openFolder('Album 2');
  await row('Album 2/Deep').click({button:'right'});
  await page.getByRole('menu',{name:'Location for Deep'}).press('Escape');
  assert.equal(await row('Album 2/Deep').evaluate(element=>document.activeElement===element),true);
  await page.unroute('**/api/files/reveal',reveal);
  check('native right-click/Shift+F10 location menus have two actions, reveal exact identity, show track/folder in Files and restore focus on Escape');

  await back();await openFolder('No art');
  const original=path.join(config.mediaLocal||config.media,'No art','Track 2.wav'),preserved=path.join(config.mediaLocal||config.media,'No art','preserved.wav');
  const originalBytes=fs.readFileSync(original);fs.renameSync(original,preserved);
  await page.getByRole('button',{name:'Manage OST folders'}).click();
  await page.getByRole('button',{name:'Close settings',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('[data-ost-entry-path="No art/Track 2.wav"]')?.getAttribute('aria-disabled')==='true');
  await page.waitForFunction(()=>document.querySelector('.ost-surface main')?.getAttribute('aria-busy')==='false');
  assert.equal(await page.getByRole('button',{name:'Manage OST folders'}).evaluate(element=>document.activeElement===element),true);
  await row('No art/Track 2.wav').focus();await row('No art/Track 2.wav').press('Shift+F10');
  menu=page.getByRole('menu',{name:'Location for Track 2.wav'});
  assert.equal(await menu.getByRole('menuitem',{name:'Show in Files'}).isDisabled(),true);
  assert.equal(await menu.getByRole('menuitem',{name:'Open in Explorer'}).isDisabled(),true);
  await menu.press('Escape');assert.deepEqual(fs.readFileSync(preserved),originalBytes);fs.renameSync(preserved,original);
  await back();
  const childPath=config.media+'/Album 10';
  const second=await api('/api/suite/folders/apply','POST',{folders:[{path:childPath,display_name:'Soundtracks',role:'ost'}]});
  assert.equal(second.status,200,JSON.stringify(second));
  const child=second.data.sources.find(value=>value.path===childPath);
  const outer=await api(`/api/ost/library?source_id=${owner.source_id}`);assert(!outer.data.items.some(item=>item.path==='Album 10'));
  await page.reload();await page.getByRole('list',{name:'OST folders'}).waitFor();
  assert.equal(await page.getByRole('button',{name:'Open OST folder Soundtracks',exact:true}).count(),2);
  await root(child.source_id).click();await row('Track 2.wav').waitFor();
  assert.equal(await row('Album 2/Track 2.wav').count(),0);
  check('unavailable indexed audio remains recoverable with disabled location actions; originals preserved; duplicate source/track names retain separate nested ownership');

  await page.getByRole('button',{name:'Manage OST folders'}).click();
  const hidden=await api('/api/suite/folders/apply','POST',{folders:[{source_id:child.source_id,display_name:'Soundtracks',role:'ost',visible:false}]});assert.equal(hidden.status,200,JSON.stringify(hidden));
  await page.getByRole('button',{name:'Close settings',exact:true}).click();
  await page.getByRole('status').filter({hasText:'This folder is no longer assigned to OST.'}).waitFor();
  await root(owner.source_id).click();await row('No art').waitFor();
  let failOnce=true;expectedFailures=1;
  const failure=async route=>{if(failOnce&&new URL(route.request().url()).searchParams.get('parent')==='No art'){failOnce=false;return route.fulfill({status:503,json:{detail:'Generated discovery failure'}});}return route.continue();};
  await page.route('**/api/ost/library?**',failure);await row('No art').click();
  await page.getByRole('alert').filter({hasText:'Generated discovery failure'}).getByRole('button',{name:'Retry',exact:true}).click();
  await row('No art/Track 2.wav').waitFor();await page.unroute('**/api/ost/library?**',failure);await back();
  let start;const started=new Promise(resolve=>start=resolve);
  const delay=async route=>{if(new URL(route.request().url()).searchParams.get('parent')==='Empty'){start();await new Promise(resolve=>setTimeout(resolve,450));}return route.continue();};
  await page.route('**/api/ost/library?**',delay);await row('Empty').click();await started;await back();
  await row('Root track.wav').waitFor();await page.waitForTimeout(550);
  assert.equal(await page.getByRole('heading',{name:'Soundtracks',exact:true}).count(),1);
  assert.equal(await row('Root track.wav').count(),1);await page.unroute('**/api/ost/library?**',delay);
  assert.deepEqual(report.errors,[]);
  check('closing Settings reconciles lost ownership; API failures retry; fast Back cancels delayed discovery without stale rows or focus');
  await page.screenshot({path:path.join(config.output,'ost-root-rows.png')});
 }finally{
  fs.writeFileSync(path.join(config.output,'report.json'),JSON.stringify(report,null,2));
  await context.tracing.stop({path:path.join(config.output,'trace.zip')});await browser.close();
 }
})().catch(error=>{console.error(error);process.exitCode=1;});
