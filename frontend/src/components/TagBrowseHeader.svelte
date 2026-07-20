<script lang="ts">
  import { createEventDispatcher, tick } from 'svelte';
  import {
    api,
    thumbnailUrl,
    type ArtistProfileAsset,
    type ArtistUrl,
    type ImageSummary,
    type TagWikiExample,
    type TagWikiInfo,
    type TagWikiTextLine,
  } from '../lib/api';
  import { persistentStorageKey } from '../lib/product';
  import { activeTags, artistFollowRefreshToken, browseTagSelection, selectedArtistProfileAsset, selectedImageId, tagBannerHeight, tagRefreshToken, viewMode } from '../lib/stores';
  import type { BrowseTagSelection } from '../lib/stores';

  export let tag: BrowseTagSelection;
  export let images: ImageSummary[] = [];
  export let total = 0;
  export let loading = false;
  export let showBackAction = false;

  const dispatch = createEventDispatcher<{ back: void }>();

  type CoverImage = {
    id: number;
    file_id: number;
    thumbnail_token: string;
    filename: string;
    width: number | null;
    height: number | null;
    score: number | null;
  };

  type FavoriteTagMeta = {
    name: string;
    category: string;
    pinned_at?: string | null;
  };

  type ArtistJourneyGroup = {
    key: string;
    label: string;
    images: ImageSummary[];
    rangeLabel: string;
  };

  type LocalTagWikiExample = TagWikiExample & {
    file_id: number;
    local_post_id: number;
  };

  const coverStorageVersion = 'v1';
  const JOURNEY_BATCH_SIZE = 1000;
  const PROFILE_ARCHIVE_EXPAND_THRESHOLD = 8;
  const categoryColors: Record<string, string> = {
    artist: 'border-red-500/30 bg-red-500/20 text-red-200',
    character: 'border-green-500/30 bg-green-500/20 text-green-200',
    copyright: 'border-purple-500/30 bg-purple-500/20 text-purple-200',
    general: 'border-blue-500/30 bg-blue-500/20 text-blue-200',
    meta: 'border-yellow-500/30 bg-yellow-500/20 text-yellow-200',
    unknown: 'border-gray-500/30 bg-gray-500/20 text-gray-300',
  };

  let wikiInfo: TagWikiInfo | null = null;
  let wikiLoading = false;
  let wikiError = '';
  let wikiSerial = 0;
  let loadedTagKey = '';
  let coverOverride: CoverImage | null = null;
  let showCoverChooser = false;
  let bannerCoverCandidates: CoverImage[] = [];
  let fetchedCoverCandidates: CoverImage[] = [];
  let coverSerial = 0;
  let coverLoading = false;
  let favoriteTagMeta = new Map<string, FavoriteTagMeta>();
  let favoriteTagSerial = 0;
  let observedTagRefreshToken = 0;
  let showArtistJourney = false;
  let artistJourneyImages: ImageSummary[] = [];
  let artistJourneyLoadedKey = '';
  let artistJourneyLoading = false;
  let artistJourneyError = '';
  let artistJourneySerial = 0;
  let followedArtistTags = new Set<string>();
  let artistFollowBusy = false;
  let artistFollowSerial = 0;
  let observedArtistFollowRefreshToken = 0;
  let artistProfileAssets: ArtistProfileAsset[] = [];
  let artistProfileArchiveLoading = false;
  let artistProfileArchiveBusy = false;
  let artistProfileArchiveError = '';
  let artistProfileArchiveStatus = '';
  let artistProfileArchiveExpanded = false;
  let artistProfileArchiveSerial = 0;
  let artistProfileArchiveRail: HTMLDivElement | null = null;
  let artistProfileArchiveCanScrollLeft = false;
  let artistProfileArchiveCanScrollRight = false;

  function displayTag(name: string) {
    return name.replace(/_/g, ' ');
  }

  function tagKey(value: BrowseTagSelection) {
    return `${value.source}:${value.category}:${value.name}`;
  }

  function favoriteTagKey(category: string, name: string) {
    return `${category}:${name}`;
  }

  function coverStorageKey(value: BrowseTagSelection) {
    return persistentStorageKey(`tag-cover:${coverStorageVersion}:${tagKey(value)}`);
  }

  function emptyWikiInfo(value: BrowseTagSelection, error: string | null = null): TagWikiInfo {
    return {
      tag_name: value.name,
      title: value.name,
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

  function coverFromImage(image: ImageSummary): CoverImage {
    return {
      id: image.id,
      file_id: image.file_id,
      thumbnail_token: image.thumbnail_token,
      filename: image.filename,
      width: image.width,
      height: image.height,
      score: image.score,
    };
  }

  function loadCoverOverride(value: BrowseTagSelection): CoverImage | null {
    if (typeof localStorage === 'undefined') return null;
    const raw = localStorage.getItem(coverStorageKey(value));
    if (!raw) return null;
    try {
      const parsed = JSON.parse(raw) as Partial<CoverImage>;
      if (
        typeof parsed.id === 'number' &&
        typeof parsed.file_id === 'number' &&
        typeof parsed.thumbnail_token === 'string' &&
        typeof parsed.filename === 'string'
      ) {
        return {
          id: parsed.id,
          file_id: parsed.file_id,
          thumbnail_token: parsed.thumbnail_token,
          filename: parsed.filename,
          width: typeof parsed.width === 'number' ? parsed.width : null,
          height: typeof parsed.height === 'number' ? parsed.height : null,
          score: typeof parsed.score === 'number' ? parsed.score : null,
        };
      }
    } catch {
      localStorage.removeItem(coverStorageKey(value));
    }
    return null;
  }

  function saveCoverOverride(candidate: CoverImage) {
    coverOverride = candidate;
    showCoverChooser = false;
    if (typeof localStorage !== 'undefined') {
      localStorage.setItem(coverStorageKey(tag), JSON.stringify(candidate));
    }
  }

  function clearCoverOverride() {
    coverOverride = null;
    showCoverChooser = false;
    if (typeof localStorage !== 'undefined') {
      localStorage.removeItem(coverStorageKey(tag));
    }
  }

  function coverQuery(value: BrowseTagSelection) {
    return value.source === 'user' ? `user:${value.name}` : value.name;
  }

  function bannerCoverQuery(value: BrowseTagSelection) {
    return `${coverQuery(value)} banner`;
  }

  function mergeCoverCandidates(primary: CoverImage[], secondary: CoverImage[]) {
    const seen = new Set<number>();
    const merged: CoverImage[] = [];
    for (const candidate of [...primary, ...secondary]) {
      if (seen.has(candidate.id)) continue;
      seen.add(candidate.id);
      merged.push(candidate);
    }
    return merged.slice(0, 18);
  }

  function preferredBannerCover(candidates: CoverImage[]) {
    return candidates.find(candidate => {
      if (!candidate.width || !candidate.height) return false;
      return candidate.width / candidate.height >= 1.8;
    }) ?? candidates[0] ?? null;
  }

  async function loadCoverCandidates(value: BrowseTagSelection) {
    const requestId = ++coverSerial;
    coverLoading = true;
    try {
      const [bannerResult, fallbackResult] = await Promise.all([
        api.getImages({
          q: bannerCoverQuery(value),
          sort: 'score',
          order: 'desc',
          limit: 18,
        }).catch(() => null),
        api.getImages({
          q: coverQuery(value),
          sort: 'score',
          order: 'desc',
          limit: 18,
        }),
      ]);
      if (requestId !== coverSerial) return;
      bannerCoverCandidates = bannerResult?.images.map(coverFromImage) ?? [];
      fetchedCoverCandidates = fallbackResult.images.map(coverFromImage);
    } catch (e) {
      if (requestId !== coverSerial) return;
      console.error('Failed to load tag cover candidates:', e);
      bannerCoverCandidates = [];
      try {
        const fallback = await api.getImages({
          q: coverQuery(value),
          sort: 'score',
          order: 'desc',
          limit: 18,
        });
        if (requestId !== coverSerial) return;
        fetchedCoverCandidates = fallback.images.map(coverFromImage);
      } catch (fallbackError) {
        if (requestId !== coverSerial) return;
        console.error('Failed to load fallback tag cover candidates:', fallbackError);
        fetchedCoverCandidates = [];
      }
    } finally {
      if (requestId === coverSerial) coverLoading = false;
    }
  }

  async function loadWiki(value: BrowseTagSelection) {
    const requestId = ++wikiSerial;
    wikiLoading = true;
    wikiError = '';
    wikiInfo = null;

    if (value.source === 'user') {
      wikiInfo = emptyWikiInfo(value, 'User-added tags do not have Danbooru wiki info.');
      wikiLoading = false;
      return;
    }

    try {
      const result = await api.getTagWiki(value.name, { category: value.category });
      if (requestId !== wikiSerial) return;
      wikiInfo = result;
    } catch (e) {
      if (requestId !== wikiSerial) return;
      console.error('Failed to load tag wiki:', e);
      wikiError = 'Could not load tag info';
      wikiInfo = emptyWikiInfo(value, wikiError);
    } finally {
      if (requestId === wikiSerial) wikiLoading = false;
    }
  }

  function selectLinkedTag(tagName: string) {
    browseTagSelection.set({
      name: tagName,
      category: 'unknown',
      count: 0,
      source: 'danbooru',
    });
    viewMode.set('tags');
  }

  function urlHost(value: string) {
    try {
      return new URL(value).hostname.replace(/^www\./, '');
    } catch {
      return value.replace(/^https?:\/\//, '').split('/')[0] || value;
    }
  }

  function artistUrlMarker(url: ArtistUrl) {
    const host = urlHost(url.url);
    return host.slice(0, 1).toUpperCase() || 'U';
  }

  function artistProfileAssetLabel(asset: ArtistProfileAsset) {
    const platform = asset.platform === 'twitter' ? 'X' : 'Pixiv';
    const kind = asset.asset_kind === 'avatar' ? 'Logo' : 'Banner';
    return `${platform} ${kind}`;
  }

  function formatArtistProfileCapture(value: string) {
    const normalized = value.includes('T') ? value : `${value.replace(' ', 'T')}Z`;
    const date = new Date(normalized);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
  }

  function updateArtistProfileArchiveRail() {
    if (!artistProfileArchiveRail || artistProfileArchiveExpanded) {
      artistProfileArchiveCanScrollLeft = false;
      artistProfileArchiveCanScrollRight = false;
      return;
    }
    const allowance = 4;
    artistProfileArchiveCanScrollLeft = artistProfileArchiveRail.scrollLeft > allowance;
    artistProfileArchiveCanScrollRight = artistProfileArchiveRail.scrollLeft + artistProfileArchiveRail.clientWidth < artistProfileArchiveRail.scrollWidth - allowance;
  }

  function scrollArtistProfileArchive(direction: -1 | 1) {
    if (!artistProfileArchiveRail) return;
    artistProfileArchiveRail.scrollBy({
      left: direction * Math.max(320, artistProfileArchiveRail.clientWidth * 0.82),
      behavior: 'smooth',
    });
    window.setTimeout(updateArtistProfileArchiveRail, 350);
  }

  async function toggleArtistProfileArchiveExpanded() {
    artistProfileArchiveExpanded = !artistProfileArchiveExpanded;
    await tick();
    if (!artistProfileArchiveExpanded && artistProfileArchiveRail) {
      artistProfileArchiveRail.scrollLeft = 0;
    }
    window.requestAnimationFrame(updateArtistProfileArchiveRail);
  }

  async function loadArtistProfileArchive(tagName: string) {
    const requestId = ++artistProfileArchiveSerial;
    artistProfileArchiveLoading = true;
    artistProfileArchiveError = '';
    try {
      const assets = await api.getArtistProfileAssets(tagName);
      if (requestId !== artistProfileArchiveSerial) return;
      artistProfileAssets = assets;
      await tick();
      window.requestAnimationFrame(updateArtistProfileArchiveRail);
    } catch (e) {
      if (requestId !== artistProfileArchiveSerial) return;
      console.error('Failed to load artist profile archive:', e);
      artistProfileArchiveError = 'Could not load archived profile media.';
      artistProfileAssets = [];
    } finally {
      if (requestId === artistProfileArchiveSerial) artistProfileArchiveLoading = false;
    }
  }

  async function refreshArtistProfileArchive() {
    if (tag.category !== 'artist' || artistProfileArchiveBusy) return;
    artistProfileArchiveBusy = true;
    artistProfileArchiveError = '';
    artistProfileArchiveStatus = 'Checking Twitter/X and Pixiv profiles...';
    try {
      const result = await api.refreshArtistProfileAssets(tag.name);
      artistProfileAssets = result.assets;
      artistProfileArchiveStatus = result.saved_count > 0
        ? `Archived ${result.saved_count.toLocaleString()} new profile image${result.saved_count === 1 ? '' : 's'}.`
        : 'No profile image changes found.';
      if (result.notices.length > 0) {
        artistProfileArchiveStatus += ` ${result.notices.join(' ')}`;
      }
      if (result.errors.length > 0) {
        artistProfileArchiveError = result.errors.join(' ');
      }
      await tick();
      window.requestAnimationFrame(updateArtistProfileArchiveRail);
    } catch (e) {
      console.error('Failed to archive artist profile media:', e);
      artistProfileArchiveError = 'Could not archive this artist profile media.';
      artistProfileArchiveStatus = '';
    } finally {
      artistProfileArchiveBusy = false;
    }
  }

  function openExampleImage(localPostId: number | null) {
    if (localPostId !== null) selectedImageId.set(localPostId);
  }

  function isLocalExample(example: TagWikiExample): example is LocalTagWikiExample {
    return example.file_id !== null && example.local_post_id !== null;
  }

  function postReferenceFor(postId: number | null) {
    if (postId === null || !wikiInfo) return null;
    return wikiInfo.post_references.find(post => post.danbooru_post_id === postId) ?? null;
  }

  function coverCandidateTitle(candidate: CoverImage) {
    const parts = [];
    if (candidate.width && candidate.height) parts.push(`${candidate.width}x${candidate.height}`);
    if (candidate.score !== null) parts.push(`Score ${candidate.score}`);
    return parts.length ? `${candidate.filename} (${parts.join(' · ')})` : candidate.filename;
  }

  function imageCreatedTime(image: ImageSummary) {
    if (!image.created_at) return Number.POSITIVE_INFINITY;
    const date = new Date(image.created_at.includes('T') ? image.created_at : `${image.created_at.replace(' ', 'T')}Z`);
    const time = date.getTime();
    return Number.isNaN(time) ? Number.POSITIVE_INFINITY : time;
  }

  function formatJourneyDate(value: string | null) {
    if (!value) return 'No created date';
    const date = new Date(value.includes('T') ? value : `${value.replace(' ', 'T')}Z`);
    if (Number.isNaN(date.getTime())) return value.slice(0, 10);
    return date.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
  }

  function journeyYear(image: ImageSummary) {
    if (!image.created_at) return 'unknown';
    const match = image.created_at.match(/\d{4}/);
    return match ? match[0] : 'unknown';
  }

  function journeyRangeLabel(images: ImageSummary[]) {
    const dated = images.filter(image => image.created_at);
    if (dated.length === 0) return 'No created dates';
    const first = dated[0];
    const last = dated[dated.length - 1];
    if (first.created_at === last.created_at) return formatJourneyDate(first.created_at);
    return `${formatJourneyDate(first.created_at)} - ${formatJourneyDate(last.created_at)}`;
  }

  function groupArtistJourney(images: ImageSummary[]): ArtistJourneyGroup[] {
    const groups = new Map<string, ImageSummary[]>();
    for (const image of images) {
      const key = journeyYear(image);
      const existing = groups.get(key) ?? [];
      existing.push(image);
      groups.set(key, existing);
    }
    return [...groups.entries()]
      .sort(([a], [b]) => {
        if (a === 'unknown') return 1;
        if (b === 'unknown') return -1;
        return Number(a) - Number(b);
      })
      .map(([key, groupImages]) => ({
        key,
        label: key === 'unknown' ? 'No date' : key,
        images: groupImages,
        rangeLabel: journeyRangeLabel(groupImages),
      }));
  }

  async function loadFavoriteTagState() {
    const requestId = ++favoriteTagSerial;
    try {
      const rows = await api.getFavoriteTagNames();
      if (requestId !== favoriteTagSerial) return;
      favoriteTagMeta = new Map(rows.map(row => [favoriteTagKey(row.category, row.name), row]));
    } catch (e) {
      if (requestId !== favoriteTagSerial) return;
      console.error('Failed to load favorite tag state:', e);
      favoriteTagMeta = new Map();
    }
  }

  async function loadArtistFollowState() {
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

  function notifyArtistFollowRefresh() {
    artistFollowRefreshToken.update(n => {
      observedArtistFollowRefreshToken = n + 1;
      return n + 1;
    });
  }

  async function toggleArtistFollow() {
    if (tag.category !== 'artist' || artistFollowBusy) return;
    artistFollowBusy = true;
    try {
      const next = new Set(followedArtistTags);
      if (isArtistFollowed) {
        await api.unfollowArtist(tag.name);
        next.delete(tag.name);
      } else {
        await api.followArtist(tag.name, wikiInfo?.title || displayTag(tag.name));
        next.add(tag.name);
      }
      followedArtistTags = next;
      notifyArtistFollowRefresh();
    } catch (e) {
      console.error('Failed to update artist follow:', e);
    } finally {
      artistFollowBusy = false;
    }
  }

  async function loadArtistJourney(value: BrowseTagSelection) {
    const requestId = ++artistJourneySerial;
    artistJourneyLoading = true;
    artistJourneyError = '';
    artistJourneyImages = [];
    artistJourneyLoadedKey = '';

    try {
      let offset = 0;
      let expectedTotal = Number.POSITIVE_INFINITY;
      const loaded: ImageSummary[] = [];

      while (loaded.length < expectedTotal) {
        const result = await api.getImages({
          q: coverQuery(value),
          sort: 'date',
          order: 'asc',
          offset,
          limit: JOURNEY_BATCH_SIZE,
        });
        if (requestId !== artistJourneySerial) return;

        loaded.push(...result.images);
        expectedTotal = result.total;
        offset += result.images.length;
        if (result.images.length === 0) break;
      }

      artistJourneyImages = loaded.sort((a, b) => imageCreatedTime(a) - imageCreatedTime(b) || a.id - b.id);
      artistJourneyLoadedKey = tagKey(value);
    } catch (e) {
      if (requestId !== artistJourneySerial) return;
      console.error('Failed to load artist journey:', e);
      artistJourneyError = 'Could not load artist journey';
      artistJourneyImages = [];
    } finally {
      if (requestId === artistJourneySerial) artistJourneyLoading = false;
    }
  }

  function toggleArtistJourney() {
    showArtistJourney = !showArtistJourney;
    if (showArtistJourney && artistJourneyLoadedKey !== currentTagKey && tag.category === 'artist') {
      loadArtistJourney(tag);
    }
  }

  $: currentTagKey = tagKey(tag);
  $: if (currentTagKey !== loadedTagKey) {
    loadedTagKey = currentTagKey;
    coverOverride = loadCoverOverride(tag);
    showCoverChooser = false;
    showArtistJourney = false;
    artistJourneyImages = [];
    artistJourneyLoadedKey = '';
    artistJourneyError = '';
    bannerCoverCandidates = [];
    fetchedCoverCandidates = [];
    artistProfileAssets = [];
    artistProfileArchiveExpanded = false;
    artistProfileArchiveError = '';
    artistProfileArchiveStatus = '';
    loadCoverCandidates(tag);
    loadWiki(tag);
    loadFavoriteTagState();
    loadArtistFollowState();
    if (tag.category === 'artist') loadArtistProfileArchive(tag.name);
  }

  $: if ($tagRefreshToken !== observedTagRefreshToken) {
    observedTagRefreshToken = $tagRefreshToken;
    loadFavoriteTagState().catch(console.error);
  }

  $: if ($artistFollowRefreshToken !== observedArtistFollowRefreshToken) {
    observedArtistFollowRefreshToken = $artistFollowRefreshToken;
    loadArtistFollowState().catch(console.error);
  }

  $: coverCandidates = mergeCoverCandidates(
    bannerCoverCandidates,
    mergeCoverCandidates(images.slice(0, 18).map(coverFromImage), fetchedCoverCandidates)
  );
  $: selectedCover = coverOverride ?? preferredBannerCover(bannerCoverCandidates) ?? coverCandidates[0] ?? null;
  $: coverUrl = selectedCover ? thumbnailUrl(selectedCover.file_id, 1200, selectedCover.thumbnail_token) : '';
  $: localCount = total || tag.count;
  $: examples = wikiInfo?.examples ?? [];
  $: localExamples = examples.filter(isLocalExample);
  $: missingExamples = examples.filter(example => !isLocalExample(example));
  $: hasRelatedTags = Boolean(wikiInfo && (wikiInfo.aliases.length > 0 || wikiInfo.implications.length > 0));
  $: titleColor = tag.category === 'artist' ? 'text-red-300' : 'text-sky-300';
  $: bannerContentPadding = Math.max(160, $tagBannerHeight - 110);
  $: headerMinHeight = $tagBannerHeight + 150;
  $: currentFavoriteTag = favoriteTagMeta.get(favoriteTagKey(tag.category, tag.name)) ?? null;
  $: artistJourneyGroups = groupArtistJourney(artistJourneyImages);
  $: artistJourneyDatedImages = artistJourneyImages.filter(image => image.created_at).length;
  $: artistJourneyRange = journeyRangeLabel(artistJourneyImages);
  $: isArtistFollowed = tag.category === 'artist' && followedArtistTags.has(tag.name);
  $: showArtistProfileArchiveExpand = artistProfileAssets.length >= PROFILE_ARCHIVE_EXPAND_THRESHOLD;
</script>

<svelte:window on:resize={updateArtistProfileArchiveRail} />

{#snippet wikiPostReference(post: TagWikiExample | null, postId: number)}
  {#if post?.file_id && post.local_post_id}
    <button
      type="button"
      class="mx-1 inline-flex h-14 w-12 align-middle items-end justify-center overflow-hidden rounded border border-[#2a2a3a] bg-[#1a1a24] bg-cover bg-center text-[9px] text-gray-100 shadow transition-colors hover:border-sky-500/50"
      style={`background-image: linear-gradient(to top, rgba(0,0,0,.78), rgba(0,0,0,0) 60%), url('${thumbnailUrl(post.file_id, 160, post.thumbnail_token || undefined)}')`}
      title="Open local image #{postId}"
      on:click={() => openExampleImage(post.local_post_id)}
    >
      <span class="mb-0.5 rounded bg-black/45 px-1">#{postId}</span>
    </button>
  {:else}
    <a
      class="mx-1 inline-flex min-w-24 flex-col items-center justify-center align-middle rounded border border-dashed border-[#3a3a50] bg-[#15151d]/80 px-2 py-1 text-center text-[10px] text-gray-500 transition-colors hover:border-sky-500/40 hover:text-sky-300"
      href={post?.post_url || `https://danbooru.donmai.us/posts/${postId}`}
      target="_blank"
      rel="noreferrer"
      title="Open Danbooru post #{postId}"
    >
      <span class="font-semibold text-sky-400/70">#{postId}</span>
      <span>Not in library</span>
    </a>
  {/if}
{/snippet}

{#snippet artistProfileArchiveTile(asset: ArtistProfileAsset, expanded: boolean)}
  <button
    type="button"
    class="group relative aspect-[4/3] overflow-hidden rounded-lg border border-[#2a2a3a] bg-[#101018] shadow-lg shadow-black/20 transition-colors hover:border-sky-500/50 {expanded ? 'w-full' : 'w-56 shrink-0'}"
    on:click={() => selectedArtistProfileAsset.set(asset)}
    title="Open archived {artistProfileAssetLabel(asset)} from {formatArtistProfileCapture(asset.captured_at)}"
  >
    <img
      class="h-full w-full object-cover object-center transition-transform duration-300 group-hover:scale-105"
      src={asset.file_url}
      alt="Archived {artistProfileAssetLabel(asset)}"
      loading="lazy"
      decoding="async"
    />
    <span class="absolute inset-0 bg-gradient-to-t from-black/85 via-transparent to-black/15"></span>
    <span class="absolute left-2 top-2 rounded border border-white/15 bg-black/55 px-2 py-0.5 text-[10px] font-semibold uppercase text-white">
      {artistProfileAssetLabel(asset)}
    </span>
    <span class="absolute bottom-2 left-2 right-2 flex items-end justify-between gap-2 text-[11px] text-gray-200">
      <span>{formatArtistProfileCapture(asset.captured_at)}</span>
      <span class="text-gray-400">{asset.width}x{asset.height}</span>
    </span>
  </button>
{/snippet}

{#snippet wikiLine(line: TagWikiTextLine)}
  {#each line.parts as part}
    {#if part.post_id}
      {@render wikiPostReference(postReferenceFor(part.post_id), part.post_id)}
    {:else if part.tag}
      <button
        type="button"
        class="text-sky-400 transition-colors hover:text-sky-300 hover:underline"
        on:click={() => part.tag && selectLinkedTag(part.tag)}
      >{part.text}</button>
    {:else}
      {part.text}
    {/if}
  {/each}
{/snippet}

<section class="relative -mx-4 -mt-4 mb-4 overflow-hidden border-b border-[#2a2a3a] bg-[#0f0f14]">
  {#if coverUrl}
    <div class="absolute inset-x-0 top-0 overflow-hidden bg-[#0f0f14]" style={`height: ${$tagBannerHeight}px;`}>
      <img
        class="absolute inset-0 h-full w-full scale-[1.03] object-cover opacity-90 saturate-110"
        style="object-position: center 35%;"
        src={coverUrl}
        alt=""
        aria-hidden="true"
      />
      <div
        class="absolute inset-0"
        style="background: linear-gradient(to bottom, rgba(15,15,20,.05) 0%, rgba(15,15,20,.06) 34%, rgba(15,15,20,.48) 72%, #0f0f14 100%);"
      ></div>
      <div
        class="absolute inset-0"
        style="background: linear-gradient(to right, rgba(15,15,20,.28) 0%, rgba(15,15,20,.03) 20%, rgba(15,15,20,.04) 72%, rgba(15,15,20,.36) 100%);"
      ></div>
    </div>
  {:else}
    <div
      class="absolute inset-x-0 top-0 bg-[radial-gradient(circle_at_25%_20%,rgba(14,165,233,.18),transparent_34%),linear-gradient(135deg,#171721,#0f0f14_72%)]"
      style={`height: ${$tagBannerHeight}px;`}
    ></div>
  {/if}

  {#if showBackAction}
    <button
      class="group absolute left-6 top-5 z-20 inline-flex max-w-[calc(100%_-_3rem)] items-center gap-2 rounded-full bg-black/35 px-3 py-1.5 text-sm text-gray-200 shadow-lg shadow-black/20 backdrop-blur-md transition-colors hover:bg-black/60 hover:text-white"
      type="button"
      aria-label="Back to Tags"
      title="Back to Tags"
      on:click={() => dispatch('back')}
    >
      <svg class="h-4 w-4 shrink-0 text-purple-200 transition-transform group-hover:-translate-x-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7" />
      </svg>
      <span class="font-medium">Tags</span>
      <span class="text-gray-500">/</span>
      <span class="truncate text-gray-400">{displayTag(tag.name)}</span>
    </button>
  {/if}

  <div
    class="relative px-6 pb-7"
    style={`min-height: ${headerMinHeight}px; padding-top: ${bannerContentPadding}px;`}
  >
    <div class="mb-6 flex flex-wrap items-start justify-between gap-4">
      <div class="min-w-0 max-w-4xl">
        <div class="mb-2 flex flex-wrap items-center gap-2 text-xs text-gray-400">
          <span class="rounded border px-2 py-0.5 text-[10px] uppercase tracking-wider {categoryColors[tag.category] || categoryColors.unknown}">
            {tag.category}
          </span>
          <span>{localCount.toLocaleString()} local images</span>
          {#if currentFavoriteTag}
            <span class="inline-flex items-center gap-1 rounded border border-pink-500/30 bg-pink-600/20 px-2 py-0.5 text-[10px] uppercase tracking-wider text-pink-200">
              <span>♥</span>
              Favorited
            </span>
            {#if currentFavoriteTag.pinned_at}
              <span class="inline-flex items-center gap-1 rounded border border-amber-500/30 bg-amber-600/15 px-2 py-0.5 text-[10px] uppercase tracking-wider text-amber-200">
                Pinned
              </span>
            {/if}
          {/if}
          {#if tag.source === 'user'}
            <span class="rounded border border-pink-500/30 bg-pink-600/20 px-2 py-0.5 text-[10px] uppercase tracking-wider text-pink-200">User-added</span>
          {/if}
        </div>
        <h1 class="break-words text-4xl font-bold leading-tight {titleColor}">
          {displayTag(wikiInfo?.title || tag.name)}
        </h1>
        {#if wikiInfo?.other_names.length}
          <div class="mt-3 flex flex-wrap gap-1.5">
            {#each wikiInfo.other_names as name}
              <span class="rounded border border-sky-500/30 bg-sky-600/15 px-2 py-0.5 text-xs text-sky-200">{name}</span>
            {/each}
          </div>
        {/if}
        {#if tag.category === 'artist'}
          <div class="mt-4 flex flex-wrap items-center gap-2">
            <button
              type="button"
              class="inline-flex items-center gap-2 rounded-lg border px-3 py-1.5 text-sm shadow-lg shadow-black/15 backdrop-blur transition-colors {showArtistJourney ? 'border-red-400/50 bg-red-500/20 text-red-100' : 'border-red-500/30 bg-[#14141f]/80 text-red-200 hover:border-red-400/50 hover:text-red-100'}"
              on:click={toggleArtistJourney}
            >
              <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 19c4-9 8-9 12 0M4 5h16M7 5v14M17 5v14"/>
              </svg>
              Artist Journey
              {#if artistJourneyLoadedKey === currentTagKey && artistJourneyImages.length > 0}
                <span class="rounded bg-black/30 px-1.5 py-0.5 text-[10px] text-red-100/80">
                  {artistJourneyImages.length.toLocaleString()}
                </span>
              {/if}
            </button>
            <button
              type="button"
              class="inline-flex items-center gap-2 rounded-lg border px-3 py-1.5 text-sm shadow-lg shadow-black/15 backdrop-blur transition-colors disabled:cursor-not-allowed disabled:opacity-60 {isArtistFollowed ? 'border-cyan-400/50 bg-cyan-500/20 text-cyan-100 hover:border-cyan-300/60' : 'border-cyan-500/30 bg-[#14141f]/80 text-cyan-200 hover:border-cyan-400/50 hover:text-cyan-100'}"
              disabled={artistFollowBusy}
              on:click={toggleArtistFollow}
              title={isArtistFollowed ? 'Remove this artist from your profile follows' : 'Follow this artist on your profile'}
            >
              <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                {#if isArtistFollowed}
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/>
                {:else}
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 5v14M5 12h14"/>
                {/if}
              </svg>
              {isArtistFollowed ? 'Following' : 'Follow Artist'}
            </button>
            <button
              type="button"
              class="inline-flex items-center gap-2 rounded-lg border border-sky-500/30 bg-[#14141f]/80 px-3 py-1.5 text-sm text-sky-200 shadow-lg shadow-black/15 backdrop-blur transition-colors hover:border-sky-400/50 hover:text-sky-100 disabled:cursor-not-allowed disabled:opacity-60"
              disabled={artistProfileArchiveBusy || wikiLoading}
              on:click={refreshArtistProfileArchive}
              title="Save the current Twitter/X and Pixiv logos and banners locally"
            >
              <svg class="h-4 w-4 {artistProfileArchiveBusy ? 'animate-spin' : ''}" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 7v10a2 2 0 002 2h12a2 2 0 002-2V7M8 3h8l2 4H6l2-4zm4 7v6m-3-3h6" />
              </svg>
              {artistProfileArchiveBusy ? 'Archiving Profiles' : 'Archive Logos & Banners'}
            </button>
          </div>
          {#if artistProfileArchiveStatus || artistProfileArchiveError}
            <div class="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs">
              {#if artistProfileArchiveStatus}
                <span class="text-sky-200/80">{artistProfileArchiveStatus}</span>
              {/if}
              {#if artistProfileArchiveError}
                <span class="text-red-200/80">{artistProfileArchiveError}</span>
              {/if}
            </div>
          {/if}
        {/if}
      </div>

      <div class="relative ml-auto shrink-0">
        <button
          type="button"
          data-testid="tag-cover-button"
          class="inline-flex items-center gap-2 rounded-lg border border-[#2a2a3a] bg-[#14141f]/80 px-3 py-1.5 text-xs text-gray-300 shadow-lg shadow-black/20 backdrop-blur transition-colors hover:border-sky-500/40 hover:text-sky-200 disabled:cursor-not-allowed disabled:opacity-50"
          disabled={coverCandidates.length === 0 && !coverOverride && !coverLoading}
          on:click|stopPropagation={() => showCoverChooser = !showCoverChooser}
          title="Change tag cover"
        >
          <svg class="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16l4-4a2 2 0 012.8 0l1.2 1.2L15 10a2 2 0 012.8 0L20 12.2M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z"/>
          </svg>
          Change Cover
        </button>

        {#if showCoverChooser}
          <div data-testid="tag-cover-panel" class="absolute right-0 top-full z-40 mt-2 w-80 max-w-[calc(100vw-2rem)] rounded-lg border border-[#2a2a3a] bg-[#171720] p-3 shadow-xl">
            <div class="mb-2 flex items-center justify-between gap-2">
              <div class="text-xs font-medium text-gray-300">Cover from current results</div>
              <button
                type="button"
                data-testid="tag-cover-auto"
                class="rounded border border-[#2a2a3a] px-2 py-1 text-[11px] text-gray-500 transition-colors hover:bg-[#1e1e2e] hover:text-gray-300 disabled:cursor-not-allowed disabled:opacity-40"
                disabled={!coverOverride}
                on:click={clearCoverOverride}
              >Auto</button>
            </div>
            {#if coverCandidates.length === 0}
              <div class="py-5 text-center text-xs text-gray-500">
                {coverLoading || loading ? 'Loading images' : 'No local images for cover'}
              </div>
            {:else}
              <div class="grid max-h-72 grid-cols-4 gap-1.5 overflow-y-auto pr-1">
                {#each coverCandidates as candidate}
                  <button
                    type="button"
                    data-testid="tag-cover-option"
                    class="group relative aspect-square overflow-hidden rounded border bg-[#101018] transition-colors {selectedCover?.id === candidate.id ? 'border-sky-400 ring-1 ring-sky-400/50' : 'border-[#2a2a3a] hover:border-sky-500/50'}"
                    on:click={() => saveCoverOverride(candidate)}
                    title={coverCandidateTitle(candidate)}
                  >
                    <img
                      class="h-full w-full object-cover transition-transform group-hover:scale-105"
                      src={thumbnailUrl(candidate.file_id, 240, candidate.thumbnail_token)}
                      alt={candidate.filename}
                      loading="lazy"
                    />
                    {#if selectedCover?.id === candidate.id}
                      <span class="absolute right-1 top-1 flex h-4 w-4 items-center justify-center rounded-full bg-sky-500 text-[10px] text-white">
                        <svg class="h-3 w-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7"/>
                        </svg>
                      </span>
                    {/if}
                  </button>
                {/each}
              </div>
            {/if}
          </div>
        {/if}
      </div>
    </div>

    {#if wikiLoading}
      <div class="flex items-center gap-2 py-4 text-sm text-gray-500">
        <div class="h-5 w-5 rounded-full border-2 border-sky-500 border-t-transparent animate-spin"></div>
        Loading tag info
      </div>
    {:else if wikiInfo?.available}
      <div class="grid max-w-7xl gap-6 lg:grid-cols-[minmax(0,1fr)_300px]">
        <div class="space-y-5">
          {#if tag.category === 'artist' && (artistProfileArchiveLoading || artistProfileAssets.length > 0)}
            <section class="max-w-5xl border-y border-[#2a2a3a]/80 py-4">
              <div class="mb-3 flex flex-wrap items-end justify-between gap-3">
                <div>
                  <h3 class="text-sm font-semibold uppercase tracking-wider text-gray-300">Profile Media Archive</h3>
                  <p class="mt-1 text-xs text-gray-500">Saved Twitter/X and Pixiv logos and banners</p>
                </div>
                {#if showArtistProfileArchiveExpand}
                  <button
                    type="button"
                    class="inline-flex items-center gap-2 rounded border border-[#2a2a3a] bg-[#15151f] px-2.5 py-1.5 text-xs text-gray-300 transition-colors hover:border-sky-500/40 hover:text-sky-100"
                    aria-expanded={artistProfileArchiveExpanded}
                    on:click={toggleArtistProfileArchiveExpanded}
                  >
                    {artistProfileArchiveExpanded ? 'Collapse archive' : 'Expand to see all'}
                  </button>
                {/if}
              </div>

              {#if artistProfileArchiveLoading}
                <div class="flex items-center gap-2 py-8 text-sm text-gray-500">
                  <div class="h-5 w-5 animate-spin rounded-full border-2 border-sky-500 border-t-transparent"></div>
                  Loading profile archive
                </div>
              {:else if artistProfileArchiveExpanded}
                <div class="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-4">
                  {#each artistProfileAssets as asset (asset.id)}
                    {@render artistProfileArchiveTile(asset, true)}
                  {/each}
                </div>
              {:else}
                <div class="relative">
                  <div
                    bind:this={artistProfileArchiveRail}
                    class="flex gap-3 overflow-x-auto scroll-smooth pb-2"
                    on:scroll={updateArtistProfileArchiveRail}
                  >
                    {#each artistProfileAssets as asset (asset.id)}
                      {@render artistProfileArchiveTile(asset, false)}
                    {/each}
                  </div>
                  {#if artistProfileArchiveCanScrollLeft}
                    <button
                      type="button"
                      class="absolute left-2 top-1/2 z-10 grid h-9 w-9 -translate-y-1/2 place-items-center rounded-full border border-white/15 bg-[#0c0c13]/90 text-gray-200 shadow-xl transition-colors hover:border-sky-400/50 hover:text-sky-100"
                      aria-label="Scroll profile archive left"
                      title="Previous archived profile images"
                      on:click={() => scrollArtistProfileArchive(-1)}
                    >
                      <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7" />
                      </svg>
                    </button>
                  {/if}
                  {#if artistProfileArchiveCanScrollRight}
                    <button
                      type="button"
                      class="absolute right-2 top-1/2 z-10 grid h-9 w-9 -translate-y-1/2 place-items-center rounded-full border border-white/15 bg-[#0c0c13]/90 text-gray-200 shadow-xl transition-colors hover:border-sky-400/50 hover:text-sky-100"
                      aria-label="Scroll profile archive right"
                      title="More archived profile images"
                      on:click={() => scrollArtistProfileArchive(1)}
                    >
                      <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
                      </svg>
                    </button>
                  {/if}
                </div>
              {/if}
            </section>
          {/if}

          {#if wikiInfo.artist_group_name || wikiInfo.artist_urls.length > 0}
            <div class="max-w-5xl space-y-4 rounded-lg border border-[#2a2a3a]/80 bg-[#111119]/70 p-4 shadow-lg shadow-black/10">
              {#if wikiInfo.artist_group_name}
                <div class="flex flex-wrap items-center gap-2 text-sm">
                  <span class="font-semibold text-gray-200">Group</span>
                  <button
                    type="button"
                    class="rounded border border-sky-500/30 bg-sky-600/15 px-2 py-0.5 text-xs text-sky-200 transition-colors hover:border-sky-400/50 hover:text-sky-100"
                    on:click={() => wikiInfo?.artist_group_name && selectLinkedTag(wikiInfo.artist_group_name)}
                  >
                    {displayTag(wikiInfo.artist_group_name)}
                  </button>
                </div>
              {/if}

              {#if wikiInfo.artist_urls.length > 0}
                <div>
                  <h3 class="mb-2 text-sm font-semibold uppercase tracking-wider text-gray-400">URLs</h3>
                  <div class="grid gap-1.5 sm:grid-cols-2 xl:grid-cols-3">
                    {#each wikiInfo.artist_urls as artistUrl}
                      <a
                        class="group flex min-w-0 items-center gap-2 rounded border border-transparent px-2 py-1 text-sm transition-colors hover:border-sky-500/30 hover:bg-sky-500/10 {artistUrl.is_active ? 'text-sky-300' : 'text-red-300/70 line-through'}"
                        href={artistUrl.url}
                        target="_blank"
                        rel="noreferrer"
                        title={artistUrl.url}
                      >
                        <span class="flex h-5 w-5 shrink-0 items-center justify-center rounded bg-[#202030] text-[10px] font-semibold text-gray-300">
                          {artistUrlMarker(artistUrl)}
                        </span>
                        <span class="min-w-0 truncate">{artistUrl.url}</span>
                      </a>
                    {/each}
                  </div>
                </div>
              {/if}
            </div>
          {/if}

          {#if wikiInfo.description.length > 0}
            <div class="max-w-5xl space-y-2 text-[15px] leading-7 text-gray-100">
              {#each wikiInfo.description as line}
                <p>{@render wikiLine(line)}</p>
              {/each}
            </div>
          {/if}

          {#each wikiInfo.sections as section}
            <div class="max-w-5xl">
              <h3 class="mb-2 text-lg font-semibold text-gray-100">{section.title}</h3>
              {#if section.paragraphs.length > 0}
                <div class="mb-2 space-y-2 text-sm leading-6 text-gray-200">
                  {#each section.paragraphs as line}
                    <p>{@render wikiLine(line)}</p>
                  {/each}
                </div>
              {/if}
              {#if section.items.length > 0}
                <ul class="space-y-1 text-sm leading-5 text-gray-200">
                  {#each section.items as item}
                    <li class="flex gap-2">
                      <span class="mt-2 h-1 w-1 shrink-0 rounded-full bg-gray-500"></span>
                      <span>{@render wikiLine(item)}</span>
                    </li>
                  {/each}
                </ul>
              {/if}
            </div>
          {/each}

          {#if hasRelatedTags}
            <div class="space-y-2 pt-1 text-xs italic text-gray-500">
              {#if wikiInfo.aliases.length > 0}
                <p>
                  The following tags are aliased to this tag:
                  {#each wikiInfo.aliases as alias, index}
                    <button class="text-sky-400 hover:text-sky-300 hover:underline" on:click={() => selectLinkedTag(alias)}>{displayTag(alias)}</button>{index < wikiInfo.aliases.length - 1 ? ', ' : '.'}
                  {/each}
                </p>
              {/if}
              {#if wikiInfo.implications.length > 0}
                <p>
                  This tag implicates
                  {#each wikiInfo.implications as implication, index}
                    <button class="text-sky-400 hover:text-sky-300 hover:underline" on:click={() => selectLinkedTag(implication)}>{displayTag(implication)}</button>{index < wikiInfo.implications.length - 1 ? ', ' : '.'}
                  {/each}
                </p>
              {/if}
            </div>
          {/if}
        </div>

        {#if examples.length > 0}
          <aside>
            <h3 class="mb-3 text-sm font-semibold uppercase tracking-wider text-gray-400">Examples</h3>
            <div class="space-y-3">
              {#if localExamples.length > 0}
                <div class="grid grid-cols-3 gap-2">
                  {#each localExamples as example}
                  <button
                    class="group relative aspect-[3/4] overflow-hidden rounded border border-[#2a2a3a] bg-[#1a1a24] transition-colors hover:border-sky-500/50"
                    on:click={() => openExampleImage(example.local_post_id)}
                    title="Open local image #{example.danbooru_post_id}"
                  >
                    <img
                      src={thumbnailUrl(example.file_id, 280, example.thumbnail_token || undefined)}
                      alt={example.filename || `Danbooru post ${example.danbooru_post_id}`}
                      class="h-full w-full object-cover transition-transform group-hover:scale-105"
                      loading="lazy"
                    />
                    <span class="absolute bottom-1 left-1 rounded bg-black/65 px-1.5 py-0.5 text-[10px] text-gray-200">
                      #{example.danbooru_post_id}
                    </span>
                  </button>
                  {/each}
                </div>
              {/if}

              {#if missingExamples.length > 0}
                <div class="grid grid-cols-3 gap-2">
                  {#each missingExamples as example}
                  <a
                    class="group flex aspect-[3/4] flex-col items-center justify-center rounded border border-dashed border-[#3a3a50] bg-[#15151d]/80 px-2 text-center text-xs text-gray-500 transition-colors hover:border-sky-500/40 hover:text-sky-300"
                    href={example.post_url || `https://danbooru.donmai.us/posts/${example.danbooru_post_id}`}
                    target="_blank"
                    rel="noreferrer"
                    title="Open Danbooru post #{example.danbooru_post_id}"
                  >
                    <span class="font-semibold text-sky-400/70 group-hover:text-sky-300">#{example.danbooru_post_id}</span>
                    <span class="mt-2">Not in library</span>
                  </a>
                  {/each}
                </div>
              {/if}
            </div>
          </aside>
        {/if}
      </div>
    {:else if wikiInfo?.error || wikiError}
      <div class="max-w-4xl rounded-lg border border-[#2a2a3a] bg-[#171720]/70 px-4 py-3 text-sm text-gray-500">
        {wikiInfo?.error || wikiError}
      </div>
    {/if}

    {#if tag.category === 'artist' && showArtistJourney}
      <div class="mt-7 max-w-none rounded-xl border border-red-500/20 bg-[#111119]/82 p-5 shadow-xl shadow-black/20">
        <div class="mb-5 flex flex-wrap items-start justify-between gap-3">
          <div>
            <div class="text-[10px] font-semibold uppercase tracking-[0.2em] text-red-300/70">Artist's Journey Through Art</div>
            <h3 class="mt-1 text-xl font-bold text-gray-100">{displayTag(wikiInfo?.title || tag.name)}</h3>
            <p class="mt-1 text-sm text-gray-500">
              {#if artistJourneyLoading}
                Building the timeline from every local post
              {:else if artistJourneyImages.length > 0}
                {artistJourneyImages.length.toLocaleString()} local images · {artistJourneyDatedImages.toLocaleString()} dated · {artistJourneyRange}
              {:else}
                No local images loaded yet
              {/if}
            </p>
          </div>
          <button
            type="button"
            class="rounded-lg border border-[#2a2a3a] px-3 py-1.5 text-xs text-gray-400 transition-colors hover:bg-[#1e1e2e] hover:text-gray-200"
            on:click={() => showArtistJourney = false}
          >
            Hide
          </button>
        </div>

        {#if artistJourneyLoading}
          <div class="flex items-center gap-3 rounded-lg border border-[#2a2a3a] bg-[#15151d] px-4 py-5 text-sm text-gray-400">
            <div class="h-5 w-5 rounded-full border-2 border-red-400 border-t-transparent animate-spin"></div>
            Loading artist timeline
          </div>
        {:else if artistJourneyError}
          <div class="rounded-lg border border-red-500/20 bg-red-500/10 px-4 py-3 text-sm text-red-200">{artistJourneyError}</div>
        {:else if artistJourneyGroups.length === 0}
          <div class="rounded-lg border border-[#2a2a3a] bg-[#15151d] px-4 py-5 text-sm text-gray-500">No local images found for this artist.</div>
        {:else}
          <div class="space-y-6">
            {#each artistJourneyGroups as group}
              <div class="grid gap-4 md:grid-cols-[9rem_minmax(0,1fr)]">
                <div class="pt-1">
                  <div class="text-3xl font-bold text-red-200">{group.label}</div>
                  <div class="mt-1 text-xs text-gray-500">{group.images.length.toLocaleString()} images</div>
                  <div class="mt-1 text-[11px] leading-4 text-gray-600">{group.rangeLabel}</div>
                </div>
                <div class="relative overflow-hidden rounded-xl border border-[#252536] bg-[#0f0f16]/90">
                  <div class="absolute left-0 right-0 top-1/2 h-px bg-red-500/20"></div>
                  <div class="relative flex gap-3 overflow-x-auto px-4 py-4">
                    {#each group.images as image}
                      <button
                        type="button"
                        class="group relative h-60 w-44 shrink-0 overflow-hidden rounded-lg border border-[#2a2a3a] bg-[#181822] text-left shadow-lg shadow-black/25 transition-colors hover:border-red-400/60"
                        title={`${image.filename}\n${formatJourneyDate(image.created_at)}${image.score !== null ? ` · Score ${image.score}` : ''}`}
                        on:click={() => selectedImageId.set(image.id)}
                      >
                        <img
                          class="h-full w-full object-cover transition-transform group-hover:scale-105"
                          src={thumbnailUrl(image.file_id, 520, image.thumbnail_token)}
                          alt={image.filename}
                          loading="lazy"
                        />
                        <span class="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/90 via-black/45 to-transparent px-2 pb-2 pt-10 text-xs font-medium text-gray-100">
                          {formatJourneyDate(image.created_at)}
                        </span>
                        {#if image.score !== null}
                          <span class="absolute right-2 top-2 rounded bg-black/70 px-1.5 py-0.5 text-xs font-semibold text-gray-100">{image.score}</span>
                        {/if}
                      </button>
                    {/each}
                  </div>
                </div>
              </div>
            {/each}
          </div>
        {/if}
      </div>
    {/if}
  </div>
</section>
