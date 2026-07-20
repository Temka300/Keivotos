<script lang="ts">
  import { createEventDispatcher, onDestroy } from 'svelte';
  import { prepareSettingsPresentation } from '../lib/settingsPresentation';
  import { loadSettingsModal, type SettingsModalModule } from '../lib/settingsLoader';
  import { MODULE_DISPLAY_NAME, SUITE_NAME } from '../lib/product';
  import { activeCollectionId, selectedImageId, viewMode } from '../lib/stores';

  const dispatch = createEventDispatcher<{ close: void }>();
  const DRAWER_EXIT_MS = 180;
  let showSettings = false;
  let settingsModule: SettingsModalModule | null = null;
  let closing = false;
  let closeTimer: ReturnType<typeof setTimeout> | null = null;

  function close() {
    if (showSettings || closing) return;
    closing = true;
    closeTimer = setTimeout(() => dispatch('close'), DRAWER_EXIT_MS);
  }

  async function openSettings() {
    settingsModule = settingsModule ?? await loadSettingsModal();
    prepareSettingsPresentation();
    showSettings = true;
  }

  function openDanbooru() {
    activeCollectionId.set(null);
    selectedImageId.set(null);
    viewMode.set('home');
    close();
  }

  function openProfile() {
    activeCollectionId.set(null);
    selectedImageId.set(null);
    viewMode.set('profile');
    close();
  }

  function handleKeydown(event: KeyboardEvent) {
    if (event.key === 'Escape') close();
  }

  onDestroy(() => {
    if (closeTimer !== null) clearTimeout(closeTimer);
  });
</script>

<svelte:window on:keydown={handleKeydown} />

<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
<div
  class="app-drawer-layer fixed inset-0 z-[90] bg-black/55"
  class:is-closing={closing}
  on:click={close}
>
  <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions a11y_no_noninteractive_element_interactions -->
  <aside
    class="app-drawer flex h-full w-[min(320px,88vw)] flex-col border-r border-[#313143] bg-[#0c0c12] shadow-2xl shadow-black/70"
    on:click|stopPropagation
  >
    <header class="flex h-[53px] items-center justify-between border-b border-[#292937] px-4">
      <div class="flex items-center gap-2.5">
        <img src="/keivotos-logo.png" alt="" class="h-8 w-8 rounded-lg shadow-[0_0_20px_rgba(85,217,255,0.22)]" />
        <span class="text-lg font-semibold text-purple-100">{SUITE_NAME}</span>
      </div>
      <button
        class="grid h-8 w-8 place-items-center rounded-full border border-[#303040] text-gray-400 transition-colors hover:border-purple-500/50 hover:bg-purple-500/10 hover:text-purple-100"
        type="button"
        title="Close menu"
        aria-label="Close menu"
        on:click={close}
      >
        <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
        </svg>
      </button>
    </header>

    <nav class="flex-1 space-y-1 p-3">
      <button
        class="group flex w-full items-center gap-2.5 rounded-lg px-2 py-2 text-left text-sm font-semibold text-gray-300 transition-colors hover:bg-purple-500/10 hover:text-purple-100"
        type="button"
        on:click={openDanbooru}
      >
        <img src="/logo.svg" alt="" class="h-9 w-9 rounded-lg transition-transform group-hover:scale-105" />
        <span class="min-w-0 flex-1 truncate">{MODULE_DISPLAY_NAME}</span>
        <svg class="h-4 w-4 translate-x-0 text-gray-600 transition-transform group-hover:translate-x-1 group-hover:text-purple-200" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
        </svg>
      </button>

      <div class="flex items-center gap-2.5 rounded-lg px-2 py-2 text-sm font-semibold text-gray-600">
        <span class="grid h-9 w-9 place-items-center rounded-lg bg-[#15151e] text-gray-700">
          <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" d="M12 6v6l4 2m5-2a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
        </span>
        <span>Coming Soon</span>
      </div>
    </nav>

    <footer class="border-t border-[#292937] p-3">
      <div class="flex items-center gap-1">
        <button
          class="group flex min-w-0 flex-1 items-center gap-2.5 rounded-lg px-2 py-2 text-left text-sm font-semibold text-gray-300 transition-colors hover:bg-purple-500/10 hover:text-purple-100"
          type="button"
          on:click={openProfile}
        >
          <img src="/profile-avatar.svg" alt="" class="h-9 w-9 rounded-lg object-cover transition-transform group-hover:scale-105" />
          <span class="truncate">Profile</span>
        </button>
        <button
          class="grid h-9 w-9 shrink-0 place-items-center rounded-lg text-gray-500 transition-colors hover:bg-purple-500/10 hover:text-purple-100"
          type="button"
          title="Settings"
          aria-label="Settings"
          on:click={openSettings}
        >
          <svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" d="M10.3 4.3c.4-1.8 2.9-1.8 3.4 0a1.7 1.7 0 002.6 1.1c1.5-.9 3.3.8 2.4 2.4a1.7 1.7 0 001.1 2.6c1.8.4 1.8 2.9 0 3.4a1.7 1.7 0 00-1.1 2.6c.9 1.5-.8 3.3-2.4 2.4a1.7 1.7 0 00-2.6 1.1c-.4 1.8-2.9 1.8-3.4 0a1.7 1.7 0 00-2.6-1.1c-1.5.9-3.3-.8-2.4-2.4a1.7 1.7 0 00-1.1-2.6c-1.8-.4-1.8-2.9 0-3.4a1.7 1.7 0 001.1-2.6c-.9-1.5.8-3.3 2.4-2.4a1.7 1.7 0 002.6-1.1z" />
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
          </svg>
        </button>
      </div>
    </footer>
  </aside>
</div>

{#if showSettings}
  {#if settingsModule}
    <svelte:component this={settingsModule.default} on:close={() => showSettings = false} />
  {/if}
{/if}

<style>
  .app-drawer {
    animation: drawer-in 220ms cubic-bezier(0.2, 0.8, 0.2, 1) both;
    will-change: transform, opacity;
  }

  .app-drawer-layer {
    animation: drawer-backdrop-in 160ms ease-out both;
  }

  .app-drawer-layer.is-closing {
    animation: drawer-backdrop-out 180ms ease-in both;
    pointer-events: none;
  }

  .app-drawer-layer.is-closing .app-drawer {
    animation: drawer-out 180ms cubic-bezier(0.4, 0, 1, 1) both;
  }

  @keyframes drawer-in {
    from { transform: translate3d(-100%, 0, 0); opacity: 0.86; }
    to { transform: translate3d(0, 0, 0); opacity: 1; }
  }

  @keyframes drawer-out {
    from { transform: translate3d(0, 0, 0); opacity: 1; }
    to { transform: translate3d(-100%, 0, 0); opacity: 0.86; }
  }

  @keyframes drawer-backdrop-in {
    from { opacity: 0; }
    to { opacity: 1; }
  }

  @keyframes drawer-backdrop-out {
    from { opacity: 1; }
    to { opacity: 0; }
  }

  @media (prefers-reduced-motion: reduce) {
    :global(html:not([data-motion='full'])) .app-drawer,
    :global(html:not([data-motion='full'])) .app-drawer-layer,
    :global(html:not([data-motion='full'])) .app-drawer-layer.is-closing,
    :global(html:not([data-motion='full'])) .app-drawer-layer.is-closing .app-drawer {
      animation-duration: 1ms;
    }
  }
</style>
