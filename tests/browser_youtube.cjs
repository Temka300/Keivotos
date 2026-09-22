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
 const input=page.getByLabel('Search downloads or paste a YouTube URL');
 const url='https://www.youtube.com/watch?v=abcdefghijk';
 try{
  await page.goto(config.url);assert.equal((await api('/api/youtube/library')).status,409);
  assert.equal((await api('/api/suite/modules/youtube/enable','POST')).status,200);
  assert.equal((await api('/api/suite/modules/video/enable','POST')).status,200);
  assert.equal((await api('/api/suite/folders/apply','POST',{folders:[{path:config.media,display_name:'Downloads',role:'youtube'}]})).status,200);
  await page.getByRole('button',{name:'Open Keivotos menu'}).click();await page.locator('.app-drawer').getByRole('button',{name:'YouTube',exact:true}).click();
  const toggle=page.getByRole('button',{name:'Download options',exact:true});
  for(const text of ['valley','https://example.com/watch?v=abcdefghijk','https://youtube.com.evil/watch?v=abcdefghijk','https://youtube.com/playlist?list=abc']){
   await input.fill(text);assert.equal(await page.getByRole('button',{name:'Download',exact:true}).count(),0);
  }
  await input.fill(url);assert.equal(await page.getByLabel('Video quality').count(),0);
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
  await page.getByRole('progressbar').waitFor();await page.waitForTimeout(1100);
  await input.fill('https://youtu.be/lmnopqrstuv');await page.waitForTimeout(250);
  await page.screenshot({path:path.join(config.output,'youtube-downloading.png')});
  check('URL controls animate open and close; qualities default to Best; explicit Download creates a progress card');
  await page.waitForFunction(async()=>{const data=await(await fetch('/api/youtube/library')).json();return data.items.some(x=>x.status==='complete');});
  await page.waitForTimeout(1100);await input.fill('');await page.waitForTimeout(300);
  await page.waitForFunction(()=>document.querySelector('.thumbnail img')?.naturalWidth>0);
  await page.screenshot({path:path.join(config.output,'youtube-library.png')});
  const result=(await api('/api/youtube/library')).data.items[0];assert.equal(result.status,'complete');
  assert(result.path.endsWith('Valley.mp4'));
  const files=(await api('/api/files/search?q=Valley')).data;assert(files.some(x=>x.relative_path===result.path));

  await input.fill('not found');await page.waitForTimeout(350);assert.equal(await page.locator('.download-grid article').count(),0);
  await input.fill('valley');await page.waitForTimeout(350);assert.equal(await page.locator('.download-grid article').count(),1);
  check('completed output and local thumbnail appear in YouTube, Files discovery; local search works');
  await input.fill(url);await toggle.click();await page.waitForTimeout(250);await page.getByRole('button',{name:'Download',exact:true}).click();
  await page.getByRole('button',{name:/^Cancel /}).click();await page.getByText('Cancelled',{exact:true}).waitFor();
  await page.getByRole('button',{name:/^Retry /}).click();await page.getByRole('progressbar').waitFor();
  await api('/api/suite/modules/youtube/disable','POST');assert.equal((await api('/api/youtube/library')).status,409);
  await api('/api/suite/modules/youtube/enable','POST');
  const restored=(await api('/api/youtube/library')).data.items;assert(restored.some(x=>x.status==='interrupted'));assert(restored.some(x=>x.status==='complete'));
  check('cancel and retry work; disable drains the queue, preserves completed media and prevents automatic restart');
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
