<script lang="ts">
  import {onMount,onDestroy,tick} from 'svelte';
  import AppDrawer from '../../components/AppDrawer.svelte';
  import {settingsOpen,settingsInitialSection} from '../../lib/suiteStores';
  import {mangaApi,type Manga,type Chapter} from './api';
  let drawer=false, query='', loading=false, error='';
  let items:Manga[]=[], total=0;
  let selected:Manga|null=null, chapters:Chapter[]=[], chapter:Chapter|null=null;
  let chapterLoading=false, chapterError='', readerError='', pageCount=0;
  let mode='fit';
  let dialog:HTMLDivElement, reader:HTMLDivElement;
  let tileFocus:HTMLElement|null=null, chapterFocus:HTMLElement|null=null;
  let libraryRequest:AbortController|null=null, detailRequest:AbortController|null=null, pageRequest:AbortController|null=null;
  let debounce:ReturnType<typeof setTimeout>;
  let visible=new Set<number>();
  let ratios:Record<number,number>={};
  let observer:IntersectionObserver|null=null;
  async function load(more=false){
    libraryRequest?.abort();const current=new AbortController();libraryRequest=current;
    loading=true;error='';
    try{const result=await mangaApi.library(query,more?items.length:0,current.signal);if(current.signal.aborted)return;items=more?[...items,...result.items]:result.items;total=result.total;}
    catch(e){if(!current.signal.aborted)error=e instanceof Error?e.message:'Could not load manga.';}
    finally{if(libraryRequest===current)loading=false;}
  }
  function search(){libraryRequest?.abort();clearTimeout(debounce);debounce=setTimeout(()=>void load(),200);}
  function folders(){settingsInitialSection.set('roots');settingsOpen.set(true);}
  async function open(manga:Manga){
    tileFocus=document.activeElement as HTMLElement;selected=manga;chapters=[];chapterError='';chapterLoading=true;
    detailRequest?.abort();const current=new AbortController();detailRequest=current;
    await tick();dialog?.focus();
    try{const result=await mangaApi.chapters(manga,current.signal);if(!current.signal.aborted)chapters=result.items;}
    catch(e){if(!current.signal.aborted)chapterError=e instanceof Error?e.message:'Could not load chapters.';}
    finally{if(detailRequest===current)chapterLoading=false;}
  }
  async function close(){detailRequest?.abort();selected=null;await tick();tileFocus?.focus();}
  async function read(item:Chapter){
    if(!selected)return;
    chapterFocus=document.activeElement as HTMLElement;chapter=item;pageCount=0;readerError='';visible=new Set();ratios={};
    pageRequest?.abort();const current=new AbortController();pageRequest=current;
    await tick();reader?.focus();
    try{const result=await mangaApi.pages(selected,item,current.signal);if(!current.signal.aborted)pageCount=result.count;}
    catch(e){if(!current.signal.aborted)readerError=e instanceof Error?e.message:'Could not open chapter. See Logs.';}
  }
  async function back(){pageRequest?.abort();observer?.disconnect();observer=null;chapter=null;pageCount=0;await tick();chapterFocus?.focus();}
  function keys(event:KeyboardEvent,root:HTMLElement,exit:()=>void){
    if(event.key==='Escape'){event.preventDefault();exit();return;}
    if(event.key!=='Tab')return;
    const controls=[...root.querySelectorAll<HTMLElement>('button:not(:disabled),select')];
    const first=controls[0],last=controls[controls.length-1];
    if(event.shiftKey&&(document.activeElement===first||document.activeElement===root)){event.preventDefault();last?.focus();}
    else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}
  }
  function watchPage(node:HTMLElement,index:number){
    if(!observer)observer=new IntersectionObserver(entries=>{
      const next=new Set(visible);
      for(const entry of entries){const n=Number((entry.target as HTMLElement).dataset.page);if(entry.isIntersecting)next.add(n);else next.delete(n);}
      visible=next;
    },{rootMargin:'100% 0px'});
    observer.observe(node);
    return {destroy(){observer?.unobserve(node);}};
  }
  function dimensions(event:Event,index:number){const image=event.currentTarget as HTMLImageElement;ratios={...ratios,[index]:image.naturalWidth/image.naturalHeight};}
  function changeMode(){reader?.scrollTo({top:0});}
  onMount(()=>{void load();});
  onDestroy(()=>{clearTimeout(debounce);libraryRequest?.abort();detailRequest?.abort();pageRequest?.abort();observer?.disconnect();});
</script>

<div class="manga-surface" inert={!!selected}>
  <header>
    <button class="menu" aria-label="Open Keivotos menu" on:click={()=>drawer=true}>☰</button>
    <span class="module-title">Manga</span>
    <input aria-label="Search manga" placeholder="Search manga…" bind:value={query} on:input={search}/>
  </header>
  <main>
    {#if error}<p role="alert">{error} <button on:click={()=>load()}>Retry</button></p>{/if}
    {#if !loading&&!error&&!items.length}<p class="empty">{#if query}No manga found.{:else}<button on:click={folders}>Add Manga folders in Settings</button>{/if}</p>{/if}
    <div class="manga-grid" aria-busy={loading}>
      {#each items as item (`${item.source_id}/${item.path}`)}
        <button class="manga-tile" title={item.name} on:click={()=>open(item)}>
          <span class="cover"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 4h7v16H4zM11 4h9v16h-9"/></svg><img alt="" loading="lazy" src={mangaApi.page(item,item.cover,0,true)} on:error={e=>(e.currentTarget as HTMLImageElement).style.display='none'}/></span>
          <span class="manga-name">{item.name}</span>
        </button>
      {/each}
    </div>
    {#if items.length<total}<button class="more" disabled={loading} on:click={()=>load(true)}>{loading?'Loading…':'Load more'}</button>{/if}
  </main>
</div>
{#if drawer}<AppDrawer on:close={()=>drawer=false}/>{/if}
{#if selected}
  <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
  <div class="scrim" inert={!!chapter} on:click={event=>{if(event.target===event.currentTarget)void close();}}>
    <!-- svelte-ignore a11y_no_noninteractive_tabindex a11y_no_noninteractive_element_interactions -->
    <div class="chapter-dialog" role="dialog" aria-modal="true" aria-label={selected.name+' chapters'} tabindex="-1" bind:this={dialog} on:keydown={event=>keys(event,dialog,()=>void close())}>
      <button class="back" aria-label="Back to manga" on:click={close}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m14 5-7 7 7 7"/></svg></button>
      <div class="chapter-cover"><img alt={selected.name} src={mangaApi.page(selected,selected.cover,0,true)} on:error={e=>(e.currentTarget as HTMLImageElement).style.visibility='hidden'}/></div>
      <div class="chapter-list" aria-busy={chapterLoading}>
        {#if chapterLoading}<p class="muted">Loading…</p>{/if}
        {#if chapterError}<p role="alert">{chapterError}</p>{/if}
        {#each chapters as item (`${item.kind}/${item.path}`)}<button on:click={()=>read(item)}>{item.name}<span aria-hidden="true">›</span></button>{/each}
      </div>
    </div>
  </div>
{/if}
{#if selected&&chapter}
  <!-- svelte-ignore a11y_no_noninteractive_tabindex a11y_no_noninteractive_element_interactions -->
  <div class="reader" class:vertical={mode==='vertical'} bind:this={reader} role="dialog" aria-label="Manga reader" aria-modal="true" tabindex="-1" on:keydown={event=>keys(event,reader,()=>void back())}>
    <div class="reader-controls">
      <button class="back" aria-label="Back to chapters" on:click={back}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m14 5-7 7 7 7"/></svg></button>
      <select aria-label="Reading layout" bind:value={mode} on:change={changeMode}><option value="fit">Fit</option><option value="vertical">Vertical scroll</option></select>
    </div>
    {#if readerError}<p class="reader-error" role="alert">{readerError}</p>{/if}
    {#if !pageCount&&!readerError}<p class="muted loading">Loading…</p>{/if}
    {#each Array(pageCount) as _,i}
      <div class="page" data-page={i} style={`--ratio:${ratios[i]||2/3}`} use:watchPage={i}>
        {#if visible.has(i)}<img alt={`Page ${i+1}`} src={mangaApi.page(selected,chapter,i)} on:load={e=>dimensions(e,i)} on:error={()=>readerError='This page cannot be opened. See Logs.'}/>{/if}
      </div>
    {/each}
  </div>
{/if}

<style>
 .manga-surface{display:flex;flex:1;min-height:0;flex-direction:column;background:#0f0f14;color:#e0e0e8}
 header{display:flex;align-items:center;gap:16px;min-height:60px;border-bottom:1px solid #2a2a3a;padding:8px 16px}
 .menu{width:36px;height:36px;border-radius:8px;background:#1e1e2e}
 .module-title{font-size:18px;font-weight:600}
 header input{max-width:640px;width:100%;margin-left:auto;margin-right:auto;border:1px solid #2a2a3a;border-radius:8px;padding:8px 12px;background:#1a1a24;font-size:14px}
 main{overflow:auto;flex:1;padding:24px;min-height:0}
 .manga-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(170px,100%),1fr));gap:28px 20px}
 .manga-tile{text-align:left;min-width:0}
 .cover{display:grid;place-items:center;position:relative;aspect-ratio:2/3;background:#1b1b24;border-radius:8px;overflow:hidden;color:#777788}
 .cover img{position:absolute;width:100%;height:100%;object-fit:cover}
 .manga-name{display:block;padding-top:10px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:14px}
 svg{width:24px;height:24px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
 .empty{text-align:center;color:#9292a5;padding:40px}.more{display:block;margin:24px auto;padding:8px 12px}
 .scrim{position:fixed;inset:0;z-index:110;display:grid;place-items:center;background:#000b;padding:24px}
 .chapter-dialog{position:relative;display:grid;grid-template-columns:minmax(0,230px) minmax(0,1fr);gap:32px;width:min(720px,100%);max-height:80dvh;padding:72px 32px 32px;background:#19191f;border-radius:14px;color:#eee}
 .chapter-cover{aspect-ratio:2/3;background:#24242d;border-radius:6px;overflow:hidden;align-self:start}
 .chapter-cover img{width:100%;height:100%;object-fit:cover}
 .chapter-list{overflow:auto;min-height:0}.chapter-list button{display:flex;align-items:center;justify-content:space-between;width:100%;text-align:left;padding:16px 12px;border-radius:6px;font-size:14px;gap:16px;overflow-wrap:anywhere}
 .chapter-list button:hover{background:#ffffff0b}.chapter-list span{font-size:23px;color:#888}
 .back{display:grid;place-items:center;width:40px;height:40px;border:0;background:transparent;border-radius:999px;color:#eee;transition:width .18s ease,background-color .18s ease}
 .back:hover,.back:focus-visible{width:56px;background:#33333b}
 .chapter-dialog>.back{position:absolute;top:16px;left:16px}
 .reader{position:fixed;inset:0;z-index:120;overflow-y:auto;overscroll-behavior:contain;background:#080808;color:#eee}
 .reader-controls{position:fixed;top:16px;left:16px;z-index:1;display:flex;align-items:center;gap:8px}
 .reader-controls select{border:0;border-radius:20px;background:#26262d;color:#ddd;padding:9px 12px;font-size:13px;cursor:pointer}
 .page{height:100dvh;display:flex;justify-content:center;align-items:center;width:100%;margin:0 auto}
 .page img{width:100%;height:100%;object-fit:contain}
 .vertical .page{height:auto;width:min(100%,1000px);aspect-ratio:var(--ratio)}
 .reader-error{position:fixed;left:50%;top:70px;transform:translateX(-50%);background:#26262d;padding:10px 16px;border-radius:8px;z-index:1;font-size:14px}
 .muted{color:#9292a5}.loading{padding:80px 24px}
 button:focus-visible,select:focus-visible,input:focus-visible{outline:2px solid var(--accent);outline-offset:3px}
 :global(html[data-motion='reduced']) .back{transition:none}
 @media(prefers-reduced-motion:reduce){.back{transition:none}}
 @media(max-width:560px){.chapter-dialog{grid-template-columns:minmax(0,110px) minmax(0,1fr);gap:16px;padding:64px 16px 16px}.scrim{padding:12px}.manga-grid{grid-template-columns:repeat(auto-fill,minmax(130px,1fr))}}
</style>
