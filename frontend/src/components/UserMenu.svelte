<script lang="ts">
  import { onMount } from 'svelte';
  import SearchHelpModal from './SearchHelpModal.svelte';
  import { prepareSettingsPresentation } from '../lib/settingsPresentation';
  import { loadSettingsModal, type SettingsModalModule } from '../lib/settingsLoader';
  import { activeCollectionId, selectedImageId, viewMode } from '../lib/stores';

  let showMenu = false;
  let showSettings = false;
  let settingsModule: SettingsModalModule | null = null;
  let showSearchHelp = false;

  function toggleMenu() {
    showMenu = !showMenu;
  }

  function closeMenu() {
    showMenu = false;
  }

  onMount(() => {
    const preloadTimer = window.setTimeout(() => {
      loadSettingsModal().then((module) => settingsModule = module).catch(console.error);
    }, 1_200);
    return () => window.clearTimeout(preloadTimer);
  });

  async function openSettings() {
    showMenu = false;
    settingsModule = settingsModule ?? await loadSettingsModal();
    prepareSettingsPresentation();
    showSettings = true;
  }

  function openSearchHelp() {
    showMenu = false;
    showSearchHelp = true;
  }

  function openProfile() {
    activeCollectionId.set(null);
    selectedImageId.set(null);
    viewMode.set('profile');
    showMenu = false;
  }

  function openFavorites() {
    activeCollectionId.set(null);
    selectedImageId.set(null);
    viewMode.set('favorites');
    showMenu = false;
  }

  function openCollections() {
    activeCollectionId.set(null);
    selectedImageId.set(null);
    viewMode.set('collections');
    showMenu = false;
  }

  function handleKeydown(event: KeyboardEvent) {
    if (event.key === 'Escape') {
      closeMenu();
      showSettings = false;
      showSearchHelp = false;
    }
  }
</script>

<svelte:window on:click={closeMenu} on:keydown={handleKeydown} />

<div class="relative flex items-center gap-2">
  <button
    class="group grid h-9 w-9 place-items-center overflow-hidden rounded-lg border border-[#343449] bg-[#15151f] transition-all hover:border-purple-400/70 hover:shadow-[0_0_18px_rgba(168,85,247,0.25)]"
    type="button"
    title="User menu"
    aria-haspopup="menu"
    aria-expanded={showMenu}
    on:click|stopPropagation={toggleMenu}
  >
    <img
      src="/profile-avatar.svg"
      alt=""
      class="h-full w-full object-cover transition-transform group-hover:scale-105"
      decoding="async"
    />
  </button>

  {#if showMenu}
    <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
    <div
      class="absolute right-0 top-full z-[80] mt-2 w-44 overflow-hidden rounded-lg border border-[#2d2d3c] bg-[#111118] p-1.5 shadow-2xl shadow-black/50"
      role="menu"
      tabindex="-1"
      on:click|stopPropagation
    >
      <button
        class="flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm transition-colors {$viewMode === 'profile' ? 'bg-purple-600/20 text-purple-200' : 'text-gray-200 hover:bg-[#1d1d29] hover:text-white'}"
        type="button"
        role="menuitem"
        on:click={openProfile}
      >
        <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM5 21a7 7 0 0114 0" />
        </svg>
        Profile
      </button>

      <button
        class="flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm transition-colors {$viewMode === 'favorites' ? 'bg-purple-600/20 text-purple-200' : 'text-gray-200 hover:bg-[#1d1d29] hover:text-white'}"
        type="button"
        role="menuitem"
        on:click={openFavorites}
      >
        <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z" />
        </svg>
        Favorites
      </button>

      <button
        class="flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm transition-colors {$viewMode === 'collections' || $viewMode === 'collection-detail' ? 'bg-purple-600/20 text-purple-200' : 'text-gray-200 hover:bg-[#1d1d29] hover:text-white'}"
        type="button"
        role="menuitem"
        on:click={openCollections}
      >
        <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
        </svg>
        Collections
      </button>

      <div class="mx-1 my-1 border-t border-[#282838]"></div>

      <button
        class="flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm text-gray-200 transition-colors hover:bg-[#1d1d29] hover:text-white"
        type="button"
        role="menuitem"
        on:click={openSearchHelp}
      >
        <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5a6 6 0 104.5 9.9L20 19.5M10 8h4m-2-2v4" />
        </svg>
        Search Help
      </button>

      <div class="mx-1 my-1 border-t border-[#282838]"></div>

      <button
        class="flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm text-gray-200 transition-colors hover:bg-[#1d1d29] hover:text-white"
        type="button"
        role="menuitem"
        on:click={openSettings}
      >
        <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.3 4.3c.4-1.8 2.9-1.8 3.4 0a1.7 1.7 0 002.6 1.1c1.5-.9 3.3.8 2.4 2.4a1.7 1.7 0 001.1 2.6c1.8.4 1.8 2.9 0 3.4a1.7 1.7 0 00-1.1 2.6c.9 1.5-.8 3.3-2.4 2.4a1.7 1.7 0 00-2.6 1.1c-.4 1.8-2.9 1.8-3.4 0a1.7 1.7 0 00-2.6-1.1c-1.5.9-3.3-.8-2.4-2.4a1.7 1.7 0 00-1.1-2.6c-1.8-.4-1.8-2.9 0-3.4a1.7 1.7 0 001.1-2.6c-.9-1.5.8-3.3 2.4-2.4a1.7 1.7 0 002.6-1.1z" />
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
        </svg>
        Settings
      </button>
    </div>
  {/if}
</div>

{#if showSettings}
  {#if settingsModule}
    <svelte:component this={settingsModule.default} on:close={() => showSettings = false} />
  {/if}
{/if}

{#if showSearchHelp}
  <SearchHelpModal on:close={() => showSearchHelp = false} />
{/if}
