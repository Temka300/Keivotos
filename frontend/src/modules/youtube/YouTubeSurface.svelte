<script lang="ts">
 import {onMount,onDestroy,tick} from 'svelte';
 import {slide} from 'svelte/transition';
 import MediaPlayer from '../../components/MediaPlayer.svelte';
 import AppDrawer from '../../components/AppDrawer.svelte';
 import {filesApi} from '../../lib/filesApi';
 import {youtubeApi,type Download,type EngineStatus} from './api';
 let drawer=false,query='',video='best',audio='best',optionsOpen=false;
 let status:EngineStatus|null=null,items:Download[]=[],total=0,error='',busy=false,loading=false;
 let request:AbortController|null=null,timer:ReturnType<typeof setTimeout>,debounce:ReturnType<typeof setTimeout>,alive=true;
 let selected:Download|null=null,returnFocus:HTMLElement|null=null,navigating=false,navigationNotice='';
 const isAudio=(item:Download)=>['mp3','m4a','aac','ogg','opus','wav','flac'].includes(item.path.split('.').pop()?.toLowerCase()||'');
 $: playable=items.filter(item=>item.status==='complete'&&!isAudio(item));
 $: selectedIndex=selected?playable.findIndex(item=>item.id===selected?.id):-1;
 $: playback=selected?{src:filesApi.fileUrl(selected.source_id,selected.path),ext:selected.path.split('.').pop()?.toLowerCase()||''}:null;
 function open(item:Download){if(!selected)returnFocus=document.activeElement as HTMLElement;selected=item;navigationNotice='';optionsOpen=false;}
 async function close(){selected=null;await tick();returnFocus?.focus();}
 async function adjacent(direction:-1|1){
  if(!selected||navigating)return;
  const current=selected,index=selectedIndex+direction;
  if(index<0)return;
  navigating=true;navigationNotice='';
  try{
   let choices=playable;
   while(direction===1&&index>=choices.length&&items.length<total){
    const count=items.length;await load(true);
    choices=items.filter(item=>item.status==='complete'&&!isAudio(item));
    if(items.length<=count){navigationNotice='Could not load the next video. Try again.';break;}
   }
   if(alive&&selected===current&&choices[index])open(choices[index]);
  }finally{navigating=false;}
 }
 let motion=200;
 function escape(event:KeyboardEvent){if(event.key==='Escape')optionsOpen=false;}
 function isVideoUrl(value:string){
  try{
   const url=new URL(value.trim());
   if(url.protocol!=='https:'||url.username||url.password||(url.port&&url.port!=='443'))return false;
   let id='';
   if(url.hostname==='youtu.be')id=url.pathname.replace(/^\/+|\/+$/g,'');
   else if(['youtube.com','www.youtube.com','m.youtube.com','music.youtube.com'].includes(url.hostname)){
    if(url.pathname==='/watch')id=url.searchParams.get('v')||'';
    else if(/^\/(shorts|live|embed)\//.test(url.pathname))id=url.pathname.split('/')[2]||'';
   }
   return /^[A-Za-z0-9_-]{11}$/.test(id);
  }catch{return false;}
 }
 $: urlMode=isVideoUrl(query);
 $: searchQuery=urlMode?'':query;
 const active=(item:Download)=>['queued','downloading','merging'].includes(item.status);
 async function engine(){try{status=await youtubeApi.status();}catch(e){error=String(e);}}
 async function load(more=false,refresh=false){
   request?.abort();const current=new AbortController();request=current;loading=true;
   try{const result=await youtubeApi.library(searchQuery,more?items.length:0,current.signal);if(!alive||current.signal.aborted)return;items=more?[...items,...result.items]:refresh?[...result.items,...items.slice(60)]:result.items;total=result.total;}
   catch(e){if(!current.signal.aborted&&alive)error=e instanceof Error?e.message:'Could not load downloads.';}
   finally{if(current===request)loading=false;}
 }
 function input(){request?.abort();clearTimeout(debounce);debounce=setTimeout(()=>void load(),200);}
 async function start(){
  busy=true;error='';
  try{const item=await youtubeApi.download(query.trim(),video,audio);query='';optionsOpen=false;items=[item,...items];total++;await load();}
  catch(e){error=e instanceof Error?e.message:'Could not start download.';}
  finally{busy=false;}
 }
 async function action(item:Download,retry=false){
  error='';try{const updated=await(retry?youtubeApi.retry(item.id):youtubeApi.cancel(item.id));items=retry?[updated,...items]:items.map(row=>row.id===updated.id?updated:row);await load();}
  catch(e){error=e instanceof Error?e.message:'Could not update download.';}
 }
 async function poll(){if(!selected&&items.some(active))await load(false,true);if(alive)timer=setTimeout(poll,1000);}
 onMount(()=>{motion=document.documentElement.dataset.motion==='reduced'||window.matchMedia('(prefers-reduced-motion: reduce)').matches?0:200;void engine();void load();timer=setTimeout(poll,1000);});
 onDestroy(()=>{alive=false;request?.abort();clearTimeout(timer);clearTimeout(debounce);});
</script>
<svelte:window on:keydown={escape}/>
<div class="youtube-surface" inert={!!selected}>
 <header><button class="menu" aria-label="Open Keivotos menu" on:click={()=>drawer=true}>☰</button><span class="module-title">YouTube</span><div class="search-controls"><div class="options-anchor"><button class="options-toggle" aria-label="Download options" title="Download options" aria-expanded={optionsOpen} aria-controls="download-options" on:click={()=>optionsOpen=!optionsOpen}><svg class:opened={optionsOpen} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="m6 15 6-6 6 6"/></svg></button>
 {#if optionsOpen}
 <div id="download-options" class="download-options" transition:slide={{duration:motion}}>
 <label>Video<select aria-label="Video quality" bind:value={video}><option value="best">Best</option><option value="1080">1080p</option><option value="720">720p</option><option value="480">480p</option><option value="audio">Audio only</option></select></label>
 <label>Audio<select aria-label="Audio quality" bind:value={audio}><option value="best">Best</option><option value="192">Up to 192 kbps</option><option value="128">Up to 128 kbps</option></select></label>
 {#if status&&!status.ready}<p role="status">Missing: {status.missing.join(', ')}. <button on:click={engine}>Check again</button></p>{/if}
 </div>{/if}</div><input aria-label="Search downloads or paste a YouTube URL" placeholder="Search or paste a YouTube URL…" bind:value={query} on:input={input}/>{#if urlMode}<button class="download" disabled={busy||!urlMode||!status?.ready} on:click={start}>{busy?'Starting…':'Download'}</button>{/if}</div></header>
 <main>
  {#if error}<p role="alert">{error}</p>{/if}
  <div class="download-grid" aria-busy={loading}>
   {#each items as item (item.id)}
    <article>
     <div class="thumbnail">
      {#if item.status==='complete'}
       {#if isAudio(item)}
       <a href={filesApi.fileUrl(item.source_id,item.path)} target="_blank" rel="noreferrer" aria-label={`Open ${item.title}`}>
        {#if item.thumbnail}<img alt="" loading="lazy" src={filesApi.thumbnailUrl(item.source_id,item.thumbnail,600,item.id)} on:error={e=>(e.currentTarget as HTMLImageElement).style.display='none'}/>{/if}
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m8 5 11 7-11 7Z"/></svg>
       </a>
       {:else}
       <button class="play-download" on:click={()=>open(item)} aria-label={`Open ${item.title}`}>
        {#if item.thumbnail}<img alt="" loading="lazy" src={filesApi.thumbnailUrl(item.source_id,item.thumbnail,600,item.id)} on:error={e=>(e.currentTarget as HTMLImageElement).style.display='none'}/>{/if}
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m8 5 11 7-11 7Z"/></svg>
       </button>
       {/if}
      {/if}
      {#if active(item)}<button class="job-action" aria-label={`Cancel ${item.title||'download'}`} title="Cancel download" on:click={()=>action(item)}>×</button>
      {:else if item.status!=='complete'}<button class="job-action" aria-label={`Retry ${item.title||'download'}`} title="Retry download" on:click={()=>action(item,true)}>↻</button>{/if}
     </div>
     {#if active(item)}<div class="progress" role="progressbar" aria-label={item.title||'Download'} aria-valuenow={Math.round(item.progress)} aria-valuemin="0" aria-valuemax="100"><div class:pending={item.status==='queued'||item.status==='merging'} style={`width:${Math.max(2,item.progress)}%`}></div></div>{/if}
     <div class="download-title">{item.title||'YouTube video'}</div>
     {#if !active(item)&&item.status!=='complete'}<p class="job-error">{item.status==='cancelled'?'Cancelled':item.error||'Interrupted. Retry to download again.'}</p>{/if}
    </article>
   {/each}
  </div>
  {#if items.length<total}<button class="more" disabled={loading} on:click={()=>load(true)}>Load more</button>{/if}
 </main>
</div>
{#if drawer}<AppDrawer on:close={()=>drawer=false}/>{/if}
{#if selected && playback}
 <MediaPlayer media={playback} label="YouTube player" backLabel="Back to downloads"
  hasPrevious={selectedIndex>0} hasNext={selectedIndex>=0&&(selectedIndex<playable.length-1||items.length<total)}
  {navigating} {navigationNotice} onClose={close} onPrevious={()=>adjacent(-1)} onNext={()=>adjacent(1)}
  onFailure={(_media,reason)=>youtubeApi.playbackError(selected!.id,reason)}/>
{/if}
<style>
 .youtube-surface{display:flex;flex:1;min-height:0;flex-direction:column;background:#0f0f14;color:#e0e0e8}
 header{display:flex;align-items:center;gap:16px;min-height:60px;border-bottom:1px solid #2a2a3a;padding:8px 16px}
 .menu{width:36px;height:36px;border-radius:8px;background:#1e1e2e}.module-title{font-size:18px;font-weight:600}
 .search-controls{display:flex;align-items:center;gap:10px;flex:1;min-width:0;max-width:800px;margin:auto}
 header input{min-width:0;flex:1;border:1px solid #2a2a3a;border-radius:8px;padding:8px 12px;background:#1a1a24;font-size:14px}
 .options-anchor{position:relative;flex-shrink:0}.options-toggle{display:grid;place-items:center;width:40px;height:36px;border:0;border-radius:20px;background:#26262d;color:#ddd}.options-toggle svg{width:20px;height:20px;transition:transform .2s ease}.options-toggle svg.opened{transform:rotate(180deg)}
 .download-options{position:absolute;left:-16px;top:46px;z-index:30;width:350px;max-width:calc(100vw - 92px);padding:16px;display:grid;grid-template-columns:1fr 1fr;gap:14px;border-radius:16px;background:#191920;box-shadow:0 12px 32px #0008}
 label{display:flex;flex-direction:column;gap:8px;min-width:0;font-size:13px;color:#ddd}select{border:0;border-radius:20px;background:#26262d;padding:9px 12px;color:#ddd;font-size:13px;min-width:0;width:100%}
 .download{background:var(--accent);color:#111118;padding:9px 18px;border-radius:20px;font-size:13px;font-weight:600;flex-shrink:0}.download:disabled{opacity:.4}.download-options p{grid-column:1/-1;font-size:12px;color:#aaa;padding:0 8px}
 @media(max-width:700px){.module-title{display:none}}
 main{overflow:auto;flex:1;padding:24px;min-height:0}.download-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(260px,100%),1fr));gap:24px 18px}
 article{min-width:0}.thumbnail{aspect-ratio:16/9;background:#1a1a24;border-radius:10px;position:relative;overflow:hidden}.thumbnail a,.thumbnail .play-download{display:grid;place-items:center;width:100%;height:100%}.thumbnail img{width:100%;height:100%;object-fit:cover;position:absolute}.thumbnail svg{width:28px;height:28px;fill:none;stroke:#ddd;stroke-width:1.5;position:relative;opacity:.7}
 .job-action{position:absolute;right:8px;top:8px;background:#292933;width:28px;height:28px;border-radius:50%;font-size:20px;display:grid;place-items:center}.download-title{padding-top:8px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:14px}.job-error{font-size:12px;color:#aaa;margin-top:4px}
 .progress{height:6px;overflow:hidden;border-radius:999px;background:#20202b;margin-top:8px}.progress>div{height:100%;border-radius:999px;background:var(--accent);transition:width .2s ease}.pending{opacity:.65}.more{display:block;margin:24px auto;padding:8px 12px}
 button:focus-visible,input:focus-visible,select:focus-visible,a:focus-visible{outline:2px solid var(--accent);outline-offset:3px}
 :global(html[data-motion='reduced']) .progress>div{transition:none}
 :global(html[data-motion='reduced']) .options-toggle svg{transition:none}
 @media(prefers-reduced-motion:reduce){.options-toggle svg{transition:none}}
</style>
