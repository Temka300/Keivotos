<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { flip } from 'svelte/animate';
  import { fade } from 'svelte/transition';
  import {
    api,
    thumbnailUrl,
    type HomeCoverCandidate,
    type HomeImageRail,
    type HomeImageRailItem,
    type HomeTagInfo,
    type HomeTags,
  } from '../lib/api';
  import { persistentStorageKey } from '../lib/product';
  import {
    activeCollectionId,
    activeFolder,
    activeRating,
    browseTagSelection,
    homeLayout,
    selectedImageId,
    viewMode,
  } from '../lib/stores';

  type StreamItem = HomeImageRailItem & {
    rail_key: string;
    rail_label: string;
  };

  const categoryOrder = ['character', 'copyright', 'artist', 'general', 'meta'];
  const categoryLabels: Record<string, string> = {
    character: 'Characters',
    copyright: 'Copyrights',
    artist: 'Artists',
    general: 'General',
    meta: 'Meta',
  };
  const categoryColors: Record<string, string> = {
    artist: 'border-red-500/30 bg-red-500/15 text-red-200',
    character: 'border-green-500/30 bg-green-500/15 text-green-200',
    copyright: 'border-purple-500/30 bg-purple-500/15 text-purple-200',
    general: 'border-blue-500/30 bg-blue-500/15 text-blue-200',
    meta: 'border-yellow-500/30 bg-yellow-500/15 text-yellow-200',
  };
  const categoryDotClasses: Record<string, string> = {
    artist: 'bg-red-400',
    character: 'bg-green-400',
    copyright: 'bg-purple-400',
    general: 'bg-blue-400',
    meta: 'bg-yellow-400',
  };
  const streamAccentClasses: Record<string, string> = {
    favorites: 'border-pink-400/35 bg-pink-500/20 text-pink-100',
    artist: 'border-red-400/35 bg-red-500/20 text-red-100',
    general: 'border-blue-400/35 bg-blue-500/20 text-blue-100',
    character: 'border-green-400/35 bg-green-500/20 text-green-100',
    copyright: 'border-purple-400/35 bg-purple-500/20 text-purple-100',
  };
  const discoveryRailOrder = ['character', 'artist', 'copyright', 'favorites', 'general'];
  const spotlightCategories = ['character', 'copyright', 'artist', 'general'];
  const spotlightCategoryLabels: Record<string, string> = {
    character: 'Characters',
    copyright: 'Copyright',
    artist: 'Artists',
    general: 'Tags',
  };
  const homeCacheVersion = 'v4';
  const SPOTLIGHT_DURATION_MS = 9000;

  let homeTags: HomeTags = { featured: [], groups: {} };
  let imageRails: HomeImageRail[] = [];
  let loadingTags = false;
  let loadingRails = false;
  let randomLoading = false;
  let selectedSpotlightKey: string | null = null;
  let spotlightTimer: number | null = null;
  let spotlightProgressKey = 0;
  let homeArtworkAssignments = new Map<string, HomeCoverCandidate>();
  let error = '';
  let mounted = false;
  let loadedRatingKey: string | null = null;
  let homeRequestSerial = 0;
  let railRequestSerial = 0;
  let railTimer: number | null = null;
  let dailyTimer: number | null = null;
  let dailySeed = dayNumber();

  onMount(() => {
    mounted = true;
    scheduleDailyReset();
    loadHome();
  });

  onDestroy(() => {
    if (railTimer !== null) window.clearTimeout(railTimer);
    if (spotlightTimer !== null) window.clearTimeout(spotlightTimer);
    if (dailyTimer !== null) window.clearTimeout(dailyTimer);
  });

  function displayTag(name: string) {
    return name.replace(/_/g, ' ');
  }

  function countLabel(count: number) {
    return count >= 1000 ? `${Math.round(count / 100) / 10}k` : count.toLocaleString();
  }

  function categoryClass(category: string) {
    return categoryColors[category] ?? 'border-gray-500/30 bg-gray-500/15 text-gray-300';
  }

  function streamAccentClass(key: string) {
    return streamAccentClasses[key] ?? 'border-gray-400/35 bg-gray-500/20 text-gray-100';
  }

  function tagImage(tag: HomeTagInfo, size = 440) {
    return tag.cover_file_id && tag.thumbnail_token
      ? thumbnailUrl(tag.cover_file_id, size, tag.thumbnail_token)
      : '';
  }

  function spotlightKey(tag: HomeTagInfo) {
    return `${tag.category}:${tag.name}`;
  }

  function artworkKey(surface: 'spotlight' | 'neighborhood', tag: HomeTagInfo) {
    return `${surface}:${spotlightKey(tag)}`;
  }

  function tagCoverCandidates(tag: HomeTagInfo): HomeCoverCandidate[] {
    if (tag.cover_candidates?.length) return tag.cover_candidates;
    if (!tag.cover_post_id || !tag.cover_file_id || !tag.thumbnail_token) return [];
    return [{
      post_id: tag.cover_post_id,
      file_id: tag.cover_file_id,
      thumbnail_token: tag.thumbnail_token,
      width: null,
      height: null,
    }];
  }

  function artworkUrl(artwork: HomeCoverCandidate | null, size = 1200) {
    return artwork ? thumbnailUrl(artwork.file_id, size, artwork.thumbnail_token) : '';
  }

  function artworkObjectPosition(item: { width: number | null; height: number | null } | null) {
    if (!item?.width || !item.height) return '50% 42%';
    return item.width / item.height < 0.9 ? '50% 24%' : '50% 44%';
  }

  function dayNumber() {
    const today = new Date();
    return Math.floor(Date.UTC(today.getFullYear(), today.getMonth(), today.getDate()) / 86_400_000);
  }

  function scheduleDailyReset() {
    if (dailyTimer !== null) window.clearTimeout(dailyTimer);
    const now = new Date();
    const tomorrow = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1);
    dailyTimer = window.setTimeout(() => {
      dailySeed = dayNumber();
      selectedSpotlightKey = null;
      scheduleSpotlightAdvance();
      scheduleDailyReset();
    }, Math.max(1_000, tomorrow.getTime() - now.getTime() + 250));
  }

  function dailySequence<T>(items: T[], salt: number, count = items.length): T[] {
    if (items.length === 0 || count <= 0) return [];
    const start = Math.abs(dailySeed * 17 + salt * 31) % items.length;
    return Array.from(
      { length: Math.min(count, items.length) },
      (_, index) => items[(start + index) % items.length],
    );
  }

  function streamLabel(item: StreamItem) {
    if (item.tag_name) return displayTag(item.tag_name);
    return item.is_favorite ? 'Favorite' : item.rail_label;
  }

  function streamTitle(item: StreamItem) {
    const label = streamLabel(item);
    return label ? `${label} - ${item.filename}` : item.filename;
  }

  function dailyIndex(length: number) {
    if (length === 0) return 0;
    return dailySeed % length;
  }

  function dailySpotlightPicks(
    category: string,
    categoryIndex: number,
    sourceTags: HomeTags,
    sourceFeaturedTags: HomeTagInfo[],
    sourceRails: HomeImageRail[],
    count = 2,
  ) {
    const groupCandidates = (sourceTags.groups[category] ?? []).filter(tag => tagCoverCandidates(tag).length > 0);
    const fallbackCandidates = sourceFeaturedTags.filter(tag => tag.category === category);
    const candidates = groupCandidates.length > 0 ? groupCandidates : fallbackCandidates;
    if (candidates.length === 0) {
      const fallback = railCoverTag(category, sourceRails, sourceTags.groups);
      return fallback ? [fallback] : [];
    }
    const start = (dailySeed * 7 + categoryIndex * 3) % candidates.length;
    return Array.from({ length: Math.min(count, candidates.length) }, (_, index) => candidates[(start + index) % candidates.length]);
  }

  function spotlightReason(tag: HomeTagInfo) {
    const count = `${countLabel(tag.count)} local ${tag.count === 1 ? 'image' : 'images'}`;
    if (tag.category === 'character') return `${count} from a character worth revisiting.`;
    if (tag.category === 'copyright') return `${count} from one of your collected worlds.`;
    if (tag.category === 'artist') return `${count} connected by the same artist.`;
    return `${count} connected by this visual thread.`;
  }

  function categoryDescription(category: string) {
    if (category === 'character') return 'Faces and personalities with the strongest presence in your library.';
    if (category === 'copyright') return 'Series, games, and worlds that connect your collection.';
    if (category === 'artist') return 'Creators whose work already has a place in your library.';
    return 'Visual themes for wandering beyond names and series.';
  }

  function discoveryRailLabel(rail: HomeImageRail) {
    if (rail.key === 'character') return 'Characters';
    if (rail.key === 'artist') return 'Artists';
    if (rail.key === 'copyright') return 'Copyright';
    if (rail.key === 'favorites') return 'Recently loved';
    return rail.label;
  }

  function railCoverTag(
    category: string,
    sourceRails = imageRails,
    sourceGroups = homeTags.groups,
  ): HomeTagInfo | null {
    const rail = sourceRails.find((candidate) => candidate.key === category);
    const item = rail?.items.find((candidate) => candidate.tag_name && candidate.tag_category);
    if (!item?.tag_name || !item.tag_category) return null;
    const knownTag = sourceGroups[item.tag_category]?.find((tag) => tag.name === item.tag_name);
    if (knownTag) return knownTag;
    return {
      name: item.tag_name,
      category: item.tag_category,
      count: 1,
      cover_post_id: item.id,
      cover_file_id: item.file_id,
      thumbnail_token: item.thumbnail_token,
      cover_candidates: [{
        post_id: item.id,
        file_id: item.file_id,
        thumbnail_token: item.thumbnail_token,
        width: item.width,
        height: item.height,
      }],
    } satisfies HomeTagInfo;
  }

  function scheduleSpotlightAdvance() {
    if (spotlightTimer !== null) window.clearTimeout(spotlightTimer);
    spotlightTimer = null;
    spotlightProgressKey += 1;
    if (!mounted || discoverySpotlightPool.length < 2) return;
    spotlightTimer = window.setTimeout(() => moveSpotlight(1), SPOTLIGHT_DURATION_MS);
  }

  function chooseSpotlight(tag: HomeTagInfo) {
    selectedSpotlightKey = spotlightKey(tag);
    scheduleSpotlightAdvance();
  }

  function moveSpotlight(direction: 1 | -1) {
    if (discoverySpotlightPool.length < 2) return;
    const currentIndex = discoverySpotlightPool.findIndex((tag) => spotlightKey(tag) === spotlightKey(discoverySpotlightTag ?? discoverySpotlightPool[0]));
    const nextIndex = currentIndex < 0
      ? 0
      : (currentIndex + direction + discoverySpotlightPool.length) % discoverySpotlightPool.length;
    const nextTag = discoverySpotlightPool[nextIndex];
    if (nextTag) selectedSpotlightKey = spotlightKey(nextTag);
    scheduleSpotlightAdvance();
  }

  function spotlightWindow(tags: HomeTagInfo[], activeTag: HomeTagInfo | null) {
    if (!activeTag || tags.length === 0) return [];
    const activeIndex = Math.max(0, tags.findIndex((tag) => spotlightKey(tag) === spotlightKey(activeTag)));
    const count = Math.min(5, tags.length);
    const firstOffset = -Math.floor(count / 2);
    return Array.from({ length: count }, (_, index) => {
      const offset = firstOffset + index;
      return {
        tag: tags[(activeIndex + offset + tags.length) % tags.length],
        offset,
      };
    });
  }

  function allocateHomeArtwork(spotlights: HomeTagInfo[], groups: Array<{ cover: HomeTagInfo | null }>) {
    const assignments = new Map<string, HomeCoverCandidate>();
    const usedFileIds = new Set<number>();
    const daySeed = dailySeed;

    function assign(surface: 'spotlight' | 'neighborhood', tag: HomeTagInfo, offset: number) {
      const candidates = tagCoverCandidates(tag);
      if (candidates.length === 0) return;
      const start = (daySeed + offset) % candidates.length;
      let selected = candidates[start];
      for (let index = 0; index < candidates.length; index += 1) {
        const candidate = candidates[(start + index) % candidates.length];
        if (!usedFileIds.has(candidate.file_id)) {
          selected = candidate;
          break;
        }
      }
      assignments.set(artworkKey(surface, tag), selected);
      usedFileIds.add(selected.file_id);
    }

    spotlights.forEach((tag, index) => assign('spotlight', tag, index));
    groups.forEach((group, index) => {
      if (group.cover) assign('neighborhood', group.cover, index + 3);
    });
    return assignments;
  }

  function spotlightArtwork(assignments: Map<string, HomeCoverCandidate>, tag: HomeTagInfo | null) {
    return tag ? assignments.get(artworkKey('spotlight', tag)) ?? tagCoverCandidates(tag)[0] ?? null : null;
  }

  function neighborhoodArtwork(assignments: Map<string, HomeCoverCandidate>, tag: HomeTagInfo | null) {
    return tag ? assignments.get(artworkKey('neighborhood', tag)) ?? tagCoverCandidates(tag)[0] ?? null : null;
  }

  function streamLoopItems(items: StreamItem[]) {
    if (items.length === 0) return [];
    const base = items.slice(0, 18);
    return [...base, ...base];
  }

  function railLoopItems(rail: HomeImageRail) {
    return streamLoopItems(
      rail.items.map((item) => ({
        ...item,
        rail_key: rail.key,
        rail_label: rail.label,
      })),
    );
  }

  function homeStorageKey(ratingKey: string, kind: 'tags' | 'rails') {
    return persistentStorageKey(`home:${homeCacheVersion}:${kind}:${ratingKey || 'all'}`);
  }

  function loadCachedHome(ratingKey: string) {
    if (typeof localStorage === 'undefined') return false;
    let restored = false;
    const rawTags = localStorage.getItem(homeStorageKey(ratingKey, 'tags'));
    if (rawTags) {
      try {
        const parsed = JSON.parse(rawTags) as HomeTags;
        if (Array.isArray(parsed.featured) && parsed.groups) {
          homeTags = parsed;
          restored = true;
        }
      } catch {
        localStorage.removeItem(homeStorageKey(ratingKey, 'tags'));
      }
    }

    const rawRails = localStorage.getItem(homeStorageKey(ratingKey, 'rails'));
    if (rawRails) {
      try {
        const parsed = JSON.parse(rawRails) as { rails: HomeImageRail[] };
        if (Array.isArray(parsed.rails)) {
          imageRails = parsed.rails;
        }
      } catch {
        localStorage.removeItem(homeStorageKey(ratingKey, 'rails'));
      }
    }
    return restored;
  }

  function saveCachedHomeTags(ratingKey: string, tags: HomeTags) {
    if (typeof localStorage === 'undefined') return;
    localStorage.setItem(homeStorageKey(ratingKey, 'tags'), JSON.stringify(tags));
  }

  function saveCachedImageRails(ratingKey: string, rails: HomeImageRail[]) {
    if (typeof localStorage === 'undefined') return;
    localStorage.setItem(homeStorageKey(ratingKey, 'rails'), JSON.stringify({ rails }));
  }

  function scheduleRails(ratingKey: string, requestId: number) {
    if (railTimer !== null) window.clearTimeout(railTimer);
    railTimer = window.setTimeout(() => {
      loadImageRails(ratingKey, requestId);
    }, 120);
  }

  async function loadHome() {
    const ratingKey = $activeRating ?? '';
    loadedRatingKey = ratingKey;
    const requestId = ++homeRequestSerial;
    const restored = loadCachedHome(ratingKey);
    loadingTags = !restored;
    loadingRails = false;
    error = '';
    if (!restored) imageRails = [];
    try {
      const tags = await api.getHomeTags({
        rating: $activeRating || undefined,
        featured_limit: 16,
        group_limit: 10,
      });
      if (requestId !== homeRequestSerial) return;
      homeTags = tags;
      saveCachedHomeTags(ratingKey, tags);
      loadingTags = false;
      window.setTimeout(scheduleSpotlightAdvance, 0);
      scheduleRails(ratingKey, requestId);
    } catch (e) {
      console.error('Failed to load home tags:', e);
      if (requestId === homeRequestSerial) {
        error = 'Failed to load home';
        loadingTags = false;
      }
    }
  }

  async function loadImageRails(ratingKey: string, homeRequestId: number) {
    const requestId = ++railRequestSerial;
    loadingRails = true;
    try {
      const rails = (await api.getHomeImageRails({
        rating: ratingKey || undefined,
        per_rail: 24,
      })).rails;
      if (requestId === railRequestSerial && homeRequestId === homeRequestSerial) {
        imageRails = rails;
        saveCachedImageRails(ratingKey, rails);
      }
    } catch (railError) {
      console.error('Failed to load home image rails:', railError);
      if (requestId === railRequestSerial) imageRails = [];
    } finally {
      if (requestId === railRequestSerial) loadingRails = false;
    }
  }

  function useTag(tag: HomeTagInfo) {
    browseTagSelection.set({
      name: tag.name,
      category: tag.category,
      count: tag.count,
      source: 'danbooru',
    });
    activeFolder.set(null);
    activeCollectionId.set(null);
    viewMode.set('tags');
  }

  function useTagIfPresent(tag: HomeTagInfo | null) {
    if (tag) useTag(tag);
  }

  function releaseLaneFocusPause() {
    const activeElement = document.activeElement;
    if (activeElement instanceof HTMLElement && activeElement.closest('.home-lane')) {
      activeElement.blur();
    }
  }

  function openImage(item: HomeImageRailItem) {
    releaseLaneFocusPause();
    selectedImageId.set(item.id);
  }

  function openSpotlightImage() {
    if (activeSpotlightArtwork) selectedImageId.set(activeSpotlightArtwork.post_id);
  }

  function openChallenges() {
    activeCollectionId.set(null);
    viewMode.set('challenges');
  }

  function openTags() {
    browseTagSelection.set(null);
    activeFolder.set(null);
    activeCollectionId.set(null);
    viewMode.set('tags');
  }

  function discoveryLaneItems(rail: { items: HomeImageRailItem[] }, railIndex: number, assignedIds: Set<number>) {
    const unassigned = rail.items.filter((item) => !assignedIds.has(item.file_id));
    return dailySequence(unassigned.length > 0 ? unassigned : rail.items, 211 + railIndex, 12);
  }

  async function openRandomImage() {
    if (randomLoading) return;
    randomLoading = true;
    try {
      const result = await api.getRandomImage({
        rating: $activeRating || undefined,
      });
      selectedImageId.set(result.id);
    } catch (e) {
      console.error('Failed to open random image:', e);
    } finally {
      randomLoading = false;
    }
  }

  $: featuredTags = dailySequence(
    homeTags.featured.filter((tag) => tagCoverCandidates(tag).length > 0),
    7,
  );
  $: spotlightTag = featuredTags[0] ?? null;
  $: sideSpotlightTags = featuredTags.slice(1, 5);
  $: featuredGridTags = featuredTags.slice(5, 16);
  $: discoveryRailCandidates = discoveryRailOrder
    .map((key) => imageRails.find((rail) => rail.key === key))
    .filter((rail): rail is HomeImageRail => Boolean(rail?.items.length))
    .slice(0, 3);
  $: discoverySpotlightPool = [0, 1]
    .flatMap(pickIndex => spotlightCategories.flatMap((category, categoryIndex) => dailySpotlightPicks(category, categoryIndex, homeTags, featuredTags, imageRails, 2).slice(pickIndex, pickIndex + 1)))
    .filter((tag, index, tags) => tags.findIndex((candidate) => candidate.name === tag.name && candidate.category === tag.category) === index)
    .slice(0, 8);
  $: dailySpotlightTag = discoverySpotlightPool[dailyIndex(discoverySpotlightPool.length)] ?? spotlightTag;
  $: discoverySpotlightTag = discoverySpotlightPool.find((tag) => spotlightKey(tag) === selectedSpotlightKey) ?? dailySpotlightTag ?? null;
  $: spotlightCarouselTags = spotlightWindow(discoverySpotlightPool, discoverySpotlightTag);
  $: tagNeighborhoods = categoryOrder
    .map((category, categoryIndex) => {
      const tags = homeTags.groups[category] ?? [];
      const railTag = railCoverTag(category);
      const coverCandidates = [
        ...tags.filter((tag) => tagCoverCandidates(tag).length > 0),
        ...featuredTags.filter((tag) => tag.category === category),
        ...(railTag ? [railTag] : []),
      ].filter((tag, index, candidates) => candidates.findIndex((candidate) => spotlightKey(candidate) === spotlightKey(tag)) === index);
      const cover = dailySequence(coverCandidates, 101 + categoryIndex, 1)[0] ?? null;
      return {
        category,
        cover,
        tags: dailySequence(
          tags.filter((tag) => tag.name !== cover?.name),
          151 + categoryIndex,
          8,
        ),
      };
    })
    .filter((group) => group.cover || group.tags.length > 0);
  $: discoveryTagGroups = tagNeighborhoods.filter((group) => group.category !== 'meta');
  $: homeArtworkAssignments = allocateHomeArtwork(discoverySpotlightPool, discoveryTagGroups);
  $: assignedHomeArtworkIds = new Set(
    [...homeArtworkAssignments.values()].map((candidate) => candidate.file_id),
  );
  $: discoveryRails = discoveryRailCandidates
    .map((rail, railIndex) => ({
      ...rail,
      items: discoveryLaneItems(rail, railIndex, assignedHomeArtworkIds),
    }))
    .filter((rail) => rail.items.length > 0);
  $: activeSpotlightArtwork = spotlightArtwork(homeArtworkAssignments, discoverySpotlightTag);
  $: discoveryTagCards = discoveryTagGroups.map((group) => ({
    ...group,
    artwork: neighborhoodArtwork(homeArtworkAssignments, group.cover),
  }));
  $: tagTotal = categoryOrder.reduce(
    (total, category) => total + (homeTags.groups[category]?.length ?? 0),
    0,
  );
  $: streamItems = dailySequence(
    imageRails.flatMap((rail) =>
      rail.items.map((item) => ({
        ...item,
        rail_key: rail.key,
        rail_label: rail.label,
      })),
    )
    .filter((item, index, items) => items.findIndex((candidate) => candidate.file_id === item.file_id) === index),
    307,
    18,
  );
  $: if (mounted && loadedRatingKey !== ($activeRating ?? '')) {
    loadHome();
  }
</script>

<div class="h-full overflow-y-auto bg-[#0f0f14]">
  <div class="px-6 py-6">
    {#if error}
      <div class="rounded-lg border border-red-500/30 bg-red-600/10 px-4 py-3 text-sm text-red-200">
        {error}
      </div>
    {:else if loadingTags}
      {#if $homeLayout === 'classic'}
        <div class="space-y-5">
          <div class="grid min-h-[420px] gap-4 lg:grid-cols-[minmax(0,1.25fr)_minmax(340px,.75fr)]">
            <div class="animate-pulse rounded-lg bg-[#1a1a24]"></div>
            <div class="grid grid-cols-2 gap-3">
              {#each Array(4) as _}
                <div class="animate-pulse rounded-lg bg-[#1a1a24]"></div>
              {/each}
            </div>
          </div>
          <div class="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-4">
            {#each Array(8) as _}
              <div class="aspect-[4/3] animate-pulse rounded-lg bg-[#1a1a24]"></div>
            {/each}
          </div>
        </div>
      {:else}
        <div class="space-y-6">
          <div class="h-[272px] animate-pulse rounded-[24px] bg-[#171721]"></div>
          <div class="space-y-5">
            {#each Array(3) as _}
              <div class="h-[145px] animate-pulse rounded-2xl bg-[#15151e]"></div>
            {/each}
          </div>
        </div>
      {/if}
    {:else if $homeLayout === 'classic'}
      <section class="-mx-6 border-y border-[#242435] bg-[#11111a] px-6 py-5">
        <div class="grid gap-5 lg:grid-cols-[minmax(0,1.18fr)_minmax(330px,.82fr)]">
          {#if spotlightTag}
            <button
              class="group relative min-h-[430px] overflow-hidden rounded-lg border border-[#2a2a3a] bg-[#09090e] text-left shadow-[0_24px_80px_rgba(0,0,0,0.35)] transition-colors hover:border-purple-500/55"
              on:click={() => useTag(spotlightTag)}
              title="Filter by {displayTag(spotlightTag.name)}"
            >
              <img
                src={tagImage(spotlightTag, 760)}
                alt={displayTag(spotlightTag.name)}
                class="absolute inset-0 h-full w-full object-cover transition-transform duration-500 group-hover:scale-[1.03]"
                decoding="async"
                loading="eager"
              />
              <div class="absolute inset-0 bg-gradient-to-t from-[#09090e] via-[#09090e]/28 to-transparent"></div>
              <div class="absolute inset-x-0 bottom-0 p-5">
                <div class="mb-3 flex flex-wrap items-center gap-2">
                  <span class="rounded border px-2 py-1 text-[10px] font-semibold uppercase tracking-wider {categoryClass(spotlightTag.category)}">
                    {spotlightTag.category}
                  </span>
                  <span class="rounded border border-white/15 bg-black/40 px-2 py-1 text-xs text-gray-200">
                    {countLabel(spotlightTag.count)} posts
                  </span>
                </div>
                <h2 class="max-w-3xl truncate text-4xl font-semibold text-white">{displayTag(spotlightTag.name)}</h2>
              </div>
            </button>
          {/if}

          <div class="grid gap-4">
            <div class="grid grid-cols-2 gap-3">
              {#each sideSpotlightTags as tag}
                <button
                  class="group relative aspect-[4/3] overflow-hidden rounded-lg border border-[#2a2a3a] bg-[#171721] text-left transition-colors hover:border-purple-500/50"
                  on:click={() => useTag(tag)}
                  title="Filter by {displayTag(tag.name)}"
                >
                  <img
                    src={tagImage(tag, 360)}
                    alt={displayTag(tag.name)}
                    class="h-full w-full object-cover transition-transform duration-300 group-hover:scale-105"
                    loading="eager"
                    decoding="async"
                  />
                  <div class="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/90 via-black/55 to-transparent p-3 pt-10">
                    <div class="truncate text-sm font-semibold text-white">{displayTag(tag.name)}</div>
                    <div class="mt-1 text-xs text-gray-300">{countLabel(tag.count)} posts</div>
                  </div>
                </button>
              {/each}
            </div>

            <div class="grid gap-3 sm:grid-cols-3">
              <button
                class="group rounded-lg border border-pink-500/25 bg-pink-600/10 px-4 py-4 text-left transition-colors hover:border-pink-500/55 hover:bg-pink-600/16"
                on:click={openChallenges}
              >
                <span class="block text-xs uppercase tracking-wider text-pink-300/80">Daily</span>
                <span class="mt-1 block text-lg font-semibold text-pink-50">Challenge</span>
              </button>
              <button
                class="group rounded-lg border border-purple-500/25 bg-purple-600/10 px-4 py-4 text-left transition-colors hover:border-purple-500/55 hover:bg-purple-600/16 disabled:cursor-wait disabled:opacity-60"
                on:click={openRandomImage}
                disabled={randomLoading}
              >
                <span class="block text-xs uppercase tracking-wider text-purple-300/80">Shuffle</span>
                <span class="mt-1 block text-lg font-semibold text-purple-50">{randomLoading ? 'Opening' : 'Random'}</span>
              </button>
              <div class="rounded-lg border border-[#2a2a3a] bg-[#171721] px-4 py-4">
                <span class="block text-xs uppercase tracking-wider text-cyan-300/75">Loaded</span>
                <span class="mt-1 block text-lg font-semibold text-cyan-50">{featuredTags.length} featured</span>
                <span class="mt-1 block text-xs text-gray-500">{tagTotal} tag links</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      {#if loadingRails}
        <section class="mt-6">
          <div class="h-[146px] animate-pulse rounded-lg bg-[#171721]"></div>
        </section>
      {:else if streamItems.length > 0}
        <section class="-mx-6 mt-6 border-y border-[#242435] bg-[#0b0b10] py-4">
          <div class="mb-3 flex items-center gap-3 px-6">
            <div class="h-7 w-1 rounded-full bg-cyan-400"></div>
            <h2 class="text-lg font-semibold text-gray-100">Image Drift</h2>
            <div class="h-px flex-1 bg-[#242435]"></div>
            <span class="text-xs text-gray-500">{streamItems.length} images</span>
          </div>
          <div class="home-stream-window overflow-hidden">
            <div class="home-stream-track flex w-max gap-3 px-6">
              {#each streamLoopItems(streamItems) as item, index (`${item.rail_key}-${item.id}-${index}`)}
                <button
                  class="group relative h-[128px] w-[186px] shrink-0 overflow-hidden rounded-lg border border-[#2a2a3a] bg-[#171721] text-left shadow-[0_12px_30px_rgba(0,0,0,0.3)] transition-colors hover:border-purple-500/55"
                  on:click={() => openImage(item)}
                  title={streamTitle(item)}
                  aria-label={streamTitle(item)}
                >
                  <img
                    src={thumbnailUrl(item.file_id, 300, item.thumbnail_token)}
                    alt={streamLabel(item)}
                    class="h-full w-full object-cover transition-transform duration-300 group-hover:scale-105"
                    loading={index < 10 ? 'eager' : 'lazy'}
                    decoding="async"
                  />
                  <div class="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/90 via-black/55 to-transparent p-2 pt-8">
                    <div class="flex min-w-0 items-center gap-2">
                      <span class="shrink-0 rounded border px-1.5 py-0.5 text-[9px] uppercase tracking-wider {streamAccentClass(item.rail_key)}">
                        {item.rail_label.slice(0, 4)}
                      </span>
                      <span class="min-w-0 truncate text-xs font-semibold text-white">{streamLabel(item)}</span>
                    </div>
                  </div>
                </button>
              {/each}
            </div>
          </div>
        </section>
      {/if}

      <section class="mt-7">
        <div class="mb-4 flex items-center gap-3">
          <div class="h-7 w-1 rounded-full bg-purple-400"></div>
          <h2 class="text-lg font-semibold text-gray-100">Featured Tags</h2>
          <div class="h-px flex-1 bg-[#242435]"></div>
        </div>
        <div class="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5">
          {#each featuredGridTags as tag}
            <button
              class="group relative aspect-[4/3] overflow-hidden rounded-lg border border-[#2a2a3a] bg-[#1a1a24] text-left shadow-[0_12px_30px_rgba(0,0,0,0.22)] transition-colors hover:border-purple-500/50"
              on:click={() => useTag(tag)}
              title="Filter by {displayTag(tag.name)}"
            >
              <img
                src={tagImage(tag, 340)}
                alt={displayTag(tag.name)}
                class="h-full w-full object-cover transition-transform duration-300 group-hover:scale-105"
                loading="lazy"
                decoding="async"
              />
              <div class="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/90 via-black/55 to-transparent p-3 pt-10">
                <div class="truncate text-sm font-semibold text-white">{displayTag(tag.name)}</div>
                <div class="mt-1 flex items-center gap-2">
                  <span class="rounded border px-1.5 py-0.5 text-[9px] uppercase tracking-wider {categoryClass(tag.category)}">
                    {tag.category.slice(0, 4)}
                  </span>
                  <span class="text-xs text-gray-300">{countLabel(tag.count)}</span>
                </div>
              </div>
            </button>
          {/each}
        </div>
      </section>

      <section class="mt-7">
        <div class="mb-4 flex items-center gap-3">
          <div class="h-7 w-1 rounded-full bg-blue-400"></div>
          <h2 class="text-lg font-semibold text-gray-100">More Tags</h2>
          <div class="h-px flex-1 bg-[#242435]"></div>
        </div>
        <div class="space-y-3">
          {#each categoryOrder as category}
            {@const tags = homeTags.groups[category] ?? []}
            {#if tags.length > 0}
              <div class="grid gap-2 border-b border-[#20202d] pb-3 last:border-b-0 lg:grid-cols-[150px_minmax(0,1fr)]">
                <div class="flex items-center gap-2">
                  <span class="h-2.5 w-2.5 shrink-0 rounded-full {categoryDotClasses[category] ?? 'bg-gray-400'}"></span>
                  <span class="truncate text-sm font-semibold text-gray-200">{categoryLabels[category] ?? category}</span>
                </div>
                <div class="flex min-w-0 flex-wrap gap-2">
                  {#each tags as tag}
                    <button
                      class="group min-w-0 rounded-lg border border-[#2a2a3a] bg-[#171721] px-3 py-2 text-left transition-colors hover:border-purple-500/40 hover:bg-[#1e1e2e]"
                      on:click={() => useTag(tag)}
                      title="Filter by {displayTag(tag.name)}"
                    >
                      <span class="text-sm text-gray-300 group-hover:text-purple-100">{displayTag(tag.name)}</span>
                      <span class="ml-2 text-xs text-gray-600">{countLabel(tag.count)}</span>
                    </button>
                  {/each}
                </div>
              </div>
            {/if}
          {/each}
        </div>
      </section>
    {:else}
      <section class="discovery-spotlight relative min-h-[410px] overflow-hidden rounded-[26px] border border-white/[0.1] bg-[#0b0b12] shadow-[0_28px_90px_rgba(0,0,0,.42)]">
        {#if discoverySpotlightTag && activeSpotlightArtwork}
          {#key `${spotlightKey(discoverySpotlightTag)}:${activeSpotlightArtwork.file_id}`}
            <button
              class="spotlight-hero-art absolute inset-0 w-full cursor-zoom-in text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-white/80"
              type="button"
              on:click={openSpotlightImage}
              title="Open image detail"
              aria-label="Open spotlight image detail"
              transition:fade={{ duration: 440 }}
            >
              <img
                src={artworkUrl(activeSpotlightArtwork, 1200)}
                alt={displayTag(discoverySpotlightTag.name)}
                class="pointer-events-none h-full w-full object-cover"
                style={`object-position: ${artworkObjectPosition(activeSpotlightArtwork)};`}
                decoding="async"
                loading="eager"
              />
            </button>
          {/key}
        {/if}

        <div class="pointer-events-none absolute inset-0 bg-[linear-gradient(90deg,rgba(5,7,14,.94)_0%,rgba(5,7,14,.74)_37%,rgba(5,7,14,.18)_70%,rgba(5,7,14,.08)_100%)]"></div>
        <div class="pointer-events-none absolute inset-x-0 bottom-0 h-[72%] bg-gradient-to-t from-[#070a12] via-[#070a12]/62 to-transparent"></div>
        <div class="pointer-events-none absolute inset-x-0 top-0 h-24 bg-gradient-to-b from-black/35 to-transparent"></div>

        <div class="spotlight-content relative z-10 flex min-h-[410px] flex-col p-5 sm:p-7">
          <div class="flex items-start gap-4">
            {#if discoverySpotlightTag}
              <button class="inline-flex min-w-0 items-center gap-2 rounded-full border border-white/10 bg-black/30 px-3 py-1.5 text-xs text-gray-200 backdrop-blur-md transition-colors hover:border-white/25 hover:text-white" type="button" on:click={() => useTag(discoverySpotlightTag)}>
                <span class="h-1.5 w-1.5 rounded-full {categoryDotClasses[discoverySpotlightTag.category] ?? 'bg-gray-400'}"></span>
                <span class="truncate">Daily spotlight · {spotlightCategoryLabels[discoverySpotlightTag.category] ?? discoverySpotlightTag.category}</span>
              </button>
            {:else}
              <span class="rounded-full border border-white/10 bg-black/30 px-3 py-1.5 text-xs text-gray-200 backdrop-blur-md">Daily spotlight</span>
            {/if}
          </div>

          <div class="mt-auto grid items-end gap-6 xl:grid-cols-[minmax(0,1fr)_auto]">
            <div class="min-w-0 max-w-2xl">
              <div class="mb-2 text-[11px] font-medium text-purple-100/75">Today from your library</div>
              {#if discoverySpotlightTag}
                {#key `${spotlightKey(discoverySpotlightTag)}:copy`}
                  <div class="spotlight-copy-switch">
                    <button class="block max-w-full text-left" type="button" on:click={() => useTag(discoverySpotlightTag)}>
                      <h1 class="line-clamp-2 text-3xl font-semibold tracking-[-0.035em] text-white drop-shadow-[0_2px_18px_rgba(0,0,0,.55)] sm:text-4xl">{displayTag(discoverySpotlightTag.name)}</h1>
                    </button>
                    <p class="mt-2 max-w-lg text-sm leading-6 text-gray-200/85">{spotlightReason(discoverySpotlightTag)}</p>
                  </div>
                {/key}
              {:else}
                <h1 class="text-3xl font-semibold tracking-[-0.035em] text-white sm:text-4xl">Your library, ready to wander</h1>
                <p class="mt-2 text-sm text-gray-300">Add local tags and covers to grow your daily spotlight.</p>
              {/if}

              <div class="mt-4 flex flex-wrap items-center gap-2">
                {#if discoverySpotlightTag}
                  <button class="inline-flex h-9 items-center gap-2 rounded-lg bg-white px-3.5 text-xs font-semibold text-[#111118] shadow-lg transition-colors hover:bg-purple-100" type="button" on:click={() => useTag(discoverySpotlightTag)}>
                    Explore tag
                    <svg class="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" d="m9 5 7 7-7 7"/></svg>
                  </button>
                {/if}
                <button class="spotlight-action" type="button" on:click={openChallenges}>Challenge</button>
                <button class="spotlight-action disabled:cursor-wait disabled:opacity-60" type="button" on:click={openRandomImage} disabled={randomLoading}>{randomLoading ? 'Opening' : 'Surprise me'}</button>
                <button class="spotlight-action" type="button" on:click={openTags}>All tags</button>
              </div>
            </div>

            {#if spotlightCarouselTags.length > 0}
              <div class="spotlight-carousel w-full max-w-[520px] xl:w-auto" aria-label="Spotlight tag carousel">
                <div class="flex items-end justify-center gap-2 xl:justify-end">
                  {#each spotlightCarouselTags as item (spotlightKey(item.tag))}
                    {@const artwork = spotlightArtwork(homeArtworkAssignments, item.tag)}
                    <button
                      class="spotlight-peek group relative shrink-0 overflow-hidden rounded-xl border bg-black/45 text-left shadow-xl backdrop-blur-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white"
                      class:is-active={item.offset === 0}
                      class:is-near={Math.abs(item.offset) === 1}
                      class:is-far={Math.abs(item.offset) >= 2}
                      type="button"
                      on:click={() => chooseSpotlight(item.tag)}
                      animate:flip={{ duration: 440 }}
                      aria-current={item.offset === 0 ? 'true' : undefined}
                      aria-label="Spotlight {displayTag(item.tag.name)}"
                      title="Spotlight {displayTag(item.tag.name)}"
                    >
                      {#if artwork}
                        <img src={artworkUrl(artwork, 300)} alt="" class="h-full w-full object-cover transition-transform duration-300 group-hover:scale-105" style={`object-position: ${artworkObjectPosition(artwork)};`} loading="eager" decoding="async" />
                      {/if}
                      <span class="absolute inset-x-0 bottom-0 truncate bg-gradient-to-t from-black/95 via-black/55 to-transparent px-2 pb-1.5 pt-5 text-[10px] font-medium text-white">{displayTag(item.tag.name)}</span>
                    </button>
                  {/each}
                </div>
                {#if discoverySpotlightPool.length > 1}
                  <div class="mt-2 h-0.5 overflow-hidden rounded-full bg-white/20">
                    {#key spotlightProgressKey}
                      <span class="spotlight-progress-fill block h-full origin-left rounded-full bg-white" style={`animation-duration: ${SPOTLIGHT_DURATION_MS}ms;`}></span>
                    {/key}
                  </div>
                {/if}
              </div>
            {/if}
          </div>
        </div>
      </section>

      {#if loadingRails}
        <section class="mt-7 space-y-4">
          {#each Array(3) as _}
            <div class="h-[122px] animate-pulse rounded-2xl bg-[#171721]"></div>
          {/each}
        </section>
      {:else if discoveryRails.length > 0}
        <section class="home-motion mt-7" aria-label="Moving image discovery">
          <div class="mb-4 flex items-end gap-3">
            <div class="min-w-0">
              <h2 class="text-lg font-semibold tracking-[-0.01em] text-gray-100">From your library</h2>
            </div>
            <div class="mb-1 h-px flex-1 bg-gradient-to-r from-[#2a2a39] to-transparent"></div>
          </div>

          <div class="space-y-5">
            {#each discoveryRails as rail, railIndex (rail.key)}
              <div class="home-lane" role="region" aria-label="{discoveryRailLabel(rail)} image lane">
                <div class="mb-2 flex items-center gap-2.5">
                  <span class="h-2 w-2 rounded-full {categoryDotClasses[rail.key] ?? (rail.key === 'favorites' ? 'bg-pink-400' : 'bg-gray-400')}"></span>
                  <h3 class="text-sm font-medium text-gray-200">{discoveryRailLabel(rail)}</h3>
                  <div class="h-px flex-1 bg-[#242432]"></div>
                  <span class="text-[10px] text-gray-600">{rail.items.length} picks</span>
                </div>
                <div class="home-lane-window overflow-hidden rounded-2xl">
                  <div class="home-lane-track home-lane-{railIndex + 1} flex w-max gap-3">
                    {#each railLoopItems(rail) as item, index (`new-${item.rail_key}-${item.id}-${index}`)}
                      <button
                        class="group relative h-[118px] w-[210px] shrink-0 overflow-hidden rounded-2xl border border-white/[0.08] bg-[#171721] text-left shadow-[0_12px_30px_rgba(0,0,0,.18)] transition-[border-color,transform] hover:-translate-y-0.5 hover:border-purple-300/35 focus-visible:border-cyan-300 focus-visible:outline-none"
                        on:click={() => openImage(item)}
                        title={streamTitle(item)}
                        aria-label={streamTitle(item)}
                      >
                        <img
                          src={thumbnailUrl(item.file_id, 300, item.thumbnail_token)}
                          alt={streamLabel(item)}
                          class="h-full w-full object-cover transition-transform duration-300 group-hover:scale-105"
                          style={`object-position: ${artworkObjectPosition(item)};`}
                          loading={railIndex === 0 && index < 10 ? 'eager' : 'lazy'}
                          decoding="async"
                        />
                        <div class="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/90 via-black/40 to-transparent p-2.5 pt-8 opacity-0 transition-opacity duration-200 group-hover:opacity-100 group-focus-visible:opacity-100">
                          <div class="truncate text-xs font-medium text-white">{streamLabel(item)}</div>
                        </div>
                      </button>
                    {/each}
                  </div>
                </div>
              </div>
            {/each}
          </div>
        </section>
      {/if}

      {#if discoveryTagCards.length > 0}
        <section class="mt-9 pb-2" aria-labelledby="tag-paths-heading">
          <div class="mb-4 flex flex-wrap items-end justify-between gap-4">
            <h2 id="tag-paths-heading" class="text-xl font-semibold tracking-[-0.02em] text-white">Tag neighborhoods</h2>
            <button class="inline-flex h-9 items-center gap-1.5 rounded-full border border-white/[0.09] bg-white/[0.025] px-3.5 text-xs text-gray-300 transition-colors hover:border-purple-300/30 hover:text-white" type="button" on:click={openTags}>
              Full tag index
              <svg class="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" d="m9 5 7 7-7 7"/></svg>
            </button>
          </div>

          <div class="grid gap-3 sm:grid-cols-2 2xl:grid-cols-4">
            {#each discoveryTagCards as group (group.category)}
              <article class="tag-neighborhood overflow-hidden rounded-2xl border border-white/[0.08] bg-[#14141d]">
                {#if group.cover}
                  <button class="group relative block h-32 w-full overflow-hidden text-left" type="button" on:click={() => useTagIfPresent(group.cover)} title="Open {displayTag(group.cover.name)}">
                    {#if group.artwork}
                      <img src={artworkUrl(group.artwork, 520)} alt={displayTag(group.cover.name)} class="h-full w-full object-cover transition-transform duration-500 group-hover:scale-105" style={`object-position: ${artworkObjectPosition(group.artwork)};`} loading="lazy" decoding="async" />
                    {/if}
                    <div class="absolute inset-0 bg-gradient-to-t from-[#0b0b11] via-black/5 to-transparent"></div>
                    <div class="absolute inset-x-0 bottom-0 p-4">
                      <div class="flex items-center gap-2 text-[10px] font-medium uppercase tracking-[0.12em] text-white/65"><span class="h-1.5 w-1.5 rounded-full {categoryDotClasses[group.category] ?? 'bg-gray-400'}"></span>{categoryLabels[group.category] ?? group.category}</div>
                      <div class="mt-1 truncate text-base font-semibold text-white">{displayTag(group.cover.name)}</div>
                    </div>
                  </button>
                {:else}
                  <div class="flex h-32 items-end bg-[radial-gradient(circle_at_20%_0%,rgba(168,85,247,.18),transparent_55%),#101018] p-4">
                    <div><span class="h-1.5 w-1.5 rounded-full {categoryDotClasses[group.category] ?? 'bg-gray-400'}"></span><div class="mt-2 text-base font-semibold text-white">{categoryLabels[group.category] ?? group.category}</div></div>
                  </div>
                {/if}

                <div class="p-3">
                  <p class="line-clamp-2 min-h-10 px-1 text-[11px] leading-5 text-gray-500">{categoryDescription(group.category)}</p>
                  <div class="mt-2 border-t border-white/[0.07]">
                    {#each group.tags.slice(0, 4) as tag}
                      <button class="group flex w-full min-w-0 items-center gap-2 border-b border-white/[0.06] px-1 py-2.5 text-left transition-colors hover:bg-white/[0.03]" type="button" on:click={() => useTag(tag)} title="Open {displayTag(tag.name)}">
                        <span class="min-w-0 flex-1 truncate text-xs text-gray-300 transition-colors group-hover:text-white">{displayTag(tag.name)}</span>
                        <span class="text-[10px] tabular-nums text-gray-600">{countLabel(tag.count)}</span>
                        <svg class="h-3 w-3 shrink-0 text-gray-700 transition-colors group-hover:text-purple-300" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" d="m9 5 7 7-7 7"/></svg>
                      </button>
                    {/each}
                  </div>
                </div>
              </article>
            {/each}
          </div>
        </section>
      {/if}
    {/if}
  </div>
</div>

<style>
  .spotlight-content {
    pointer-events: none;
  }

  .spotlight-content button {
    pointer-events: auto;
  }

  .spotlight-hero-art {
    animation: spotlight-hero-drift 9s ease-out both;
  }

  .spotlight-peek {
    width: 4.1rem;
    height: 3.05rem;
    border-color: rgba(255, 255, 255, 0.13);
    opacity: 0.66;
    transition:
      width 420ms cubic-bezier(0.2, 0.8, 0.2, 1),
      height 420ms cubic-bezier(0.2, 0.8, 0.2, 1),
      opacity 180ms ease,
      border-color 180ms ease,
      transform 220ms ease;
  }

  .spotlight-peek.is-near {
    width: 4.9rem;
    height: 3.65rem;
    opacity: 0.82;
  }

  .spotlight-peek.is-active {
    z-index: 2;
    width: 6.5rem;
    height: 4.8rem;
    border-color: rgba(255, 255, 255, 0.78);
    opacity: 1;
    transform: translateY(-0.18rem);
    box-shadow: 0 16px 38px rgba(0, 0, 0, 0.48);
  }

  .spotlight-peek:hover {
    border-color: rgba(255, 255, 255, 0.72);
    opacity: 1;
  }

  .spotlight-progress-fill {
    width: 100%;
    transform: scaleX(0);
    animation-name: spotlight-progress;
    animation-timing-function: linear;
    animation-fill-mode: forwards;
  }

  .spotlight-copy-switch {
    animation: spotlight-copy-in 320ms cubic-bezier(0.2, 0.8, 0.2, 1) both;
  }

  .spotlight-action {
    display: inline-flex;
    height: 2.25rem;
    align-items: center;
    gap: 0.5rem;
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 0.5rem;
    background: rgba(8, 8, 14, 0.42);
    padding: 0 0.75rem;
    color: rgb(209 213 219);
    font-size: 0.75rem;
    line-height: 1rem;
    backdrop-filter: blur(12px);
    transition: border-color 160ms ease, background-color 160ms ease, color 160ms ease;
  }

  .spotlight-action:hover {
    border-color: rgba(216, 180, 254, 0.32);
    background: rgba(255, 255, 255, 0.09);
    color: white;
  }

  .tag-neighborhood {
    transition:
      border-color 180ms ease,
      transform 220ms cubic-bezier(0.2, 0.8, 0.2, 1),
      box-shadow 220ms ease;
  }

  .tag-neighborhood:hover {
    transform: translateY(-2px);
    border-color: rgba(216, 180, 254, 0.2);
    box-shadow: 0 18px 44px rgba(0, 0, 0, 0.22);
  }

  .home-stream-track {
    animation: home-stream-slide 58s linear infinite;
    will-change: transform;
  }

  .home-stream-window:hover .home-stream-track {
    animation-play-state: paused;
  }

  .home-lane-track {
    animation: home-lane-slide 72s linear infinite;
    animation-play-state: running;
    will-change: transform;
  }

  .home-lane-2 {
    animation-direction: reverse;
    animation-duration: 84s;
  }

  .home-lane-3 {
    animation-duration: 96s;
  }

  .home-lane:hover .home-lane-track,
  .home-lane:focus-within .home-lane-track {
    animation-play-state: paused;
  }

  @keyframes spotlight-hero-drift {
    from {
      transform: scale(1.025);
    }
    to {
      transform: scale(1);
    }
  }

  @keyframes spotlight-progress {
    from {
      transform: scaleX(0);
    }
    to {
      transform: scaleX(1);
    }
  }

  @keyframes spotlight-copy-in {
    from {
      opacity: 0;
      transform: translateY(8px);
    }
    to {
      opacity: 1;
      transform: translateY(0);
    }
  }

  @keyframes home-stream-slide {
    from {
      transform: translateX(0);
    }
    to {
      transform: translateX(-50%);
    }
  }

  @keyframes home-lane-slide {
    from {
      transform: translateX(0);
    }
    to {
      transform: translateX(-50%);
    }
  }

  @media (prefers-reduced-motion: reduce) {
    :global(html:not([data-motion='full'])) .spotlight-hero-art,
    :global(html:not([data-motion='full'])) .spotlight-copy-switch,
    :global(html:not([data-motion='full'])) .spotlight-progress-fill {
      animation: none;
      transform: none;
    }

    :global(html:not([data-motion='full'])) .home-stream-window {
      overflow-x: auto;
    }

    :global(html:not([data-motion='full'])) .home-stream-track {
      animation: none;
      transform: none;
      width: max-content;
      padding-right: 1.5rem;
    }

    :global(html:not([data-motion='full'])) .home-lane-window {
      overflow-x: auto;
    }

    :global(html:not([data-motion='full'])) .home-lane-track {
      animation: none;
      transform: none;
      width: max-content;
      padding-right: 1.5rem;
    }
  }

  @media (max-width: 640px) {
    .spotlight-peek {
      width: 3.2rem;
      height: 2.55rem;
    }

    .spotlight-peek.is-near {
      width: 3.55rem;
      height: 2.85rem;
    }

    .spotlight-peek.is-active {
      width: 4.35rem;
      height: 3.45rem;
    }
  }
</style>
