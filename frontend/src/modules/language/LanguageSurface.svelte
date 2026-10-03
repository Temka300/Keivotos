<script lang="ts">
  import {onMount,onDestroy,tick} from 'svelte';
  import AppDrawer from '../../components/AppDrawer.svelte';
  import {settingsInitialSection,settingsOpen} from '../../lib/suiteStores';
  import {languageApi,type LanguageDocument,type LanguageFile,type LanguageFolder} from './api';

  type OpenNote = LanguageDocument & {sessionId:string; dirty:boolean; saving:boolean; error:string; timer?:ReturnType<typeof setTimeout>};
  let drawer=false, loading=true, error='';
  let folders:LanguageFolder[]=[], sourceId='', files:LanguageFile[]=[], tabs:OpenNote[]=[], activeName='';
  let editingName='', nameDraft='', renameBusy=false, nameInput:HTMLInputElement;
  let saveQueue:Promise<boolean>=Promise.resolve(true);
  $: active=tabs.find(tab=>tab.name===activeName);

  function draftKey(folder:string,name:string){return `keivotos:language-draft:${folder}:${name}`;}
  function remember(tab:OpenNote){
    const key=draftKey(sourceId,tab.name);
    const value=JSON.stringify({content:tab.content,revision:tab.revision,sessionId:tab.sessionId});
    let persistent=false;
    try{localStorage.setItem(key,value);persistent=true;}catch{/* Keep a session copy if persistent storage is unavailable. */}
    try{sessionStorage.setItem(key,value);}catch{/* Persistent storage may still be available. */}
    if(!persistent)tab.error ||= 'Could not keep this draft across app restarts. Save or copy the text before leaving.';
  }
  function clearDraft(tab:OpenNote){
    const key=draftKey(sourceId,tab.name);
    try{localStorage.removeItem(key);}catch{/* Storage may be disabled. */}
    try{sessionStorage.removeItem(key);}catch{/* Storage may be disabled. */}
  }
  function restoreDraft(tab:OpenNote){
    try{
      const key=draftKey(sourceId,tab.name);
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
      tab.dirty=true;
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
    if(!sourceId){files=[];return;}
    files=(await languageApi.files(sourceId)).files;
  }
  function flushTab(tab:OpenNote):Promise<boolean>{
    if(tab.timer)clearTimeout(tab.timer);
    saveQueue=saveQueue.then(async()=>{
      while(tab.dirty){
        const content=tab.content;
        tab.saving=true;tab.error='';tabs=[...tabs];
        try{
          const saved=await languageApi.save(sourceId,tab.name,content,tab.revision,tab.sessionId);
          tab.revision=saved.revision;
          tab.dirty=tab.content!==content;
          if(tab.dirty)remember(tab);else clearDraft(tab);
          tab.saving=false;tabs=[...tabs];
        }catch(caught){
          tab.error=caught instanceof Error?caught.message:'Save failed. Your text remains in the editor.';
          tab.saving=false;tabs=[...tabs];remember(tab);
          return false;
        }
      }
      return true;
    });
    return saveQueue;
  }
  function scheduleSave(tab:OpenNote){
    if(tab.timer)clearTimeout(tab.timer);
    tab.timer=setTimeout(()=>void flushTab(tab),500);
  }
  async function flushActive(){return active?flushTab(active):true;}
  async function openDocument(name:string){
    if(name===activeName)return true;
    if(!await flushActive())return false;
    error='';
    let tab=tabs.find(item=>item.name===name);
    if(!tab){
      try{
        const result=await languageApi.read(sourceId,name);
        tab={...result,sessionId:crypto.randomUUID().replaceAll('-',''),dirty:false,saving:false,error:''};
        restoreDraft(tab);
        tabs=[...tabs,tab];
      }catch(caught){error=caught instanceof Error?caught.message:'Could not open this note.';return false;}
    }
    activeName=name;
    return true;
  }
  async function selectFolder(next:string){
    if(next===sourceId)return;
    if(!await flushActive())return;
    sourceId=next;tabs=[];activeName='';editingName='';
    try{await loadFiles();error='';}
    catch(caught){error=caught instanceof Error?caught.message:'Could not list Language notes.';}
  }
  async function create(){
    if(!sourceId||!await flushActive())return;
    error='';
    try{
      const result=await languageApi.create(sourceId);
      files=[...files,{name:result.name,size:0}].sort((a,b)=>a.name.localeCompare(b.name));
      tabs=[...tabs,{...result,sessionId:crypto.randomUUID().replaceAll('-',''),dirty:false,saving:false,error:''}];
      activeName=result.name;
      await startRename(result.name);
    }catch(caught){error=caught instanceof Error?caught.message:'Could not create a note.';}
  }
  async function startRename(name:string){
    if(!await openDocument(name))return;
    editingName=name;nameDraft=name.slice(0,-3);
    await tick();nameInput?.focus();nameInput?.select();
  }
  async function commitRename(){
    if(!editingName||renameBusy)return;
    const oldName=editingName, nextName=`${nameDraft.trim()}.md`;
    if(nextName===oldName){editingName='';return;}
    if(!await flushActive())return;
    const tab=tabs.find(item=>item.name===oldName);
    if(!tab)return;
    renameBusy=true;error='';
    try{
      const result=await languageApi.rename(sourceId,oldName,nextName,tab.revision);
      tab.name=result.name;
      files=files.map(file=>file.name===oldName?{...file,name:result.name}:file).sort((a,b)=>a.name.localeCompare(b.name));
      activeName=result.name;editingName='';tabs=[...tabs];
    }catch(caught){error=caught instanceof Error?caught.message:'Could not rename this note.';}
    finally{renameBusy=false;}
  }
  function input(event:Event){
    if(!active)return;
    active.content=(event.currentTarget as HTMLTextAreaElement).value;
    active.dirty=true;active.error='';remember(active);scheduleSave(active);tabs=[...tabs];
  }
  function beforeUnload(event:BeforeUnloadEvent){
    if(!tabs.some(tab=>tab.dirty||tab.saving))return;
    event.preventDefault();event.returnValue='';
  }
  function foldersSettings(){settingsInitialSection.set('roots');settingsOpen.set(true);}
  onMount(()=>{window.addEventListener('beforeunload',beforeUnload);void loadFolders();});
  onDestroy(()=>{
    window.removeEventListener('beforeunload',beforeUnload);
    for(const tab of tabs){if(tab.timer)clearTimeout(tab.timer);if(tab.dirty){remember(tab);void flushTab(tab);}}
  });
</script>

<div class="language-surface">
  <header><button class="menu" aria-label="Open Keivotos menu" on:click={()=>drawer=true}>☰</button><span>Language</span></header>
  {#if error}<p class="notice" role="alert">{error} <button on:click={loadFolders}>Retry</button></p>{/if}
  {#if loading}<p class="notice" role="status">Loading Language folders…</p>{/if}
  {#if !loading&&!folders.length}<div class="empty"><p>Assign a folder the Language role to write Markdown notes.</p><button on:click={foldersSettings}>Add Language folders in Settings</button></div>{/if}
  {#if sourceId}
    <div class="tabs" role="tablist" aria-label="Markdown files">
      <button class="plus" aria-label="New Markdown file" title="New Markdown file" on:click={create}>+</button>
      <div class="tab-scroll">
        {#each files as file (file.name)}
          {#if editingName===file.name}
            <div class="tab editing"><input aria-label="Rename Markdown file" bind:this={nameInput} bind:value={nameDraft} disabled={renameBusy} on:keydown={event=>{if(event.key==='Enter'){event.preventDefault();void commitRename();}else if(event.key==='Escape'){event.preventDefault();editingName='';}}} on:blur={commitRename}/><span>.md</span></div>
          {:else}
            <button class="tab" class:active={activeName===file.name} role="tab" aria-selected={activeName===file.name} on:click={()=>openDocument(file.name)} on:dblclick={()=>startRename(file.name)} title={file.name}>{file.name}</button>
          {/if}
        {/each}
      </div>
      {#if folders.length>1}<select aria-label="Language folder" value={sourceId} on:change={event=>selectFolder(event.currentTarget.value)}>{#each folders as folder}<option value={folder.source_id}>{folder.name}</option>{/each}</select>{/if}
    </div>
    {#if active}
      <textarea class="editor" aria-label={`Edit ${active.name}`} spellcheck="false" value={active.content} on:input={input}></textarea>
      <div class="save-status" role="status">
        {#if active.error}<span class="failed">Save failed: {active.error}</span><button on:click={()=>flushTab(active)}>Retry save</button>
        {:else if active.saving}Saving…{:else if active.dirty}Unsaved changes…{:else}Saved{/if}
      </div>
    {:else}<div class="empty"><p>{files.length?'Choose a Markdown tab or create a new file.':'Create a Markdown file with +.'}</p></div>{/if}
  {/if}
</div>
{#if drawer}<AppDrawer on:close={()=>drawer=false}/>{/if}

<style>
  .language-surface{display:flex;flex:1;min-height:0;flex-direction:column;background:#0f0f14;color:#e0e0e8}
  header{display:flex;align-items:center;gap:16px;min-height:60px;padding:8px 16px;border-bottom:1px solid #292936;font-size:18px;font-weight:600}
  .menu{width:36px;height:36px;border-radius:8px;background:#1e1e2e;font-size:16px}
  .tabs{display:flex;align-items:stretch;min-height:48px;border-bottom:1px solid #393946;background:#17171f;min-width:0}
  .plus{order:0;width:48px;flex:none;border-right:1px solid #34343f;font-size:24px;color:#ddd}
  .tab-scroll{order:1;display:flex;flex:1;min-width:0;overflow-x:auto}
  .tab{display:flex;align-items:center;flex:none;max-width:240px;min-width:90px;padding:8px 15px;border-right:1px solid #34343f;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:13px;color:#a7a7b6}
  button.tab.active{color:#fff;background:#22222b;box-shadow:inset 0 -2px var(--accent)}
  .tab.editing{gap:0;color:#fff;background:#22222b}.tab input{width:125px;min-width:40px;background:transparent;outline:none;color:#fff}.tab span{color:#a7a7b6}
  .tabs select{order:2;max-width:180px;padding:0 12px;background:#1b1b25;border-left:1px solid #393946;font-size:12px}
  .editor{width:100%;min-height:0;flex:1;resize:none;border:0;outline:none;background:#101016;color:#eee;padding:24px;font:15px/1.65 ui-monospace,SFMono-Regular,Consolas,monospace;tab-size:2}
  .save-status{min-height:32px;padding:5px 16px;border-top:1px solid #292936;color:#9393a5;font-size:12px}.save-status .failed{color:#fca5a5}.save-status button,.notice button,.empty button{text-decoration:underline;margin-left:8px;color:#ddd}
  .notice{padding:12px 16px;color:#fca5a5;font-size:13px}.empty{flex:1;display:grid;place-content:center;text-align:center;color:#a7a7b6;gap:12px}
  button:focus-visible,select:focus-visible,.editor:focus-visible{outline:2px solid var(--accent);outline-offset:-2px}
  @media(max-width:600px){.tabs select{max-width:110px}.editor{padding:16px}}
</style>
