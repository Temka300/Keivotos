const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const config=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
assert.match(config.home,/[/\\]keivotos-modularization-[^/\\]+[/\\]home$/);
(async()=>{
 const browser=await chromium.launch({headless:true,channel:process.env.PLAYWRIGHT_CHANNEL});
 const context=await browser.newContext({viewport:{width:1280,height:850}});
 const page=await context.newPage();page.setDefaultTimeout(12000);
 const report={checks:[],errors:[]};
 page.on('pageerror',error=>report.errors.push(error.message));
 await context.tracing.start({screenshots:true,snapshots:true});
 const check=value=>{report.checks.push(value);console.log('PASS: '+value);};
 async function api(url,method='GET',body){return page.evaluate(async({url,method,body})=>{const response=await fetch(url,{method,headers:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});return {status:response.status,data:await response.json()};},{url,method,body});}
 try{
  await page.goto(config.url);
  assert.equal((await api('/api/suite/modules/language/enable','POST')).status,200);
  const applied=await api('/api/suite/folders/apply','POST',{folders:[{path:config.media,display_name:'Notes',role:'language'}]});
  assert.equal(applied.status,200,JSON.stringify(applied));
  const sourceId=applied.data.sources.find(source=>source.role==='language').source_id;
  await page.getByRole('button',{name:'Open Keivotos menu'}).click();
  await page.locator('.app-drawer').getByRole('button',{name:'Language',exact:true}).click();
  const welcome=page.getByRole('tab',{name:'Welcome.md',exact:true});
  await welcome.click();
  const editor=page.getByRole('textbox',{name:'Edit Welcome.md'});
  await editor.fill('# Updated locally\n');
  await page.waitForFunction(async sourceId=>{
   const response=await fetch('/api/language/document?source_id='+encodeURIComponent(sourceId)+'&name=Welcome.md');
   return response.ok&&(await response.json()).content==='# Updated locally\n';
  },sourceId);
  check('existing local Markdown opens in a writable full-height editor and saves');

  await page.getByRole('button',{name:'New Markdown file'}).click();
  const rename=page.getByRole('textbox',{name:'Rename Markdown file'});
  await rename.waitFor();
  assert.equal(await rename.inputValue(),'New File');
  assert.deepEqual(await rename.evaluate(node=>[node.selectionStart,node.selectionEnd]),[0,8]);
  await rename.fill('Study');await rename.press('Enter');
  await page.getByRole('tab',{name:'Study.md'}).waitFor();
  await page.route('**/api/language/document',async route=>{
   if(route.request().method()==='PUT')await new Promise(resolve=>setTimeout(resolve,500));
   await route.continue();
  });
  const studyEditor=page.getByRole('textbox',{name:'Edit Study.md'});
  const firstSave=page.waitForRequest(request=>request.method()==='PUT'&&request.url().includes('/api/language/document'));
  await studyEditor.fill('First draft');await firstSave;
  await studyEditor.fill('한국어 notes');
  await page.getByRole('button',{name:'New Markdown file'}).click();
  await rename.press('Escape');
  await page.waitForFunction(async sourceId=>{
   const response=await fetch('/api/language/document?source_id='+encodeURIComponent(sourceId)+'&name=Study.md');
   return response.ok&&(await response.json()).content==='한국어 notes';
  },sourceId);
  await page.unroute('**/api/language/document');
  await page.getByRole('button',{name:'New Markdown file'}).click();
  await rename.waitFor();
  assert.equal(await rename.inputValue(),'New File (2)');
  await rename.press('Escape');
  await page.getByRole('tab',{name:'New File (2).md'}).waitFor();
  await page.getByRole('tab',{name:'Study.md'}).dblclick();
  await rename.fill('Study 2');await rename.evaluate(node=>node.blur());
  await page.getByRole('tab',{name:'Study 2.md'}).waitFor();
  check('plus creates and opens collision-safe notes; selected stem and double-click support rename');

  const current=path.join(config.mediaLocal||config.media,'Study 2.md');
  fs.writeFileSync(current,'external content');
  await page.getByRole('textbox',{name:'Edit Study 2.md'}).fill('unsaved local draft');
  await page.getByText(/Save failed:/).waitFor();
  assert.equal(fs.readFileSync(current,'utf8'),'external content');
  assert.equal(await page.getByRole('textbox',{name:'Edit Study 2.md'}).inputValue(),'unsaved local draft');
  check('external edit conflict keeps both disk content and the visible local draft');

  await page.screenshot({path:path.join(config.output,'language.png')});
  assert.equal((await api('/api/suite/modules/language/disable','POST')).status,200);
  assert.equal((await api('/api/language/folders')).status,409);
  assert.equal(fs.readFileSync(current,'utf8'),'external content');
  assert.equal(fs.readFileSync(path.join(config.mediaLocal||config.media,'Welcome.md'),'utf8'),'# Updated locally\n');
  check('disable blocks Language operations and leaves original Markdown files untouched');

  assert.equal((await api('/api/suite/modules/language/enable','POST')).status,200);
  await page.reload();
  await page.getByRole('button',{name:'Open Keivotos menu'}).click();
  await page.locator('.app-drawer').getByRole('button',{name:'Language',exact:true}).click();
  await page.getByRole('tab',{name:'Welcome.md',exact:true}).click();
  await page.getByRole('textbox',{name:'Edit Welcome.md'}).fill('# Draft across restart\n');
  await page.close({runBeforeUnload:false});
  assert.equal(fs.readFileSync(path.join(config.mediaLocal||config.media,'Welcome.md'),'utf8'),'# Updated locally\n');
  const reopened=await context.newPage();
  reopened.on('pageerror',error=>report.errors.push(error.message));
  await reopened.goto(config.url);
  await reopened.getByRole('button',{name:'Open Keivotos menu'}).click();
  await reopened.locator('.app-drawer').getByRole('button',{name:'Language',exact:true}).click();
  await reopened.getByRole('tab',{name:'Welcome.md',exact:true}).click();
  const recovered=reopened.getByRole('textbox',{name:'Edit Welcome.md'});
  assert.equal(await recovered.inputValue(),'# Draft across restart\n');
  await recovered.fill('# Draft across restart and saved\n');
  await reopened.waitForFunction(async sourceId=>{
   const response=await fetch('/api/language/document?source_id='+encodeURIComponent(sourceId)+'&name=Welcome.md');
   return response.ok&&(await response.json()).content==='# Draft across restart and saved\n';
  },sourceId);
  const savedPath=path.join(config.mediaLocal||config.media,'Welcome.md');
  for(let attempt=0;attempt<30&&fs.readFileSync(savedPath,'utf8')!=='# Draft across restart and saved\n';attempt++){
   await new Promise(resolve=>setTimeout(resolve,100));
  }
  assert.equal(fs.readFileSync(savedPath,'utf8'),'# Draft across restart and saved\n');
  await reopened.waitForFunction(sourceId=>!localStorage.getItem(`keivotos:language-draft:${sourceId}:Welcome.md`),sourceId);
  check('closing before autosave preserves a recoverable draft across a new browser session');
  assert.deepEqual(report.errors,[]);
 }finally{
  fs.writeFileSync(path.join(config.output,'report.json'),JSON.stringify(report,null,2));
  await context.tracing.stop({path:path.join(config.output,'trace.zip')});await browser.close();
 }
})().catch(error=>{console.error(error);process.exitCode=1;});
