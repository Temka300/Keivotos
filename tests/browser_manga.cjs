const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const config=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
(async()=>{
 const browser=await chromium.launch({headless:true,channel:process.env.PLAYWRIGHT_CHANNEL});
 const context=await browser.newContext({viewport:{width:1440,height:1000}});
 const page=await context.newPage();page.setDefaultTimeout(15000);
 const report={checks:[],errors:[]};page.on('pageerror',e=>report.errors.push(e.message));
 await context.tracing.start({screenshots:true,snapshots:true});
 const check=x=>{report.checks.push(x);console.log('PASS: '+x);};
 async function api(url,method='GET',body){return page.evaluate(async({url,method,body})=>{const r=await fetch(url,{method,headers:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});return {status:r.status,data:await r.json()};},{url,method,body});}
 async function shot(name){await page.screenshot({path:path.join(config.output,name+'.png')});}
 try{
  await page.goto(config.url);
  assert.equal((await api('/api/manga/library')).status,409);
  assert.equal((await api('/api/suite/modules/manga/enable','POST')).status,200);
  const add=await api('/api/suite/folders/apply','POST',{folders:[{path:config.media,display_name:'Manga',role:'manga'}]});assert.equal(add.status,200,JSON.stringify(add));
  assert.equal((await api('/api/manga/library')).data.total,8);
  await page.getByRole('button',{name:'Open Keivotos menu'}).click();await page.locator('.app-drawer').getByRole('button',{name:'Manga',exact:true}).click();
  await page.waitForFunction(()=>document.querySelectorAll('.manga-tile img').length===8&&[...document.querySelectorAll('.manga-tile img')].every(i=>i.complete&&i.naturalWidth>0));
  report.timings=await page.evaluate(async sourceId=>{
   const measured={runtime:'Windows Edge via loopback',fixture:'generated folder PNGs and deflated CBZ',chapters:{},covers:performance.getEntriesByType('resource').filter(entry=>entry.name.includes('/api/manga/page?')&&entry.name.includes('cover=true')).map(entry=>({duration_ms:entry.duration,transfer_bytes:entry.transferSize}))};
   for(const [kind,path] of [['folder','The Quiet Valley/Chapter 1'],['archive','The Quiet Valley/Chapter 2.cbz']]){
    const parameters=new URLSearchParams({source_id:sourceId,path,kind});
    const start=performance.now();parameters.set('metadata','true');const metadata=await(await fetch('/api/manga/pages?'+parameters,{cache:'no-store'})).json();parameters.delete('metadata');
    const times={manifest_ms:performance.now()-start,first:[],turn:[],revisit:[]};
    for(let sample=0;sample<3;sample++)for(const [name,page] of [['first',0],['turn',1],['revisit',0]]){
     parameters.set('page',String(page));parameters.set('cover','false');
     parameters.set('representation','original');parameters.set('revision',metadata.revisions[page]);
     const started=performance.now();const response=await fetch('/api/manga/page?'+parameters,{cache:'no-store'});
     if(!response.ok)throw new Error('Timing page failed: '+response.status);
     const url=URL.createObjectURL(await response.blob());const image=new Image();
     try{image.src=url;await image.decode();times[name].push(performance.now()-started);}
     finally{URL.revokeObjectURL(url);}
    }
    measured.chapters[kind]=times;
   }
   return measured;
  },add.data.sources.find(source=>source.role==='manga').source_id);
  await shot('manga-library');
  await page.getByLabel('Search manga').fill('quiet');await page.waitForTimeout(450);assert.equal(await page.locator('.manga-tile').count(),1);
  await page.getByLabel('Search manga').fill('');await page.waitForTimeout(450);
  check('optional Manga enables, adopts a source, renders eight covers and searches names');
  const sourceId=add.data.sources.find(source=>source.role==='manga').source_id;
  const responseChecks=await page.evaluate(async sourceId=>{
   const parameters=new URLSearchParams({source_id:sourceId,path:'The Quiet Valley/Chapter 1',kind:'folder',metadata:'true'});
   const metadata=await(await fetch('/api/manga/pages?'+parameters,{cache:'no-store'})).json();
   parameters.delete('metadata');parameters.set('page','0');parameters.set('representation','original');parameters.set('revision',metadata.revisions[0]);
   const original=await fetch('/api/manga/page?'+parameters,{cache:'no-store'});const body=await original.arrayBuffer();
   const unchanged=await fetch('/api/manga/page?'+parameters,{cache:'no-store',headers:{'If-None-Match':original.headers.get('etag')}});
   const raw=await(await fetch('/api/files/file?'+new URLSearchParams({source_id:sourceId,path:'The Quiet Valley/Chapter 1/00-cover.png'}))).arrayBuffer();
   const identical=body.byteLength===raw.byteLength&&new Uint8Array(body).every((value,index)=>value===new Uint8Array(raw)[index]);
   parameters.set('revision','0'.repeat(64));const stale=await fetch('/api/manga/page?'+parameters,{cache:'no-store',headers:{'If-None-Match':original.headers.get('etag')}});
   parameters.delete('revision');parameters.delete('representation');const legacy=await fetch('/api/manga/page?'+parameters,{cache:'no-store'});
   return {status:original.status,mime:original.headers.get('content-type'),cache:original.headers.get('cache-control'),nosniff:original.headers.get('x-content-type-options'),unchanged:unchanged.status,unchangedBytes:(await unchanged.arrayBuffer()).byteLength,stale:stale.status,legacyMime:legacy.headers.get('content-type'),identical};
  },sourceId);
  assert.equal(responseChecks.status,200);assert.equal(responseChecks.mime,'image/png');assert.equal(responseChecks.cache,'private, no-cache');
  assert.equal(responseChecks.nosniff,'nosniff');assert.equal(responseChecks.unchanged,304);assert.equal(responseChecks.unchangedBytes,0);
  assert.equal(responseChecks.stale,409);assert.equal(responseChecks.legacyMime,'image/webp');assert(responseChecks.identical);
  report.responses=responseChecks;
  check('Original preserves exact PNG bytes, uses private validators, refuses forged revisions and retains legacy WebP defaults');
  const tile=page.getByRole('button',{name:'The Quiet Valley',exact:true});
  const mangaTitle=page.locator('.manga-tile[title="The Quiet Valley"] .manga-name');
  for(const width of [1440,360]){
   await page.setViewportSize({width,height:1000});
   for(const text of ['The Quiet Valley','静かな谷を越えて旅を続ける物語','The Quiet Valley and the morning train that kept going','unbroken'.repeat(18)]){
    await mangaTitle.evaluate((node,value)=>node.textContent=value,text);
    const metrics=await mangaTitle.evaluate(node=>({height:node.getBoundingClientRect().height,width:node.getBoundingClientRect().width,card:node.closest('button').getBoundingClientRect().width,font:parseFloat(getComputedStyle(node).fontSize),clamp:getComputedStyle(node).webkitLineClamp,wrap:getComputedStyle(node).overflowWrap}));
    assert.equal(metrics.clamp,'2');assert.equal(metrics.wrap,'anywhere');
    assert(Math.abs(metrics.height-metrics.font*2.7)<1);assert(metrics.width<=metrics.card);
   }
  }
  await mangaTitle.evaluate(node=>node.textContent='The Quiet Valley');
  await page.setViewportSize({width:1440,height:1000});
  assert.equal(await tile.getAttribute('title'),'The Quiet Valley');
  check('Manga titles reserve two rows and contain Japanese, long Latin and unbroken names at both widths');
  await tile.click({button:'right'});
  await page.getByRole('menu',{name:'Location for The Quiet Valley'}).getByRole('menuitem',{name:'Show in Files'}).click();
  await page.getByRole('navigation',{name:'Current folder'}).getByRole('button',{name:'The Quiet Valley'}).waitFor();
  await page.getByRole('button',{name:'Open Keivotos menu'}).click();
  await page.locator('.app-drawer').getByRole('button',{name:'Manga',exact:true}).click();
  await tile.click();
  const dialog=page.getByRole('dialog',{name:'The Quiet Valley chapters'});
  await dialog.getByRole('button',{name:'Chapter 10',exact:true}).waitFor();
  assert.deepEqual(await page.locator('.chapter-list button').allTextContents(),['Chapter 1›','Chapter 2›','Chapter 10›']);
  let revealed=null;
  const revealRoute=async route=>{revealed=route.request().postDataJSON();await route.fulfill({json:{status:'revealed'}});};
  await page.route('**/api/files/reveal',revealRoute);
  await dialog.getByRole('button',{name:'Chapter 1',exact:true}).click({button:'right'});
  await page.getByRole('menu',{name:'Location for Chapter 1'}).getByRole('menuitem',{name:'Open in Explorer'}).click();
  assert.equal(revealed.path,'The Quiet Valley/Chapter 1');
  await page.unroute('**/api/files/reveal',revealRoute);
  await dialog.getByRole('button',{name:'Chapter 2',exact:true}).click({button:'right'});
  await page.getByRole('menu',{name:'Location for Chapter 2'}).getByRole('menuitem',{name:'Show in Files'}).click();
  await page.locator('[data-files-entry-path="The Quiet Valley/Chapter 2.cbz"]').waitFor();
  await page.getByRole('button',{name:'Open Keivotos menu'}).click();
  await page.locator('.app-drawer').getByRole('button',{name:'Manga',exact:true}).click();
  await tile.click();
  await dialog.getByRole('button',{name:'Chapter 10',exact:true}).waitFor();
  check('Manga series, folder chapter and archive chapter menus target registered Files items');
  await shot('manga-chapters');
  await page.mouse.click(20,500);await dialog.waitFor({state:'detached'});assert(await tile.evaluate(n=>n===document.activeElement));
  await tile.click();await dialog.getByRole('button',{name:'Chapter 1',exact:true}).click();
  const reader=page.getByRole('dialog',{name:'Manga reader'});
  await page.getByAltText('Page 1',{exact:true}).waitFor();
  const box=await reader.boundingBox();assert.equal(box.width,1440);assert.equal(box.height,1000);
  assert.equal(await reader.locator('img').count(),1);
  assert.equal(await page.getByLabel('Reading layout').inputValue(),'paged');
  async function assertPagedImageFits(){
    await page.waitForFunction(()=>{const image=document.querySelector('.paged-page img');return image?.complete&&image.naturalWidth>0;});
    const bounds=await reader.locator('.paged-page img').evaluate(image=>{
      const page=image.closest('.paged-page').getBoundingClientRect();
      const rect=image.getBoundingClientRect();
      return {page:{left:page.left,top:page.top,right:page.right,bottom:page.bottom},image:{left:rect.left,top:rect.top,right:rect.right,bottom:rect.bottom,width:rect.width,height:rect.height},naturalRatio:image.naturalWidth/image.naturalHeight};
    });
    assert(bounds.image.left>=bounds.page.left-1&&bounds.image.top>=bounds.page.top-1);
    assert(bounds.image.right<=bounds.page.right+1&&bounds.image.bottom<=bounds.page.bottom+1);
    assert(Math.abs(bounds.image.width/bounds.image.height-bounds.naturalRatio)<.01);
  }
  await assertPagedImageFits();
  const originalUrl=new URL(await reader.locator('img').getAttribute('src'),config.url);
  assert.equal(originalUrl.searchParams.get('representation'),'original');assert.match(originalUrl.searchParams.get('revision'),/^[a-f0-9]{64}$/);
  await page.mouse.click(700,900);await page.getByAltText('Page 2',{exact:true}).waitFor();
  await page.mouse.click(700,100);await page.getByAltText('Page 1',{exact:true}).waitFor();
  await reader.focus();await page.keyboard.press('ArrowRight');await page.getByAltText('Page 2',{exact:true}).waitFor();
  await page.keyboard.press('PageDown');await page.getByAltText('Page 3',{exact:true}).waitFor();
  await assertPagedImageFits();
  await shot('manga-reader-paged');
  check('Paged shows one contained page; bottom/top clicks and keyboard move exactly one page');
  await page.mouse.click(700,500);
  await page.waitForTimeout(230);
  assert.equal(await reader.locator('.reader-controls').evaluate(n=>getComputedStyle(n).opacity),'0');
  assert.equal(await reader.locator('.reader-controls').getAttribute('aria-hidden'),'true');
  await page.keyboard.press('Tab');
  await page.waitForTimeout(230);
  assert.equal(await reader.locator('.reader-controls').evaluate(n=>getComputedStyle(n).opacity),'1');
  await page.mouse.click(700,500);await page.mouse.click(700,500);
  await page.waitForTimeout(230);
  assert.equal(await reader.locator('.reader-controls').evaluate(n=>getComputedStyle(n).opacity),'1');
  assert.equal(await page.getByAltText('Page 3',{exact:true}).count(),1);
  check('center click animates reader controls without turning a page; Tab restores hidden controls');
  const back=page.getByRole('button',{name:'Back to chapters'});
  await page.mouse.move(1100,400);await page.waitForTimeout(220);
  const resting=(await back.boundingBox()).width;
  await back.hover();await page.waitForTimeout(70);const middle=(await back.boundingBox()).width;
  await page.waitForTimeout(180);const expanded=(await back.boundingBox()).width;
  assert(middle>resting&&middle<expanded);
  assert.equal(await back.evaluate(n=>getComputedStyle(n).backgroundColor),'rgb(51, 51, 59)');
  await page.mouse.move(1100,400);await page.waitForTimeout(220);assert.equal((await back.boundingBox()).width,resting);
  await page.getByLabel('Reading layout').selectOption('vertical');
  await page.waitForTimeout(350);
  assert(await reader.evaluate(n=>n.scrollTop>0));
  const width=await page.locator('.page[data-page="1"]').evaluate(n=>n.getBoundingClientRect().width);assert.equal(width,1000);
  await shot('manga-reader-vertical');
  await page.getByLabel('Reading layout').selectOption('paged');
  assert.notEqual(await reader.locator('.paged-page').getAttribute('data-page'),'0');
  await reader.focus();
  for(let i=0;i<20;i++)await page.keyboard.press('ArrowRight');
  await page.getByAltText('Page 13',{exact:true}).waitFor();
  await page.keyboard.press('ArrowRight');assert.equal(await page.getByAltText('Page 13',{exact:true}).count(),1);
  await page.mouse.click(700,900);assert.equal(await page.getByAltText('Page 13',{exact:true}).count(),1);
  await page.emulateMedia({reducedMotion:'reduce'});
  await page.mouse.click(700,500);
  assert.equal(await reader.locator('.reader-controls').evaluate(n=>getComputedStyle(n).transitionDuration),'0s');
  await page.mouse.click(700,500);
  await page.emulateMedia({reducedMotion:'no-preference'});
  await page.getByLabel('Reading layout').focus();await page.keyboard.press('Tab');assert(await back.evaluate(n=>n===document.activeElement));
  await back.click();await reader.waitFor({state:'detached'});assert(await dialog.getByRole('button',{name:'Chapter 1',exact:true}).evaluate(n=>n===document.activeElement));
  check('chapter window closes outside; vertical scroll and Paged retain position, clamp at last page, respect reduced motion and restore focus');
  await dialog.getByRole('button',{name:'Chapter 2',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('img[alt="Page 1"]')?.naturalWidth>0);
  await page.keyboard.press('Escape');await reader.waitFor({state:'detached'});
  await page.keyboard.press('Escape');await dialog.waitFor({state:'detached'});
  check('CBZ chapter pages decode without extraction and Escape returns through chapters to the library');
  await tile.click();await dialog.getByRole('button',{name:'Chapter 10',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('.paged-page img')?.naturalWidth>0);
  await reader.focus();for(let i=0;i<4;i++)await page.keyboard.press('ArrowRight');
  await page.getByAltText('Page 5',{exact:true}).waitFor();await assertPagedImageFits();
  const oriented=await reader.locator('img').evaluate(image=>({width:image.naturalWidth,height:image.naturalHeight,url:image.getAttribute('src')}));
  assert.equal(oriented.width,60);assert.equal(oriented.height,120);assert(oriented.url.includes('representation=original'));
  await page.keyboard.press('ArrowRight');await page.getByRole('alert').filter({hasText:'Original page 6'}).waitFor();
  await page.getByRole('button',{name:'Open converted page',exact:true}).focus();await page.keyboard.press('Space');
  await page.waitForFunction(()=>document.querySelector('.paged-page img')?.complete&&document.querySelector('.paged-page img')?.naturalWidth===120);
  assert((await reader.locator('img').getAttribute('src')).includes('representation=webp'));
  assert.equal(await reader.locator('.paged-page').getAttribute('data-page'),'5');
  await reader.focus();await page.keyboard.press('ArrowRight');await page.getByRole('alert').filter({hasText:'Original page 7'}).waitFor();
  await page.getByRole('button',{name:'Open converted page',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('.paged-page img')?.complete&&document.querySelector('.paged-page img')?.naturalWidth===120);
  await shot('manga-original-conversion');await page.keyboard.press('Escape');await reader.waitFor({state:'detached'});await page.keyboard.press('Escape');await dialog.waitFor({state:'detached'});
  check('Original JPEG MIME and EXIF orientation render correctly; BMP and animation require explicit converted-still acceptance');
  await context.route('**/api/manga/pages?*',route=>route.fulfill({status:422,contentType:'application/json',body:JSON.stringify({detail:'This chapter cannot be opened. See Logs.'})}));
  await tile.click();await dialog.getByRole('button',{name:'Chapter 1',exact:true}).click();
  await page.getByRole('alert').filter({hasText:'See Logs'}).waitFor();await back.click();await page.keyboard.press('Escape');
  await context.unroute('**/api/manga/pages?*');
  check('chapter errors remain concise and preserve the route back to the library');
  await tile.click();await dialog.getByRole('button',{name:'Chapter 1',exact:true}).click();await assertPagedImageFits();
  const previousUrl=await reader.locator('img').getAttribute('src');
  const coverFile=path.join(config.mediaLocal,'The Quiet Valley','Chapter 1','00-cover.png');
  const preservedFixture=fs.readFileSync(coverFile);
  try{
   fs.writeFileSync(coverFile,fs.readFileSync(path.join(config.mediaLocal,'The Quiet Valley','Chapter 1','1.png')));
   await page.evaluate(()=>window.dispatchEvent(new Event('focus')));
   await page.getByRole('alert').filter({hasText:'This chapter changed'}).waitFor();
   assert.equal(await reader.locator('img').count(),0);
   await page.getByRole('button',{name:'Reopen chapter',exact:true}).click();await assertPagedImageFits();
   assert.notEqual(await reader.locator('img').getAttribute('src'),previousUrl);
   const openedUrl=await reader.locator('img').getAttribute('src');
   assert.equal((await api('/api/suite/folders/apply','POST',{folders:[{source_id:sourceId,path:config.media,display_name:'Manga',role:'manga',visible:false}]})).status,200);
   await page.evaluate(()=>window.dispatchEvent(new Event('focus')));await reader.waitFor({state:'detached'});
   assert.equal(await page.locator('.manga-tile img').count(),0);
   assert.equal((await api(openedUrl)).status,404);
  }finally{fs.writeFileSync(coverFile,preservedFixture);}
  assert.equal((await api('/api/suite/folders/apply','POST',{folders:[{source_id:sourceId,path:config.media,display_name:'Manga',role:'manga',visible:true}]})).status,200);
  await page.evaluate(()=>window.dispatchEvent(new Event('focus')));await tile.waitFor();
  await page.waitForFunction(()=>document.querySelectorAll('.manga-tile img').length===8&&[...document.querySelectorAll('.manga-tile img')].every(image=>image.complete&&image.naturalWidth>0));
  check('changed chapters discard mounted images and reopen with new revisions; hidden sources drop reader and cover references');
  assert.equal((await api('/api/suite/modules/manga/disable','POST')).status,200);
  assert.equal((await api('/api/manga/library')).status,409);
  assert.equal((await api('/api/manga/page?'+new URLSearchParams({source_id:sourceId,path:'The Quiet Valley/Chapter 1',kind:'folder',representation:'original'}))).status,409);
  assert((await api('/api/files/sources')).data.some(s=>s.role==='manga'));
  assert.equal((await api('/api/suite/modules/manga/enable','POST')).status,200);
  assert.equal((await api('/api/manga/library')).data.total,8);
  const sample=(await api('/api/manga/library')).data.items[0],windowRequests=[];
  const pagination=async route=>{
   const url=new URL(route.request().url());if(url.searchParams.get('q')!=='pagination'){await route.continue();return;}
   const offset=Number(url.searchParams.get('offset')||0);windowRequests.push(offset);
   const items=Array.from({length:120},(_,index)=>({...sample,path:'pagination-'+index,name:'Pagination series '+index}));
   await route.fulfill({json:{items:items.slice(offset,offset+60),total:120}});
  };
  await page.route('**/api/manga/library?*',pagination);
  await page.getByLabel('Search manga').fill('pagination');await page.waitForFunction(()=>document.querySelectorAll('.manga-tile').length===60);
  await page.getByRole('button',{name:'Load more',exact:true}).click();await page.waitForFunction(()=>document.querySelectorAll('.manga-tile').length===120);
  const scrollBefore=await page.locator('.manga-surface main').evaluate(node=>node.scrollTop);
  windowRequests.length=0;await page.evaluate(()=>window.dispatchEvent(new Event('focus')));
  await page.waitForFunction(()=>document.querySelector('.manga-grid')?.getAttribute('aria-busy')==='false');
  assert.deepEqual(windowRequests,[0,60]);assert.equal(await page.locator('.manga-tile').count(),120);
  assert.equal(await page.locator('.manga-surface main').evaluate(node=>node.scrollTop),scrollBefore);
  await page.unroute('**/api/manga/library?*',pagination);await page.getByLabel('Search manga').fill('');
  await page.waitForFunction(()=>document.querySelectorAll('.manga-tile').length===8);
  check('focus refresh preserves expanded Load more results and library scroll position');
  assert.deepEqual(report.errors,[]);
  check('disable rejects Manga work and preserves source registration and rediscovery');
 }finally{fs.writeFileSync(path.join(config.output,'report.json'),JSON.stringify(report,null,2));await context.tracing.stop({path:path.join(config.output,'trace.zip')});await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
