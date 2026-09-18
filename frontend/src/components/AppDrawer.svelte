<script lang="ts">
  import { createEventDispatcher, onDestroy, onMount } from 'svelte';
  import { prepareSettingsPresentation } from '../lib/settingsPresentation';
  import { loadSettingsModal, type SettingsModalModule } from '../lib/settingsLoader';
  import { SUITE_NAME, VERSION } from '../lib/product';
  import { activeModule, enabledModules, suiteModules } from '../lib/suiteStores';
  import { suiteApi, type SuiteModule } from '../lib/suiteApi';
  import { activateModule, moduleUi } from '../modules/registry';

  const dispatch = createEventDispatcher<{ close: void }>();
  const DRAWER_EXIT_MS = 180;
  let showSettings = false;
  let settingsModule: SettingsModalModule | null = null;
  let closing = false;
  let closeTimer: ReturnType<typeof setTimeout> | null = null;
  let modules: SuiteModule[] = [];
  let moduleBusy = false;

  $: enabledList = modules.filter((mod) => mod.enabled);
  $: availableList = modules.filter((mod) => mod.disableable && !mod.enabled);
  $: footerActions = enabledList.flatMap((mod) => moduleUi(mod.slug).drawerActions);

  onMount(refreshModules);

  async function refreshModules() {
    try {
      modules = await suiteApi.listModules();
      suiteModules.set(modules);
      enabledModules.set(modules.filter((mod) => mod.enabled).map((mod) => mod.id));
    } catch (e) {
      console.error('Failed to load modules:', e);
    }
  }

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

  function openModule(mod: SuiteModule) {
    activateModule(mod.slug);
    close();
  }

  async function enableModule(mod: SuiteModule) {
    if (moduleBusy) return;
    moduleBusy = true;
    try {
      await suiteApi.enableModule(mod.id);
      await refreshModules();
      openModule(mod); // switch straight into the newly added module
    } catch (e) {
      console.error('Failed to enable module:', e);
    } finally {
      moduleBusy = false;
    }
  }

  async function disableModule(mod: SuiteModule, event: Event) {
    event.stopPropagation();
    if (moduleBusy) return;
    moduleBusy = true;
    try {
      await suiteApi.disableModule(mod.id);
      if ($activeModule === mod.id) activeModule.set('files');
      await refreshModules();
    } catch (e) {
      console.error('Failed to disable module:', e);
    } finally {
      moduleBusy = false;
    }
  }

  function runFooterAction(action: { run: () => void }) {
    action.run();
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
        <div class="flex flex-col leading-none">
          <span class="text-lg font-semibold text-purple-100">{SUITE_NAME}</span>
          <span class="mt-0.5 text-[10px] font-medium tracking-wide text-gray-500">v{VERSION}</span>
        </div>
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

    <nav class="flex-1 space-y-1 overflow-y-auto p-3">
      {#each enabledList as mod (mod.id)}
        <button
          class="group flex w-full items-center gap-2.5 rounded-lg px-2 py-2 text-left text-sm font-semibold transition-colors {$activeModule === mod.id ? 'bg-purple-500/15 text-purple-100' : 'text-gray-300 hover:bg-purple-500/10 hover:text-purple-100'}"
          type="button"
          on:click={() => openModule(mod)}
        >
          {#if moduleUi(mod.slug).iconSrc}
            <img src={moduleUi(mod.slug).iconSrc ?? ''} alt="" class="h-9 w-9 rounded-lg transition-transform group-hover:scale-105" />
          {:else}
            <span class="grid h-9 w-9 place-items-center rounded-lg bg-[#15151e] text-purple-200 transition-transform group-hover:scale-105">
              <svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" d="M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2V7z" />
              </svg>
            </span>
          {/if}
          <span class="min-w-0 flex-1 truncate">{mod.name}</span>
          {#if mod.disableable}
            <span
              role="button"
              tabindex="0"
              title="Disable module (your data is kept)"
              class="px-1 text-gray-600 opacity-0 transition-opacity hover:text-red-400 group-hover:opacity-100"
              on:click={(e) => disableModule(mod, e)}
              on:keydown={(e) => e.key === 'Enter' && disableModule(mod, e)}
            >✕</span>
          {/if}
        </button>
      {/each}

      <!-- Available modules to add -->
      {#if availableList.length}
        <div class="px-2 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-wide text-gray-600">Add a module</div>
        {#each availableList as mod (mod.id)}
          <div class="flex items-center gap-2.5 rounded-lg px-2 py-2 text-sm">
            <span class="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-[#15151e]">
              {#if moduleUi(mod.slug).iconSrc}
                <img src={moduleUi(mod.slug).iconSrc ?? ''} alt="" class="h-6 w-6 rounded opacity-50" />
              {:else}
                <span class="text-gray-600">◇</span>
              {/if}
            </span>
            <span class="min-w-0 flex-1 truncate text-gray-400">{mod.name}</span>
            <button
              class="rounded-md bg-purple-500/20 px-2.5 py-1 text-xs font-medium text-purple-100 transition-colors hover:bg-purple-500/30 disabled:opacity-40"
              type="button"
              on:click={() => enableModule(mod)}
              disabled={moduleBusy}
            >Enable</button>
          </div>
        {/each}
      {/if}

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
        {#each footerActions as action (action.id)}
          <button
            class="group flex min-w-0 flex-1 items-center gap-2.5 rounded-lg px-2 py-2 text-left text-sm font-semibold text-gray-300 transition-colors hover:bg-purple-500/10 hover:text-purple-100"
            type="button"
            on:click={() => runFooterAction(action)}
          >
            <img src={action.iconSrc} alt="" class="h-9 w-9 rounded-lg object-cover transition-transform group-hover:scale-105" />
            <span class="truncate">{action.label}</span>
          </button>
        {/each}
        {#if footerActions.length === 0}
          <div class="min-w-0 flex-1"></div>
        {/if}
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
