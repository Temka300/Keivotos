<script lang="ts">
  import {onMount,onDestroy,tick} from 'svelte';
  import AppDrawer from '../../components/AppDrawer.svelte';
  import ModuleLocationMenu from '../../components/ModuleLocationMenu.svelte';
  import {settingsInitialSection,settingsOpen} from '../../lib/suiteStores';
  import {ostApi,type OstSource,type OstItem} from './api';
  type Position={count:number;scroll:number;focus:string;selected:string};
  let drawer=false,loading=false,sourceLoading=true,error='',sourceError='',notice='';
  let sources:OstSource[]=[];
  let source:OstSource|null=null,parent='',items:OstItem[]=[],total=0,selected='';
  let main:HTMLElement,heading:HTMLHeadingElement;
  let request:AbortController|null=null,sourceRequest:AbortController|null=null;
  let alive=true;
  let navigationSerial=0;
  let retryMore=false;
  let settingsAnchor:HTMLElement|null=null;
  let missingArt=new Set<string>();
  const positions=new Map<string,Position>();
  let locationMenu:{x:number;y:number;label:string;sourceId:string;relativePath:string;anchor:HTMLElement;unavailableReason:string}|null=null;
  let locationMenuSerial=0;
  $: parts=parent?parent.split('/'):[];
  $: backLabel=parent?(parts.length>1?parts[parts.length-2]:source?.name):'Soundtrack folders';
  function key(owner:OstSource|null,path:string){return owner?`${owner.source_id}:${path}`:'roots';}
  function remember(){
    const active=document.activeElement as HTMLElement|null;
    positions.set(key(source,parent),{count:items.length,scroll:main?.scrollTop??0,
      focus:active?.dataset.ostFocus??'',selected});
    if(positions.size>64)positions.delete(positions.keys().next().value!);
  }
  async function restore(position?:Position,signal?:AbortSignal,serial=navigationSerial,focusHeading=true){
    await tick();
    if(!alive||signal?.aborted||serial!==navigationSerial)return;
    const anchor=position?.focus?[...main.querySelectorAll<HTMLElement>('[data-ost-focus]')]
      .find(node=>node.dataset.ostFocus===position.focus):null;
    if(anchor)anchor.focus({preventScroll:true});
    else if(focusHeading)heading?.focus({preventScroll:true});
    main.scrollTop=position?.scroll??0;
  }
  async function load(more=false,wanted=0,position?:Position,focusHeading=true){
    if(!source)return;
    request?.abort();const current=new AbortController();request=current;
    const owner=source,folder=parent,scroll=main?.scrollTop??0;
    loading=true;error='';retryMore=more;
    try{
      let next:OstItem[]=[],result;
      do{
        result=await ostApi.library(owner.source_id,folder,more?items.length:next.length,current.signal);
        if(!alive||current.signal.aborted)return;
        next=[...next,...result.items];
      }while(!more&&next.length<wanted&&next.length<result.total&&result.items.length>0);
      items=more?[...items,...next]:next;total=result.total;
      if(position)selected=position.selected;
      await tick();
      if(!alive||current.signal.aborted)return;
      if(more)main.scrollTop=scroll;
      else if(position)await restore(position,current.signal,navigationSerial,focusHeading);
    }catch(caught){if(alive&&!current.signal.aborted)error=caught instanceof Error?caught.message:'Could not load this folder.';}
    finally{if(alive&&request===current)loading=false;}
  }
  async function navigate(owner:OstSource|null,path=''){
    const serial=++navigationSerial;
    remember();request?.abort();locationMenu=null;
    source=owner;parent=path;items=[];total=0;selected='';error='';notice='';missingArt=new Set();
    const position=positions.get(key(owner,path))??{count:0,scroll:0,focus:'',selected:''};
    await restore(undefined,undefined,serial);
    if(!alive||serial!==navigationSerial)return;
    if(owner)await load(false,position.count,position);
    else{loading=false;await restore(position,undefined,serial);}
  }
  function back(){void navigate(source&&parent?source:null,parent?parts.slice(0,-1).join('/'):'');}
  async function refreshSources(){
    sourceRequest?.abort();const current=new AbortController();sourceRequest=current;
    sourceLoading=true;sourceError='';
    try{
      const result=await ostApi.folders(current.signal);
      if(!alive||current.signal.aborted)return;
      sources=result;
      if(source){
        const fresh=result.find(row=>row.source_id===source?.source_id);
        if(fresh){
          source=fresh;const active=document.activeElement as HTMLElement|null;
          void load(false,items.length,{count:items.length,scroll:main?.scrollTop??0,focus:active?.dataset.ostFocus??'',selected},false);
        }
        else{await navigate(null);notice='This folder is no longer assigned to OST.';}
      }
    }catch(caught){if(alive&&!current.signal.aborted)sourceError=caught instanceof Error?caught.message:'Could not load OST folders.';}
    finally{if(alive&&sourceRequest===current)sourceLoading=false;}
  }
  function folders(event:MouseEvent){
    settingsAnchor=event.currentTarget as HTMLElement;
    settingsInitialSection.set('roots');settingsOpen.set(true);
  }
  async function settingsClosed(){
    await tick();
    if(!alive||$settingsOpen)return;
    const anchor=settingsAnchor;settingsAnchor=null;
    if(anchor?.isConnected)anchor.focus({preventScroll:true});
    void refreshSources();
  }
  function openLocation(event:MouseEvent|KeyboardEvent,label:string,sourceId:string,path:string,available:boolean){
    event.preventDefault();event.stopPropagation();
    const anchor=event.currentTarget as HTMLElement,rect=anchor.getBoundingClientRect();
    locationMenu={x:event instanceof MouseEvent?event.clientX:rect.left+8,y:event instanceof MouseEvent?event.clientY:rect.bottom,
      label,sourceId,relativePath:path,anchor,unavailableReason:available?'':'This local item is unavailable.'};
    locationMenuSerial++;
  }
  function locationKey(event:KeyboardEvent,label:string,sourceId:string,path:string,available:boolean){
    if(event.key==='ContextMenu'||event.shiftKey&&event.key==='F10')openLocation(event,label,sourceId,path,available);
  }
  function artKey(sourceId:string,path:string,version:string){return `${sourceId}:${path}:${version}`;}
  function artFailed(id:string){missingArt=new Set([...missingArt,id]);}
  function choose(item:OstItem){
    if(!item.available||!source)return;
    if(item.is_dir)void navigate(source,item.path);
    else selected=item.path;
  }
  onMount(()=>{
    let previous=false;
    const stop=settingsOpen.subscribe(open=>{if(previous&&!open)void settingsClosed();previous=open;});
    void refreshSources();return stop;
  });
  onDestroy(()=>{alive=false;request?.abort();sourceRequest?.abort();});
</script>

<svelte:window on:focus={()=>{if(!$settingsOpen)void refreshSources();}} />
<div class="ost-surface">
  <header>
    <button class="menu" aria-label="Open Keivotos menu" title="Open Keivotos menu" on:click={()=>drawer=true}>☰</button><h1>OST</h1>
    {#if sources.length}<button class="folders" on:click={folders}>Manage OST folders</button>{/if}
  </header>
  {#if source}
      <div class="location">
        <button class="back" aria-label={`Back to ${backLabel}`} title={`Back to ${backLabel}`} on:click={back}>
          <svg width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="m15 18-6-6 6-6"/></svg>
        </button>
        <nav aria-label="OST location">
          <button on:click={()=>navigate(null)}>Soundtrack folders</button><span aria-hidden="true">/</span>
          <button on:click={()=>navigate(source)} title={source.name}>{source.name}</button>
          {#each parts as part,i}<span aria-hidden="true">/</span><button on:click={()=>navigate(source,parts.slice(0,i+1).join('/'))} title={part}>{part}</button>{/each}
        </nav>
      </div>
  {/if}
  <main bind:this={main} aria-busy={loading||sourceLoading}>
    <h2 bind:this={heading} tabindex="-1">{source?(parts.at(-1)||source.name):'Soundtrack folders'}</h2>
    {#if notice}<p role="status">{notice}</p>{/if}
    {#if sourceError}<p role="alert">{sourceError} <button on:click={refreshSources}>Retry folders</button></p>{/if}
    {#if error}<p role="alert">{error} <button on:click={()=>load(retryMore,items.length)}>Retry</button></p>{/if}
    {#if !source}
      {#if sourceLoading&&!sources.length}<p role="status">Loading OST folders…</p>{/if}
      {#if sources.length}
        <ul aria-label="OST folders" class="entries">
          {#each sources as root (root.source_id)}
            {@const id=artKey(root.source_id,'',root.cover_version)}
            <li><button class="entry" data-ost-source={root.source_id} data-ost-entry-path="" data-ost-focus={root.source_id}
              aria-label={`Open OST folder ${root.name}`} aria-disabled={!root.available} title={`${root.name}\n${root.path}`}
              on:click={()=>{if(root.available)void navigate(root);}}
              on:contextmenu={event=>openLocation(event,root.name,root.source_id,'',root.available)}
              on:keydown={event=>locationKey(event,root.name,root.source_id,'',root.available)}>
              <span class="art"><span aria-hidden="true">♫</span>{#if root.available&&!missingArt.has(id)}<img alt="" loading="lazy" decoding="async" width="52" height="52" src={ostApi.coverUrl(root.source_id,'',root.cover_version)} on:error={()=>artFailed(id)}/>{/if}</span>
              <span class="details"><span class="name">{root.name}</span><small title={root.path}>{root.available?root.path:'Folder unavailable'}</small></span>
              <span class="kind" aria-hidden="true">›</span>
            </button></li>
          {/each}
        </ul>
      {:else if !sourceLoading&&!sourceError}<button class="folders add" on:click={folders}>Add OST folders in Settings</button>{/if}
    {:else}
      {#if loading&&!items.length}<p role="status">Loading this folder…</p>{/if}
      <ul aria-label="OST folder contents" class="entries">
        {#each items as item (`${item.path}:${item.cover_version}`)}
          {@const id=artKey(item.source_id,item.path,item.cover_version)}
          <li><button class="entry" class:selected={selected===item.path} data-ost-source={item.source_id} data-ost-entry-path={item.path} data-ost-focus={item.path}
            aria-label={`${item.is_dir?'Open folder':'Select track'} ${item.name}`} aria-disabled={!item.available}
            aria-pressed={item.is_dir?undefined:selected===item.path} title={item.name} on:click={()=>choose(item)}
            on:contextmenu={event=>openLocation(event,item.name,item.source_id,item.path,item.available)}
            on:keydown={event=>locationKey(event,item.name,item.source_id,item.path,item.available)}>
            <span class="art"><span aria-hidden="true">♫</span>{#if item.available&&!missingArt.has(id)}<img alt="" loading="lazy" decoding="async" width="52" height="52" src={ostApi.coverUrl(item.source_id,item.path,item.cover_version)} on:error={()=>artFailed(id)}/>{/if}</span>
            <span class="details"><span class="name">{item.name}</span><small>{!item.available?'File unavailable':item.is_dir?'Folder':item.ext.toUpperCase()}</small></span>
            {#if item.is_dir}<span class="kind" aria-hidden="true">›</span>{/if}
          </button></li>
        {/each}
      </ul>
      {#if !loading&&!error&&!items.length}<p role="status">No folders or supported audio files here.</p>{/if}
      {#if items.length<total}<button class="more" disabled={loading} on:click={()=>load(true)}>{loading?'Loading…':'Load more'}</button>{/if}
      <p class="count" aria-live="polite">{items.length} / {total} items</p>
    {/if}
  </main>
</div>
{#if drawer}<AppDrawer on:close={()=>drawer=false} />{/if}
{#if locationMenu}{#key locationMenuSerial}<ModuleLocationMenu {...locationMenu} on:close={()=>locationMenu=null}/>{/key}{/if}

<style>
  .ost-surface{display:flex;flex:1;min-height:0;min-width:0;flex-direction:column;background:#0f0f14;color:#e0e0e8;font-family:system-ui,sans-serif}
  header{display:flex;align-items:center;gap:16px;min-height:60px;padding:8px 16px;border-bottom:1px solid #292936}
  .menu{width:36px;height:36px;flex:none;border-radius:8px;background:#1e1e2e;font-size:16px}
  h1{font-size:18px;font-weight:600}header .folders{margin-left:auto;flex-shrink:0}
  h2{font-size:18px;font-weight:600;overflow-wrap:anywhere;margin:10px 0 20px}h2:focus{outline:none}
  main{flex:1;min-height:0;overflow:auto;padding:20px 24px 28px;scrollbar-gutter:stable}
  .location{display:flex;flex:none;align-items:center;gap:12px;padding:12px 24px 0;min-width:0}
  .back{display:grid;place-items:center;flex-shrink:0;width:40px;height:40px;border:0;background:transparent;border-radius:999px;color:#eee;transition:width .18s ease,background-color .18s ease}
  .back:hover,.back:focus-visible{width:56px;background:#33333b}
  nav{display:flex;flex-wrap:wrap;align-items:center;gap:6px;min-width:0;font-size:12px;color:#858599}
  nav button{max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#b6b6c6}nav button:hover{color:#fff}
  .entries{margin:0;list-style:none;padding:0;max-width:1000px}.entries li{border-bottom:1px solid #242431}
  .entry{display:flex;align-items:center;gap:14px;width:100%;min-width:0;min-height:76px;padding:12px 8px;text-align:left;border-radius:10px;transition:background-color .15s ease}
  .entry:hover,.entry:focus-visible{background:#1c1c29}.entry.selected{background:#202033}.entry[aria-disabled='true']{opacity:.55;cursor:not-allowed}
  .art{position:relative;display:grid;place-items:center;flex:none;width:52px;height:52px;overflow:hidden;border-radius:10px;background:#20202d;color:#858599;font-size:25px}
  .art img{position:absolute;width:100%;height:100%;object-fit:cover}.details{flex:1;min-width:0}
  .name{display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;line-clamp:2;overflow:hidden;overflow-wrap:anywhere;font-size:14px;line-height:1.45}
  small{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;margin-top:4px;color:#858599;font-size:11px}
  .kind{color:#858599;font-size:24px}.folders,.more{padding:8px 14px;border:1px solid #393946;border-radius:10px;font-size:13px}
  .folders:hover,.more:hover{background:#242431}.add{margin-top:8px}.more{margin-top:16px}
  button:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
  p{font-size:13px;color:#b6b6c6}p button{text-decoration:underline}.count{font-size:11px;margin-top:16px;color:#858599}
  @media(max-width:480px){main{padding:16px 12px 24px}.location{padding:12px 12px 0}header{gap:10px;padding:8px 12px}.folders{font-size:12px;padding:8px 10px}.entry{gap:10px}}
  :global(html[data-motion='reduced']) .back,:global(html[data-motion='reduced']) .entry{transition:none}
  @media(prefers-reduced-motion:reduce){.back,.entry{transition:none}}
</style>
