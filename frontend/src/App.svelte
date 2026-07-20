<script lang="ts">
  import { onMount } from 'svelte';
  import './app.css';
  import TopBar from './components/TopBar.svelte';
  import SidebarDock from './components/SidebarDock.svelte';
  import HomeView from './components/HomeView.svelte';
  import ProfileView from './components/ProfileView.svelte';
  import ImageGrid from './components/ImageGrid.svelte';
  import ImageDetail from './components/ImageDetail.svelte';
  import CollectionsView from './components/CollectionsView.svelte';
  import TagsBrowser from './components/TagsBrowser.svelte';
  import PopularityBrowser from './components/PopularityBrowser.svelte';
  import TimelapseBrowser from './components/TimelapseBrowser.svelte';
  import DailyChallengeView from './components/DailyChallengeView.svelte';
  import { api } from './lib/api';
  import { viewMode, selectedImageId, selectedArtistProfileAsset, blacklistedTagNames, interfaceScale, motionPreference } from './lib/stores';

  $: if (typeof document !== 'undefined') {
    document.documentElement.dataset.motion = $motionPreference;
    document.documentElement.dataset.interfaceScale = $interfaceScale;
  }

  onMount(async () => {
    try {
      blacklistedTagNames.set(await api.getBlacklistTagNames());
    } catch (e) {
      console.error('Failed to load blacklist tags:', e);
    }
  });
</script>

<div class="flex flex-col h-screen bg-[#0f0f14] text-gray-200">
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
</div>
