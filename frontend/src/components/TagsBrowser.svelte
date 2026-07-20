<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import {
    api,
    thumbnailUrl,
    type FavoriteTagCombo,
    type ImageSummary,
    type PaginatedTags,
    type TagInfo,
    type TagWikiExample,
    type TagWikiInfo,
    type TagWikiTextLine,
  } from '../lib/api';
  import { cacheView, getCachedView, invalidateViewCache } from '../lib/viewCache';
  import { activeTags, artistFollowRefreshToken, browseTagSelection, fitMode, imageSize, imageSizeByValue, selectedImageId, tagRefreshToken, viewMode } from '../lib/stores';
  import ImageCard from './ImageCard.svelte';
  import TagBrowseHeader from './TagBrowseHeader.svelte';

  const PAGE_SIZE = 200;
  const TAG_IMAGE_PAGE_SIZE = 80;

  let tags: TagInfo[] = [];
  let total = 0;
  let offset = 0;
  let loading = false;
  let selectedTag: TagInfo | null = null;
  let selectedTagSource: 'danbooru' | 'user' = 'danbooru';
  let wikiInfo: TagWikiInfo | null = null;
  let wikiLoading = false;
  let wikiError = '';
  let tagImages: ImageSummary[] = [];
  let tagImageTotal = 0;
  let tagImageOffset = 0;
  let tagImagesLoading = false;
  let wikiRequestSerial = 0;
  let tagImageRequestSerial = 0;
  let tagListRequestSerial = 0;
  let tagListRequestController: AbortController | null = null;
  let requestedTagDetailKey = '';

  let searchQ = '';
  let searchDebounce: ReturnType<typeof setTimeout>;
  let category: string | null = null;
  let sort: 'count' | 'alpha' | 'length' | 'category' = 'count';
  let order: 'asc' | 'desc' = 'desc';
  let minCount = 1;
  let favoriteOnly = false;
  let pinnedOnly = false;
  let tagSource: 'danbooru' | 'user' = 'danbooru';
  let tagDisplayMode: 'wide' | 'wrap' | 'compact' = 'wide';
  let alphabetView: 'off' | 'columns' | 'sections' = 'off';
  let selectedAlphabetLetter: string | null = null;

  let favTagSet = new Set<string>();
  let pinnedTagSet = new Set<string>();
  let favoriteTags: Record<string, TagInfo[]> = {};
  let tagCombos: FavoriteTagCombo[] = [];
  let comboName = '';
  let comboBusy = false;
  let currentComboTags: string[] = [];
  let showComboMenu = false;
  let comboButton: HTMLButtonElement;
  let comboMenu: HTMLDivElement;
  let observedTagRefreshToken = 0;
  let observedArtistFollowRefreshToken = 0;
  let followedArtistTags = new Set<string>();
  let artistFollowSerial = 0;
  let artistFollowBusy = false;

  const categories = ['character', 'artist', 'copyright', 'general', 'meta'];
  const categoryColors: Record<string, string> = {
    artist: 'bg-red-500/20 text-red-300 border-red-500/30',
    character: 'bg-green-500/20 text-green-300 border-green-500/30',
    copyright: 'bg-purple-500/20 text-purple-300 border-purple-500/30',
    general: 'bg-blue-500/20 text-blue-300 border-blue-500/30',
    meta: 'bg-yellow-500/20 text-yellow-300 border-yellow-500/30',
  };

  const sortOptions = [
    { value: 'count', label: 'Image Count', defaultOrder: 'desc' },
    { value: 'alpha', label: 'Alphabetical', defaultOrder: 'asc' },
    { value: 'length', label: 'Name Length', defaultOrder: 'asc' },
    { value: 'category', label: 'Category', defaultOrder: 'asc' },
  ] as const;

  const displayOptions = [
    { value: 'wide', label: 'Wide Cards' },
    { value: 'wrap', label: 'Wrap Names' },
    { value: 'compact', label: 'Compact Hover' },
  ] as const;

  const alphabetOptions = [
    { value: 'columns', label: 'A-Z Columns' },
    { value: 'sections', label: 'A-Z Sections' },
  ] as const;
  const alphabetLetters = ['#', ...'ABCDEFGHIJKLMNOPQRSTUVWXYZ'.split('')];

  onMount(() => {
    Promise.all([
      fetchFavoriteTags(),
      fetchArtistFollowState(),
      fetchTagCombos(),
      fetchTags(),
    ]).catch((error) => console.error('Failed to initialize tag browser:', error));
  });

  onDestroy(() => {
    clearTimeout(searchDebounce);
    tagListRequestController?.abort();
  });

  $: if ($tagRefreshToken !== observedTagRefreshToken) {
    observedTagRefreshToken = $tagRefreshToken;
    invalidateViewCache('tags:');
    refreshFavoriteTagViews().catch(console.error);
  }

  $: if ($artistFollowRefreshToken !== observedArtistFollowRefreshToken) {
    observedArtistFollowRefreshToken = $artistFollowRefreshToken;
    fetchArtistFollowState().catch(console.error);
  }

  async function fetchFavoriteTags() {
    const [nextFavoriteTags, favNames] = await Promise.all([
      api.getFavoriteTags(),
      api.getFavoriteTagNames(),
    ]);
    favoriteTags = nextFavoriteTags;
    favTagSet = new Set(favNames.map(t => `${t.category}:${t.name}`));
    pinnedTagSet = new Set(favNames.filter(t => t.pinned_at).map(t => `${t.category}:${t.name}`));
  }

  async function refreshFavoriteTagViews() {
    await fetchFavoriteTags();
    if (favoriteOnly || pinnedOnly) fetchTags({ showLoader: false });
  }

  async function fetchArtistFollowState() {
    const requestId = ++artistFollowSerial;
    try {
      const rows = await api.getArtistFollowNames();
      if (requestId !== artistFollowSerial) return;
      followedArtistTags = new Set(rows.map(row => row.name));
    } catch (e) {
      if (requestId !== artistFollowSerial) return;
      console.error('Failed to load artist follow state:', e);
      followedArtistTags = new Set();
    }
  }

  async function fetchTagCombos() {
    tagCombos = await api.getFavoriteTagCombos();
  }

  function notifyTagRefresh() {
    tagRefreshToken.update(n => {
      observedTagRefreshToken = n + 1;
      return n + 1;
    });
  }

  function notifyArtistFollowRefresh() {
    artistFollowRefreshToken.update(n => {
      observedArtistFollowRefreshToken = n + 1;
      return n + 1;
    });
  }

  function tagKey(cat: string, tagName: string) {
    return `${cat}:${tagName}`;
  }

  function tagInfoFor(tagName: string, cat: string): TagInfo {
    return tags.find(tag => tag.name === tagName && tag.category === cat)
      ?? (selectedTag?.name === tagName && selectedTag.category === cat ? selectedTag : null)
      ?? Object.values(favoriteTags).flat().find(tag => tag.name === tagName && tag.category === cat)
      ?? { name: tagName, category: cat, count: 0 };
  }

  function setVisibleTagMeta(tagName: string, cat: string, patch: Partial<TagInfo>) {
    tags = tags.map(tag => tag.name === tagName && tag.category === cat ? { ...tag, ...patch } : tag);
    if (selectedTag?.name === tagName && selectedTag.category === cat) {
      selectedTag = { ...selectedTag, ...patch };
    }
  }

  function upsertFavoriteTag(tagName: string, cat: string, patch: Partial<TagInfo>) {
    const entry = { ...tagInfoFor(tagName, cat), ...patch, name: tagName, category: cat };
    const list = favoriteTags[cat] ?? [];
    favoriteTags = {
      ...favoriteTags,
      [cat]: [entry, ...list.filter(tag => !(tag.name === tagName && tag.category === cat))],
    };
  }

  function removeFavoriteTag(tagName: string, cat: string) {
    const list = favoriteTags[cat] ?? [];
    const nextList = list.filter(tag => !(tag.name === tagName && tag.category === cat));
    const nextFavorites = { ...favoriteTags };
    if (nextList.length) nextFavorites[cat] = nextList;
    else delete nextFavorites[cat];
    favoriteTags = nextFavorites;
  }

  function syncFavoriteTagPage() {
    if (!favoriteOnly && !pinnedOnly) return;
    const favoriteResults = getFavoriteTagResults();
    total = favoriteResults.length;
    if (offset >= total && offset > 0) {
      offset = Math.max(0, Math.floor(Math.max(total - 1, 0) / PAGE_SIZE) * PAGE_SIZE);
    }
    tags = favoriteResults.slice(offset, offset + PAGE_SIZE);
    loading = false;
  }

  function getFavoriteTagResults(letterFilter = selectedAlphabetLetter) {
    const q = searchQ.trim().toLowerCase();
    const filtered = Object.values(favoriteTags)
      .flat()
      .filter(tag => {
        if (category && tag.category !== category) return false;
        if (pinnedOnly && !tag.pinned_at) return false;
        if (tag.count < minCount) return false;
        if (letterFilter && getTagLetter(tag) !== letterFilter) return false;
        if (!q) return true;
        const displayName = tag.name.replace(/_/g, ' ').toLowerCase();
        return tag.name.toLowerCase().includes(q) || displayName.includes(q);
      })
      .sort((a, b) => {
        if (a.pinned_at && !b.pinned_at) return -1;
        if (!a.pinned_at && b.pinned_at) return 1;
        if (a.pinned_at && b.pinned_at) return b.pinned_at.localeCompare(a.pinned_at);
        let result = 0;
        if (sort === 'count') result = a.count - b.count;
        else if (sort === 'alpha') result = a.name.localeCompare(b.name);
        else if (sort === 'length') result = a.name.length - b.name.length || a.name.localeCompare(b.name);
        else result = a.category.localeCompare(b.category) || a.name.localeCompare(b.name);
        return order === 'desc' ? -result : result;
      });

    return filtered;
  }

  async function fetchTags(options: { showLoader?: boolean } = {}) {
    const { showLoader = true } = options;
    const shouldClearLoader = showLoader || loading;
    if (showLoader) loading = true;
    if (favoriteOnly || pinnedOnly) {
      tagListRequestController?.abort();
      await fetchFavoriteTags();
      const favoriteResults = getFavoriteTagResults();
      tags = favoriteResults.slice(offset, offset + PAGE_SIZE);
      total = favoriteResults.length;
      if (shouldClearLoader) loading = false;
      return;
    }

    const params: Record<string, string | number> = {
      source: tagSource,
      sort,
      order,
      offset,
      limit: PAGE_SIZE,
      min_count: minCount,
    };
    if (category) params.category = category;
    if (searchQ.trim()) params.q = searchQ.trim();
    if (sort === 'alpha' && alphabetView !== 'off' && selectedAlphabetLetter) params.letter = selectedAlphabetLetter;

    const requestId = ++tagListRequestSerial;
    tagListRequestController?.abort();
    const requestController = new AbortController();
    tagListRequestController = requestController;
    const cacheKey = `tags:${JSON.stringify(params)}`;
    const cached = getCachedView<PaginatedTags>(cacheKey);
    if (cached) {
      tags = cached.tags;
      total = cached.total;
      loading = false;
    }
    try {
      const res = await api.getTags(params as any, requestController.signal);
      if (requestId !== tagListRequestSerial) return;
      tags = res.tags;
      total = res.total;
      cacheView(cacheKey, res);
    } catch (error) {
      if (!(error instanceof DOMException && error.name === 'AbortError')) throw error;
    } finally {
      if (requestId === tagListRequestSerial && shouldClearLoader) loading = false;
    }
  }

  function onSearch() {
    clearTimeout(searchDebounce);
    searchDebounce = setTimeout(() => {
      offset = 0;
      fetchTags();
    }, 300);
  }

  function setSort(s: typeof sort) {
    if (sort === s) {
      order = order === 'desc' ? 'asc' : 'desc';
    } else {
      sort = s;
      order = sortOptions.find(o => o.value === s)!.defaultOrder as 'asc' | 'desc';
    }
    offset = 0;
    if (s !== 'alpha') {
      alphabetView = 'off';
      selectedAlphabetLetter = null;
    }
    fetchTags();
  }

  function setAlphabetView(view: 'columns' | 'sections') {
    alphabetView = view;
    selectedAlphabetLetter = null;
    offset = 0;
    fetchTags();
  }

  function setAlphabetLetter(letter: string) {
    selectedAlphabetLetter = selectedAlphabetLetter === letter ? null : letter;
    offset = 0;
    fetchTags();
  }

  function setCategory(c: string | null) {
    category = c;
    offset = 0;
    fetchTags();
  }

  function toggleUserAddedOnly() {
    tagSource = tagSource === 'user' ? 'danbooru' : 'user';
    favoriteOnly = false;
    pinnedOnly = false;
    offset = 0;
    fetchTags();
  }

  function toggleComboMenu() {
    showComboMenu = !showComboMenu;
  }

  function onWindowClick(event: MouseEvent) {
    const target = event.target;
    if (!(target instanceof Node)) {
      showComboMenu = false;
      return;
    }
    if (comboButton?.contains(target) || comboMenu?.contains(target)) return;
    showComboMenu = false;
  }

  function goPage(dir: 'prev' | 'next') {
    if (dir === 'prev' && offset > 0) offset = Math.max(0, offset - PAGE_SIZE);
    else if (dir === 'next' && offset + PAGE_SIZE < total) offset += PAGE_SIZE;
    fetchTags();
  }

  function goToPage(page: number) {
    offset = (page - 1) * PAGE_SIZE;
    fetchTags();
  }

  function toggleFavoriteOnly() {
    favoriteOnly = !favoriteOnly;
    if (!favoriteOnly) pinnedOnly = false;
    if (favoriteOnly) tagSource = 'danbooru';
    offset = 0;
    fetchTags();
  }

  function togglePinnedOnly() {
    pinnedOnly = !pinnedOnly;
    if (pinnedOnly) {
      favoriteOnly = true;
      tagSource = 'danbooru';
    }
    offset = 0;
    fetchTags();
  }

  function tagFilterTerm(tag: TagInfo, source: 'danbooru' | 'user' = tagSource) {
    return source === 'user' ? `user:${tag.name}` : tag.name;
  }

  function emptyWikiInfo(tag: TagInfo, error: string | null = null): TagWikiInfo {
    return {
      tag_name: tag.name,
      title: tag.name,
      other_names: [],
      description: [],
      examples: [],
      post_references: [],
      sections: [],
      aliases: [],
      implications: [],
      artist_id: null,
      artist_name: null,
      artist_group_name: null,
      artist_urls: [],
      available: false,
      cached_at: null,
      error,
    };
  }

  async function fetchSelectedTagWiki(tag: TagInfo, source: 'danbooru' | 'user') {
    const requestId = ++wikiRequestSerial;
    wikiLoading = true;
    wikiError = '';
    wikiInfo = null;

    if (source === 'user') {
      wikiInfo = emptyWikiInfo(tag, 'User-added tags do not have Danbooru wiki info.');
      wikiLoading = false;
      return;
    }

    try {
      const result = await api.getTagWiki(tag.name, { category: tag.category });
      if (requestId !== wikiRequestSerial) return;
      wikiInfo = result;
    } catch (e) {
      if (requestId !== wikiRequestSerial) return;
      console.error('Failed to load tag wiki:', e);
      wikiError = 'Could not load tag info';
      wikiInfo = emptyWikiInfo(tag, wikiError);
    } finally {
      if (requestId === wikiRequestSerial) wikiLoading = false;
    }
  }

  async function fetchSelectedTagImages(tag: TagInfo, source: 'danbooru' | 'user', nextOffset = 0) {
    const requestId = ++tagImageRequestSerial;
    tagImagesLoading = true;
    try {
      const result = await api.getImages({
        q: tagFilterTerm(tag, source),
        sort: 'score',
        order: 'desc',
        offset: nextOffset,
        limit: TAG_IMAGE_PAGE_SIZE,
      });
      if (requestId !== tagImageRequestSerial) return;
      tagImages = result.images;
      tagImageTotal = result.total;
      tagImageOffset = result.offset;
    } catch (e) {
      if (requestId === tagImageRequestSerial) {
        console.error('Failed to load tag images:', e);
        tagImages = [];
        tagImageTotal = 0;
        tagImageOffset = 0;
      }
    } finally {
      if (requestId === tagImageRequestSerial) tagImagesLoading = false;
    }
  }

  function useTag(tag: TagInfo) {
    const source = tagSource === 'user' ? 'user' : 'danbooru';
    openTagDetail(tag, source);
  }

  function openTagDetail(tag: TagInfo, source: 'danbooru' | 'user', updateRequest = true) {
    requestedTagDetailKey = `${source}:${tag.category}:${tag.name}`;
    selectedTag = tag;
    selectedTagSource = source;
    wikiInfo = null;
    wikiError = '';
    tagImages = [];
    tagImageTotal = 0;
    tagImageOffset = 0;
    if (updateRequest) {
      browseTagSelection.set({
        name: tag.name,
        category: tag.category,
        count: tag.count,
        source,
      });
    }
    void fetchSelectedTagImages(tag, source);
  }

  function useWikiLinkedTag(tagName: string) {
    openTagDetail({ name: tagName, category: 'unknown', count: 0 }, 'danbooru');
  }

  $: requestedTagDetail = $browseTagSelection;
  $: incomingTagDetailKey = requestedTagDetail
    ? `${requestedTagDetail.source}:${requestedTagDetail.category}:${requestedTagDetail.name}`
    : '';
  $: if (requestedTagDetail && incomingTagDetailKey !== requestedTagDetailKey) {
    openTagDetail({
      name: requestedTagDetail.name,
      category: requestedTagDetail.category,
      count: requestedTagDetail.count,
    }, requestedTagDetail.source, false);
  }
  $: if (!requestedTagDetail && requestedTagDetailKey && selectedTag) {
    requestedTagDetailKey = '';
    selectedTag = null;
    wikiInfo = null;
    wikiError = '';
    tagImages = [];
    tagImageTotal = 0;
    tagImageOffset = 0;
  }

  function clearSelectedTag() {
    requestedTagDetailKey = '';
    browseTagSelection.set(null);
    selectedTag = null;
    wikiInfo = null;
    wikiError = '';
    tagImages = [];
    tagImageTotal = 0;
    tagImageOffset = 0;
  }

  function goTagImagePage(dir: 'prev' | 'next') {
    if (!selectedTag) return;
    const nextOffset = dir === 'prev'
      ? Math.max(0, tagImageOffset - TAG_IMAGE_PAGE_SIZE)
      : tagImageOffset + TAG_IMAGE_PAGE_SIZE;
    if (nextOffset < 0 || nextOffset >= tagImageTotal) return;
    fetchSelectedTagImages(selectedTag, selectedTagSource, nextOffset);
  }

  function openExampleImage(localPostId: number | null) {
    if (localPostId !== null) selectedImageId.set(localPostId);
  }

  function postReferenceFor(postId: number | null) {
    if (postId === null || !wikiInfo) return null;
    return wikiInfo.post_references.find(post => post.danbooru_post_id === postId) ?? null;
  }

  function removeActiveTag(tagName: string) {
    activeTags.update(tags => tags.filter(tag => tag !== tagName));
  }

  function clearActiveTags() {
    activeTags.set([]);
  }

  async function toggleFavTag(tagName: string, cat: string) {
    const key = tagKey(cat, tagName);
    const res = await api.toggleFavoriteTag(tagName, cat);
    const nextFavorites = new Set(favTagSet);
    const nextPinned = new Set(pinnedTagSet);
    if (res.status === 'added') {
      const addedAt = new Date().toISOString();
      nextFavorites.add(key);
      upsertFavoriteTag(tagName, cat, { favorite_added_at: addedAt, pinned_at: null });
      setVisibleTagMeta(tagName, cat, { favorite_added_at: addedAt, pinned_at: null });
    } else {
      nextFavorites.delete(key);
      nextPinned.delete(key);
      removeFavoriteTag(tagName, cat);
      setVisibleTagMeta(tagName, cat, { favorite_added_at: null, pinned_at: null });
    }
    favTagSet = nextFavorites;
    pinnedTagSet = nextPinned;
    syncFavoriteTagPage();
    notifyTagRefresh();
  }

  async function togglePinTag(tag: TagInfo) {
    const key = tagKey(tag.category, tag.name);
    if (!favTagSet.has(key)) return;
    const res = await api.toggleFavoriteTagPin(tag.name, tag.category);
    const nextPinned = new Set(pinnedTagSet);
    const pinnedAt = res.status === 'pinned' ? (res.pinned_at ?? new Date().toISOString()) : null;
    if (res.status === 'pinned') {
      nextPinned.add(key);
    } else {
      nextPinned.delete(key);
    }
    pinnedTagSet = nextPinned;
    upsertFavoriteTag(tag.name, tag.category, { pinned_at: pinnedAt });
    setVisibleTagMeta(tag.name, tag.category, { pinned_at: pinnedAt });
    syncFavoriteTagPage();
    notifyTagRefresh();
  }

  async function toggleSelectedArtistFollow() {
    if (!selectedTag || selectedTag.category !== 'artist' || artistFollowBusy) return;
    artistFollowBusy = true;
    try {
      const next = new Set(followedArtistTags);
      if (selectedArtistFollowed) {
        await api.unfollowArtist(selectedTag.name);
        next.delete(selectedTag.name);
      } else {
        await api.followArtist(selectedTag.name, wikiInfo?.title || displayTag(selectedTag.name));
        next.add(selectedTag.name);
      }
      followedArtistTags = next;
      notifyArtistFollowRefresh();
    } finally {
      artistFollowBusy = false;
    }
  }

  function comboTagsFrom(tags: string[]) {
    const seen = new Set<string>();
    return tags
      .map(tag => tag.trim())
      .filter(tag => {
        if (!tag || seen.has(tag)) return false;
        seen.add(tag);
        return true;
      });
  }

  function displayTag(tag: string) {
    return tag.replace(/_/g, ' ');
  }

  function defaultComboName() {
    const label = currentComboTags.slice(0, 4).map(displayTag).join(' + ');
    return currentComboTags.length > 4 ? `${label} + ${currentComboTags.length - 4}` : label;
  }

  async function saveTagCombo() {
    const tags = currentComboTags;
    if (tags.length < 2 || comboBusy) return;
    comboBusy = true;
    try {
      const combo = await api.createFavoriteTagCombo(tags, comboName.trim() || defaultComboName());
      tagCombos = [combo, ...tagCombos.filter(item => item.id !== combo.id)];
      comboName = '';
      showComboMenu = true;
    } finally {
      comboBusy = false;
    }
  }

  function useTagCombo(combo: FavoriteTagCombo) {
    activeTags.set(combo.tags);
    viewMode.set('gallery');
  }

  async function removeTagCombo(combo: FavoriteTagCombo) {
    if (comboBusy) return;
    comboBusy = true;
    try {
      await api.deleteFavoriteTagCombo(combo.id);
      tagCombos = tagCombos.filter(item => item.id !== combo.id);
    } finally {
      comboBusy = false;
    }
  }

  $: currentPage = Math.floor(offset / PAGE_SIZE) + 1;
  $: totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  $: tagImagePage = Math.floor(tagImageOffset / TAG_IMAGE_PAGE_SIZE) + 1;
  $: tagImageTotalPages = Math.max(1, Math.ceil(tagImageTotal / TAG_IMAGE_PAGE_SIZE));
  $: tagImageStart = tagImageTotal === 0 ? 0 : tagImageOffset + 1;
  $: tagImageEnd = Math.min(tagImageOffset + tagImages.length, tagImageTotal);
  $: tagGridStyle = tagDisplayMode === 'wide'
    ? 'grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));'
    : 'grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));';
  $: selectedImageSize = imageSizeByValue[$imageSize];
  $: tagImageSizeVars = `--image-card-width: ${selectedImageSize.cardWidth}px; --image-card-max-height: ${selectedImageSize.maxHeight}px; --image-grid-min: ${selectedImageSize.gridMin}px;`;
  $: tagImageGridStyle = $fitMode === 'contain'
    ? tagImageSizeVars
    : `${tagImageSizeVars} grid-template-columns: repeat(auto-fill, minmax(min(100%, var(--image-grid-min)), 1fr));`;
  $: alphabetGroups = alphabetLetters
    .map(letter => ({
      letter,
      tags: tags.filter(tag => getTagLetter(tag) === letter),
    }))
    .filter(group => group.tags.length > 0);
  $: currentComboTags = comboTagsFrom($activeTags);
  $: selectedArtistFollowed = Boolean(selectedTag && selectedTag.category === 'artist' && followedArtistTags.has(selectedTag.name));
  $: selectedLocalExamples = wikiInfo?.examples.filter(
    (example): example is TagWikiExample & { file_id: number; local_post_id: number } =>
      example.file_id !== null && example.local_post_id !== null
  ) ?? [];
  $: selectedMissingExamples = wikiInfo?.examples.filter(example => example.file_id === null || example.local_post_id === null) ?? [];

  function getTagLetter(tag: TagInfo): string {
    const first = tag.name.replace(/_/g, ' ').trim().charAt(0).toUpperCase();
    return /^[A-Z]$/.test(first) ? first : '#';
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
</script>

<svelte:window on:click={onWindowClick} />

{#snippet tagCard(tag: TagInfo)}
  <div class="relative flex items-center gap-1 px-2.5 py-1.5 rounded-lg border border-[#2a2a3a] bg-[#1a1a24] hover:bg-[#1e1e2e] transition-colors group">
    <!-- Favorite button -->
    {#if tagSource === 'user'}
      <span class="shrink-0 w-5 h-5 flex items-center justify-center text-[10px] font-semibold text-pink-300" title="User-added tag">U</span>
    {:else}
      <button
        class="shrink-0 w-5 h-5 flex items-center justify-center text-sm transition-colors {favTagSet.has(tag.category + ':' + tag.name) ? 'text-pink-400 hover:text-pink-300' : 'text-gray-600 hover:text-pink-400 opacity-0 group-hover:opacity-100'}"
        on:click={() => toggleFavTag(tag.name, tag.category)}
        title="{favTagSet.has(tag.category + ':' + tag.name) ? 'Unfavorite' : 'Favorite'}"
      >{favTagSet.has(tag.category + ':' + tag.name) ? '♥' : '♡'}</button>
    {/if}

    {#if tagSource !== 'user' && favTagSet.has(tag.category + ':' + tag.name)}
      <button
        class="shrink-0 w-5 h-5 flex items-center justify-center rounded text-xs transition-colors {pinnedTagSet.has(tag.category + ':' + tag.name) ? 'text-amber-300' : 'text-gray-600 opacity-0 hover:text-amber-300 group-hover:opacity-100'}"
        on:click|stopPropagation={() => togglePinTag(tag)}
        title="{pinnedTagSet.has(tag.category + ':' + tag.name) ? 'Unpin from front' : 'Pin to front'}"
      >
        <svg class="h-3.5 w-3.5 {pinnedTagSet.has(tag.category + ':' + tag.name) ? 'fill-current' : ''}" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 4l5 5-4 1-4.5 4.5V18L9 20.5 3.5 15 6 12.5h3.5L14 8l1-4z"/>
        </svg>
      </button>
    {/if}

    <!-- Tag name + filter action -->
    <button
      class="flex-1 min-w-0 text-left text-sm transition-colors {tagDisplayMode === 'wrap' ? 'whitespace-normal break-words leading-snug' : 'truncate'} {categoryColors[tag.category]?.split(' ')[1] || 'text-gray-300'}"
      on:click={() => useTag(tag)}
      title="Open info for {tagSource === 'user' ? 'user-added tag ' + tag.name : tag.name}"
    >{tag.name.replace(/_/g, ' ')}</button>

    {#if tagDisplayMode === 'compact'}
      <div class="pointer-events-none absolute left-8 right-2 top-full mt-1 z-20 hidden rounded border border-[#2a2a3a] bg-[#1e1e2e] px-2 py-1 text-xs text-gray-200 shadow-xl group-hover:block">
        {tag.name.replace(/_/g, ' ')}
      </div>
    {/if}

    <!-- Category badge -->
    <span class="shrink-0 px-1.5 py-0.5 text-[9px] rounded uppercase tracking-wider {categoryColors[tag.category] || 'bg-gray-500/20 text-gray-400 border-gray-500/30'} border">
      {tag.category.slice(0, 4)}
    </span>

    <!-- Count -->
    <span class="shrink-0 text-xs text-gray-600 tabular-nums w-12 text-right">{tag.count.toLocaleString()}</span>
  </div>
{/snippet}

{#snippet wikiPostReference(post: TagWikiExample | null, postId: number)}
  {#if post?.file_id && post.local_post_id}
    <button
      type="button"
      class="mx-1 inline-flex h-16 w-14 align-middle items-end justify-center overflow-hidden rounded border border-[#2a2a3a] bg-[#1a1a24] bg-cover bg-center text-[9px] text-gray-100 shadow transition-colors hover:border-sky-500/50"
      style={`background-image: linear-gradient(to top, rgba(0,0,0,.78), rgba(0,0,0,0) 60%), url('${thumbnailUrl(post.file_id, 160, post.thumbnail_token || undefined)}')`}
      title="Open local image #{postId}"
      on:click={() => openExampleImage(post.local_post_id)}
    >
      <span class="mb-0.5 rounded bg-black/45 px-1">#{postId}</span>
    </button>
  {:else}
    <a
      class="mx-1 inline-flex align-middle rounded border border-[#2a2a3a] bg-[#15151d] px-1.5 py-0.5 text-[11px] text-gray-500 transition-colors hover:border-sky-500/40 hover:text-sky-300"
      href={post?.post_url || `https://danbooru.donmai.us/posts/${postId}`}
      target="_blank"
      rel="noreferrer"
      title="Open Danbooru post #{postId}"
    >#{postId}</a>
  {/if}
{/snippet}

{#snippet wikiLine(line: TagWikiTextLine)}
  {#each line.parts as part}
    {#if part.post_id}
      {@render wikiPostReference(postReferenceFor(part.post_id), part.post_id)}
    {:else if part.tag}
      <button
        type="button"
        class="text-sky-400 transition-colors hover:text-sky-300 hover:underline"
        on:click={() => part.tag && useWikiLinkedTag(part.tag)}
      >{part.text}</button>
    {:else}
      {part.text}
    {/if}
  {/each}
{/snippet}

{#if selectedTag}
  <div class="flex h-full flex-col overflow-hidden">
    <div class="flex-1 overflow-y-auto">
      <TagBrowseHeader
        tag={{
          name: selectedTag.name,
          category: selectedTag.category,
          count: selectedTag.count,
          source: selectedTagSource,
        }}
        images={tagImages}
        total={tagImageTotal}
        loading={tagImagesLoading}
        showBackAction={true}
        on:back={clearSelectedTag}
      />

      <section class="p-6">
        <div class="mb-4 flex flex-wrap items-center justify-between gap-3">
          <h3 class="text-xl font-semibold text-gray-100">
            Posts
            <span class="ml-2 text-sm font-normal text-gray-500">{tagImageTotal.toLocaleString()} local images</span>
          </h3>
          {#if tagImageTotal > TAG_IMAGE_PAGE_SIZE}
            <div class="text-xs text-gray-500">Page {tagImagePage} of {tagImageTotalPages}</div>
          {/if}
        </div>

        {#if tagImagesLoading && tagImages.length === 0}
          <div class="flex items-center justify-center py-16">
            <div class="h-8 w-8 animate-spin rounded-full border-2 border-purple-500 border-t-transparent"></div>
          </div>
        {:else if tagImages.length === 0}
          <div class="py-16 text-center text-gray-500">No local images found for this tag</div>
        {:else}
          <div
            style={tagImageGridStyle}
            class="{$fitMode === 'contain' ? 'flex flex-wrap items-end justify-center gap-3' : 'grid gap-3'}"
          >
            {#each tagImages as image (image.id)}
              <ImageCard
                {image}
                on:select={(event) => selectedImageId.set(event.detail)}
                on:longselect={(event) => selectedImageId.set(event.detail)}
              />
            {/each}
          </div>
        {/if}

        {#if tagImageTotal > TAG_IMAGE_PAGE_SIZE}
          <div class="mt-4 flex flex-wrap items-center justify-center gap-2">
            <button
              class="rounded-lg border px-3 py-1.5 text-sm transition-colors {tagImageOffset > 0 ? 'border-[#2a2a3a] text-gray-400 hover:bg-[#1e1e2e]' : 'cursor-not-allowed border-transparent text-gray-600'}"
              disabled={tagImageOffset === 0 || tagImagesLoading}
              on:click={() => goTagImagePage('prev')}
            >Previous</button>
            <div class="px-2 py-1 text-xs text-gray-500">
              {tagImageStart.toLocaleString()}-{tagImageEnd.toLocaleString()} of {tagImageTotal.toLocaleString()}
            </div>
            <button
              class="rounded-lg border px-3 py-1.5 text-sm transition-colors {tagImageOffset + TAG_IMAGE_PAGE_SIZE < tagImageTotal ? 'border-[#2a2a3a] text-gray-400 hover:bg-[#1e1e2e]' : 'cursor-not-allowed border-transparent text-gray-600'}"
              disabled={tagImageOffset + TAG_IMAGE_PAGE_SIZE >= tagImageTotal || tagImagesLoading}
              on:click={() => goTagImagePage('next')}
            >Next</button>
          </div>
        {/if}
      </section>
    </div>
  </div>
{:else}
<div class="h-full flex flex-col overflow-hidden">
  <div class="flex-1 overflow-y-auto">
    {#if !selectedTag}
    <!-- Header -->
    <div class="px-6 py-4 border-b border-[#2a2a3a] bg-[#13131b]">
      <div class="flex items-center justify-between mb-3">
        <h2 class="text-lg font-semibold text-gray-200">
          Tags
          <span class="text-sm font-normal text-gray-500 ml-2">{total.toLocaleString()} tags</span>
        </h2>
        <div class="flex items-center gap-2">
          <div class="relative">
            <button
              bind:this={comboButton}
              class="flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs transition-colors {showComboMenu ? 'border-pink-500/40 bg-pink-600/20 text-pink-200' : 'border-[#2a2a3a] text-gray-400 hover:bg-[#1e1e2e]'}"
              on:click={toggleComboMenu}
              title="Tag combos"
            >
              <svg class="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 7h.01M7 12h.01M7 17h.01M11 7h6M11 12h6M11 17h6"/>
              </svg>
              Combos
              {#if tagCombos.length > 0}
                <span class="rounded bg-pink-500/20 px-1 text-[10px] text-pink-200">{tagCombos.length}</span>
              {/if}
            </button>

            {#if showComboMenu}
              <div
                bind:this={comboMenu}
                class="absolute right-0 top-full z-40 mt-2 w-[min(420px,calc(100vw-2rem))] rounded-lg border border-[#2a2a3a] bg-[#171720] p-3 shadow-xl"
              >
                {#if currentComboTags.length >= 2}
                  <div class="mb-2 flex gap-2">
                    <input
                      type="text"
                      bind:value={comboName}
                      placeholder={defaultComboName()}
                      class="h-8 min-w-0 flex-1 rounded-lg border border-[#2a2a3a] bg-[#1a1a24] px-2 text-xs text-gray-300 outline-none focus:border-pink-500/50"
                      on:keydown={(e) => e.key === 'Enter' && saveTagCombo()}
                    />
                    <button
                      class="h-8 shrink-0 rounded-lg border border-pink-500/30 bg-pink-600/20 px-2.5 text-xs text-pink-300 transition-colors hover:bg-pink-600/30 disabled:opacity-50"
                      disabled={comboBusy}
                      on:click={saveTagCombo}
                    >Save</button>
                  </div>
                  <div class="mb-2 flex flex-wrap gap-1">
                    {#each currentComboTags as tag}
                      <span class="rounded border border-purple-500/30 bg-purple-600/15 px-1.5 py-0.5 text-xs text-purple-200">
                        {displayTag(tag)}
                      </span>
                    {/each}
                  </div>
                {/if}

                {#if tagCombos.length > 0}
                  <div class="max-h-64 space-y-1 overflow-y-auto pr-1">
                    {#each tagCombos as combo}
                      <div class="flex items-center rounded-lg border border-[#2a2a3a] bg-[#1a1a24]">
                        <button
                          class="min-w-0 flex-1 truncate px-2 py-1.5 text-left text-xs text-pink-200 hover:text-pink-100"
                          on:click={() => useTagCombo(combo)}
                          title={combo.tags.map(displayTag).join(' + ')}
                        >{combo.name}</button>
                        <button
                          class="px-2 py-1.5 text-pink-300/70 transition-colors hover:text-pink-200"
                          disabled={comboBusy}
                          on:click|stopPropagation={() => removeTagCombo(combo)}
                          title="Remove combo"
                        >
                          <svg class="h-3 w-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
                          </svg>
                        </button>
                      </div>
                    {/each}
                  </div>
                {:else if currentComboTags.length < 2}
                  <div class="py-4 text-center text-xs text-gray-500">No combos</div>
                {/if}
              </div>
            {/if}
          </div>

          <div class="text-xs text-gray-500">
            Page {currentPage} of {totalPages}
          </div>
        </div>
      </div>

      {#if $activeTags.length > 0}
        <div class="mb-3 flex flex-wrap items-center gap-1.5">
          <span class="mr-1 text-xs text-gray-500">Searched:</span>
          {#each $activeTags as tag}
            <span class="inline-flex max-w-full items-center rounded-lg border border-purple-500/30 bg-purple-600/15 text-purple-200">
              <span class="min-w-0 truncate px-2 py-1 text-xs">{displayTag(tag)}</span>
              <button
                class="px-1.5 py-1 text-purple-200/70 transition-colors hover:text-purple-100"
                on:click={() => removeActiveTag(tag)}
                title="Remove tag"
              >
                <svg class="h-3 w-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
                </svg>
              </button>
            </span>
          {/each}
          <button
            class="ml-1 rounded-lg border border-[#2a2a3a] px-2 py-1 text-xs text-gray-500 transition-colors hover:bg-[#1e1e2e] hover:text-gray-300"
            on:click={clearActiveTags}
          >Clear</button>
        </div>
      {/if}

    <div class="flex flex-wrap items-start gap-3">
      <div class="w-full max-w-3xl">
        <!-- Search -->
        <div class="relative mb-3">
          <svg class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>
          </svg>
          <input
            type="text"
            placeholder="Search tags..."
            class="w-full pl-10 pr-3 py-2 bg-[#1a1a24] border border-[#2a2a3a] rounded-lg text-sm text-gray-300 placeholder-gray-600 focus:outline-none focus:border-purple-500/50"
            bind:value={searchQ}
            on:input={onSearch}
          />
        </div>

        <!-- Filter controls -->
        <div class="flex items-start justify-between gap-4">
          <div class="min-w-0 space-y-2">
            <div class="flex flex-wrap items-center gap-1.5">
              <span class="text-xs text-gray-500 mr-1">Filters:</span>
              <button
                class="px-2.5 py-1 text-xs rounded-lg border transition-colors {category === null ? 'bg-purple-600/20 text-purple-300 border-purple-500/30' : 'border-[#2a2a3a] text-gray-400 hover:bg-[#1e1e2e]'}"
                on:click={() => setCategory(null)}
              >All</button>
              {#each categories as cat}
                <button
                  class="px-2.5 py-1 text-xs rounded-lg border capitalize transition-colors {category === cat ? categoryColors[cat] : 'border-[#2a2a3a] text-gray-400 hover:bg-[#1e1e2e]'}"
                  on:click={() => setCategory(cat)}
                >{cat}</button>
              {/each}
            </div>

            <div class="flex flex-wrap items-center gap-1.5">
              <span class="text-xs text-gray-500 mr-1">Sort:</span>
              {#each sortOptions as opt}
                <button
                  class="flex items-center gap-1 px-2.5 py-1 text-xs rounded-lg border transition-colors {sort === opt.value ? 'bg-purple-600/20 text-purple-300 border-purple-500/30' : 'border-[#2a2a3a] text-gray-400 hover:bg-[#1e1e2e]'}"
                  on:click={() => setSort(opt.value)}
                >
                  {opt.label}
                  {#if sort === opt.value}
                    <svg class="w-3 h-3 transition-transform {order === 'asc' ? 'rotate-180' : ''}" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
                    </svg>
                  {/if}
                </button>
                {#if opt.value === 'alpha' && sort === 'alpha'}
                  {#each alphabetOptions as alphabetOpt}
                    <button
                      class="px-2.5 py-1 text-xs rounded-lg border transition-colors {alphabetView === alphabetOpt.value ? 'bg-purple-600/20 text-purple-300 border-purple-500/30' : 'border-[#2a2a3a] text-gray-400 hover:bg-[#1e1e2e]'}"
                      on:click={() => setAlphabetView(alphabetOpt.value)}
                    >{alphabetOpt.label}</button>
                  {/each}
                {/if}
              {/each}
            </div>

            <div class="flex flex-wrap items-center gap-1.5">
              <span class="text-xs text-gray-500 mr-1">Display:</span>
              {#each displayOptions as opt}
                <button
                  class="px-2.5 py-1 text-xs rounded-lg border transition-colors {tagDisplayMode === opt.value ? 'bg-purple-600/20 text-purple-300 border-purple-500/30' : 'border-[#2a2a3a] text-gray-400 hover:bg-[#1e1e2e]'}"
                  on:click={() => tagDisplayMode = opt.value}
                >{opt.label}</button>
              {/each}
            </div>

          </div>

          <div class="shrink-0 flex flex-wrap items-center gap-1.5">
            <button
              class="flex items-center gap-1 px-2.5 py-1 text-xs rounded-lg border transition-colors {favoriteOnly ? 'bg-pink-600/20 text-pink-300 border-pink-500/30' : 'border-[#2a2a3a] text-gray-400 hover:bg-[#1e1e2e]'}"
              on:click={toggleFavoriteOnly}
              title="{favoriteOnly ? 'Show all tags' : 'Show favorited tags'}"
            >
              <svg class="w-3 h-3" fill="currentColor" viewBox="0 0 24 24">
                <path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/>
              </svg>
              Favorited
            </button>
            <button
              class="flex items-center gap-1 px-2.5 py-1 text-xs rounded-lg border transition-colors {tagSource === 'user' ? 'bg-pink-600/20 text-pink-300 border-pink-500/30' : 'border-[#2a2a3a] text-gray-400 hover:bg-[#1e1e2e]'}"
              on:click={toggleUserAddedOnly}
              title="{tagSource === 'user' ? 'Show all tags' : 'Show user-added tags'}"
            >
              <span class="text-[10px] font-semibold leading-none">U</span>
              User-added
            </button>
            <button
              class="flex items-center gap-1 px-2.5 py-1 text-xs rounded-lg border transition-colors {pinnedOnly ? 'bg-amber-600/20 text-amber-300 border-amber-500/30' : 'border-[#2a2a3a] text-gray-400 hover:bg-[#1e1e2e]'}"
              on:click={togglePinnedOnly}
              title="{pinnedOnly ? 'Show all favorited tags' : 'Show pinned favorited tags'}"
            >
              <svg class="h-3 w-3 {pinnedOnly ? 'fill-current' : ''}" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 4l5 5-4 1-4.5 4.5V18L9 20.5 3.5 15 6 12.5h3.5L14 8l1-4z"/>
              </svg>
              Pinned
            </button>
          </div>
        </div>
      </div>

      <div class="flex items-center gap-1.5">
        <span class="text-xs text-gray-500">Min:</span>
        <input
          type="number"
          min="1"
          class="w-16 px-2 py-2 bg-[#1a1a24] border border-[#2a2a3a] rounded-lg text-sm text-gray-300 focus:outline-none focus:border-purple-500/50"
          bind:value={minCount}
          on:change={() => { offset = 0; fetchTags(); }}
        />
      </div>
    </div>

    </div>
    {/if}

    <!-- Tags grid -->
    <div class="p-6">
      {#if loading}
        <div class="flex items-center justify-center h-32">
          <div class="w-6 h-6 border-2 border-purple-500 border-t-transparent rounded-full animate-spin"></div>
        </div>
      {:else}
        {#if sort === 'alpha' && alphabetView !== 'off'}
          <div class="mb-5 flex flex-wrap items-center justify-center gap-2">
            {#each alphabetLetters as letter}
              <button
                class="h-9 min-w-9 rounded-lg border px-3 text-sm font-medium transition-colors {selectedAlphabetLetter === letter ? 'bg-purple-600/25 text-purple-200 border-purple-500/40 shadow-sm shadow-purple-900/20' : 'border-[#2a2a3a] text-gray-400 hover:bg-[#1e1e2e] hover:text-gray-100 hover:border-purple-500/30'}"
                on:click={() => setAlphabetLetter(letter)}
                title="{selectedAlphabetLetter === letter ? 'Clear letter filter' : 'Show ' + letter + ' tags'}"
              >{letter}</button>
            {/each}
          </div>
        {/if}

        {#if tags.length === 0}
          <div class="text-center text-gray-500 py-12">No tags found</div>
        {:else if sort === 'alpha' && alphabetView === 'columns'}
          <div class="columns-1 gap-2 md:columns-2 xl:columns-3 2xl:columns-4">
            {#each alphabetGroups as group}
              <div class="mb-1.5 mt-3 flex items-center gap-2 break-inside-avoid [break-after:avoid] first:mt-0">
                <div class="flex h-6 min-w-6 items-center justify-center rounded border border-purple-500/30 bg-purple-600/20 px-1.5 text-xs font-medium text-purple-300">
                  {group.letter}
                </div>
                <span class="text-xs text-gray-600">{group.tags.length.toLocaleString()}</span>
              </div>
              {#each group.tags as tag}
                <div class="mb-1.5 break-inside-avoid">
                  {@render tagCard(tag)}
                </div>
              {/each}
            {/each}
          </div>
        {:else if sort === 'alpha' && alphabetView === 'sections'}
          <div class="space-y-5">
            {#each alphabetGroups as group}
              <section>
                <div class="mb-2 flex items-center gap-2">
                  <div class="flex h-6 w-6 items-center justify-center rounded border border-purple-500/30 bg-purple-600/20 text-xs font-medium text-purple-300">
                    {group.letter}
                  </div>
                  <div class="h-px flex-1 bg-[#2a2a3a]"></div>
                  <span class="text-xs text-gray-600">{group.tags.length.toLocaleString()}</span>
                </div>
                <div class="grid gap-1.5" style={tagGridStyle}>
                  {#each group.tags as tag}
                    {@render tagCard(tag)}
                  {/each}
                </div>
              </section>
            {/each}
          </div>
        {:else}
          <div class="grid gap-1.5" style={tagGridStyle}>
            {#each tags as tag}
              {@render tagCard(tag)}
            {/each}
          </div>
        {/if}
      {/if}
    </div>

    <!-- Pagination -->
    {#if totalPages > 1}
      <div class="px-6 py-3 border-t border-[#2a2a3a] bg-[#13131b] flex items-center justify-center gap-2">
        <button
          class="px-3 py-1.5 text-sm rounded-lg border transition-colors {offset > 0 ? 'border-[#2a2a3a] text-gray-400 hover:bg-[#1e1e2e]' : 'border-transparent text-gray-600 cursor-not-allowed'}"
          disabled={offset === 0}
          on:click={() => goPage('prev')}
        >Previous</button>

        <div class="flex gap-1 mx-1">
          {#each visiblePages(currentPage, totalPages) as p}
            {#if p === '...'}
              <span class="px-2 py-1 text-xs text-gray-600">...</span>
            {:else}
              <button
                class="px-2.5 py-1 text-xs rounded-lg border transition-colors {p === currentPage ? 'bg-purple-600/20 text-purple-300 border-purple-500/30' : 'border-[#2a2a3a] text-gray-400 hover:bg-[#1e1e2e]'}"
                on:click={() => goToPage(p)}
              >{p}</button>
            {/if}
          {/each}
        </div>

        <button
          class="px-3 py-1.5 text-sm rounded-lg border transition-colors {offset + PAGE_SIZE < total ? 'border-[#2a2a3a] text-gray-400 hover:bg-[#1e1e2e]' : 'border-transparent text-gray-600 cursor-not-allowed'}"
          disabled={offset + PAGE_SIZE >= total}
          on:click={() => goPage('next')}
        >Next</button>
      </div>
    {/if}
  </div>
</div>
{/if}
