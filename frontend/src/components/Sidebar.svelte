<script lang="ts">
  import { onMount } from 'svelte';
  import { api, type FolderInfo, type TagInfo } from '../lib/api';
  import {
    activeFolder,
    activeFolderLabel,
    activeTags,
    activeRating,
    viewMode,
    activeCollectionId,
    blacklistedTagNames,
    collectionRefreshToken,
    imageRefreshToken,
    ratingSelectionValues,
    tagRefreshToken,
    toggleRatingSelection,
  } from '../lib/stores';
  import type { CollectionInfo } from '../lib/api';

  let folders: FolderInfo[] = [];
  let collections: CollectionInfo[] = [];
  let topTags: Record<string, TagInfo[]> = {};
  let expandedCategories: Record<string, boolean> = { character: true, artist: true };
  let stats = { total_images: 0, total_tags: 0, total_favorites: 0 };

  let favTagSet = new Set<string>();
  let blacklistTags: TagInfo[] = [];
  let newBlacklistTag = '';
  let blacklistBusy = false;

  let relatedTags: Record<string, TagInfo[]> = {};
  let hasActiveSearch = false;
  let unsubscribeActiveTags: (() => void) | null = null;
  let sidebarListSerial = 0;
  let favoriteTagSerial = 0;
  let observedImageRefreshToken = 0;
  let observedCollectionRefreshToken = 0;
  let observedTagRefreshToken = 0;


  const categories = ['character', 'artist', 'copyright', 'general', 'meta'];
  const relatedCategories = ['meta', 'character', 'artist', 'copyright', 'general'];
  const categoryColors: Record<string, string> = {
    artist: 'bg-red-500/20 text-red-300 border-red-500/30',
    character: 'bg-green-500/20 text-green-300 border-green-500/30',
    copyright: 'bg-purple-500/20 text-purple-300 border-purple-500/30',
    general: 'bg-blue-500/20 text-blue-300 border-blue-500/30',
    meta: 'bg-yellow-500/20 text-yellow-300 border-yellow-500/30',
  };
  const categoryLabels: Record<string, string> = {
    meta: 'Metadata',
    character: 'Characters',
    artist: 'Artist',
    copyright: 'Copyright',
    general: 'General',
  };
  const ratingLabels: Record<string, string> = { g: 'General', s: 'Sensitive', q: 'Questionable', e: 'Explicit', u: 'Unrated' };

  async function refreshSidebarLists() {
    const requestId = ++sidebarListSerial;
    const [f, s, c] = await Promise.all([
      api.getFolders(),
      api.getStats(),
      api.getCollections(),
    ]);
    if (requestId !== sidebarListSerial) return;
    folders = f;
    stats = s;
    collections = c;
  }

  async function refreshFavoriteTagState() {
    const requestId = ++favoriteTagSerial;
    const favNames = await api.getFavoriteTagNames();
    if (requestId !== favoriteTagSerial) return;
    favTagSet = new Set(favNames.map(t => `${t.category}:${t.name}`));
  }

  onMount(() => {
    async function loadSidebarData() {
      const [f, s, c] = await Promise.all([
        api.getFolders(),
        api.getStats(),
        api.getCollections(),
      ]);
      folders = f;
      stats = s;
      collections = c;

      for (const cat of categories) {
        const res = await api.getTags({ category: cat, limit: 30, min_count: 5 });
        topTags[cat] = res.tags;
      }
      topTags = topTags;

      await refreshFavoriteTagState();
      await refreshBlacklistTags();

      unsubscribeActiveTags = activeTags.subscribe(async (tags) => {
        if (tags.length > 0) {
          hasActiveSearch = true;
          relatedTags = await api.getRelatedTags(tags);
        } else {
          hasActiveSearch = false;
          relatedTags = {};
        }
      });
    }

    loadSidebarData().catch(console.error);

    return () => {
      unsubscribeActiveTags?.();
    };
  });

  $: if ($imageRefreshToken !== observedImageRefreshToken || $collectionRefreshToken !== observedCollectionRefreshToken) {
    observedImageRefreshToken = $imageRefreshToken;
    observedCollectionRefreshToken = $collectionRefreshToken;
    refreshSidebarLists().catch(console.error);
  }

  $: if ($tagRefreshToken !== observedTagRefreshToken) {
    observedTagRefreshToken = $tagRefreshToken;
    refreshFavoriteTagState().catch(console.error);
  }

  function toggleTag(tagName: string) {
    activeTags.update(tags => {
      if (tags.includes(tagName)) return tags.filter(t => t !== tagName);
      return [...tags, tagName];
    });
  }

  function selectFolder(selector: string | null, label: string | null = null) {
    activeFolder.set(selector);
    activeFolderLabel.set(label);
    viewMode.set('gallery');
  }

  function openPopularity() {
    activeCollectionId.set(null);
    viewMode.set('popularity');
  }

  function openTimelapse() {
    activeCollectionId.set(null);
    viewMode.set('timelapse');
  }

  function openChallenges() {
    activeCollectionId.set(null);
    viewMode.set('challenges');
  }

  function toggleCategory(cat: string) {
    expandedCategories[cat] = !expandedCategories[cat];
    expandedCategories = expandedCategories;
  }

  function selectRating(r: string | null) {
    if (r === null) {
      activeRating.set(null);
      return;
    }
    activeRating.update(current => toggleRatingSelection(current, r));
  }

  async function toggleFavTag(tagName: string, category: string) {
    const key = `${category}:${tagName}`;
    const res = await api.toggleFavoriteTag(tagName, category);
    const next = new Set(favTagSet);
    if (res.status === 'added') {
      next.add(key);
    } else {
      next.delete(key);
    }
    favTagSet = next;
    tagRefreshToken.update(n => n + 1);
  }

  function normalizeTagInput(value: string) {
    return value.trim().toLowerCase().replace(/\s+/g, '_');
  }

  function knownTagInfo(tagName: string): TagInfo {
    return Object.values(topTags).flat().find(tag => tag.name === tagName)
      ?? Object.values(relatedTags).flat().find(tag => tag.name === tagName)
      ?? blacklistTags.find(tag => tag.name === tagName)
      ?? { name: tagName, category: 'unknown', count: 0 };
  }

  function setBlacklistTagsLocal(items: TagInfo[]) {
    blacklistTags = items;
    blacklistedTagNames.set(items.map(tag => tag.name));
  }

  async function refreshBlacklistTags() {
    blacklistTags = await api.getBlacklistTags();
    blacklistedTagNames.set(blacklistTags.map(tag => tag.name));
  }

  async function addBlacklistTag() {
    const name = normalizeTagInput(newBlacklistTag);
    if (!name || blacklistBusy) return;
    blacklistBusy = true;
    try {
      await api.addBlacklistTag(name);
      newBlacklistTag = '';
      activeTags.update(tags => tags.filter(tag => tag !== name));
      setBlacklistTagsLocal([
        knownTagInfo(name),
        ...blacklistTags.filter(tag => tag.name !== name),
      ]);
    } finally {
      blacklistBusy = false;
    }
  }

  async function removeBlacklistTag(tagName: string) {
    if (blacklistBusy) return;
    blacklistBusy = true;
    try {
      await api.removeBlacklistTag(tagName);
      setBlacklistTagsLocal(blacklistTags.filter(tag => tag.name !== tagName));
    } finally {
      blacklistBusy = false;
    }
  }

  function viewCollection(id: number) {
    activeCollectionId.set(id);
    viewMode.set('collection-detail');
  }
</script>

<aside class="flex h-full min-h-0 w-64 shrink-0 flex-col overflow-y-auto border-r border-[#2a2a3a] bg-[#13131b]">
  <div class="p-3 border-b border-[#2a2a3a]">
    <div class="mb-2 grid grid-cols-2 gap-2 text-sm font-medium">
        <span class="text-gray-300"><strong class="font-semibold text-gray-100">{stats.total_images.toLocaleString()}</strong> images</span>
        <span class="text-gray-300"><strong class="font-semibold text-gray-100">{stats.total_tags.toLocaleString()}</strong> tags</span>
    </div>
    <button
      class="mt-2 flex w-full items-center justify-between rounded-lg border px-2 py-1.5 text-sm transition-colors {$viewMode === 'popularity' ? 'border-cyan-500/40 bg-cyan-600/20 text-cyan-200' : 'border-[#2a2a3a] text-gray-400 hover:bg-[#1e1e2e]'}"
      on:click={openPopularity}
    >
      <span class="flex items-center gap-1.5">
        <svg class="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 19h16M6 17V9m6 8V5m6 12v-6"/>
        </svg>
        Popularity
      </span>
      <span class="text-[10px] text-gray-600">Date</span>
    </button>
    <button
      class="mt-1.5 flex w-full items-center justify-between rounded-lg border px-2 py-1.5 text-sm transition-colors {$viewMode === 'timelapse' ? 'border-purple-500/40 bg-purple-600/20 text-purple-200' : 'border-[#2a2a3a] text-gray-400 hover:bg-[#1e1e2e]'}"
      on:click={openTimelapse}
    >
      <span class="flex items-center gap-1.5">
        <svg class="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 5v14m16-14v14M8 8h8M8 12h8M8 16h8"/>
        </svg>
        Timelapse
      </span>
      <span class="text-[10px] text-gray-600">Created</span>
    </button>
    <button
      class="mt-1.5 flex w-full items-center justify-between rounded-lg border px-2 py-1.5 text-sm transition-colors {$viewMode === 'challenges' ? 'border-pink-500/40 bg-pink-600/20 text-pink-200' : 'border-[#2a2a3a] text-gray-400 hover:bg-[#1e1e2e]'}"
      on:click={openChallenges}
    >
      <span class="flex items-center gap-1.5">
        <svg class="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 3l2.2 4.8 5.2.6-3.8 3.5 1 5.1L12 14.4 7.4 17l1-5.1-3.8-3.5 5.2-.6L12 3z"/>
        </svg>
        Challenges
      </span>
      <span class="text-[10px] text-gray-600">Daily</span>
    </button>
  </div>

  <div class="p-3 border-b border-[#2a2a3a]">
    <div class="text-xs text-gray-500 uppercase tracking-wider mb-2">Folders</div>
    <button
      class="w-full text-left px-2 py-1 text-sm rounded transition-colors {$activeFolder === null ? 'bg-purple-600/20 text-purple-300' : 'text-gray-400 hover:bg-[#1e1e2e]'}"
      on:click={() => selectFolder(null)}
    >All Folders</button>
    {#each folders as folder (folder.selector)}
      <div class="group flex items-center rounded transition-colors {$activeFolder === folder.selector ? 'bg-purple-600/20 text-purple-300' : 'text-gray-400 hover:bg-[#1e1e2e]'}">
        <button
          class="min-w-0 flex-1 px-2 py-1 text-left"
          title={folder.path ?? folder.name}
          on:click={() => selectFolder(folder.selector, folder.path ? `${folder.name} · ${folder.path}` : folder.name)}
        ><span class="block truncate text-sm">{folder.name}</span>{#if folder.path}<span class="block truncate text-[9px] text-gray-600">{folder.path}</span>{/if}</button>
        <span class="text-xs text-gray-600 mr-1">{folder.count}</span>
      </div>
    {/each}
  </div>

  <div class="p-3 border-b border-[#2a2a3a]">
    <div class="text-xs text-gray-500 uppercase tracking-wider mb-2">Rating</div>
    <div class="flex flex-wrap gap-1">
      {#each Object.entries(ratingLabels) as [key, label]}
        <button
          class="px-2 py-0.5 text-xs rounded border transition-colors {ratingSelectionValues($activeRating).includes(key) ? 'bg-purple-600/30 text-purple-300 border-purple-500/40' : 'border-[#2a2a3a] text-gray-400 hover:bg-[#1e1e2e]'}"
          on:click={() => selectRating(key)}
          aria-pressed={ratingSelectionValues($activeRating).includes(key)}
        >{label}</button>
      {/each}
    </div>
  </div>

  <div class="border-b border-[#2a2a3a]">
    <div class="p-3 pb-2">
      <div class="text-xs text-gray-500 uppercase tracking-wider flex items-center gap-1.5 mb-2">
        <svg class="w-3 h-3 text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M18.364 5.636L5.636 18.364M12 3l7 4v5c0 4.5-3 7.5-7 9-4-1.5-7-4.5-7-9V7l7-4z"/>
        </svg>
        Blacklist
      </div>

      <div class="flex gap-1 mb-2">
        <input
          type="text"
          bind:value={newBlacklistTag}
          placeholder="Add tag..."
          class="min-w-0 flex-1 bg-[#1a1a24] border border-[#2a2a3a] rounded px-2 py-1 text-xs text-gray-300 outline-none focus:border-red-500/50"
          on:keydown={(e) => e.key === 'Enter' && addBlacklistTag()}
        />
        <button
          class="px-2 py-1 rounded border border-red-500/30 bg-red-600/20 text-red-300 hover:bg-red-600/30 disabled:opacity-50 transition-colors"
          disabled={blacklistBusy || !newBlacklistTag.trim()}
          on:click={addBlacklistTag}
          title="Add tag to blacklist"
        >
          <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6v12m6-6H6"/>
          </svg>
        </button>
      </div>

      {#if blacklistTags.length > 0}
        <div class="flex flex-wrap gap-1">
          {#each blacklistTags as tag}
            <span class="inline-flex max-w-full items-center rounded border border-red-500/30 bg-red-600/10 text-red-300">
              <span
                class="min-w-0 truncate px-1.5 py-0.5 text-xs"
                title="{tag.name} ({tag.count})"
              >{tag.name.replace(/_/g, ' ')}</span>
              <span class="pr-1 text-[10px] text-red-300/50">{tag.count.toLocaleString()}</span>
              <button
                class="px-1 py-0.5 text-red-300/70 hover:text-red-200"
                on:click={() => removeBlacklistTag(tag.name)}
                title="Remove from blacklist"
              >
                <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
                </svg>
              </button>
            </span>
          {/each}
        </div>
      {/if}
    </div>
  </div>

  {#if hasActiveSearch && Object.keys(relatedTags).length > 0}
    <div class="p-3 pb-2 border-b border-[#2a2a3a]">
      <div class="text-xs text-gray-500 uppercase tracking-wider flex items-center gap-1.5 mb-1">
        <svg class="w-3 h-3 text-cyan-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1"/>
        </svg>
        Related Tags
      </div>
      {#if relatedTags.all?.length}
        <div class="flex flex-wrap gap-1">
          {#each relatedTags.all as tag}
            <span class="inline-flex items-center rounded border transition-colors {$activeTags.includes(tag.name) ? categoryColors[tag.category] : 'border-[#2a2a3a] text-gray-500 hover:bg-[#1e1e2e]'}">
              <button
                class="px-1.5 py-0.5 text-xs"
                on:click={() => toggleTag(tag.name)}
                title="{tag.name} ({tag.count} co-occurrences)"
              >{tag.name.replace(/_/g, ' ')}</button>
              <button
                class="px-0.5 py-0.5 text-[10px] transition-colors {favTagSet.has(tag.category + ':' + tag.name) ? 'text-pink-400 hover:text-pink-300' : 'text-gray-600 hover:text-pink-400'}"
                on:click|stopPropagation={() => toggleFavTag(tag.name, tag.category)}
                title="{favTagSet.has(tag.category + ':' + tag.name) ? 'Unfavorite' : 'Favorite'} tag"
              >{favTagSet.has(tag.category + ':' + tag.name) ? '♥' : '♡'}</button>
            </span>
          {/each}
        </div>
      {/if}
    </div>
    {#each relatedCategories as cat}
      {#if relatedTags[cat]?.length}
        <div class="border-b border-[#2a2a3a]">
          <button
            class="w-full flex items-center justify-between p-3 py-2 text-xs text-gray-500 uppercase tracking-wider hover:bg-[#1e1e2e] transition-colors"
            on:click={() => toggleCategory(cat)}
          >
              <span>{categoryLabels[cat] || cat}</span>
            <div class="flex items-center gap-1">
              <span class="text-[9px] text-gray-600">{relatedTags[cat].length}</span>
              <svg class="w-3 h-3 transition-transform {expandedCategories[cat] ? 'rotate-180' : ''}" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
              </svg>
            </div>
          </button>
          {#if expandedCategories[cat]}
            <div class="px-3 pb-2 flex flex-wrap gap-1">
              {#each relatedTags[cat] as tag}
                  <span class="inline-flex items-center rounded border transition-colors {$activeTags.includes(tag.name) ? categoryColors[tag.category] : 'border-[#2a2a3a] text-gray-500 hover:bg-[#1e1e2e]'}">
                  <button
                    class="px-1.5 py-0.5 text-xs"
                    on:click={() => toggleTag(tag.name)}
                    title="{tag.name} ({tag.count} co-occurrences)"
                  >{tag.name.replace(/_/g, ' ')}</button>
                  <button
                    class="px-0.5 py-0.5 text-[10px] transition-colors {favTagSet.has(tag.category + ':' + tag.name) ? 'text-pink-400 hover:text-pink-300' : 'text-gray-600 hover:text-pink-400'}"
                    on:click|stopPropagation={() => toggleFavTag(tag.name, tag.category)}
                    title="{favTagSet.has(tag.category + ':' + tag.name) ? 'Unfavorite' : 'Favorite'} tag"
                  >{favTagSet.has(tag.category + ':' + tag.name) ? '♥' : '♡'}</button>
                </span>
              {/each}
            </div>
          {/if}
        </div>
      {/if}
    {/each}
  {:else}
    {#each categories as cat}
      <div class="border-b border-[#2a2a3a]">
        <button
          class="w-full flex items-center justify-between p-3 text-xs text-gray-500 uppercase tracking-wider hover:bg-[#1e1e2e] transition-colors"
          on:click={() => toggleCategory(cat)}
        >
          <span>{cat}</span>
          <svg class="w-3 h-3 transition-transform {expandedCategories[cat] ? 'rotate-180' : ''}" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
          </svg>
        </button>
        {#if expandedCategories[cat] && topTags[cat]}
          <div class="px-3 pb-2 flex flex-wrap gap-1">
            {#each topTags[cat] as tag}
              <span class="inline-flex items-center rounded border transition-colors {$activeTags.includes(tag.name) ? categoryColors[cat] : 'border-[#2a2a3a] text-gray-500 hover:bg-[#1e1e2e]'}">
                <button
                  class="px-1.5 py-0.5 text-xs"
                  on:click={() => toggleTag(tag.name)}
                  title="{tag.name} ({tag.count})"
                >{tag.name.replace(/_/g, ' ')}</button>
                <button
                  class="px-0.5 py-0.5 text-[10px] transition-colors {favTagSet.has(cat + ':' + tag.name) ? 'text-pink-400 hover:text-pink-300' : 'text-gray-600 hover:text-pink-400'}"
                  on:click|stopPropagation={() => toggleFavTag(tag.name, tag.category)}
                  title="{favTagSet.has(cat + ':' + tag.name) ? 'Unfavorite' : 'Favorite'} tag"
                >{favTagSet.has(cat + ':' + tag.name) ? '♥' : '♡'}</button>
              </span>
            {/each}
          </div>
        {/if}
      </div>
    {/each}
  {/if}

  {#if collections.length > 0}
    <div class="p-3 border-b border-[#2a2a3a]">
      <div class="text-xs text-gray-500 uppercase tracking-wider mb-2">Collections</div>
      {#each collections as col}
        <button
          class="w-full text-left px-2 py-1 text-sm rounded transition-colors flex justify-between {$activeCollectionId === col.id ? 'bg-purple-600/20 text-purple-300' : 'text-gray-400 hover:bg-[#1e1e2e]'}"
          on:click={() => viewCollection(col.id)}
        >
          <span class="truncate">{col.name}</span>
          <span class="text-xs text-gray-600 ml-1">{col.image_count}</span>
        </button>
      {/each}
    </div>
  {/if}

</aside>
