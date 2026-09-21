<script lang="ts">
  import {onMount, onDestroy, tick} from 'svelte';
  import AppDrawer from '../../components/AppDrawer.svelte';
  import {filesApi} from '../../lib/filesApi';
  import {settingsOpen, settingsInitialSection} from '../../lib/suiteStores';
  import {videoApi, type VideoItem, type PlaybackFailure} from './api';
  let drawer = false;
  let query = '';
  let items: VideoItem[] = [];
  let total = 0;
  let loading = false;
  let error = '';
  let selected: VideoItem | null = null;
  let player: HTMLVideoElement;
  let viewer: HTMLDivElement;
  let playing = false;
  let position = 0;
  let duration = 0;
  let failure = '';
  let reported = new Set<PlaybackFailure>();
  let notice = '';
  let request: AbortController | null = null;
  let debounce: ReturnType<typeof setTimeout>;
  let alive = true;
  let returnFocus: HTMLElement | null = null;
  let navigating = false;
  $: selectedIndex = selected ? items.findIndex(item => item.source_id === selected?.source_id && item.path === selected?.path) : -1;
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
  async function report(reason: PlaybackFailure) {
    if (!selected || reported.has(reason)) return;
    reported.add(reason);
    const item = selected;
    try {await videoApi.error(item, reason);}
    catch { if (alive && selected === item) failure += ' Could not write to Logs.'; }
  }
  function mediaError() {
    if (!selected || !player?.error || player.error.code === 1) return;
    failure = 'This video cannot play here. See Logs.';
    void report(player.error.code === 2 ? 'network' : player.error.code === 3 ? 'decode' : 'unsupported_codec');
  }
  async function open(item: VideoItem) {
    if (!selected) returnFocus = document.activeElement as HTMLElement;
    player?.pause();
    selected = item; playing = false; position = 0; duration = 0; failure = ''; notice = ''; reported = new Set();
    await tick(); viewer?.focus();
    if (!['mp4','m4v','webm'].includes(item.ext)) {
      failure = 'This format cannot play here. See Logs.'; void report('unsupported_format'); return;
    }
    try {await player.play();}
    catch (caught) {
      // A browser autoplay policy is not a broken file: Play remains available.
      if (caught instanceof DOMException && (caught.name === 'NotAllowedError' || caught.name === 'AbortError')) return;
      if (selected !== item) return;
      failure = 'This video cannot play here. See Logs.'; void report('playback');
    }
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
  async function togglePlay() {
    if (!player || failure) return;
    if (!player.paused) player.pause();
    else try {await player.play();} catch {failure = 'Could not play this video. See Logs.'; void report('playback');}
  }
  async function fullscreen() {
    try {if (document.fullscreenElement) await document.exitFullscreen(); else await viewer.requestFullscreen();}
    catch {notice = 'Fullscreen is unavailable. See Logs.'; void report('fullscreen');}
  }
  async function close() {
    player?.pause();
    if (document.fullscreenElement === viewer) await document.exitFullscreen().catch(() => {});
    selected = null;
    await tick(); returnFocus?.focus();
  }
  function playerKeys(event: KeyboardEvent) {
    if (event.key === 'Escape' && !document.fullscreenElement) {void close(); return;}
    if (event.key !== 'Tab') return;
    const controls = [...viewer.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled)')];
    const first = controls[0], last = controls[controls.length - 1];
    if (event.shiftKey && (document.activeElement === first || document.activeElement === viewer)) {event.preventDefault(); last?.focus();}
    else if (!event.shiftKey && document.activeElement === last) {event.preventDefault(); first?.focus();}
  }
  function seek(event: Event) {
    if (player && Number.isFinite(duration)) player.currentTime = Number((event.currentTarget as HTMLInputElement).value);
  }
  onMount(() => {void load();});
  onDestroy(() => {alive = false; clearTimeout(debounce); request?.abort(); player?.pause();});
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
{#if selected}
  <!-- svelte-ignore a11y_no_noninteractive_tabindex a11y_no_noninteractive_element_interactions -->
  <div class="video-viewer" bind:this={viewer} role="dialog" aria-modal="true" aria-label="Video player" tabindex="-1" on:keydown={playerKeys}>
    {#key selected.source_id + selected.path}
      <!-- svelte-ignore a11y_media_has_caption -->
      <video bind:this={player} src={['mp4','m4v','webm'].includes(selected.ext) ? filesApi.fileUrl(selected.source_id,selected.path) : undefined} playsinline preload="metadata" on:error={mediaError} on:play={() => playing = true} on:pause={() => playing = false} on:ended={() => playing = false} on:timeupdate={() => position = player.currentTime} on:durationchange={() => duration = Number.isFinite(player.duration) ? player.duration : 0}></video>
    {/key}
    <button class="back" aria-label="Back to videos" on:click={close}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m14 5-7 7 7 7" /></svg></button>
    {#if failure || notice}<p class="playback-error" role="alert">{failure || notice}</p>{/if}
    <div class="player-controls">
      <input aria-label="Seek" type="range" min="0" max={duration || 0} step="0.1" value={position} style={`--progress:${duration ? position / duration * 100 : 0}%`} disabled={!duration || !!failure} on:input={seek} />
      <div class="control-row">
        <button aria-label="Previous video" disabled={navigating || selectedIndex <= 0} on:click={() => adjacent(-1)}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 5v14M19 5 8 12l11 7Z" /></svg></button>
        <button aria-label={playing ? 'Pause' : 'Play'} disabled={!!failure} on:click={togglePlay}><svg viewBox="0 0 24 24" aria-hidden="true">{#if playing}<path d="M8 5v14M16 5v14" />{:else}<path d="m7 4 13 8-13 8Z" />{/if}</svg></button>
        <button aria-label="Next video" disabled={navigating || selectedIndex < 0 || selectedIndex >= total - 1} on:click={() => adjacent(1)}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 5v14M5 5l11 7-11 7Z" /></svg></button>
        <button class="fullscreen" aria-label="Fullscreen" on:click={fullscreen}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 4H4v5m11-5h5v5M4 15v5h5m11-5v5h-5" /></svg></button>
      </div>
    </div>
  </div>
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
 .video-viewer{position:fixed;inset:0;z-index:110;background:black;display:grid;place-items:center}
 video{width:100%;height:100%;max-height:100dvh;object-fit:contain}
 .back{position:absolute;top:16px;left:16px;width:40px;height:40px;display:grid;place-items:center;border:0;background:transparent;border-radius:999px;color:#eee;transition:width .18s ease,background-color .18s ease}
 .back:hover,.back:focus-visible{width:56px;background:#33333b}
 .video-viewer svg{width:24px;height:24px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
 .player-controls{position:absolute;bottom:0;left:0;right:0;display:flex;flex-direction:column;gap:8px;background:linear-gradient(transparent,#000b);padding:32px 24px 16px}
 .control-row{display:flex;align-items:center;gap:12px}
 .player-controls button{display:grid;place-items:center;width:40px;height:40px;border:0;background:transparent;color:#eee;border-radius:50%;transition:background-color .15s ease}
 .player-controls button:hover:not(:disabled){background:#ffffff20}
 .fullscreen{margin-left:auto}
 .player-controls input{appearance:none;width:100%;height:20px;margin:0;padding:0;border:0;border-radius:0;background:transparent;cursor:pointer}
 .player-controls input::-webkit-slider-runnable-track{height:3px;border:0;background:linear-gradient(to right,var(--accent) var(--progress),#ffffff55 var(--progress))}
 .player-controls input::-moz-range-track{height:3px;border:0;background:linear-gradient(to right,var(--accent) var(--progress),#ffffff55 var(--progress))}
 .player-controls input::-webkit-slider-thumb{appearance:none;width:11px;height:11px;margin-top:-4px;border:0;border-radius:50%;background:var(--accent)}
 .player-controls input::-moz-range-thumb{width:11px;height:11px;border:0;border-radius:50%;background:var(--accent)}
 :global(html[data-motion='reduced']) .back,:global(html[data-motion='reduced']) .player-controls button{transition:none}
 @media(prefers-reduced-motion:reduce){.back,.player-controls button{transition:none}}
 .playback-error{position:absolute;color:#e5e5eb;background:#171720;padding:12px 18px;border-radius:8px}
 button:focus-visible,input:focus-visible{outline:2px solid var(--accent);outline-offset:3px}
 button:disabled{opacity:.45}
</style>
