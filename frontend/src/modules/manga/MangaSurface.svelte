<script lang="ts">
  import {onMount,onDestroy,tick} from 'svelte';
  import AppDrawer from '../../components/AppDrawer.svelte';
  import ModuleLocationMenu from '../../components/ModuleLocationMenu.svelte';
  import {settingsOpen,settingsInitialSection,suiteModules} from '../../lib/suiteStores';
  import {mangaApi,createPagePrefetch,type Manga,type Chapter} from './api';
  let drawer=false, query='', loading=false, error='';
  let items:Manga[]=[], total=0;
  let selected:Manga|null=null, chapters:Chapter[]=[], chapter:Chapter|null=null;
  let chapterLoading=false, chapterError='', readerError='', pageCount=0;
  let chapterRevision='', pageRevisions:string[]=[], converted=new Set<number>(), failedPage:number|null=null;
  let mode='paged', pageIndex=0, controlsVisible=true;
  let verticalIndex=0,scrollFrame:number|null=null;
  const pageNodes=new Map<number,HTMLElement>();
  const prefetch=createPagePrefetch();
  let loadedPage='';
  let dialog:HTMLDivElement, reader:HTMLDivElement;
  let tileFocus:HTMLElement|null=null, chapterFocus:HTMLElement|null=null;
  let libraryRequest:AbortController|null=null, detailRequest:AbortController|null=null, pageRequest:AbortController|null=null;
  let refreshRequest:AbortController|null=null;
  let debounce:ReturnType<typeof setTimeout>;
  let visible=new Set<number>();
  let ratios:Record<number,number>={};
  let observer:IntersectionObserver|null=null;
  let pointerStart:{x:number;y:number}|null=null, pointerDragged=false;
  let locationMenu:{x:number;y:number;label:string;sourceId:string;relativePath:string;anchor:HTMLElement}|null=null;
  let locationMenuSerial=0;
  function openLocation(event:MouseEvent|KeyboardEvent,label:string,sourceId:string,relativePath:string){
    event.preventDefault();event.stopPropagation();
    const anchor=event.currentTarget as HTMLElement,rect=anchor.getBoundingClientRect();
    locationMenu={x:event instanceof MouseEvent?event.clientX:rect.left+8,y:event instanceof MouseEvent?event.clientY:rect.top+rect.height,
      label,sourceId,relativePath,anchor};
    locationMenuSerial++;
  }
  function locationKey(event:KeyboardEvent,label:string,sourceId:string,relativePath:string){if(event.key==='ContextMenu'||event.shiftKey&&event.key==='F10')openLocation(event,label,sourceId,relativePath);}
  async function load(more=false,keepCount=false){
    libraryRequest?.abort();const current=new AbortController();libraryRequest=current;
    loading=true;error='';
    try{
      const wanted=keepCount?items.length:0;let next:Manga[]=[],result:{items:Manga[];total:number};
      do{result=await mangaApi.library(query,more?items.length:next.length,current.signal);if(current.signal.aborted)return;next=[...next,...result.items];}
      while(!more&&next.length<wanted&&next.length<result.total&&result.items.length>0);
      items=more?[...items,...next]:next;total=result.total;
    }
    catch(e){if(!current.signal.aborted)error=e instanceof Error?e.message:'Could not load manga.';}
    finally{if(libraryRequest===current)loading=false;}
  }
  function search(){libraryRequest?.abort();clearTimeout(debounce);debounce=setTimeout(()=>void load(),200);}
  function folders(){settingsInitialSection.set('roots');settingsOpen.set(true);}
  async function open(manga:Manga){
    refreshRequest?.abort();
    tileFocus=document.activeElement as HTMLElement;selected=manga;chapters=[];chapterError='';chapterLoading=true;
    detailRequest?.abort();const current=new AbortController();detailRequest=current;
    await tick();dialog?.focus();
    try{const result=await mangaApi.chapters(manga,current.signal);if(!current.signal.aborted)chapters=result.items;}
    catch(e){if(!current.signal.aborted)chapterError=e instanceof Error?e.message:'Could not load chapters.';}
    finally{if(detailRequest===current)chapterLoading=false;}
  }
  async function close(){detailRequest?.abort();refreshRequest?.abort();selected=null;await tick();tileFocus?.focus();}
  async function read(item:Chapter){
    if(!selected)return;
    if(!reader?.contains(document.activeElement))chapterFocus=document.activeElement as HTMLElement;
    refreshRequest?.abort();clearPages();chapter=item;pageIndex=0;controlsVisible=true;readerError='';ratios={};
    pageRequest?.abort();const current=new AbortController();pageRequest=current;
    await tick();reader?.focus();
    try{const result=await mangaApi.pages(selected,item,current.signal);if(!current.signal.aborted){chapterRevision=result.revision;pageRevisions=result.revisions;pageCount=result.count;}}
    catch(e){if(!current.signal.aborted)readerError=e instanceof Error?e.message:'Could not open chapter. See Logs.';}
  }
  function clearPages(){prefetch.clear();loadedPage='';cancelScrollFrame();verticalIndex=0;pageNodes.clear();observer?.disconnect();observer=null;pageCount=0;chapterRevision='';pageRevisions=[];converted=new Set();failedPage=null;visible=new Set();}
  async function back(){pageRequest?.abort();refreshRequest?.abort();clearPages();chapter=null;await tick();chapterFocus?.focus();}
  function pageUrl(index:number,revisions=pageRevisions,fallback=converted){return mangaApi.page(selected!,chapter!,index,false,revisions[index],fallback.has(index)?'webp':'original');}
  function warmPages(manga:Manga|null,item:Chapter|null,count:number,index:number,layout:string,revisions:string[],fallback:Set<number>,loaded:string){
    if(!manga||!item||!count||layout!=='paged'){prefetch.clear();return;}
    const url=(page:number)=>mangaApi.page(manga,item,page,false,revisions[page],fallback.has(page)?'webp':'original');
    prefetch.update(url(index),[index+1,index-1,index+2].filter(page=>page>=0&&page<count).map(url),loaded===url(index));
  }
  $: warmPages(selected,chapter,pageCount,pageIndex,mode,pageRevisions,converted,loadedPage);
  function pageLoaded(event:Event,index:number,url:string){
    const image=event.currentTarget as HTMLImageElement;
    if(chapter&&pageCount&&mode==='paged'&&index===pageIndex&&pageUrl(index)===url&&image.getAttribute('src')===url)loadedPage=url;
  }
  function pageFailed(event:Event,index:number,url:string){
    if(!chapter||!pageCount||pageUrl(index)!==url||(mode==='paged'&&index!==pageIndex))return;
    if((event.currentTarget as HTMLImageElement).getAttribute('src')!==url)return;
    failedPage=index;readerError=converted.has(index)?`Converted page ${index+1} cannot be opened. See Logs.`:`Original page ${index+1} is unavailable or unsupported. You can try a converted still image, or reopen a changed chapter.`;
  }
  function convertFailed(){if(failedPage===null)return;converted=new Set([...converted,failedPage]);readerError='';failedPage=null;void tick().then(()=>reader?.focus());}
  async function refreshSources(){
    refreshRequest?.abort();const current=new AbortController();refreshRequest=current;
    const openChapter=chapter,openManga=selected;
    await load(false,true);if(current.signal.aborted)return;
    if(error){pageRequest?.abort();detailRequest?.abort();clearPages();chapter=null;selected=null;items=[];return;}
    if(openManga){
      const fresh=items.find(item=>item.source_id===openManga.source_id&&item.path===openManga.path);
      if(!fresh){pageRequest?.abort();detailRequest?.abort();clearPages();chapter=null;selected=null;return;}
      if(selected?.source_id===openManga.source_id&&selected.path===openManga.path)selected=fresh;
    }
    if(!openChapter||!openManga||chapter!==openChapter||!pageCount)return;
    try{
      const metadata=await mangaApi.pages(openManga,openChapter,current.signal);
      if(current.signal.aborted||chapter!==openChapter)return;
      if(metadata.revision!==chapterRevision){clearPages();readerError='This chapter changed. Reopen it to load the current pages.';}
    }catch(e){if(!current.signal.aborted&&chapter===openChapter){clearPages();readerError=e instanceof Error?e.message:'This chapter is unavailable.';}}
  }
  function keys(event:KeyboardEvent,root:HTMLElement,exit:()=>void){
    if(event.key==='Escape'){event.preventDefault();exit();return;}
    if(event.key!=='Tab')return;
    const controls=[...root.querySelectorAll<HTMLElement>('button:not(:disabled),select')];
    const first=controls[0],last=controls[controls.length-1];
    if(event.shiftKey&&(document.activeElement===first||document.activeElement===root)){event.preventDefault();last?.focus();}
    else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}
  }
  function turnPage(direction:-1|1){const next=Math.max(0,Math.min(pageCount-1,pageIndex+direction));if(next!==pageIndex&&failedPage!==null){readerError='';failedPage=null;}pageIndex=next;}
  function readerKeys(event:KeyboardEvent){
    if(event.key==='Tab'&&!controlsVisible){
      event.preventDefault();controlsVisible=true;
      void tick().then(()=>reader?.querySelector<HTMLElement>(event.shiftKey?'.reader-controls select':'.reader-controls button')?.focus());
      return;
    }
    if(mode==='paged'&&pageCount&&!(event.target as HTMLElement).closest('.reader-controls,.reader-error')&&['ArrowLeft','ArrowUp','PageUp','ArrowRight','ArrowDown','PageDown',' '].includes(event.key)){
      event.preventDefault();turnPage(['ArrowLeft','ArrowUp','PageUp'].includes(event.key)?-1:1);return;
    }
    keys(event,reader,()=>void back());
  }
  function watchPage(node:HTMLElement,index:number){
    pageNodes.set(index,node);
    if(!observer)observer=new IntersectionObserver(entries=>{
      const next=new Set(visible);
      for(const entry of entries){const n=Number((entry.target as HTMLElement).dataset.page);if(entry.isIntersecting)next.add(n);else next.delete(n);}
      visible=next;
      trackVerticalPage();
    },{rootMargin:'100% 0px'});
    observer.observe(node);
    return {destroy(){observer?.unobserve(node);if(pageNodes.get(index)===node)pageNodes.delete(index);}};
  }
  function dimensions(event:Event,index:number){const image=event.currentTarget as HTMLImageElement;ratios={...ratios,[index]:image.naturalWidth/image.naturalHeight};trackVerticalPage();}
  function nearestPage(all=false){
    const bounds=reader.getBoundingClientRect(),center=bounds.top+bounds.height/2;
    let nearest=verticalIndex,distance=Infinity;
    for(const index of all?pageNodes.keys():visible){
      const node=pageNodes.get(index);if(!node)continue;
      const rect=node.getBoundingClientRect();
      if(rect.top<=center&&rect.bottom>center)return index;
      const gap=Math.max(rect.top-center,center-rect.bottom,0);
      if(gap<distance){nearest=index;distance=gap;}
    }
    return Math.max(0,Math.min(pageCount-1,nearest));
  }
  function cancelScrollFrame(){if(scrollFrame!==null)cancelAnimationFrame(scrollFrame);scrollFrame=null;}
  function trackVerticalPage(){
    if(mode!=='vertical'||!reader||!pageCount||scrollFrame!==null)return;
    scrollFrame=requestAnimationFrame(()=>{scrollFrame=null;if(mode==='vertical'&&reader&&pageCount)verticalIndex=nearestPage();});
  }
  async function changeMode(){
    if(mode==='paged'){
      cancelScrollFrame();pageIndex=nearestPage(true);
      reader.scrollTo({top:0});
    }else{
      verticalIndex=pageIndex;
      await tick();reader.querySelector<HTMLElement>(`.page[data-page="${pageIndex}"]`)?.scrollIntoView({block:'start'});
      trackVerticalPage();
    }
  }
  function pointerDown(event:PointerEvent){pointerStart={x:event.clientX,y:event.clientY};pointerDragged=false;}
  function pointerMove(event:PointerEvent){if(pointerStart&&Math.hypot(event.clientX-pointerStart.x,event.clientY-pointerStart.y)>8)pointerDragged=true;}
  function readerClick(event:MouseEvent){
    if(pointerDragged){pointerDragged=false;return;}
    if((event.target as HTMLElement).closest('.reader-controls,.reader-error'))return;
    const bounds=reader.getBoundingClientRect(),position=(event.clientY-bounds.top)/bounds.height;
    if(mode==='paged'&&position<=.25)turnPage(-1);
    else if(mode==='paged'&&position>=.75)turnPage(1);
    else if(position>.25&&position<.75){
      controlsVisible=!controlsVisible;
      if(!controlsVisible&&reader.contains(document.activeElement))reader.focus();
    }
  }
  onMount(()=>{
    void load();let settingsSeen=false;
    const stopSettings=settingsOpen.subscribe(value=>{if(value)settingsSeen=true;else if(settingsSeen){settingsSeen=false;void refreshSources();}});
    const stopModules=suiteModules.subscribe(modules=>{if(modules.find(module=>module.id==='manga')?.enabled===false){libraryRequest?.abort();detailRequest?.abort();pageRequest?.abort();refreshRequest?.abort();clearPages();chapter=null;selected=null;items=[];}});
    const focus=()=>{if(!settingsSeen)void refreshSources();};window.addEventListener('focus',focus);
    return()=>{stopSettings();stopModules();window.removeEventListener('focus',focus);};
  });
  onDestroy(()=>{prefetch.clear();cancelScrollFrame();clearTimeout(debounce);libraryRequest?.abort();detailRequest?.abort();pageRequest?.abort();refreshRequest?.abort();observer?.disconnect();});
</script>

<svelte:window on:resize={trackVerticalPage}/>

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
        <button class="manga-tile" title={item.name} on:click={()=>open(item)} on:contextmenu={event=>openLocation(event,item.name,item.source_id,item.path)} on:keydown={event=>locationKey(event,item.name,item.source_id,item.path)}>
          <span class="cover"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 4h7v16H4zM11 4h9v16h-9"/></svg><img alt="" loading="lazy" src={mangaApi.page(item,item.cover,0,true)} on:load={e=>(e.currentTarget as HTMLImageElement).style.display=''} on:error={e=>(e.currentTarget as HTMLImageElement).style.display='none'}/></span>
          <span class="manga-name">{item.name}</span>
        </button>
      {/each}
    </div>
    {#if items.length<total}<button class="more" disabled={loading} on:click={()=>load(true)}>{loading?'Loading…':'Load more'}</button>{/if}
  </main>
</div>
{#if drawer}<AppDrawer on:close={()=>drawer=false}/>{/if}
{#if locationMenu}
  {#key locationMenuSerial}<ModuleLocationMenu {...locationMenu} on:close={()=>locationMenu=null}/>{/key}
{/if}
{#if selected}
  <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
  <div class="scrim" inert={!!chapter} on:click={event=>{if(event.target===event.currentTarget)void close();}}>
    <!-- svelte-ignore a11y_no_noninteractive_tabindex a11y_no_noninteractive_element_interactions -->
    <div class="chapter-dialog" role="dialog" aria-modal="true" aria-label={selected.name+' chapters'} tabindex="-1" bind:this={dialog} on:keydown={event=>keys(event,dialog,()=>void close())}>
      <div class="chapter-heading">
        <button class="back" aria-label="Back to manga" on:click={close}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m14 5-7 7 7 7"/></svg></button>
        <h2 class="series-title" title={selected.name}>{selected.name}</h2>
      </div>
      <div class="chapter-cover"><img alt={selected.name} src={mangaApi.page(selected,selected.cover,0,true)} on:load={e=>(e.currentTarget as HTMLImageElement).style.visibility=''} on:error={e=>(e.currentTarget as HTMLImageElement).style.visibility='hidden'}/></div>
      <div class="chapter-list" aria-busy={chapterLoading}>
        {#if chapterLoading}<p class="muted">Loading…</p>{/if}
        {#if chapterError}<p role="alert">{chapterError}</p>{/if}
        {#each chapters as item (`${item.kind}/${item.path}`)}<button on:click={()=>read(item)} on:contextmenu={event=>openLocation(event,item.name,selected!.source_id,item.path)} on:keydown={event=>locationKey(event,item.name,selected!.source_id,item.path)}>{item.name}<span aria-hidden="true">›</span></button>{/each}
      </div>
    </div>
  </div>
{/if}
{#if selected&&chapter}
  <!-- svelte-ignore a11y_no_noninteractive_tabindex a11y_no_noninteractive_element_interactions -->
  <div class="reader" class:vertical={mode==='vertical'} bind:this={reader} role="dialog" aria-label="Manga reader" aria-modal="true" tabindex="-1" on:keydown={readerKeys} on:pointerdown={pointerDown} on:pointermove={pointerMove} on:click={readerClick} on:scroll={trackVerticalPage}>
    <div class="reader-controls" class:hidden={!controlsVisible} inert={!controlsVisible} aria-hidden={!controlsVisible}>
      <div class="reader-heading">
        <button class="back" aria-label="Back to chapters" on:click={back}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m14 5-7 7 7 7"/></svg></button>
        <span class="series-title" title={selected.name}>{selected.name}</span>
      </div>
      <span class="page-counter" role="status" aria-live="off" aria-label={pageCount?`Page ${(mode==='vertical'?verticalIndex:pageIndex)+1} of ${pageCount}`:'Page count unavailable'}>{pageCount?`${(mode==='vertical'?verticalIndex:pageIndex)+1} / ${pageCount}`:'— / —'}</span>
      <select aria-label="Reading layout" bind:value={mode} on:change={changeMode}><option value="paged">Paged</option><option value="vertical">Vertical scroll</option></select>
    </div>
    {#if readerError}<div class="reader-error" role="alert">{readerError}
      {#if failedPage!==null&&!converted.has(failedPage)}<button on:click={convertFailed}>Open converted page</button>{/if}
      <button on:click={()=>chapter&&read(chapter)}>Reopen chapter</button>
    </div>{/if}
    {#if !pageCount&&!readerError}<p class="muted loading">Loading…</p>{/if}
    {#if mode==='paged'&&pageCount}
      {@const url=pageUrl(pageIndex,pageRevisions,converted)}
      <div class="paged-page" data-page={pageIndex}><img alt={`Page ${pageIndex+1}`} src={url} fetchpriority="high" on:load={event=>pageLoaded(event,pageIndex,url)} on:error={event=>pageFailed(event,pageIndex,url)}/></div>
    {:else if mode==='vertical'}
      {#each Array(pageCount) as _,i}
        <div class="page" data-page={i} style={`--ratio:${ratios[i]||2/3}`} use:watchPage={i}>
          {#if visible.has(i)}{@const url=pageUrl(i,pageRevisions,converted)}<img alt={`Page ${i+1}`} src={url} on:load={e=>dimensions(e,i)} on:error={event=>pageFailed(event,i,url)}/>{/if}
        </div>
      {/each}
    {/if}
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
 .manga-name{display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;line-clamp:2;height:2.7em;margin-top:10px;overflow:hidden;overflow-wrap:anywhere;line-height:1.35;font-size:14px}
 svg{width:24px;height:24px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
 .empty{text-align:center;color:#9292a5;padding:40px}.more{display:block;margin:24px auto;padding:8px 12px}
 .scrim{position:fixed;inset:0;z-index:110;display:grid;place-items:center;background:#000b;padding:24px}
 .chapter-dialog{position:relative;display:grid;grid-template-columns:minmax(0,230px) minmax(0,1fr);gap:32px;width:min(720px,100%);max-height:80dvh;padding:88px 32px 32px;background:#19191f;border-radius:14px;color:#eee}
 .chapter-cover{aspect-ratio:2/3;background:#24242d;border-radius:6px;overflow:hidden;align-self:start}
 .chapter-cover img{width:100%;height:100%;object-fit:cover}
 .chapter-list{overflow:auto;min-height:0}.chapter-list button{display:flex;align-items:center;justify-content:space-between;width:100%;text-align:left;padding:16px 12px;border-radius:6px;font-size:14px;gap:16px;overflow-wrap:anywhere}
 .chapter-list button:hover{background:#ffffff0b}.chapter-list span{font-size:23px;color:#888}
 .back{display:grid;place-items:center;flex-shrink:0;width:40px;height:40px;border:0;background:transparent;border-radius:999px;color:#eee;transition:width .18s ease,background-color .18s ease}
 .back:hover,.back:focus-visible{width:56px;background:#33333b}
 .chapter-heading{position:absolute;top:16px;left:16px;right:16px}
 .chapter-heading,.reader-heading{display:flex;align-items:center;gap:8px;min-width:0;padding:6px;border:1px solid #0006;border-radius:16px;background:#0009;backdrop-filter:blur(6px)}
 .series-title{display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;line-clamp:2;min-width:0;overflow:hidden;overflow-wrap:anywhere;margin:0;font-size:14px;font-weight:500;line-height:1.35}
 .reader{--reader-error-top:82px;position:fixed;inset:0;z-index:120;overflow:hidden;overscroll-behavior:contain;background:#080808;color:#eee}
 .reader.vertical{overflow-y:auto}
 .reader-controls{position:fixed;top:16px;left:16px;right:16px;z-index:1;display:grid;grid-template-columns:minmax(0,1fr) auto minmax(0,1fr);align-items:center;gap:12px;pointer-events:none;transition:opacity .18s ease,transform .18s ease}
 .reader-heading{justify-self:start;max-width:100%;pointer-events:auto}
 .page-counter{grid-column:2;min-width:64px;padding:9px 12px;border:1px solid #0006;border-radius:14px;background:#0009;backdrop-filter:blur(6px);text-align:center;white-space:nowrap;font-size:14px;font-variant-numeric:tabular-nums;pointer-events:auto}
 .reader-controls.hidden{opacity:0;transform:translateY(-10px);pointer-events:none}
 .reader-controls.hidden>*{pointer-events:none}
 .reader-controls select{grid-column:3;justify-self:end;min-width:0;max-width:100%;border:1px solid #0006;border-radius:20px;background:#0009;color:#eee;padding:9px 12px;font-size:13px;cursor:pointer;pointer-events:auto}
 .paged-page{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;overflow:hidden}
 .paged-page img{display:block;max-width:100%;max-height:100%;width:auto;height:auto;object-fit:contain;image-orientation:from-image}
 .page{height:100dvh;display:flex;justify-content:center;align-items:center;width:100%;margin:0 auto}
 .page img{width:100%;height:100%;object-fit:contain;image-orientation:from-image}
 .vertical .page{height:auto;width:min(100%,1000px);aspect-ratio:var(--ratio)}
 .reader-error{position:fixed;left:50%;top:var(--reader-error-top);transform:translateX(-50%);max-width:calc(100% - 32px);overflow-wrap:anywhere;background:#26262d;padding:10px 16px;border-radius:8px;z-index:1;font-size:14px}
 .reader-error button{display:block;margin-top:8px;text-decoration:underline}
 .muted{color:#9292a5}.loading{padding:80px 24px}
 button:focus-visible,select:focus-visible,input:focus-visible{outline:2px solid var(--accent);outline-offset:3px}
 :global(html[data-motion='reduced']) .back,:global(html[data-motion='reduced']) .reader-controls{transition:none}
 @media(prefers-reduced-motion:reduce){.back,.reader-controls{transition:none}}
 @media(max-width:560px){.chapter-dialog{grid-template-columns:minmax(0,110px) minmax(0,1fr);gap:16px;padding:88px 16px 16px}.scrim{padding:12px}.manga-grid{grid-template-columns:repeat(auto-fill,minmax(130px,1fr))}.reader{--reader-error-top:128px}.reader-controls{gap:8px}.reader-heading{grid-column:1/-1;grid-row:2;justify-self:stretch}.page-counter,.reader-controls select{grid-row:1}.reader-controls select{padding:9px 8px;font-size:12px}}
</style>
