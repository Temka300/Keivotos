<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '../../lib/api';
  import {
    blacklistedTagNames,
    selectedArtistProfileAsset,
    selectedImageId,
    viewMode,
  } from '../../lib/stores';
  import CollectionsView from '../../components/CollectionsView.svelte';
  import DailyChallengeView from '../../components/DailyChallengeView.svelte';
  import HomeView from '../../components/HomeView.svelte';
  import ImageDetail from '../../components/ImageDetail.svelte';
  import ImageGrid from '../../components/ImageGrid.svelte';
  import PopularityBrowser from '../../components/PopularityBrowser.svelte';
  import ProfileView from '../../components/ProfileView.svelte';
  import SidebarDock from '../../components/SidebarDock.svelte';
  import TagsBrowser from '../../components/TagsBrowser.svelte';
  import TimelapseBrowser from '../../components/TimelapseBrowser.svelte';
  import TopBar from '../../components/TopBar.svelte';

  onMount(async () => {
    try {
      blacklistedTagNames.set(await api.getBlacklistTagNames());
    } catch (error) {
      console.error('Failed to load blacklist tags:', error);
    }
  });
</script>

<TopBar />

<div class="flex flex-1 overflow-hidden">
  {#if $viewMode === 'gallery' || $viewMode === 'tags'}
    <SidebarDock />
  {/if}

  <main class="min-w-0 flex-1 overflow-hidden">
    {#if $viewMode === 'home'}
      <HomeView />
    {:else if $viewMode === 'profile'}
      <ProfileView />
    {:else if $viewMode === 'collections'}
      <CollectionsView />
    {:else if $viewMode === 'tags'}
      <TagsBrowser />
    {:else if $viewMode === 'popularity'}
      <PopularityBrowser />
    {:else if $viewMode === 'timelapse'}
      <TimelapseBrowser />
    {:else if $viewMode === 'challenges'}
      <DailyChallengeView />
    {:else}
      <ImageGrid />
    {/if}
  </main>
</div>

{#if $selectedArtistProfileAsset !== null}
  <ImageDetail
    profileAsset={$selectedArtistProfileAsset}
    on:close={() => selectedArtistProfileAsset.set(null)}
  />
{:else if $selectedImageId !== null}
  <ImageDetail postId={$selectedImageId} on:close={() => selectedImageId.set(null)} />
{/if}
