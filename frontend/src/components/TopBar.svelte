<script lang="ts">
  import { api } from '../lib/api';
  import { MODULE_DISPLAY_NAME, SUITE_NAME } from '../lib/product';
  import { viewMode, sortBy, sortOrder, activeFolder, activeRating, activeTags, activeCollectionId, selectedImageId, fitMode, imageSize, imageSizeOptions, imagePageSize, imagePageSizeOptions, duplicatesOnly, duplicateScope, blacklistedTagNames, searchString, browseTagSelection, artistNotificationsEnabled } from '../lib/stores';
  import type { DuplicateScope, ViewMode } from '../lib/stores';
  import SearchBar from './SearchBar.svelte';
  import ArtistNotifications from './ArtistNotifications.svelte';
  import UserMenu from './UserMenu.svelte';
  import AppDrawer from './AppDrawer.svelte';

  let showFilterMenu = false;
  let showSizeMenu = false;
  let showPageSizeMenu = false;
  let randomBusy = false;
  let showAppMenu = false;

  type SortOption = {
    value: string;
    label: string;
    order?: 'asc' | 'desc';
  };

  function setView(v: ViewMode) {
    if (v === 'gallery' || v === 'tags') {
      browseTagSelection.set(null);
    }
    viewMode.set(v);
    if (v !== 'collection-detail') {
      activeCollectionId.set(null);
    }
  }

  function goHome() {
    setView('home');
    selectedImageId.set(null);
    closeMenu();
  }

  function clearFilters() {
    activeFolder.set(null);
    activeRating.set(null);
    activeTags.set([]);
    browseTagSelection.set(null);
    duplicatesOnly.set(false);
    duplicateScope.set('all');
  }

  function isSortSelected(option: SortOption) {
    return $sortBy === option.value && (!option.order || $sortOrder === option.order);
  }

  function setSortOption(option: SortOption) {
    sortBy.set(option.value);
    if (option.order) {
      sortOrder.set(option.order);
    }
  }

  function setDuplicateFilter(scope: DuplicateScope) {
    if ($duplicatesOnly && $duplicateScope === scope) {
      duplicatesOnly.set(false);
      return;
    }
    duplicateScope.set(scope);
    duplicatesOnly.set(true);
  }

  function toggleSearchTerm(term: string) {
    activeTags.update(tags =>
      tags.includes(term)
        ? tags.filter(tag => tag !== term)
        : [...tags, term]
    );
  }

  function closeMenu() {
    showFilterMenu = false;
    showSizeMenu = false;
    showPageSizeMenu = false;
  }

  function toggleFilterMenu() {
    showFilterMenu = !showFilterMenu;
    showSizeMenu = false;
    showPageSizeMenu = false;
  }

  function toggleSizeMenu() {
    showSizeMenu = !showSizeMenu;
    showFilterMenu = false;
    showPageSizeMenu = false;
  }

  function togglePageSizeMenu() {
    showPageSizeMenu = !showPageSizeMenu;
    showSizeMenu = false;
    showFilterMenu = false;
  }

  const sortOptions: SortOption[] = [
    { value: 'date', label: 'Date' },
    { value: 'downloaded', label: 'Downloaded' },
    { value: 'score', label: 'Score' },
    { value: 'views', label: 'Viewed' },
    { value: 'tags', label: 'Most tagged' },
    { value: 'random', label: 'Random' },
    { value: 'name', label: 'Name' },
    { value: 'size', label: 'Size' },
  ];

  const duplicateOptions: { value: DuplicateScope; label: string }[] = [
    { value: 'all', label: 'All duplicates' },
    { value: 'same_folder', label: 'Same folder' },
    { value: 'different_folder', label: 'Different folders' },
  ];

  const shapeOptions = [
    { value: 'phone', label: 'Phone', hint: '9:16 / 2160x3840' },
    { value: 'vertical', label: 'Vertical', hint: 'taller than wide' },
    { value: 'horizontal', label: 'Horizontal', hint: 'wider than tall' },
    { value: 'banner', label: 'Banner', hint: 'very wide' },
    { value: 'logo', label: 'Logo', hint: 'near square' },
  ];

  function blacklistParam(tags: string[]) {
    return tags.length ? tags.join(',') : undefined;
  }

  async function useRandom() {
    if (randomBusy) return;
    randomBusy = true;
    closeMenu();

    try {
      if ($viewMode === 'tags') {
        const tag = await api.getRandomTag({ min_count: 1 });
        browseTagSelection.set({
          name: tag.name,
          category: tag.category,
          count: tag.count,
          source: 'danbooru',
        });
        viewMode.set('tags');
        return;
      }

      const inImageGrid = $viewMode === 'gallery' || $viewMode === 'favorites' || $viewMode === 'collection-detail' || $viewMode === 'popularity' || $viewMode === 'timelapse';
      const result = await api.getRandomImage({
        q: inImageGrid ? ($searchString || undefined) : undefined,
        folder: inImageGrid ? ($activeFolder || undefined) : undefined,
        rating: inImageGrid ? ($activeRating || undefined) : undefined,
        blacklist: inImageGrid ? blacklistParam($blacklistedTagNames) : undefined,
        duplicates_only: inImageGrid ? $duplicatesOnly : undefined,
        duplicate_scope: inImageGrid && $duplicatesOnly ? $duplicateScope : undefined,
        favorites_only: $viewMode === 'favorites',
        collection_id: $viewMode === 'collection-detail' ? ($activeCollectionId ?? undefined) : undefined,
        collections_only: $viewMode === 'collections',
      });
      selectedImageId.set(result.id);
    } catch (e) {
      console.error('Failed to open random item:', e);
    } finally {
      randomBusy = false;
    }
  }

  $: selectedImageSize = imageSizeOptions.find(option => option.value === $imageSize) ?? imageSizeOptions[1];
  $: selectedPageSize = imagePageSizeOptions.find(option => option.value === $imagePageSize) ?? imagePageSizeOptions[0];
  $: showImagePaging = $viewMode === 'gallery' || $viewMode === 'favorites' || $viewMode === 'collection-detail' || $viewMode === 'popularity';
  $: randomLabel = $viewMode === 'tags' ? 'Random Tag' : 'Random';
</script>

<svelte:window on:click={closeMenu} />

<header class="flex items-center gap-3 px-4 py-2 bg-[#16161e] border-b border-[#2a2a3a] shrink-0">
  <button
    class="p-1.5 rounded hover:bg-[#2a2a3a] transition-colors"
    on:click={() => showAppMenu = true}
    title="Open {SUITE_NAME} menu"
    aria-label="Open {SUITE_NAME} menu"
  >
    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h16"/>
    </svg>
  </button>

  <button
    class="group flex cursor-pointer items-center gap-2 whitespace-nowrap rounded-lg px-1.5 py-1 transition-colors hover:bg-[#20202c]"
    on:click={goHome}
    title="Go Home"
  >
    <img
      src="/logo.svg"
      alt=""
      class="h-7 w-7 rounded-md shadow-[0_0_18px_rgba(168,85,247,0.22)] transition-transform group-hover:scale-105"
      decoding="async"
    />
    <span class="text-lg font-semibold {$viewMode === 'home' ? 'text-purple-100' : 'text-purple-300 group-hover:text-purple-100'}">
      {MODULE_DISPLAY_NAME}
    </span>
  </button>

  <nav class="flex gap-1 ml-2">
    {#each [['gallery', 'Browse'], ['tags', 'Tags']] as [id, label]}
      <button
        class="px-3 py-1 text-sm rounded transition-colors {$viewMode === id ? 'bg-purple-600/30 text-purple-300' : 'hover:bg-[#2a2a3a] text-gray-400'}"
        on:click={() => setView(id as ViewMode)}
      >{label}</button>
    {/each}
  </nav>

  <div class="flex-1 max-w-xl mx-4">
    <SearchBar />
  </div>

  <div class="flex items-center gap-2 text-sm">
    <!-- Image size dropdown -->
    <div class="relative">
      <button
        class="grid h-9 w-9 place-items-center rounded-lg border border-[#2a2a3a] bg-[#1e1e2e] text-gray-300 transition-colors hover:border-purple-500/50 hover:text-white"
        on:click|stopPropagation={toggleSizeMenu}
        aria-label="Size"
        title="Size: {selectedImageSize.label}"
      >
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h6v6H4V6zm10 0h6v6h-6V6zM4 16h6v2H4v-2zm10 0h6v2h-6v-2z"/>
        </svg>
      </button>

      {#if showSizeMenu}
        <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
        <div
          class="absolute right-0 top-full mt-1 w-40 overflow-hidden rounded-lg border border-[#2a2a3a] bg-[#1e1e2e] shadow-xl z-50"
          on:click|stopPropagation
        >
          {#each imageSizeOptions as opt}
            <button
              class="w-full flex items-center justify-between px-3 py-1.5 text-sm transition-colors {$imageSize === opt.value ? 'text-purple-300 bg-purple-600/10' : 'text-gray-400 hover:bg-[#2a2a3a]'}"
              on:click={() => { imageSize.set(opt.value); closeMenu(); }}
            >
              <span>{opt.label}</span>
              {#if $imageSize === opt.value}
                <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/>
                </svg>
              {/if}
            </button>
          {/each}
        </div>
      {/if}
    </div>

    <!-- Filter dropdown -->
    <div class="relative">
      <button
        class="grid h-9 w-9 place-items-center rounded-lg border border-[#2a2a3a] bg-[#1e1e2e] text-gray-300 transition-colors hover:border-purple-500/50 hover:text-white"
        on:click|stopPropagation={toggleFilterMenu}
        aria-label="Filter"
        title="Filter"
      >
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2.586a1 1 0 01-.293.707l-6.414 6.414a1 1 0 00-.293.707V17l-4 4v-6.586a1 1 0 00-.293-.707L3.293 7.293A1 1 0 013 6.586V4z"/>
        </svg>
      </button>

      {#if showFilterMenu}
        <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
        <div
          class="absolute right-0 top-full mt-1 w-64 bg-[#1e1e2e] border border-[#2a2a3a] rounded-lg shadow-xl z-50 overflow-hidden"
          on:click|stopPropagation
        >
          <!-- Sort section -->
          <div class="px-3 pt-2.5 pb-1">
            <div class="text-[10px] text-gray-500 uppercase tracking-wider font-medium">Sort</div>
          </div>
          {#each sortOptions as opt}
            <div class="flex items-center justify-between px-3 py-1.5 text-sm transition-colors {isSortSelected(opt) ? 'text-purple-300 bg-purple-600/10' : 'text-gray-400 hover:bg-[#2a2a3a]'}">
              <button class="flex-1 text-left" on:click={() => setSortOption(opt)}>
                {opt.label}
              </button>
              {#if isSortSelected(opt) && !opt.order}
                <button
                  class="p-0.5 rounded hover:bg-purple-600/20 transition-colors"
                  on:click={() => sortOrder.update(o => o === 'desc' ? 'asc' : 'desc')}
                  title="{$sortOrder === 'desc' ? 'Descending' : 'Ascending'}"
                >
                  <svg class="w-3.5 h-3.5 transition-transform {$sortOrder === 'asc' ? 'rotate-180' : ''}" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
                  </svg>
                </button>
              {/if}
            </div>
          {/each}

          <div class="border-t border-[#2a2a3a] mx-2 my-1"></div>

          <!-- Resize section -->
          <div class="px-3 pt-1 pb-1">
            <div class="text-[10px] text-gray-500 uppercase tracking-wider font-medium">Resize</div>
          </div>
          <button
            class="w-full flex items-center gap-2 px-3 py-1.5 text-sm transition-colors {$fitMode === 'fit' ? 'text-purple-300 bg-purple-600/10' : 'text-gray-400 hover:bg-[#2a2a3a]'}"
            on:click={() => fitMode.set('fit')}
          >
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 5a1 1 0 011-1h4a1 1 0 010 2H7.414l2.293 2.293a1 1 0 01-1.414 1.414L6 7.414V9a1 1 0 01-2 0V5zm16 14a1 1 0 01-1 1h-4a1 1 0 010-2h1.586l-2.293-2.293a1 1 0 011.414-1.414L18 16.586V15a1 1 0 012 0v4z"/>
            </svg>
            Fit (crop to fill)
          </button>
          <button
            class="w-full flex items-center gap-2 px-3 py-1.5 text-sm transition-colors {$fitMode === 'contain' ? 'text-purple-300 bg-purple-600/10' : 'text-gray-400 hover:bg-[#2a2a3a]'}"
            on:click={() => fitMode.set('contain')}
          >
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z"/>
            </svg>
            Contain (true size)
          </button>

          <div class="border-t border-[#2a2a3a] mx-2 my-1"></div>

          <!-- Shape section -->
          <div class="px-3 pt-1 pb-1">
            <div class="text-[10px] text-gray-500 uppercase tracking-wider font-medium">Shape</div>
          </div>
          {#each shapeOptions as option}
            <button
              class="w-full flex items-center gap-2 px-3 py-1.5 text-left text-sm transition-colors {$activeTags.includes(option.value) ? 'text-purple-300 bg-purple-600/10' : 'text-gray-400 hover:bg-[#2a2a3a]'}"
              on:click={() => toggleSearchTerm(option.value)}
              title="Search {option.hint}"
            >
              <svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                {#if option.value === 'phone'}
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 2h8a2 2 0 012 2v16a2 2 0 01-2 2H8a2 2 0 01-2-2V4a2 2 0 012-2z"/>
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 18h2"/>
                {:else if option.value === 'vertical'}
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 3h6v18H9z"/>
                {:else if option.value === 'horizontal'}
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 8h18v8H3z"/>
                {:else if option.value === 'banner'}
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 7h18v10H3z"/>
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 11h12"/>
                {:else}
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 6h12v12H6z"/>
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 15l2-2 2 2 2-3"/>
                {/if}
              </svg>
              <span class="min-w-0 flex-1">
                <span class="block leading-tight">{option.label}</span>
                <span class="block truncate text-[10px] text-gray-600">{option.hint}</span>
              </span>
              {#if $activeTags.includes(option.value)}
                <svg class="ml-auto w-3.5 h-3.5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/>
                </svg>
              {/if}
            </button>
          {/each}

          <div class="border-t border-[#2a2a3a] mx-2 my-1"></div>

          <!-- Duplicate section -->
          <div class="px-3 pt-1 pb-1">
            <div class="text-[10px] text-gray-500 uppercase tracking-wider font-medium">Duplicates</div>
          </div>
          {#each duplicateOptions as option}
            <button
              class="w-full flex items-center gap-2 px-3 py-1.5 text-sm transition-colors {$duplicatesOnly && $duplicateScope === option.value ? 'text-purple-300 bg-purple-600/10' : 'text-gray-400 hover:bg-[#2a2a3a]'}"
              on:click={() => setDuplicateFilter(option.value)}
            >
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7h9a2 2 0 012 2v9m-4 2H7a2 2 0 01-2-2V9m0 0H3m2 0V7a2 2 0 012-2h8a2 2 0 012 2v2"/>
              </svg>
              {option.label}
              {#if $duplicatesOnly && $duplicateScope === option.value}
                <svg class="ml-auto w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/>
                </svg>
              {/if}
            </button>
          {/each}

          <div class="border-t border-[#2a2a3a] mx-2 my-1"></div>

          <button
            class="w-full px-3 py-1.5 text-sm text-gray-500 hover:text-gray-300 hover:bg-[#2a2a3a] transition-colors"
            on:click={() => { clearFilters(); closeMenu(); }}
          >Clear all filters</button>
        </div>
      {/if}
    </div>

    <button
      class="grid h-9 w-9 place-items-center rounded-lg border border-[#2a2a3a] bg-[#1e1e2e] text-gray-300 transition-colors hover:border-purple-500/50 hover:text-white disabled:cursor-not-allowed disabled:opacity-60"
      disabled={randomBusy}
      on:click={useRandom}
      aria-label={randomLabel}
      title="{$viewMode === 'tags' ? 'Use a random tag' : $viewMode === 'collections' ? 'Open a random image from collections' : 'Open a random image'}"
    >
      <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 7a3 3 0 013-3h10a3 3 0 013 3v10a3 3 0 01-3 3H7a3 3 0 01-3-3V7z"/>
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 8h.01M12 12h.01M16 16h.01M16 8h.01M8 16h.01"/>
      </svg>
    </button>

  </div>

  <div class="ml-auto flex items-center gap-2 text-sm">

    {#if showImagePaging}
      <!-- Page size dropdown -->
      <div class="relative">
        <button
          class="flex items-center gap-1.5 min-w-16 justify-center px-3 py-1.5 bg-[#1e1e2e] border border-[#2a2a3a] rounded-lg text-sm text-gray-300 hover:border-purple-500/50 transition-colors"
          on:click|stopPropagation={togglePageSizeMenu}
          title="Images per page"
        >
          <span>{selectedPageSize.label}</span>
          <svg class="w-3 h-3 transition-transform {showPageSizeMenu ? 'rotate-180' : ''}" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
          </svg>
        </button>

        {#if showPageSizeMenu}
          <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
          <div
            class="absolute right-0 top-full mt-1 w-24 bg-[#1e1e2e] border border-[#2a2a3a] rounded-lg shadow-xl z-50 overflow-hidden"
            on:click|stopPropagation
          >
            {#each imagePageSizeOptions as opt}
              <button
                class="w-full flex items-center justify-between px-3 py-1.5 text-sm transition-colors {$imagePageSize === opt.value ? 'text-purple-300 bg-purple-600/10' : 'text-gray-400 hover:bg-[#2a2a3a]'}"
                on:click={() => { imagePageSize.set(opt.value); closeMenu(); }}
              >
                <span>{opt.label}</span>
                {#if $imagePageSize === opt.value}
                  <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/>
                  </svg>
                {/if}
              </button>
            {/each}
          </div>
        {/if}
      </div>
    {/if}

    {#if $artistNotificationsEnabled}
      <ArtistNotifications />
    {/if}
    <UserMenu />
  </div>
</header>

{#if showAppMenu}
  <AppDrawer on:close={() => showAppMenu = false} />
{/if}
