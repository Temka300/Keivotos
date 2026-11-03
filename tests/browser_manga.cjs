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
  assert.equal(await dialog.locator('.series-title').textContent(),'The Quiet Valley');
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
  assert.equal(await reader.locator('.series-title').textContent(),'The Quiet Valley');
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
  assert.equal(await reader.locator('.page-counter').textContent(),'1 / 13');
  const originalUrl=new URL(await reader.locator('img').getAttribute('src'),config.url);
  assert.equal(originalUrl.searchParams.get('representation'),'original');assert.match(originalUrl.searchParams.get('revision'),/^[a-f0-9]{64}$/);
  await page.mouse.click(700,900);await page.getByAltText('Page 2',{exact:true}).waitFor();
  await page.mouse.click(700,100);await page.getByAltText('Page 1',{exact:true}).waitFor();
  await reader.focus();await page.keyboard.press('ArrowRight');await page.getByAltText('Page 2',{exact:true}).waitFor();
  await page.keyboard.press('PageDown');await page.getByAltText('Page 3',{exact:true}).waitFor();
  assert.equal(await reader.locator('.page-counter').textContent(),'3 / 13');
  await assertPagedImageFits();
  await shot('manga-reader-paged');
  check('Paged shows one contained page; bottom/top clicks and keyboard move exactly one page');
  await reader.focus();
  for(const [key,count] of [['ArrowLeft',2],['ArrowUp',1],['PageUp',1],['ArrowDown',2],['PageDown',3],[' ',4]]){
   await page.keyboard.press(key);assert.equal(await reader.locator('.page-counter').textContent(),count+' / 13');
  }
  for(let repeat=0;repeat<16;repeat++)await page.keyboard.down('ArrowRight');await page.keyboard.up('ArrowRight');
  assert.equal(await reader.locator('.page-counter').textContent(),'13 / 13');
  for(let repeat=0;repeat<16;repeat++)await page.keyboard.down('ArrowLeft');await page.keyboard.up('ArrowLeft');
  assert.equal(await reader.locator('.page-counter').textContent(),'1 / 13');
  await page.getByLabel('Reading layout').focus();await page.keyboard.press('ArrowDown');
  assert.equal(await page.getByLabel('Reading layout').inputValue(),'vertical');assert.equal(await reader.locator('.page-counter').textContent(),'1 / 13');
  await page.keyboard.press('ArrowUp');assert.equal(await page.getByLabel('Reading layout').inputValue(),'paged');
  assert.equal(await reader.locator('.page-counter').textContent(),'1 / 13');
  await page.mouse.click(700,750);assert.equal(await reader.locator('.page-counter').textContent(),'2 / 13');
  await page.mouse.click(700,250);assert.equal(await reader.locator('.page-counter').textContent(),'1 / 13');
  await page.keyboard.press('ArrowRight');assert.equal(await reader.locator('.page-counter').textContent(),'2 / 13');
  await page.mouse.move(700,500);await page.mouse.down();await page.mouse.move(700,350,{steps:5});await page.mouse.up();
  assert.equal(await reader.locator('.page-counter').textContent(),'2 / 13');
  assert.equal(await reader.locator('.reader-controls').getAttribute('aria-hidden'),'false');
  await reader.focus();await page.keyboard.press('ArrowRight');
  check('all Paged keys and native repeat events clamp; focused layout arrows remain native, exact mouse zones turn once, and dragging does not toggle controls');
  await page.mouse.click(700,500);
  await page.waitForTimeout(230);
  assert.equal(await reader.locator('.reader-controls').evaluate(n=>getComputedStyle(n).opacity),'0');
  assert.equal(await reader.locator('.page-counter').evaluate(n=>getComputedStyle(n.closest('.reader-controls')).opacity),'0');
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
  const scrollBeforeWheel=await reader.evaluate(node=>node.scrollTop);
  await page.mouse.move(700,600);await page.mouse.wheel(0,1700);
  await page.waitForFunction(before=>document.querySelector('.reader').scrollTop>before,scrollBeforeWheel);
  async function assertVerticalCounter(){await page.waitForFunction(()=>{
   const reader=document.querySelector('.reader'),bounds=reader.getBoundingClientRect(),center=bounds.top+bounds.height/2;
   const current=[...reader.querySelectorAll('.page')].find(node=>{const rect=node.getBoundingClientRect();return rect.top<=center&&rect.bottom>center;});
   return current&&reader.querySelector('.page-counter').textContent===(Number(current.dataset.page)+1)+' / 13';
  });}
  await assertVerticalCounter();
  const scrollbar=await reader.evaluate(node=>{
   const bounds=node.getBoundingClientRect(),size=bounds.width-node.clientWidth,thumb=node.clientHeight*node.clientHeight/node.scrollHeight;
   return {size,x:bounds.right-size/2,y:bounds.top+node.scrollTop/(node.scrollHeight-node.clientHeight)*(node.clientHeight-thumb)+thumb/2,scroll:node.scrollTop};
  });
  if(scrollbar.size>0){
   await page.mouse.move(scrollbar.x,scrollbar.y);await page.mouse.down();await page.mouse.move(scrollbar.x,scrollbar.y+180,{steps:8});await page.mouse.up();
   await page.waitForFunction(before=>document.querySelector('.reader').scrollTop>before,scrollbar.scroll);await assertVerticalCounter();
   report.navigation={scrollbarDrag:'native scrollbar drag passed'};
  }else report.navigation={scrollbarDrag:'native browser exposes no scrollbar hit area; wheel verified'};
  assert.equal(await reader.locator('.reader-controls').getAttribute('aria-hidden'),'false');
  check('Vertical mouse wheel and available native scrollbar dragging scroll naturally, update the reading-center counter and keep controls visible');
  const width=await page.locator('.page[data-page="1"]').evaluate(n=>n.getBoundingClientRect().width);assert.equal(width,1000);
  await reader.evaluate(node=>{
   const target=node.querySelector('.page[data-page="5"]'),bounds=node.getBoundingClientRect(),rect=target.getBoundingClientRect();
   node.scrollTop+=rect.top+rect.height/2-(bounds.top+bounds.height/2);
  });
  await page.waitForFunction(()=>document.querySelector('.page-counter')?.textContent==='6 / 13');
  const verticalCurrent=await reader.locator('.page-counter').textContent();
  await shot('manga-reader-vertical');
  await page.getByLabel('Reading layout').selectOption('paged');
  assert.equal(await reader.locator('.paged-page').getAttribute('data-page'),'5');
  assert.equal(await reader.locator('.page-counter').textContent(),verticalCurrent);
  await reader.focus();
  for(let i=0;i<20;i++)await page.keyboard.press('ArrowRight');
  await page.getByAltText('Page 13',{exact:true}).waitFor();
  assert.equal(await reader.locator('.page-counter').textContent(),'13 / 13');
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
  await page.getByRole('alert').filter({hasText:'See Logs'}).waitFor();
  assert.equal(await reader.locator('.page-counter').textContent(),'— / —');
  await back.click();await page.keyboard.press('Escape');
  await context.unroute('**/api/manga/pages?*');
  check('chapter errors remain concise and preserve the route back to the library');
  const pendingCount=async route=>{
   if(new URL(route.request().url()).searchParams.get('path')!=='The Quiet Valley/Chapter 1'){await route.continue();return;}
   const response=await route.fetch();await new Promise(resolve=>setTimeout(resolve,450));await route.fulfill({response});
  };
  await page.route('**/api/manga/pages?*',pendingCount);
  try{
   await tile.click();await dialog.getByRole('button',{name:'Chapter 1',exact:true}).click();
   assert.equal(await reader.locator('.page-counter').textContent(),'— / —');
   await page.keyboard.press('Escape');await reader.waitFor({state:'detached'});
   assert(await dialog.getByRole('button',{name:'Chapter 1',exact:true}).evaluate(node=>node===document.activeElement));
   await dialog.getByRole('button',{name:'Chapter 2',exact:true}).click();await assertPagedImageFits();
   await page.waitForTimeout(550);assert.equal(await reader.locator('.page-counter').textContent(),'1 / 4');
   assert((await reader.locator('img').getAttribute('src')).includes('Chapter+2.cbz'));
   await back.click();await page.keyboard.press('Escape');
  }finally{await page.unroute('**/api/manga/pages?*',pendingCount);}
  check('Escape cancels delayed chapter counts, restores chapter focus and ignores their late response after opening another chapter');
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
  let readerTitle='boku ni onnanoko',metadataMode='normal';
  const titleRoute=async route=>{
   const response=await route.fetch(),body=await response.json();
   await route.fulfill({response,json:{...body,items:body.items.map(item=>item.path==='The Quiet Valley'?{...item,name:readerTitle}:item)}});
  };
  const countRoute=async route=>{
   if(metadataMode==='normal'){await route.continue();return;}
   const response=await route.fetch(),body=await response.json();await new Promise(resolve=>setTimeout(resolve,260));
   if(metadataMode==='error'){await route.fulfill({status:422,json:{detail:'This chapter cannot be opened. See Logs.'}});return;}
   await route.fulfill({response,json:{...body,count:1,revisions:body.revisions.slice(0,1)}});
  };
  await page.route('**/api/manga/library?*',titleRoute);await page.route('**/api/manga/pages?*',countRoute);
  try{
   for(const name of ['boku ni onnanoko','静かな谷を越えて旅を続ける物語 '.repeat(8)+'unbroken'.repeat(18)]){
    readerTitle=name;await page.evaluate(()=>window.dispatchEvent(new Event('focus')));
    const namedTile=page.getByRole('button',{name,exact:true});await namedTile.waitFor();await namedTile.click();
    const namedDialog=page.getByRole('dialog',{name:name+' chapters'});
    assert.equal(await namedDialog.locator('.series-title').textContent(),name);
    assert.equal(await namedDialog.locator('.series-title').getAttribute('title'),name);
    const headerBox=await namedDialog.locator('.chapter-heading').boundingBox(),coverBox=await namedDialog.locator('.chapter-cover').boundingBox();assert(headerBox.y+headerBox.height<=coverBox.y);
    await namedDialog.getByRole('button',{name:'Chapter 1',exact:true}).click();await assertPagedImageFits();
    assert.equal(await reader.locator('.series-title').textContent(),name);assert.equal(await reader.locator('.series-title').getAttribute('title'),name);
    for(const width of [1440,720,360]){
     await page.setViewportSize({width,height:1000});
     const boxes=await reader.locator('.reader-controls').evaluate(node=>{
      const parts=[...node.children].map(child=>{const rect=child.getBoundingClientRect();return {x:rect.x,y:rect.y,right:rect.right,bottom:rect.bottom,width:rect.width};});
      const title=node.querySelector('.series-title');return {parts,titleClamp:getComputedStyle(title).webkitLineClamp,backing:getComputedStyle(node.querySelector('.reader-heading')).backgroundColor};
     });
     assert.equal(boxes.titleClamp,'2');assert.equal(boxes.backing,'rgba(0, 0, 0, 0.6)');
     const counter=boxes.parts[1];assert(Math.abs(counter.x+counter.width/2-width/2)<1);
     for(const part of boxes.parts)assert(part.x>=0&&part.right<=width);
     for(let first=0;first<boxes.parts.length;first++)for(let second=first+1;second<boxes.parts.length;second++){
      const a=boxes.parts[first],b=boxes.parts[second];assert(!(a.x<b.right&&a.right>b.x&&a.y<b.bottom&&a.bottom>b.y),'header controls must not overlap');
     }
     await back.hover();await page.waitForTimeout(220);
     const afterHover=await reader.locator('.page-counter').boundingBox();assert(Math.abs(afterHover.x+afterHover.width/2-width/2)<1);
     await page.mouse.move(width-20,500);
    }
    await shot('manga-header-compact');await page.setViewportSize({width:1440,height:1000});
    await reader.focus();await page.keyboard.press('ArrowRight');await assertPagedImageFits();
    assert.equal(await reader.locator('.page-counter').textContent(),'2 / 13');await shot('manga-header-bright');
    await back.click();await page.keyboard.press('Escape');
   }
   check('real series names appear beside Back with two-line full titles; translucent header and centered counter avoid collisions across widths and hover');
   metadataMode='single';await page.setViewportSize({width:360,height:1000});
   const namedTile=page.getByRole('button',{name:readerTitle,exact:true});await namedTile.click();
   const namedDialog=page.getByRole('dialog',{name:readerTitle+' chapters'});
   await namedDialog.getByRole('button',{name:'Chapter 1',exact:true}).click();
   assert.equal(await reader.locator('.page-counter').textContent(),'— / —');
   await assertPagedImageFits();assert.equal(await reader.locator('.page-counter').textContent(),'1 / 1');
   await reader.focus();await page.keyboard.press('ArrowRight');assert.equal(await reader.locator('.page-counter').textContent(),'1 / 1');
   await page.getByLabel('Reading layout').selectOption('vertical');await page.waitForTimeout(120);assert.equal(await reader.locator('.page-counter').textContent(),'1 / 1');
   await page.getByLabel('Reading layout').selectOption('paged');await back.click();
   metadataMode='error';await namedDialog.getByRole('button',{name:'Chapter 1',exact:true}).click();
   assert.equal(await reader.locator('.page-counter').textContent(),'— / —');
   await reader.getByRole('alert').waitFor();assert.equal(await reader.locator('.page-counter').textContent(),'— / —');
   const errorBox=await reader.getByRole('alert').boundingBox(),controlsBox=await reader.locator('.reader-controls').boundingBox();assert(errorBox.y>=controlsBox.y+controlsBox.height);
   await back.click();await page.keyboard.press('Escape');
   check('loading and errors keep a neutral page count; a single-page chapter stays 1/1 in both layouts and compact errors clear the header');
  }finally{
   await page.unroute('**/api/manga/library?*',titleRoute);await page.unroute('**/api/manga/pages?*',countRoute);
   await page.setViewportSize({width:1440,height:1000});await page.evaluate(()=>window.dispatchEvent(new Event('focus')));await tile.waitFor();
  }
  const warmContext=await browser.newContext({viewport:{width:1440,height:1000}});
  await warmContext.tracing.start({screenshots:true,snapshots:true});
  await warmContext.addInitScript(()=>{
   const NativeImage=window.Image;window.__warmImages=[];window.__warmStarts=[];
   const src=Object.getOwnPropertyDescriptor(HTMLImageElement.prototype,'src');
   const width=Object.getOwnPropertyDescriptor(HTMLImageElement.prototype,'naturalWidth').get,height=Object.getOwnPropertyDescriptor(HTMLImageElement.prototype,'naturalHeight').get;
   window.Image=function(...args){
    const image=new NativeImage(...args);window.__warmImages.push(new WeakRef(image));
    Object.defineProperty(image,'src',{get:()=>src.get.call(image),set:value=>{if(image.fetchPriority==='low')window.__warmStarts.push(value);src.set.call(image,value);}});
    // Exercise the retention policy without allocating oversized fixture images.
    Object.defineProperty(image,'naturalWidth',{get:()=>window.__largeWarmPages&&image.fetchPriority==='low'?2800:width.call(image)});
    Object.defineProperty(image,'naturalHeight',{get:()=>window.__largeWarmPages&&image.fetchPriority==='low'?2800:height.call(image)});
    return image;
   };
   window.Image.prototype=NativeImage.prototype;
  });
  const warm=await warmContext.newPage();warm.setDefaultTimeout(15000);
  warm.on('pageerror',error=>report.errors.push(error.message));
  const requests=[];let delay=100,holdFirst=false,holdNeighbor=false,active=0,peak=0;
  const warmerImages=()=>warm.evaluate(()=>window.__warmImages.map(ref=>ref.deref()).filter(image=>image?.fetchPriority==='low'&&image.hasAttribute('src')).map(image=>({url:image.getAttribute('src'),complete:image.complete,width:image.naturalWidth,height:image.naturalHeight})));
  const settled=()=>warm.waitForFunction(()=>window.__warmImages.map(ref=>ref.deref()).filter(image=>image?.fetchPriority==='low'&&image.hasAttribute('src')).every(image=>image.complete&&image.naturalWidth>0));
  const fullPageRoute=async route=>{
   const url=new URL(route.request().url());if(url.searchParams.get('cover')!=='false'){await route.continue();return;}
   const index=Number(url.searchParams.get('page')),chapter=url.searchParams.get('path');
   requests.push({index,chapter,representation:url.searchParams.get('representation'),time:Date.now()});active++;peak=Math.max(peak,active);
   try{
    const response=await route.fetch();
    await new Promise(resolve=>setTimeout(resolve,(holdFirst&&index===0?350:holdNeighbor&&index===1?650:delay)));
    await route.fulfill({response});
   }finally{active--;}
  };
  await warm.route('**/api/manga/page?*',fullPageRoute);
  try{
   await warm.goto(config.url);await warm.getByRole('button',{name:'Open Keivotos menu'}).click();
   await warm.locator('.app-drawer').getByRole('button',{name:'Manga',exact:true}).click();
   const warmTile=warm.getByRole('button',{name:'The Quiet Valley',exact:true}),warmReader=warm.getByRole('dialog',{name:'Manga reader'});
   const warmDialog=warm.getByRole('dialog',{name:'The Quiet Valley chapters'});
   async function openChapter(name){await warmTile.click();await warmDialog.getByRole('button',{name,exact:true}).click();}
   async function exitChapter(){await warm.getByRole('button',{name:'Back to chapters'}).click();await warmReader.waitFor({state:'detached'});assert.equal((await warmerImages()).length,0);}
   async function ready(index){await warm.waitForFunction(index=>{const image=document.querySelector('.paged-page img');return image?.complete&&image.naturalWidth>0&&Number(image.closest('.paged-page').dataset.page)===index;},index);}
   const firstRequest=warm.waitForRequest(request=>new URL(request.url()).searchParams.get('cover')==='false');
   holdFirst=true;await openChapter('Chapter 1');await firstRequest;
   await warm.waitForTimeout(90);assert.deepEqual(requests.map(request=>request.index),[0]);assert.equal((await warmerImages()).length,0);
   await ready(0);await warm.waitForFunction(()=>window.__warmImages.filter(ref=>ref.deref()?.getAttribute('src')).length===2);await settled();
   assert.deepEqual(requests.map(request=>request.index),[0,1,2]);assert.equal(peak,1);
   report.prefetch={coldSequence:requests.map(request=>request.index),initialRequestConcurrency:peak,warmTurns:[]};
   holdFirst=false;await warmReader.focus();
   await warm.evaluate(()=>{
    const reader=document.querySelector('.reader');window.__turnTimes=[];let started=0;
    reader.addEventListener('keydown',event=>{if(['ArrowRight','ArrowLeft'].includes(event.key))started=performance.now();},true);
    reader.addEventListener('load',event=>{if(event.target.matches('.paged-page img')&&started){window.__turnTimes.push(performance.now()-started);started=0;}},true);
   });
   for(let sample=0;sample<3;sample++){
    await warm.keyboard.press('ArrowRight');await ready(1);await settled();
    await warm.keyboard.press('ArrowLeft');await ready(0);await settled();
   }
   report.prefetch.warmTurns=await warm.evaluate(()=>window.__turnTimes);
   assert.equal(requests.filter(request=>request.index===1).length,1,'warm visible page must reuse its prefetched image');
   assert.equal(requests.filter(request=>request.index===0).length,1,'revisit must reuse the displayed original');
   assert((await warmerImages()).length<=4);
   check('visible page completes before serial low-priority next-two prefetch; warm turns and revisits reuse exact revision URLs');
   for(let index=0;index<20;index++)await warm.keyboard.press('ArrowRight');await ready(12);await settled();
   assert(requests.every(request=>request.index>=0&&request.index<13));
   const lastImages=await warmerImages();assert(lastImages.every(image=>[11,12].includes(Number(new URL(image.url,config.url).searchParams.get('page')))));
   await exitChapter();await warm.keyboard.press('Escape');
   check('first/last boundaries remain bounded and closing the reader releases every retained preview');
   // A new document removes the old reader's image sharing window.
   await warm.reload();await warm.getByRole('button',{name:'Open Keivotos menu'}).click();
   await warm.locator('.app-drawer').getByRole('button',{name:'Manga',exact:true}).click();
   requests.length=0;holdNeighbor=true;
   await openChapter('Chapter 1');await ready(0);
   await warm.waitForFunction(()=>window.__warmImages.some(ref=>ref.deref()?.getAttribute('src')?.includes('page=1&')));
   await warmReader.focus();for(let index=0;index<6;index++)await warm.keyboard.press('ArrowRight');await ready(6);
   await warm.waitForTimeout(720);await settled();
   assert(!(await warm.evaluate(()=>window.__warmStarts)).some(url=>Number(new URL(url,config.url).searchParams.get('page'))===2),'cancelled old neighbor must not start its old next-two prefetch');
   assert((await warmerImages()).every(image=>[5,6,7,8].includes(Number(new URL(image.url,config.url).searchParams.get('page')))));
   await warm.getByLabel('Reading layout').selectOption('vertical');assert.equal((await warmerImages()).length,0);
   await warm.waitForTimeout(250);assert((await warmReader.locator('img').count())>0&&(await warmReader.locator('img').count())<13);
   await warm.getByLabel('Reading layout').selectOption('paged');await exitChapter();
   holdNeighbor=false;await warm.evaluate(()=>window.__largeWarmPages=true);
   await warmDialog.getByRole('button',{name:'Chapter 2',exact:true}).click();await ready(0);
   await warm.waitForTimeout(500);await settled();
   const capped=await warmerImages();assert.equal(capped.length,1);
   assert.equal(capped.reduce((sum,image)=>sum+image.width*image.height*4,0),31360000);
   assert.deepEqual(requests.filter(request=>request.chapter==='The Quiet Valley/Chapter 2.cbz').map(request=>request.index),[0,1,2]);
   report.prefetch.budgetProbe={method:'2800x2800 dimension override on detached previews; no corresponding pixel allocation',retainedImages:capped.length,estimatedDecodedBytes:31360000,limitBytes:32*1024*1024};
   await warm.evaluate(()=>window.__largeWarmPages=false);
   assert((await warmerImages()).every(image=>new URL(image.url,config.url).searchParams.get('path')==='The Quiet Valley/Chapter 2.cbz'));
   await exitChapter();await warmDialog.getByRole('button',{name:'Chapter 10',exact:true}).click();await ready(0);
   await warmReader.focus();for(let index=0;index<3;index++)await warm.keyboard.press('ArrowRight');await ready(3);
   await warm.waitForTimeout(450);assert.equal(await warmReader.getByRole('alert').count(),0);
   assert(requests.some(request=>request.chapter==='The Quiet Valley/Chapter 10.cbz'&&request.index===5));
   assert(!requests.some(request=>request.chapter==='The Quiet Valley/Chapter 10.cbz'&&request.index===5&&request.representation==='webp'));
   await warm.keyboard.press('ArrowRight');await ready(4);await warm.keyboard.press('ArrowRight');
   await warm.getByRole('alert').filter({hasText:'Original page 6'}).waitFor();
   await exitChapter();await warm.keyboard.press('Escape');
   check('rapid turns abandon stale work; mode/chapter switches clear previews; adjacent failure stays silent until displayed');
  }finally{
   await warm.unrouteAll({behavior:'wait'});
   await warmContext.tracing.stop({path:path.join(config.output,'prefetch-trace.zip')});await warmContext.close();
  }
  const corruptContext=await browser.newContext({viewport:{width:1440,height:1000}});
  await corruptContext.tracing.start({screenshots:true,snapshots:true});
  const corrupt=await corruptContext.newPage();corrupt.on('pageerror',error=>report.errors.push(error.message));
  await corrupt.route('**/api/manga/page?*',async route=>{
   const url=new URL(route.request().url());
   if(url.searchParams.get('cover')==='false'&&url.searchParams.get('page')==='0'&&url.searchParams.get('representation')==='original'){
    await route.fulfill({status:200,contentType:'image/png',headers:{'Cache-Control':'no-store'},body:'deliberately invalid generated image response'});
   }else await route.continue();
  });
  try{
   await corrupt.goto(config.url);await corrupt.getByRole('button',{name:'Open Keivotos menu'}).click();
   await corrupt.locator('.app-drawer').getByRole('button',{name:'Manga',exact:true}).click();
   await corrupt.getByRole('button',{name:'The Quiet Valley',exact:true}).click();
   await corrupt.getByRole('dialog',{name:'The Quiet Valley chapters'}).getByRole('button',{name:'Chapter 2',exact:true}).click();
   const failedReader=corrupt.getByRole('dialog',{name:'Manga reader'});
   await failedReader.getByRole('alert').filter({hasText:'Original page 1'}).waitFor();
   assert.equal(await failedReader.locator('.page-counter').textContent(),'1 / 4');
   await failedReader.focus();await corrupt.keyboard.press('ArrowRight');
   await corrupt.waitForFunction(()=>document.querySelector('.paged-page img')?.naturalWidth>0);
   assert.equal(await failedReader.locator('.page-counter').textContent(),'2 / 4');assert.equal(await failedReader.getByRole('alert').count(),0);
   await corrupt.keyboard.press('ArrowLeft');await failedReader.getByRole('alert').filter({hasText:'Original page 1'}).waitFor();
   await corrupt.getByRole('button',{name:'Open converted page',exact:true}).focus();await corrupt.keyboard.press('Space');
   await corrupt.waitForFunction(()=>document.querySelector('.paged-page img')?.naturalWidth>0);
   assert.equal(await failedReader.locator('.page-counter').textContent(),'1 / 4');
   assert((await failedReader.locator('img').getAttribute('src')).includes('representation=webp'));
   await corrupt.keyboard.press('Escape');await failedReader.waitFor({state:'detached'});
   check('a browser-rejected image keeps its page count, allows navigation away/back and accepts explicit conversion with Space without turning pages');
  }finally{
   await corruptContext.tracing.stop({path:path.join(config.output,'navigation-error-trace.zip')});await corruptContext.close();
  }
  assert.deepEqual(report.errors,[]);
  check('disable rejects Manga work and preserves source registration and rediscovery');
 }finally{fs.writeFileSync(path.join(config.output,'report.json'),JSON.stringify(report,null,2));await context.tracing.stop({path:path.join(config.output,'trace.zip')});await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
