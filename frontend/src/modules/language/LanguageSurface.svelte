<script lang="ts">
  import {onMount,onDestroy,tick} from 'svelte';
  import AppDrawer from '../../components/AppDrawer.svelte';
  import {settingsInitialSection,settingsOpen} from '../../lib/suiteStores';
  import {languageApi,type LanguageDocument,type LanguageFile,type LanguageFolder} from './api';

  type OpenNote = LanguageDocument & {sourceId:string; savedContent:string; sessionId:string; dirty:boolean; saving:boolean; error:string};
  type Decision = 'save'|'keep'|'discard';
  let drawer=false, loading=true, error='';
  let folders:LanguageFolder[]=[], sourceId='', files:LanguageFile[]=[], tabs:OpenNote[]=[], openNames:string[]=[], activeName='', openSourceId='';
  let editingName='', nameDraft='', renameBusy=false, nameInput:HTMLInputElement;
  let surface:HTMLDivElement, decisionFocus:HTMLDivElement;
  let pendingDecision:{description:string; resolve:(choice:Decision)=>void}|null=null;
  let saveQueue:Promise<boolean>=Promise.resolve(true);
  $: active=tabs.find(tab=>tab.name===activeName);

  function draftKey(folder:string,name:string){return `keivotos:language-draft:${folder}:${name}`;}
  function remember(tab:OpenNote){
    const key=draftKey(tab.sourceId,tab.name);
    const value=JSON.stringify({content:tab.content,revision:tab.revision,sessionId:tab.sessionId});
    let persistent=false;
    try{localStorage.setItem(key,value);persistent=true;}catch{/* Keep a session copy if persistent storage is unavailable. */}
    try{sessionStorage.setItem(key,value);}catch{/* Persistent storage may still be available. */}
    if(!persistent)tab.error ||= 'Could not keep this draft across app restarts. Save or copy the text before leaving.';
  }
  function clearDraft(tab:OpenNote){
    const key=draftKey(tab.sourceId,tab.name);
    try{localStorage.removeItem(key);}catch{/* Storage may be disabled. */}
    try{sessionStorage.removeItem(key);}catch{/* Storage may be disabled. */}
  }
  function restoreDraft(tab:OpenNote){
    try{
      const key=draftKey(tab.sourceId,tab.name);
      let raw:string|null=null;
      try{raw=localStorage.getItem(key);}catch{/* Fall back to the current session. */}
      if(!raw)raw=sessionStorage.getItem(key);
      if(!raw)return;
      const saved=JSON.parse(raw);
      if(typeof saved.content!=='string'||typeof saved.revision!=='string')return;
      if(saved.content===tab.content){clearDraft(tab);return;}
      const diskRevision=tab.revision;
      tab.content=saved.content;tab.revision=saved.revision;
      tab.sessionId=typeof saved.sessionId==='string'?saved.sessionId:tab.sessionId;
      tab.dirty=tab.content!==tab.savedContent;
      if(saved.revision!==diskRevision)tab.error='This note changed outside Keivotos. Your draft is preserved; review it before retrying.';
      remember(tab);
    }catch{/* An invalid browser draft cannot replace the disk note. */}
  }
  async function loadFolders(){
    loading=true;error='';
    try{
      folders=await languageApi.folders();
      if(!folders.some(folder=>folder.source_id===sourceId))sourceId=folders[0]?.source_id??'';
      await loadFiles();
    }catch(caught){error=caught instanceof Error?caught.message:'Could not load Language folders.';}
    finally{loading=false;}
  }
  async function loadFiles(){
    if(!sourceId){files=[];openNames=[];openSourceId='';return;}
    files=(await languageApi.files(sourceId)).files;
    if(openSourceId!==sourceId){openNames=files.map(file=>file.name);openSourceId=sourceId;}
  }
  function saveTab(tab:OpenNote):Promise<boolean>{
    const source=tab.sourceId, name=tab.name, session=tab.sessionId;
    saveQueue=saveQueue.then(async()=>{
      if(!tab.dirty)return true;
      const content=tab.content;
      tab.saving=true;tab.error='';tabs=[...tabs];
      try{
        const saved=await languageApi.save(source,name,content,tab.revision,session);
        tab.revision=saved.revision;
        tab.savedContent=content;
        tab.dirty=tab.content!==content;
        if(tab.dirty)remember(tab);else clearDraft(tab);
        return true;
      }catch(caught){
        tab.error=caught instanceof Error?caught.message:'Save failed. Your text remains in the editor.';
        remember(tab);
        return false;
      }finally{
        tab.saving=false;tabs=[...tabs];
      }
    });
    return saveQueue;
  }
  async function askDecision(description:string):Promise<Decision>{
    if(pendingDecision)return 'keep';
    return new Promise(resolve=>{
      pendingDecision={description,resolve};
      void tick().then(()=>decisionFocus?.focus());
    });
  }
  function decide(choice:Decision){
    const current=pendingDecision;
    pendingDecision=null;
    current?.resolve(choice);
  }
  function decisionKeydown(event:KeyboardEvent){
    if(event.key==='Escape'){event.preventDefault();decide('keep');return;}
    if(event.key!=='Tab')return;
    const buttons=decisionFocus.querySelectorAll('button');
    const first=buttons[0], last=buttons[buttons.length-1];
    if(event.shiftKey&&(document.activeElement===first||document.activeElement===decisionFocus)){event.preventDefault();last?.focus();}
    else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}
  }
  async function guardTabs(targets:OpenNote[],description:string):Promise<boolean>{
    await saveQueue;
    const dirty=targets.filter(tab=>tab.dirty);
    if(!dirty.length)return true;
    const choice=await askDecision(description);
    if(choice==='keep')return false;
    if(choice==='discard'){
      for(const tab of dirty){tab.content=tab.savedContent;tab.dirty=false;tab.error='';clearDraft(tab);}
      tabs=[...tabs];
      return true;
    }
    for(const tab of dirty){
      if(!await saveTab(tab)){
        activeName=tab.name;drawer=false;
        return false;
      }
    }
    return true;
  }
  async function openDocument(name:string){
    if(name===activeName)return true;
    error='';
    let tab=tabs.find(item=>item.name===name);
    if(!tab){
      try{
        const result=await languageApi.read(sourceId,name);
        tab={...result,sourceId,savedContent:result.content,sessionId:crypto.randomUUID().replaceAll('-',''),dirty:false,saving:false,error:''};
        restoreDraft(tab);
        tabs=[...tabs,tab];
      }catch(caught){error=caught instanceof Error?caught.message:'Could not open this note.';return false;}
    }
    if(!openNames.includes(name))openNames=[...openNames,name];
    activeName=name;
    return true;
  }
  async function closeTab(name:string){
    const tab=tabs.find(item=>item.name===name);
    if(tab&&!await guardTabs([tab],`close ${name}`))return;
    const position=openNames.indexOf(name);
    const next=openNames[position+1]??openNames[position-1]??'';
    tabs=tabs.filter(item=>item!==tab);
    openNames=openNames.filter(item=>item!==name);
    if(activeName===name){activeName='';if(next)await openDocument(next);}
  }
  async function selectFolder(select:HTMLSelectElement){
    const next=select.value;
    if(next===sourceId)return;
    if(!await guardTabs(tabs,`switch to another Language folder`)){select.value=sourceId;return;}
    sourceId=next;tabs=[];openNames=[];openSourceId='';activeName='';editingName='';
    try{await loadFiles();error='';}
    catch(caught){error=caught instanceof Error?caught.message:'Could not list Language notes.';}
  }
  async function beforeNavigate(slug:string){
    return slug==='language'||await guardTabs(tabs,'switch modules');
  }
  async function create(){
    if(!sourceId)return;
    error='';
    try{
      const result=await languageApi.create(sourceId);
      files=[...files,{name:result.name,size:0}].sort((a,b)=>a.name.localeCompare(b.name));
      tabs=[...tabs,{...result,sourceId,savedContent:result.content,sessionId:crypto.randomUUID().replaceAll('-',''),dirty:false,saving:false,error:''}];
      openNames=[...openNames,result.name];
      activeName=result.name;
      await startRename(result.name);
    }catch(caught){error=caught instanceof Error?caught.message:'Could not create a note.';}
  }
  async function startRename(name:string){
    if(!await openDocument(name))return;
    const tab=tabs.find(item=>item.name===name);
    if(tab&&!await guardTabs([tab],`rename ${name}`))return;
    editingName=name;nameDraft=name.slice(0,-3);
    await tick();nameInput?.focus();nameInput?.select();
  }
  async function commitRename(){
    if(!editingName||renameBusy)return;
    const oldName=editingName, nextName=`${nameDraft.trim()}.md`;
    if(nextName===oldName){editingName='';return;}
    await saveQueue;
    const tab=tabs.find(item=>item.name===oldName);
    if(!tab)return;
    if(!await guardTabs([tab],`rename ${oldName}`))return;
    renameBusy=true;error='';
    try{
      const result=await languageApi.rename(tab.sourceId,oldName,nextName,tab.revision);
      tab.name=result.name;
      files=files.map(file=>file.name===oldName?{...file,name:result.name}:file).sort((a,b)=>a.name.localeCompare(b.name));
      openNames=openNames.map(name=>name===oldName?result.name:name);
      activeName=result.name;editingName='';tabs=[...tabs];
    }catch(caught){error=caught instanceof Error?caught.message:'Could not rename this note.';}
    finally{renameBusy=false;}
  }
  function input(event:Event){
    if(!active)return;
    active.content=(event.currentTarget as HTMLTextAreaElement).value;
    active.dirty=active.content!==active.savedContent;
    active.error='';
    if(active.dirty)remember(active);else clearDraft(active);
    tabs=[...tabs];
  }
  function keydown(event:KeyboardEvent){
    if(event.key.toLowerCase()!=='s'||(!event.ctrlKey&&!event.metaKey)||event.altKey||event.shiftKey)return;
    if(!active||editingName||pendingDecision)return;
    const target=event.target;
    if(target!==document.body&&(!(target instanceof Node)||!surface?.contains(target)))return;
    event.preventDefault();
    void saveTab(active);
  }
  function beforeUnload(event:BeforeUnloadEvent){
    if(!tabs.some(tab=>tab.dirty||tab.saving))return;
    event.preventDefault();event.returnValue='';
  }
  function foldersSettings(){settingsInitialSection.set('roots');settingsOpen.set(true);}
  onMount(()=>{window.addEventListener('beforeunload',beforeUnload);void loadFolders();});
  onDestroy(()=>{
    window.removeEventListener('beforeunload',beforeUnload);
    if(pendingDecision)decide('keep');
    for(const tab of tabs)if(tab.dirty)remember(tab);
  });
</script>

<svelte:window on:keydown={keydown}/>

<div class="language-surface" bind:this={surface}>
  <header><button class="menu" aria-label="Open Keivotos menu" on:click={()=>drawer=true}>☰</button><span>Language</span></header>
  {#if error}<p class="notice" role="alert">{error} <button on:click={loadFolders}>Retry</button></p>{/if}
  {#if loading}<p class="notice" role="status">Loading Language folders…</p>{/if}
  {#if !loading&&!folders.length}<div class="empty"><p>Assign a folder the Language role to write Markdown notes.</p><button on:click={foldersSettings}>Add Language folders in Settings</button></div>{/if}
  {#if sourceId}
    <div class="tabs" role="tablist" aria-label="Markdown files">
      <button class="plus" aria-label="New Markdown file" title="New Markdown file" on:click={create}>+</button>
      <div class="tab-scroll">
        {#each openNames as name, index (name)}
          {@const tab=tabs.find(item=>item.name===name)}
          {#if editingName===name}
            <div class="tab editing"><input aria-label="Rename Markdown file" bind:this={nameInput} bind:value={nameDraft} disabled={renameBusy} on:keydown={event=>{if(event.key==='Enter'){event.preventDefault();void commitRename();}else if(event.key==='Escape'){event.preventDefault();editingName='';}}} on:blur={commitRename}/><span>.md</span></div>
          {:else}
            <div class="tab-shell" class:active={activeName===name}>
              <button class="tab-title" role="tab" aria-selected={activeName===name} aria-describedby={tab?.dirty?`language-dirty-${index}`:undefined} on:click={()=>openDocument(name)} on:dblclick={()=>startRename(name)} title={name}>{name}</button>
              {#if tab?.dirty}<span class="sr-only" id={`language-dirty-${index}`}>Unsaved changes</span>{/if}
              <button class="tab-close" class:is-dirty={tab?.dirty} aria-label={`Close ${name}`} title={`Close ${name}`} on:click={()=>closeTab(name)}>
                <span class="close-glyph" aria-hidden="true">×</span><span class="dirty-glyph" aria-hidden="true">●</span>
              </button>
            </div>
          {/if}
        {/each}
      </div>
      {#if files.some(file=>!openNames.includes(file.name))}
        <select aria-label="Open Markdown file" value="" on:change={event=>{const select=event.currentTarget;void openDocument(select.value).then(()=>select.value='');}}>
          <option value="" disabled>Open note…</option>
          {#each files.filter(file=>!openNames.includes(file.name)) as file}<option value={file.name}>{file.name}</option>{/each}
        </select>
      {/if}
      {#if folders.length>1}<select aria-label="Language folder" value={sourceId} on:change={event=>selectFolder(event.currentTarget)}>{#each folders as folder}<option value={folder.source_id}>{folder.name}</option>{/each}</select>{/if}
    </div>
    {#if active}
      <textarea class="editor" aria-label={`Edit ${active.name}`} spellcheck="false" value={active.content} on:input={input}></textarea>
      <div class="save-status" role="status">
        {#if active.error}<span class="failed">{active.error}</span>{/if}
        <span>{#if active.saving}Saving…{:else if active.dirty}Unsaved changes…{:else}Saved{/if}</span>
        {#if active.dirty}<button aria-label={`Save ${active.name}`} on:click={()=>saveTab(active)}>{active.error?'Retry save':'Save'}</button>{/if}
      </div>
    {:else}<div class="empty"><p>{files.length?'Choose a Markdown tab or create a new file.':'Create a Markdown file with +.'}</p></div>{/if}
  {/if}
</div>
{#if drawer}<AppDrawer beforeNavigate={beforeNavigate} on:close={()=>drawer=false}/>{/if}
{#if pendingDecision}
  <div class="decision-overlay">
    <div class="decision-dialog" role="dialog" aria-modal="true" aria-label="Unsaved Markdown changes" tabindex="-1" bind:this={decisionFocus} on:keydown={decisionKeydown}>
      <h2>Unsaved Markdown changes</h2>
      <p>Save before you {pendingDecision.description}?</p>
      <div class="decision-actions">
        <button on:click={()=>decide('save')}>Save</button>
        <button on:click={()=>decide('keep')}>Keep editing</button>
        <button on:click={()=>decide('discard')}>Discard changes</button>
      </div>
    </div>
  </div>
{/if}

<style>
  .language-surface{display:flex;flex:1;min-height:0;flex-direction:column;background:#0f0f14;color:#e0e0e8}
  header{display:flex;align-items:center;gap:16px;min-height:60px;padding:8px 16px;border-bottom:1px solid #292936;font-size:18px;font-weight:600}
  .menu{width:36px;height:36px;border-radius:8px;background:#1e1e2e;font-size:16px}
  .tabs{display:flex;align-items:stretch;min-height:48px;border-bottom:1px solid #393946;background:#17171f;min-width:0}
  .plus{order:0;width:48px;flex:none;border-right:1px solid #34343f;font-size:24px;color:#ddd}
  .tab-scroll{order:1;display:flex;flex:1;min-width:0;overflow-x:auto}
  .tab-shell{display:flex;align-items:stretch;flex:none;max-width:240px;min-width:90px;border-right:1px solid #34343f;color:#a7a7b6}
  .tab-shell.active{color:#fff;background:#22222b;box-shadow:inset 0 -2px var(--accent)}
  .tab-title{min-width:0;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;padding:8px 4px 8px 15px;text-align:left;font-size:13px}
  .tab-close{display:grid;place-items:center;flex:none;width:30px;padding-right:6px;color:#8b8b9b;font-size:18px}
  .tab-close:hover,.tab-close:focus-visible{color:#fff}
  .tab-close .dirty-glyph{display:none;font-size:11px;color:#fff}
  .tab-close.is-dirty .close-glyph{display:none}
  .tab-close.is-dirty .dirty-glyph{display:block}
  .tab-close.is-dirty:hover .close-glyph,.tab-close.is-dirty:focus-visible .close-glyph{display:block}
  .tab-close.is-dirty:hover .dirty-glyph,.tab-close.is-dirty:focus-visible .dirty-glyph{display:none}
  .tab.editing{display:flex;align-items:center;flex:none;min-width:90px;padding:8px 15px;border-right:1px solid #34343f;color:#fff;background:#22222b;font-size:13px}.tab input{width:125px;min-width:40px;background:transparent;outline:none;color:#fff}.tab span{color:#a7a7b6}
  .tabs select{order:2;max-width:180px;padding:0 12px;background:#1b1b25;border-left:1px solid #393946;font-size:12px}
  .editor{width:100%;min-height:0;flex:1;resize:none;border:0;outline:none;background:#101016;color:#eee;padding:24px;font:15px/1.65 ui-monospace,SFMono-Regular,Consolas,monospace;tab-size:2}
  .save-status{display:flex;align-items:center;gap:8px;min-height:32px;padding:5px 16px;border-top:1px solid #292936;color:#9393a5;font-size:12px}.save-status .failed{color:#fca5a5}.save-status button,.notice button,.empty button{text-decoration:underline;margin-left:8px;color:#ddd}
  .notice{padding:12px 16px;color:#fca5a5;font-size:13px}.empty{flex:1;display:grid;place-content:center;text-align:center;color:#a7a7b6;gap:12px}
  .decision-overlay{position:fixed;inset:0;z-index:150;display:grid;place-items:center;background:rgba(0,0,0,.72);padding:16px}
  .decision-dialog{width:min(430px,100%);border:1px solid #383848;border-radius:14px;background:#17171f;padding:24px;box-shadow:0 24px 70px rgba(0,0,0,.5)}
  .decision-dialog h2{font-size:18px;font-weight:600;color:#fff}.decision-dialog p{margin-top:12px;color:#b8b8c7;font-size:14px}
  .decision-actions{display:flex;flex-wrap:wrap;justify-content:flex-end;gap:8px;margin-top:22px}.decision-actions button{border:1px solid #444455;border-radius:8px;padding:7px 11px;font-size:13px}.decision-actions button:first-child{background:var(--accent-strong);border-color:var(--accent-strong);color:#fff}.decision-actions button:hover{border-color:var(--accent);color:#fff}
  button:focus-visible,select:focus-visible,.editor:focus-visible{outline:2px solid var(--accent);outline-offset:-2px}
  @media(max-width:600px){.tabs select{max-width:110px}.editor{padding:16px}}
</style>
