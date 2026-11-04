const assert=require('node:assert/strict');const fs=require('node:fs');const path=require('node:path');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const config=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
(async()=>{
 const browser=await chromium.launch({headless:true,channel:process.env.PLAYWRIGHT_CHANNEL});
 const context=await browser.newContext({viewport:{width:1440,height:1000}});const page=await context.newPage();page.setDefaultTimeout(15000);
 const report={checks:[],errors:[]};page.on('pageerror',e=>report.errors.push(e.message));
 await page.route('**/*',route=>{if(new URL(route.request().url()).origin!==config.url){report.errors.push('Unexpected remote request');return route.abort();}return route.continue();});
 await context.tracing.start({screenshots:true,snapshots:true});
 const check=x=>{report.checks.push(x);console.log('PASS: '+x);};
 async function api(url,method='GET',body){return page.evaluate(async({url,method,body})=>{const r=await fetch(url,{method,headers:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});return {status:r.status,data:await r.json()};},{url,method,body});}
 async function libraryRow(predicate){
  const deadline=Date.now()+15000;
  while(Date.now()<deadline){
   const response=await api('/api/youtube/library');assert.equal(response.status,200);
   const row=response.data.items.find(predicate);if(row)return row;
   await page.waitForTimeout(100);
  }
  throw new Error('Expected YouTube job state was not reached');
 }
 const input=page.getByLabel('Search downloads or paste a YouTube URL');
 const url='https://www.youtube.com/watch?v=abcdefghijk';
 try{
  await page.goto(config.url);assert.equal((await api('/api/youtube/library')).status,409);
  assert.equal((await api('/api/suite/modules/youtube/enable','POST')).status,200);
  assert.equal((await api('/api/video/library')).status,409);
  assert.equal((await api('/api/suite/folders/apply','POST',{folders:[{path:config.media,display_name:'Downloads',role:'youtube'}]})).status,200);
  await page.getByRole('button',{name:'Open Keivotos menu'}).click();await page.locator('.app-drawer').getByRole('button',{name:'YouTube',exact:true}).click();
  const toggle=page.getByRole('button',{name:'Download options',exact:true});
  for(const text of ['valley','https://example.com/watch?v=abcdefghijk','https://youtube.com.evil/watch?v=abcdefghijk','https://youtube.com/playlist?list=abc']){
   await input.fill(text);assert.equal(await page.getByRole('button',{name:'Download',exact:true}).count(),0);
  }
  const beforeSearch=await input.boundingBox(),beforeOptions=await toggle.boundingBox();
  const reveal=page.locator('.download-reveal');
  assert((await reveal.getAttribute('inert'))!==null);
  await input.fill(url);assert.equal(await page.getByLabel('Video quality').count(),0);
  assert.equal(await page.locator('.download-grid article').count(),0);
  const duringClip=await reveal.evaluate(node=>getComputedStyle(node).clipPath);
  await page.waitForTimeout(70);
  const middleClip=await reveal.evaluate(node=>getComputedStyle(node).clipPath);
  await page.waitForTimeout(220);
  const finalClip=await reveal.evaluate(node=>getComputedStyle(node).clipPath);
  assert.notEqual(duringClip,finalClip);assert.notEqual(middleClip,finalClip);
  assert.equal(finalClip,'inset(0px)');
  const afterSearch=await input.boundingBox(),afterOptions=await toggle.boundingBox();
  assert(Math.abs(beforeSearch.x-afterSearch.x)<1&&Math.abs(beforeSearch.width-afterSearch.width)<1);
  assert(Math.abs(beforeOptions.x-afterOptions.x)<1);
  for(let i=0;i<3;i++){
   await input.fill('https://example.com/watch?v=abcdefghijk');
   assert.equal(await page.getByRole('button',{name:'Download',exact:true}).count(),0);
   await input.fill(url);
   assert.equal(await page.getByRole('button',{name:'Download',exact:true}).count(),1);
  }
  await page.waitForTimeout(250);
  await page.setViewportSize({width:360,height:780});
  const narrowSearch=await input.boundingBox(),narrowDownload=await page.getByRole('button',{name:'Download',exact:true}).boundingBox();
  assert(narrowSearch.width>=80&&narrowDownload.x+narrowDownload.width<=360);
  await page.setViewportSize({width:1440,height:1000});
  await page.evaluate(()=>document.documentElement.dataset.motion='reduced');
  assert(Number.parseFloat(await reveal.evaluate(node=>getComputedStyle(node).transitionDuration))<.001);
  await page.evaluate(()=>{delete document.documentElement.dataset.motion;});
  check('search width and options position stay fixed; Download reveals left to right, reverses rapidly and fits narrow screens');
  const top=await page.locator('main').last().evaluate(n=>n.getBoundingClientRect().top);
  await toggle.click();await page.waitForTimeout(60);const middle=await page.locator('.download-options').evaluate(n=>n.getBoundingClientRect().height);await page.waitForTimeout(220);const full=await page.locator('.download-options').evaluate(n=>n.getBoundingClientRect().height);assert(middle>0&&middle<full);
  assert.equal(await page.locator('main').last().evaluate(n=>n.getBoundingClientRect().top),top);
  assert.equal(await page.getByLabel('Video quality').inputValue(),'best');assert.equal(await page.getByLabel('Audio quality').inputValue(),'best');
  const toggleBox=await toggle.boundingBox(),searchBox=await input.boundingBox(),downloadBox=await page.getByRole('button',{name:'Download',exact:true}).boundingBox();
  assert(toggleBox.x+toggleBox.width<searchBox.x&&searchBox.x-toggleBox.x-toggleBox.width<16);
  assert(downloadBox.x>searchBox.x+searchBox.width&&downloadBox.x-searchBox.x-searchBox.width<16);
  const videoBox=await page.getByLabel('Video quality').boundingBox(),audioBox=await page.getByLabel('Audio quality').boundingBox();
  assert(Math.abs(videoBox.y-audioBox.y)<1&&audioBox.x>videoBox.x);
  assert.equal(await page.locator('.download-options').getByRole('button',{name:'Download',exact:true}).count(),0);
  await page.screenshot({path:path.join(config.output,'youtube-options.png')});
  await page.locator('.module-title').click();assert.equal(await toggle.getAttribute('aria-expanded'),'true');
  await toggle.click();await page.waitForTimeout(250);assert.equal(await page.getByLabel('Video quality').count(),0);
  await toggle.click();await page.waitForTimeout(250);await page.getByRole('button',{name:'Download',exact:true}).click();
  await page.getByRole('progressbar').waitFor();
  await page.locator('.download-grid article').first().click({button:'right'});
  const unfinishedMenu=page.getByRole('menu');
  assert(await unfinishedMenu.getByRole('menuitem',{name:'Show in Files'}).isDisabled());
  assert(await unfinishedMenu.getByRole('menuitem',{name:'Open in Explorer'}).isDisabled());
  await unfinishedMenu.getByText('This download has no completed local file.').waitFor();
  await page.keyboard.press('Escape');
  await page.waitForTimeout(1100);
  await input.fill('https://youtu.be/lmnopqrstuv');await page.waitForTimeout(250);
  await page.screenshot({path:path.join(config.output,'youtube-downloading.png')});
  check('URL controls animate open and close; qualities default to Best; explicit Download creates a progress card');
  await libraryRow(x=>x.status==='complete');
  await page.waitForTimeout(1100);await input.fill('');await page.waitForTimeout(300);
  await page.waitForFunction(()=>document.querySelector('.thumbnail img')?.naturalWidth>0);
  await page.screenshot({path:path.join(config.output,'youtube-library.png')});
  const result=(await api('/api/youtube/library')).data.items[0];assert.equal(result.status,'complete');
  assert(result.path.endsWith('Valley.mp4'));
  const youtubeTitle=page.locator(`[data-job-id="${result.id}"] .download-title`);
  for(const width of [1440,360]){
   await page.setViewportSize({width,height:1000});
   for(const text of [result.title,'静かな谷を越えて旅を続ける物語','A quiet journey through the valley that needs more than two rows','unbroken'.repeat(18)]){
    await youtubeTitle.evaluate((node,value)=>node.textContent=value,text);
    const metrics=await youtubeTitle.evaluate(node=>({height:node.getBoundingClientRect().height,width:node.getBoundingClientRect().width,card:node.closest('article').getBoundingClientRect().width,font:parseFloat(getComputedStyle(node).fontSize),clamp:getComputedStyle(node).webkitLineClamp,wrap:getComputedStyle(node).overflowWrap}));
    assert.equal(metrics.clamp,'2');assert.equal(metrics.wrap,'anywhere');
    assert(Math.abs(metrics.height-metrics.font*2.7)<1);assert(metrics.width<=metrics.card);
   }
  }
  await youtubeTitle.evaluate((node,value)=>node.textContent=value,result.title);
  await page.setViewportSize({width:1440,height:1000});
  assert.equal(await youtubeTitle.getAttribute('title'),result.title);
  assert.equal(await page.locator(`[data-job-id="${result.id}"]`).getAttribute('aria-label'),result.title);
  check('YouTube titles reserve two rows and contain Japanese, long Latin and unbroken names at both widths');
  const files=(await api('/api/files/search?q=Valley')).data;assert(files.some(x=>x.relative_path===result.path));

  await input.fill('not found');await page.waitForTimeout(350);assert.equal(await page.locator('.download-grid article').count(),0);
  await input.fill('valley');await page.waitForTimeout(350);assert.equal(await page.locator('.download-grid article').count(),1);
  check('completed output and local thumbnail appear in YouTube, Files discovery; local search works');
  let revealed=null;
  const revealRoute=async route=>{revealed=route.request().postDataJSON();await route.fulfill({json:{status:'revealed'}});};
  await page.route('**/api/files/reveal',revealRoute);
  await page.locator('.download-grid article').click({button:'right'});
  await page.getByRole('menu').getByRole('menuitem',{name:'Open in Explorer'}).click();
  assert.deepEqual(revealed,{source_id:result.source_id,path:result.path});
  await page.unroute('**/api/files/reveal',revealRoute);
  await page.locator('.download-grid article').click({button:'right'});
  await page.getByRole('menu').getByRole('menuitem',{name:'Show in Files'}).click();
  await page.locator('[data-files-entry-path]').filter({hasText:'Valley.mp4'}).waitFor();
  await page.getByRole('button',{name:'Open Keivotos menu'}).click();
  await page.locator('.app-drawer').getByRole('button',{name:'YouTube',exact:true}).click();
  await page.getByRole('button',{name:'Open '+result.title,exact:true}).waitFor();
  check('YouTube completed media uses exact Files/Explorer location; unfinished jobs disable both actions');
  const tile=page.getByRole('button',{name:'Open '+result.title,exact:true});
  await tile.click();await page.getByRole('dialog',{name:'YouTube player'}).waitFor();
  await page.waitForFunction(()=>document.querySelector('video')?.currentTime>0.1);
  await page.getByRole('button',{name:'Pause',exact:true}).click();
  assert(await page.locator('video').evaluate(v=>v.paused));
  await page.getByRole('dialog',{name:'YouTube player'}).focus();
  await page.locator('video').evaluate(node=>node.currentTime=.2);
  await page.keyboard.press('ArrowRight');
  await page.waitForFunction(()=>document.querySelector('video').currentTime>1);
  await page.keyboard.press('ArrowLeft');
  assert((await page.locator('video').evaluate(node=>node.currentTime))<.25);
  await page.keyboard.press('Space');await page.waitForFunction(()=>!document.querySelector('video').paused);
  await page.keyboard.press('Space');await page.waitForFunction(()=>document.querySelector('video').paused);
  check('YouTube shared player responds to Space and five-second seek keys');
  await page.getByRole('button',{name:'Play',exact:true}).click();
  await page.locator('video').evaluate(node=>node.loop=true);
  await page.getByRole('dialog',{name:'YouTube player'}).focus();
  await page.mouse.move(700,400);await page.mouse.move(1439,400);
  assert(await page.locator('.player-controls').evaluate(node=>node.classList.contains('controls-hidden')));
  await page.mouse.move(700,400);
  assert(await page.locator('.player-controls').evaluate(node=>!node.classList.contains('controls-hidden')));
  await page.mouse.move(700,999);
  assert(await page.locator('.player-controls').evaluate(node=>node.classList.contains('controls-hidden')));
  await page.mouse.move(700,400);
  await page.locator('video').evaluate(node=>node.loop=false);
  await page.getByRole('button',{name:'Pause',exact:true}).click();
  check('YouTube shared player hides controls at right/bottom edges and reveals them on return');
  const volume=page.getByRole('slider',{name:'Volume'});
  await volume.fill('62');await volume.dispatchEvent('input');
  await page.waitForFunction(()=>Math.abs(document.querySelector('video').volume-.62)<.001);
  assert.equal(await volume.getAttribute('aria-valuetext'),'62%');
  assert.equal(await page.evaluate(()=>localStorage.getItem('keivotos:youtube-volume-percent')),'62');
  assert.equal(await page.evaluate(()=>localStorage.getItem('keivotos:video-volume-percent')),'100');
  await page.getByLabel('Seek',{exact:true}).fill('1');
  await page.getByLabel('Seek',{exact:true}).dispatchEvent('input');
  await page.waitForFunction(()=>document.querySelector('video').currentTime>=0.9);
  await page.waitForFunction(()=>document.querySelector('[aria-label="Playback time"]')?.textContent==='0:01 / 0:04');
  for(const width of [1440,360]){
   await page.setViewportSize({width,height:1000});
   const timerBox=await page.getByLabel('Playback time',{exact:true}).boundingBox(),volumeBox=await page.locator('.volume-control').boundingBox();
   assert(timerBox.x>=volumeBox.x+volumeBox.width&&timerBox.x-volumeBox.x-volumeBox.width<16);
   assert(Math.abs(timerBox.y+timerBox.height/2-volumeBox.y-volumeBox.height/2)<2);
   assert(timerBox.x+timerBox.width<=width&&(await volume.boundingBox()).width>=40);
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
   await page.screenshot({path:path.join(config.output,`youtube-playback-time-${width}.png`)});
  }
  await page.setViewportSize({width:1440,height:1000});
  check('YouTube uses the same elapsed/duration display right of volume, updates after seeking and fits desktop/compact controls');
  assert(await page.getByRole('button',{name:'Previous video',exact:true}).isDisabled());
  assert(await page.getByRole('button',{name:'Next video',exact:true}).isDisabled());
  await page.getByRole('button',{name:'Fullscreen',exact:true}).click();
  await page.waitForFunction(()=>!!document.fullscreenElement);
  await page.getByRole('button',{name:'Fullscreen',exact:true}).click();
  await page.waitForFunction(()=>!document.fullscreenElement);
  await page.getByRole('button',{name:'Back to downloads'}).hover();await page.waitForTimeout(220);
  await page.screenshot({path:path.join(config.output,'youtube-player.png')});
  await page.getByRole('button',{name:'Back to downloads'}).click();
  assert(await tile.evaluate(n=>n===document.activeElement));
  assert.equal(context.pages().length,1);
  assert.equal((await api('/api/video/library')).status,409);
  check('YouTube uses shared playback, seek, fullscreen, hover Back and focus return with Video disabled; no new tab');
  const second=(await api('/api/youtube/downloads','POST',{url:'https://youtu.be/lmnopqrstuv',video:'best',audio:'best'})).data;
  await libraryRow(x=>x.id===second.id&&x.status==='complete');
  await page.reload();await input.waitFor();
  const tiles=page.locator('.play-download');await page.waitForFunction(()=>document.querySelectorAll('.play-download').length===2);
  await tiles.first().click();await page.waitForFunction(()=>document.querySelector('video')?.currentTime>0.1);
  assert.equal(await page.getByRole('slider',{name:'Volume'}).inputValue(),'62');
  assert(Math.abs((await page.locator('video').evaluate(node=>node.volume))-.62)<.001);
  const firstSrc=await page.locator('video').getAttribute('src');
  await page.getByRole('button',{name:'Next video',exact:true}).click();
  await page.waitForFunction(src=>document.querySelector('video')?.getAttribute('src')!==src,firstSrc);
  assert(Math.abs((await page.locator('video').evaluate(node=>node.volume))-.62)<.001);
  assert(await page.getByRole('button',{name:'Next video',exact:true}).isDisabled());
  await page.getByRole('button',{name:'Previous video',exact:true}).click();
  await page.waitForFunction(src=>document.querySelector('video')?.getAttribute('src')===src,firstSrc);
  await page.getByRole('button',{name:'Fullscreen',exact:true}).focus();await page.keyboard.press('Tab');
  assert(await page.getByRole('button',{name:'Back to downloads'}).evaluate(n=>n===document.activeElement));
  await page.keyboard.press('Escape');await page.getByRole('dialog',{name:'YouTube player'}).waitFor({state:'detached'});
  assert(await tiles.first().evaluate(n=>n===document.activeElement));
  check('YouTube previous/next follows its completed downloads; focus is trapped and Escape restores the original tile');


  await input.fill(url);await toggle.click();await page.waitForTimeout(250);await page.getByRole('button',{name:'Download',exact:true}).click();
  const pending=(await api('/api/youtube/library')).data.items.find(item=>item.status==='queued'||item.status==='downloading');assert(pending);
  await page.getByRole('button',{name:/^Cancel /}).click();
  await page.waitForFunction(id=>!document.querySelector(`[data-job-id="${id}"]`),pending.id);
  assert.equal((await api('/api/youtube/library')).data.items.some(item=>item.id===pending.id),false);
  await page.reload();await page.getByRole('button',{name:'Open Keivotos menu'}).click();await page.locator('.app-drawer').getByRole('button',{name:'YouTube',exact:true}).click();
  assert.equal(await page.getByText('Cancelled',{exact:true}).count(),0);
  const retried=await api(`/api/youtube/downloads/${pending.id}/retry`,'POST');assert.equal(retried.status,200);
  await page.reload();await page.getByRole('button',{name:'Open Keivotos menu'}).click();await page.locator('.app-drawer').getByRole('button',{name:'YouTube',exact:true}).click();
  await page.getByRole('progressbar').waitFor();
  await api('/api/suite/modules/youtube/disable','POST');assert.equal((await api('/api/youtube/library')).status,409);
  await api('/api/suite/modules/youtube/enable','POST');
  const restored=(await api('/api/youtube/library')).data.items;assert(restored.some(x=>x.status==='interrupted'));assert(restored.some(x=>x.status==='complete'));
  check('cancelled cards stay hidden after refresh and reload; retry remains possible, disable drains the queue and preserves completed media');

  async function terminal(id,status){
   return libraryRow(x=>x.id===id&&x.status===status);
  }
  async function replacementOf(id){
   return libraryRow(x=>x.retry_of===id);
  }
  const failed=(await api('/api/youtube/downloads','POST',{url:'https://youtu.be/retryfailed'})).data;
  await terminal(failed.id,'failed');await page.reload();await input.waitFor();
  const originalCard=page.locator(`[data-job-id="${failed.id}"]`),retryButton=originalCard.getByRole('button',{name:/^Retry /});
  await retryButton.waitFor();let retryCalls=0;
  const retryPattern=`**/api/youtube/downloads/${failed.id}/retry`;
  await page.route(retryPattern,async route=>{
   retryCalls++;
   if(retryCalls===1)return route.fulfill({status:400,json:{detail:'Fixture retry refused'}});
   const response=await route.fetch();await page.waitForTimeout(350);await route.fulfill({response});
  });
  await retryButton.click();await page.getByRole('alert').filter({hasText:'Fixture retry refused'}).waitFor();
  assert(await retryButton.isEnabled());assert.equal((await api('/api/youtube/library')).data.items.some(x=>x.id===failed.id),true);
  await retryButton.evaluate(n=>{n.click();n.click();});
  await page.waitForFunction(id=>document.querySelector(`[data-job-id="${id}"] button.job-action`)?.disabled,failed.id);
  await originalCard.waitFor({state:'detached'});assert.equal(retryCalls,2);await page.unroute(retryPattern);
  const replacement=await replacementOf(failed.id);
  await terminal(replacement.id,'failed');
  await page.locator(`[data-job-id="${replacement.id}"]`).getByRole('button',{name:/^Retry /}).click();
  const successful=await replacementOf(replacement.id);
  await terminal(successful.id,'complete');await page.reload();await input.fill('Retry failure fixture');
  await page.waitForFunction(()=>document.querySelectorAll('.download-grid article').length===1&&!!document.querySelector('.play-download'));
  assert.equal(await page.locator(`[data-job-id="${failed.id}"], [data-job-id="${replacement.id}"]`).count(),0);
  for(const id of [failed.id,replacement.id])assert.equal(fs.readFileSync(path.join(config.mediaLocal,'.keivotos','youtube',id,'unfinished.part'),'utf8'),'preserved failed attempt');
  await page.screenshot({path:path.join(config.output,'retry-success.png')});
  check('rejected Retry retains its card; rapid double click submits once; failed replacement stays retryable; successful replacement alone survives reload/search; partial bytes retained');

  const repair=(await api('/api/youtube/downloads','POST',{url:'https://youtu.be/repairvideo'})).data;
  const saved=await terminal(repair.id,'failed');assert.equal(saved.failure_phase,'integration');assert(saved.path&&saved.error.includes('Video saved'));
  const publishedFile=path.join(config.mediaLocal,...saved.path.split('/')),publishedBytes=fs.readFileSync(publishedFile);
  const foldersBefore=fs.readdirSync(path.join(config.mediaLocal,'YouTube')).sort();
  // Decode the retained MP4 before retrying: this is a working video whose origin registration failed.
  await page.evaluate(async item=>{
   const video=document.createElement('video'),url=new URL('/api/files/file',location.origin);
   url.searchParams.set('source_id',item.source_id);url.searchParams.set('path',item.path);video.src=url.toString();video.muted=true;
   document.body.append(video);try{await video.play();await new Promise(resolve=>setTimeout(resolve,150));if(video.currentTime<=0)throw new Error('Saved fixture did not play');}
   finally{video.pause();video.removeAttribute('src');video.load();video.remove();}
  },saved);
  await page.reload();await input.fill('Registration recovery fixture');
  const repairCard=page.locator(`[data-job-id="${repair.id}"]`);await repairCard.getByRole('button',{name:/^Retry /}).click();
  const repaired=await replacementOf(repair.id);
  const registered=await terminal(repaired.id,'complete');assert.equal(registered.path,saved.path);
  assert.deepEqual(fs.readFileSync(publishedFile),publishedBytes);assert.deepEqual(fs.readdirSync(path.join(config.mediaLocal,'YouTube')).sort(),foldersBefore);
  await repairCard.waitFor({state:'detached'});await page.locator(`[data-job-id="${repaired.id}"] .play-download`).click();
  await page.waitForFunction(()=>document.querySelector('video')?.currentTime>0.1);await page.keyboard.press('Escape');
  await page.reload();await input.fill('Registration recovery fixture');
  await page.waitForFunction(()=>document.querySelectorAll('.download-grid article').length===1&&!!document.querySelector('.play-download'));
  check('playable published MP4 with annotation failure is registered by Retry at the identical path/bytes, with no new output folder; completed playback/reload works');

  const stale=(await api('/api/youtube/downloads','POST',{url:'https://youtu.be/stalefailed'})).data;
  const staleItem=await terminal(stale.id,'failed');let accepted=null,holdNext=false,held=false,release;
  const releaseStale=new Promise(resolve=>release=resolve);
  const mockRows=Array.from({length:119},(_,i)=>({...staleItem,id:`pagination-${i}`,title:`Pagination fixture ${i}`,status:i===0?'downloading':'complete',path:'',thumbnail:'',error:'',retry_of:'',superseded_by:''}));
  const libraryPattern='**/api/youtube/library?*';
  await page.route(libraryPattern,async route=>{
   const request=new URL(route.request().url());
   if(request.searchParams.get('q')!=='Pagination fixture')return route.continue();
   const rows=[...mockRows,accepted||staleItem],offset=Number(request.searchParams.get('offset')),limit=Number(request.searchParams.get('limit')||60);
   const snapshot={items:rows.slice(offset,offset+limit),total:rows.length};
   if(holdNext){holdNext=false;held=true;await releaseStale;}
   await route.fulfill({json:snapshot});
  });
  await input.fill('Pagination fixture');await page.waitForFunction(()=>document.querySelectorAll('.download-grid article').length===60);
  await page.getByRole('button',{name:'Load more',exact:true}).click();await page.waitForFunction(()=>document.querySelectorAll('.download-grid article').length===120);
  holdNext=true;await page.waitForFunction(()=>document.querySelector('.download-grid')?.getAttribute('aria-busy')==='true');
  for(let i=0;i<50&&!held;i++)await page.waitForTimeout(20);assert(held);
  const staleRetryPattern=`**/api/youtube/downloads/${stale.id}/retry`;
  await page.route(staleRetryPattern,async route=>{const response=await route.fetch();accepted=await response.json();await route.fulfill({response});});
  await page.locator(`[data-job-id="${stale.id}"]`).getByRole('button',{name:/^Retry /}).click();
  await page.waitForFunction(id=>!document.querySelector(`[data-job-id="${id}"]`)&&document.querySelectorAll('.download-grid article').length===120,stale.id);
  release();await page.waitForTimeout(1250);
  assert.equal(await page.locator(`[data-job-id="${stale.id}"]`).count(),0);assert.equal(await page.locator(`[data-job-id="${accepted.id}"]`).count(),1);
  await page.reload();await input.fill('Pagination fixture');await page.waitForFunction(()=>document.querySelectorAll('.download-grid article').length===60);
  await page.getByRole('button',{name:'Load more',exact:true}).click();await page.locator(`[data-job-id="${accepted.id}"]`).waitFor();
  assert.equal(await page.locator(`[data-job-id="${stale.id}"]`).count(),0);
  await page.unroute(libraryPattern);await page.unroute(staleRetryPattern);await input.fill('');
  check('timed delayed old poll cannot revive a retried second-page card; 120 loaded rows remain unique and reload/pagination keeps the replacement');
  await page.reload();await page.getByRole('button',{name:'Open Keivotos menu'}).click();await page.getByRole('button',{name:'Settings',exact:true}).click();
  const dialog=page.getByRole('dialog',{name:'Settings',exact:true});
  await page.setViewportSize({width:1440,height:600});
  const nav=dialog.getByRole('navigation',{name:'Settings sections'});
  await nav.getByRole('button',{name:'Downloads',exact:true}).click();
  assert(await nav.evaluate(n=>n.scrollHeight>n.clientHeight&&n.scrollTop>0));
  assert.equal(await page.getByLabel('Save to path',{exact:true}).inputValue(),config.media);
  assert.equal(await page.getByRole('button',{name:'Change folder'}).isDisabled(),true);
  await page.screenshot({path:path.join(config.output,'youtube-settings-default.png')});
  await page.getByRole('button',{name:'Custom',exact:true}).click();
  await page.waitForFunction(()=>!document.querySelector('#youtube-save-path')?.disabled);
  await page.route('**/api/files/pick',route=>route.fulfill({json:{native:false,path:null}}));
  await page.getByRole('button',{name:'Change folder'}).click();
  const picker=page.getByRole('dialog',{name:'Choose a folder',exact:true});
  await picker.getByLabel('Folder path',{exact:true}).fill(config.media.replace(/[/\\][^/\\]+$/,'/custom-downloads'));
  await picker.getByRole('button',{name:'Go',exact:true}).click();
  await picker.getByRole('button',{name:'Choose this folder',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#youtube-save-path')?.value.endsWith('custom-downloads'));
  assert((await api('/api/youtube/settings')).data.path.endsWith('custom-downloads'));
  assert.equal(await dialog.getByRole('alert').count(),0);
  await page.screenshot({path:path.join(config.output,'youtube-settings-custom.png')});
  await page.getByRole('button',{name:'Change folder'}).click();await picker.getByRole('button',{name:'Cancel',exact:true}).click();
  assert((await api('/api/youtube/settings')).data.path.endsWith('custom-downloads'));

  await page.getByRole('button',{name:'Default',exact:true}).click();
  check('YouTube role resolves default path; Custom enables folder picker; settings categories scroll at unchanged dimensions');
  assert.deepEqual(report.errors,[]);
 }finally{fs.writeFileSync(path.join(config.output,'report.json'),JSON.stringify(report,null,2));await context.tracing.stop({path:path.join(config.output,'trace.zip')});await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
