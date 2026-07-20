<script lang="ts">
  import { onMount } from 'svelte';
  import { api, thumbnailUrl, type ArtistFollowInfo } from '../lib/api';
  import {
    activeCollectionId,
    artistFocusRequest,
    artistFollowRefreshToken,
    artistNotificationIntervalMinutes,
    selectedImageId,
    viewMode,
  } from '../lib/stores';

  const notificationPostLimit = 12;

  let showMenu = false;
  let artistFollows: ArtistFollowInfo[] = [];
  let loading = true;
  let checking = false;
  let error = '';
  let observedArtistFollowRefreshToken = 0;
  let markSeenBusyTags = new Set<string>();
  let mounted = false;
  let pollTimer: number | null = null;
  let scheduledIntervalMinutes = 0;
  let lastCheckStatus = '';
  let checkIntervalMs = 15 * 60 * 1000;

  $: checkIntervalMs = $artistNotificationIntervalMinutes * 60 * 1000;

  $: unseenFollows = artistFollows.filter(follow => follow.notification_initialized_at && follow.unseen_count > 0);
  $: unseenTotal = unseenFollows.reduce((total, follow) => total + follow.unseen_count, 0);
  $: notificationBadge = unseenTotal > 99 ? '99+' : unseenTotal.toLocaleString();

  onMount(() => {
    mounted = true;
    loadNotifications().then(() => checkForNewPosts()).catch(console.error);
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        checkForNewPosts().catch(console.error);
      }
    };
    document.addEventListener('visibilitychange', handleVisibilityChange);

    return () => {
      mounted = false;
      if (pollTimer !== null) window.clearInterval(pollTimer);
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  });

  $: if (mounted && scheduledIntervalMinutes !== $artistNotificationIntervalMinutes) {
    scheduledIntervalMinutes = $artistNotificationIntervalMinutes;
    schedulePolling();
  }

  $: if ($artistFollowRefreshToken !== observedArtistFollowRefreshToken) {
    observedArtistFollowRefreshToken = $artistFollowRefreshToken;
    if (!loading && !checking) {
      loadNotifications().catch(console.error);
    }
  }

  function displayTag(name: string) {
    return name.replace(/_/g, ' ');
  }

  function artistLabel(follow: ArtistFollowInfo) {
    return follow.display_name || displayTag(follow.tag_name);
  }

  function parseTimestamp(value: string | null) {
    if (!value) return null;
    const normalized = value.includes('T') ? value : `${value.replace(' ', 'T')}Z`;
    const date = new Date(normalized);
    return Number.isNaN(date.getTime()) ? null : date;
  }

  function needsCheck(follow: ArtistFollowInfo) {
    if (!follow.notification_initialized_at) return true;
    const lastChecked = parseTimestamp(follow.last_checked_at);
    return !lastChecked || Date.now() - lastChecked.getTime() >= checkIntervalMs;
  }

  function schedulePolling() {
    if (pollTimer !== null) window.clearInterval(pollTimer);
    pollTimer = window.setInterval(() => {
      if (document.visibilityState === 'visible') {
        checkForNewPosts().catch(console.error);
      }
    }, $artistNotificationIntervalMinutes * 60 * 1000);
  }

  function replaceArtistFollow(follow: ArtistFollowInfo) {
    artistFollows = artistFollows.map(item => item.tag_name === follow.tag_name ? follow : item);
  }

  function notifyArtistFollowRefresh() {
    artistFollowRefreshToken.update(value => {
      observedArtistFollowRefreshToken = value + 1;
      return value + 1;
    });
  }

  async function loadNotifications() {
    try {
      artistFollows = await api.getArtistFollows();
      error = '';
    } catch (e) {
      console.error('Failed to load artist notifications:', e);
      error = 'Notifications could not load';
    } finally {
      loading = false;
    }
  }

  async function checkForNewPosts(force = false) {
    if (checking) return;
    checking = true;
    error = '';
    try {
      if (loading) await loadNotifications();
      const candidates = artistFollows.filter(follow => force || needsCheck(follow));
      let failedChecks = 0;
      let discoveredPosts = 0;

      for (const follow of candidates) {
        try {
          const result = await api.checkArtistFollow(follow.tag_name, notificationPostLimit, true);
          replaceArtistFollow(result.follow);
          discoveredPosts += result.discovered_count;
        } catch (e) {
          failedChecks += 1;
          console.error(`Failed to check ${follow.tag_name} for new Danbooru posts:`, e);
        }
      }

      if (candidates.length > 0) notifyArtistFollowRefresh();
      if (force || candidates.length > 0) {
        const checkedCount = candidates.length - failedChecks;
        lastCheckStatus = candidates.length === 0
          ? 'No followed artists to check.'
          : `Checked ${checkedCount.toLocaleString()} artist${checkedCount === 1 ? '' : 's'}${discoveredPosts > 0 ? ` · ${discoveredPosts.toLocaleString()} new post${discoveredPosts === 1 ? '' : 's'}` : ' · no new posts'}.`;
      }
      if (failedChecks > 0) {
        error = failedChecks === candidates.length
          ? 'Danbooru checks failed'
          : `${failedChecks} artist check${failedChecks === 1 ? '' : 's'} failed`;
      }
    } finally {
      checking = false;
    }
  }

  function toggleMenu() {
    showMenu = !showMenu;
  }

  function closeMenu() {
    showMenu = false;
  }

  function openArtist(follow: ArtistFollowInfo) {
    activeCollectionId.set(null);
    selectedImageId.set(null);
    artistFocusRequest.set(follow.tag_name);
    viewMode.set('profile');
    showMenu = false;
  }

  function setMarkSeenBusy(tagName: string, busy: boolean) {
    const next = new Set(markSeenBusyTags);
    if (busy) next.add(tagName);
    else next.delete(tagName);
    markSeenBusyTags = next;
  }

  async function markArtistSeen(follow: ArtistFollowInfo) {
    if (markSeenBusyTags.has(follow.tag_name)) return;
    const previous = follow;
    replaceArtistFollow({ ...follow, unseen_count: 0 });
    setMarkSeenBusy(follow.tag_name, true);
    try {
      replaceArtistFollow(await api.markArtistFollowSeen(follow.tag_name));
      notifyArtistFollowRefresh();
    } catch (e) {
      replaceArtistFollow(previous);
      console.error('Failed to mark artist notification seen:', e);
      error = `Could not mark ${artistLabel(follow)} seen`;
    } finally {
      setMarkSeenBusy(follow.tag_name, false);
    }
  }

  async function markAllSeen() {
    if (unseenFollows.length === 0) return;
    const previous = artistFollows;
    const targets = [...unseenFollows];
    artistFollows = artistFollows.map(follow => follow.unseen_count > 0 ? { ...follow, unseen_count: 0 } : follow);
    try {
      const updated = await Promise.all(targets.map(follow => api.markArtistFollowSeen(follow.tag_name)));
      for (const follow of updated) replaceArtistFollow(follow);
      notifyArtistFollowRefresh();
    } catch (e) {
      artistFollows = previous;
      console.error('Failed to mark all artist notifications seen:', e);
      error = 'Could not mark all notifications seen';
      await loadNotifications();
    }
  }

  function handleKeydown(event: KeyboardEvent) {
    if (event.key === 'Escape') closeMenu();
  }
</script>

<svelte:window on:click={closeMenu} on:keydown={handleKeydown} />

<div class="relative">
  <button
    class="relative grid h-9 w-9 place-items-center rounded-lg border border-[#2a2a3a] bg-[#1e1e2e] text-gray-300 transition-colors hover:border-cyan-400/50 hover:text-white"
    type="button"
    title={unseenTotal > 0 ? `${unseenTotal.toLocaleString()} new Danbooru post${unseenTotal === 1 ? '' : 's'}` : 'Artist notifications'}
    aria-label="Artist notifications"
    aria-haspopup="menu"
    aria-expanded={showMenu}
    on:click|stopPropagation={toggleMenu}
  >
    <svg class="h-[18px] w-[18px]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M18 8a6 6 0 00-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4" />
    </svg>
    {#if unseenTotal > 0}
      <span class="absolute -right-1.5 -top-1.5 grid min-h-5 min-w-5 place-items-center rounded-full border-2 border-[#16161e] bg-cyan-500 px-1 text-[10px] font-bold leading-none text-[#071116]">
        {notificationBadge}
      </span>
    {/if}
  </button>

  {#if showMenu}
    <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
    <div
      class="absolute right-0 top-full z-[90] mt-2 w-[min(24rem,calc(100vw-1rem))] overflow-hidden rounded-lg border border-[#2d2d3c] bg-[#111118] shadow-2xl shadow-black/60"
      role="menu"
      tabindex="-1"
      on:click|stopPropagation
    >
      <div class="flex items-center justify-between border-b border-[#282838] px-3.5 py-3">
        <div>
          <div class="text-sm font-semibold text-gray-100">Artist notifications</div>
          <div class="mt-0.5 text-[11px] text-gray-500">New posts found on Danbooru</div>
        </div>
        <button
          class="inline-flex h-8 items-center gap-1.5 rounded-md border border-cyan-500/20 bg-cyan-500/10 px-2.5 text-xs text-cyan-200 transition-colors hover:border-cyan-400/40 hover:bg-cyan-500/15 disabled:cursor-not-allowed disabled:opacity-50"
          type="button"
          title="Check followed artists now"
          aria-label="Check followed artists now"
          disabled={checking}
          on:click={() => checkForNewPosts(true)}
        >
          <svg class="h-4 w-4 {checking ? 'animate-spin' : ''}" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20 11a8.1 8.1 0 00-15.5-2M4 4v5h5m-5 4a8.1 8.1 0 0015.5 2M20 20v-5h-5" />
          </svg>
          Check now
        </button>
      </div>

      {#if error}
        <div class="border-b border-red-500/20 bg-red-500/10 px-3.5 py-2 text-xs text-red-200">{error}</div>
      {/if}
      {#if lastCheckStatus}
        <div class="border-b border-cyan-500/10 bg-cyan-500/[0.04] px-3.5 py-2 text-xs text-cyan-100/75">{lastCheckStatus}</div>
      {/if}

      <div class="max-h-[28rem] overflow-y-auto p-1.5">
        {#if loading}
          <div class="px-3 py-8 text-center text-sm text-gray-500">Loading notifications...</div>
        {:else if artistFollows.length === 0}
          <div class="px-4 py-8 text-center">
            <div class="text-sm text-gray-300">No followed artists</div>
            <div class="mt-1 text-xs text-gray-500">Follow an artist from their tag page.</div>
          </div>
        {:else if unseenFollows.length === 0}
          <div class="px-4 py-8 text-center">
            <div class="text-sm text-gray-300">No new Danbooru posts</div>
            <div class="mt-1 text-xs text-gray-500">Checks run every {$artistNotificationIntervalMinutes} minutes while the app is open.</div>
          </div>
        {:else}
          {#each unseenFollows as follow (follow.tag_name)}
            <div class="flex items-center gap-2 rounded-md p-1.5 transition-colors hover:bg-[#1b1b26]">
              <button
                class="flex min-w-0 flex-1 items-center gap-3 rounded text-left"
                type="button"
                role="menuitem"
                on:click={() => openArtist(follow)}
                title="Open {artistLabel(follow)}"
              >
                <div class="h-12 w-12 shrink-0 overflow-hidden rounded-md border border-[#343449] bg-[#191923]">
                  {#if follow.profile_post?.file_id}
                    <img
                      src={thumbnailUrl(follow.profile_post.file_id, 180, follow.profile_post.thumbnail_token || undefined)}
                      alt=""
                      class="h-full w-full object-cover"
                      decoding="async"
                    />
                  {:else}
                    <div class="grid h-full w-full place-items-center text-sm font-semibold text-gray-500">
                      {artistLabel(follow).slice(0, 1).toUpperCase()}
                    </div>
                  {/if}
                </div>
                <div class="min-w-0 flex-1">
                  <div class="truncate text-sm font-medium text-cyan-100">{artistLabel(follow)}</div>
                  <div class="mt-0.5 text-xs text-gray-400">{follow.unseen_count.toLocaleString()} new post{follow.unseen_count === 1 ? '' : 's'}</div>
                  <div class="mt-1 flex min-w-0 gap-1 overflow-hidden">
                    {#each follow.posts.slice(0, 3) as post (post.danbooru_post_id)}
                      <span class="rounded border border-cyan-500/20 bg-cyan-500/10 px-1.5 py-0.5 text-[10px] text-cyan-300">#{post.danbooru_post_id}</span>
                    {/each}
                  </div>
                </div>
              </button>
              <button
                class="grid h-8 w-8 shrink-0 place-items-center rounded-md text-gray-500 transition-colors hover:bg-cyan-500/10 hover:text-cyan-200 disabled:opacity-50"
                type="button"
                title="Mark {artistLabel(follow)} seen"
                aria-label="Mark {artistLabel(follow)} seen"
                disabled={markSeenBusyTags.has(follow.tag_name)}
                on:click={() => markArtistSeen(follow)}
              >
                <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
                </svg>
              </button>
            </div>
          {/each}
        {/if}
      </div>

      {#if unseenFollows.length > 0}
        <div class="border-t border-[#282838] p-1.5">
          <button
            class="w-full rounded-md px-3 py-2 text-center text-xs text-gray-400 transition-colors hover:bg-[#1d1d29] hover:text-cyan-100"
            type="button"
            on:click={markAllSeen}
          >
            Mark all as seen
          </button>
        </div>
      {/if}
    </div>
  {/if}
</div>
