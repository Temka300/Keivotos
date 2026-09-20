// Real backup/restore in isolated storage; no live media or network operations.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const config = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
assert.match(config.home, /[/\\]keivotos-modularization-[^/\\]+[/\\]home$/);
(async () => {
 const browser = await chromium.launch({headless:true,channel:process.env.PLAYWRIGHT_CHANNEL});
 const context = await browser.newContext({viewport:{width:1440,height:1000}});
 await context.tracing.start({screenshots:true,snapshots:true});
 const page = await context.newPage(); page.setDefaultTimeout(12000);
 const report = {checks:[],errors:[],restoreRequests:0};
 const check = text => {report.checks.push(text);console.log('PASS: '+text);};
 page.on('pageerror',e=>report.errors.push(e.message));
 page.on('console',m=>{if(m.type()==='error')report.errors.push(m.text());});
 await page.route('**/*',route=>{
  const u=new URL(route.request().url());
  if(u.origin!==config.url){report.errors.push('Unexpected remote request');return route.abort();}
  if(u.pathname==='/api/backups/restore')report.restoreRequests++;
  return route.continue();
 });
 const settings=page.getByRole('dialog',{name:'Settings',exact:true});
 const restore=page.getByRole('dialog',{name:'Restore backup',exact:true});
 const moduleDialog=name=>page.getByRole('dialog',{name:`${name} backups`,exact:true});
 const automatic=page.getByRole('switch',{name:'Automatic backup',exact:true});
 async function open(){
  await page.getByRole('button',{name:'Open Keivotos menu',exact:true}).click();
  await page.getByRole('button',{name:'Settings',exact:true}).click();
  await settings.getByRole('button',{name:'Backup',exact:true}).click();
  await page.waitForFunction(()=>!document.querySelector('[aria-label="Automatic backup"]').disabled);
 }
 try {
  await page.goto(config.url);
  assert.equal(await page.evaluate(async()=>(await(await fetch('/api/storage')).json()).suite_home),config.home);
  await open();
  assert.equal(await settings.getByRole('checkbox').count(),1);
  await settings.getByRole('checkbox',{name:'User data',exact:true}).waitFor();
  await settings.getByRole('button',{name:'Files',exact:true}).click();
  assert.equal(await moduleDialog('Files').getByRole('checkbox').count(),1);
  await moduleDialog('Files').getByRole('checkbox',{name:'File attachments',exact:true}).waitFor();
  await page.keyboard.press('Escape');
  await moduleDialog('Files').waitFor({state:'detached'});
  assert.equal(await settings.isVisible(),true);
  await settings.getByRole('button',{name:'Danbooru',exact:true}).click();
  assert.equal(await moduleDialog('Danbooru').getByRole('checkbox').count(),4);
  check('module-oriented main page, real component dialogs, disabled module eligibility and Escape isolation');

  let calls=0;
  await page.route('**/api/backups/estimate',async route=>{
   const call=++calls; const response=await route.fetch(); const value=await response.json();
   value.estimated_compressed_display=call===1?'old selection':'latest selection';
   await new Promise(resolve=>setTimeout(resolve,call===1?450:20)); await route.fulfill({json:value});
  });
  const history=moduleDialog('Danbooru').getByRole('checkbox',{name:'Metadata history',exact:true});
  await history.click(); await history.click();
  await page.waitForTimeout(650);
  assert.equal(await settings.getByText('Estimated compressed size: old selection',{exact:true}).count(),0);
  await settings.getByText('Estimated compressed size: latest selection',{exact:true}).waitFor();
  await page.unroute('**/api/backups/estimate');
  await page.route('**/api/backups',async route=>{const response=await route.fetch();await new Promise(resolve=>setTimeout(resolve,300));await route.fulfill({response});});
  await moduleDialog('Danbooru').getByRole('button',{name:'Done',exact:true}).click();
  assert.equal(await history.isDisabled(),true);
  await moduleDialog('Danbooru').waitFor({state:'detached'});
  await page.unroute('**/api/backups');
  check('stale estimates cannot replace the latest selection; saving locks dialog edits');

  await page.getByLabel('Keep automatic backups',{exact:true}).selectOption('2');
  await page.waitForFunction(()=>!document.querySelector('#backup-retention').disabled);
  await page.getByLabel('Frequency',{exact:true}).selectOption('15');
  await page.waitForFunction(()=>!document.querySelector('#backup-frequency').disabled);
  await automatic.click();
  await page.waitForFunction(()=>document.querySelector('[aria-label="Automatic backup"]').getAttribute('aria-checked')==='true'&&!document.querySelector('[aria-label="Automatic backup"]').disabled);
  await page.reload(); await open();
  assert.equal(await automatic.getAttribute('aria-checked'),'true');
  assert.equal(await page.getByLabel('Keep automatic backups',{exact:true}).inputValue(),'2');
  assert.equal(await page.getByLabel('Frequency',{exact:true}).inputValue(),'15');
  await automatic.click();
  await page.waitForFunction(()=>!document.querySelector('[aria-label="Automatic backup"]').disabled);
  check('automatic enablement, retention and frequency persist across reload');

  await settings.getByRole('button',{name:'Custom',exact:true}).click();
  const picker=page.getByRole('dialog',{name:'Choose a folder',exact:true});
  await picker.getByRole('textbox',{name:'Folder path'}).fill(config.home);
  await picker.getByRole('button',{name:'Go',exact:true}).click();
  await picker.getByRole('button',{name:'Choose this folder',exact:true}).click();
  await picker.waitFor({state:'hidden'});
  await page.waitForFunction(async home=>(await(await fetch('/api/backups')).json()).destination===home,config.home);
  await settings.getByRole('button',{name:'Default',exact:true}).click();
  await page.waitForFunction(async home=>(await(await fetch('/api/backups')).json()).destination===home+'/backups',config.home);
  check('custom folder picker and default location save without moving existing backups');

  await settings.getByRole('button',{name:'Back up now',exact:true}).click();
  await settings.getByText(/Backup saved ✓/).waitFor();
  assert.match(await settings.locator('[aria-live="polite"]').innerText(),/Not included: Library index/);
  await settings.getByRole('button',{name:'Restore now',exact:true}).click();
  await restore.getByText(/Replaces user data for Files/).waitFor();
  await restore.getByText(/Not included:/).waitFor();
  await restore.getByRole('button',{name:'Cancel',exact:true}).click();
  assert.equal(report.restoreRequests,0);
  check('verified manual backup reports omissions; reviewed restore explains scope and cancellation writes nothing');
  await page.evaluate(()=>localStorage.setItem('keivotos:files-grid-size',JSON.stringify('absurd')));
  await settings.getByRole('button',{name:'Restore now',exact:true}).click();
  await restore.getByText(/Replaces user data for Files/).waitFor();
  await restore.getByRole('button',{name:'Restore',exact:true}).click();
  await restore.getByText(/Restore complete/).waitFor();
  assert.equal(report.restoreRequests,1);
  assert.equal(await page.evaluate(()=>JSON.parse(localStorage.getItem('keivotos:files-grid-size'))),'absurd');
  await restore.getByRole('button',{name:'Close backup dialog',exact:true}).click();
  await settings.locator('summary').filter({hasText:'Backup details and recovery'}).click();
  await settings.getByRole('button',{name:'Checkpoint now',exact:true}).click();
  await page.waitForFunction(()=>[...document.querySelectorAll('button')].some(b=>b.textContent==='Checkpoint now'&&!b.disabled));
  check('real scratch restore preserves browser preferences and exposes recovery results; existing checkpoint control remains');
  await settings.locator('summary').filter({hasText:'Backup details and recovery'}).click();
  await settings.locator('main').evaluate(node => node.scrollTo(0,0));
  await page.screenshot({path:path.join(config.output,'backups.png')});
  await page.route('**/api/backups',async route=>{
   const response=await route.fetch();const value=await response.json();
   value.components={user_database:true,file_attachments:true,extra_archive:false};
   value.estimate.details={user_database:value.estimate.details.user_database,file_attachments:value.estimate.details.file_attachments,
    extra_archive:{owner:'example',enabled:false,exists:false,files:0,bytes:0,display_size:'0 B'}};
   value.automatic_status={running:false,last_result:'failed',last_at:null,last_success_at:null};
   await route.fulfill({json:value});
  });
  await page.reload();await open();
  assert.equal(await settings.getByRole('button',{name:'Danbooru',exact:true}).count(),0);
  await settings.getByText(/Last backup failed/).waitFor();
  await settings.getByRole('button',{name:'example',exact:true}).click();
  await moduleDialog('example').getByRole('checkbox',{name:'extra archive',exact:true}).waitFor();
  check('fixture: absent owners disappear, contributed components remain available and failed automatic status points to Logs');
  assert.deepEqual(report.errors,[]);
 } catch(e) {report.failure=e.stack;await page.screenshot({path:path.join(config.output,'failure.png')});throw e;}
 finally {fs.writeFileSync(path.join(config.output,'report.json'),JSON.stringify(report,null,2));await context.tracing.stop({path:path.join(config.output,'trace.zip')});await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
