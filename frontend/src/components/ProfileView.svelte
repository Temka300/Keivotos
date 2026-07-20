<script lang="ts">
  import { onMount, tick } from 'svelte';
  import {
    api,
    thumbnailUrl,
    type ArtistFollowInfo,
    type CollectionInfo,
    type ImageSummary,
    type Stats,
    type TagWikiExample,
  } from '../lib/api';
  import CollectionPreviewGrid from './CollectionPreviewGrid.svelte';
  import {
    activeCollectionId,
    artistFollowRefreshToken,
    artistFocusRequest,
    browseTagSelection,
    collectionRefreshToken,
    imageRefreshToken,
    normalizeProfileName,
    profileName,
    selectedImageId,
    viewMode,
  } from '../lib/stores';

  const favoritePreviewLimit = 9;
  const collectionPreviewLimit = 6;
  const artistExpandThreshold = 10;

  let stats: Stats | null = null;
  let favorites: ImageSummary[] = [];
  let favoriteTotal = 0;
  let collections: CollectionInfo[] = [];
  let artistFollows: ArtistFollowInfo[] = [];
  let loading = true;
  let error = '';
  let observedImageRefreshToken = 0;
  let observedCollectionRefreshToken = 0;
  let observedArtistFollowRefreshToken = 0;
  let artistFollowBusyTags = new Set<string>();
  let focusedArtistTagName: string | null = null;
  let focusedArtist: ArtistFollowInfo | null = null;
  let artistListExpanded = false;
  let artistRailElement: HTMLDivElement | null = null;
  let artistRailCanScrollLeft = false;
  let artistRailCanScrollRight = false;
  let artistProfileBulkBusy = false;
  let artistProfileBulkStatus = '';
  let editingProfileName = false;
  let profileNameDraft = '';
  let profileNameInput: HTMLInputElement | null = null;

  $: avatarUrl = stats?.profile_avatar_file_id
    ? thumbnailUrl(stats.profile_avatar_file_id, 360, stats.profile_avatar_token ?? undefined)
    : '/profile-avatar.svg';
  $: bannerUrl = stats?.profile_banner_file_id
    ? thumbnailUrl(stats.profile_banner_file_id, 1120, stats.profile_banner_token ?? undefined)
    : '/profile-banner.svg';
  $: favoritePercent = stats ? percent(stats.total_favorites, stats.total_images) : '0%';
  $: seenPercent = stats ? percent(stats.seen_images, stats.total_images) : '0%';
  $: collectionItemsLabel = stats ? `${formatNumber(stats.total_collection_items)} saved` : '0 saved';
  $: topCollections = collections.slice(0, collectionPreviewLimit);
  $: showArtistExpand = artistFollows.length >= artistExpandThreshold;
  $: if (artistListExpanded && !showArtistExpand) artistListExpanded = false;
  $: {
    const nextFocusedArtist = focusedArtistTagName
      ? artistFollows.find(follow => follow.tag_name === focusedArtistTagName) ?? null
      : null;
    focusedArtist = nextFocusedArtist;
    if (focusedArtistTagName && !nextFocusedArtist) {
      focusedArtistTagName = null;
    }
  }
  $: if ($artistFocusRequest && artistFollows.some(follow => follow.tag_name === $artistFocusRequest)) {
    focusedArtistTagName = $artistFocusRequest;
    artistFocusRequest.set(null);
  }

  onMount(() => {
    loadProfile(true);
  });

  $: if (
    $imageRefreshToken !== observedImageRefreshToken ||
    $collectionRefreshToken !== observedCollectionRefreshToken ||
    $artistFollowRefreshToken !== observedArtistFollowRefreshToken
  ) {
    observedImageRefreshToken = $imageRefreshToken;
    observedCollectionRefreshToken = $collectionRefreshToken;
    observedArtistFollowRefreshToken = $artistFollowRefreshToken;
    if (!loading) {
      loadProfile();
    }
  }

  function notifyArtistFollowRefresh() {
    artistFollowRefreshToken.update(n => {
      observedArtistFollowRefreshToken = n + 1;
      return n + 1;
    });
  }

  async function beginProfileNameEdit() {
    profileNameDraft = $profileName;
    editingProfileName = true;
    await tick();
    profileNameInput?.focus();
    profileNameInput?.select();
  }

  async function saveProfileName() {
    try {
      await profileName.set(normalizeProfileName(profileNameDraft));
      editingProfileName = false;
    } catch (caught) {
      error = caught instanceof Error ? caught.message : 'Could not save the profile name.';
    }
  }

  function cancelProfileNameEdit() {
    profileNameDraft = $profileName;
    editingProfileName = false;
  }

  function handleProfileNameKeydown(event: KeyboardEvent) {
    if (event.key !== 'Escape') return;
    event.preventDefault();
    cancelProfileNameEdit();
  }

  async function loadProfile(showLoader = false) {
    if (showLoader) loading = true;
    error = '';
    try {
      const [nextStats, favoritePage, nextCollections, nextArtistFollows] = await Promise.all([
        api.getStats(),
        api.getImages({
          favorites_only: true,
          sort: 'date',
          order: 'desc',
          offset: 0,
          limit: favoritePreviewLimit,
        }),
        api.getCollections(),
        api.getArtistFollows(),
        profileName.load(),
      ]);
      stats = nextStats;
      favorites = favoritePage.images;
      favoriteTotal = favoritePage.total;
      collections = nextCollections;
      artistFollows = nextArtistFollows;
      await tick();
      window.requestAnimationFrame(updateArtistRailControls);
    } catch (e) {
      console.error('Failed to load profile:', e);
      error = 'Profile could not load';
    } finally {
      if (showLoader) loading = false;
    }
  }

  function formatNumber(value: number | null | undefined) {
    return (value ?? 0).toLocaleString();
  }

  function formatBytes(value: number | null | undefined) {
    const size = value ?? 0;
    if (size <= 0) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    const exponent = Math.min(Math.floor(Math.log(size) / Math.log(1024)), units.length - 1);
    const amount = size / Math.pow(1024, exponent);
    return `${amount.toLocaleString(undefined, { maximumFractionDigits: exponent === 0 ? 0 : 1 })} ${units[exponent]}`;
  }

  function parseDate(value: string | null | undefined) {
    if (!value) return null;
    const normalized = value.includes('T') ? value : `${value.replace(' ', 'T')}Z`;
    const date = new Date(normalized);
    return Number.isNaN(date.getTime()) ? null : date;
  }

  function formatDate(value: string | null | undefined) {
    const date = parseDate(value);
    if (!date) return 'None';
    return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
  }

  function formatDateRange(start: string | null | undefined, end: string | null | undefined) {
    if (!start && !end) return 'No dates';
    if (start && end) return `${formatDate(start)} - ${formatDate(end)}`;
    return formatDate(start ?? end);
  }

  function formatScore(value: number | null | undefined) {
    if (value === null || value === undefined) return 'n/a';
    return value.toLocaleString(undefined, { maximumFractionDigits: 1 });
  }

  function percent(value: number, total: number) {
    if (!total) return '0%';
    return `${Math.round((value / total) * 100)}%`;
  }

  function openImage(image: ImageSummary) {
    selectedImageId.set(image.id);
  }

  function openCollection(id: number) {
    activeCollectionId.set(id);
    viewMode.set('collection-detail');
  }

  function openFavorites() {
    viewMode.set('favorites');
  }

  function openCollections() {
    activeCollectionId.set(null);
    viewMode.set('collections');
  }

  function displayTag(name: string) {
    return name.replace(/_/g, ' ');
  }

  function artistLabel(follow: ArtistFollowInfo) {
    return follow.display_name || displayTag(follow.tag_name);
  }

  function isLocalPost(post: TagWikiExample): post is TagWikiExample & { file_id: number; local_post_id: number } {
    return post.file_id !== null && post.local_post_id !== null;
  }

  function artistProfilePost(follow: ArtistFollowInfo) {
    return follow.profile_post && isLocalPost(follow.profile_post) ? follow.profile_post : null;
  }

  function missingFollowPosts(follow: ArtistFollowInfo) {
    return follow.posts.filter(post => !isLocalPost(post));
  }

  function setArtistBusy(tagName: string, busy: boolean) {
    const next = new Set(artistFollowBusyTags);
    if (busy) next.add(tagName);
    else next.delete(tagName);
    artistFollowBusyTags = next;
  }

  function replaceArtistFollow(follow: ArtistFollowInfo) {
    artistFollows = artistFollows.map(item => item.tag_name === follow.tag_name ? follow : item);
  }

  function openArtistTag(follow: ArtistFollowInfo) {
    focusedArtistTagName = null;
    browseTagSelection.set({
      name: follow.tag_name,
      category: follow.tag_category || 'artist',
      count: follow.local_count,
      source: 'danbooru',
    });
    viewMode.set('tags');
  }

  function openArtistFocus(follow: ArtistFollowInfo) {
    focusedArtistTagName = follow.tag_name;
  }

  function updateArtistRailControls() {
    if (!artistRailElement || artistListExpanded) {
      artistRailCanScrollLeft = false;
      artistRailCanScrollRight = false;
      return;
    }
    const edgeAllowance = 4;
    artistRailCanScrollLeft = artistRailElement.scrollLeft > edgeAllowance;
    artistRailCanScrollRight = artistRailElement.scrollLeft + artistRailElement.clientWidth < artistRailElement.scrollWidth - edgeAllowance;
  }

  function scrollArtistRail(direction: -1 | 1) {
    if (!artistRailElement) return;
    artistRailElement.scrollBy({
      left: direction * Math.max(320, artistRailElement.clientWidth * 0.82),
      behavior: 'smooth',
    });
    window.setTimeout(updateArtistRailControls, 350);
  }

  async function toggleArtistListExpanded() {
    artistListExpanded = !artistListExpanded;
    await tick();
    if (!artistListExpanded && artistRailElement) {
      artistRailElement.scrollLeft = 0;
    }
    window.requestAnimationFrame(updateArtistRailControls);
  }

  async function refreshAllArtistProfileMedia() {
    if (artistProfileBulkBusy) return;
    artistProfileBulkBusy = true;
    artistProfileBulkStatus = '';
    try {
      const result = await api.refreshFollowedArtistProfileAssets();
      artistProfileBulkStatus = result.saved_count > 0
        ? `Archived ${result.saved_count.toLocaleString()} new profile image${result.saved_count === 1 ? '' : 's'} from ${result.checked_artists.toLocaleString()} artists.`
        : `No profile image changes across ${result.checked_artists.toLocaleString()} artists.`;
      if (result.errors.length > 0) {
        artistProfileBulkStatus += ` ${result.errors.length.toLocaleString()} source${result.errors.length === 1 ? '' : 's'} could not be checked.`;
      }
    } catch (e) {
      console.error('Failed to refresh followed artist profile media:', e);
      artistProfileBulkStatus = 'Artist profile media refresh failed.';
    } finally {
      artistProfileBulkBusy = false;
    }
  }

  function closeArtistFocus() {
    focusedArtistTagName = null;
  }

  function openFocusedArtistTag() {
    if (focusedArtist) openArtistTag(focusedArtist);
  }

  function checkFocusedArtist() {
    if (focusedArtist) checkArtist(focusedArtist);
  }

  function markFocusedArtistSeen() {
    if (focusedArtist) markArtistSeen(focusedArtist);
  }

  function unfollowFocusedArtist() {
    if (focusedArtist) unfollowArtist(focusedArtist);
  }

  async function checkArtist(follow: ArtistFollowInfo) {
    if (artistFollowBusyTags.has(follow.tag_name)) return;
    setArtistBusy(follow.tag_name, true);
    try {
      const result = await api.checkArtistFollow(follow.tag_name);
      replaceArtistFollow(result.follow);
    } catch (e) {
      console.error('Failed to check artist follow:', e);
      error = `Could not check ${artistLabel(follow)}`;
    } finally {
      setArtistBusy(follow.tag_name, false);
    }
  }

  async function markArtistSeen(follow: ArtistFollowInfo) {
    if (artistFollowBusyTags.has(follow.tag_name)) return;
    setArtistBusy(follow.tag_name, true);
    try {
      replaceArtistFollow(await api.markArtistFollowSeen(follow.tag_name));
    } catch (e) {
      console.error('Failed to mark artist follow seen:', e);
      error = `Could not mark ${artistLabel(follow)} seen`;
    } finally {
      setArtistBusy(follow.tag_name, false);
    }
  }

  async function unfollowArtist(follow: ArtistFollowInfo) {
    if (artistFollowBusyTags.has(follow.tag_name)) return;
    setArtistBusy(follow.tag_name, true);
    try {
      await api.unfollowArtist(follow.tag_name);
      artistFollows = artistFollows.filter(item => item.tag_name !== follow.tag_name);
      await tick();
      window.requestAnimationFrame(updateArtistRailControls);
      if (stats) {
        stats = {
          ...stats,
          total_followed_artists: Math.max(0, stats.total_followed_artists - 1),
        };
      }
      notifyArtistFollowRefresh();
    } catch (e) {
      console.error('Failed to unfollow artist:', e);
      error = `Could not unfollow ${artistLabel(follow)}`;
    } finally {
      setArtistBusy(follow.tag_name, false);
    }
  }
</script>

<svelte:window on:resize={updateArtistRailControls} />

{#snippet artistProfileTile(follow: ArtistFollowInfo, expanded: boolean)}
  {@const profilePost = artistProfilePost(follow)}
  <button
    type="button"
    class="group relative aspect-[4/3] overflow-hidden rounded-lg border border-[#252532] bg-[#0d0d13] text-left shadow-lg shadow-black/25 transition-colors hover:border-cyan-500/50 {expanded ? 'w-full' : 'w-[clamp(12rem,18vw,14rem)] shrink-0'}"
    on:click={() => openArtistFocus(follow)}
    title="Focus {artistLabel(follow)}"
  >
    {#if profilePost}
      <img
        class="h-full w-full object-cover object-center transition-transform duration-300 group-hover:scale-105"
        src={thumbnailUrl(profilePost.file_id, expanded ? 760 : 640, profilePost.thumbnail_token || undefined)}
        alt={profilePost.filename || artistLabel(follow)}
        loading="lazy"
        decoding="async"
      />
    {:else}
      <span class="flex h-full w-full items-center justify-center bg-[#15151d] text-4xl font-bold text-cyan-200">
        {artistLabel(follow).slice(0, 1).toUpperCase()}
      </span>
    {/if}
    <span class="absolute inset-0 bg-gradient-to-t from-black/90 via-transparent to-transparent"></span>
    <span class="absolute bottom-3 left-3 right-3 line-clamp-2 text-base font-semibold leading-tight text-white drop-shadow">
      {artistLabel(follow)}
    </span>
    <span
      class="absolute left-2 top-2 min-w-7 rounded border border-purple-400/35 bg-purple-500/25 px-2 py-0.5 text-center text-xs font-semibold text-purple-100"
      title={`${follow.local_count.toLocaleString()} local images`}
    >
      {follow.local_count.toLocaleString()}
    </span>
    {#if follow.unseen_count > 0}
      <span
        class="absolute right-2 top-2 min-w-7 rounded border border-cyan-400/40 bg-cyan-500/25 px-2 py-0.5 text-center text-xs font-semibold text-cyan-100"
        title={`${follow.unseen_count.toLocaleString()} new tracked posts`}
      >
        {follow.unseen_count.toLocaleString()}
      </span>
    {/if}
  </button>
{/snippet}

<div class="h-full overflow-y-auto bg-[#09090d] text-gray-200">
  <div class="relative min-h-full">
    <section class="relative h-64 overflow-hidden border-b border-[#252532] bg-[#101018]">
      <img
        src={bannerUrl}
        alt=""
        class="h-full w-full object-cover"
        decoding="async"
      />
      <div class="absolute inset-0 bg-gradient-to-b from-black/5 via-[#09090d]/10 to-[#09090d]"></div>
      <div class="absolute inset-x-0 bottom-0 h-28 bg-gradient-to-t from-[#09090d] to-transparent"></div>

      <div class="absolute bottom-5 left-6 flex items-end gap-4">
        <div class="h-28 w-28 overflow-hidden rounded-xl border-4 border-[#09090d] bg-[#15151f] shadow-2xl shadow-black/60">
          <img
            src={avatarUrl}
            alt=""
            class="h-full w-full object-cover"
            decoding="async"
          />
        </div>
        <div class="mb-2 min-w-0">
          {#if editingProfileName}
            <form class="flex max-w-full items-center gap-2" on:submit|preventDefault={saveProfileName}>
              <input
                bind:this={profileNameInput}
                bind:value={profileNameDraft}
                class="min-w-0 max-w-sm rounded-lg border border-purple-300/50 bg-black/55 px-3 py-1.5 text-2xl font-bold text-white outline-none shadow-lg shadow-black/30 focus:border-purple-200"
                type="text"
                maxlength="40"
                aria-label="Profile name"
                on:keydown={handleProfileNameKeydown}
              />
              <button class="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-green-300/30 bg-green-500/15 text-green-100 transition-colors hover:bg-green-500/25" type="submit" title="Save profile name" aria-label="Save profile name">
                <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" /></svg>
              </button>
              <button class="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-white/15 bg-black/35 text-gray-300 transition-colors hover:bg-white/10 hover:text-white" type="button" on:click={cancelProfileNameEdit} title="Cancel profile name edit" aria-label="Cancel profile name edit">
                <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 6l12 12M18 6L6 18" /></svg>
              </button>
            </form>
          {:else}
            <div class="flex min-w-0 items-center gap-2">
              <div class="truncate text-3xl font-bold text-white drop-shadow">{$profileName}</div>
              <button class="grid h-8 w-8 shrink-0 place-items-center rounded-lg border border-white/15 bg-black/30 text-gray-300 opacity-80 transition-all hover:border-purple-300/40 hover:bg-purple-500/15 hover:text-white hover:opacity-100" type="button" on:click={beginProfileNameEdit} title="Edit profile name" aria-label="Edit profile name">
                <svg class="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" d="M16.862 3.487a2.1 2.1 0 113 2.97L8.28 18.158 4 19.5l1.35-4.24L16.862 3.487zM14.75 5.6l3 2.98" /></svg>
              </button>
            </div>
          {/if}
          <div class="mt-1 flex flex-wrap items-center gap-2 text-sm text-gray-300">
            <span class="rounded border border-white/10 bg-black/35 px-2 py-1">Local library</span>
            <span class="rounded border border-white/10 bg-black/35 px-2 py-1">{stats ? formatNumber(stats.total_images) : '0'} images</span>
          </div>
        </div>
      </div>
    </section>

    <div class="mx-auto grid max-w-[1500px] gap-6 px-6 pb-8 pt-6 lg:grid-cols-[320px_1fr]">
      <aside class="space-y-4">
        <section class="overflow-hidden rounded-lg border border-[#292938] bg-[#111118]">
          <div class="border-b border-[#242433] px-4 py-3">
            <h2 class="text-sm font-semibold uppercase tracking-wide text-gray-300">Library Stats</h2>
          </div>
          <div class="divide-y divide-[#222230]">
            <div class="grid grid-cols-2">
              <div class="border-r border-[#222230] p-4">
                <div class="text-2xl font-bold text-purple-200">{stats ? formatNumber(stats.total_images) : '0'}</div>
                <div class="mt-1 text-xs text-gray-500">Images Downloaded</div>
              </div>
              <div class="p-4">
                <div class="text-2xl font-bold text-cyan-200">{stats ? formatNumber(stats.total_tags) : '0'}</div>
                <div class="mt-1 text-xs text-gray-500">Tags Downloaded</div>
              </div>
            </div>
            <div class="grid grid-cols-2">
              <div class="border-r border-[#222230] p-4">
                <div class="text-2xl font-bold text-pink-200">{stats ? formatNumber(stats.total_favorites) : '0'}</div>
                <div class="mt-1 text-xs text-gray-500">Favorites Added</div>
              </div>
              <div class="p-4">
                <div class="text-2xl font-bold text-emerald-200">{stats ? formatNumber(stats.total_image_views) : '0'}</div>
                <div class="mt-1 text-xs text-gray-500">Total Views</div>
              </div>
            </div>
          </div>
        </section>

        <section class="rounded-lg border border-[#292938] bg-[#111118] p-4">
          <h2 class="text-sm font-semibold uppercase tracking-wide text-gray-300">Activity</h2>
          <div class="mt-3 space-y-3 text-sm">
            <div class="flex items-center justify-between gap-4">
              <span class="text-gray-500">Seen Images</span>
              <span class="font-semibold text-gray-100">{stats ? formatNumber(stats.seen_images) : '0'} <span class="text-gray-600">({seenPercent})</span></span>
            </div>
            <div class="flex items-center justify-between gap-4">
              <span class="text-gray-500">Favorite Rate</span>
              <span class="font-semibold text-gray-100">{favoritePercent}</span>
            </div>
            <div class="flex items-center justify-between gap-4">
              <span class="text-gray-500">Last Seen</span>
              <span class="text-right font-semibold text-gray-100">{stats ? formatDate(stats.last_viewed_at) : 'None'}</span>
            </div>
            <div class="flex items-center justify-between gap-4">
              <span class="text-gray-500">First Seen</span>
              <span class="text-right font-semibold text-gray-100">{stats ? formatDate(stats.first_viewed_at) : 'None'}</span>
            </div>
          </div>
        </section>

        <section class="rounded-lg border border-[#292938] bg-[#111118] p-4">
          <h2 class="text-sm font-semibold uppercase tracking-wide text-gray-300">Library Detail</h2>
          <div class="mt-3 space-y-3 text-sm">
            <div class="flex items-center justify-between gap-4">
              <span class="text-gray-500">Storage</span>
              <span class="font-semibold text-gray-100">{stats ? formatBytes(stats.total_storage_bytes) : '0 B'}</span>
            </div>
            <div class="flex items-center justify-between gap-4">
              <span class="text-gray-500">Folders</span>
              <span class="font-semibold text-gray-100">{stats ? formatNumber(stats.total_folders) : '0'}</span>
            </div>
            <div class="flex items-center justify-between gap-4">
              <span class="text-gray-500">Collections</span>
              <span class="font-semibold text-gray-100">{stats ? formatNumber(stats.total_collections) : '0'}</span>
            </div>
            <div class="flex items-center justify-between gap-4">
              <span class="text-gray-500">Collection Images</span>
              <span class="font-semibold text-gray-100">{collectionItemsLabel}</span>
            </div>
            <div class="flex items-center justify-between gap-4">
              <span class="text-gray-500">Favorite Tags</span>
              <span class="font-semibold text-gray-100">{stats ? formatNumber(stats.total_favorite_tags) : '0'}</span>
            </div>
            <div class="flex items-center justify-between gap-4">
              <span class="text-gray-500">Followed Artists</span>
              <span class="font-semibold text-gray-100">{stats ? formatNumber(stats.total_followed_artists) : '0'}</span>
            </div>
            <div class="flex items-center justify-between gap-4">
              <span class="text-gray-500">User Tags</span>
              <span class="font-semibold text-gray-100">{stats ? formatNumber(stats.total_user_tags) : '0'}</span>
            </div>
          </div>
        </section>

        <section class="rounded-lg border border-[#292938] bg-[#111118] p-4">
          <h2 class="text-sm font-semibold uppercase tracking-wide text-gray-300">Scores And Dates</h2>
          <div class="mt-3 space-y-3 text-sm">
            <div class="flex items-center justify-between gap-4">
              <span class="text-gray-500">Average Score</span>
              <span class="font-semibold text-gray-100">{stats ? formatScore(stats.average_score) : 'n/a'}</span>
            </div>
            <div class="flex items-center justify-between gap-4">
              <span class="text-gray-500">Best Score</span>
              <span class="font-semibold text-gray-100">{stats ? formatScore(stats.best_score) : 'n/a'}</span>
            </div>
            <div>
              <div class="text-gray-500">Downloaded Range</div>
              <div class="mt-1 text-sm font-semibold text-gray-100">
                {stats ? formatDateRange(stats.downloaded_from, stats.downloaded_to) : 'No dates'}
              </div>
            </div>
          </div>
        </section>
      </aside>

      <main class="min-w-0 space-y-7">
        {#if error}
          <div class="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">{error}</div>
        {/if}

        <section>
          <div class="mb-3 flex items-end justify-between gap-4">
            <div>
              <h2 class="text-xl font-semibold text-gray-100">Followed Artists</h2>
              <p class="mt-1 text-sm text-gray-500">{formatNumber(artistFollows.length)} artist watchlist</p>
            </div>
            {#if !loading && artistFollows.length > 0}
              <div class="flex flex-wrap justify-end gap-2">
                <button
                  class="inline-flex items-center gap-2 rounded-lg border border-[#2a2a3a] bg-[#15151f] px-3 py-2 text-sm text-gray-300 transition-colors hover:border-sky-500/40 hover:text-sky-100 disabled:cursor-not-allowed disabled:opacity-50"
                  type="button"
                  disabled={artistProfileBulkBusy}
                  on:click={refreshAllArtistProfileMedia}
                  title="Save changed Twitter/X and Pixiv avatars and banners for all followed artists"
                >
                  <svg class="h-4 w-4 {artistProfileBulkBusy ? 'animate-spin' : ''}" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 7v10a2 2 0 002 2h12a2 2 0 002-2V7M8 3h8l2 4H6l2-4zm4 7v6m-3-3h6" />
                  </svg>
                  {artistProfileBulkBusy ? 'Checking profiles' : 'Archive profile updates'}
                </button>
                {#if showArtistExpand}
                  <button
                    class="inline-flex items-center gap-2 rounded-lg border border-[#2a2a3a] bg-[#15151f] px-3 py-2 text-sm text-gray-300 transition-colors hover:border-cyan-500/40 hover:text-cyan-100"
                    type="button"
                    aria-expanded={artistListExpanded}
                    on:click={toggleArtistListExpanded}
                  >
                    {#if artistListExpanded}
                      <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 3v5H3m13-5v5h5M8 21v-5H3m13 5v-5h5" />
                      </svg>
                      Collapse to row
                    {:else}
                      <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 8V4h4m8 0h4v4M4 16v4h4m8 0h4v-4" />
                      </svg>
                      Expand to see all
                    {/if}
                  </button>
                {/if}
              </div>
            {/if}
          </div>

          {#if artistProfileBulkStatus}
            <div class="mb-3 text-xs text-sky-200/80">{artistProfileBulkStatus}</div>
          {/if}

          {#if loading}
            <div class="flex justify-center rounded-lg border border-[#242433] bg-[#101018] py-12">
              <div class="h-8 w-8 rounded-full border-2 border-cyan-500 border-t-transparent animate-spin"></div>
            </div>
          {:else if artistFollows.length === 0}
            <div class="rounded-lg border border-[#242433] bg-[#101018] px-6 py-12 text-center text-gray-500">
              <div class="text-lg text-gray-400">No followed artists yet</div>
              <div class="mt-1 text-sm">Follow an artist from an artist tag page.</div>
            </div>
          {:else}
            {#if artistListExpanded}
              <div class="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5">
                {#each artistFollows as follow (follow.tag_name)}
                  {@render artistProfileTile(follow, true)}
                {/each}
              </div>
            {:else}
              <div class="relative">
                <div
                  bind:this={artistRailElement}
                  class="artist-profile-rail flex gap-3 overflow-x-auto scroll-smooth pb-3"
                  on:scroll={updateArtistRailControls}
                >
                  {#each artistFollows as follow (follow.tag_name)}
                    {@render artistProfileTile(follow, false)}
                  {/each}
                </div>
                {#if artistRailCanScrollLeft}
                  <button
                    class="absolute left-2 top-1/2 z-10 grid h-10 w-10 -translate-y-1/2 place-items-center rounded-full border border-white/15 bg-[#0c0c13]/90 text-gray-200 shadow-xl transition-colors hover:border-cyan-400/50 hover:text-cyan-100"
                    type="button"
                    aria-label="Scroll followed artists left"
                    title="Previous artists"
                    on:click={() => scrollArtistRail(-1)}
                  >
                    <svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7" />
                    </svg>
                  </button>
                {/if}
                {#if artistRailCanScrollRight}
                  <button
                    class="absolute right-2 top-1/2 z-10 grid h-10 w-10 -translate-y-1/2 place-items-center rounded-full border border-white/15 bg-[#0c0c13]/90 text-gray-200 shadow-xl transition-colors hover:border-cyan-400/50 hover:text-cyan-100"
                    type="button"
                    aria-label="Scroll followed artists right"
                    title="More artists"
                    on:click={() => scrollArtistRail(1)}
                  >
                    <svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
                    </svg>
                  </button>
                {/if}
              </div>
            {/if}
          {/if}
        </section>

        <section>
          <div class="mb-3 flex items-end justify-between gap-4">
            <div>
              <h2 class="text-xl font-semibold text-gray-100">Favorites</h2>
              <p class="mt-1 text-sm text-gray-500">{formatNumber(favoriteTotal)} saved images</p>
            </div>
            <button
              class="rounded-lg border border-[#2a2a3a] bg-[#15151f] px-3 py-2 text-sm text-gray-300 transition-colors hover:border-pink-500/40 hover:text-pink-200"
              type="button"
              on:click={openFavorites}
            >
              View All
            </button>
          </div>

          {#if loading}
            <div class="flex justify-center rounded-lg border border-[#242433] bg-[#101018] py-16">
              <div class="h-8 w-8 rounded-full border-2 border-purple-500 border-t-transparent animate-spin"></div>
            </div>
          {:else if favorites.length === 0}
            <div class="rounded-lg border border-[#242433] bg-[#101018] px-6 py-14 text-center text-gray-500">
              <div class="text-lg text-gray-400">No favorites yet</div>
            </div>
          {:else}
            <div class="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
              {#each favorites as image}
                <button
                  class="group overflow-hidden rounded-lg border border-[#252532] bg-[#111118] text-left transition-colors hover:border-pink-500/40"
                  type="button"
                  on:click={() => openImage(image)}
                  title={image.filename}
                >
                  <div class="aspect-[4/3] overflow-hidden bg-[#171723]">
                    <img
                      src={thumbnailUrl(image.file_id, 520, image.thumbnail_token)}
                      alt={image.filename}
                      class="h-full w-full object-cover transition-transform duration-300 group-hover:scale-105"
                      loading="lazy"
                      decoding="async"
                    />
                  </div>
                  <div class="space-y-2 p-3">
                    <div class="line-clamp-2 text-sm font-semibold text-gray-100">{image.filename}</div>
                    <div class="flex items-center justify-between gap-2 text-xs text-gray-500">
                      <span class="min-w-0 truncate">{image.folder ?? 'root'}</span>
                      <span class="shrink-0 text-yellow-300">{image.score !== null ? `Score ${image.score}` : 'No score'}</span>
                    </div>
                    <div class="flex items-center justify-between text-xs text-gray-600">
                      <span>{image.width && image.height ? `${image.width}x${image.height}` : image.ext?.toUpperCase() ?? 'File'}</span>
                      <span>{formatDate(image.favorite_added_at)}</span>
                    </div>
                  </div>
                </button>
              {/each}
            </div>
          {/if}
        </section>

        <section>
          <div class="mb-3 flex items-end justify-between gap-4">
            <div>
              <h2 class="text-xl font-semibold text-gray-100">Collections</h2>
              <p class="mt-1 text-sm text-gray-500">{stats ? formatNumber(stats.total_collections) : '0'} collections</p>
            </div>
            <button
              class="rounded-lg border border-[#2a2a3a] bg-[#15151f] px-3 py-2 text-sm text-gray-300 transition-colors hover:border-purple-500/40 hover:text-purple-200"
              type="button"
              on:click={openCollections}
            >
              Manage
            </button>
          </div>

          {#if !loading && topCollections.length === 0}
            <div class="rounded-lg border border-[#242433] bg-[#101018] px-6 py-12 text-center text-gray-500">
              <div class="text-lg text-gray-400">No collections yet</div>
            </div>
          {:else}
            <div class="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
              {#each topCollections as col}
                <button
                  class="group overflow-hidden rounded-lg border border-[#252532] bg-[#111118] text-left transition-colors hover:border-purple-500/40"
                  type="button"
                  on:click={() => openCollection(col.id)}
                  title={col.name}
                >
                  <div class="aspect-video bg-[#171723]">
                    <CollectionPreviewGrid
                      items={col.preview_items ?? []}
                      previewIds={col.preview_ids}
                      size={320}
                    />
                  </div>
                  <div class="p-3">
                    <div class="flex items-center justify-between gap-2">
                      <div class="min-w-0 truncate text-sm font-semibold text-gray-100">{col.name}</div>
                      {#if col.pinned_at}
                        <span class="shrink-0 rounded bg-amber-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-amber-200">Pinned</span>
                      {/if}
                    </div>
                    <div class="mt-1 line-clamp-2 min-h-8 text-xs leading-snug text-gray-500">{col.description || 'No description'}</div>
                    <div class="mt-3 flex items-center justify-between text-xs text-gray-600">
                      <span>{formatNumber(col.image_count)} images</span>
                      <span>{formatDate(col.created_at)}</span>
                    </div>
                  </div>
                </button>
              {/each}
            </div>
          {/if}
        </section>
      </main>
    </div>
  </div>

  {#if focusedArtist}
    {@const focusProfilePost = artistProfilePost(focusedArtist)}
    {@const focusMissingPosts = missingFollowPosts(focusedArtist)}
    {@const focusBusy = artistFollowBusyTags.has(focusedArtist.tag_name)}
    <div
      class="artist-focus-backdrop fixed inset-0 z-[90] flex items-center justify-center bg-black/80 px-5 py-6 backdrop-blur-sm"
      on:click|self={closeArtistFocus}
      role="presentation"
    >
      <div
        class="artist-focus-stage grid max-h-[86vh] w-full max-w-6xl grid-cols-[minmax(220px,330px)_minmax(0,1fr)] overflow-hidden rounded-lg border border-[#303044] bg-[#101018] shadow-2xl shadow-black/70"
        role="dialog"
        aria-modal="true"
        aria-label="{artistLabel(focusedArtist)} artist profile"
      >
        <div class="artist-focus-profile relative min-h-[430px] overflow-hidden bg-[#15151f]">
          {#if focusProfilePost}
            <img
              class="h-full w-full object-cover"
              src={thumbnailUrl(focusProfilePost.file_id, 760, focusProfilePost.thumbnail_token || undefined)}
              alt={focusProfilePost.filename || artistLabel(focusedArtist)}
              decoding="async"
            />
          {:else}
            <div class="flex h-full min-h-[430px] w-full items-center justify-center bg-[#15151f] text-7xl font-bold text-cyan-200">
              {artistLabel(focusedArtist).slice(0, 1).toUpperCase()}
            </div>
          {/if}
          <div class="absolute inset-0 bg-gradient-to-t from-black via-black/25 to-black/10"></div>
          <button
            type="button"
            class="absolute right-3 top-3 flex h-8 w-8 items-center justify-center rounded border border-white/10 bg-black/50 text-gray-300 transition-colors hover:bg-black/75 hover:text-white"
            on:click={closeArtistFocus}
            title="Close"
            aria-label="Close artist profile"
          >
            <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
            </svg>
          </button>
          <div class="absolute inset-x-0 bottom-0 p-5">
            <div class="text-2xl font-bold leading-tight text-white drop-shadow">{artistLabel(focusedArtist)}</div>
            <div class="mt-2 flex flex-wrap items-center gap-2 text-xs text-gray-200">
              <span class="rounded border border-red-500/30 bg-red-500/20 px-2 py-0.5 text-red-100">artist</span>
              <span class="rounded border border-white/10 bg-black/35 px-2 py-0.5">{focusedArtist.local_count.toLocaleString()} local images</span>
              {#if focusedArtist.unseen_count > 0}
                <span class="rounded border border-cyan-500/30 bg-cyan-500/20 px-2 py-0.5 text-cyan-100">{focusedArtist.unseen_count.toLocaleString()} new</span>
              {/if}
              {#if focusProfilePost}
                <span class="rounded border border-white/10 bg-black/35 px-2 py-0.5">#{focusProfilePost.danbooru_post_id}</span>
              {/if}
            </div>
          </div>
        </div>

        <div class="artist-focus-menu min-h-0 overflow-y-auto p-5">
          <div class="flex flex-wrap items-start justify-between gap-4 border-b border-[#252532] pb-4">
            <div>
              <div class="text-xs uppercase text-gray-600">Followed Artist</div>
              <h3 class="mt-1 text-xl font-semibold text-cyan-100">{artistLabel(focusedArtist)}</h3>
              <div class="mt-2 text-xs text-gray-500">
                {#if focusedArtist.last_checked_at}
                  Checked {formatDate(focusedArtist.last_checked_at)}
                {:else}
                  Not checked yet
                {/if}
              </div>
            </div>
            <div class="flex flex-wrap items-center gap-2">
              <button
                type="button"
                class="rounded border border-[#2a2a3a] px-2.5 py-1 text-xs text-gray-400 transition-colors hover:bg-[#1e1e2e] hover:text-gray-200"
                on:click={openFocusedArtistTag}
              >Artist Info</button>
              <button
                type="button"
                class="rounded border border-cyan-500/30 px-2.5 py-1 text-xs text-cyan-200 transition-colors hover:bg-cyan-500/10 disabled:cursor-not-allowed disabled:opacity-50"
                disabled={focusBusy}
                on:click={checkFocusedArtist}
                title="Check Danbooru for recent post IDs without downloading images"
              >Check</button>
              <button
                type="button"
                class="rounded border border-[#2a2a3a] px-2.5 py-1 text-xs text-gray-400 transition-colors hover:bg-[#1e1e2e] hover:text-gray-200 disabled:cursor-not-allowed disabled:opacity-50"
                disabled={focusBusy || focusedArtist.unseen_count === 0}
                on:click={markFocusedArtistSeen}
              >Mark Seen</button>
              <button
                type="button"
                class="rounded border border-red-500/30 px-2.5 py-1 text-xs text-red-200 transition-colors hover:bg-red-500/10 disabled:cursor-not-allowed disabled:opacity-50"
                disabled={focusBusy}
                on:click={unfollowFocusedArtist}
              >Unfollow</button>
            </div>
          </div>

          <div class="mt-5">
            <div class="mb-3 flex items-center justify-between gap-3">
              <h4 class="text-sm font-semibold uppercase text-gray-300">Undownloaded Posts</h4>
              <span class="rounded border border-[#2a2a3a] bg-[#15151d] px-2 py-0.5 text-xs text-gray-400">{focusMissingPosts.length.toLocaleString()}</span>
            </div>

            {#if focusMissingPosts.length > 0}
              <div class="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-4">
                {#each focusMissingPosts as post}
                  <a
                    class="group flex aspect-[3/4] flex-col items-center justify-center rounded border border-dashed border-[#3a3a50] bg-[#15151d]/85 px-2 text-center text-xs text-gray-500 transition-colors hover:border-sky-500/40 hover:text-sky-300"
                    href={post.post_url || `https://danbooru.donmai.us/posts/${post.danbooru_post_id}`}
                    target="_blank"
                    rel="noreferrer"
                    title="Open Danbooru post #{post.danbooru_post_id}"
                  >
                    <span class="font-semibold text-sky-400/85 group-hover:text-sky-300">#{post.danbooru_post_id}</span>
                    <span class="mt-2">Not in library</span>
                  </a>
                {/each}
              </div>
            {:else}
              <div class="rounded-lg border border-[#242433] bg-[#111118] px-4 py-10 text-center text-sm text-gray-500">
                No undownloaded tracked posts.
              </div>
            {/if}
          </div>
        </div>
      </div>
    </div>
  {/if}
</div>

<style>
  .artist-profile-rail {
    scrollbar-color: #38384a #111118;
    scrollbar-width: thin;
    scroll-snap-type: x proximity;
  }

  .artist-profile-rail > :global(button) {
    scroll-snap-align: start;
  }

  .artist-profile-rail::-webkit-scrollbar {
    height: 8px;
  }

  .artist-profile-rail::-webkit-scrollbar-track {
    background: #111118;
    border-radius: 4px;
  }

  .artist-profile-rail::-webkit-scrollbar-thumb {
    background: #38384a;
    border-radius: 4px;
  }

  .artist-profile-rail::-webkit-scrollbar-thumb:hover {
    background: #4b4b62;
  }

  .artist-focus-backdrop {
    animation: artistFocusFade 150ms ease-out both;
  }

  .artist-focus-stage {
    animation: artistFocusStage 260ms cubic-bezier(.2, .8, .2, 1) both;
  }

  .artist-focus-profile {
    animation: artistFocusProfile 300ms cubic-bezier(.2, .8, .2, 1) both;
  }

  .artist-focus-menu {
    animation: artistFocusMenu 320ms cubic-bezier(.2, .8, .2, 1) both;
    transform-origin: left center;
  }

  @keyframes artistFocusFade {
    from { opacity: 0; }
    to { opacity: 1; }
  }

  @keyframes artistFocusStage {
    from { opacity: 0; transform: translateY(18px) scale(.98); }
    to { opacity: 1; transform: translateY(0) scale(1); }
  }

  @keyframes artistFocusProfile {
    from { transform: translateX(140px) scale(.96); }
    to { transform: translateX(0) scale(1); }
  }

  @keyframes artistFocusMenu {
    from { opacity: 0; transform: translateX(-28px) scaleX(.94); }
    to { opacity: 1; transform: translateX(0) scaleX(1); }
  }

  @media (max-width: 760px) {
    .artist-focus-stage {
      grid-template-columns: 1fr;
    }

    .artist-focus-profile {
      min-height: 280px;
    }
  }
</style>
