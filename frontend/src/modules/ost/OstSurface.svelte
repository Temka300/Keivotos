<script lang="ts">
  import {onMount,onDestroy} from 'svelte';
  import AppDrawer from '../../components/AppDrawer.svelte';
  import {settingsInitialSection,settingsOpen} from '../../lib/suiteStores';
  import {ostApi,type OstSource} from './api';
  let drawer=false,loading=true,error='';
  let sources:OstSource[]=[];
  let request:AbortController|null=null;
  let alive=true;
  async function load(){
    request?.abort();const current=new AbortController();request=current;
    loading=true;error='';
    try{
      const result=await ostApi.folders(current.signal);
      if(alive&&!current.signal.aborted)sources=result;
    }catch(caught){if(alive&&!current.signal.aborted)error=caught instanceof Error?caught.message:'Could not load OST folders.';}
    finally{if(alive&&request===current)loading=false;}
  }
  function folders(){settingsInitialSection.set('roots');settingsOpen.set(true);}
  onMount(()=>{
    let previous=false;
    const stop=settingsOpen.subscribe(open=>{if(previous&&!open)void load();previous=open;});
    void load();return stop;
  });
  onDestroy(()=>{alive=false;request?.abort();});
</script>

<svelte:window on:focus={()=>{if(!$settingsOpen)void load();}} />
<div class="ost-surface">
  <header><button class="menu" aria-label="Open Keivotos menu" title="Open Keivotos menu" on:click={()=>drawer=true}>☰</button><h1>OST</h1></header>
  <main aria-busy={loading}>
    {#if error}<p role="alert">{error} <button on:click={()=>load()}>Retry</button></p>{/if}
    {#if loading}<p role="status">Loading OST folders…</p>
    {:else if !error}
      {#if sources.length}
        <h2>Soundtrack folders</h2>
        <ul aria-label="OST folders">{#each sources as source (source.source_id)}<li><span>{source.name}</span>{#if !source.available}<small>Folder unavailable</small>{/if}</li>{/each}</ul>
      {/if}
      <button class="folders" on:click={folders}>{sources.length?'Manage OST folders':'Add OST folders in Settings'}</button>
    {/if}
  </main>
</div>
{#if drawer}<AppDrawer on:close={()=>drawer=false} />{/if}

<style>
  .ost-surface{display:flex;flex:1;min-height:0;min-width:0;flex-direction:column;background:#0f0f14;color:#e0e0e8}
  header{display:flex;align-items:center;gap:16px;min-height:60px;padding:8px 16px;border-bottom:1px solid #292936}
  .menu{width:36px;height:36px;flex:none;border-radius:8px;background:#1e1e2e;font-size:16px}
  h1{font-size:18px;font-weight:600}h2{font-size:15px;font-weight:600}
  main{flex:1;min-height:0;overflow:auto;padding:24px}ul{max-width:720px;margin:16px 0}
  li{display:flex;flex-wrap:wrap;gap:12px;padding:14px 0;border-bottom:1px solid #292936}
  li span{overflow-wrap:anywhere}small{color:#b6a2a2}.folders{padding:8px 14px;border:1px solid #393946;border-radius:10px;font-size:13px}
  .folders:hover{background:#242431}button:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
  p{font-size:13px;color:#b6b6c6}p button{text-decoration:underline}
</style>
