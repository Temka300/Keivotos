<script lang="ts">
  import { createEventDispatcher } from 'svelte';
  import { activeTags, activeFolder, activeFolderLabel, activeRating, duplicatesOnly, duplicateScope, ratingSelectionValues } from '../lib/stores';

  export let total = 0;
  export let selectMode = false;
  export let selectedCount = 0;

  const dispatch = createEventDispatcher<{ 'toggle-select': void }>();

  function removeTag(tag: string) {
    activeTags.update(t => t.filter(x => x !== tag));
  }

  function removeTagOnMiddleClick(event: MouseEvent, tag: string) {
    if (event.button !== 1) return;
    event.preventDefault();
    removeTag(tag);
  }

  const ratingLabels: Record<string, string> = { g: 'General', s: 'Sensitive', q: 'Questionable', e: 'Explicit', u: 'Unrated' };
  const duplicateLabels = {
    all: 'All duplicates',
    same_folder: 'Duplicates in folder',
    different_folder: 'Duplicates across folders',
  };

  const specialPrefixes = [
    'rating:', 'ext:', 'folder:', 'orientation:', 'width:', 'height:', 'score:', 'w:', 'h:',
    'res:', 'resolution:', 'dim:', 'dims:', 'dimension:', 'dimensions:', 'size:', 'pixels:', 'mp:', 'ratio:', 'user:',
    'id:', 'post:', 'post_id:', 'danbooru:', 'danbooru_id:', 'danbooru_post_id:',
    'shape:', 'aspect:', 'aspect_ratio:', 'preset:',
    'created:', 'created_at:', 'created_date:', 'uploaded:', 'uploaded_at:', 'upload_date:',
  ];
  const shapeTerms = new Set([
    'vertical', 'portrait', 'horizontal', 'landscape', 'wide',
    'phone', 'phones', 'phone_sized', 'phone_size', 'phone_wallpaper', 'phone_wallpapers',
    'mobile', 'mobile_sized', 'mobile_wallpaper',
    'banner', 'banners', 'banner_sized', 'banner_size', 'wide_banner', 'header', 'headers',
    'logo', 'logos', 'logo_sized', 'logo_size', 'icon', 'icons', 'avatar', 'avatars', 'square',
  ]);

  function isFilterTag(tag: string): boolean {
    const normalized = tag.toLowerCase().replace(/[\s-]+/g, '_');
    if (shapeTerms.has(normalized)) return true;
    if (/^-?#\d+$/.test(normalized)) return true;
    if (/^(>=|<=|>|<|=)?\d+[xX\u00d7]\d+$/.test(normalized)) return true;
    return specialPrefixes.some(p => normalized.startsWith(p) || normalized.startsWith('-'));
  }

  const categoryColors: Record<string, string> = {
    filter: 'bg-orange-600/20 text-orange-300 border-orange-500/30',
    exclude: 'bg-red-600/20 text-red-300 border-red-500/30',
    tag: 'bg-blue-600/20 text-blue-300 border-blue-500/30',
  };

  function chipStyle(tag: string): string {
    if (tag.startsWith('-')) return categoryColors.exclude;
    if (isFilterTag(tag)) return categoryColors.filter;
    return categoryColors.tag;
  }

  function selectedRatingLabel(value: string) {
    return ratingSelectionValues(value).map(rating => ratingLabels[rating] || rating).join(' + ');
  }
</script>

<div class="flex items-center gap-2 px-4 py-1.5 bg-[#13131b] border-b border-[#2a2a3a] min-h-[36px] flex-wrap">
  <span class="text-xs text-gray-500 shrink-0">{total.toLocaleString()} results</span>

  {#if $activeFolder}
    <span class="inline-flex items-center gap-1 px-2 py-0.5 text-xs rounded-full bg-purple-600/20 text-purple-300 border border-purple-500/30">
      {$activeFolderLabel ?? $activeFolder}
      <button class="hover:text-white" on:click={() => { activeFolder.set(null); activeFolderLabel.set(null); }}>&times;</button>
    </span>
  {/if}

  {#if $activeRating}
    <span class="inline-flex items-center gap-1 px-2 py-0.5 text-xs rounded-full bg-orange-600/20 text-orange-300 border border-orange-500/30">
      {selectedRatingLabel($activeRating)}
      <button class="hover:text-white" on:click={() => activeRating.set(null)}>&times;</button>
    </span>
  {/if}

  {#if $duplicatesOnly}
    <span class="inline-flex items-center gap-1 px-2 py-0.5 text-xs rounded-full bg-purple-600/20 text-purple-300 border border-purple-500/30">
      {duplicateLabels[$duplicateScope]}
      <button class="hover:text-white" on:click={() => duplicatesOnly.set(false)}>&times;</button>
    </span>
  {/if}

  {#each $activeTags as tag (tag)}
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <span
      class="inline-flex items-center gap-1 px-2 py-0.5 text-xs rounded-full {chipStyle(tag)}"
      title="Middle-click to remove"
      on:auxclick|preventDefault={event => removeTagOnMiddleClick(event, tag)}
    >
      {tag.replace(/_/g, ' ')}
      <button class="hover:text-white" on:click={() => removeTag(tag)}>&times;</button>
    </span>
  {/each}

  <span class="min-w-3 flex-1"></span>

  <button
    class="relative inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border transition-colors {selectMode ? 'border-purple-500/50 bg-purple-600/25 text-purple-200' : 'border-[#2a2a3a] bg-[#1e1e2e] text-gray-400 hover:border-purple-500/40 hover:text-purple-300'}"
    title={selectMode ? 'Exit image selection' : 'Select images'}
    aria-label={selectMode ? 'Exit image selection' : 'Select images'}
    aria-pressed={selectMode}
    on:click={() => dispatch('toggle-select')}
  >
    <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-5"/>
      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 5h14v14H5z"/>
    </svg>
    {#if selectedCount > 0}
      <span class="absolute -right-1.5 -top-1.5 min-w-4 rounded-full bg-purple-500 px-1 text-[10px] font-semibold leading-4 text-white shadow">
        {selectedCount}
      </span>
    {/if}
  </button>
</div>
