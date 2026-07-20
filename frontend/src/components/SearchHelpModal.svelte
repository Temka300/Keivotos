<script lang="ts">
  import { createEventDispatcher } from 'svelte';

  const dispatch = createEventDispatcher<{ close: void }>();

  type SearchSection = {
    title: string;
    description: string;
    examples: { query: string; note: string }[];
  };

  const sections: SearchSection[] = [
    {
      title: 'Tags',
      description: 'Use normal Danbooru tag names. Spaces are treated as separate terms.',
      examples: [
        { query: '1girl', note: 'images tagged 1girl' },
        { query: 'blue_archive halo', note: 'must include both tags' },
        { query: '-1girl', note: 'exclude a tag' },
        { query: 'character:aris', note: 'match a category' },
        { query: '-artist:ask', note: 'exclude a category tag' },
        { query: 'user:favorite_pose', note: 'search your own image tags' },
      ],
    },
    {
      title: 'Post IDs',
      description: 'Jump to local images by Danbooru post id.',
      examples: [
        { query: '#8824525', note: 'exact Danbooru post id' },
        { query: 'id:8824525', note: 'same as #id' },
        { query: '-post:8824525', note: 'exclude that post id' },
      ],
    },
    {
      title: 'Filenames',
      description: 'Paste a complete local media filename, or use a filename prefix for a partial match.',
      examples: [
        { query: '__akita_neru_vocaloid_and_1_more_drawn_by_roin__4091acdf2342e502bcaafd87a0f57308.png', note: 'pasted complete filename' },
        { query: 'filename:akita_neru', note: 'filename contains this text' },
        { query: '-file:sample', note: 'exclude filenames containing this text' },
      ],
    },
    {
      title: 'Size And Shape',
      description: 'Filter by exact dimensions, numeric comparisons, orientation, or presets.',
      examples: [
        { query: '2160x3840', note: 'exact width and height' },
        { query: 'res:1920x1080', note: 'exact resolution' },
        { query: 'width:>=2000 height:>=3000', note: 'large images' },
        { query: 'height:<1000', note: 'shorter than 1000px' },
        { query: 'mp:>=8000000', note: 'at least 8 megapixels as pixels' },
        { query: 'ratio:>1.8', note: 'wide aspect ratio' },
        { query: 'phone banner logo vertical horizontal', note: 'shape presets' },
        { query: '-shape:banner', note: 'exclude a shape preset' },
      ],
    },
    {
      title: 'Score, Rating, Files',
      description: 'Filter metadata stored in the local SQLite index.',
      examples: [
        { query: 'score:>=100', note: 'minimum Danbooru score' },
        { query: 'rating:g', note: 'general rating only' },
        { query: 'rating:g,s,q', note: 'combine ratings, matching the sidebar multi-select' },
        { query: 'rating:u', note: 'sidecar-less or otherwise unrated media' },
        { query: 'rating:e', note: 'explicit rating only' },
        { query: 'folder:Danbooru_Holy', note: 'folder name contains text' },
        { query: 'ext:png', note: 'file extension' },
        { query: 'orientation:portrait', note: 'portrait images' },
        { query: 'orientation:square', note: 'square images' },
      ],
    },
    {
      title: 'User Activity',
      description: 'Filter local activity recorded while browsing this library.',
      examples: [
        { query: 'hearts:>0', note: 'images with any heart spam' },
        { query: 'heart_spam:>=10', note: 'images spammed at least ten times' },
        { query: 'hearts:5', note: 'five or more heart taps' },
      ],
    },
    {
      title: 'Dates',
      description: 'Use created/uploaded dates from Danbooru or downloaded dates from the local file index.',
      examples: [
        { query: 'created:2025-12-01', note: 'uploaded on a date' },
        { query: 'uploaded:>=2026-01-01', note: 'uploaded after a date' },
        { query: 'downloaded:2026-03-01..2026-06-01', note: 'local download date range' },
        { query: 'downloaded:today', note: 'downloaded today' },
        { query: 'created:yesterday', note: 'uploaded yesterday' },
      ],
    },
    {
      title: 'Combining',
      description: 'Search terms combine with AND. Negative terms remove matches.',
      examples: [
        { query: '1girl rating:g height:>=1600 -school_uniform', note: 'safe tall images without that tag' },
        { query: 'artist:modare score:>=50 phone', note: 'artist plus score plus shape' },
        { query: 'blue_archive -character:aris downloaded:>=2026-06-01', note: 'tag search with exclusion and date' },
      ],
    },
  ];

  const prefixes = [
    'artist:',
    'character:',
    'copyright:',
    'general:',
    'meta:',
    'user:',
    'rating:',
    'folder:',
    'ext:',
    'id:',
    'post:',
    'filename:',
    'file:',
    'name:',
    'width:',
    'w:',
    'height:',
    'h:',
    'res:',
    'size:',
    'pixels:',
    'mp:',
    'ratio:',
    'score:',
    'hearts:',
    'heart_spam:',
    'orientation:',
    'shape:',
    'created:',
    'uploaded:',
    'downloaded:',
  ];

  function close() {
    dispatch('close');
  }

  function handleKeydown(event: KeyboardEvent) {
    if (event.key === 'Escape') close();
  }
</script>

<svelte:window on:keydown={handleKeydown} />

<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
<div
  class="fixed inset-0 z-[120] flex items-center justify-center bg-black/65 p-4 backdrop-blur-sm"
  on:click={close}
>
  <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
  <div
    class="flex h-[min(820px,calc(100vh-2rem))] w-[min(1120px,calc(100vw-2rem))] flex-col overflow-hidden rounded-xl border border-[#2d2d3c] bg-[#09090d] shadow-2xl shadow-black/60"
    role="dialog"
    aria-modal="true"
    aria-label="Search Help"
    tabindex="-1"
    on:click|stopPropagation
  >
    <header class="flex h-16 shrink-0 items-center justify-between border-b border-[#252532] bg-[#111116] px-5">
      <div class="min-w-0">
        <h2 class="text-2xl font-bold text-gray-100">Search Help</h2>
        <p class="mt-0.5 text-xs text-gray-500">Use these in the top search bar, then press Enter.</p>
      </div>
      <button
        class="grid h-9 w-9 place-items-center rounded-lg border border-[#2b2b3a] bg-[#15151d] text-gray-300 transition-colors hover:border-purple-500/40 hover:text-white"
        type="button"
        on:click={close}
        title="Close search help"
        aria-label="Close search help"
      >
        <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 6l12 12M18 6L6 18" />
        </svg>
      </button>
    </header>

    <main class="min-h-0 flex-1 overflow-y-auto p-5">
      <section class="mb-4 rounded-lg border border-[#252532] bg-[#111118] p-4">
        <div class="mb-3 flex items-center gap-2 text-sm font-semibold text-gray-200">
          <svg class="h-4 w-4 text-purple-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5a6 6 0 104.5 9.9L20 19.5M10 8h4m-2-2v4" />
          </svg>
          Supported prefixes
        </div>
        <div class="flex flex-wrap gap-1.5">
          {#each prefixes as prefix}
            <code class="rounded border border-[#2a2a3a] bg-[#0d0d13] px-2 py-1 text-xs text-purple-200">{prefix}</code>
          {/each}
        </div>
      </section>

      <div class="grid gap-4 lg:grid-cols-2">
        {#each sections as section}
          <section class="rounded-lg border border-[#252532] bg-[#111118]">
            <div class="border-b border-[#222230] px-4 py-3">
              <h3 class="font-semibold text-gray-100">{section.title}</h3>
              <p class="mt-1 text-xs leading-relaxed text-gray-500">{section.description}</p>
            </div>
            <div class="divide-y divide-[#20202d]">
              {#each section.examples as example}
                <div class="grid gap-2 px-4 py-3 sm:grid-cols-[minmax(180px,0.8fr)_1fr] sm:items-center">
                  <code class="min-w-0 overflow-hidden text-ellipsis rounded border border-[#2a2a3a] bg-[#0c0c11] px-2.5 py-1.5 text-sm text-cyan-100">{example.query}</code>
                  <div class="text-xs leading-relaxed text-gray-500">{example.note}</div>
                </div>
              {/each}
            </div>
          </section>
        {/each}
      </div>
    </main>
  </div>
</div>
