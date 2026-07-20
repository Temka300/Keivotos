<script lang="ts">
  import { createEventDispatcher } from 'svelte';
  import type { ImageSummary } from '../lib/api';
  import { imageFileUrl, thumbnailUrl } from '../lib/api';
  import { fitMode, imageSize, imageSizeByValue, mediaPlayback } from '../lib/stores';

  export let image: ImageSummary;
  export let selectMode = false;
  export let selected = false;
  export let collectionCount = 0;
  export let pinMode: 'none' | 'favorite' | 'collection' = 'none';
  export let pinBusy = false;

  const dispatch = createEventDispatcher();

  let loaded = false;
  let errored = false;
  let hovered = false;
  let previewVideo: HTMLVideoElement | null = null;
  let longPressTimer: number | null = null;
  let longPressTriggered = false;

  const ratingColors: Record<string, string> = {
    g: 'bg-green-600', s: 'bg-yellow-600', q: 'bg-orange-600', e: 'bg-red-600', u: 'bg-slate-600',
  };

  function formatFavoriteDate(value: string) {
    const date = new Date(value.includes('T') ? value : `${value.replace(' ', 'T')}Z`);
    return date.toLocaleDateString();
  }

  $: selectedSize = imageSizeByValue[$imageSize];
  $: imageAspect = image.width && image.height ? image.width / image.height : 1;
  $: containMaxHeight = selectedSize.maxHeight;
  $: containMaxWidth = selectedSize.maxHeight * 2.2;
  $: containWidth = imageAspect >= 1
    ? Math.min(containMaxHeight * imageAspect, containMaxWidth)
    : containMaxHeight * imageAspect;
  $: containHeight = imageAspect >= 1 ? containWidth / imageAspect : containMaxHeight;
  $: containCardStyle = $fitMode === 'contain'
    ? `width: ${Math.max(24, Math.round(containWidth))}px; height: ${Math.max(24, Math.round(containHeight))}px; max-width: 100%;`
    : '';
  $: fileExt = image.ext?.toLowerCase() ?? '';
  $: isGif = fileExt === 'gif';
  $: isVideo = fileExt === 'mp4' || fileExt === 'webm';
  $: shouldPlayMedia = $mediaPlayback === 'always' || ($mediaPlayback === 'hover' && hovered);
  $: mediaUrl = imageFileUrl(image.file_id, image.thumbnail_token);
  $: thumbUrl = thumbnailUrl(image.file_id, selectedSize.previewSize, image.thumbnail_token);
  $: previewUrl = (isVideo || (isGif && shouldPlayMedia)) ? mediaUrl : thumbUrl;
  $: mediaLabel = isVideo || isGif ? fileExt.toUpperCase() : '';
  $: pinnedAt = pinMode === 'favorite' ? image.favorite_pinned_at : image.collection_pinned_at;
  $: showPinControl = pinMode !== 'none' && !selectMode;

  $: if (previewUrl) {
    loaded = false;
    errored = false;
  }

  $: if (previewVideo) {
    if (shouldPlayMedia) {
      previewVideo.play().catch(() => undefined);
    } else {
      previewVideo.pause();
      try {
        previewVideo.currentTime = 0;
      } catch {
        // Some browsers reject seeking before metadata is available.
      }
    }
  }

  function clearLongPressTimer() {
    if (longPressTimer !== null) {
      window.clearTimeout(longPressTimer);
      longPressTimer = null;
    }
  }

  function onPointerDown(event: PointerEvent) {
    if (selectMode || event.button !== 0) return;
    longPressTriggered = false;
    clearLongPressTimer();
    longPressTimer = window.setTimeout(() => {
      longPressTriggered = true;
      dispatch('longselect', image.id);
    }, 450);
  }

  function onPointerEnd() {
    clearLongPressTimer();
  }

  function onCardClick() {
    if (longPressTriggered) {
      longPressTriggered = false;
      return;
    }
    dispatch('select', image.id);
  }

  function onPinClick(event: MouseEvent) {
    event.stopPropagation();
    if (!pinBusy && pinMode !== 'none') {
      dispatch('pin', { image, mode: pinMode });
    }
  }
</script>

<div
  class="group relative {$fitMode === 'contain' ? 'shrink-0' : ''}"
  style={containCardStyle}
>
<button
  class="group relative block w-full bg-[#1a1a24] rounded-lg overflow-hidden border transition-all duration-200 hover:shadow-lg hover:shadow-purple-900/20 focus:outline-none focus:border-purple-500 {$fitMode === 'contain' ? 'h-full' : ''} {selectMode ? 'cursor-copy hover:border-purple-400/70' : 'cursor-pointer hover:border-purple-500/50'} {selected ? 'border-purple-400 ring-2 ring-purple-500/70 shadow-lg shadow-purple-900/30' : 'border-transparent'}"
  aria-pressed={selectMode ? selected : undefined}
  aria-label={selectMode ? `${selected ? 'Deselect' : 'Select'} ${image.filename}` : image.filename}
  on:mouseenter={() => hovered = true}
  on:mouseleave={() => hovered = false}
  on:pointerdown={onPointerDown}
  on:pointerup={onPointerEnd}
  on:pointerleave={onPointerEnd}
  on:pointercancel={onPointerEnd}
  on:click={onCardClick}
>
  {#if $fitMode === 'contain'}
    <div class="flex h-full w-full items-center justify-center bg-[#1e1e2e]">
      {#if !errored}
        {#if isVideo}
          <!-- svelte-ignore a11y_media_has_caption -->
          <video
            bind:this={previewVideo}
            src={previewUrl}
            muted
            loop
            playsinline
            autoplay={shouldPlayMedia}
            preload={shouldPlayMedia ? 'auto' : 'metadata'}
            class="h-full w-full object-contain transition-transform duration-300 group-hover:scale-105"
            class:opacity-0={!loaded}
            class:opacity-100={loaded}
            on:loadedmetadata={() => loaded = true}
            on:loadeddata={() => loaded = true}
            on:error={() => errored = true}
          ></video>
        {:else}
          <img
            src={previewUrl}
            alt={image.filename}
            loading="lazy"
            decoding="async"
            class="h-full w-full object-contain transition-transform duration-300 group-hover:scale-105"
            class:opacity-0={!loaded}
            class:opacity-100={loaded}
            on:load={() => loaded = true}
            on:error={() => errored = true}
          />
        {/if}
      {:else}
        <div class="flex h-full w-full items-center justify-center text-gray-600 text-xs">
          Failed to load
        </div>
      {/if}
    </div>
  {:else}
    <div class="aspect-[3/4] overflow-hidden bg-[#1e1e2e]">
      {#if !errored}
        {#if isVideo}
          <!-- svelte-ignore a11y_media_has_caption -->
          <video
            bind:this={previewVideo}
            src={previewUrl}
            muted
            loop
            playsinline
            autoplay={shouldPlayMedia}
            preload={shouldPlayMedia ? 'auto' : 'metadata'}
            class="w-full h-full object-cover transition-transform duration-300 group-hover:scale-105"
            class:opacity-0={!loaded}
            class:opacity-100={loaded}
            on:loadedmetadata={() => loaded = true}
            on:loadeddata={() => loaded = true}
            on:error={() => errored = true}
          ></video>
        {:else}
          <img
            src={previewUrl}
            alt={image.filename}
            loading="lazy"
            decoding="async"
            class="w-full h-full object-cover transition-transform duration-300 group-hover:scale-105"
            class:opacity-0={!loaded}
            class:opacity-100={loaded}
            on:load={() => loaded = true}
            on:error={() => errored = true}
          />
        {/if}
      {:else}
        <div class="w-full h-full flex items-center justify-center text-gray-600 text-xs">
          Failed to load
        </div>
      {/if}
    </div>
  {/if}

  <div class="absolute top-1.5 right-1.5 flex gap-1">
    {#if image.rating}
      <span class="px-1.5 py-0.5 text-[10px] font-bold rounded {ratingColors[image.rating] || 'bg-gray-600'} text-white uppercase opacity-80">
        {image.rating}
      </span>
    {/if}
  </div>

  {#if selectMode}
    <div class="absolute top-1.5 left-1.5 z-10">
      <span class="flex h-6 w-6 items-center justify-center rounded-full border shadow {selected ? 'border-purple-300 bg-purple-500 text-white' : 'border-white/50 bg-black/45 text-white/70'}">
        <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M5 13l4 4L19 7"/>
        </svg>
      </span>
    </div>
  {/if}

  {#if selectMode && (image.is_favorite || collectionCount > 0)}
    <div class="absolute top-8 left-1.5 z-10 flex gap-1">
      {#if image.is_favorite}
        <span class="flex h-5 min-w-5 items-center justify-center rounded-full bg-black/60 px-1 text-pink-300 shadow" title="Already favorited">
          <svg class="h-3.5 w-3.5 fill-current" viewBox="0 0 24 24">
            <path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/>
          </svg>
        </span>
      {/if}
      {#if collectionCount > 0}
        <span class="flex h-5 min-w-5 items-center gap-0.5 rounded-full bg-black/60 px-1 text-[10px] font-semibold text-purple-200 shadow" title="Already in {collectionCount} collection{collectionCount === 1 ? '' : 's'}">
          <svg class="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10"/>
          </svg>
          {collectionCount}
        </span>
      {/if}
    </div>
  {:else if image.is_favorite}
    <div class="absolute top-1.5 left-1.5">
      <svg class="w-4 h-4 text-pink-500 fill-current drop-shadow" viewBox="0 0 24 24">
        <path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/>
      </svg>
    </div>
  {/if}

  {#if mediaLabel && $mediaPlayback !== 'always' && !shouldPlayMedia && !errored}
    <div class="pointer-events-none absolute inset-0 flex items-center justify-center">
      <div class="flex items-center gap-1.5 rounded-lg bg-black/55 px-2 py-1 text-[10px] font-semibold text-gray-100 shadow">
        <svg class="h-3.5 w-3.5" fill="currentColor" viewBox="0 0 24 24">
          <path d="M8 5v14l11-7z"/>
        </svg>
        {mediaLabel}
      </div>
    </div>
  {/if}

  <div class="absolute bottom-0 inset-x-0 bg-gradient-to-t from-black/80 to-transparent p-2 pt-6 opacity-0 group-hover:opacity-100 transition-opacity">
    {#if image.favorite_added_at}
      <div class="mb-0.5 truncate text-left text-[10px] font-medium text-pink-300">
        Favorited {formatFavoriteDate(image.favorite_added_at)}
      </div>
    {/if}
    {#if image.collection_added_at}
      <div class="mb-0.5 truncate text-left text-[10px] font-medium text-purple-300">
        Added {formatFavoriteDate(image.collection_added_at)}
      </div>
    {/if}
    <div class="flex justify-between items-end">
      {#if image.score !== null}
        <span class="text-xs text-yellow-400 font-medium">
          ★ {image.score}
        </span>
      {/if}
      {#if image.width && image.height}
        <span class="text-[10px] text-gray-400">
          {image.width}x{image.height}
        </span>
      {/if}
    </div>
  </div>
</button>

{#if showPinControl}
  <button
    type="button"
    class="absolute left-1.5 top-7 z-20 flex h-6 w-6 items-center justify-center rounded-full border shadow transition-all {pinnedAt ? 'border-amber-300/60 bg-amber-500/85 text-[#16110a]' : 'border-white/15 bg-black/55 text-gray-300 opacity-0 hover:border-amber-300/50 hover:text-amber-200 group-hover:opacity-100'} disabled:cursor-not-allowed disabled:opacity-50"
    disabled={pinBusy}
    on:click={onPinClick}
    title="{pinnedAt ? 'Unpin from front' : 'Pin to front'}"
    aria-label="{pinnedAt ? 'Unpin' : 'Pin'} {image.filename}"
  >
    <svg class="h-3.5 w-3.5 {pinnedAt ? 'fill-current' : ''}" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 4l5 5-4 1-4.5 4.5V18L9 20.5 3.5 15 6 12.5h3.5L14 8l1-4z"/>
    </svg>
  </button>
{/if}
</div>
