const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const config=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
(async()=>{
 const browser=await chromium.launch({headless:true,channel:process.env.PLAYWRIGHT_CHANNEL});
 const page=await browser.newPage({viewport:{width:1440,height:1000}});page.setDefaultTimeout(15000);
 const report={checks:[],errors:[]};page.on('pageerror',e=>report.errors.push(e.message));
 page.on('dialog',d=>d.accept());
 const check=text=>{report.checks.push(text);console.log('PASS: '+text)};
 try{
  await page.goto(config.url);await page.getByRole('button',{name:'Open Keivotos menu'}).click();await page.getByRole('button',{name:'Settings',exact:true}).click();
  await page.getByRole('navigation',{name:'Settings sections'}).getByRole('button',{name:'Data & storage',exact:true}).click();
  const section=page.getByRole('region',{name:'Data & storage',exact:true});
  await section.getByText('Keivotos data total').waitFor();
  for(const name of ['Files Module','Danbooru Module','Video Module','Manga Module','YouTube Module','Backups','Databases','Logs & Diagnostics'])await section.getByText(name,{exact:true}).waitFor();
  await page.waitForTimeout(350);
  await page.screenshot({path:path.join(config.output,'data-storage.png')});
  await page.getByRole('button',{name:'Show all',exact:true}).click();await page.waitForTimeout(240);
  for(const tier of ['300 px','600 px','1200 px'])assert((await section.getByText(tier,{exact:true}).locator('..').textContent()).includes('1.00 MB'));
  await page.screenshot({path:path.join(config.output,'thumbnail-details.png')});
  check('requested rows render real sizes; Show all expands 300/600/1200 byte totals');
  await page.getByRole('switch',{name:'Remove stale on startup'}).check();
  await page.waitForFunction(async()=> (await(await fetch('/api/storage/usage')).json()).cleanup_on_startup);
  await page.getByRole('button',{name:'Remove stale',exact:true}).click();await page.getByText('Removed 1 thumbnail files.',{exact:true}).waitFor();
  let usage=await page.evaluate(async()=> (await(await fetch('/api/storage/usage')).json()));assert.equal(usage.thumbnails.files,3);
  await page.getByRole('button',{name:'Clear all',exact:true}).click();await page.getByText('Removed 3 thumbnail files.',{exact:true}).waitFor();
  usage=await page.evaluate(async()=> (await(await fetch('/api/storage/usage')).json()));assert.equal(usage.categories.thumbnails,0);assert(usage.categories.databases>0);
  assert(usage.categories.files>=9);
  check('stale cleanup retains current tiers; clear preserves non-cache files and databases; startup preference persists');
  assert.deepEqual(report.errors,[]);
 }finally{fs.writeFileSync(path.join(config.output,'report.json'),JSON.stringify(report,null,2));await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
