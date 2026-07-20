<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { api, imageFileUrl, thumbnailUrl, type ImageSummary } from '../lib/api';
  import {
    activeFolder,
    activeRating,
    blacklistedTagNames,
    duplicateScope,
    duplicatesOnly,
    imageRefreshToken,
    mediaPlayback,
    selectedImageId,
    viewMode,
    visibleImageIds,
  } from '../lib/stores';
  import HomeBreadcrumbBack from './HomeBreadcrumbBack.svelte';

  const SIMPLE_BATCH_SIZE = 80;
  const SIMPLE_INTERVAL_MS = 4500;
  const ADVANCED_INTERVAL_MS = 450;

  let advancedMode = false;
  let simpleFrames: ImageSummary[] = [];
  let simpleIndex = 0;
  let simpleTotal = 0;
  let simpleLoading = false;
  let simpleError = '';
  let simplePlaying = true;
  let simpleKey = '';
  let simpleRefreshToken = 0;
  let simpleRequestSerial = 0;
  let simpleTimer: ReturnType<typeof setInterval> | null = null;
  let simplePreviewVideo: HTMLVideoElement | null = null;
  let simpleFrame: ImageSummary | null = null;
  let simpleExt = '';
  let simpleIsVideo = false;
  let simpleIsGif = false;
  let simplePreviewUrl = '';
  let timelapseRoot: HTMLDivElement | null = null;
  let fullscreen = false;
  let pseudoFullscreen = false;
  let uiHidden = false;
  let showSourceMenu = false;
  let timelapseScope: 'all' | 'tag' = 'all';
  let tagInput = '';
  let activeTimelapseTag = '';

  let frames: ImageSummary[] = [];
  let total = 0;
  let sampled = 0;
  let startDate: string | null = null;
  let endDate: string | null = null;
  let loading = false;
  let error = '';
  let index = 0;
  let playing = false;
  let frameCount = 240;
  let currentKey = '';
  let currentRefreshToken = 0;
  let requestSerial = 0;
  let playTimer: ReturnType<typeof setInterval> | null = null;
  let previewVideo: HTMLVideoElement | null = null;
  let currentFrame: ImageSummary | null = null;
  let currentExt = '';
  let currentIsVideo = false;
  let currentIsGif = false;
  let currentPreviewUrl = '';
  let progressPercent = 0;
  let frameLabel = '0 / 0';
  let advancedIntervalMs = ADVANCED_INTERVAL_MS;
  let advancedSpeed = 1;

  function blacklistParam(tags: string[]) {
    return tags.length ? tags.join(',') : undefined;
  }

  function clearPlayTimer() {
    if (playTimer) {
      clearInterval(playTimer);
      playTimer = null;
    }
  }

  function clearSimpleTimer() {
    if (simpleTimer) {
      clearInterval(simpleTimer);
      simpleTimer = null;
    }
  }

  function seek(nextIndex: number) {
    if (!frames.length) {
      index = 0;
      return;
    }
    index = Math.min(Math.max(0, nextIndex), frames.length - 1);
  }

  function step(delta: number) {
    seek(index + delta);
  }

  function advance(delta: number) {
    if (frames.length <= 1) return;
    const nextIndex = index + delta;
    if (nextIndex >= frames.length) {
      index = 0;
      return;
    }
    index = nextIndex;
  }

  function togglePlay() {
    if (!frames.length) return;
    if (!playing && index >= frames.length - 1) {
      index = 0;
    }
    playing = !playing;
  }

  function openCurrent() {
    if (currentFrame) selectedImageId.set(currentFrame.id);
  }

  function openSimpleCurrent() {
    if (simpleFrame) selectedImageId.set(simpleFrame.id);
  }

  async function toggleFullscreen() {
    if (!timelapseRoot) return;
    const nativeFullscreen = document.fullscreenElement === timelapseRoot;
    try {
      if (nativeFullscreen || pseudoFullscreen) {
        if (nativeFullscreen) await document.exitFullscreen();
        pseudoFullscreen = false;
        fullscreen = false;
        return;
      }

      pseudoFullscreen = false;
      if (typeof timelapseRoot.requestFullscreen === 'function') {
        await timelapseRoot.requestFullscreen();
      }
      fullscreen = document.fullscreenElement === timelapseRoot;
      if (!fullscreen) {
        pseudoFullscreen = true;
        fullscreen = true;
      }
    } catch {
      // Native fullscreen can be denied by embedded browsers. Keep the
      // viewport-filling fallback silent because it is the intended recovery.
      pseudoFullscreen = true;
      fullscreen = true;
    }
  }

  async function goHome() {
    if (document.fullscreenElement === timelapseRoot) {
      try {
        await document.exitFullscreen();
      } catch {
        // Navigating home should still work if the host denies fullscreen exit.
      }
    }
    pseudoFullscreen = false;
    fullscreen = false;
    viewMode.set('home');
  }

  function normalizeTimelapseTag(value: string) {
    return value.trim().toLowerCase().replace(/\s+/g, '_');
  }

  function useAllImages() {
    timelapseScope = 'all';
    tagInput = '';
    activeTimelapseTag = '';
    showSourceMenu = false;
  }

  function applyTagScope() {
    const normalized = normalizeTimelapseTag(tagInput);
    if (!normalized) return;
    timelapseScope = 'tag';
    activeTimelapseTag = normalized;
    tagInput = normalized;
    showSourceMenu = false;
  }

  function speedLabel(value: number) {
    return `${value.toFixed(2).replace(/\.?0+$/, '')}x`;
  }

  function handleWindowKeydown(event: KeyboardEvent) {
    if (event.key === 'Escape' && pseudoFullscreen) {
      pseudoFullscreen = false;
      fullscreen = false;
    }
  }

  function showAdvanced() {
    simplePlaying = false;
    showSourceMenu = false;
    advancedMode = true;
  }

  function showSimple() {
    playing = false;
    showSourceMenu = false;
    advancedMode = false;
    simplePlaying = true;
  }

  async function loadSimpleFrames(options: { showLoader?: boolean } = {}) {
    const { showLoader = true } = options;
    const requestId = ++simpleRequestSerial;
    const shouldClearLoader = showLoader || simpleLoading;
    if (showLoader) {
      simpleLoading = true;
      simpleError = '';
    }

    try {
      const result = await api.getImages({
        q: timelapseQuery || undefined,
        folder: $activeFolder || undefined,
        rating: $activeRating || undefined,
        sort: 'random',
        order: 'desc',
        blacklist: blacklistParam($blacklistedTagNames),
        duplicates_only: $duplicatesOnly,
        duplicate_scope: $duplicatesOnly ? $duplicateScope : undefined,
        limit: SIMPLE_BATCH_SIZE,
        offset: 0,
      });

      if (requestId !== simpleRequestSerial) return;
      const currentId = simpleFrame?.id ?? null;
      simpleFrames = result.images;
      simpleTotal = result.total;
      if (showLoader) {
        simpleIndex = 0;
      } else {
        const preservedIndex = currentId === null ? -1 : simpleFrames.findIndex(image => image.id === currentId);
        simpleIndex = preservedIndex >= 0 ? preservedIndex : Math.min(simpleIndex, Math.max(simpleFrames.length - 1, 0));
      }
      visibleImageIds.set(simpleFrames.map(image => image.id));
    } catch (e) {
      if (requestId === simpleRequestSerial) {
        if (showLoader) {
          simpleError = e instanceof Error ? e.message : 'Failed to load random timelapse';
          simpleFrames = [];
          simpleTotal = 0;
          visibleImageIds.set([]);
        } else {
          console.error('Failed to refresh random timelapse:', e);
        }
      }
    } finally {
      if (requestId === simpleRequestSerial) {
        if (shouldClearLoader) simpleLoading = false;
      }
    }
  }

  function advanceSimple() {
    if (simpleLoading || simpleFrames.length === 0) return;
    if (simpleIndex < simpleFrames.length - 1) {
      simpleIndex += 1;
      return;
    }
    loadSimpleFrames();
  }

  function onScrub(event: Event) {
    const target = event.currentTarget as HTMLInputElement;
    seek(Number(target.value));
  }

  function formatDate(value: string | null) {
    if (!value) return 'Unknown date';
    const normalized = value.includes('T') ? value : `${value.replace(' ', 'T')}Z`;
    const date = new Date(normalized);
    if (Number.isNaN(date.getTime())) return value.slice(0, 10);
    return date.toLocaleDateString(undefined, {
      day: '2-digit',
      month: 'short',
      year: 'numeric',
      timeZone: 'UTC',
    });
  }

  function formatRange(startValue: string | null, endValue: string | null) {
    if (!startValue || !endValue) return 'No date range';
    if (startValue.slice(0, 10) === endValue.slice(0, 10)) return formatDate(startValue);
    return `${formatDate(startValue)} .. ${formatDate(endValue)}`;
  }

  async function loadFrames(options: { showLoader?: boolean } = {}) {
    const { showLoader = true } = options;
    const requestId = ++requestSerial;
    const shouldClearLoader = showLoader || loading;
    if (showLoader) {
      loading = true;
      error = '';
      playing = false;
    }

    try {
      const result = await api.getTimelapseFrames({
        q: timelapseQuery || undefined,
        folder: $activeFolder || undefined,
        rating: $activeRating || undefined,
        blacklist: blacklistParam($blacklistedTagNames),
        duplicates_only: $duplicatesOnly,
        duplicate_scope: $duplicatesOnly ? $duplicateScope : undefined,
        frame_count: frameCount,
      });

      if (requestId !== requestSerial) return;
      const currentId = currentFrame?.id ?? null;
      frames = result.images;
      total = result.total;
      sampled = result.sampled;
      startDate = result.start_date;
      endDate = result.end_date;
      if (showLoader) {
        index = 0;
      } else {
        const preservedIndex = currentId === null ? -1 : frames.findIndex(image => image.id === currentId);
        index = preservedIndex >= 0 ? preservedIndex : Math.min(index, Math.max(frames.length - 1, 0));
      }
      visibleImageIds.set(frames.map(image => image.id));
    } catch (e) {
      if (requestId === requestSerial) {
        if (showLoader) {
          error = e instanceof Error ? e.message : 'Failed to load timelapse';
          frames = [];
          total = 0;
          sampled = 0;
          startDate = null;
          endDate = null;
          visibleImageIds.set([]);
        } else {
          console.error('Failed to refresh timelapse:', e);
        }
      }
    } finally {
      if (requestId === requestSerial) {
        if (shouldClearLoader) loading = false;
      }
    }
  }

  function reloadIfNeeded(..._deps: unknown[]) {
    if (!advancedMode) return;
    const key = JSON.stringify([
      timelapseScope,
      activeTimelapseTag,
      $activeFolder,
      $activeRating,
      $blacklistedTagNames,
      $duplicatesOnly,
      $duplicateScope,
      frameCount,
    ]);
    const refreshToken = $imageRefreshToken;
    const filterChanged = key !== currentKey;
    const refreshChanged = refreshToken !== currentRefreshToken;
    if (!filterChanged && !refreshChanged) return;
    currentKey = key;
    currentRefreshToken = refreshToken;
    loadFrames({ showLoader: filterChanged });
  }

  function reloadSimpleIfNeeded(..._deps: unknown[]) {
    if (advancedMode) return;
    const key = JSON.stringify([
      timelapseScope,
      activeTimelapseTag,
      $activeFolder,
      $activeRating,
      $blacklistedTagNames,
      $duplicatesOnly,
      $duplicateScope,
    ]);
    const refreshToken = $imageRefreshToken;
    const filterChanged = key !== simpleKey;
    const refreshChanged = refreshToken !== simpleRefreshToken;
    if (!filterChanged && !refreshChanged) return;
    simpleKey = key;
    simpleRefreshToken = refreshToken;
    loadSimpleFrames({ showLoader: filterChanged });
  }

  onMount(() => {
    const updateFullscreen = () => {
      fullscreen = document.fullscreenElement === timelapseRoot || pseudoFullscreen;
    };
    document.addEventListener('fullscreenchange', updateFullscreen);
    updateFullscreen();

    return () => {
      document.removeEventListener('fullscreenchange', updateFullscreen);
    };
  });

  onDestroy(() => {
    clearSimpleTimer();
    clearPlayTimer();
    visibleImageIds.set([]);
  });

  $: simpleFrame = simpleFrames[simpleIndex] ?? null;
  $: simpleExt = simpleFrame?.ext?.toLowerCase() ?? '';
  $: simpleIsVideo = simpleExt === 'mp4' || simpleExt === 'webm';
  $: simpleIsGif = simpleExt === 'gif';
  $: simplePreviewUrl = simpleFrame
    ? (simpleIsVideo || (simpleIsGif && ($mediaPlayback === 'always' || simplePlaying))
      ? imageFileUrl(simpleFrame.file_id, simpleFrame.thumbnail_token)
      : thumbnailUrl(simpleFrame.file_id, 1200, simpleFrame.thumbnail_token))
    : '';
  $: if (simplePreviewVideo) {
    if (simpleIsVideo) {
      simplePreviewVideo.play().catch(() => undefined);
    } else {
      simplePreviewVideo.pause();
    }
  }
  $: {
    clearSimpleTimer();
    if (!advancedMode && simplePlaying && simpleFrames.length > 0) {
      simpleTimer = setInterval(advanceSimple, SIMPLE_INTERVAL_MS);
    }
  }

  $: currentFrame = frames[index] ?? null;
  $: currentExt = currentFrame?.ext?.toLowerCase() ?? '';
  $: currentIsVideo = currentExt === 'mp4' || currentExt === 'webm';
  $: currentIsGif = currentExt === 'gif';
  $: currentPreviewUrl = currentFrame
    ? (currentIsVideo || (currentIsGif && ($mediaPlayback === 'always' || playing))
      ? imageFileUrl(currentFrame.file_id, currentFrame.thumbnail_token)
      : thumbnailUrl(currentFrame.file_id, 1200, currentFrame.thumbnail_token))
    : '';
  $: progressPercent = frames.length > 1 ? (index / (frames.length - 1)) * 100 : 0;
  $: frameLabel = frames.length ? `${(index + 1).toLocaleString()} / ${frames.length.toLocaleString()}` : '0 / 0';
  $: timelapseQuery = timelapseScope === 'tag' ? activeTimelapseTag : '';
  $: advancedIntervalMs = Math.max(100, Math.round(ADVANCED_INTERVAL_MS / advancedSpeed));
  $: if (previewVideo) {
    if (currentIsVideo) {
      previewVideo.play().catch(() => undefined);
    } else {
      previewVideo.pause();
    }
  }
  $: {
    clearPlayTimer();
    if (playing && frames.length > 1) {
      playTimer = setInterval(() => advance(1), advancedIntervalMs);
    }
  }
  $: reloadSimpleIfNeeded(advancedMode, timelapseScope, activeTimelapseTag, $activeFolder, $activeRating, $blacklistedTagNames, $duplicatesOnly, $duplicateScope, $imageRefreshToken);
  $: reloadIfNeeded(advancedMode, timelapseScope, activeTimelapseTag, $activeFolder, $activeRating, $blacklistedTagNames, $duplicatesOnly, $duplicateScope, frameCount, $imageRefreshToken);
</script>

<svelte:window on:keydown={handleWindowKeydown} />

{#snippet timelapseSourceMenu()}
  <div class="w-72 rounded-xl border border-white/10 bg-[#101017]/95 p-3 text-left shadow-2xl shadow-black/50 backdrop-blur">
    <div class="mb-2 text-[10px] font-semibold uppercase tracking-[0.18em] text-gray-500">Timelapse source</div>
    <div class="grid grid-cols-2 overflow-hidden rounded-lg border border-[#303040]">
      <button
        class="px-3 py-2 text-xs transition-colors {timelapseScope === 'all' ? 'bg-purple-600/25 text-purple-100' : 'text-gray-400 hover:bg-white/5'}"
        type="button"
        on:click={useAllImages}
      >All images</button>
      <button
        class="border-l border-[#303040] px-3 py-2 text-xs transition-colors {timelapseScope === 'tag' ? 'bg-purple-600/25 text-purple-100' : 'text-gray-400 hover:bg-white/5'}"
        type="button"
        on:click={() => timelapseScope = 'tag'}
      >One tag</button>
    </div>

    {#if timelapseScope === 'tag'}
      <form class="mt-2 flex gap-2" on:submit|preventDefault={applyTagScope}>
        <input
          class="min-w-0 flex-1 rounded-lg border border-[#303040] bg-black/45 px-2.5 py-2 text-xs text-gray-100 outline-none placeholder:text-gray-600 focus:border-purple-500/60"
          type="text"
          bind:value={tagInput}
          placeholder="e.g. blue archive"
          aria-label="Exclusive timelapse tag"
        />
        <button class="rounded-lg bg-purple-600/25 px-3 text-xs font-semibold text-purple-100 hover:bg-purple-600/35 disabled:opacity-40" type="submit" disabled={!tagInput.trim()}>Apply</button>
      </form>
      <p class="mt-2 text-[10px] leading-relaxed text-gray-600">Only images with this exact local tag are included.</p>
    {/if}
  </div>
{/snippet}

<div bind:this={timelapseRoot} class="timelapse-root relative h-full min-h-0 bg-black {fullscreen ? 'h-screen w-screen' : ''} {pseudoFullscreen ? 'fixed inset-0 z-[100]' : ''}">
{#if !uiHidden}
  <div class="absolute left-3 top-3 z-30"><HomeBreadcrumbBack current="Timelapse" on:back={goHome} /></div>
{/if}
{#if uiHidden}
  <div class="group absolute right-3 top-3 z-50 h-10 w-10">
    <button
      class="grid h-8 w-8 place-items-center rounded-lg border border-white/10 bg-black/45 text-gray-300 opacity-0 shadow transition-all group-hover:opacity-100 hover:bg-black/75 hover:text-purple-200"
      type="button"
      on:click={() => uiHidden = false}
      title="Show timelapse UI"
      aria-label="Show timelapse UI"
    >
      <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7S1 12 1 12z"/><circle cx="12" cy="12" r="3" stroke-width="2"/></svg>
    </button>
  </div>
{/if}
{#if !advancedMode}
  <div class="relative h-full min-h-0 overflow-hidden bg-black">
    {#if !uiHidden}
    <div class="absolute right-3 top-3 z-20 flex items-center gap-2">
      <button
        class="flex h-8 w-8 items-center justify-center rounded-lg border border-white/10 bg-black/35 text-gray-300 opacity-70 shadow transition-colors hover:bg-black/70 hover:text-purple-200 hover:opacity-100 disabled:cursor-not-allowed disabled:opacity-30"
        disabled={simpleFrames.length === 0}
        on:click={() => simplePlaying = !simplePlaying}
        title={simplePlaying ? 'Pause timelapse' : 'Play timelapse'}
      >
        {#if simplePlaying}
          <svg class="h-4 w-4" fill="currentColor" viewBox="0 0 24 24">
            <path d="M6 5h4v14H6V5zm8 0h4v14h-4V5z"/>
          </svg>
        {:else}
          <svg class="h-4 w-4" fill="currentColor" viewBox="0 0 24 24">
            <path d="M8 5v14l11-7z"/>
          </svg>
        {/if}
      </button>

      <button
        class="flex h-8 w-8 items-center justify-center rounded-lg border border-white/10 bg-black/35 text-gray-300 opacity-70 shadow transition-colors hover:bg-black/70 hover:text-purple-200 hover:opacity-100"
        on:click={() => showSourceMenu = !showSourceMenu}
        title={timelapseScope === 'tag' && activeTimelapseTag ? `Tag: ${activeTimelapseTag.replace(/_/g, ' ')}` : 'Timelapse all images or one tag'}
        aria-label="Choose timelapse source"
      >
        <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 5h18M6 12h12m-9 7h6"/></svg>
      </button>

      <button
        class="flex h-8 w-8 items-center justify-center rounded-lg border border-white/10 bg-black/35 text-gray-300 opacity-70 shadow transition-colors hover:bg-black/70 hover:text-purple-200 hover:opacity-100"
        on:click={toggleFullscreen}
        title={fullscreen ? 'Exit fullscreen' : 'Enter fullscreen'}
      >
        {#if fullscreen}
          <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 9H5V5m10 4h4V5M9 15H5v4m10-4h4v4"/>
          </svg>
        {:else}
          <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 9V4h5m11 5V4h-5M4 15v5h5m11-5v5h-5"/>
          </svg>
        {/if}
      </button>

      <button
        class="flex h-8 w-8 items-center justify-center rounded-lg border border-white/10 bg-black/35 text-gray-300 opacity-70 shadow transition-colors hover:bg-black/70 hover:text-purple-200 hover:opacity-100"
        on:click={() => { uiHidden = true; showSourceMenu = false; }}
        title="Hide timelapse UI"
        aria-label="Hide timelapse UI"
      >
        <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 3l18 18M10.6 10.7a2 2 0 002.7 2.7M9.9 4.2A10.8 10.8 0 0112 4c7 0 11 8 11 8a17 17 0 01-2.1 3.2M6.2 6.2C3.6 8 1 12 1 12s4 8 11 8a10 10 0 005-1.3"/></svg>
      </button>

      <button
        class="flex h-8 w-8 items-center justify-center rounded-lg border border-white/10 bg-black/30 text-gray-400 opacity-40 shadow transition-colors hover:bg-black/70 hover:text-purple-200 hover:opacity-100"
        on:click={showAdvanced}
        title="Advanced timelapse"
      >
        <svg class="h-4 w-4" fill="currentColor" viewBox="0 0 24 24">
          <path d="M5 12a2 2 0 114 0 2 2 0 01-4 0zm5 0a2 2 0 114 0 2 2 0 01-4 0zm5 0a2 2 0 114 0 2 2 0 01-4 0z"/>
        </svg>
      </button>
    </div>
    {#if showSourceMenu}
      <div class="absolute right-3 top-14 z-30">{@render timelapseSourceMenu()}</div>
    {/if}
    {/if}

    {#if simpleLoading && !simpleFrame}
      <div class="absolute inset-0 flex items-center justify-center">
        <div class="h-9 w-9 rounded-full border-2 border-purple-500 border-t-transparent animate-spin"></div>
      </div>
    {:else if simpleError}
      <div class="absolute inset-0 flex flex-col items-center justify-center gap-3 px-6 text-center">
        <div class="text-sm text-red-300">{simpleError}</div>
        <button
          class="rounded-lg border border-[#2a2a3a] bg-[#1a1a24] px-3 py-1.5 text-sm text-gray-300 transition-colors hover:bg-[#1e1e2e]"
          on:click={() => loadSimpleFrames()}
        >Retry</button>
      </div>
    {:else if simpleFrame}
      <button
        class="absolute inset-0 flex h-full w-full items-center justify-center bg-black focus:outline-none"
        on:click={openSimpleCurrent}
        title="Open image detail"
      >
        {#if simpleIsVideo}
          <!-- svelte-ignore a11y_media_has_caption -->
          <video
            bind:this={simplePreviewVideo}
            class="h-full w-full object-contain"
            src={simplePreviewUrl}
            muted
            loop
            playsinline
            autoplay
            preload="metadata"
          ></video>
        {:else}
          <img
            class="h-full w-full object-contain"
            src={simplePreviewUrl}
            alt={simpleFrame.filename}
            decoding="async"
          />
        {/if}

      </button>
    {:else}
      <div class="absolute inset-0 flex flex-col items-center justify-center gap-2 text-gray-500">
        <svg class="h-14 w-14" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1" d="M4 4v16m16-16v16M8 8h8M8 12h8M8 16h8"/>
        </svg>
        <div class="text-sm">No timelapse images</div>
      </div>
    {/if}
</div>
{:else}
<div class="relative h-full min-h-0 overflow-hidden bg-black">
  {#if !uiHidden}
  <div class="absolute right-3 top-3 z-20 flex items-center gap-2">
    <button
      class="flex h-8 w-8 items-center justify-center rounded-lg border border-white/10 bg-black/35 text-gray-300 opacity-80 shadow transition-colors hover:bg-black/70 hover:text-purple-200 disabled:cursor-not-allowed disabled:opacity-30"
      disabled={frames.length === 0 || index === 0}
      on:click={() => step(-1)}
      title="Previous frame"
    >
      <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7"/>
      </svg>
    </button>

    <button
      class="flex h-8 w-8 items-center justify-center rounded-lg border border-white/10 bg-black/35 text-gray-300 opacity-80 shadow transition-colors hover:bg-black/70 hover:text-purple-200 disabled:cursor-not-allowed disabled:opacity-30"
      disabled={frames.length === 0}
      on:click={togglePlay}
      title={playing ? 'Pause timelapse' : 'Play timelapse'}
    >
      {#if playing}
        <svg class="h-4 w-4" fill="currentColor" viewBox="0 0 24 24">
          <path d="M6 5h4v14H6V5zm8 0h4v14h-4V5z"/>
        </svg>
      {:else}
        <svg class="h-4 w-4" fill="currentColor" viewBox="0 0 24 24">
          <path d="M8 5v14l11-7z"/>
        </svg>
      {/if}
    </button>

    <button
      class="flex h-8 w-8 items-center justify-center rounded-lg border border-white/10 bg-black/35 text-gray-300 opacity-80 shadow transition-colors hover:bg-black/70 hover:text-purple-200 disabled:cursor-not-allowed disabled:opacity-30"
      disabled={frames.length === 0 || index >= frames.length - 1}
      on:click={() => step(1)}
      title="Next frame"
    >
      <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/>
      </svg>
    </button>

    <div class="flex h-8 w-28 items-center gap-1.5 rounded-lg border border-white/10 bg-black/35 px-2 text-gray-300 opacity-80 shadow" title="Timelapse speed">
      <input
        class="min-w-0 flex-1 accent-purple-500"
        type="range"
        min="0.25"
        max="3"
        step="0.25"
        value={advancedSpeed}
        aria-label="Timelapse speed"
        on:input={(event) => advancedSpeed = Number((event.currentTarget as HTMLInputElement).value)}
      />
      <span class="w-8 text-right text-[10px] tabular-nums text-purple-100">{speedLabel(advancedSpeed)}</span>
    </div>

    <button
      class="flex h-8 w-8 items-center justify-center rounded-lg border border-white/10 bg-black/35 text-gray-300 opacity-80 shadow transition-colors hover:bg-black/70 hover:text-purple-200"
      on:click={() => showSourceMenu = !showSourceMenu}
      title={timelapseScope === 'tag' && activeTimelapseTag ? `Tag: ${activeTimelapseTag.replace(/_/g, ' ')}` : 'Timelapse all images or one tag'}
      aria-label="Choose timelapse source"
    >
      <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 5h18M6 12h12m-9 7h6"/></svg>
    </button>

    <button
      class="flex h-8 w-8 items-center justify-center rounded-lg border border-white/10 bg-black/35 text-gray-300 opacity-80 shadow transition-colors hover:bg-black/70 hover:text-purple-200"
      on:click={toggleFullscreen}
      title={fullscreen ? 'Exit fullscreen' : 'Enter fullscreen'}
    >
      {#if fullscreen}
        <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 9H5V5m10 4h4V5M9 15H5v4m10-4h4v4"/>
        </svg>
      {:else}
        <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 9V4h5m11 5V4h-5M4 15v5h5m11-5v5h-5"/>
        </svg>
      {/if}
    </button>

    <button
      class="flex h-8 w-8 items-center justify-center rounded-lg border border-white/10 bg-black/35 text-gray-300 opacity-80 shadow transition-colors hover:bg-black/70 hover:text-purple-200"
      on:click={() => { uiHidden = true; showSourceMenu = false; }}
      title="Hide timelapse UI"
      aria-label="Hide timelapse UI"
    >
      <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 3l18 18M10.6 10.7a2 2 0 002.7 2.7M9.9 4.2A10.8 10.8 0 0112 4c7 0 11 8 11 8a17 17 0 01-2.1 3.2M6.2 6.2C3.6 8 1 12 1 12s4 8 11 8a10 10 0 005-1.3"/></svg>
    </button>

    <button
      class="flex h-8 w-8 items-center justify-center rounded-lg border border-white/10 bg-black/35 text-gray-300 opacity-80 shadow transition-colors hover:bg-black/70 hover:text-purple-200"
      on:click={showSimple}
      title="Simple timelapse"
      aria-label="Return to simple timelapse"
    >
      <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7"/></svg>
    </button>
  </div>

  {#if showSourceMenu}
    <div class="absolute right-3 top-14 z-30">{@render timelapseSourceMenu()}</div>
  {/if}
  {/if}

  {#if !uiHidden}
  <div class="pointer-events-none absolute left-1/2 top-3 z-20 flex max-w-[min(520px,calc(100%-17rem))] -translate-x-1/2 flex-col items-center gap-0.5 rounded-lg bg-black/40 px-4 py-2 text-center shadow">
    <div class="text-sm font-medium text-gray-100">
      {currentFrame ? formatDate(currentFrame.created_at) : 'Created timeline'}
    </div>
    <div class="max-w-full truncate text-xs text-gray-400">
      {#if loading}
        Loading created-date frames
      {:else if frames.length}
        {formatRange(startDate, endDate)} · {sampled.toLocaleString()} frames from {total.toLocaleString()} images
      {:else}
        No created-date frames
      {/if}
    </div>
  </div>
  {/if}

  <button
    class="absolute inset-0 flex h-full w-full items-center justify-center bg-black text-left focus:outline-none"
    disabled={!currentFrame}
    on:click={openCurrent}
    title="Open image detail"
  >
    {#if loading}
      <div class="absolute inset-0 flex items-center justify-center">
        <div class="h-9 w-9 rounded-full border-2 border-purple-500 border-t-transparent animate-spin"></div>
      </div>
    {:else if error}
      <div class="absolute inset-0 flex items-center justify-center px-6 text-center text-sm text-red-300">{error}</div>
    {:else if currentFrame}
      {#if currentIsVideo}
        <!-- svelte-ignore a11y_media_has_caption -->
        <video
          bind:this={previewVideo}
          class="h-full w-full object-contain"
          src={currentPreviewUrl}
          muted
          loop
          playsinline
          autoplay
          preload="metadata"
        ></video>
      {:else}
        <img
          class="h-full w-full object-contain"
          src={currentPreviewUrl}
          alt={currentFrame.filename}
          decoding="async"
        />
      {/if}
    {:else}
      <div class="absolute inset-0 flex flex-col items-center justify-center gap-2 text-gray-500">
        <svg class="h-14 w-14" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1" d="M4 4v16m16-16v16M8 8h8M8 12h8M8 16h8"/>
        </svg>
        <div class="text-sm">No timelapse frames</div>
      </div>
    {/if}
  </button>

  {#if !uiHidden}
  <div class="absolute inset-x-4 bottom-4 z-20 flex items-center gap-3 rounded-lg bg-black/45 px-3 py-2 shadow">
    <span class="w-16 text-right text-xs tabular-nums text-gray-300">{frameLabel}</span>
    <input
      class="h-2 min-w-0 flex-1 accent-purple-500"
      type="range"
      min="0"
      max={Math.max(0, frames.length - 1)}
      value={index}
      disabled={frames.length === 0}
      aria-label="Timelapse frame"
      on:input={onScrub}
    />
    <span class="w-10 text-xs tabular-nums text-gray-400">{Math.round(progressPercent)}%</span>
  </div>
  {/if}
</div>
{/if}
</div>

<style>
  :global(.timelapse-root:fullscreen) {
    width: 100vw;
    height: 100vh;
    background: #000;
  }
</style>
