const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const config=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
assert.match(config.home,/[/\\]keivotos-modularization-[^/\\]+[/\\]home$/);
const report={checks:[],errors:[],covers:[],audio:[],timings:{}};
(async()=>{
 const browser=await chromium.launch({headless:true,channel:process.env.PLAYWRIGHT_CHANNEL});
 const context=await browser.newContext({viewport:{width:1440,height:1000}});
 await context.tracing.start({screenshots:true,snapshots:true});
 const page=await context.newPage();page.setDefaultTimeout(15000);
 page.on('pageerror',error=>report.errors.push(error.message));
 let expectedFailures=0,playbackStarted=false;
 page.on('response',response=>{
  if(response.status()<500)return;
  if(response.status()===503&&new URL(response.url()).pathname==='/api/ost/library'&&expectedFailures>0){expectedFailures--;return;}
  report.errors.push(`${response.status()} ${response.url()}`);
 });
 await page.route('**/*',route=>{
  const url=new URL(route.request().url());
  if(url.origin!==config.url){report.errors.push('Unexpected external request');return route.abort();}
  if(url.pathname==='/api/ost/cover')report.covers.push(url.searchParams.get('path'));
  if(url.pathname==='/api/files/file'){
   report.audio.push(url.searchParams.get('path'));
   if(!playbackStarted)report.errors.push('Discovery unexpectedly requested audio playback');
  }
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
 async function openFolder(relative){await row(relative).click();await page.getByRole('navigation',{name:'OST location'}).getByRole('button',{name:path.posix.basename(relative),exact:true}).waitFor();await page.waitForFunction(()=>document.querySelector('.ost-surface main')?.getAttribute('aria-busy')==='false');}
 async function back(){await page.locator('.ost-surface .back').click();await page.waitForFunction(()=>document.querySelector('.ost-surface main')?.getAttribute('aria-busy')==='false');}
 async function pixel(button){const image=button.locator('img');await image.waitFor();await page.waitForFunction(element=>element?.complete&&element.naturalWidth>0,await image.elementHandle());return image.evaluate(image=>{const canvas=document.createElement('canvas');canvas.width=1;canvas.height=1;const draw=canvas.getContext('2d');draw.drawImage(image,0,0);return [...draw.getImageData(0,0,1,1).data].slice(0,3);});}
 async function returnToRoots(){
  await page.getByRole('navigation',{name:'OST location'}).getByRole('button').first().click();
  await page.waitForFunction(()=>document.querySelector('.ost-surface main')?.getAttribute('aria-busy')==='false');
  await page.getByRole('button',{name:'Back to OST',exact:true}).click();await page.getByRole('list',{name:'OST folders'}).waitFor();
 }
 async function openSettings(){
  await page.getByRole('button',{name:'Open Keivotos menu',exact:true}).click();
  await page.locator('.app-drawer').getByRole('button',{name:'Settings',exact:true}).click();
  await page.getByRole('dialog',{name:'Settings',exact:true}).waitFor();
 }
 async function closeSettings(){
  await page.getByRole('button',{name:'Close settings',exact:true}).click();
  if(await page.getByRole('button',{name:'Close menu',exact:true}).count())await page.getByRole('button',{name:'Close menu',exact:true}).click();
  await page.locator('.app-drawer').waitFor({state:'detached'});
 }
 async function pauseAndBrowse(){
  await page.getByRole('region',{name:'OST player',exact:true}).waitFor();
  await page.waitForFunction(()=>{const audio=document.querySelector('audio');return audio&&audio.readyState>=2&&!audio.paused;});
  await page.getByRole('button',{name:'Pause',exact:true}).click();
  await page.getByRole('button',{name:'Back to tracks',exact:true}).click();
  await page.locator('.ost-surface main').waitFor({state:'visible'});
 }
 try{
  await page.goto(config.url);
  assert.equal((await api('/api/ost/cover')).status,409);
  assert.equal((await api('/api/suite/modules/ost/enable','POST')).status,200);
  const registration=await api('/api/suite/folders/apply','POST',{folders:[{path:config.media,display_name:'Soundtracks',role:'ost'}]});
  assert.equal(registration.status,200,JSON.stringify(registration));
  const owner=registration.data.sources.find(source=>source.role==='ost');
  await page.reload();await chooseModule();
  assert.equal(await page.getByRole('button',{name:'Manage OST folders',exact:true}).count(),0);
  assert.equal(await page.getByRole('heading',{name:'Soundtrack folders',exact:true}).count(),0);
  assert.equal(await root(owner.source_id).locator('.art').innerText(),'📁');
  await page.screenshot({path:path.join(config.output,'ost-sources-clean.png')});
  await root(owner.source_id).click();
  await row('Root track.wav').waitFor();
  assert.deepEqual(await page.getByRole('navigation',{name:'OST location'}).getByRole('button').allTextContents(),['Soundtracks']);
  assert.equal(await page.locator('.ost-surface main h2').count(),0);
  assert.equal(await row('Album 2').locator('.art').innerText(),'📁');
  assert.equal(await row('Album 2').locator('small').count(),0);
  await page.screenshot({path:path.join(config.output,'ost-folder-clean.png')});
  assert.deepEqual(await page.getByRole('list',{name:'OST folder contents'}).locator('.name').allTextContents(),['Album 2','Album 10','Corrupt art','Empty','Large library','No art','Root track.wav']);
  await openFolder('Album 2');
  assert.deepEqual(await page.getByRole('list',{name:'OST folder contents'}).locator('.name').allTextContents(),['Deep','00 - Opening.flac','A long soundtrack title with quiet rain and a distant train that wraps across two rows while its complete name remains readable 曲 2.wav','Track 2.wav','Track 10.wav']);
  const embedded=await pixel(row('Album 2/00 - Opening.flac'));
  const fallback=await pixel(row('Album 2/Track 2.wav'));
  assert(embedded[0]>embedded[2]+20);assert(fallback[2]>fallback[0]+20);
  assert.equal(report.audio.length,0);playbackStarted=true;
  await row('Album 2/Track 2.wav').click();await pauseAndBrowse();assert.equal(await row('Album 2/Track 2.wav').getAttribute('aria-pressed'),'true');
  assert.equal(await page.getByRole('switch',{name:'Auto next',exact:true}).getAttribute('aria-checked'),'true');
  const cover=await context.request.get(`${config.url}/api/ost/cover?source_id=${owner.source_id}&path=Album%202%2FTrack%202.wav`);
  assert.equal(cover.status(),200);assert.equal(cover.headers()['content-type'],'image/webp');assert.match(cover.headers()['cache-control'],/immutable/);
  check('actual hierarchy, mixed folders, natural names, local/embedded precedence and immutable WebP covers; discovery requests no audio, track click opens playback');

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
  await row('No art/broken.mp3').click();await page.getByRole('alert').filter({hasText:'This track is unavailable'}).waitFor();
  await page.getByRole('button',{name:'Back to tracks',exact:true}).click();assert.equal(await row('No art/broken.mp3').getAttribute('aria-pressed'),'true');
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
  const longTrack=page.getByRole('button',{name:/^Play track A long soundtrack title/});
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
  await openSettings();
  await closeSettings();
  await page.waitForFunction(()=>document.querySelector('[data-ost-entry-path="No art/Track 2.wav"]')?.getAttribute('aria-disabled')==='true');
  await page.waitForFunction(()=>document.querySelector('.ost-surface main')?.getAttribute('aria-busy')==='false');
  await row('No art/Track 2.wav').focus();await row('No art/Track 2.wav').press('Shift+F10');
  menu=page.getByRole('menu',{name:'Location for Track 2.wav'});
  assert.equal(await menu.getByRole('menuitem',{name:'Show in Files'}).isDisabled(),true);
  assert.equal(await menu.getByRole('menuitem',{name:'Open in Explorer'}).isDisabled(),true);
  await menu.press('Escape');assert.deepEqual(fs.readFileSync(preserved),originalBytes);fs.renameSync(preserved,original);
  await back();
  const childPath=config.media+'/Album 10';
  const second=await api('/api/suite/folders/apply','POST',{folders:[{path:childPath,display_name:'Soundtracks',role:'ost'}]});
  assert.equal(second.status,200,JSON.stringify(second));
  const child=second.data.sources.find(value=>value.path.replaceAll('\\','/')===childPath.replaceAll('\\','/'));
  const outer=await api(`/api/ost/library?source_id=${owner.source_id}`);assert(!outer.data.items.some(item=>item.path==='Album 10'));
  await page.reload();await page.getByRole('list',{name:'OST folders'}).waitFor();
  assert.equal(await page.getByRole('button',{name:'Open OST folder Soundtracks',exact:true}).count(),2);
  await root(child.source_id).click();await row('Track 2.wav').waitFor();
  assert.equal(await row('Album 2/Track 2.wav').count(),0);
  check('unavailable indexed audio remains recoverable with disabled location actions; originals preserved; duplicate source/track names retain separate nested ownership');

  await openSettings();
  const hidden=await api('/api/suite/folders/apply','POST',{folders:[{source_id:child.source_id,display_name:'Soundtracks',role:'ost',visible:false}]});assert.equal(hidden.status,200,JSON.stringify(hidden));
  await closeSettings();
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
  assert.deepEqual(await page.getByRole('navigation',{name:'OST location'}).getByRole('button').allTextContents(),['Soundtracks']);
  assert.equal(await row('Root track.wav').count(),1);await page.unroute('**/api/ost/library?**',delay);
  assert.deepEqual(report.errors,[]);
  check('closing Settings reconciles lost ownership; API failures retry; fast Back cancels delayed discovery without stale rows or focus');
  await page.screenshot({path:path.join(config.output,'ost-root-rows.png')});

  const audio=page.locator('audio');
  const player=()=>page.getByRole('region',{name:'OST player',exact:true});
  const transport=()=>page.getByRole('region',{name:'OST playback controls',exact:true});
  const play=()=>page.getByRole('button',{name:'Play',exact:true});
  const pause=()=>page.getByRole('button',{name:'Pause',exact:true});
  const loop=()=>page.getByRole('button',{name:/^Loop (off|all|one)$/});
  const auto=()=>page.getByRole('switch',{name:'Auto next',exact:true});
 async function waitTrack(relative){await page.waitForFunction(relative=>{const node=document.querySelector('audio');return node&&new URL(node.src).searchParams.get('path')===relative&&node.readyState>=2&&!node.paused;},relative);}
  async function paused(){if(await pause().count())await pause().click();await page.waitForFunction(()=>document.querySelector('audio')?.paused);}
  async function startTrack(relative){await row(relative).click();await player().waitFor();await waitTrack(relative);}
  async function finishTrack(){if(await play().count())await play().click();await page.waitForFunction(()=>{const node=document.querySelector('audio');return node&&!node.paused&&node.duration>0;});await audio.evaluate(node=>node.currentTime=node.duration-.12);}
  async function browse(){await page.getByRole('button',{name:'Back to tracks',exact:true}).click();await page.locator('.ost-surface main').waitFor({state:'visible'});}
  async function cycleTo(mode){for(let i=0;i<3&&await loop().getAttribute('aria-label')!==`Loop ${mode}`;i++)await loop().click();assert.equal(await loop().getAttribute('aria-label'),`Loop ${mode}`);}

  // OST transport uses no Video/YouTube implementation or enabled state.
  const modules=await api('/api/suite/modules');
  for(const id of ['video','youtube'])if(modules.data.find(value=>value.id===id)?.enabled)assert.equal((await api(`/api/suite/modules/${id}/disable`,'POST')).status,200);
  await openFolder('Album 2');await startTrack('Album 2/Track 2.wav');
  await page.waitForFunction(()=>document.querySelector('audio')?.currentTime>.05);
  assert(Math.abs(await audio.evaluate(node=>node.duration)-20)<.1);
  assert.equal(await auto().getAttribute('aria-checked'),'true');assert.equal(await loop().getAttribute('aria-label'),'Loop off');
  await paused();await player().focus();await page.keyboard.press('ArrowRight');
  assert(await audio.evaluate(node=>node.currentTime>=5&&node.currentTime<5.5));
  await page.keyboard.press('ArrowLeft');assert(await audio.evaluate(node=>node.currentTime<.5));
  await page.keyboard.press('Space');await page.waitForFunction(()=>!document.querySelector('audio')?.paused);
  await page.keyboard.down('Space');await page.keyboard.down('Space');await page.keyboard.up('Space');
  assert.equal(await audio.evaluate(node=>node.paused),true);
  const seek=page.getByRole('slider',{name:'Seek',exact:true});await seek.focus();await seek.press('Home');await seek.press('ArrowRight');
  assert(await audio.evaluate(node=>node.currentTime>0&&node.currentTime<.5));
  const volume=page.getByRole('slider',{name:'Volume',exact:true});
  const otherVolumes=await page.evaluate(()=>[localStorage.getItem('keivotos:video-volume-percent'),localStorage.getItem('keivotos:youtube-volume-percent')]);
  await volume.focus();await volume.press('Home');assert.equal(await audio.evaluate(node=>node.volume),0);
  await volume.press('End');assert.equal(await audio.evaluate(node=>node.volume),1);
  for(let i=0;i<6;i++)await volume.press('PageDown');for(let i=0;i<3;i++)await volume.press('ArrowRight');
  assert.equal(await volume.inputValue(),'43');assert.equal(await audio.evaluate(node=>node.volume),.43);
  await page.getByRole('button',{name:'Mute',exact:true}).click();assert.equal(await audio.evaluate(node=>node.volume),0);
  await page.getByRole('button',{name:'Unmute',exact:true}).click();assert.equal(await audio.evaluate(node=>node.volume),.43);
  assert.deepEqual(await page.evaluate(()=>[localStorage.getItem('keivotos:video-volume-percent'),localStorage.getItem('keivotos:youtube-volume-percent')]),otherVolumes);
  assert.equal(await page.evaluate(()=>localStorage.getItem('keivotos:ost-volume-percent')),'43');
  check('real WAV playback with Video/YouTube disabled; Space, repeat protection, five-second seeks, native slider keys, mute and independent 0–100 volume');

  for(const width of [1440,720,360]){
   await page.setViewportSize({width,height:1000});await page.waitForTimeout(120);
   const playBox=await play().boundingBox(),seekBox=await seek.boundingBox(),volumeBox=await volume.boundingBox();
   const currentBox=await page.getByLabel('Current time',{exact:true}).boundingBox(),durationBox=await page.getByLabel('Track duration',{exact:true}).boundingBox();
   assert(Math.abs(playBox.x+playBox.width/2-width/2)<2);
   assert(seekBox.y>playBox.y+playBox.height&&seekBox.y>volumeBox.y+volumeBox.height);
   assert(currentBox.x+currentBox.width<seekBox.x&&durationBox.x>seekBox.x+seekBox.width);
   assert(Math.abs(currentBox.y+currentBox.height/2-seekBox.y-seekBox.height/2)<2);
   assert(Math.abs(durationBox.y+durationBox.height/2-seekBox.y-seekBox.height/2)<2);
   assert(1000-seekBox.y-seekBox.height>=10);
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
   const nextBox=await page.getByRole('button',{name:'Next song',exact:true}).boundingBox(),previousBox=await page.getByRole('button',{name:'Previous song',exact:true}).boundingBox(),loopBox=await loop().boundingBox();
   assert(Math.abs((previousBox.x+nextBox.x+nextBox.width)/2-width/2)<2);
   assert(loopBox.x>=nextBox.x+nextBox.width&&loopBox.x+loopBox.width<=width);
   await page.screenshot({path:path.join(config.output,`ost-player-${width}.png`)});
  }
  await page.setViewportSize({width:1440,height:1000});
  const originalAudio=await audio.elementHandle();await player().focus();await page.keyboard.press('Escape');
  assert.equal(await row('Album 2/Track 2.wav').evaluate(node=>document.activeElement===node),true);
  await play().click();await openFolder('Album 2/Deep');
  assert.equal(await audio.elementHandle().then(handle=>handle.evaluate((node,old)=>node===old,originalAudio)),true);
  await page.waitForTimeout(150);assert.equal(await audio.evaluate(node=>node.paused),false);
  await page.getByRole('button',{name:'Open player for Track 2.wav',exact:true}).click();await player().waitFor();await browse();
  await row('Album 2/Deep/曲 2.wav').waitFor();await paused();await back();
  const longPath='Album 2/A long soundtrack title with quiet rain and a distant train that wraps across two rows while its complete name remains readable 曲 2.wav';
  await startTrack(longPath);await paused();await page.setViewportSize({width:360,height:1000});
  assert.equal(await player().locator('h2').getAttribute('title'),path.posix.basename(longPath));
  assert.equal(await player().locator('h2').evaluate(node=>getComputedStyle(node).webkitLineClamp),'2');
  assert((await player().locator('h2').boundingBox()).height<=60);
  await page.screenshot({path:path.join(config.output,'ost-player-long-title-360.png')});
  await page.setViewportSize({width:1440,height:1000});await browse();
  check('centered Play and bottom seek bar fit 1440/720/360px; Escape restores row focus; the same audio continues through folder browsing and cover-view return');

  await startTrack('Album 2/Track 2.wav');await paused();
  await page.getByRole('button',{name:'Next song',exact:true}).click();await waitTrack('Album 2/Track 10.wav');await paused();
  assert.equal(await page.getByRole('button',{name:'Next song',exact:true}).isDisabled(),true);
  await page.getByRole('button',{name:'Previous song',exact:true}).click();await waitTrack('Album 2/Track 2.wav');await paused();
  await finishTrack();await waitTrack('Album 2/Track 10.wav');await paused();
  await finishTrack();await page.waitForFunction(()=>document.querySelector('audio')?.ended);
  assert.equal(new URL(await audio.getAttribute('src')).searchParams.get('path'),'Album 2/Track 10.wav');
  await auto().click();assert.equal(await auto().getAttribute('aria-checked'),'false');
  await cycleTo('one');await finishTrack();
  await page.waitForFunction(()=>{const node=document.querySelector('audio');return node&&!node.paused&&!node.ended&&node.currentTime<1;});
  assert.equal(new URL(await audio.getAttribute('src')).searchParams.get('path'),'Album 2/Track 10.wav');await paused();
  await cycleTo('off');await finishTrack();await page.waitForFunction(()=>document.querySelector('audio')?.ended);
  await auto().click();await cycleTo('all');await finishTrack();await waitTrack('Album 2/00 - Opening.flac');await paused();
  await page.getByRole('button',{name:'Previous song',exact:true}).click();await waitTrack('Album 2/Track 10.wav');await paused();
  await cycleTo('off');await browse();
  check('natural ended events advance with Auto next, Off stops at the folder boundary, One repeats independently, All wraps in both directions; actual FLAC decodes');

  await back();await openFolder('Large library');await page.getByText('120 / 260 items',{exact:true}).waitFor();
  await startTrack('Large library/Track 120.wav');await paused();
  await page.getByRole('button',{name:'Next song',exact:true}).click();await waitTrack('Large library/Track 121.wav');await paused();await browse();
  await page.getByText('120 / 260 items',{exact:true}).waitFor();
  assert.equal(await row('Large library/Track 121.wav').count(),0);
  await page.getByRole('button',{name:'Load more',exact:true}).click();await row('Large library/Track 121.wav').waitFor();
  assert.equal(await row('Large library/Track 121.wav').getAttribute('aria-pressed'),'true');
  await startTrack('Large library/Track 1.wav');await paused();await cycleTo('all');
  await page.getByRole('button',{name:'Previous song',exact:true}).click();await waitTrack('Large library/Track 260.wav');await paused();await cycleTo('off');await browse();
  await back();await openFolder('Large library');
  // Restore 240 loaded rows, then deliberately return to a fresh 120-row listing.
  await page.reload();await root(owner.source_id).click();await openFolder('Large library');
  let resolveQueue;const queueStarted=new Promise(resolve=>resolveQueue=resolve);
  const queueDelay=async route=>{if(new URL(route.request().url()).searchParams.get('parent')==='Large library'&&new URL(route.request().url()).searchParams.get('offset')==='120'){resolveQueue();await new Promise(resolve=>setTimeout(resolve,450));}return route.continue().catch(()=>{});};
  await page.route('**/api/ost/library?**',queueDelay);
  await startTrack('Large library/Track 120.wav');await paused();await page.getByRole('button',{name:'Next song',exact:true}).click();await queueStarted;
  assert.equal(await page.getByRole('button',{name:'Next song',exact:true}).isDisabled(),true);
  await browse();await startTrack('Large library/Track 2.wav');await paused();await page.waitForTimeout(550);
  assert.equal(new URL(await audio.getAttribute('src')).searchParams.get('path'),'Large library/Track 2.wav');
  await page.unroute('**/api/ost/library?**',queueDelay);await browse();
  let queueFailure=true;expectedFailures++;
  const failQueue=async route=>{const url=new URL(route.request().url());if(queueFailure&&url.searchParams.get('parent')==='Large library'&&url.searchParams.get('offset')==='120'){queueFailure=false;return route.fulfill({status:503,json:{detail:'Generated queue failure'}});}return route.continue();};
  await page.route('**/api/ost/library?**',failQueue);await startTrack('Large library/Track 120.wav');await paused();
  await page.getByRole('button',{name:'Next song',exact:true}).click();await page.getByRole('status').filter({hasText:'Generated queue failure'}).waitFor();
  assert.equal(new URL(await audio.getAttribute('src')).searchParams.get('path'),'Large library/Track 120.wav');
  await page.getByRole('button',{name:'Next song',exact:true}).click();await waitTrack('Large library/Track 121.wav');await paused();
  await page.unroute('**/api/ost/library?**',failQueue);await browse();await back();
  check('queue crosses unloaded pages and wraps the current folder without changing browse pagination; rapid selection cancels delayed Next; failed queue extension retries without losing the track');

  await openFolder('Album 2');
  await page.evaluate(()=>{
   window.__ostPlay=HTMLMediaElement.prototype.play;window.__ostDeny=true;
   HTMLMediaElement.prototype.play=function(){if(this.tagName==='AUDIO'&&window.__ostDeny){window.__ostDeny=false;return Promise.reject(new DOMException('Generated policy rejection','NotAllowedError'));}return window.__ostPlay.call(this);};
  });
  await row('Album 2/Track 2.wav').click();await page.getByRole('status').filter({hasText:'Press Play to start audio.'}).waitFor();
  assert.equal(await page.getByRole('alert').count(),0);assert.equal(await play().isDisabled(),false);
  await play().click();await page.waitForFunction(()=>!document.querySelector('audio')?.paused);await paused();
  await page.evaluate(()=>{HTMLMediaElement.prototype.play=window.__ostPlay;delete window.__ostPlay;});await browse();
  await page.evaluate(()=>{
   window.__ostPlay=HTMLMediaElement.prototype.play;window.__ostDelay=true;
   HTMLMediaElement.prototype.play=function(){if(this.tagName==='AUDIO'&&window.__ostDelay){window.__ostDelay=false;return new Promise((resolve,reject)=>setTimeout(()=>reject(new Error('Generated stale playback failure')),350));}return window.__ostPlay.call(this);};
  });
  await row('Album 2/Track 2.wav').click();await player().waitFor();await browse();await startTrack('Album 2/Track 10.wav');await paused();await page.waitForTimeout(450);
  assert.equal(await page.getByRole('alert').count(),0);
  await page.evaluate(()=>{HTMLMediaElement.prototype.play=window.__ostPlay;delete window.__ostPlay;});await browse();await back();
  await openFolder('No art');
  const missing=path.join(config.mediaLocal||config.media,'No art','Track 2.wav'),saved=path.join(config.mediaLocal||config.media,'No art','preserved-for-playback.wav');
  const savedBytes=fs.readFileSync(missing);fs.renameSync(missing,saved);
  await row('No art/Track 2.wav').click();await page.getByRole('alert').filter({hasText:/track.*(unavailable|play)/}).waitFor();
  assert.equal(await play().isDisabled(),true);fs.renameSync(saved,missing);assert.deepEqual(fs.readFileSync(missing),savedBytes);
  await page.getByRole('button',{name:'Retry track',exact:true}).click();await page.waitForFunction(()=>{const node=document.querySelector('audio');return node&&node.readyState>=2&&!node.paused;});await paused();await browse();
  await row('No art/broken.mp3').click();await page.getByRole('alert').waitFor();
  await page.getByRole('button',{name:'Next song',exact:true}).click();await waitTrack('No art/Track 2.wav');await paused();await browse();await back();
  check('autoplay policy keeps Play usable; stale play rejection cannot damage a newer track; actual missing/corrupt audio explains failure and Retry/Next recover with original bytes preserved');

  await openFolder('Album 2');
  let resolveMedia;const mediaStarted=new Promise(resolve=>resolveMedia=resolve);
  const mediaDelay=async route=>{if(new URL(route.request().url()).searchParams.get('path')==='Album 2/00 - Opening.flac'){resolveMedia();await new Promise(resolve=>setTimeout(resolve,450));}return route.continue().catch(()=>{});};
  await page.route('**/api/files/file?**',mediaDelay);
  await row('Album 2/00 - Opening.flac').click();await mediaStarted;
  assert.equal(await page.getByRole('button',{name:'Next song',exact:true}).isDisabled(),false);
  await page.getByRole('button',{name:'Next song',exact:true}).click();await waitTrack(longPath);await paused();await page.waitForTimeout(550);
  assert.equal(await page.getByRole('alert').count(),0);
  assert.equal(new URL(await audio.getAttribute('src')).searchParams.get('path'),longPath);
  await page.unroute('**/api/files/file?**',mediaDelay);await browse();await back();
  check('Next stays usable during actual delayed media loading; cancelled old media events and play promises cannot replace or fail the new track');

  // Verify decoded nonzero PCM through the browser audio graph; hardware output is not asserted.
  await startTrack('Root track.wav');
  await cycleTo('all');await finishTrack();
  await page.waitForFunction(()=>{const node=document.querySelector('audio');return node&&!node.paused&&!node.ended&&node.currentTime<1;});
  assert.equal(new URL(await audio.getAttribute('src')).searchParams.get('path'),'Root track.wav');
  await cycleTo('off');
  await page.waitForFunction(()=>document.querySelector('audio')?.currentTime>.05);
  const signal=await audio.evaluate(async node=>{
   const graph=new AudioContext(),source=graph.createMediaElementSource(node),analyser=graph.createAnalyser();
   analyser.fftSize=256;source.connect(analyser);analyser.connect(graph.destination);await graph.resume();
   let rms=0;const data=new Float32Array(analyser.fftSize);
   for(let i=0;i<20&&rms<=.001;i++){await new Promise(resolve=>setTimeout(resolve,50));analyser.getFloatTimeDomainData(data);rms=Math.sqrt(data.reduce((sum,value)=>sum+value*value,0)/data.length);}
   const facts={rms,graphState:graph.state,paused:node.paused,muted:node.muted,time:node.currentTime,duration:node.duration,volume:node.volume};
   await graph.close();return facts;
  });
  report.timings.decodedAudio=signal;assert(signal.rms>.001,JSON.stringify(signal));
  await audio.evaluate(node=>window.__releasedAudio=node);
  await page.getByRole('button',{name:'Open Keivotos menu',exact:true}).click();await page.locator('.app-drawer').getByRole('button',{name:'Files',exact:true}).click();
  await page.locator('.audio-player').waitFor({state:'detached'});
  assert.equal(await page.evaluate(()=>window.__releasedAudio.paused&&window.__releasedAudio.getAttribute('src')===null&&window.__releasedAudio.readyState===0),true);
  await page.waitForTimeout(200);assert.equal(await page.evaluate(()=>window.__releasedAudio.currentTime),0);
  await chooseModule();await root(owner.source_id).click();await openFolder('Album 2');await startTrack('Album 2/Track 2.wav');
  assert.equal(await audio.evaluate(node=>node.volume),.43);assert.equal(await auto().getAttribute('aria-checked'),'true');
  await audio.evaluate(node=>window.__releasedAudio=node);
  await openSettings();
  assert.equal((await api('/api/suite/folders/apply','POST',{folders:[{source_id:owner.source_id,display_name:'Soundtracks',role:'ost',visible:false}]})).status,200);
  await closeSettings();
  await page.locator('.audio-player').waitFor({state:'detached'});
  assert.equal(await page.evaluate(()=>window.__releasedAudio.paused&&window.__releasedAudio.getAttribute('src')===null),true);
  assert.equal((await api('/api/suite/folders/apply','POST',{folders:[{source_id:owner.source_id,display_name:'Soundtracks',role:'ost',visible:true}]})).status,200);
  await page.reload();await root(owner.source_id).click();await openFolder('Album 2');await startTrack('Album 2/Track 2.wav');
  await audio.evaluate(node=>window.__releasedAudio=node);
  await openSettings();
  await page.getByRole('navigation',{name:'Settings sections'}).getByRole('button',{name:'Modules',exact:true}).click();
  const ostSwitch=page.getByRole('switch',{name:'OST module',exact:true});await page.waitForFunction(()=>document.querySelector('[role="switch"][aria-label="OST module"]')?.disabled===false);await ostSwitch.click();
  await page.locator('.ost-surface').waitFor({state:'detached'});
  assert.equal(await page.evaluate(()=>window.__releasedAudio.paused&&window.__releasedAudio.getAttribute('src')===null),true);
  await closeSettings();
  check('a one-track folder replays under All; browser audio graph decodes nonzero PCM; source loss/module exit/disable release media; scoped OST preferences survive reload/re-entry');
  assert.deepEqual(report.errors,[]);
 }finally{
  fs.writeFileSync(path.join(config.output,'report.json'),JSON.stringify(report,null,2));
  await context.tracing.stop({path:path.join(config.output,'trace.zip')});await browser.close();
 }
})().catch(error=>{console.error(error);process.exitCode=1;});
