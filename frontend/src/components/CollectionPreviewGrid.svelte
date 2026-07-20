<script lang="ts">
  import { imageFileUrl, thumbnailUrl, type CollectionPreviewItem } from '../lib/api';
  import { mediaPlayback } from '../lib/stores';

  export let items: CollectionPreviewItem[] = [];
  export let previewIds: number[] = [];
  export let size = 360;

  let hoveredFileId: number | null = null;

  $: fallbackItems = previewIds.map(fileId => ({
    file_id: fileId,
    thumbnail_token: null,
    filename: null,
    ext: null,
    width: null,
    height: null,
  }));
  $: tiles = (items?.length ? items : fallbackItems).slice(0, 4);
  $: placeholderCount = Math.max(0, 4 - tiles.length);

  function fileExt(item: CollectionPreviewItem) {
    return (item.ext ?? '').replace(/^\./, '').toLowerCase();
  }

  function isGif(item: CollectionPreviewItem) {
    return fileExt(item) === 'gif';
  }

  function isVideo(item: CollectionPreviewItem) {
    const ext = fileExt(item);
    return ext === 'mp4' || ext === 'webm';
  }

  function mediaLabel(item: CollectionPreviewItem) {
    const ext = fileExt(item);
    return ext === 'gif' || ext === 'mp4' || ext === 'webm' ? ext.toUpperCase() : '';
  }

  function shouldPlay(item: CollectionPreviewItem) {
    return $mediaPlayback === 'always' || ($mediaPlayback === 'hover' && hoveredFileId === item.file_id);
  }

  function token(item: CollectionPreviewItem) {
    return item.thumbnail_token ?? undefined;
  }

  function thumbSrc(item: CollectionPreviewItem) {
    return thumbnailUrl(item.file_id, size, token(item));
  }

  function mediaSrc(item: CollectionPreviewItem) {
    return imageFileUrl(item.file_id, token(item));
  }

  function playWhen(node: HTMLVideoElement, play: boolean) {
    function sync(nextPlay: boolean) {
      if (nextPlay) {
        node.play().catch(() => undefined);
      } else {
        node.pause();
        try {
          node.currentTime = 0;
        } catch {
          // Browsers can reject seeking before metadata has loaded.
        }
      }
    }

    sync(play);
    return {
      update: sync,
    };
  }
</script>

<div class="grid h-full w-full grid-cols-2 gap-0.5 bg-[#171723] p-0.5">
  {#each tiles as item (item.file_id)}
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div
      class="relative min-h-0 overflow-hidden bg-[#0d0d13]"
      title={item.filename ?? ''}
      on:mouseenter={() => hoveredFileId = item.file_id}
      on:mouseleave={() => hoveredFileId = null}
    >
      {#if isVideo(item)}
        <!-- svelte-ignore a11y_media_has_caption -->
        <video
          use:playWhen={shouldPlay(item)}
          src={mediaSrc(item)}
          poster={thumbSrc(item)}
          muted
          loop
          playsinline
          autoplay={shouldPlay(item)}
          preload={shouldPlay(item) ? 'auto' : 'metadata'}
          class="h-full w-full object-cover transition-transform duration-300 group-hover:scale-105"
        ></video>
      {:else}
        <img
          src={isGif(item) && shouldPlay(item) ? mediaSrc(item) : thumbSrc(item)}
          alt={item.filename ?? ''}
          class="h-full w-full object-cover transition-transform duration-300 group-hover:scale-105"
          loading="lazy"
          decoding="async"
        />
      {/if}

      {#if mediaLabel(item) && $mediaPlayback !== 'always' && !shouldPlay(item)}
        <div class="pointer-events-none absolute inset-0 flex items-center justify-center bg-black/15">
          <span class="flex items-center gap-1 rounded bg-black/65 px-1.5 py-0.5 text-[10px] font-semibold text-gray-100 shadow">
            <svg class="h-3 w-3" fill="currentColor" viewBox="0 0 24 24">
              <path d="M8 5v14l11-7z"/>
            </svg>
            {mediaLabel(item)}
          </span>
        </div>
      {/if}
    </div>
  {/each}

  {#each Array(placeholderCount) as _}
    <div class="bg-[#0d0d13]"></div>
  {/each}
</div>
