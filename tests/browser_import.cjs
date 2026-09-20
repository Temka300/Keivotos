// Timed update/retry/cancel checks. Network metadata work is simulated.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const config = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const report = { checks: [], errors: [], requests: [] };
(async () => {
 const browser = await chromium.launch({headless:true, channel:process.env.PLAYWRIGHT_CHANNEL});
 const context = await browser.newContext({viewport:{width:1440,height:1000}});
 await context.tracing.start({screenshots:true,snapshots:true});
 const page = await context.newPage();
 page.setDefaultTimeout(12000);
 let fixture = false, state = 'idle', taskReads = 0, requests = [], blocked = false;
 const phases = {total:3,discovered:3,enriched:3,metadata:1,finalized:3,errors:1,no_match:1};
 const task = () => ({status:state,stage:'Fetching Danbooru tags',progress:2,total:3,
   output:'Fixture: connection interrupted; tags saved.',
   result_counts:{matched:1,partial:1,no_match:0,error:0},
   file_results:state==='running' ? [] : [{filename:'sample.png',path:'sample.png',status:'partial',detail:'Tags saved; extra details incomplete',index:2,total:3}]});
 page.on('pageerror',e=>report.errors.push(e.message));
 page.on('console',m=>{if(m.type()==='error')report.errors.push(m.text());});
 await page.route('**/*', async route=>{
  const request=route.request(), u=new URL(request.url());
  if(u.origin!==config.url){report.errors.push('Unexpected external request');return route.abort();}
  if(fixture){
   if(u.pathname==='/api/tools/folders')return route.fulfill({json:[{name:'Fixture folder',path:'/fixture',registered:true,exists:true}]});
   if(u.pathname==='/api/import-pipeline')return route.fulfill({json:{phases,task:task()}});
   if(u.pathname==='/api/import-pipeline/task'){taskReads++;return route.fulfill({json:task()});}
   if(u.pathname==='/api/import-pipeline/run'){
    requests.push(request.postDataJSON());
    if(blocked)return route.fulfill({json:{status:'busy',active_tool_id:'sync'}});
    state='running';return route.fulfill({json:{status:'started'}});
   }
   if(u.pathname==='/api/import-pipeline/cancel'){state='cancelled';return route.fulfill({json:{status:'cancelling'}});}
  }
  return route.continue();
 });
 const check=s=>{report.checks.push(s);console.log('PASS: '+s);};
 const dialog=page.getByRole('dialog',{name:'Settings',exact:true});
 const section=s=>dialog.getByRole('navigation',{name:'Settings sections'}).getByRole('button',{name:s,exact:true});
 async function open(){await page.getByRole('button',{name:'Open Keivotos menu',exact:true}).click();await page.getByRole('button',{name:'Settings',exact:true}).click();await dialog.waitFor();}
 try {
  await page.goto(config.url);
  await page.getByRole('button',{name:'Open Keivotos menu',exact:true}).click();
  await page.getByRole('button',{name:'Enable',exact:true}).click();
  fixture=true;
  await page.getByRole('button',{name:'Close menu',exact:true}).waitFor({state:'hidden'});
  await open();await section('Library').click();
  await page.getByRole('button',{name:'Update library',exact:true}).waitFor();
  assert.equal(await page.getByRole('button',{name:'Run phase',exact:true}).count(),0);
  await page.waitForTimeout(1500);assert.equal(taskReads,0);
  await page.getByRole('button',{name:'Update library',exact:true}).click();
  assert.equal(requests[0].phase,'update');assert.equal(requests[0].fetch_metadata,false);assert.equal(requests[0].confirm_network,false);
  await page.waitForTimeout(1600);assert.ok(taskReads>0);
  check('one update action, local-only default, idle polling stopped and active polling running');
  state='partial';await page.getByText('Finished with incomplete results',{exact:false}).waitFor();
  await page.getByText('Tags saved; extra details incomplete',{exact:true}).waitFor();
  await page.waitForTimeout(300);const idleReads=taskReads;await page.waitForTimeout(1500);assert.equal(taskReads,idleReads);
  await page.getByLabel('Fetch missing Danbooru tags',{exact:false}).check();
  await page.getByLabel('Update folders').selectOption('/fixture');
  await page.getByLabel('Maximum files to fetch').fill('2');
  await page.getByRole('button',{name:'Retry unfinished items',exact:true}).click();
  assert.equal(requests[1].phase,'retry');assert.equal(requests[1].folder,'/fixture');assert.equal(requests[1].limit,2);assert.equal(requests[1].confirm_network,true);
  await page.getByRole('button',{name:'Cancel update',exact:true}).click();
  await page.getByRole('button',{name:'Retry unfinished items',exact:true}).waitFor();
  check('incomplete results, selected-folder retry, explicit network consent and cancellation');
  blocked=true;
  await page.getByRole('button',{name:'Update library',exact:true}).click();
  await page.getByText('Another task is running.',{exact:false}).waitFor();
  check('busy admission is shown without claiming a new job started');
  blocked=false;await page.getByRole('button',{name:'Update library',exact:true}).click();
  await section('Appearance').click();await page.waitForTimeout(300);
  const closedReads=taskReads;await page.waitForTimeout(1600);assert.equal(taskReads,closedReads);
  await section('Library').click();await page.getByRole('button',{name:'Cancel update',exact:true}).waitFor();
  await page.waitForTimeout(1400);assert.ok(taskReads>closedReads);
  check('leaving the page stops polling; returning restores the active job');
  await page.screenshot({path:path.join(config.output,'library-update.png'),fullPage:true});
  await section('Advanced').click();await page.getByRole('button',{name:'Refresh tags…',exact:true}).waitFor();
  check('deliberate metadata refresh remains separate in Advanced');
  assert.deepEqual(report.errors,[]);
 } finally {
  await page.screenshot({path:path.join(config.output,'last-screen.png'),fullPage:true}).catch(()=>{});
  report.requests=requests;
  fs.writeFileSync(path.join(config.output,'report.json'),JSON.stringify(report,null,2));
  await context.tracing.stop({path:path.join(config.output,'trace.zip')});
  await browser.close();
 }
})().catch(e=>{console.error(e);process.exitCode=1;});
