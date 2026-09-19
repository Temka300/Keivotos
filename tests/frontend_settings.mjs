// Captured pre-extraction Settings catalog + cross-owner dialog coordination.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { build } from '../frontend/node_modules/vite/dist/node/index.js';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const frontend=path.join(root,'frontend');
const temporary=await fs.mkdtemp(path.join(os.tmpdir(),'keivotos-settings-contract-'));
const entry=path.join(frontend,'__settings_contract__.ts');
const code=`export { settingsContributions } from './src/modules/settings';
export { createSettingsSession } from './src/lib/settingsSession';`;
try {
 const result=await build({root:frontend,configFile:false,logLevel:'silent',plugins:[{
  name:'settings-contract',resolveId:id=>id===entry?id:null,
  load:id=>id===entry?code:id.endsWith('.svelte')?'export default {};':null,
 }],build:{write:false,minify:false,lib:{entry,formats:['es']}}});
 const chunk=(Array.isArray(result)?result[0]:result).output.find(x=>x.type==='chunk');
 const file=path.join(temporary,'settings.mjs');await fs.writeFile(file,chunk.code);
 const {settingsContributions:owners,createSettingsSession}=await import(pathToFileURL(file).href);
 const baseline=JSON.parse(await fs.readFile(path.join(root,'tests/snapshots/settings_catalog.json'),'utf8'));
 assert.deepEqual(owners.map(x=>x.group),baseline.groups);
 assert.deepEqual(owners.flatMap(x=>x.sections),baseline.sections);
 // The only deliberate copy change removes a hardcoded optional owner from Files.
 baseline.searchItems.find(x=>x.id==='folder-roles').description=
   baseline.searchItems.find(x=>x.id==='folder-roles').description.replace('Files or Danbooru','Files or a module');
 const sorted=rows=>rows.toSorted((a,b)=>a.id.localeCompare(b.id));
 assert.deepEqual(sorted(owners.flatMap(x=>x.searchItems)),sorted(baseline.searchItems));
 const session=createSettingsSession(async path=>path+'/chosen');
 const calls=[];let busy;
 const stop=session.busyOwners.subscribe(value=>busy=[...value]);
 const unregister=session.register('fixture',{
  reloadFolders:async()=>calls.push('reload'),refreshImages:()=>calls.push('refresh'),
  startToolPolling:id=>calls.push(id),resumeMedia:()=>true,dismissOverlay:()=>true,
 });
 session.setBusy('fixture',true);assert.deepEqual(busy,['fixture']);
 session.setBusy('other',true);session.setBusy('fixture',false);assert.deepEqual(busy,['other']);
 assert.equal(await session.pickDirectory('/fixture'),'/fixture/chosen');
 await session.reloadFolders();session.refreshImages();session.startToolPolling('fixture','sync');
 session.startToolPolling('absent','ignored');assert.deepEqual(calls,['reload','refresh','sync']);
 assert.equal(session.resumeMedia(),true);assert.equal(session.dismissOverlay(),true);
 unregister();assert.equal(session.resumeMedia(),true);assert.equal(session.dismissOverlay(),false);
 assert.deepEqual(busy,['other']);
 const separate=createSettingsSession(async()=>null);assert.equal(separate.resumeMedia(),false);
 stop();
 console.log(`PASS: ${baseline.sections.length} sections, ${baseline.searchItems.length} search entries and isolated owner coordination`);
}finally{await fs.rm(temporary,{recursive:true,force:true});}
