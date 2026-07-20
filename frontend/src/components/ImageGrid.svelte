<script lang="ts">
  import { onDestroy } from 'svelte';
  import { api, type CollectionInfo, type FolderInfo, type ImageSummary, type PaginatedImages } from '../lib/api';
  import { cacheView, getCachedView, invalidateViewCache } from '../lib/viewCache';
  import {
    searchString,
    activeTags,
    sortBy,
    sortOrder,
    activeFolder,
    activeRating,
    selectedImageId,
    imageRefreshToken,
    viewMode,
    activeCollectionId,
    collectionRefreshToken,
    fitMode,
    imageSize,
    imageSizeByValue,
    imagePageSize,
    blacklistedTagNames,
    duplicatesOnly,
    duplicateScope,
    visibleImageIds,
    browseTagSelection,
    type ImagePageSize,
    type BrowseTagSelection,
  } from '../lib/stores';
  import ImageCard from './ImageCard.svelte';
  import FilterChips from './FilterChips.svelte';
  import TagBrowseHeader from './TagBrowseHeader.svelte';

  const ALL_BATCH_SIZE = 50;

  type BulkMembership = {
    collectionIds: Set<number>;
    loading: boolean;
    failed: boolean;
  };
  type ImagePinMode = 'none' | 'favorite' | 'collection';

  let images: ImageSummary[] = [];
  let total = 0;
  let loading = false;
  let offset = 0;
  let page = 1;
  let container: HTMLDivElement;
  let requestSerial = 0;
  let imageRequestController: AbortController | null = null;

  let currentQuery = '';
  let currentSort = '';
  let currentOrder = '';
  let currentFolder: string | null = null;
  let currentRating: string | null = null;
  let currentView = '';
  let currentCollectionId: number | null = null;
  let currentPageSize: ImagePageSize = 10;
  let currentBlacklist = '';
  let currentDuplicatesOnly = false;
  let currentDuplicateScope = 'all';
  let currentRefreshToken = 0;
  let selectMode = false;
  let selectedIds = new Set<number>();
  let allCollections: CollectionInfo[] = [];
  let allFolders: FolderInfo[] = [];
  let showCollectionMenu = false;
  let showFolderMenu = false;
  let bulkBusy = false;
  let bulkError = '';
  let bulkMessage = '';
  let newCollectionName = '';
  let bulkMembershipByPostId = new Map<number, BulkMembership>();
  let selectedMembershipKey = '';
  let pinBusyKeys = new Set<string>();
  let imagePinMode: ImagePinMode = 'none';
  let activeBrowseTag: BrowseTagSelection | null = null;
  let observedCollectionRefreshToken = 0;

  $: selectedSize = imageSizeByValue[$imageSize];
  $: imageSizeVars = `--image-card-width: ${selectedSize.cardWidth}px; --image-card-max-height: ${selectedSize.maxHeight}px; --image-grid-min: ${selectedSize.gridMin}px;`;
  $: gridStyle = $fitMode === 'contain'
    ? imageSizeVars
    : `${imageSizeVars} grid-template-columns: repeat(auto-fill, minmax(min(100%, var(--image-grid-min)), 1fr));`;
  $: pageSizeLabel = $imagePageSize === 'all' ? 'All' : String($imagePageSize);
  $: totalPages = $imagePageSize === 'all'
    ? 1
    : Math.max(1, Math.ceil(total / $imagePageSize));
  $: pageStart = total === 0 ? 0 : offset + 1;
  $: pageEnd = Math.min(offset + images.length, total);
  $: visibleImageIds.set(images.map(image => image.id));
  $: selectedImages = images.filter(image => selectedIds.has(image.id));
  $: selectedCount = selectedIds.size;
  $: selectedFileIds = selectedImages.map(image => image.file_id);
  $: imagePinMode = $viewMode === 'favorites' ? 'favorite' : ($viewMode === 'collection-detail' ? 'collection' : 'none');
  $: activeBrowseTag = $browseTagSelection && selectedBrowseTagMatches($browseTagSelection) ? $browseTagSelection : null;
  $: if ($browseTagSelection && !selectedBrowseTagMatches($browseTagSelection)) {
    browseTagSelection.set(null);
  }
  $: selectedFavoriteCount = selectedImages.filter(image => image.is_favorite).length;
  $: selectedCollectionCount = selectedImages.filter(image => collectionCountForImage(image) > 0).length;
  $: bulkMembershipLoading = selectedImages.some(image => membershipFor(image.id)?.loading);
  $: bulkMembershipFailed = selectedImages.some(image => membershipFor(image.id)?.failed);
  $: bulkFolderTargets = allFolders.filter(folder =>
    folder.registered || selectedImages.some(image => (image.folder || 'root') !== folder.name)
  );
  $: nextSelectedMembershipKey = selectMode ? [...selectedIds].sort((a, b) => a - b).join(',') : '';
  $: if (nextSelectedMembershipKey !== selectedMembershipKey) {
    selectedMembershipKey = nextSelectedMembershipKey;
    loadSelectedMemberships();
  }

  $: if ($collectionRefreshToken !== observedCollectionRefreshToken) {
    observedCollectionRefreshToken = $collectionRefreshToken;
    if (selectMode) loadBulkLists();
  }

  onDestroy(() => {
    imageRequestController?.abort();
    visibleImageIds.set([]);
  });

  function limitFor(size: ImagePageSize) {
    return size === 'all' ? ALL_BATCH_SIZE : size;
  }

  function offsetFor(size: ImagePageSize) {
    return size === 'all' ? 0 : (page - 1) * size;
  }

  function blacklistParam(tags: string[]) {
    return tags.length ? tags.join(',') : undefined;
  }

  function browseTagTerm(tag: BrowseTagSelection) {
    return tag.source === 'user' ? `user:${tag.name}` : tag.name;
  }

  function selectedBrowseTagMatches(tag: BrowseTagSelection) {
    return $viewMode === 'gallery' && $activeTags.length === 1 && $activeTags[0] === browseTagTerm(tag);
  }

  async function loadBulkLists() {
    try {
      const [collections, folders] = await Promise.all([
        api.getCollections(),
        api.getFolders(),
      ]);
      allCollections = collections;
      allFolders = folders;
    } catch (e) {
      console.error('Failed to load bulk action lists:', e);
    }
  }

  function closeBulkMenus() {
    showCollectionMenu = false;
    showFolderMenu = false;
  }

  function membershipFor(postId: number) {
    return bulkMembershipByPostId.get(postId);
  }

  function collectionCountForImage(image: ImageSummary) {
    const membership = membershipFor(image.id);
    if (membership) return membership.collectionIds.size;
    return image.collection_added_at ? 1 : 0;
  }

  function selectedCountInCollection(collectionId: number) {
    return selectedImages.filter(image => membershipFor(image.id)?.collectionIds.has(collectionId)).length;
  }

  function selectedMissingCollectionImages(collectionId: number) {
    return selectedImages.filter(image => !membershipFor(image.id)?.collectionIds.has(collectionId));
  }

  async function loadSelectedMemberships() {
    if (!selectMode || selectedIds.size === 0) return;
    const missing = selectedImages.filter(image => !bulkMembershipByPostId.has(image.id));
    if (missing.length === 0) return;

    let next = new Map(bulkMembershipByPostId);
    for (const image of missing) {
      next.set(image.id, { collectionIds: new Set(), loading: true, failed: false });
    }
    bulkMembershipByPostId = next;

    let loaded: Array<{ postId: number; membership: BulkMembership }>;
    try {
      const response = await api.getCollectionMemberships(missing.map(image => image.file_id));
      loaded = missing.map(image => ({
        postId: image.id,
        membership: {
          collectionIds: new Set(response.memberships[String(image.file_id)] ?? []),
          loading: false,
          failed: false,
        },
      }));
    } catch (e) {
      console.error('Failed to load selected image collection state:', e);
      loaded = missing.map(image => ({
        postId: image.id,
        membership: { collectionIds: new Set<number>(), loading: false, failed: true },
      }));
    }

    next = new Map(bulkMembershipByPostId);
    for (const item of loaded) {
      next.set(item.postId, item.membership);
    }
    bulkMembershipByPostId = next;
  }

  function markImagesInCollection(targetImages: ImageSummary[], collectionId: number) {
    const next = new Map(bulkMembershipByPostId);
    for (const image of targetImages) {
      const current = next.get(image.id) ?? { collectionIds: new Set<number>(), loading: false, failed: false };
      const collectionIds = new Set(current.collectionIds);
      collectionIds.add(collectionId);
      next.set(image.id, { collectionIds, loading: false, failed: false });
    }
    bulkMembershipByPostId = next;
  }

  function setSelectMode(enabled: boolean) {
    selectMode = enabled;
    bulkError = '';
    bulkMessage = '';
    if (enabled) {
      loadBulkLists();
    } else {
      selectedIds = new Set();
      closeBulkMenus();
    }
  }

  function toggleSelectMode() {
    setSelectMode(!selectMode);
  }

  function clearSelection() {
    selectedIds = new Set();
    bulkError = '';
    bulkMessage = '';
    closeBulkMenus();
  }

  function toggleImageSelection(postId: number) {
    const next = new Set(selectedIds);
    if (next.has(postId)) {
      next.delete(postId);
    } else {
      next.add(postId);
    }
    selectedIds = next;
    bulkError = '';
    bulkMessage = '';
    if (selectedIds.size === 0) closeBulkMenus();
  }

  function pruneSelectedIds(loadedImages: ImageSummary[]) {
    if (selectedIds.size === 0) return;
    const loadedIds = new Set(loadedImages.map(image => image.id));
    const next = [...selectedIds].filter(id => loadedIds.has(id));
    if (next.length !== selectedIds.size) {
      selectedIds = new Set(next);
      if (next.length === 0) closeBulkMenus();
    }
  }

  $: pruneSelectedIds(images);

  function selectedImageLabel(count: number) {
    return `${count.toLocaleString()} selected image${count === 1 ? '' : 's'}`;
  }

  function onNewCollectionKeydown(event: KeyboardEvent) {
    if (event.key !== 'Enter') return;
    event.preventDefault();
    createCollectionAndAddSelected();
  }

  async function addSelectedFavorites() {
    if (bulkBusy || selectedCount === 0) return;
    const targets = selectedImages.filter(image => !image.is_favorite);
    if (targets.length === 0) {
      bulkMessage = 'Selected images are already favorited';
      bulkError = '';
      return;
    }

    bulkBusy = true;
    bulkError = '';
    bulkMessage = '';
    try {
      const result = await api.updateFavorites(targets.map(image => image.file_id), 'add');
      const updates = new Map<number, string | null>(targets.map(image => [
        image.id,
        result.added_at_by_file[String(image.file_id)] ?? null,
      ] as [number, string | null]));
      images = images.map(image => updates.has(image.id)
        ? { ...image, is_favorite: true, favorite_added_at: updates.get(image.id) ?? null }
        : image
      );
      imageRefreshToken.update(n => n + 1);
      bulkMessage = `Added ${updates.size.toLocaleString()} to favorites`;
    } catch (e) {
      console.error(e);
      bulkError = 'Failed to add selected images to favorites';
    } finally {
      bulkBusy = false;
    }
  }

  async function addSelectedToCollection(collectionId: number) {
    if (bulkBusy || selectedCount === 0) return;
    if (bulkMembershipLoading) {
      bulkMessage = 'Checking selected images first';
      bulkError = '';
      return;
    }
    const collection = allCollections.find(col => col.id === collectionId);
    const targets = selectedMissingCollectionImages(collectionId);
    if (targets.length === 0) {
      bulkMessage = `Selected images are already in ${collection?.name ?? 'that collection'}`;
      bulkError = '';
      showCollectionMenu = false;
      return;
    }

    bulkBusy = true;
    bulkError = '';
    bulkMessage = '';
    try {
      await api.updateCollectionImages(collectionId, targets.map(image => image.file_id), 'add');
      markImagesInCollection(targets, collectionId);
      allCollections = allCollections.map(col => col.id === collectionId
        ? { ...col, image_count: col.image_count + targets.length }
        : col
      );
      imageRefreshToken.update(n => n + 1);
      collectionRefreshToken.update(n => n + 1);
      showCollectionMenu = false;
      bulkMessage = `Added ${targets.length.toLocaleString()} of ${selectedImageLabel(selectedCount)} to ${collection?.name ?? 'collection'}`;
    } catch (e) {
      console.error(e);
      bulkError = 'Failed to add selected images to collection';
    } finally {
      bulkBusy = false;
    }
  }

  async function createCollectionAndAddSelected() {
    const name = newCollectionName.trim();
    if (bulkBusy || selectedCount === 0 || !name) return;

    bulkBusy = true;
    bulkError = '';
    bulkMessage = '';
    try {
      const collection = await api.createCollection(name);
      await api.updateCollectionImages(collection.id, selectedFileIds, 'add');
      markImagesInCollection(selectedImages, collection.id);
      allCollections = [{ ...collection, image_count: selectedCount }, ...allCollections];
      newCollectionName = '';
      showCollectionMenu = false;
      imageRefreshToken.update(n => n + 1);
      collectionRefreshToken.update(n => n + 1);
      bulkMessage = `Created ${collection.name} and added ${selectedImageLabel(selectedCount)}`;
    } catch (e) {
      console.error(e);
      bulkError = 'Failed to create collection';
    } finally {
      bulkBusy = false;
    }
  }

  async function moveSelectedToFolder(folder: FolderInfo) {
    if (bulkBusy || selectedCount === 0) return;
    const targets = [...selectedImages];
    let movedIds = new Set<number>();
    let failed = 0;

    bulkBusy = true;
    bulkError = '';
    bulkMessage = '';
    try {
      const result = await api.moveImagesToFolder(targets.map(image => image.id), folder.selector);
      movedIds = new Set(result.moved_post_ids);
      failed = Object.keys(result.errors).length;

      if (movedIds.size > 0) {
        images = images.map(image => movedIds.has(image.id) ? { ...image, folder: folder.name } : image);
        imageRefreshToken.update(n => n + 1);
        loadBulkLists();
      }

      showFolderMenu = false;
      if (failed > 0) {
        bulkError = `Moved ${movedIds.size.toLocaleString()}, failed ${failed.toLocaleString()}`;
      } else {
        bulkMessage = `Moved ${selectedImageLabel(movedIds.size)} to ${folder.name}`;
      }
    } finally {
      bulkBusy = false;
    }
  }

  async function loadImages(options: { resetScroll?: boolean; showLoader?: boolean } = {}) {
    const { resetScroll = true, showLoader = true } = options;
    const requestId = ++requestSerial;
    const requestedPageSize = $imagePageSize;
    const requestedOffset = offsetFor(requestedPageSize);
    const shouldClearLoader = showLoader || loading;
    imageRequestController?.abort();
    const requestController = new AbortController();
    imageRequestController = requestController;
    if (showLoader) loading = true;

    try {
      const baseParams = {
        q: $searchString || undefined,
        sort: $sortBy,
        order: $sortOrder,
        folder: $activeFolder || undefined,
        rating: $activeRating || undefined,
        blacklist: blacklistParam($blacklistedTagNames),
        duplicates_only: $duplicatesOnly,
        duplicate_scope: $duplicatesOnly ? $duplicateScope : undefined,
        favorites_only: $viewMode === 'favorites',
        collection_id: $viewMode === 'collection-detail' ? ($activeCollectionId ?? undefined) : undefined,
      };

      const requestParams = {
        ...baseParams,
        offset: requestedOffset,
        limit: limitFor(requestedPageSize),
      };
      const cacheKey = `images:${JSON.stringify(requestParams)}`;
      const cached = getCachedView<PaginatedImages>(cacheKey);
      if (cached && requestId === requestSerial) {
        images = cached.images;
        total = cached.total;
        offset = cached.offset;
        loading = false;
      }

      const result = await api.getImages(requestParams, requestController.signal);

      if (requestId !== requestSerial) return;
      cacheView(cacheKey, result);

      if (requestedPageSize === 'all') {
        images = result.images;
        total = result.total;
        offset = 0;

        if (resetScroll) {
          requestAnimationFrame(() => {
            if (container) container.scrollTop = 0;
          });
        }
        return;
      }

      const maxPage = Math.max(1, Math.ceil(result.total / requestedPageSize));
      if (page > maxPage) {
        page = maxPage;
        await loadImages({ resetScroll, showLoader });
        return;
      }

      images = result.images;
      total = result.total;
      offset = result.offset;

      if (resetScroll) {
        requestAnimationFrame(() => {
          if (container) container.scrollTop = 0;
        });
      }
    } catch (e) {
      if (requestId === requestSerial && !(e instanceof DOMException && e.name === 'AbortError')) {
        console.error('Failed to load images:', e);
      }
    } finally {
      if (requestId === requestSerial) {
        if (shouldClearLoader) loading = false;
      }
    }
  }

  function checkAndReload(..._deps: unknown[]) {
    const q = $searchString;
    const s = $sortBy;
    const o = $sortOrder;
    const f = $activeFolder;
    const r = $activeRating;
    const v = $viewMode;
    const c = $activeCollectionId;
    const ps = $imagePageSize;
    const b = $blacklistedTagNames.join('\n');
    const d = $duplicatesOnly;
    const ds = $duplicateScope;
    const rt = $imageRefreshToken;
    const queryChanged = q !== currentQuery || s !== currentSort || o !== currentOrder ||
      f !== currentFolder || r !== currentRating || v !== currentView ||
      c !== currentCollectionId || ps !== currentPageSize || b !== currentBlacklist ||
      d !== currentDuplicatesOnly || ds !== currentDuplicateScope;
    const refreshChanged = rt !== currentRefreshToken;

    if (queryChanged || refreshChanged) {
      if (refreshChanged) invalidateViewCache('images:');
      currentQuery = q;
      currentSort = s;
      currentOrder = o;
      currentFolder = f;
      currentRating = r;
      currentView = v;
      currentCollectionId = c;
      currentPageSize = ps;
      currentBlacklist = b;
      currentDuplicatesOnly = d;
      currentDuplicateScope = ds;
      currentRefreshToken = rt;

      if (queryChanged) {
        page = 1;
        clearSelection();
        loadImages();
        return;
      }

      if (ps === 'all') {
        loadImages({ resetScroll: false, showLoader: false });
        return;
      }

      const scrollTop = container?.scrollTop ?? 0;
      loadImages({ resetScroll: false, showLoader: false }).then(() => {
        requestAnimationFrame(() => {
          if (container) container.scrollTop = scrollTop;
        });
      });
    }
  }

  $: checkAndReload($searchString, $sortBy, $sortOrder, $activeFolder, $activeRating, $viewMode, $activeCollectionId, $imagePageSize, $blacklistedTagNames, $duplicatesOnly, $duplicateScope, $imageRefreshToken);

  async function loadMoreAll() {
    if (loading || $imagePageSize !== 'all' || images.length >= total) return;

    const requestId = ++requestSerial;
    imageRequestController?.abort();
    const requestController = new AbortController();
    imageRequestController = requestController;
    loading = true;
    try {
      const result = await api.getImages({
        q: $searchString || undefined,
        sort: $sortBy,
        order: $sortOrder,
        folder: $activeFolder || undefined,
        rating: $activeRating || undefined,
        blacklist: blacklistParam($blacklistedTagNames),
        duplicates_only: $duplicatesOnly,
        duplicate_scope: $duplicatesOnly ? $duplicateScope : undefined,
        offset: images.length,
        limit: ALL_BATCH_SIZE,
        favorites_only: $viewMode === 'favorites',
        collection_id: $viewMode === 'collection-detail' ? ($activeCollectionId ?? undefined) : undefined,
      }, requestController.signal);
      if (requestId !== requestSerial) return;
      images = [...images, ...result.images];
      total = result.total;
    } catch (e) {
      if (requestId === requestSerial && !(e instanceof DOMException && e.name === 'AbortError')) {
        console.error('Failed to load more images:', e);
      }
    } finally {
      if (requestId === requestSerial) {
        loading = false;
      }
    }
  }

  function onScroll() {
    if (!container || $imagePageSize !== 'all') return;
    const distanceToBottom = container.scrollHeight - container.scrollTop - container.clientHeight;
    if (distanceToBottom < 900) {
      loadMoreAll();
    }
  }

  function goToPage(nextPage: number) {
    if ($imagePageSize === 'all') return;
    const bounded = Math.min(Math.max(1, nextPage), totalPages);
    if (bounded === page) return;
    page = bounded;
    loadImages();
  }

  function visiblePages(current: number, max: number): (number | '...')[] {
    if (max <= 7) return Array.from({ length: max }, (_, i) => i + 1);
    const pages: (number | '...')[] = [1];
    if (current > 3) pages.push('...');
    for (let i = Math.max(2, current - 1); i <= Math.min(max - 1, current + 1); i++) {
      pages.push(i);
    }
    if (current < max - 2) pages.push('...');
    pages.push(max);
    return pages;
  }

  function onSelect(e: CustomEvent<number>) {
    if (selectMode) {
      toggleImageSelection(e.detail);
      return;
    }
    selectedImageId.set(e.detail);
  }

  function onLongSelect(e: CustomEvent<number>) {
    if (!selectMode) setSelectMode(true);
    toggleImageSelection(e.detail);
  }

  async function toggleImagePin(e: CustomEvent<{ image: ImageSummary; mode: 'favorite' | 'collection' }>) {
    const { image, mode } = e.detail;
    const key = `${mode}:${image.file_id}`;
    if (pinBusyKeys.has(key)) return;
    if (mode === 'collection' && $activeCollectionId === null) return;

    pinBusyKeys = new Set(pinBusyKeys).add(key);
    try {
      const result = mode === 'favorite'
        ? await api.toggleFavoritePin(image.file_id)
        : await api.toggleCollectionImagePin($activeCollectionId!, image.file_id);
      images = images.map(item => {
        if (item.id !== image.id) return item;
        return mode === 'favorite'
          ? { ...item, favorite_pinned_at: result.pinned_at }
          : { ...item, collection_pinned_at: result.pinned_at };
      });
      imageRefreshToken.update(n => n + 1);
    } catch (err) {
      console.error('Failed to pin image:', err);
    } finally {
      const next = new Set(pinBusyKeys);
      next.delete(key);
      pinBusyKeys = next;
    }
  }
</script>

<div class="flex flex-col h-full">
  <FilterChips {total} {selectMode} {selectedCount} on:toggle-select={toggleSelectMode} />

  <div bind:this={container} class="flex-1 overflow-y-auto p-4" on:scroll={onScroll}>
    {#if activeBrowseTag}
      <TagBrowseHeader tag={activeBrowseTag} {images} {total} {loading} />
    {/if}

    <div
      style={gridStyle}
      class="{$fitMode === 'contain'
      ? 'flex flex-wrap gap-3 justify-center items-end'
      : 'grid gap-3'}"
    >
      {#each images as image (image.id)}
        <ImageCard
          {image}
          {selectMode}
          selected={selectedIds.has(image.id)}
          collectionCount={collectionCountForImage(image)}
          pinMode={imagePinMode}
          pinBusy={pinBusyKeys.has(`${imagePinMode}:${image.file_id}`)}
          on:select={onSelect}
          on:longselect={onLongSelect}
          on:pin={toggleImagePin}
        />
      {/each}
    </div>

    {#if loading}
      <div class="flex justify-center py-8">
        <div class="w-8 h-8 border-2 border-purple-500 border-t-transparent rounded-full animate-spin"></div>
      </div>
    {/if}

    {#if !loading && images.length === 0}
      <div class="flex flex-col items-center justify-center py-20 text-gray-500">
        <svg class="w-16 h-16 mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z"/>
        </svg>
        <p class="text-lg">No images found</p>
        <p class="text-sm">Try adjusting your filters</p>
      </div>
    {/if}

    {#if total > 0}
      <div class="mt-4 pb-4 flex flex-wrap items-center justify-center gap-2">
        {#if $imagePageSize !== 'all' && totalPages > 1}
          <button
            class="px-3 py-1.5 text-sm rounded-lg border transition-colors {page > 1 ? 'border-[#2a2a3a] text-gray-400 hover:bg-[#1e1e2e]' : 'border-transparent text-gray-600 cursor-not-allowed'}"
            disabled={page === 1}
            on:click={() => goToPage(page - 1)}
          >Previous</button>

          <div class="flex gap-1 mx-1">
            {#each visiblePages(page, totalPages) as p}
              {#if p === '...'}
                <span class="px-2 py-1 text-xs text-gray-600">...</span>
              {:else}
                <button
                  class="px-2.5 py-1 text-xs rounded-lg border transition-colors {p === page ? 'bg-purple-600/20 text-purple-300 border-purple-500/30' : 'border-[#2a2a3a] text-gray-400 hover:bg-[#1e1e2e]'}"
                  on:click={() => goToPage(p)}
                >{p}</button>
              {/if}
            {/each}
          </div>

          <button
            class="px-3 py-1.5 text-sm rounded-lg border transition-colors {page < totalPages ? 'border-[#2a2a3a] text-gray-400 hover:bg-[#1e1e2e]' : 'border-transparent text-gray-600 cursor-not-allowed'}"
            disabled={page >= totalPages}
            on:click={() => goToPage(page + 1)}
          >Next</button>
        {/if}

        <div class="px-2 py-1 text-xs text-gray-500">
          {#if $imagePageSize === 'all'}
            {#if images.length >= total}
              Showing all {total.toLocaleString()}
            {:else}
              Showing {images.length.toLocaleString()} of {total.toLocaleString()} · scroll for more
            {/if}
          {:else}
            {pageStart.toLocaleString()}-{pageEnd.toLocaleString()} of {total.toLocaleString()} · {pageSizeLabel} per page
          {/if}
        </div>
      </div>
    {/if}
  </div>

  {#if selectMode && selectedCount > 0}
    <div class="fixed bottom-5 left-1/2 z-40 w-[calc(100%-2rem)] max-w-4xl -translate-x-1/2 rounded-xl border border-[#3a3a50] bg-[#14141f]/95 px-3 py-2.5 shadow-2xl shadow-black/40 backdrop-blur">
      <div class="flex flex-wrap items-center gap-2">
        <div class="flex min-w-64 flex-col pr-2">
          <div class="flex items-center gap-2 text-sm text-gray-200">
            <span class="flex h-7 w-7 items-center justify-center rounded-lg bg-purple-600/25 text-purple-200">
              <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M5 13l4 4L19 7"/>
              </svg>
            </span>
            <span class="font-medium">{selectedImageLabel(selectedCount)}</span>
          </div>
          <div class="mt-0.5 text-xs text-gray-500">
            {selectedFavoriteCount.toLocaleString()} favorited · {selectedCollectionCount.toLocaleString()} in collections
            {#if bulkMembershipLoading}
              · checking
            {:else if bulkMembershipFailed}
              · some unknown
            {/if}
          </div>
        </div>

        <button
          class="flex items-center gap-2 rounded-lg border border-[#2a2a3a] bg-[#1e1e2e] px-3 py-2 text-sm text-gray-300 transition-colors hover:border-pink-500/40 hover:text-pink-300 disabled:cursor-not-allowed disabled:opacity-50"
          disabled={bulkBusy || selectedFavoriteCount === selectedCount}
          on:click={addSelectedFavorites}
          title="{selectedFavoriteCount === selectedCount ? 'Selected images are already favorited' : 'Add selected images that are not already favorites'}"
        >
          <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/>
          </svg>
          Favorite
          <span class="rounded bg-black/30 px-1.5 py-0.5 text-[10px] text-gray-400">
            {selectedFavoriteCount}/{selectedCount}
          </span>
        </button>

        <div class="relative">
          <button
            class="flex items-center gap-2 rounded-lg border border-[#2a2a3a] bg-[#1e1e2e] px-3 py-2 text-sm text-gray-300 transition-colors hover:border-purple-500/40 hover:text-purple-300 disabled:cursor-not-allowed disabled:opacity-50"
            disabled={bulkBusy}
            on:click={() => { showCollectionMenu = !showCollectionMenu; showFolderMenu = false; }}
            title="Add selected images to a collection"
          >
            <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10"/>
            </svg>
            Collection
            <span class="rounded bg-black/30 px-1.5 py-0.5 text-[10px] text-gray-400">
              {selectedCollectionCount}/{selectedCount}
            </span>
          </button>

          {#if showCollectionMenu}
            <div class="absolute bottom-full left-0 mb-2 w-80 overflow-hidden rounded-lg border border-[#2a2a3a] bg-[#1e1e2e] shadow-xl">
              <div class="max-h-64 overflow-y-auto">
                {#if allCollections.length === 0}
                  <div class="px-3 py-3 text-sm text-gray-500">No collections yet</div>
                {:else}
                  {#each allCollections as col}
                    {@const alreadyInCollection = selectedCountInCollection(col.id)}
                    {@const allAlreadyInCollection = alreadyInCollection === selectedCount && selectedCount > 0}
                    <button
                      class="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm text-gray-300 transition-colors hover:bg-[#2a2a3a] disabled:opacity-60"
                      disabled={bulkBusy || bulkMembershipLoading || allAlreadyInCollection}
                      on:click={() => addSelectedToCollection(col.id)}
                      title="{allAlreadyInCollection ? 'Selected images are already in this collection' : bulkMembershipLoading ? 'Checking selected images first' : 'Add missing selected images to this collection'}"
                    >
                      <span class="min-w-0 truncate">{col.name}</span>
                      <span class="flex shrink-0 items-center gap-2 text-xs">
                        <span class="{allAlreadyInCollection ? 'text-purple-300' : 'text-gray-600'}">
                          {alreadyInCollection}/{selectedCount}
                        </span>
                        {#if allAlreadyInCollection}
                          <svg class="h-3.5 w-3.5 text-purple-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M5 13l4 4L19 7"/>
                          </svg>
                        {:else}
                          <span class="text-gray-700">{col.image_count.toLocaleString()}</span>
                        {/if}
                      </span>
                    </button>
                  {/each}
                {/if}
              </div>
              <div class="flex gap-1 border-t border-[#2a2a3a] p-2">
                <input
                  type="text"
                  bind:value={newCollectionName}
                  placeholder="New collection..."
                  class="min-w-0 flex-1 rounded border border-[#2a2a3a] bg-[#16161e] px-2 py-1 text-xs outline-none focus:border-purple-500"
                  disabled={bulkBusy}
                  on:keydown|stopPropagation={onNewCollectionKeydown}
                />
                <button
                  class="rounded bg-purple-600 px-2 py-1 text-xs text-white transition-colors hover:bg-purple-500 disabled:cursor-not-allowed disabled:opacity-50"
                  disabled={bulkBusy || !newCollectionName.trim()}
                  on:click={createCollectionAndAddSelected}
                >Add</button>
              </div>
            </div>
          {/if}
        </div>

        <div class="relative">
          <button
            class="flex items-center gap-2 rounded-lg border border-[#2a2a3a] bg-[#1e1e2e] px-3 py-2 text-sm text-gray-300 transition-colors hover:border-cyan-500/40 hover:text-cyan-300 disabled:cursor-not-allowed disabled:opacity-50"
            disabled={bulkBusy}
            on:click={() => { showFolderMenu = !showFolderMenu; showCollectionMenu = false; }}
            title="Move selected images to another folder"
          >
            <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 7h5l2 2h11v8a2 2 0 01-2 2H5a2 2 0 01-2-2V7z"/>
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 13h5m0 0l-2-2m2 2l-2 2"/>
            </svg>
            Move
          </button>

          {#if showFolderMenu}
            <div class="absolute bottom-full left-0 mb-2 w-72 max-h-80 overflow-y-auto rounded-lg border border-[#2a2a3a] bg-[#1e1e2e] shadow-xl">
              {#if bulkFolderTargets.length === 0}
                <div class="px-3 py-3 text-sm text-gray-500">No other folders</div>
              {:else}
                {#each bulkFolderTargets as folder}
                  <button
                    class="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm text-gray-300 transition-colors hover:bg-[#2a2a3a] disabled:opacity-60"
                    disabled={bulkBusy}
                    on:click={() => moveSelectedToFolder(folder)}
                    title="Move selected images to {folder.name}"
                  >
                    <span class="min-w-0"><span class="block truncate">{folder.name}</span>{#if folder.path}<span class="block truncate text-[10px] text-gray-600">{folder.path}</span>{/if}</span>
                    <span class="shrink-0 text-xs text-gray-600">{folder.count.toLocaleString()}</span>
                  </button>
                {/each}
              {/if}
            </div>
          {/if}
        </div>

        <button
          class="ml-auto flex h-9 w-9 items-center justify-center rounded-lg border border-[#2a2a3a] bg-[#1e1e2e] text-gray-400 transition-colors hover:text-white disabled:cursor-not-allowed disabled:opacity-50"
          disabled={bulkBusy}
          on:click={clearSelection}
          title="Clear selection"
          aria-label="Clear selection"
        >
          <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
          </svg>
        </button>

        {#if bulkBusy}
          <div class="h-5 w-5 rounded-full border-2 border-purple-500 border-t-transparent animate-spin"></div>
        {/if}

        {#if bulkError || bulkMessage}
          <div class="w-full px-1 text-xs {bulkError ? 'text-red-300' : 'text-gray-400'}">
            {bulkError || bulkMessage}
          </div>
        {/if}
      </div>
    </div>
  {/if}
</div>
