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
 async function waitDisk(name,expected){
  const filename=path.join(config.mediaLocal||config.media,name);
  for(let attempt=0;attempt<30&&fs.readFileSync(filename,'utf8')!==expected;attempt++)await new Promise(resolve=>setTimeout(resolve,100));
  assert.equal(fs.readFileSync(filename,'utf8'),expected);
 }
 async function editorText(locator){
  return locator.evaluate(node=>[...node.querySelectorAll('.cm-line')].map(line=>line.textContent).join('\n'));
 }
 try{
  await page.goto(config.url);
  assert.equal((await api('/api/suite/modules/language/enable','POST')).status,200);
  fs.mkdirSync((config.mediaLocal||config.media)+'-other');
  const applied=await api('/api/suite/folders/apply','POST',{folders:[
   {path:config.media,display_name:'Notes',role:'language'},
   {path:config.media+'-other',display_name:'Other notes',role:'language'}
  ]});
  assert.equal(applied.status,200,JSON.stringify(applied));
  const sourceId=applied.data.sources.find(source=>source.display_name==='Notes').source_id;
  const otherSourceId=applied.data.sources.find(source=>source.display_name==='Other notes').source_id;
  await page.getByRole('button',{name:'Open Keivotos menu'}).click();
  await page.locator('.app-drawer').getByRole('button',{name:'Language',exact:true}).click();
  const welcome=page.getByRole('tab',{name:'Welcome.md',exact:true});
  let revealed=null;
  const revealRoute=async route=>{revealed=route.request().postDataJSON();await route.fulfill({json:{status:'revealed'}});};
  await page.route('**/api/files/reveal',revealRoute);
  await welcome.click({button:'right'});
  await page.getByRole('menu',{name:'Location for Welcome.md'}).getByRole('menuitem',{name:'Open in Explorer'}).click();
  assert.deepEqual(revealed,{source_id:sourceId,path:'Welcome.md'});
  await page.unroute('**/api/files/reveal',revealRoute);
  await welcome.click({button:'right'});
  await page.getByRole('menu',{name:'Location for Welcome.md'}).getByRole('menuitem',{name:'Show in Files'}).click();
  await page.locator('[data-files-entry-path="Welcome.md"]').waitFor();
  await page.getByRole('button',{name:'Open Keivotos menu'}).click();
  await page.locator('.app-drawer').getByRole('button',{name:'Language',exact:true}).click();
  await welcome.waitFor();
  check('Language tab location menu reveals the exact Markdown file and navigates into Files');
  await welcome.click();
  const editor=page.getByRole('textbox',{name:'Edit Welcome.md'});
  await editor.fill('# Updated locally\n');
  await page.waitForTimeout(700);
  assert.equal(fs.readFileSync(path.join(config.mediaLocal||config.media,'Welcome.md'),'utf8'),'# Local note\n');
  await welcome.click({button:'right'});
  await page.getByRole('menu',{name:'Location for Welcome.md'}).getByRole('menuitem',{name:'Show in Files'}).click();
  await page.getByRole('dialog',{name:'Unsaved Markdown changes'}).getByRole('button',{name:'Keep editing'}).click();
  assert.equal(await editorText(editor),'# Updated locally\n');
  assert.equal(await page.locator('.language-surface').count(),1);
  check('Show in Files respects the Language unsaved-note decision');
  const closeWelcome=page.getByRole('button',{name:'Close Welcome.md'});
  assert.equal(await closeWelcome.locator('.dirty-glyph').evaluate(node=>getComputedStyle(node).display),'block');
  await closeWelcome.hover();
  assert.equal(await closeWelcome.locator('.close-glyph').evaluate(node=>getComputedStyle(node).display),'block');
  await closeWelcome.focus();
  assert.equal(await closeWelcome.locator('.close-glyph').evaluate(node=>getComputedStyle(node).display),'block');
  await editor.press('Control+s');
  await waitDisk('Welcome.md','# Updated locally\n');
  await editor.fill('# Temporary edit\n');
  await editor.fill('# Updated locally\n');
  assert.equal(await page.getByRole('button',{name:'Save Welcome.md'}).count(),0);
  assert.equal(await page.evaluate(sourceId=>localStorage.getItem(`keivotos:language-draft:${sourceId}:Welcome.md`),sourceId),null);
  await editor.fill('# Mouse save\n');
  await page.getByRole('button',{name:'Save Welcome.md'}).click();
  await waitDisk('Welcome.md','# Mouse save\n');
  check('Ctrl+S and the visible Save action write only on request; undo to saved text returns clean');

  await editor.fill('# Close and save\n');
  await closeWelcome.click();
  const decision=page.getByRole('dialog',{name:'Unsaved Markdown changes'});
  await page.screenshot({path:path.join(config.output,'language-dirty-dialog.png')});
  await decision.press('Shift+Tab');
  assert.equal(await decision.getByRole('button',{name:'Discard changes'}).evaluate(node=>document.activeElement===node),true);
  await decision.press('Tab');
  assert.equal(await decision.getByRole('button',{name:'Save',exact:true}).evaluate(node=>document.activeElement===node),true);
  await decision.press('Escape');
  await decision.waitFor({state:'detached'});
  assert.equal(await editorText(editor),'# Close and save\n');
  await closeWelcome.click();
  await decision.getByRole('button',{name:'Save',exact:true}).click();
  await page.getByRole('tab',{name:'Welcome.md',exact:true}).waitFor({state:'detached'});
  await waitDisk('Welcome.md','# Close and save\n');
  await page.getByRole('combobox',{name:'Open Markdown file'}).selectOption('Welcome.md');
  await page.getByRole('tab',{name:'Welcome.md',exact:true}).waitFor();
  await page.getByRole('textbox',{name:'Edit Welcome.md'}).fill('# Discard this edit\n');
  await closeWelcome.click();
  await decision.getByRole('button',{name:'Discard changes'}).click();
  assert.equal(fs.readFileSync(path.join(config.mediaLocal||config.media,'Welcome.md'),'utf8'),'# Close and save\n');
  await page.getByRole('combobox',{name:'Open Markdown file'}).selectOption('Welcome.md');
  await page.getByRole('tab',{name:'Welcome.md',exact:true}).waitFor();
  assert.equal(await editorText(page.getByRole('textbox',{name:'Edit Welcome.md'})),'# Close and save\n');
  check('dirty dot and close control offer Save, Keep editing and Discard without deleting the file');

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
  await studyEditor.fill('First draft');
  await page.getByRole('button',{name:'Save Study.md'}).click();
  await firstSave;
  await studyEditor.fill('한국어 notes');
  await page.getByRole('button',{name:'Save Study.md'}).click();
  await page.getByRole('button',{name:'New Markdown file'}).click();
  await rename.press('Escape');
  await waitDisk('Study.md','한국어 notes');
  await page.unroute('**/api/language/document');
  await page.getByRole('button',{name:'New Markdown file'}).click();
  await rename.waitFor();
  assert.equal(await rename.inputValue(),'New File (2)');
  await rename.press('Escape');
  await page.getByRole('tab',{name:'New File (2).md'}).waitFor();
  await page.getByRole('tab',{name:'Study.md'}).click();
  await page.getByRole('textbox',{name:'Edit Study.md'}).fill('Save before rename');
  await page.getByRole('tab',{name:'Study.md'}).dblclick();
  await decision.getByRole('button',{name:'Keep editing'}).click();
  assert.equal(await rename.count(),0);
  await page.getByRole('tab',{name:'Study.md'}).dblclick();
  await decision.getByRole('button',{name:'Save',exact:true}).click();
  await rename.fill('Study 2');await rename.evaluate(node=>node.blur());
  await page.getByRole('tab',{name:'Study 2.md'}).waitFor();
  check('plus creates collision-safe notes; edits during save remain dirty and rename requires a save decision');

  const current=path.join(config.mediaLocal||config.media,'Study 2.md');
  fs.writeFileSync(current,'external content');
  await page.getByRole('textbox',{name:'Edit Study 2.md'}).fill('unsaved local draft');
  await page.getByRole('button',{name:'Save Study 2.md'}).click();
  await page.getByText(/Markdown file changed outside Keivotos/).waitFor();
  assert.equal(fs.readFileSync(current,'utf8'),'external content');
  assert.equal(await editorText(page.getByRole('textbox',{name:'Edit Study 2.md'})),'unsaved local draft');
  check('external edit conflict keeps both disk content and the visible local draft');

  await page.screenshot({path:path.join(config.output,'language.png')});
  assert.equal((await api('/api/suite/modules/language/disable','POST')).status,200);
  assert.equal((await api('/api/language/folders')).status,409);
  assert.equal(fs.readFileSync(current,'utf8'),'external content');
  assert.equal(fs.readFileSync(path.join(config.mediaLocal||config.media,'Welcome.md'),'utf8'),'# Close and save\n');
  check('disable blocks Language operations and leaves original Markdown files untouched');

  assert.equal((await api('/api/suite/modules/language/enable','POST')).status,200);
  await page.reload();
  await page.getByRole('button',{name:'Open Keivotos menu'}).click();
  await page.locator('.app-drawer').getByRole('button',{name:'Language',exact:true}).click();
  await page.getByRole('tab',{name:'Welcome.md',exact:true}).click();
  await page.getByRole('textbox',{name:'Edit Welcome.md'}).fill('# Draft across restart\n');
  await page.close({runBeforeUnload:false});
  assert.equal(fs.readFileSync(path.join(config.mediaLocal||config.media,'Welcome.md'),'utf8'),'# Close and save\n');
  const reopened=await context.newPage();
  reopened.on('pageerror',error=>report.errors.push(error.message));
  await reopened.goto(config.url);
  await reopened.getByRole('button',{name:'Open Keivotos menu'}).click();
  await reopened.locator('.app-drawer').getByRole('button',{name:'Language',exact:true}).click();
  await reopened.getByRole('tab',{name:'Welcome.md',exact:true}).click();
  const recovered=reopened.getByRole('textbox',{name:'Edit Welcome.md'});
  assert.equal(await editorText(recovered),'# Draft across restart\n');
  assert.equal(await reopened.getByRole('button',{name:'Save Welcome.md'}).count(),1);
  await recovered.press('Control+s');
  await waitDisk('Welcome.md','# Draft across restart\n');
  await reopened.waitForFunction(sourceId=>!localStorage.getItem(`keivotos:language-draft:${sourceId}:Welcome.md`),sourceId);
  check('closing without saving preserves a recoverable draft across a new browser session');

  await recovered.fill('# Folder save A\n');
  await reopened.getByRole('button',{name:'New Markdown file'}).click();
  const newName=reopened.getByRole('textbox',{name:'Rename Markdown file'});
  await newName.fill('Second');await newName.press('Enter');
  await reopened.getByRole('textbox',{name:'Edit Second.md'}).fill('Folder save B');
  await reopened.getByRole('combobox',{name:'Language folder'}).selectOption(otherSourceId);
  const reopenedDecision=reopened.getByRole('dialog',{name:'Unsaved Markdown changes'});
  await reopenedDecision.getByRole('button',{name:'Save',exact:true}).click();
  await waitDisk('Welcome.md','# Folder save A\n');
  await waitDisk('Second.md','Folder save B');
  await reopened.getByRole('combobox',{name:'Language folder'}).selectOption(sourceId);
  await reopened.getByRole('tab',{name:'Welcome.md',exact:true}).click();
  await reopened.getByRole('textbox',{name:'Edit Welcome.md'}).fill('# Module leave draft\n');
  await reopened.getByRole('button',{name:'Open Keivotos menu'}).click();
  const drawer=reopened.locator('.app-drawer');
  await drawer.getByRole('button',{name:'Files',exact:true}).click();
  await reopenedDecision.getByRole('button',{name:'Keep editing'}).click();
  assert.equal(await editorText(reopened.getByRole('textbox',{name:'Edit Welcome.md'})),'# Module leave draft\n');
  await drawer.getByRole('button',{name:'Files',exact:true}).click();
  await reopenedDecision.getByRole('button',{name:'Discard changes'}).click();
  await reopened.getByRole('textbox',{name:'Edit Welcome.md'}).waitFor({state:'detached'});
  await waitDisk('Welcome.md','# Folder save A\n');
  await reopened.getByRole('button',{name:'Open Keivotos menu'}).click();
  await reopened.locator('.app-drawer').getByRole('button',{name:'Language',exact:true}).click();
  await reopened.getByRole('tab',{name:'Welcome.md',exact:true}).click();
  assert.equal(await editorText(reopened.getByRole('textbox',{name:'Edit Welcome.md'})),'# Folder save A\n');
  check('folder switch saves all dirty tabs; module switch asks before leaving and discard keeps disk bytes');

  const formatted=reopened.getByRole('textbox',{name:'Edit Welcome.md'});
  const toolbar=reopened.getByRole('toolbar',{name:'Markdown formatting'});
  for(let level=1;level<=6;level++){
   await formatted.fill('Heading text');
   await toolbar.getByRole('combobox',{name:'Heading level'}).selectOption(`heading-${level}`);
   assert.equal(await editorText(formatted),'#'.repeat(level)+' Heading text');
  }
  for(const [button,expected] of [
   ['Bold','**words**'],['Italic','*words*'],['Bold and italic','***words***'],['Highlight','==words==']
  ]){
   await formatted.fill('words');await formatted.press('Control+a');
   await toolbar.getByRole('button',{name:button,exact:true}).click();
   assert.equal(await editorText(formatted),expected);
  }
  await formatted.press('Control+z');
  assert.equal(await editorText(formatted),'words');
  await formatted.press('Control+y');
  assert.equal(await editorText(formatted),'==words==');
  assert.equal(await formatted.locator('.cm-markdown-highlight').count(),1);
  await formatted.fill('before');
  await toolbar.getByRole('button',{name:'Insert horizontal rule'}).click();
  assert.equal(await editorText(formatted),'before\n\n---\n');
  check('heading levels, rule, bold, italic, combined emphasis and highlight insert readable Markdown');

  const remoteRequests=[];
  reopened.on('request',request=>{if(!request.url().startsWith(config.url))remoteRequests.push(request.url());});
  const corpus='---\ntitle: 원문\n---\n\n# Heading\n\n**bold *nested*** and ***both***\n'+
   '| One | Two |\n| --- | --- |\n| escaped \\| pipe | 한국어 |\n\n'+
   '`==literal==` and \\==escaped== and ==visible==\n\n'+
   '```md\n==fenced==\n```\n\n'+
   '<script>window.__languageUnsafe = true</script>\n'+
   '![remote](https://example.invalid/never-load.png)\n';
  await formatted.fill(corpus);
  assert.equal(await formatted.locator('.cm-markdown-highlight').count(),1);
  assert.equal(await reopened.evaluate(()=>window.__languageUnsafe),undefined);
  await formatted.press('Control+s');
  await waitDisk('Welcome.md',corpus);
  await reopened.getByRole('tab',{name:'Study 2.md'}).click();
  await reopened.getByRole('tab',{name:'Welcome.md'}).click();
  assert.equal(await editorText(reopened.getByRole('textbox',{name:'Edit Welcome.md'})),corpus);
  assert.equal(await reopened.getByRole('button',{name:'Save Welcome.md'}).count(),0);
  assert.deepEqual(remoteRequests,[]);
  await reopened.screenshot({path:path.join(config.output,'language-markdown-editor.png')});
  check('mixed Markdown round-trips unchanged; literal markers stay literal and raw HTML/remote images do not run');
  // Deterministic clipboard seam: never inspect or overwrite the user's OS clipboard.
  await reopened.evaluate(()=>{
   window.__testClipboard={text:'',denyRead:false,denyWrite:false,delay:0};
   Object.defineProperty(navigator,'clipboard',{configurable:true,value:{
    readText:async()=>{const state=window.__testClipboard;await new Promise(resolve=>setTimeout(resolve,state.delay));if(state.denyRead)throw new DOMException('Denied','NotAllowedError');return state.text;},
    writeText:async text=>{const state=window.__testClipboard;await new Promise(resolve=>setTimeout(resolve,state.delay));if(state.denyWrite)throw new DOMException('Denied','NotAllowedError');state.text=text;}
   }});
  });
  const textMenu=reopened.getByRole('menu',{name:'Markdown text actions'});
  async function openTextMenu(){await formatted.press('Shift+F10');await textMenu.waitFor();}
  await formatted.fill('alpha beta');
  await formatted.press('Control+Home');
  for(let index=0;index<5;index++)await formatted.press('Shift+ArrowRight');
  const firstLine=await formatted.locator('.cm-line').first().boundingBox();
  await reopened.mouse.click(firstLine.x+15,firstLine.y+10,{button:'right'});
  await textMenu.waitFor();
  await textMenu.getByRole('menuitem',{name:'Copy',exact:true}).click();
  assert.equal(await reopened.evaluate(()=>window.__testClipboard.text),'alpha');
  assert.equal(await editorText(formatted),'alpha beta');
  await openTextMenu();
  await textMenu.getByRole('menuitem',{name:'Cut',exact:true}).click();
  assert.equal(await editorText(formatted),' beta');
  await formatted.press('Control+z');
  assert.equal(await editorText(formatted),'alpha beta');
  await openTextMenu();
  await textMenu.getByRole('menuitem',{name:'Paste',exact:true}).click();
  assert.equal(await editorText(formatted),'alpha beta');
  check('keyboard text menu retains selection; Copy is nonmutating and Cut deletes only copied text with one-step undo');

  await formatted.press('Control+Home');
  for(let index=0;index<5;index++)await formatted.press('Shift+ArrowRight');
  await reopened.evaluate(()=>{window.__testClipboard.denyWrite=true;});
  for(const kind of ['Copy','Cut']){
   await openTextMenu();await textMenu.getByRole('menuitem',{name:kind,exact:true}).click();
   await textMenu.getByRole('alert').waitFor();
   assert.match(await textMenu.getByRole('alert').innerText(),/Clipboard access was blocked/);
   assert.equal(await editorText(formatted),'alpha beta');
   await textMenu.press('Escape');
  }
  await reopened.evaluate(()=>{window.__testClipboard.denyRead=true;});
  await openTextMenu();await textMenu.getByRole('menuitem',{name:'Paste',exact:true}).click();
  await textMenu.getByRole('alert').waitFor();
  assert.match(await textMenu.getByRole('alert').innerText(),/Ctrl\+V/);
  await textMenu.press('Escape');
  assert.equal(await formatted.evaluate(node=>node.contains(document.activeElement)),true);
  assert.equal(await editorText(formatted),'alpha beta');
  await reopened.evaluate(()=>{Object.assign(window.__testClipboard,{denyRead:false,denyWrite:false,text:''});});
  await formatted.press('ArrowRight');
  await formatted.press('Control+s');await waitDisk('Welcome.md','alpha beta');
  await openTextMenu();
  assert.equal(await textMenu.getByRole('menuitem',{name:'Copy',exact:true}).isDisabled(),true);
  assert.equal(await textMenu.getByRole('menuitem',{name:'Cut',exact:true}).isDisabled(),true);
  await textMenu.getByRole('menuitem',{name:'Paste',exact:true}).click();
  assert.equal(await reopened.getByRole('button',{name:'Save Welcome.md'}).count(),0);
  check('denied clipboard never deletes content, exposes keyboard fallback and restores focus; empty Paste keeps a saved note clean');

  const paste='한국어 \\| literal\n<script>window.__clipboardUnsafe=true</script>\n![image](https://example.invalid/clipboard.png)';
  await reopened.evaluate(text=>{window.__testClipboard.text=text;},paste);
  await formatted.press('Control+End');await openTextMenu();
  await textMenu.getByRole('menuitem',{name:'Paste',exact:true}).click();
  assert.equal(await editorText(formatted),'alpha beta'+paste);
  assert.equal(await reopened.evaluate(()=>window.__clipboardUnsafe),undefined);
  assert.deepEqual(remoteRequests,[]);
  await formatted.press('Control+z');assert.equal(await editorText(formatted),'alpha beta');
  check('Paste inserts exact plain Unicode/Markdown source, stays inert and can be undone without remote requests');

  await formatted.press('Control+Home');
  for(let index=0;index<5;index++)await formatted.press('Shift+ArrowRight');
  await reopened.evaluate(()=>{window.__testClipboard.delay=450;});
  await openTextMenu();await textMenu.getByRole('menuitem',{name:'Cut',exact:true}).click();
  await reopened.getByRole('tab',{name:'Second.md',exact:true}).click();
  await reopened.waitForTimeout(550);
  assert.equal(await editorText(reopened.getByRole('textbox',{name:'Edit Second.md'})),'Folder save B');
  await reopened.getByRole('tab',{name:'Welcome.md',exact:true}).click();
  assert.equal(await editorText(formatted),'alpha beta');
  await reopened.evaluate(()=>{window.__testClipboard.delay=0;});
  check('switching notes during delayed Cut prevents late clipboard completion from deleting either note');

  await formatted.fill('beforeafter');await formatted.press('Control+Home');
  for(let index=0;index<6;index++)await formatted.press('ArrowRight');
  await openTextMenu();
  await textMenu.press('End');
  assert.equal(await textMenu.getByRole('menuitem',{name:'Insert table'}).evaluate(node=>document.activeElement===node),true);
  await reopened.keyboard.press('Enter');
  const initial='before\n\n|  |  |\n| --- | --- |\n|  |  |\n\nafter';
  assert.equal(await editorText(formatted),initial);
  const addRow=reopened.getByRole('button',{name:'Add table row',exact:true});
  const addColumn=reopened.getByRole('button',{name:'Add table column',exact:true});
  await addRow.waitFor();await addColumn.waitFor();
  await addRow.click();assert.equal(await editorText(formatted),initial.replace('|  |  |\n\nafter','|  |  |\n|  |  |\n\nafter'));
  await formatted.press('Control+z');assert.equal(await editorText(formatted),initial);
  await formatted.press('Control+y');
  await addRow.focus();await addRow.press('Space');
  await addColumn.focus();await addColumn.press('Enter');
  await addColumn.click();
  const grown='before\n\n|  |  |  |  |\n| --- | --- | --- | --- |\n|  |  |  |  |\n|  |  |  |  |\n|  |  |  |  |\n\nafter';
  assert.equal(await editorText(formatted),grown);
  await formatted.press('Control+z');
  assert.equal(await editorText(formatted),grown.replaceAll('|  |  |  |  |','|  |  |  |').replace('| --- | --- | --- | --- |','| --- | --- | --- |'));
  await formatted.press('Control+y');assert.equal(await editorText(formatted),grown);
  await reopened.screenshot({path:path.join(config.output,'language-table-controls.png')});
  check('Insert table preserves surrounding text at the caret; 2x2 grows one row/column per mouse or keyboard action with separate undo/redo');

  async function replaceSource(text){await formatted.press('Control+a');await reopened.keyboard.insertText(text);}
  const escapedTable='| Name | Meaning |\n| :--- | ---: |\n| escaped \\| pipe | 日本語 한국어 |';
  await replaceSource(escapedTable);
  await formatted.press('Control+Home');await formatted.press('ArrowDown');await formatted.press('ArrowDown');
  await formatted.press('Home');for(let index=0;index<4;index++)await formatted.press('ArrowRight');
  await addColumn.click();
  await formatted.type('X');
  const exactTable='| Name | Meaning |  |\n| :--- | ---: | --- |\n| esXcaped \\| pipe | 日本語 한국어 |  |';
  assert.equal(await editorText(formatted),exactTable);
  await addRow.click();
  const savedTable=exactTable+'\n|  |  |  |';
  await formatted.press('Control+s');await waitDisk('Welcome.md',savedTable);
  await reopened.getByRole('tab',{name:'Second.md'}).click();
  await reopened.getByRole('tab',{name:'Welcome.md'}).click();
  assert.equal(await editorText(formatted),savedTable);
  assert.equal(await reopened.getByRole('button',{name:'Save Welcome.md'}).count(),0);
  check('table growth preserves cursor, alignment, escaped pipes and Unicode; explicit save/reopen matches exact Markdown bytes');

  await replaceSource('A | B\n--- | ---\nx | y');await addColumn.waitFor();await addColumn.click();
  assert.equal(await editorText(formatted),'A | B |  |\n--- | --- | --- |\nx | y |  |');
  await addRow.click();
  assert.equal(await editorText(formatted),'A | B |  |\n--- | --- | --- |\nx | y |  |\n|  |  |  |');
  await replaceSource('| A | B |\n| --- | --- |\n| extra | cell | retained |');
  assert.equal(await addColumn.isDisabled(),true);assert.equal(await addRow.isDisabled(),true);
  assert.equal(await editorText(formatted),'| A | B |\n| --- | --- |\n| extra | cell | retained |');
  await replaceSource('```md\n| A | B |\n| --- | --- |\n| x | y |\n```');
  await formatted.press('Control+Home');await formatted.press('ArrowDown');
  assert.equal(await addColumn.count(),0);assert.equal(await addRow.count(),0);
  await openTextMenu();assert.equal(await textMenu.getByRole('menuitem',{name:'Insert table'}).isDisabled(),true);
  await textMenu.press('Escape');
  check('optional outer pipes expand correctly; ragged table cells are preserved and code-fenced tables stay literal');

  await replaceSource('> | A | B |\n> | --- | --- |\n> | x | y |');
  await addColumn.waitFor();await addColumn.click();await addRow.click();
  assert.equal(await editorText(formatted),'> | A | B |  |\n> | --- | --- | --- |\n> | x | y |  |\n> |  |  |  |');
  check('nested blockquote table growth preserves every Markdown prefix');

  await reopened.setViewportSize({width:360,height:700});
  const existingWidth=await reopened.evaluate(()=>document.documentElement.scrollWidth);
  await replaceSource('| Very long heading | 説明 |\n| --- | --- |\n| '+('long '.repeat(24))+' | 漢字 |');
  await addColumn.waitFor();await addColumn.focus();
  await addColumn.press('Enter');
  const bodyWidth=await reopened.evaluate(()=>document.documentElement.scrollWidth);
  assert.ok(bodyWidth<=Math.max(360,existingWidth),`table introduced horizontal overflow: ${bodyWidth} versus ${existingWidth}`);
  const buttonBounds=await addColumn.boundingBox();
  assert.ok(buttonBounds.x>=0&&buttonBounds.x+buttonBounds.width<=360);
  const bounds=await formatted.boundingBox();
  assert.ok(bounds.x>=0&&bounds.x+bounds.width<=360);
  report.compact={existingDocumentWidth:existingWidth,documentWidth:bodyWidth,editor:bounds,columnButton:buttonBounds};
  await reopened.mouse.click(bounds.x+bounds.width-12,bounds.y+bounds.height-16,{button:'right'});
  await textMenu.waitFor();const menuBounds=await textMenu.boundingBox();
  assert.ok(menuBounds.x>=8&&menuBounds.y>=8&&menuBounds.x+menuBounds.width<=352&&menuBounds.y+menuBounds.height<=692);
  await reopened.screenshot({path:path.join(config.output,'language-table-compact.png')});
  await textMenu.press('Escape');
  check('long tables retain line wrapping and keyboard controls; right-click menu fits a compact viewport and dismisses with Escape');

  // Requests belong to the folder/session that initiated them, even when a
  // different folder has the same filename and starting content revision.
  const racePage=await context.newPage();racePage.setDefaultTimeout(12000);
  racePage.on('pageerror',error=>report.errors.push(error.message));
  const notesA=config.mediaLocal||config.media,notesB=notesA+'-other';
  const shared='Race shared.md',onlyA='Race A.md',onlyB='Race B.md',template='# Shared template\n';
  fs.writeFileSync(path.join(notesA,shared),template,{flag:'wx'});
  fs.writeFileSync(path.join(notesB,shared),template,{flag:'wx'});
  fs.writeFileSync(path.join(notesA,onlyA),'Only A',{flag:'wx'});
  fs.writeFileSync(path.join(notesB,onlyB),'Only B',{flag:'wx'});
  await racePage.goto(config.url);
  await racePage.getByRole('button',{name:'Open Keivotos menu'}).click();
  await racePage.locator('.app-drawer').getByRole('button',{name:'Language',exact:true}).click();
  const raceFolder=racePage.getByRole('combobox',{name:'Language folder',exact:true});
  async function folderTo(id,visible){
    await raceFolder.selectOption(id);
    await racePage.getByRole('tab',{name:visible,exact:true}).waitFor();
    assert.equal(await raceFolder.inputValue(),id);
  }
  async function hold(method,endpoint,owner,name){
    let reached,release,completed,body;
    const received=new Promise(resolve=>reached=resolve),unlocked=new Promise(resolve=>release=resolve),done=new Promise(resolve=>completed=resolve);
    const handler=async route=>{
      const request=route.request(),url=new URL(request.url());
      const payload=method==='GET'?Object.fromEntries(url.searchParams):request.postDataJSON();
      if(request.method()!==method||url.pathname!==endpoint||payload.source_id!==owner||(name&&payload.name!==name))return route.continue();
      const response=await route.fetch();assert(response.ok(),await response.text());body=await response.json();
      reached();await unlocked;await route.fulfill({response});completed();
    };
    await racePage.route('**/api/language/**',handler);
    return {received,get body(){return body;},release:async()=>{
      const delivered=racePage.waitForResponse(response=>response.request().method()===method&&new URL(response.url()).pathname===endpoint);
      release();await done;await (await delivered).finished();
      await racePage.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
      await racePage.unroute('**/api/language/**',handler);
    }};
  }
  async function saveRace(name,text,owner,folder){
    const input=racePage.getByRole('textbox',{name:`Edit ${name}`,exact:true});
    await input.fill(text);
    const saving=racePage.waitForRequest(request=>request.method()==='PUT'&&new URL(request.url()).pathname==='/api/language/document');
    await input.press('Control+s');const payload=(await saving).postDataJSON();
    assert.equal(payload.source_id,owner);assert.equal(payload.name,name);
    await racePage.getByRole('button',{name:`Save ${name}`,exact:true}).waitFor({state:'detached'});
    assert.equal(fs.readFileSync(path.join(folder,name),'utf8'),text);
  }

  await folderTo(sourceId,onlyA);
  let delayed=await hold('GET','/api/language/document',sourceId,shared);
  await racePage.getByRole('tab',{name:shared,exact:true}).click();await delayed.received;
  await folderTo(otherSourceId,onlyB);await delayed.release();
  assert.equal(await racePage.getByRole('textbox',{name:`Edit ${shared}`,exact:true}).count(),0);
  assert.equal(fs.readFileSync(path.join(notesA,shared),'utf8'),template);
  assert.equal(fs.readFileSync(path.join(notesB,shared),'utf8'),template);
  await racePage.getByRole('tab',{name:shared,exact:true}).click();
  await saveRace(shared,'Explicit B edit',otherSourceId,notesB);
  await folderTo(sourceId,onlyA);await racePage.getByRole('tab',{name:shared,exact:true}).click();
  await saveRace(shared,'Explicit A edit',sourceId,notesA);
  assert.equal(fs.readFileSync(path.join(notesB,shared),'utf8'),'Explicit B edit');
  check('delayed cross-folder read cannot bind a note to another source; identical starting revisions save only after an explicit current-folder open');

  await folderTo(otherSourceId,onlyB);
  delayed=await hold('GET','/api/language/documents',sourceId);
  await raceFolder.selectOption(sourceId);await delayed.received;
  await folderTo(otherSourceId,onlyB);await delayed.release();
  assert.equal(await racePage.getByRole('tab',{name:onlyA,exact:true}).count(),0);
  assert.equal(await racePage.getByRole('tab',{name:onlyB,exact:true}).count(),1);
  check('an older folder listing cannot replace the current folder tabs');

  await folderTo(sourceId,onlyA);
  delayed=await hold('POST','/api/language/documents',sourceId);
  await racePage.getByRole('button',{name:'New Markdown file'}).click();await delayed.received;
  const created=delayed.body.name;
  assert.equal(fs.readFileSync(path.join(notesA,created),'utf8'),'');
  fs.writeFileSync(path.join(notesB,created),'',{flag:'wx'});
  await folderTo(otherSourceId,onlyB);await delayed.release();
  assert.equal(await racePage.getByRole('textbox',{name:'Rename Markdown file'}).count(),0);
  assert.equal(await racePage.getByRole('textbox',{name:`Edit ${created}`,exact:true}).count(),0);
  await racePage.getByRole('tab',{name:created,exact:true}).click();
  await saveRace(created,'Explicit B created-note edit',otherSourceId,notesB);
  assert.equal(fs.readFileSync(path.join(notesA,created),'utf8'),'');
  check('late create completion stays in its initiating folder and cannot open or rename a same-named note elsewhere');

  delayed=await hold('POST','/api/language/document/rename',otherSourceId,created);
  await racePage.getByRole('tab',{name:created,exact:true}).dblclick();
  const raceRename=racePage.getByRole('textbox',{name:'Rename Markdown file'});
  await raceRename.fill('Race renamed B');await raceRename.press('Enter');await delayed.received;
  await folderTo(sourceId,onlyA);await delayed.release();
  assert.equal(await racePage.getByRole('tab',{name:'Race renamed B.md',exact:true}).count(),0);
  assert.equal(await racePage.getByRole('textbox').count(),0);
  assert.equal(fs.readFileSync(path.join(notesB,'Race renamed B.md'),'utf8'),'Explicit B created-note edit');
  assert.equal(fs.readFileSync(path.join(notesA,created),'utf8'),'');
  check('an accepted rename finishes in its original folder without altering the new folder view');

  delayed=await hold('GET','/api/language/document',sourceId,onlyA);
  await racePage.getByRole('tab',{name:onlyA,exact:true}).click();await delayed.received;
  await racePage.getByRole('tab',{name:shared,exact:true}).click();
  await racePage.getByRole('textbox',{name:`Edit ${shared}`,exact:true}).waitFor();await delayed.release();
  assert.equal(await racePage.getByRole('textbox',{name:`Edit ${onlyA}`,exact:true}).count(),0);
  assert.equal(await editorText(racePage.getByRole('textbox',{name:`Edit ${shared}`,exact:true})),'Explicit A edit');
  check('a late note read cannot steal the newer note selection within the same folder');

  delayed=await hold('GET','/api/language/document',sourceId,onlyA);
  await racePage.getByRole('tab',{name:onlyA,exact:true}).click();await delayed.received;
  await racePage.getByRole('button',{name:`Close ${onlyA}`,exact:true}).click();await delayed.release();
  assert.equal(await racePage.getByRole('tab',{name:onlyA,exact:true}).count(),0);
  assert.equal(fs.readFileSync(path.join(notesA,onlyA),'utf8'),'Only A');
  await racePage.screenshot({path:path.join(config.output,'language-folder-ownership.png')});
  await racePage.close();
  check('closing a pending note prevents late reopening while retaining the original file');
  assert.deepEqual(report.errors,[]);
 }finally{
  fs.writeFileSync(path.join(config.output,'report.json'),JSON.stringify(report,null,2));
  await context.tracing.stop({path:path.join(config.output,'trace.zip')});await browser.close();
 }
})().catch(error=>{console.error(error);process.exitCode=1;});
