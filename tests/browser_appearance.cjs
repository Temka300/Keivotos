const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const config=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
(async()=>{
 const browser=await chromium.launch({headless:true,channel:process.env.PLAYWRIGHT_CHANNEL});
 const context=await browser.newContext({viewport:{width:1440,height:1000}});
 const page=await context.newPage();page.setDefaultTimeout(12000);
 const report={checks:[],errors:[]};page.on('pageerror',error=>report.errors.push(error.message));
 await context.tracing.start({screenshots:true,snapshots:true});
 const check=text=>{report.checks.push(text);console.log('PASS: '+text);};
 const dialog=page.getByRole('dialog',{name:'Settings',exact:true});
 const section=name=>dialog.getByRole('navigation',{name:'Settings sections'}).getByRole('button',{name,exact:true}).first();
 async function open(){await page.getByRole('button',{name:'Open Keivotos menu',exact:true}).click();await page.getByRole('button',{name:'Settings',exact:true}).click();await section('Appearance').click();}
 const color=locator=>locator.evaluate(node=>getComputedStyle(node).backgroundColor);
 try{
  await page.goto(config.url);await open();
  const selected=[], semantic=[];
  const semanticColors=()=>page.evaluate(()=>{
    const node=document.createElement('span');document.body.append(node);
    node.className='text-copyright-300';const tag=getComputedStyle(node).color;
    node.className='text-red-300';const error=getComputedStyle(node).color;node.remove();return {tag,error};
  });
  for(const accent of ['purple','pink','cyan','yellow','blue','green','orange']){
   await page.getByLabel('Accent style',{exact:true}).selectOption(accent);
   await page.waitForFunction(value=>document.documentElement.dataset.accent===value,accent);
   await section('Backup').click();await page.getByRole('button',{name:'Back up now',exact:true}).waitFor();
   semantic.push(await semanticColors());
   selected.push(await color(page.getByRole('button',{name:'Back up now',exact:true})));
   const mark=dialog.locator('.backup-check').first();
   assert.notEqual(await mark.evaluate(node=>getComputedStyle(node).color),'rgba(0, 0, 0, 0)');
   await section('Appearance').click();
  }
  assert.equal(new Set(selected).size,7);
  assert.equal(new Set(semantic.map(value=>JSON.stringify(value))).size,1);
  check('all seven accents change rendered controls while tag and error colors stay stable');
  await page.getByLabel('Accent style',{exact:true}).selectOption('cyan');
  await section('Modules').click();await page.getByRole('switch',{name:'Danbooru module',exact:true}).click();
  await section('Browsing').waitFor();await section('Browsing').click();
  const heart=page.getByRole('switch',{name:'Toggle Heart Spam',exact:true});
  const artist=page.getByRole('switch',{name:'Toggle artist notifications',exact:true});
  // Defaults may differ; both enabled switches should share the selected accent.
  for(const toggle of [heart,artist])if(await toggle.getAttribute('aria-checked')!=='true')await toggle.click();
  await page.waitForTimeout(300);
  assert.equal(await color(heart),await color(artist));
  await section('Display').click();
  const range=dialog.locator('input[type=range]');
  const modernRange=await range.evaluate(node=>getComputedStyle(node).accentColor);
  await section('Library').click();
  assert.equal(await dialog.locator('#setting-library-health').evaluate(node=>getComputedStyle(node).backgroundImage),'none');
  await section('Advanced').click();await page.getByLabel('Settings style',{exact:true}).selectOption('legacy');
  await section('Browsing').click();assert.notEqual(await color(heart),await color(artist));
  await section('Display').click();assert.notEqual(await range.evaluate(node=>getComputedStyle(node).accentColor),modernRange);
  await section('Library').click();assert.notEqual(await dialog.locator('#setting-library-health').evaluate(node=>getComputedStyle(node).backgroundImage),'none');
  await page.screenshot({path:path.join(config.output,'legacy-library.png')});
  check('Modern unifies controls and neutral panels; Legacy restores pink/cyan controls and decorated library');
  await page.reload();await open();
  assert.equal(await page.getByLabel('Accent style',{exact:true}).inputValue(),'cyan');
  await section('Advanced').click();assert.equal(await page.getByLabel('Settings style',{exact:true}).inputValue(),'legacy');
  await page.getByLabel('Settings style',{exact:true}).selectOption('modern');
  await section('Backup').click();await page.waitForTimeout(250);await page.screenshot({path:path.join(config.output,'modern-backup.png')});
  await section('Appearance').click();await page.waitForTimeout(250);await page.screenshot({path:path.join(config.output,'appearance.png')});
  check('accent and style persist independently across reload and switch back without losing settings');
  assert.deepEqual(report.errors,[]);
 }finally{fs.writeFileSync(path.join(config.output,'report.json'),JSON.stringify(report,null,2));await context.tracing.stop({path:path.join(config.output,'trace.zip')});await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
