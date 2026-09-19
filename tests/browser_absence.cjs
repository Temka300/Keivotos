// Real Files-only application: no route mocks and no Danbooru source folders.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const config=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
assert.match(config.home,/[/\\]keivotos-modularization-[^/\\]+[/\\]home$/);
const report={checks:[],errors:[],requests:[]};
(async()=>{
 const browser=await chromium.launch({headless:true,channel:process.env.PLAYWRIGHT_CHANNEL});
 const context=await browser.newContext({viewport:{width:1440,height:1000}});
 await context.tracing.start({screenshots:true,snapshots:true});
 const page=await context.newPage();page.setDefaultTimeout(10000);
 page.on('pageerror',e=>report.errors.push(e.message));
 page.on('console',m=>{if(m.type()==='error')report.errors.push(m.text());});
 page.on('response',r=>{if(r.status()>=400)report.errors.push(`${r.status()} ${r.url()}`);});
 await page.route('**/*',route=>{
  const url=new URL(route.request().url());
  if(url.origin!==config.url){report.errors.push('External request '+url.href);return route.abort();}
  report.requests.push(url.pathname);return route.continue();
 });
 const check=s=>{report.checks.push(s);console.log('PASS: '+s);};
 try{
  const modules=await (await context.request.get(config.url+'/api/suite/modules')).json();
  assert.deepEqual(modules.map(m=>m.slug),['files']);
  const sourceResponse=await context.request.post(config.url+'/api/files/sources',{headers:{Origin:config.url},data:{path:config.media,display_name:'Preserved fixture'}});
  assert(sourceResponse.ok(),await sourceResponse.text());
  const source=await sourceResponse.json();
  const scan=await context.request.post(`${config.url}/api/files/sources/${source.source_id}/scan`,{headers:{Origin:config.url}});
  assert(scan.ok(),await scan.text());
  await context.addInitScript(()=>{
   localStorage.setItem('keivotos:startup-module',JSON.stringify('danbooru'));
   localStorage.setItem('keivotos:active-module',JSON.stringify('danbooru'));
  });
  await page.goto(config.url);
  await page.getByRole('button',{name:'Preserved fixture',exact:true}).click();
  await page.getByText('preserved.txt',{exact:true}).waitFor();
  assert.equal(await page.title(),'Keivotos');
  check('real Files-only startup, folder registration, scan and browsing; stale module preference falls back');
  await page.getByPlaceholder('Search this folder…').fill('preserved');
  await page.getByText('preserved.txt',{exact:true}).waitFor();
  await page.reload();
  await page.getByRole('button',{name:'Preserved fixture',exact:true}).click();
  await page.getByText('preserved.txt',{exact:true}).waitFor();
  check('Files search and reload preserve registered source data');
  await page.getByRole('button',{name:'Open Keivotos menu',exact:true}).click();
  assert.equal(await page.getByText('Danbooru',{exact:true}).count(),0);
  await page.getByRole('button',{name:'Settings',exact:true}).click();
  const dialog=page.getByRole('dialog',{name:'Settings',exact:true});await dialog.waitFor();
  assert.deepEqual(await dialog.locator('nav button').allTextContents(),['Appearance','Startup','Storage','Backup','Folders','Attachments']);
  for(const name of ['Startup','Storage','Backup','Folders','Attachments','Appearance']){
   await dialog.getByRole('navigation',{name:'Settings sections'}).getByRole('button',{name,exact:true}).click();
  }
  await page.getByRole('button',{name:'Close settings',exact:true}).click();
  check('suite drawer and every remaining Settings section work without module UI');
  const paths=(await (await context.request.get(config.url+'/openapi.json')).json()).paths;
  assert(!paths['/api/images']);assert(!paths['/api/danbooru/credentials']);assert(paths['/api/files/sources']);
  assert(!report.requests.some(p=>p.startsWith('/api/danbooru')||p==='/api/images'||p==='/api/tools'));
  assert.deepEqual(report.errors,[]);
  check('module endpoints absent, no module requests or browser errors');
  await page.screenshot({path:path.join(config.output,'files-only.png')});
 }finally{
  fs.writeFileSync(path.join(config.output,'report.json'),JSON.stringify(report,null,2));
  await context.tracing.stop({path:path.join(config.output,'trace.zip')});await browser.close();
 }
})().catch(error=>{console.error(error);process.exitCode=1;});
