<script lang="ts">
  import {onMount,onDestroy,tick} from 'svelte';
  import AppDrawer from '../../components/AppDrawer.svelte';
  import ModuleLocationMenu from '../../components/ModuleLocationMenu.svelte';
  import {settingsOpen} from '../../lib/suiteStores';
  import {ostApi,type OstSource,type OstItem} from './api';
  import AudioPlayer from './AudioPlayer.svelte';
  type Position={count:number;scroll:number;focus:string;selected:string};
  let drawer=false,loading=false,sourceLoading=true,error='',sourceError='',notice='';
  let sources:OstSource[]=[];
  let source:OstSource|null=null,parent='',items:OstItem[]=[],total=0,selected='';
  let main:HTMLElement;
  let request:AbortController|null=null,sourceRequest:AbortController|null=null;
  let alive=true;
  let navigationSerial=0;
  let retryMore=false;
  let missingArt=new Set<string>();
  const positions=new Map<string,Position>();
  let locationMenu:{x:number;y:number;label:string;sourceId:string;relativePath:string;anchor:HTMLElement;unavailableReason:string}|null=null;
  let locationMenuSerial=0;
  type Queue={source:OstSource;parent:string;tracks:OstItem[];offset:number;total:number};
  let queue:Queue|null=null,playingTrack:OstItem|null=null;
  let playerExpanded=false,playbackNavigating=false,playbackNotice='';
  let playbackRequest:AbortController|null=null;
  let playerReturn:Position|undefined,playerAnchor:HTMLElement|null=null;
  $: playingIndex=queue&&playingTrack?queue.tracks.findIndex(item=>item.path===playingTrack?.path):-1;
  $: hasPrevious=playingIndex>0;
  $: hasNext=!!queue&&(playingIndex<queue.tracks.length-1||queue.offset<queue.total);
  $: folderLabel=queue?`${queue.source.name}${queue.parent?' / '+queue.parent:''}`:'';
  $: parts=parent?parent.split('/'):[];
  $: backLabel=parent?(parts.length>1?parts[parts.length-2]:source?.name):'OST';
  function key(owner:OstSource|null,path:string){return owner?`${owner.source_id}:${path}`:'roots';}
  function remember(){
    const active=document.activeElement as HTMLElement|null;
    positions.set(key(source,parent),{count:items.length,scroll:main?.scrollTop??0,
      focus:active?.dataset.ostFocus??'',selected});
    if(positions.size>64)positions.delete(positions.keys().next().value!);
  }
  async function restore(position?:Position,signal?:AbortSignal,serial=navigationSerial,focusLibrary=true){
    await tick();
    if(!alive||signal?.aborted||serial!==navigationSerial)return;
    const anchor=position?.focus?[...main.querySelectorAll<HTMLElement>('[data-ost-focus]')]
      .find(node=>node.dataset.ostFocus===position.focus):null;
    if(anchor)anchor.focus({preventScroll:true});
    else if(focusLibrary)main?.focus({preventScroll:true});
    main.scrollTop=position?.scroll??0;
  }
  async function load(more=false,wanted=0,position?:Position,focusLibrary=true){
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
      else if(position)await restore(position,current.signal,navigationSerial,focusLibrary);
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
      if(queue&&!result.some(row=>row.source_id===queue?.source.source_id&&row.available)){
        playbackRequest?.abort();queue=null;playingTrack=null;playerExpanded=false;playbackNavigating=false;
      }
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
  async function settingsClosed(){
    await tick();
    if(!alive||$settingsOpen)return;
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
  function expandPlayer(event?:MouseEvent){
    if(playerExpanded)return;
    remember();playerReturn=positions.get(key(source,parent));
    playerAnchor=(event?.currentTarget as HTMLElement|null)??document.activeElement as HTMLElement|null;
    playerExpanded=true;
  }
  async function browsePlayer(){
    playerExpanded=false;await tick();
    if(!alive)return;
    await restore(playerReturn);
    if(playerAnchor?.isConnected)playerAnchor.focus({preventScroll:true});
    playerAnchor=null;
  }
  async function extendQueue(target:Queue,signal:AbortSignal){
    while(target.offset<target.total){
      const result=await ostApi.library(target.source.source_id,target.parent,target.offset,signal);
      if(!alive||signal.aborted||queue!==target)return;
      if(!result.items.length){target.offset=result.total;target.total=result.total;break;}
      target.offset+=result.items.length;target.total=result.total;
      const additions=result.items.filter(item=>!item.is_dir&&item.available&&!target.tracks.some(old=>old.path===item.path));
      target.tracks=[...target.tracks,...additions];
      queue=target;
      if(additions.length)return;
    }
  }
  async function navigatePlayback(direction:-1|1,wrap:boolean){
    if(!queue||!playingTrack||playbackNavigating)return false;
    const target=queue,currentTrack=playingTrack;
    playbackRequest?.abort();const pending=new AbortController();playbackRequest=pending;
    playbackNavigating=true;playbackNotice='';
    try{
      let index=target.tracks.findIndex(item=>item.path===currentTrack.path);
      if(direction===1&&index===target.tracks.length-1&&target.offset<target.total)await extendQueue(target,pending.signal);
      if(direction===-1&&index===0&&wrap)while(target.offset<target.total){await extendQueue(target,pending.signal);if(pending.signal.aborted||queue!==target)return false;}
      if(!alive||pending.signal.aborted||queue!==target||playingTrack!==currentTrack)return false;
      index+=direction;
      if(index<0||index>=target.tracks.length){if(!wrap)return false;index=(index+target.tracks.length)%target.tracks.length;}
      const next=target.tracks[index];
      if(!next||next===currentTrack)return false;
      playingTrack=next;
      if(source?.source_id===target.source.source_id&&parent===target.parent)selected=next.path;
      return true;
    }catch(caught){
      if(alive&&!pending.signal.aborted&&queue===target)playbackNotice=caught instanceof Error?caught.message:'Could not load another song. Try Next again.';
      return false;
    }finally{if(playbackRequest===pending)playbackNavigating=false;}
  }
  function choose(item:OstItem,event:MouseEvent){
    if(!item.available||!source)return;
    if(item.is_dir)void navigate(source,item.path);
    else{
      playbackRequest?.abort();playbackNavigating=false;playbackNotice='';selected=item.path;
      queue={source,parent,tracks:items.filter(row=>!row.is_dir&&row.available),offset:items.length,total};
      playingTrack=item;expandPlayer(event);
    }
  }
  onMount(()=>{
    let previous=false;
    const stop=settingsOpen.subscribe(open=>{if(previous&&!open)void settingsClosed();previous=open;});
    void refreshSources();return stop;
  });
  onDestroy(()=>{alive=false;request?.abort();sourceRequest?.abort();playbackRequest?.abort();});
</script>

<svelte:window on:focus={()=>{if(!$settingsOpen)void refreshSources();}} />
<div class="ost-surface">
  <header>
    <button class="menu" aria-label="Open Keivotos menu" title="Open Keivotos menu" on:click={()=>drawer=true}>☰</button><h1>OST</h1>
  </header>
  {#if source}
      <div class="location" class:player-hidden={playerExpanded}>
        <button class="back" aria-label={`Back to ${backLabel}`} title={`Back to ${backLabel}`} on:click={back}>
          <svg width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="m15 18-6-6 6-6"/></svg>
        </button>
        <nav aria-label="OST location">
          <button on:click={()=>navigate(source)} title={source.name}>{source.name}</button>
          {#each parts as part,i}<span aria-hidden="true">/</span><button on:click={()=>navigate(source,parts.slice(0,i+1).join('/'))} title={part}>{part}</button>{/each}
        </nav>
      </div>
  {/if}
  <main bind:this={main} aria-label="OST library" tabindex="-1" aria-busy={loading||sourceLoading} class:player-hidden={playerExpanded}>
    {#if notice}<p role="status">{notice}</p>{/if}
    {#if sourceError}<p role="alert">{sourceError} <button on:click={refreshSources}>Retry folders</button></p>{/if}
    {#if error}<p role="alert">{error} <button on:click={()=>load(retryMore,items.length)}>Retry</button></p>{/if}
    {#if !source}
      {#if sourceLoading&&!sources.length}<p role="status">Loading OST folders…</p>{/if}
      {#if sources.length}
        <ul aria-label="OST folders" class="entries">
          {#each sources as root (root.source_id)}
            <li><button class="entry" data-ost-source={root.source_id} data-ost-entry-path="" data-ost-focus={root.source_id}
              aria-label={`Open OST folder ${root.name}`} aria-disabled={!root.available} title={`${root.name}\n${root.path}`}
              on:click={()=>{if(root.available)void navigate(root);}}
              on:contextmenu={event=>openLocation(event,root.name,root.source_id,'',root.available)}
              on:keydown={event=>locationKey(event,root.name,root.source_id,'',root.available)}>
              <span class="art"><span aria-hidden="true">📁</span></span>
              <span class="details"><span class="name">{root.name}</span>{#if !root.available}<small>Folder unavailable</small>{/if}</span>
              <span class="kind" aria-hidden="true">›</span>
            </button></li>
          {/each}
        </ul>
      {:else if !sourceLoading&&!sourceError}<p>Assign folders to the OST role in Settings → Files → Folders.</p>{/if}
    {:else}
      {#if loading&&!items.length}<p role="status">Loading this folder…</p>{/if}
      <ul aria-label="OST folder contents" class="entries">
        {#each items as item (`${item.path}:${item.cover_version}`)}
          {@const id=artKey(item.source_id,item.path,item.cover_version)}
          <li><button class="entry" class:selected={selected===item.path} data-ost-source={item.source_id} data-ost-entry-path={item.path} data-ost-focus={item.path}
            aria-label={`${item.is_dir?'Open folder':'Play track'} ${item.name}`} aria-disabled={!item.available}
            aria-pressed={item.is_dir?undefined:selected===item.path} title={item.name} on:click={event=>choose(item,event)}
            on:contextmenu={event=>openLocation(event,item.name,item.source_id,item.path,item.available)}
            on:keydown={event=>locationKey(event,item.name,item.source_id,item.path,item.available)}>
            <span class="art"><span aria-hidden="true">{item.is_dir?'📁':'♫'}</span>{#if !item.is_dir&&item.available&&!missingArt.has(id)}<img alt="" loading="lazy" decoding="async" width="52" height="52" src={ostApi.coverUrl(item.source_id,item.path,item.cover_version)} on:error={()=>artFailed(id)}/>{/if}</span>
            <span class="details"><span class="name">{item.name}</span>{#if !item.available||!item.is_dir}<small>{!item.available?'File unavailable':item.ext.toUpperCase()}</small>{/if}</span>
            {#if item.is_dir}<span class="kind" aria-hidden="true">›</span>{/if}
          </button></li>
        {/each}
      </ul>
      {#if !loading&&!error&&!items.length}<p role="status">No folders or supported audio files here.</p>{/if}
      {#if items.length<total}<button class="more" disabled={loading} on:click={()=>load(true)}>{loading?'Loading…':'Load more'}</button>{/if}
      <p class="count" aria-live="polite">{items.length} / {total} items</p>
    {/if}
  </main>
  {#if playingTrack}<AudioPlayer track={playingTrack} {folderLabel} expanded={playerExpanded}
    {hasPrevious} {hasNext} canWrap={!!queue?.tracks.length} navigating={playbackNavigating} navigationNotice={playbackNotice}
    onNavigate={navigatePlayback} onExpand={expandPlayer} onBrowse={browsePlayer}/>{/if}
</div>
{#if drawer}<AppDrawer on:close={()=>drawer=false} />{/if}
{#if locationMenu}{#key locationMenuSerial}<ModuleLocationMenu {...locationMenu} on:close={()=>locationMenu=null}/>{/key}{/if}

<style>
  .ost-surface{display:flex;flex:1;min-height:0;min-width:0;flex-direction:column;background:#0f0f14;color:#e0e0e8;font-family:system-ui,sans-serif}
  header{display:flex;align-items:center;gap:16px;min-height:60px;padding:8px 16px;border-bottom:1px solid #292936}
  .menu{width:36px;height:36px;flex:none;border-radius:8px;background:#1e1e2e;font-size:16px}
  h1{font-size:18px;font-weight:600}main:focus{outline:none}
  main{flex:1;min-height:0;overflow:auto;padding:20px 24px 28px;scrollbar-gutter:stable}
  main.player-hidden,.location.player-hidden{display:none}
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
  .kind{color:#858599;font-size:24px}.more{margin-top:16px;padding:8px 14px;border:1px solid #393946;border-radius:10px;font-size:13px}
  .more:hover{background:#242431}
  button:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
  p{font-size:13px;color:#b6b6c6}p button{text-decoration:underline}.count{font-size:11px;margin-top:16px;color:#858599}
  @media(max-width:480px){main{padding:16px 12px 24px}.location{padding:12px 12px 0}header{gap:10px;padding:8px 12px}.entry{gap:10px}}
  :global(html[data-motion='reduced']) .back,:global(html[data-motion='reduced']) .entry{transition:none}
  @media(prefers-reduced-motion:reduce){.back,.entry{transition:none}}
</style>
