const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const config=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
(async()=>{
 const browser=await chromium.launch({headless:true,channel:process.env.PLAYWRIGHT_CHANNEL});
 const context=await browser.newContext({viewport:{width:1440,height:1000}});
 const page=await context.newPage();page.setDefaultTimeout(15000);
 const report={checks:[],errors:[],failures:[]};page.on('pageerror',e=>report.errors.push(e.message));
 page.on('request',r=>{if(r.url().endsWith('/api/video/playback-error'))report.failures.push(r.postDataJSON());});
 await context.tracing.start({screenshots:true,snapshots:true});
 const check=x=>{report.checks.push(x);console.log('PASS: '+x);};
 async function api(url,method='GET',body){return page.evaluate(async({url,method,body})=>{const r=await fetch(url,{method,headers:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});return {status:r.status,data:await r.json()};},{url,method,body});}
 async function back(){await page.getByRole('button',{name:'Back to videos'}).click();await page.getByRole('dialog',{name:'Video player'}).waitFor({state:'detached'});}
 try{
  await page.goto(config.url);
  assert.equal((await api('/api/video/library')).status,409);
  assert.equal((await api('/api/suite/modules/video/enable','POST')).status,200);
  const add=await api('/api/suite/folders/apply','POST',{folders:[{path:config.media,display_name:'Videos',role:'video'}]});assert.equal(add.status,200,JSON.stringify(add));
  const library=await api('/api/video/library');assert.equal(library.data.total,5);assert.equal(library.data.items.some(x=>x.name==='notes.txt'),false);
  await page.getByRole('button',{name:'Open Keivotos menu'}).click();await page.locator('.app-drawer').getByRole('button',{name:'Video',exact:true}).click();
  await page.getByRole('button',{name:'sample.mp4',exact:true}).waitFor();
  await page.getByLabel('Search videos').fill('sample.webm');await page.waitForTimeout(400);
  assert.equal(await page.locator('.video-tile').count(),1);
  await page.getByLabel('Search videos').fill('');await page.waitForTimeout(400);
  await page.screenshot({path:path.join(config.output,'library.png')});
  check('Video enables, adopts a folder, filters indexed media and searches names');
  for(const name of ['sample.mp4','sample.m4v','sample.webm']){
   await page.getByRole('button',{name,exact:true}).click();
   await page.waitForFunction(()=>document.querySelector('video')?.currentTime>0.1);
   const rect=await page.locator('.video-viewer').boundingBox();assert.equal(rect.width,1440);assert.equal(rect.height,1000);
   await page.getByRole('button',{name:'Pause',exact:true}).click();assert(await page.locator('video').evaluate(v=>v.paused));
   await page.getByLabel('Seek',{exact:true}).fill('2');await page.getByLabel('Seek',{exact:true}).dispatchEvent('input');
   await page.waitForFunction(()=>document.querySelector('video').currentTime>=1.9);
   await page.getByRole('button',{name:'Play',exact:true}).click();await page.waitForFunction(()=>!document.querySelector('video').paused);
   await page.getByRole('button',{name:'Fullscreen',exact:true}).click();await page.waitForFunction(()=>!!document.fullscreenElement);
   await page.getByRole('button',{name:'Fullscreen',exact:true}).click();await page.waitForFunction(()=>!document.fullscreenElement);
   await page.screenshot({path:path.join(config.output,'player-'+name+'.png')});await back();
  }
  check('real H.264 MP4/M4V and VP8 WebM decode, pause, seek, resume and enter/exit fullscreen in a full-browser player');
  await page.getByRole('button',{name:'sample.mp4',exact:true}).click();
  const backButton=page.getByRole('button',{name:'Back to videos'});
  await page.mouse.move(700,400);
  assert.equal(await backButton.innerText(),'');
  const restingWidth=(await backButton.boundingBox()).width;
  await backButton.hover();await page.waitForTimeout(250);
  assert((await backButton.boundingBox()).width>restingWidth);
  assert.equal(await backButton.evaluate(node=>getComputedStyle(node).backgroundColor),'rgb(51, 51, 59)');
  assert.equal(await backButton.evaluate(node=>getComputedStyle(node).borderTopWidth),'0px');
  await page.screenshot({path:path.join(config.output,'player-back-hover.png')});
  const seekBox=await page.getByLabel('Seek',{exact:true}).boundingBox();
  const playBox=await page.getByRole('button',{name:/^(Play|Pause)$/}).boundingBox();
  assert(seekBox.y+seekBox.height<=playBox.y);
  await page.getByRole('button',{name:'Next video',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('video').src.includes('sample.webm'));
  await page.getByRole('button',{name:'Previous video',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('video').src.includes('sample.mp4'));
  await back();assert(await page.getByRole('button',{name:'sample.mp4',exact:true}).evaluate(node=>node===document.activeElement));
  check('borderless chevron expands to an opaque hover pill; seek sits above transport; previous/next retain originating focus');

  for(const name of ['unsupported.avi','broken.mp4']){await page.getByRole('button',{name,exact:true}).click();await page.getByRole('alert').filter({hasText:'See Logs'}).waitFor();await page.waitForTimeout(200);await back();}
  assert(report.failures.some(x=>x.reason==='unsupported_format'));assert(report.failures.some(x=>['decode','unsupported_codec','playback'].includes(x.reason)));
  check('unsupported container and broken video report bounded diagnostic events without crashing');
  await page.getByRole('button',{name:'sample.webm',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('video')?.currentTime>0.1);
  await page.locator('.video-viewer').evaluate(node=>node.requestFullscreen=()=>Promise.reject(new Error('fixture unavailable')));
  await page.getByRole('button',{name:'Fullscreen',exact:true}).click();
  await page.getByRole('alert').filter({hasText:'Fullscreen is unavailable'}).waitFor();
  await page.getByRole('button',{name:'Pause',exact:true}).click();
  assert(await page.locator('video').evaluate(v=>v.paused));
  await page.getByRole('button',{name:'Fullscreen',exact:true}).focus();await page.keyboard.press('Tab');
  assert.equal(await page.getByRole('button',{name:'Back to videos'}).evaluate(node=>node===document.activeElement),true);
  await back();assert.equal(await page.getByRole('button',{name:'sample.webm',exact:true}).evaluate(node=>node===document.activeElement),true);
  check('fullscreen rejection keeps playback controls usable; focus stays inside the player and returns to the tile');
  assert.equal((await api('/api/suite/modules/video/disable','POST')).status,200);
  assert.equal((await api('/api/video/library')).status,409);
  const sources=await api('/api/files/sources');assert(sources.data.some(x=>x.role==='video'));
  assert.equal((await api('/api/suite/modules/video/enable','POST')).status,200);
  assert.equal((await api('/api/video/library')).data.total,5);
  check('disable rejects Video operations while preserving folder assignments and re-enable restores discovery');
  // Force small real API pages to exercise navigation at the loaded boundary.
  await page.route('**/api/video/library?*',async route=>{
   const url=new URL(route.request().url());url.searchParams.set('limit','2');
   const response=await route.fetch({url:url.toString()});await route.fulfill({response});
  });
  await page.reload();
  await page.getByRole('button',{name:'Open Keivotos menu'}).click();
  await page.locator('.app-drawer').getByRole('button',{name:'Video',exact:true}).click();
  await page.getByLabel('Search videos').fill('sample');await page.waitForTimeout(400);
  await page.getByRole('button',{name:'sample.mp4',exact:true}).click();
  await page.getByRole('button',{name:'Next video',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('video').src.includes('sample.webm'));
  assert(await page.getByRole('button',{name:'Next video',exact:true}).isDisabled());
  await page.getByRole('button',{name:'Previous video',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('video').src.includes('sample.mp4'));
  await page.getByRole('button',{name:'Previous video',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('video').src.includes('sample.m4v'));
  assert(await page.getByRole('button',{name:'Previous video',exact:true}).isDisabled());
  await back();
  check('next fetches another page within filtered results; first/last controls disable without wrapping');

  assert.deepEqual(report.errors,[]);
 }finally{fs.writeFileSync(path.join(config.output,'report.json'),JSON.stringify(report,null,2));await context.tracing.stop({path:path.join(config.output,'trace.zip')});await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
