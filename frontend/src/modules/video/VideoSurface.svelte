<script lang="ts">
  import {onMount, onDestroy, tick} from 'svelte';
  import AppDrawer from '../../components/AppDrawer.svelte';
  import {filesApi} from '../../lib/filesApi';
  import {settingsOpen, settingsInitialSection} from '../../lib/suiteStores';
  import {videoApi, type VideoItem} from './api';
  import MediaPlayer from '../../components/MediaPlayer.svelte';
  let drawer = false;
  let query = '';
  let items: VideoItem[] = [];
  let total = 0;
  let loading = false;
  let error = '';
  let selected: VideoItem | null = null;
  let notice = '';
  let request: AbortController | null = null;
  let debounce: ReturnType<typeof setTimeout>;
  let alive = true;
  let returnFocus: HTMLElement | null = null;
  let navigating = false;
  $: selectedIndex = selected ? items.findIndex(item => item.source_id === selected?.source_id && item.path === selected?.path) : -1;
  $: playback=selected ? {src:filesApi.fileUrl(selected.source_id,selected.path),ext:selected.ext} : null;
  async function load(more = false) {
    request?.abort();
    const current = new AbortController(); request = current;
    loading = true; error = '';
    try {
      const result = await videoApi.library(query, more ? items.length : 0, current.signal);
      if (current.signal.aborted || !alive) return;
      items = more ? [...items, ...result.items] : result.items; total = result.total;
    } catch (caught) {
      if (!current.signal.aborted && alive) error = caught instanceof Error ? caught.message : 'Could not load videos.';
    } finally { if (request === current && alive) loading = false; }
  }
  function search() {
    request?.abort(); clearTimeout(debounce); loading = true;
    debounce = setTimeout(() => void load(), 200);
  }
  function folders() { settingsInitialSection.set('roots'); settingsOpen.set(true); }
  function open(item: VideoItem) {
    if(!selected)returnFocus=document.activeElement as HTMLElement;
    selected=item;notice='';
  }
  async function adjacent(direction: -1 | 1) {
    if (!selected || navigating) return;
    const current = selected;
    const nextIndex = selectedIndex + direction;
    if (nextIndex < 0 || nextIndex >= total) return;
    navigating = true;
    try {
      if (nextIndex >= items.length) await load(true);
      if (alive && selected === current) {
        if (items[nextIndex]) await open(items[nextIndex]);
        else notice = 'Could not load the next video. Try again.';
      }
    } finally { navigating = false; }
  }
  async function close() {
    selected=null;
    await tick();returnFocus?.focus();
  }
  onMount(() => {void load();});
  onDestroy(() => {alive = false; clearTimeout(debounce); request?.abort();});
</script>

<div class="video-surface" inert={!!selected}>
  <header>
    <button aria-label="Open Keivotos menu" title="Open Keivotos menu" on:click={() => drawer = true}>☰</button>
    <span class="module-title">Video</span>
    <input aria-label="Search videos" placeholder="Search videos…" bind:value={query} on:input={search} />
  </header>
  <main>
    {#if error}<p role="alert">{error} <button on:click={() => load()}>Retry</button></p>{/if}
    {#if !loading && !error && !items.length}<p class="empty">{#if query}No videos found.{:else}<button on:click={folders}>Add Video folders in Settings</button>{/if}</p>{/if}
    <div class="video-grid" aria-busy={loading}>
      {#each items as item (`${item.source_id}/${item.path}`)}
        <button class="video-tile" title={item.name} on:click={() => open(item)}>
          <span class="thumbnail"><span aria-hidden="true">▷</span><img loading="lazy" alt="" src={filesApi.thumbnailUrl(item.source_id,item.path,600,`${item.mtime}:${item.size}`)} on:error={event => (event.currentTarget as HTMLImageElement).style.display = 'none'} /></span>
          <span class="video-name">{item.name}</span>
        </button>
      {/each}
    </div>
    {#if items.length < total}<button class="more" disabled={loading} on:click={() => load(true)}>{loading ? 'Loading…' : 'Load more'}</button>{/if}
  </main>
</div>
{#if drawer}<AppDrawer on:close={() => drawer = false} />{/if}
{#if selected && playback}
  <MediaPlayer media={playback}
    hasPrevious={selectedIndex>0} hasNext={selectedIndex>=0&&selectedIndex<total-1}
    {navigating} navigationNotice={notice} onClose={close}
    onPrevious={()=>adjacent(-1)} onNext={()=>adjacent(1)}
    onFailure={(_media,reason)=>videoApi.error(selected!,reason)} />
{/if}

<style>
 .video-surface{display:flex;flex:1;min-height:0;flex-direction:column;background:#0f0f14;color:#e0e0e8}
 header{display:flex;align-items:center;gap:16px;min-height:60px;border-bottom:1px solid #2a2a3a;padding:8px 16px}
 header button{width:36px;height:36px;border-radius:8px;background:#1e1e2e}
 .module-title{font-size:18px;font-weight:600}
 header input{max-width:640px;width:100%;margin-left:auto;margin-right:auto;border:1px solid #2a2a3a;border-radius:8px;padding:8px 12px;background:#1a1a24;font-size:14px}
 main{overflow:auto;flex:1;padding:20px;min-height:0}
 .video-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(260px,100%),1fr));gap:24px 18px}
 .video-tile{text-align:left;min-width:0}
 .thumbnail{display:grid;place-items:center;position:relative;aspect-ratio:16/9;background:#1a1a24;border-radius:10px;overflow:hidden;color:#858599}
 .thumbnail img{position:absolute;width:100%;height:100%;object-fit:cover}
 .video-name{display:block;padding-top:8px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:14px}
 .empty{text-align:center;color:#9292a5;padding:40px}
 .empty button,.more{padding:8px 12px;border:1px solid #303040;border-radius:8px}
 .more{display:block;margin:24px auto}
 button:focus-visible,input:focus-visible{outline:2px solid var(--accent);outline-offset:3px}
 button:disabled{opacity:.45}
</style>
