// Reproduce missing-service and old-backend responses without touching live data.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const config = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
(async()=>{
 const browser=await chromium.launch({headless:true,channel:process.env.PLAYWRIGHT_CHANNEL});
 const context=await browser.newContext({viewport:{width:1440,height:1000}});
 const page=await context.newPage();page.setDefaultTimeout(12000);
 const report={checks:[],errors:[]};let diagnosticsMissing=true,recoveryMissing=false,legacyBackup=false,opened=[];
 page.on('pageerror',e=>report.errors.push(e.message));
 await context.tracing.start({screenshots:true,snapshots:true});
 await page.route('**/*',async route=>{
  const url=new URL(route.request().url());
  if(url.origin!==config.url){report.errors.push('Unexpected external request');return route.abort();}
  if((diagnosticsMissing && url.pathname==='/api/diagnostics')||(recoveryMissing && url.pathname==='/api/local-recovery'))return route.fulfill({status:404,json:{detail:'Not Found'}});
  if(url.pathname.startsWith('/api/diagnostics/open/')){opened.push(url.pathname.split('/').pop());return route.fulfill({json:{status:'opened'}});}
  if(legacyBackup && url.pathname==='/api/backups'){const response=await route.fetch();const value=await response.json();delete value.options;delete value.automatic_status;return route.fulfill({json:value});}
  return route.continue();
 });
 const dialog=page.getByRole('dialog',{name:'Settings',exact:true});
 const section=name=>dialog.getByRole('navigation',{name:'Settings sections'}).getByRole('button',{name,exact:true}).first();
 const check=message=>{report.checks.push(message);console.log('PASS: '+message);};
 try{
  await page.goto(config.url);await page.getByRole('button',{name:'Open Keivotos menu',exact:true}).click();
  assert.equal(await page.getByRole('button',{name:'Manage modules',exact:true}).count(),0);
  await page.locator('.app-drawer').getByText('Coming Soon',{exact:true}).waitFor();
  await page.getByRole('button',{name:'Settings',exact:true}).click();await section('Modules').click();
  await page.getByText(/Experimental module preferences is unavailable/).waitFor();
  assert.equal(await page.getByRole('switch',{name:'Danbooru module'}).isEnabled(),true);
  assert.equal(await page.getByRole('switch',{name:'Video module'}).isEnabled(),true);
  assert.equal(await page.getByRole('switch',{name:'Manga module'}).isEnabled(),true);
  assert.equal(await page.getByRole('switch',{name:'YouTube module'}).count(),0);
  await page.screenshot({path:path.join(config.output,'modules-missing-service.png')});
  check('missing diagnostics does not disable installed modules; upcoming entries are explicit and sidebar Coming Soon is restored');
  await section('Advanced').click();await page.getByText(/Diagnostic preferences is unavailable/).waitFor();
  for(const name of ['Open data folder','Open logs folder','Open application log','Open request log'])await page.getByRole('button',{name,exact:true}).click();
  assert.deepEqual(opened,['data','logs','runtime','access']);
  diagnosticsMissing=false;await section('Modules').click();await section('Advanced').click();
  await page.getByRole('switch',{name:'Show experimental modules',exact:true}).click();
  await page.waitForFunction(async()=>(await(await fetch('/api/diagnostics')).json()).show_experimental_modules);
  await section('Modules').click();await page.getByRole('switch',{name:'YouTube module',exact:true}).waitFor();
  assert.equal(await page.getByRole('switch',{name:'YouTube module',exact:true}).isDisabled(),true);
  await page.waitForTimeout(300);await page.screenshot({path:path.join(config.output,'modules.png')});
  check('Advanced folder/log buttons are independent of preferences; experimental toggle reveals YouTube');
  recoveryMissing=true;await section('Backup').click();await page.getByRole('switch',{name:'Automatic backup'}).waitFor();
  assert.equal(await page.getByRole('button',{name:'Back up now',exact:true}).isEnabled(),true);
  assert.equal(await page.getByText(/Recovery checkpoints is unavailable/).count(),0);
  check('retired recovery service is not required by backup controls');
  legacyBackup=true;recoveryMissing=false;await section('Appearance').click();await section('Backup').click();
  await page.getByText(/running backend does not support these backup settings/).waitFor();
  assert.equal(await page.getByRole('switch',{name:'Automatic backup'}).count(),0);
  legacyBackup=false;await page.getByRole('button',{name:'Retry',exact:true}).click();
  await page.getByRole('switch',{name:'Automatic backup'}).waitFor();
  await page.waitForTimeout(300);await page.screenshot({path:path.join(config.output,'backup.png')});
  check('old backup response is explained without crashing; retry loads the corrected response');
  assert.deepEqual(report.errors,[]);
 }finally{fs.writeFileSync(path.join(config.output,'report.json'),JSON.stringify(report,null,2));await context.tracing.stop({path:path.join(config.output,'trace.zip')});await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
