<script lang="ts">
  import { createEventDispatcher, onMount, tick } from 'svelte';
  import { fly } from 'svelte/transition';
  import { danbooruApi as api, imageFileUrl, thumbnailUrl } from '../api';
  import { type ArtistProfileAsset, type ImageDetail as ImageDetailType, type CollectionInfo, type FolderInfo, type RelatedImageInfo, type TagInfo } from '../apiTypes';
  import { activeCollectionId, activeFolder, activeTags, browseTagSelection, collectionRefreshToken, heartSpamEnabled, imageRefreshToken, mediaPlayback, selectedImageId, tagRefreshToken, viewMode, visibleImageIds } from '../stores';

  export let postId: number | null = null;
  export let profileAsset: ArtistProfileAsset | null = null;

  const dispatch = createEventDispatcher();
  let detail: ImageDetailType | null = null;
  let loading = true;
  let allCollections: CollectionInfo[] = [];
  let allFolders: FolderInfo[] = [];
  let showCollectionMenu = false;
  let showMoveMenu = false;
  let newCollectionName = '';
  let activeUserTagCategory: string | null = null;
  let userTagDraft = '';
  let userTagInput: HTMLInputElement | null = null;
  let userTagSuggestions: TagInfo[] = [];
  let userTagSuggestSerial = 0;
  const MIN_IMAGE_ZOOM = 1;
  const MAX_IMAGE_ZOOM = 5;
  const IMAGE_ZOOM_STEP = 0.2;
  let imageZoom = MIN_IMAGE_ZOOM;
  let imagePanX = 0;
  let imagePanY = 0;
  let imagePanning = false;
  let imagePanMoved = false;
  let zoomSliderDragging = false;
  let suppressNextBackdropClick = false;
  let panStartX = 0;
  let panStartY = 0;
  let panOriginX = 0;
  let panOriginY = 0;
  let userTagSaving = false;
  let userTagError = '';
  let movingFolder = false;
  let moveError = '';
  let openingLocation = false;
  let openLocationError = '';
  let relationRefreshing = false;
  let relationError = '';
  let favoriteBusy = false;
  let favTagSet = new Set<string>();
  let favoriteTagBusy = new Set<string>();
  let favoriteTagError = '';
  let mediaHovered = false;
  let floatingHearts: FloatingHeart[] = [];
  let nextFloatingHeartId = 1;
  let videoEl: HTMLVideoElement | null = null;
  let loadedPostId: number | null = null;
  let loadedProfileAssetId: number | null = null;
  let detailRequestSerial = 0;
  let userTagRefreshSerial = 0;
  let observedTagRefreshToken = -1;
  let observedCollectionRefreshToken = 0;

  type RelationGroup = {
    label: string;
    items: RelatedImageInfo[];
  };

  type FloatingHeart = {
    id: number;
    x: number;
    drift: number;
    rotate: number;
    size: number;
    duration: number;
  };

  const categoryColors: Record<string, string> = {
    artist: 'bg-red-500/20 text-red-300 border-red-500/30 hover:bg-red-500/30',
    character: 'bg-green-500/20 text-green-300 border-green-500/30 hover:bg-green-500/30',
    copyright: 'bg-copyright-500/20 text-copyright-300 border-copyright-500/30 hover:bg-copyright-500/30',
    general: 'bg-blue-500/20 text-blue-300 border-blue-500/30 hover:bg-blue-500/30',
    meta: 'bg-yellow-500/20 text-yellow-300 border-yellow-500/30 hover:bg-yellow-500/30',
    user: 'bg-pink-500/20 text-pink-300 border-pink-500/30 hover:bg-pink-500/30',
    unknown: 'bg-gray-500/20 text-gray-300 border-gray-500/30 hover:bg-gray-500/30',
  };
  const ratingLabels: Record<string, string> = { g: 'General', s: 'Sensitive', q: 'Questionable', e: 'Explicit', u: 'Unrated' };
  const categoryOrder = ['artist', 'character', 'copyright', 'general', 'meta', 'unknown'];
  const editableTagCategories = new Set(['artist', 'character', 'copyright', 'general', 'meta']);

  $: fileExt = detail?.ext?.toLowerCase() ?? '';
  $: isGif = fileExt === 'gif';
  $: isVideo = fileExt === 'mp4' || fileExt === 'webm';
  $: originalMediaUrl = detail
    ? imageFileUrl(detail.file_id, detail.thumbnail_token)
    : '';
  $: staticImageUrl = detail
    ? thumbnailUrl(detail.file_id, 1200, detail.thumbnail_token)
    : '';
  $: shouldPlayMedia = $mediaPlayback === 'always' || ($mediaPlayback === 'hover' && mediaHovered);
  $: displayImageUrl = !isGif || shouldPlayMedia
    ? originalMediaUrl
    : staticImageUrl;
  $: currentFolder = detail?.folder || 'root';
  $: folderMoveTargets = allFolders.filter(folder => folder.registered || folder.name !== currentFolder);
  $: imageZoomPercent = Math.round(imageZoom * 100);
  $: showZoomSlider = imageZoom > MIN_IMAGE_ZOOM || zoomSliderDragging;
  $: relationGroups = detail ? [
    { label: 'Parent', items: detail.relations?.parent ? [detail.relations.parent] : [] },
    { label: 'Siblings', items: detail.relations?.siblings ?? [] },
    { label: 'Children', items: detail.relations?.children ?? [] },
  ].filter(group => group.items.length > 0) as RelationGroup[] : [];
  $: showRelationSection = Boolean(detail?.danbooru_post_id);

  $: if (videoEl) {
    if (shouldPlayMedia) {
      videoEl.play().catch(() => undefined);
    } else {
      videoEl.pause();
    }
  }

  onMount(() => {
    if (profileAsset) return;
    refreshCollections().catch(console.error);
    api.getFolders()
      .then(folders => allFolders = folders)
      .catch(console.error);
  });

  function adjustFolderCounts(previousFolder: string, nextFolder: string) {
    if (previousFolder === nextFolder) return;
    let hasNextFolder = false;
    const adjusted = allFolders.map(folder => {
      if (folder.name === previousFolder) {
        return { ...folder, count: Math.max(0, folder.count - 1) };
      }
      if (folder.name === nextFolder) {
        hasNextFolder = true;
        return { ...folder, count: folder.count + 1 };
      }
      return folder;
    });
    if (!hasNextFolder) adjusted.push({ name: nextFolder, selector: nextFolder, count: 1, path: null, registered: false });
    allFolders = adjusted.sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
  }

  $: if ($tagRefreshToken !== observedTagRefreshToken) {
    observedTagRefreshToken = $tagRefreshToken;
    refreshFavoriteTags().catch(console.error);
  }

  $: if ($collectionRefreshToken !== observedCollectionRefreshToken) {
    observedCollectionRefreshToken = $collectionRefreshToken;
    refreshCollections().catch(console.error);
  }

  $: if (!profileAsset && postId !== null && postId !== loadedPostId) {
    loadDetail(postId);
  }

  $: if (profileAsset && profileAsset.id !== loadedProfileAssetId) {
    loadedProfileAssetId = profileAsset.id;
    loading = false;
    detail = null;
    resetImageView();
  }

  async function loadDetail(nextPostId: number) {
    const requestId = ++detailRequestSerial;
    loadedPostId = nextPostId;
    loading = true;
    detail = null;
    resetImageView();
    mediaHovered = false;
    floatingHearts = [];
    userTagError = '';
    activeUserTagCategory = null;
    userTagDraft = '';
    userTagSuggestions = [];
    moveError = '';
    openLocationError = '';
    relationError = '';
    relationRefreshing = false;
    showMoveMenu = false;

    try {
      const nextDetail = await api.getImage(nextPostId);
      if (requestId !== detailRequestSerial) return;
      detail = nextDetail;
    } catch (e) {
      console.error(e);
    } finally {
      if (requestId === detailRequestSerial) {
        loading = false;
      }
    }
  }

  async function toggleFavorite() {
    if (!detail || favoriteBusy) return;
    const fileId = detail.file_id;
    const previousDetail = detail;
    const nextIsFavorite = !detail.is_favorite;
    detail = {
      ...detail,
      is_favorite: nextIsFavorite,
      favorite_added_at: nextIsFavorite ? (detail.favorite_added_at ?? new Date().toISOString()) : null,
      favorite_pinned_at: nextIsFavorite ? detail.favorite_pinned_at : null,
    };
    favoriteBusy = true;
    try {
      const result = await api.toggleFavorite(fileId);
      if (!detail || detail.file_id !== fileId) return;
      const isFavorite = result.status === 'added';
      detail = {
        ...detail,
        is_favorite: isFavorite,
        favorite_added_at: result.added_at,
        favorite_pinned_at: isFavorite ? detail.favorite_pinned_at : null,
      };
      imageRefreshToken.update(n => n + 1);
    } catch (e) {
      console.error(e);
      if (detail?.file_id === fileId) detail = previousDetail;
    } finally {
      favoriteBusy = false;
    }
  }

  function addFloatingHeart() {
    const heart: FloatingHeart = {
      id: nextFloatingHeartId++,
      x: 22 + Math.random() * 42,
      drift: -24 + Math.random() * 48,
      rotate: -18 + Math.random() * 36,
      size: 18 + Math.random() * 10,
      duration: 720 + Math.random() * 260,
    };
    floatingHearts = [...floatingHearts, heart];
    window.setTimeout(() => {
      floatingHearts = floatingHearts.filter(item => item.id !== heart.id);
    }, heart.duration + 180);
  }

  async function spamHeart() {
    if (!detail) return;
    const postId = detail.id;
    addFloatingHeart();
    detail = {
      ...detail,
      heart_spam_count: (detail.heart_spam_count ?? 0) + 1,
    };

    try {
      const result = await api.spamHeart(postId);
      if (!detail || detail.id !== postId) return;
      detail = {
        ...detail,
        heart_spam_count: Math.max(detail.heart_spam_count ?? 0, result.heart_spam_count),
      };
      imageRefreshToken.update(n => n + 1);
    } catch (e) {
      console.error(e);
    }
  }

  function filterByHeartSpam() {
    if (!detail || (detail.heart_spam_count ?? 0) < 1) return;
    const term = `hearts:>=${detail.heart_spam_count}`;
    activeTags.update(tags => tags.includes(term) ? tags : [...tags, term]);
  }

  function openTag(tag: string, category: string, source: 'danbooru' | 'user' = 'danbooru') {
    if ($viewMode === 'tags') {
      browseTagSelection.set({ name: tag, category, count: 0, source });
    } else {
      activeTags.update(tags => tags.includes(tag) ? tags : [...tags, tag]);
      activeFolder.set(null);
      activeCollectionId.set(null);
      browseTagSelection.set(null);
      viewMode.set('gallery');
    }
    dispatch('close');
  }

  function favoriteTagKey(category: string, tagName: string) {
    return `${category}:${tagName}`;
  }

  async function refreshFavoriteTags() {
    try {
      const favNames = await api.getFavoriteTagNames();
      favTagSet = new Set(favNames.map(t => favoriteTagKey(t.category, t.name)));
    } catch (e) {
      console.error(e);
    }
  }

  async function refreshCollections() {
    const collections = await api.getCollections();
    allCollections = collections;
    if (!detail) return;
    const byId = new Map(collections.map(collection => [collection.id, collection]));
    detail = {
      ...detail,
      collections: detail.collections.map(collection => {
        const latest = byId.get(collection.id);
        return latest
          ? { ...latest, item_added_at: collection.item_added_at, item_pinned_at: collection.item_pinned_at }
          : collection;
      }),
    };
  }

  async function toggleFavoriteTag(category: string, tagName: string) {
    const key = favoriteTagKey(category, tagName);
    if (favoriteTagBusy.has(key)) return;

    favoriteTagError = '';
    const wasFavorite = favTagSet.has(key);
    const nextBusy = new Set(favoriteTagBusy);
    nextBusy.add(key);
    favoriteTagBusy = nextBusy;

    const optimisticFavorites = new Set(favTagSet);
    if (wasFavorite) {
      optimisticFavorites.delete(key);
    } else {
      optimisticFavorites.add(key);
    }
    favTagSet = optimisticFavorites;

    try {
      const res = await api.toggleFavoriteTag(tagName, category);
      const confirmedFavorites = new Set(favTagSet);
      if (res.status === 'added') {
        confirmedFavorites.add(key);
      } else {
        confirmedFavorites.delete(key);
      }
      favTagSet = confirmedFavorites;
      tagRefreshToken.update(n => n + 1);
    } catch (e) {
      console.error(e);
      const rollbackFavorites = new Set(favTagSet);
      if (wasFavorite) {
        rollbackFavorites.add(key);
      } else {
        rollbackFavorites.delete(key);
      }
      favTagSet = rollbackFavorites;
      favoriteTagError = 'Failed to favorite tag';
    } finally {
      const nextBusyAfterSave = new Set(favoriteTagBusy);
      nextBusyAfterSave.delete(key);
      favoriteTagBusy = nextBusyAfterSave;
    }
  }

  function openRelatedImage(item: RelatedImageInfo) {
    if (item.local_post_id) {
      selectedImageId.set(item.local_post_id);
    }
  }

  function relatedThumbnailUrl(item: RelatedImageInfo) {
    return item.file_id && item.thumbnail_token
      ? thumbnailUrl(item.file_id, 220, item.thumbnail_token)
      : '';
  }

  function relatedPostUrl(item: RelatedImageInfo) {
    return item.post_url || `https://danbooru.donmai.us/posts/${item.danbooru_post_id}`;
  }

  function relatedSubtitle(item: RelatedImageInfo) {
    const parts = [];
    if (item.rating) parts.push(item.rating.toUpperCase());
    if (item.score !== null) parts.push(`★ ${item.score}`);
    if (item.width && item.height) parts.push(`${item.width}x${item.height}`);
    return parts.join(' · ') || (item.local_post_id ? 'Local image' : 'Danbooru only');
  }

  async function refreshRelations() {
    if (!detail || relationRefreshing) return;
    relationRefreshing = true;
    relationError = '';
    try {
      detail = await api.refreshImageRelations(detail.id);
    } catch (e) {
      console.error(e);
      relationError = 'Failed to check Danbooru family';
    } finally {
      relationRefreshing = false;
    }
  }

  function normalizeUserTagInput(value: string) {
    return value.trim().replace(/\s+/g, '_').toLowerCase();
  }

  function userTagsForCategory(category: string) {
    const userTags = detail?.user_tags ?? {};
    return userTags[category] ?? [];
  }

  function cloneUserTags(tags: Record<string, string[]>) {
    return Object.fromEntries(
      Object.entries(tags).map(([category, values]) => [category, [...values]])
    ) as Record<string, string[]>;
  }

  function collectionAddedAt(
    result: { added_at: string | null; added_at_by_file?: Record<string, string | null> },
    fileId: number
  ) {
    return result.added_at_by_file?.[String(fileId)] ?? result.added_at ?? null;
  }

  function setUserTagsForCategory(category: string, tags: string[]) {
    if (!detail) return;
    const nextUserTags = cloneUserTags(detail.user_tags ?? {});
    if (tags.length > 0) {
      nextUserTags[category] = tags;
    } else {
      delete nextUserTags[category];
    }
    detail = { ...detail, user_tags: nextUserTags };
  }

  function hasTagInCategory(category: string, tagName: string) {
    return (detail?.tags[category] ?? []).includes(tagName)
      || userTagsForCategory(category).includes(tagName);
  }

  async function refreshOpenDetail(postId: number, refreshId: number) {
    const nextDetail = await api.getImage(postId, { record_view: false });
    if (refreshId !== userTagRefreshSerial || !detail || detail.id !== postId) return;
    detail = nextDetail;
  }

  async function startUserTagInput(category: string) {
    activeUserTagCategory = category;
    userTagDraft = '';
    userTagSuggestions = [];
    userTagError = '';
    await tick();
    userTagInput?.focus();
  }

  function cancelUserTagInput() {
    activeUserTagCategory = null;
    userTagDraft = '';
    userTagSuggestions = [];
  }

  async function updateUserTagSuggestions() {
    const category = activeUserTagCategory;
    const query = normalizeUserTagInput(userTagDraft);
    const requestId = ++userTagSuggestSerial;
    if (!category || query.length < 1) {
      userTagSuggestions = [];
      return;
    }

    try {
      const suggestions = await api.suggestTags(query, category);
      if (requestId !== userTagSuggestSerial || activeUserTagCategory !== category) return;
      userTagSuggestions = suggestions.filter(tag => !hasTagInCategory(category, tag.name));
    } catch (e) {
      console.error(e);
      if (requestId === userTagSuggestSerial) userTagSuggestions = [];
    }
  }

  async function addUserTag(category: string, value = userTagDraft) {
    if (!detail || userTagSaving) return;
    const postId = detail.id;
    const tagName = normalizeUserTagInput(value);
    if (!tagName) return;

    const refreshId = ++userTagRefreshSerial;
    const previousUserTags = cloneUserTags(detail.user_tags ?? {});
    const currentCategoryTags = previousUserTags[category] ?? [];
    if (!currentCategoryTags.includes(tagName)) {
      setUserTagsForCategory(category, [...currentCategoryTags, tagName].sort());
    }
    cancelUserTagInput();
    userTagSaving = true;
    userTagError = '';
    try {
      const result = await api.addUserImageTag(postId, tagName, category);
      if (!detail || detail.id !== postId) return;
      detail = { ...detail, user_tags: result.tags };
      await refreshOpenDetail(postId, refreshId);
      imageRefreshToken.update(n => n + 1);
    } catch (e) {
      console.error(e);
      if (detail && detail.id === postId) {
        detail = { ...detail, user_tags: previousUserTags };
      }
      userTagError = 'Failed to add user tag';
    } finally {
      userTagSaving = false;
    }
  }

  async function removeUserTag(category: string, tagName: string) {
    if (!detail || userTagSaving) return;
    const postId = detail.id;

    const refreshId = ++userTagRefreshSerial;
    const previousUserTags = cloneUserTags(detail.user_tags ?? {});
    setUserTagsForCategory(category, userTagsForCategory(category).filter(tag => tag !== tagName));
    userTagSaving = true;
    userTagError = '';
    try {
      const result = await api.removeUserImageTag(postId, tagName, category);
      if (!detail || detail.id !== postId) return;
      detail = { ...detail, user_tags: result.tags };
      await refreshOpenDetail(postId, refreshId);
      imageRefreshToken.update(n => n + 1);
    } catch (e) {
      console.error(e);
      if (detail && detail.id === postId) {
        detail = { ...detail, user_tags: previousUserTags };
      }
      userTagError = 'Failed to remove user tag';
    } finally {
      userTagSaving = false;
    }
  }

  function onUserTagKeydown(event: KeyboardEvent, category: string) {
    if (event.key === 'Enter') {
      event.preventDefault();
      addUserTag(category);
    } else if (event.key === 'Escape') {
      event.preventDefault();
      cancelUserTagInput();
    }
  }

  function formatSize(bytes: number | null) {
    if (!bytes) return '-';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  function formatDateTime(value: string | null) {
    if (!value) return '-';
    const date = new Date(value.includes('T') ? value : `${value.replace(' ', 'T')}Z`);
    return date.toLocaleString(undefined, {
      year: 'numeric',
      month: 'numeric',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  }

  function isTextEntryTarget(target: EventTarget | null): boolean {
    if (!(target instanceof HTMLElement)) return false;
    const tagName = target.tagName.toLowerCase();
    return tagName === 'input' || tagName === 'textarea' || tagName === 'select' || target.isContentEditable;
  }

  function navigateImage(direction: -1 | 1) {
    if (postId === null || profileAsset) return;
    const ids = $visibleImageIds;
    const currentIndex = ids.indexOf(postId);
    if (currentIndex === -1) return;

    const nextId = ids[currentIndex + direction];
    if (nextId === undefined) return;
    selectedImageId.set(nextId);
  }

  function onKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape') dispatch('close');
    if (isTextEntryTarget(e.target)) return;
    if (profileAsset) return;

    if (e.key === 'ArrowLeft') {
      e.preventDefault();
      navigateImage(-1);
    }
    if (e.key === 'ArrowRight') {
      e.preventDefault();
      navigateImage(1);
    }
  }

  function resetImageView() {
    imageZoom = MIN_IMAGE_ZOOM;
    imagePanX = 0;
    imagePanY = 0;
    imagePanning = false;
    imagePanMoved = false;
    zoomSliderDragging = false;
    suppressNextBackdropClick = false;
  }

  function setImageZoom(nextZoom: number) {
    if (Number.isNaN(nextZoom)) return;

    imageZoom = Math.min(MAX_IMAGE_ZOOM, Math.max(MIN_IMAGE_ZOOM, Number(nextZoom.toFixed(2))));
    if (imageZoom <= MIN_IMAGE_ZOOM) {
      imagePanX = 0;
      imagePanY = 0;
      imagePanning = false;
    }
  }

  function onImageWheel(event: WheelEvent) {
    event.preventDefault();
    const direction = event.deltaY < 0 ? 1 : -1;
    setImageZoom(imageZoom + direction * IMAGE_ZOOM_STEP);
  }

  function onZoomInput(event: Event) {
    setImageZoom(Number((event.currentTarget as HTMLInputElement).value));
  }

  function stopZoomSliderDrag() {
    zoomSliderDragging = false;
  }

  function onImageClick() {
    if (suppressNextBackdropClick || imagePanMoved) {
      suppressNextBackdropClick = false;
      imagePanMoved = false;
      return;
    }

    if (imageZoom <= MIN_IMAGE_ZOOM) {
      setImageZoom(2);
    }
  }

  function onImageBackdropClick(event: MouseEvent) {
    if (event.target !== event.currentTarget) return;
    if (suppressNextBackdropClick) {
      suppressNextBackdropClick = false;
      return;
    }

    dispatch('close');
  }

  function onImagePointerDown(event: PointerEvent) {
    if (imageZoom <= MIN_IMAGE_ZOOM || event.button !== 0) return;

    event.preventDefault();
    imagePanning = true;
    imagePanMoved = false;
    panStartX = event.clientX;
    panStartY = event.clientY;
    panOriginX = imagePanX;
    panOriginY = imagePanY;
    (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
  }

  function onImagePointerMove(event: PointerEvent) {
    if (!imagePanning) return;

    event.preventDefault();
    const deltaX = event.clientX - panStartX;
    const deltaY = event.clientY - panStartY;
    imagePanMoved = imagePanMoved || Math.abs(deltaX) > 3 || Math.abs(deltaY) > 3;
    imagePanX = panOriginX + deltaX;
    imagePanY = panOriginY + deltaY;
  }

  function onImagePointerUp(event: PointerEvent) {
    if (!imagePanning) return;

    imagePanning = false;
    suppressNextBackdropClick = imagePanMoved;
    const target = event.currentTarget as HTMLElement;
    if (target.hasPointerCapture(event.pointerId)) {
      target.releasePointerCapture(event.pointerId);
    }
  }

  async function addToCollection(colId: number) {
    if (!detail) return;
    const fileId = detail.file_id;
    const result = await api.updateCollectionImages(colId, [fileId], 'add');
    if (!detail || detail.file_id !== fileId) return;
    const col = allCollections.find(c => c.id === colId);
    const wasInCollection = detail.collections.some(c => c.id === colId);
    const addedAt = collectionAddedAt(result, fileId);
    if (col) {
      const nextCollections = wasInCollection
        ? detail.collections.map(c => c.id === colId ? { ...c, item_added_at: c.item_added_at ?? addedAt } : c)
        : [...detail.collections, { ...col, item_added_at: addedAt }];
      detail = { ...detail, collections: nextCollections };
      if (!wasInCollection) {
        allCollections = allCollections.map(c => c.id === colId ? { ...c, image_count: c.image_count + 1 } : c);
      }
    }
    showCollectionMenu = false;
    imageRefreshToken.update(n => n + 1);
    collectionRefreshToken.update(n => n + 1);
  }

  async function createAndAdd() {
    if (!detail || !newCollectionName.trim()) return;
    const fileId = detail.file_id;
    const col = await api.createCollection(newCollectionName.trim());
    const result = await api.updateCollectionImages(col.id, [fileId], 'add');
    if (!detail || detail.file_id !== fileId) return;
    const addedAt = collectionAddedAt(result, fileId);
    const collectionWithImage = { ...col, image_count: Math.max(1, col.image_count), item_added_at: addedAt };
    allCollections = [{ ...col, image_count: collectionWithImage.image_count }, ...allCollections];
    detail = { ...detail, collections: [...detail.collections, collectionWithImage] };
    newCollectionName = '';
    showCollectionMenu = false;
    imageRefreshToken.update(n => n + 1);
    collectionRefreshToken.update(n => n + 1);
  }

  async function removeFromCollection(colId: number) {
    if (!detail) return;
    const fileId = detail.file_id;
    const wasInCollection = detail.collections.some(c => c.id === colId);
    await api.updateCollectionImages(colId, [fileId], 'remove');
    if (!detail || detail.file_id !== fileId) return;
    detail = { ...detail, collections: detail.collections.filter(c => c.id !== colId) };
    if (wasInCollection) {
      allCollections = allCollections.map(c => c.id === colId
        ? { ...c, image_count: Math.max(0, c.image_count - 1) }
        : c
      );
    }
    imageRefreshToken.update(n => n + 1);
    collectionRefreshToken.update(n => n + 1);
  }

  async function moveToFolder(folder: FolderInfo) {
    if (!detail || movingFolder) return;
    const imageId = detail.id;
    const previousFolder = detail.folder || 'root';
    movingFolder = true;
    moveError = '';
    try {
      const updated = await api.moveImageToFolder(imageId, folder.selector);
      if (!detail || detail.id !== imageId) return;
      detail = updated;
      adjustFolderCounts(previousFolder, updated.folder || 'root');
      showMoveMenu = false;
      imageRefreshToken.update(n => n + 1);
      api.getFolders()
        .then(folders => allFolders = folders)
        .catch(console.error);
    } catch (e) {
      console.error(e);
      moveError = 'Failed to move image';
    } finally {
      movingFolder = false;
    }
  }

  async function openImageLocation() {
    if (!detail || openingLocation) return;
    openingLocation = true;
    openLocationError = '';
    try {
      await api.openImageLocation(detail.id);
    } catch (e) {
      console.error(e);
      openLocationError = 'Failed to open image location';
    } finally {
      openingLocation = false;
    }
  }

</script>

<svelte:window on:keydown={onKeydown} on:pointerup={stopZoomSliderDrag} on:pointercancel={stopZoomSliderDrag} />

<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
<div
  class="fixed inset-0 z-50 flex bg-black/80 backdrop-blur-sm"
  on:click|self={() => dispatch('close')}
>
  {#if profileAsset}
    <div class="flex flex-1 overflow-hidden" data-testid="archived-profile-image-detail">
      <div class="relative flex flex-1 items-center justify-center overflow-hidden p-4" on:click|self={() => dispatch('close')}>
        <div
          class="relative flex h-full w-full cursor-default items-center justify-center overflow-hidden"
          on:click={onImageBackdropClick}
        >
          <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
          <img
            src={profileAsset.file_url}
            alt={`Archived ${profileAsset.platform === 'twitter' ? 'X' : 'Pixiv'} ${profileAsset.asset_kind === 'avatar' ? 'Logo' : 'Banner'}`}
            decoding="async"
            draggable="false"
            class="max-h-full max-w-full select-none rounded shadow-2xl {imageZoom > MIN_IMAGE_ZOOM ? (imagePanning ? 'cursor-grabbing' : 'cursor-grab') : 'cursor-zoom-in'} {imagePanning ? 'transition-none' : 'transition-transform duration-150'}"
            style="transform: translate({imagePanX}px, {imagePanY}px) scale({imageZoom}); transform-origin: center center;"
            on:wheel={onImageWheel}
            on:pointerdown={onImagePointerDown}
            on:pointermove={onImagePointerMove}
            on:pointerup={onImagePointerUp}
            on:pointercancel={onImagePointerUp}
            on:click|stopPropagation={onImageClick}
          />
        </div>
        {#if showZoomSlider}
          <div
            class="pointer-events-none absolute inset-x-0 bottom-6 flex justify-center px-4"
            transition:fly={{ y: 16, duration: 170 }}
          >
            <div class="pointer-events-auto flex w-full max-w-sm items-center gap-2.5 rounded-full border border-[#3a3a50] bg-[#11111a]/90 px-3.5 py-1.5 shadow-xl backdrop-blur">
              <input
                type="range"
                min={MIN_IMAGE_ZOOM}
                max={MAX_IMAGE_ZOOM}
                step="0.05"
                value={imageZoom}
                class="h-2 flex-1 accent-purple-500"
                aria-label="Image zoom"
                on:pointerdown={() => zoomSliderDragging = true}
                on:pointerup={stopZoomSliderDrag}
                on:pointercancel={stopZoomSliderDrag}
                on:blur={stopZoomSliderDrag}
                on:input={onZoomInput}
              />
              <span class="w-10 text-right text-[11px] tabular-nums text-gray-300">{imageZoomPercent}%</span>
            </div>
          </div>
        {/if}
      </div>

      <aside class="w-96 shrink-0 overflow-y-auto border-l border-[#2a2a3a] bg-[#16161e]">
        <div class="flex items-start justify-between gap-3 border-b border-[#2a2a3a] p-4">
          <div class="min-w-0">
            <div class="text-[10px] font-semibold uppercase text-sky-300/80">Archived profile media</div>
            <h2 class="mt-1 break-words text-base font-semibold text-white">{profileAsset.tag_name.replaceAll('_', ' ')}</h2>
            <div class="mt-1 text-xs text-gray-500">
              {profileAsset.platform === 'twitter' ? 'Twitter/X' : 'Pixiv'} {profileAsset.asset_kind === 'avatar' ? 'Logo' : 'Banner'}
            </div>
          </div>
          <button class="shrink-0 rounded p-1 transition-colors hover:bg-[#2a2a3a]" on:click={() => dispatch('close')} title="Close">
            <svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
            </svg>
          </button>
        </div>

        <div class="border-b border-[#2a2a3a] p-4">
          <h3 class="mb-3 text-xs uppercase text-gray-500">Metadata</h3>
          <div class="space-y-2 text-sm">
            <div class="flex justify-between gap-4">
              <span class="text-gray-500">Dimensions</span>
              <span>{profileAsset.width} x {profileAsset.height}</span>
            </div>
            <div class="flex justify-between gap-4">
              <span class="text-gray-500">Captured</span>
              <span class="text-right">{formatDateTime(profileAsset.captured_at)}</span>
            </div>
            <div class="flex justify-between gap-4">
              <span class="text-gray-500">Platform</span>
              <span>{profileAsset.platform === 'twitter' ? 'Twitter/X' : 'Pixiv'}</span>
            </div>
            <div class="flex justify-between gap-4">
              <span class="text-gray-500">Type</span>
              <span class="capitalize">{profileAsset.asset_kind === 'avatar' ? 'Logo' : 'Banner'}</span>
            </div>
          </div>
        </div>

        <div class="space-y-2 p-4">
          <a
            class="flex w-full items-center justify-center gap-2 rounded-lg border border-[#2a2a3a] bg-[#1e1e2e] px-3 py-2 text-sm text-sky-300 transition-colors hover:border-sky-500/50 hover:text-sky-200"
            href={profileAsset.source_profile_url}
            target="_blank"
            rel="noreferrer"
          >Open source profile</a>
          <div class="rounded-lg border border-green-500/20 bg-green-500/10 px-3 py-2 text-xs text-green-200/80">
            Stored locally in the profile media archive.
          </div>
        </div>
      </aside>
    </div>
  {:else if loading}
    <div class="m-auto">
      <div class="w-10 h-10 border-2 border-purple-500 border-t-transparent rounded-full animate-spin"></div>
    </div>
  {:else if detail}
    <div class="flex flex-1 overflow-hidden">
      <!-- Image area -->
      <div class="relative flex flex-1 items-center justify-center overflow-hidden p-4" on:click|self={() => dispatch('close')}>
        {#if isVideo}
          <!-- svelte-ignore a11y_media_has_caption -->
          <video
            bind:this={videoEl}
            src={originalMediaUrl}
            controls
            autoplay={shouldPlayMedia}
            muted={shouldPlayMedia}
            loop={shouldPlayMedia}
            playsinline
            preload={shouldPlayMedia ? 'auto' : 'metadata'}
            class="max-h-full max-w-full rounded shadow-2xl"
            on:mouseenter={() => mediaHovered = true}
            on:mouseleave={() => mediaHovered = false}
          ></video>
        {:else}
          <div
            class="relative flex h-full w-full cursor-default items-center justify-center overflow-hidden"
            on:mouseenter={() => mediaHovered = true}
            on:mouseleave={() => mediaHovered = false}
            on:click={onImageBackdropClick}
          >
            <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
            <img
              src={displayImageUrl}
              alt={detail.filename}
              decoding="async"
              draggable="false"
              class="max-h-full max-w-full select-none rounded shadow-2xl {imageZoom > MIN_IMAGE_ZOOM ? (imagePanning ? 'cursor-grabbing' : 'cursor-grab') : 'cursor-zoom-in'} {imagePanning ? 'transition-none' : 'transition-transform duration-150'}"
              style="transform: translate({imagePanX}px, {imagePanY}px) scale({imageZoom}); transform-origin: center center;"
              on:wheel={onImageWheel}
              on:pointerdown={onImagePointerDown}
              on:pointermove={onImagePointerMove}
              on:pointerup={onImagePointerUp}
              on:pointercancel={onImagePointerUp}
              on:click|stopPropagation={onImageClick}
            />
            {#if isGif && !shouldPlayMedia}
              <div class="pointer-events-none absolute inset-0 m-auto flex h-16 w-32 items-center justify-center gap-2 rounded-xl bg-black/60 text-sm font-semibold text-white shadow-lg">
                <svg class="h-5 w-5" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M8 5v14l11-7z"/>
                </svg>
                {$mediaPlayback === 'never' ? 'Animation off' : 'Hover GIF'}
              </div>
            {/if}
          </div>
          {#if showZoomSlider}
            <div
              class="pointer-events-none absolute inset-x-0 bottom-6 flex justify-center px-4"
              transition:fly={{ y: 16, duration: 170 }}
            >
              <div class="pointer-events-auto flex w-full max-w-sm items-center gap-2.5 rounded-full border border-[#3a3a50] bg-[#11111a]/90 px-3.5 py-1.5 shadow-xl backdrop-blur">
                <input
                  type="range"
                  min={MIN_IMAGE_ZOOM}
                  max={MAX_IMAGE_ZOOM}
                  step="0.05"
                  value={imageZoom}
                  class="h-2 flex-1 accent-purple-500"
                  aria-label="Image zoom"
                  on:pointerdown={() => zoomSliderDragging = true}
                  on:pointerup={stopZoomSliderDrag}
                  on:pointercancel={stopZoomSliderDrag}
                  on:blur={stopZoomSliderDrag}
                  on:input={onZoomInput}
                />
                <span class="w-10 text-right text-[11px] tabular-nums text-gray-300">{imageZoomPercent}%</span>
              </div>
            </div>
          {/if}
        {/if}
        {#if $heartSpamEnabled}
          <div class="pointer-events-none absolute bottom-7 right-7 z-30 h-28 w-28">
            {#each floatingHearts as heart (heart.id)}
              <span
                class="heart-float pointer-events-none absolute bottom-12 text-pink-300 drop-shadow-[0_0_8px_rgba(244,114,182,0.75)]"
                style="left: {heart.x}px; --heart-drift: {heart.drift}px; --heart-rotate: {heart.rotate}deg; --heart-duration: {heart.duration}ms; font-size: {heart.size}px;"
              >♥</span>
            {/each}
            <button
              type="button"
              class="pointer-events-auto absolute bottom-0 right-0 grid h-12 w-12 place-items-center rounded-full border border-pink-400/45 bg-black/60 text-pink-200 shadow-xl shadow-black/40 backdrop-blur transition hover:border-pink-300/70 hover:bg-pink-600/25 hover:text-pink-100 active:scale-95"
              on:click|stopPropagation={spamHeart}
              title="Heart spam"
              aria-label="Heart spam"
            >
              <svg class="h-6 w-6 fill-current" viewBox="0 0 24 24" aria-hidden="true">
                <path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z" />
              </svg>
            </button>
          </div>
        {/if}
      </div>

      <!-- Info panel -->
      <div class="w-96 bg-[#16161e] border-l border-[#2a2a3a] overflow-y-auto shrink-0">
        <div class="p-4 border-b border-[#2a2a3a] flex items-start justify-between gap-2">
          <h2 class="min-w-0 flex-1 break-all text-sm font-medium leading-snug" title={detail.filename}>{detail.filename}</h2>
          <button class="shrink-0 p-1 hover:bg-[#2a2a3a] rounded transition-colors" on:click={() => dispatch('close')} title="Close">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
            </svg>
          </button>
        </div>

        <!-- Actions -->
        <div class="p-4 border-b border-[#2a2a3a] flex flex-wrap gap-2">
          <button
            class="flex-1 flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors {detail.is_favorite ? 'bg-pink-600/30 text-pink-300 border border-pink-500/40' : 'bg-[#1e1e2e] text-gray-400 hover:text-pink-300 border border-[#2a2a3a]'}"
            disabled={favoriteBusy}
            on:click={toggleFavorite}
          >
            <svg class="w-4 h-4 {detail.is_favorite ? 'fill-current' : ''}" viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/>
            </svg>
            {detail.is_favorite ? 'Favorited' : 'Favorite'}
          </button>

          <div class="relative">
            <button
              class="flex items-center gap-2 px-3 py-2 rounded-lg text-sm bg-[#1e1e2e] text-gray-400 hover:text-purple-300 border border-[#2a2a3a] transition-colors"
              on:click={() => { showCollectionMenu = !showCollectionMenu; showMoveMenu = false; }}
            >
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6v6m0 0v6m0-6h6m-6 0H6"/>
              </svg>
              Collection
            </button>

            {#if showCollectionMenu}
              <div class="absolute right-0 top-full mt-1 w-56 bg-[#1e1e2e] border border-[#2a2a3a] rounded-lg shadow-xl z-10">
                {#each allCollections as col}
                  <button
                    class="w-full text-left px-3 py-2 text-sm hover:bg-[#2a2a3a] transition-colors"
                    on:click={() => addToCollection(col.id)}
                  >{col.name}</button>
                {/each}
                <div class="border-t border-[#2a2a3a] p-2 flex gap-1">
                  <input
                    type="text"
                    bind:value={newCollectionName}
                    placeholder="New collection..."
                    class="flex-1 bg-[#16161e] border border-[#2a2a3a] rounded px-2 py-1 text-xs outline-none focus:border-purple-500"
                    on:keydown|stopPropagation={(e) => e.key === 'Enter' && createAndAdd()}
                  />
                  <button
                    class="px-2 py-1 text-xs bg-purple-600 rounded hover:bg-purple-500 transition-colors"
                    on:click={createAndAdd}
                  >Add</button>
                </div>
              </div>
            {/if}
          </div>
        </div>

        <!-- Collections this image belongs to -->
        {#if detail.collections.length > 0}
          <div class="px-4 py-3 border-b border-[#2a2a3a]">
            <h3 class="text-xs text-gray-500 uppercase tracking-wider mb-2">In Collections</h3>
            <div class="flex flex-wrap gap-1.5">
              {#each detail.collections as col}
                <span
                  class="group inline-flex max-w-full flex-col gap-0.5 rounded-lg border border-purple-500/25 bg-purple-600/15 px-2.5 py-1 text-xs text-purple-300 transition-colors hover:border-red-500/40"
                  title={col.item_added_at ? `Added ${formatDateTime(col.item_added_at)}` : col.name}
                >
                  <span class="inline-flex items-center gap-1.5">
                    <button
                      class="relative w-3 h-3 shrink-0"
                      on:click={() => removeFromCollection(col.id)}
                      title="Remove from {col.name}"
                    >
                      <!-- Collection icon (default) -->
                      <svg class="w-3 h-3 absolute inset-0 group-hover:opacity-0 transition-opacity" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10"/>
                      </svg>
                      <!-- X icon (on hover) -->
                      <svg class="w-3 h-3 absolute inset-0 opacity-0 group-hover:opacity-100 text-red-400 transition-opacity" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
                      </svg>
                    </button>
                    <span class="min-w-0 break-words">{col.name}</span>
                  </span>
                  {#if col.item_added_at}
                    <span class="pl-4 text-[10px] leading-tight text-purple-200/60">
                      Added {formatDateTime(col.item_added_at)}
                    </span>
                  {/if}
                </span>
              {/each}
            </div>
          </div>
        {/if}

        <!-- Metadata -->
        <div class="p-4 border-b border-[#2a2a3a]">
          <h3 class="text-xs text-gray-500 uppercase tracking-wider mb-2">Metadata</h3>
          {#if openLocationError}
            <div class="mb-2 text-xs text-red-300">{openLocationError}</div>
          {/if}
          <div class="space-y-1.5 text-sm">
            <div class="flex justify-between">
              <span class="text-gray-500">Dimensions</span>
              <span>{detail.width || '?'} x {detail.height || '?'}</span>
            </div>
            <div class="flex justify-between">
              <span class="text-gray-500">File size</span>
              <span>{formatSize(detail.size)}</span>
            </div>
            <div class="flex justify-between">
              <span class="text-gray-500">Format</span>
              <span class="uppercase">{detail.ext || '?'}</span>
            </div>
            <div class="flex justify-between">
              <span class="text-gray-500">Score</span>
              <span class="text-yellow-400">★ {detail.score ?? '-'}</span>
            </div>
            <div class="flex justify-between">
              <span class="text-gray-500">Rating</span>
              <span>{detail.rating ? ratingLabels[detail.rating] || detail.rating : '-'}</span>
            </div>
            <div class="flex justify-between">
              <span class="text-gray-500">Seen</span>
              <span>{detail.view_count.toLocaleString()} {detail.view_count === 1 ? 'time' : 'times'}</span>
            </div>
            <div class="flex justify-between">
              <span class="text-gray-500">Heart spam</span>
              <button
                type="button"
                class="text-pink-300 transition-colors hover:text-pink-200 disabled:cursor-default disabled:text-gray-500"
                disabled={(detail.heart_spam_count ?? 0) < 1}
                on:click={filterByHeartSpam}
                title={(detail.heart_spam_count ?? 0) > 0 ? 'Filter images with at least this many hearts' : 'No heart spam yet'}
              >
                {(detail.heart_spam_count ?? 0).toLocaleString()}
              </button>
            </div>
            <div class="relative flex justify-between gap-2">
              <span class="text-gray-500">Folder</span>
              <div class="min-w-0 flex items-center justify-end gap-1.5">
                <button
                  class="flex h-5 w-5 shrink-0 items-center justify-center rounded border border-[#2a2a3a] bg-[#1e1e2e] text-gray-500 transition-colors hover:border-cyan-500/40 hover:text-cyan-300 disabled:cursor-not-allowed disabled:opacity-50"
                  disabled={openingLocation}
                  on:click={openImageLocation}
                  title="Open image location"
                >
                  <svg class="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h6l2 2h8v10a2 2 0 01-2 2H4a2 2 0 01-2-2V8a2 2 0 012-2z"/>
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 13h5m0 0l-2-2m2 2l-2 2"/>
                  </svg>
                </button>
                <button
                  class="flex h-5 w-5 shrink-0 items-center justify-center rounded border border-[#2a2a3a] bg-[#1e1e2e] text-gray-500 transition-colors hover:border-purple-500/40 hover:text-purple-300 disabled:cursor-not-allowed disabled:opacity-50"
                  disabled={movingFolder}
                  on:click={() => { showMoveMenu = !showMoveMenu; showCollectionMenu = false; }}
                  title="Move to another folder"
                >
                  <svg class="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 7h5l2 2h11v8a2 2 0 01-2 2H5a2 2 0 01-2-2V7z"/>
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 13h5m0 0l-2-2m2 2l-2 2"/>
                  </svg>
                </button>
                <span class="truncate ml-1">{detail.folder || '-'}</span>
              </div>

              {#if showMoveMenu}
                <div class="absolute right-0 top-full mt-1 w-64 max-h-80 overflow-y-auto bg-[#1e1e2e] border border-[#2a2a3a] rounded-lg shadow-xl z-20">
                  <div class="px-3 py-2 text-[10px] uppercase tracking-wider text-gray-500 border-b border-[#2a2a3a]">
                    From {currentFolder}
                  </div>
                  {#if moveError}
                    <div class="px-3 py-2 text-xs text-red-300 border-b border-[#2a2a3a]">{moveError}</div>
                  {/if}
                  {#if folderMoveTargets.length === 0}
                    <div class="px-3 py-3 text-sm text-gray-500">No other folders</div>
                  {:else}
                    {#each folderMoveTargets as folder}
                      <button
                        class="w-full flex items-center justify-between gap-2 px-3 py-2 text-left text-sm text-gray-300 hover:bg-[#2a2a3a] transition-colors disabled:opacity-60"
                        disabled={movingFolder}
                        on:click={() => moveToFolder(folder)}
                        title="Move to {folder.name}"
                      >
                        <span class="min-w-0"><span class="block truncate">{folder.name}</span>{#if folder.path}<span class="block truncate text-[10px] text-gray-600">{folder.path}</span>{/if}</span>
                        <span class="shrink-0 text-xs text-gray-600">{folder.count.toLocaleString()}</span>
                      </button>
                    {/each}
                  {/if}
                </div>
              {/if}
            </div>
            {#if detail.danbooru_post_id}
              <div class="flex justify-between">
                <span class="text-gray-500">Danbooru</span>
                <a
                  href={detail.post_url || `https://danbooru.donmai.us/posts/${detail.danbooru_post_id}`}
                  target="_blank"
                  rel="noreferrer"
                  class="text-purple-400 hover:text-purple-300"
                >#{detail.danbooru_post_id}</a>
              </div>
            {/if}
            {#if detail.source_url}
              <div class="flex justify-between">
                <span class="text-gray-500">Source</span>
                <a
                  href={detail.source_url}
                  target="_blank"
                  rel="noreferrer"
                  class="text-purple-400 hover:text-purple-300 truncate ml-2 max-w-48"
                >{detail.source_url}</a>
              </div>
            {/if}
            {#if detail.created_at}
              <div class="flex justify-between">
                <span class="text-gray-500">Uploaded</span>
                <span>{new Date(detail.created_at).toLocaleDateString()}</span>
              </div>
            {/if}
            {#if detail.downloaded_at}
              <div class="flex justify-between">
                <span class="text-gray-500">Downloaded</span>
                <span>{formatDateTime(detail.downloaded_at)}</span>
              </div>
            {/if}
            {#if detail.is_favorite && detail.favorite_added_at}
              <div class="flex justify-between">
                <span class="text-gray-500">Favorited</span>
                <span>{formatDateTime(detail.favorite_added_at)}</span>
              </div>
            {/if}
          </div>

        </div>

        {#if showRelationSection}
          <div class="p-4 border-b border-[#2a2a3a]">
            <div class="mb-2 flex items-center justify-between gap-2">
              <h3 class="text-xs text-gray-500 uppercase tracking-wider">Danbooru Family</h3>
              <div class="flex items-center gap-2">
                {#if detail.danbooru_post_id}
                  <a
                    href={`https://danbooru.donmai.us/posts/${detail.danbooru_post_id}?q=parent%3A${detail.danbooru_post_id}`}
                    target="_blank"
                    rel="noreferrer"
                    class="text-[11px] text-purple-400 transition-colors hover:text-purple-300"
                  >Children search</a>
                {/if}
                <button
                  type="button"
                  class="rounded border border-[#2a2a3a] bg-[#1e1e2e] px-2 py-1 text-[11px] text-gray-300 transition-colors hover:border-purple-500/50 hover:text-purple-200 disabled:cursor-not-allowed disabled:opacity-50"
                  disabled={relationRefreshing}
                  on:click={refreshRelations}
                  title="Check Danbooru parent and child posts"
                >{relationRefreshing ? 'Checking...' : (relationGroups.length > 0 ? 'Refresh' : 'Check')}</button>
              </div>
            </div>

            {#if relationError}
              <div class="mb-2 rounded-lg border border-red-500/25 bg-red-500/10 px-3 py-2 text-xs text-red-300">{relationError}</div>
            {/if}

            {#if relationGroups.length === 0}
              <div class="rounded-lg border border-[#2a2a3a] bg-[#1a1a24] px-3 py-2 text-xs text-gray-500">
                No parent, sibling, or child links are loaded locally yet.
              </div>
            {:else}
              <div class="space-y-3">
                {#each relationGroups as group}
                  <div>
                    <div class="mb-1.5 flex items-center justify-between text-xs">
                      <span class="text-gray-500">{group.label}</span>
                      <span class="text-gray-600">{group.items.length}</span>
                    </div>
                    <div class="grid max-h-72 grid-cols-2 gap-2 overflow-y-auto pr-1">
                      {#each group.items as item}
                        {@const thumb = relatedThumbnailUrl(item)}
                        {#if item.local_post_id}
                          <button
                            type="button"
                            class="group overflow-hidden rounded-lg border border-[#2a2a3a] bg-[#1a1a24] text-left transition-colors hover:border-purple-500/60 hover:bg-[#1e1e2e]"
                            on:click={() => openRelatedImage(item)}
                            title={`Open local Danbooru #${item.danbooru_post_id}`}
                          >
                            <div class="relative aspect-square bg-black/30">
                              {#if thumb}
                                <img
                                  class="h-full w-full object-cover transition-transform group-hover:scale-105"
                                  src={thumb}
                                  alt={item.filename || `Danbooru #${item.danbooru_post_id}`}
                                  loading="lazy"
                                />
                              {:else}
                                <div class="flex h-full w-full items-center justify-center text-xs text-gray-600">Local</div>
                              {/if}
                              <span class="absolute right-1 top-1 rounded bg-black/70 px-1.5 py-0.5 text-[10px] text-green-300">Local</span>
                            </div>
                            <div class="space-y-0.5 p-2">
                              <div class="truncate text-xs text-purple-300">#{item.danbooru_post_id}</div>
                              <div class="truncate text-[11px] text-gray-500">{relatedSubtitle(item)}</div>
                            </div>
                          </button>
                        {:else}
                          <a
                            class="group overflow-hidden rounded-lg border border-[#2a2a3a] bg-[#1a1a24] text-left transition-colors hover:border-cyan-500/60 hover:bg-[#1e1e2e]"
                            href={relatedPostUrl(item)}
                            target="_blank"
                            rel="noreferrer"
                            title={`Open Danbooru #${item.danbooru_post_id}`}
                          >
                            <div class="flex aspect-square flex-col items-center justify-center gap-2 bg-black/30 text-gray-500 transition-colors group-hover:text-cyan-300">
                              <svg class="h-6 w-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14 3h7v7m0-7L10 14"/>
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 7v12h12"/>
                              </svg>
                              <span class="text-[11px]">Danbooru</span>
                            </div>
                            <div class="space-y-0.5 p-2">
                              <div class="truncate text-xs text-cyan-300">#{item.danbooru_post_id}</div>
                              <div class="truncate text-[11px] text-gray-500">Not downloaded</div>
                            </div>
                          </a>
                        {/if}
                      {/each}
                    </div>
                  </div>
                {/each}
              </div>
            {/if}
          </div>
        {/if}

        <!-- Tags -->
        <div class="p-4">
          <h3 class="text-xs text-gray-500 uppercase tracking-wider mb-2">Tags</h3>
          {#if userTagError}
            <div class="mb-2 text-xs text-red-300">{userTagError}</div>
          {/if}
          {#if favoriteTagError}
            <div class="mb-2 text-xs text-red-300">{favoriteTagError}</div>
          {/if}
          {#each categoryOrder as cat}
            {@const categoryTags = detail.tags[cat] ?? []}
            {@const userCategoryTags = detail.user_tags?.[cat] ?? []}
            {#if editableTagCategories.has(cat) || categoryTags.length > 0 || userCategoryTags.length > 0}
              <div class="mb-3">
                <div class="mb-1 text-xs text-gray-600 capitalize">{cat}</div>
                <div class="flex flex-wrap gap-1">
                  {#each categoryTags as tag}
                    {@const favKey = favoriteTagKey(cat, tag)}
                    <span class="group relative inline-flex">
                      <button
                        class="px-1.5 py-0.5 text-xs rounded border transition-colors {categoryColors[cat] || categoryColors['unknown']}"
                        on:click={() => openTag(tag, cat)}
                        title="Filter by {tag}"
                      >{tag.replace(/_/g, ' ')}</button>
                      <button
                        type="button"
                        class="absolute -right-1 -top-1 z-10 flex h-5 w-5 items-center justify-center rounded-full border border-pink-500/35 bg-[#11111a]/95 text-[10px] text-pink-300 opacity-0 shadow-sm transition-opacity hover:bg-pink-500/20 focus:opacity-100 disabled:cursor-wait disabled:opacity-50 group-hover:opacity-100"
                        disabled={favoriteTagBusy.has(favKey)}
                        on:click|stopPropagation={() => toggleFavoriteTag(cat, tag)}
                        title="{favTagSet.has(favKey) ? 'Unfavorite' : 'Favorite'} tag"
                        aria-label="{favTagSet.has(favKey) ? 'Unfavorite' : 'Favorite'} tag {tag.replace(/_/g, ' ')}"
                      >{favTagSet.has(favKey) ? '♥' : '♡'}</button>
                    </span>
                  {/each}

                  {#if editableTagCategories.has(cat) && userCategoryTags.length === 0}
                    {#if activeUserTagCategory !== cat}
                      <button
                        type="button"
                        class="inline-flex h-[22px] w-6 items-center justify-center rounded border text-xs transition-colors disabled:cursor-not-allowed disabled:opacity-50 {categoryColors[cat] || categoryColors['unknown']}"
                        disabled={userTagSaving}
                        on:pointerdown|preventDefault|stopPropagation={() => startUserTagInput(cat)}
                        title="Add {cat} user tag"
                      >
                        <svg class="h-3 w-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 5v14m7-7H5"/>
                        </svg>
                      </button>
                    {:else}
                      <span class="relative inline-flex items-center rounded border px-1.5 py-0.5 {categoryColors[cat] || categoryColors['unknown']}">
                        {#if userTagSuggestions.length > 0}
                          <div class="absolute bottom-full left-0 z-30 mb-1 max-h-44 w-56 overflow-y-auto rounded-lg border border-[#2a2a3a] bg-[#1e1e2e] py-1 shadow-xl">
                            {#each userTagSuggestions as suggestion}
                              <button
                                class="flex w-full items-center justify-between gap-2 px-2 py-1 text-left text-xs text-gray-200 transition-colors hover:bg-[#2a2a3a]"
                                on:mousedown|preventDefault={() => addUserTag(cat, suggestion.name)}
                                title="Add {suggestion.name}"
                              >
                                <span class="min-w-0 truncate">{suggestion.name.replace(/_/g, ' ')}</span>
                                <span class="shrink-0 text-[10px] text-gray-600">{suggestion.count.toLocaleString()}</span>
                              </button>
                            {/each}
                          </div>
                        {/if}
                        <input
                          bind:this={userTagInput}
                          type="text"
                          bind:value={userTagDraft}
                          size={Math.max(8, Math.min(24, userTagDraft.length || 8))}
                          class="min-w-20 bg-transparent text-xs text-current outline-none placeholder:text-current/50"
                          placeholder="tag"
                          on:input={updateUserTagSuggestions}
                          on:keydown|stopPropagation={(e) => onUserTagKeydown(e, cat)}
                          on:blur={() => setTimeout(cancelUserTagInput, 120)}
                        />
                      </span>
                    {/if}
                  {/if}
                </div>

                {#if userCategoryTags.length > 0}
                  {#if categoryTags.length > 0}
                    <div class="my-1.5 h-px w-full bg-[#2a2a3a]"></div>
                  {/if}
                  <div class="flex flex-wrap gap-1">
                    {#each userCategoryTags as tag}
                    <span class="inline-flex max-w-full items-center rounded border transition-colors {categoryColors[cat] || categoryColors['unknown']}">
                      <button
                        class="min-w-0 truncate px-1.5 py-0.5 text-xs"
                        on:click={() => openTag(tag, cat, 'user')}
                        title="Filter by user tag {tag}"
                      >{tag.replace(/_/g, ' ')}</button>
                      <button
                        class="px-1 py-0.5 text-xs opacity-70 transition-colors hover:opacity-100 disabled:cursor-not-allowed disabled:opacity-50"
                        disabled={userTagSaving}
                        on:click={() => removeUserTag(cat, tag)}
                        title="Remove user tag {tag}"
                      >&times;</button>
                    </span>
                    {/each}

                    {#if editableTagCategories.has(cat) && activeUserTagCategory !== cat}
                      <button
                        type="button"
                        class="inline-flex h-[22px] w-6 items-center justify-center rounded border text-xs transition-colors disabled:cursor-not-allowed disabled:opacity-50 {categoryColors[cat] || categoryColors['unknown']}"
                        disabled={userTagSaving}
                        on:pointerdown|preventDefault|stopPropagation={() => startUserTagInput(cat)}
                        title="Add {cat} user tag"
                      >
                        <svg class="h-3 w-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 5v14m7-7H5"/>
                        </svg>
                      </button>
                    {:else if activeUserTagCategory === cat}
                      <span class="relative inline-flex items-center rounded border px-1.5 py-0.5 {categoryColors[cat] || categoryColors['unknown']}">
                        {#if userTagSuggestions.length > 0}
                          <div class="absolute bottom-full left-0 z-30 mb-1 max-h-44 w-56 overflow-y-auto rounded-lg border border-[#2a2a3a] bg-[#1e1e2e] py-1 shadow-xl">
                            {#each userTagSuggestions as suggestion}
                              <button
                                class="flex w-full items-center justify-between gap-2 px-2 py-1 text-left text-xs text-gray-200 transition-colors hover:bg-[#2a2a3a]"
                                on:mousedown|preventDefault={() => addUserTag(cat, suggestion.name)}
                                title="Add {suggestion.name}"
                              >
                                <span class="min-w-0 truncate">{suggestion.name.replace(/_/g, ' ')}</span>
                                <span class="shrink-0 text-[10px] text-gray-600">{suggestion.count.toLocaleString()}</span>
                              </button>
                            {/each}
                          </div>
                        {/if}
                        <input
                          bind:this={userTagInput}
                          type="text"
                          bind:value={userTagDraft}
                          size={Math.max(8, Math.min(24, userTagDraft.length || 8))}
                          class="min-w-20 bg-transparent text-xs text-current outline-none placeholder:text-current/50"
                          placeholder="tag"
                          on:input={updateUserTagSuggestions}
                          on:keydown|stopPropagation={(e) => onUserTagKeydown(e, cat)}
                          on:blur={() => setTimeout(cancelUserTagInput, 120)}
                        />
                      </span>
                    {/if}
                  </div>
                {/if}
              </div>
            {/if}
          {/each}

          {#if detail.removed_tags?.length > 0}
            <div class="mt-4 border-t border-red-500/20 pt-3">
              <div class="mb-1.5 flex items-center gap-2 text-xs uppercase tracking-wider text-red-300/80">
                <span>Removed upstream</span>
                <span class="text-[10px] font-normal normal-case tracking-normal text-gray-600">Historical only</span>
              </div>
              <div class="flex flex-wrap gap-1">
                {#each detail.removed_tags as tag}
                  <span class="rounded border border-red-500/20 bg-red-500/10 px-1.5 py-0.5 text-xs text-red-300/75 line-through decoration-red-400/60">{tag.replace(/_/g, ' ')}</span>
                {/each}
              </div>
            </div>
          {/if}

        </div>
      </div>
    </div>
  {/if}
</div>

<style>
  @keyframes heart-rise {
    0% {
      opacity: 0;
      transform: translate3d(0, 0, 0) scale(0.65) rotate(var(--heart-rotate));
    }
    12% {
      opacity: 1;
    }
    100% {
      opacity: 0;
      transform: translate3d(var(--heart-drift), -78px, 0) scale(1.15) rotate(calc(var(--heart-rotate) + 12deg));
    }
  }

  .heart-float {
    animation: heart-rise var(--heart-duration) ease-out forwards;
  }
</style>
