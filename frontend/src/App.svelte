<script lang="ts">
  import { accentStyle, settingsStyle, accents } from './lib/appearance';
  import { onMount } from 'svelte';
  import { get } from 'svelte/store';
  import './app.css';
  import { SUITE_NAME } from './lib/product';
  import { suiteApi } from './lib/suiteApi';
  import { activeModule, enabledModules, interfaceScale, motionPreference, startupModule, suiteModules, settingsOpen, settingsInitialSection } from './lib/suiteStores';
  import { loadSettingsModal, type SettingsModalModule } from './lib/settingsLoader';
  let settingsModule: SettingsModalModule | null = null;
  let settingsLoading = false;
  let settingsError = '';
  async function showSettings() {
    settingsLoading = true;
    settingsError = '';
    try { settingsModule = await loadSettingsModal(); }
    catch (error) { settingsError = String(error); settingsOpen.set(false); }
    finally { settingsLoading = false; }
  }
  $: if ($settingsOpen && !settingsModule && !settingsLoading) void showSettings();

  import { surfaceComponent } from './modules/surfaces';
  let registryReady = false;
  let registryLoading = false;
  let registryError = '';

  async function initializeModules() {
    if (registryLoading) return;
    registryLoading = true;
    registryError = '';
    try {
      const modules = await suiteApi.listModules();
      const startup = get(startupModule);
      const remembered = get(activeModule);
      const requested = startup === 'last' ? remembered : startup;
      const selected = modules.find(module => module.slug === requested && module.enabled);
      const base = modules.find(module => module.is_base);
      if (!base) throw new Error('Files module is unavailable.');
      activeModule.set(selected?.slug ?? base.slug);
      enabledModules.set(modules.filter(module => module.enabled).map(module => module.id));
      suiteModules.set(modules);
      registryReady = true;
    } catch (error) {
      console.error('Failed to load modules:', error);
      registryError = 'Could not load modules. Retry to open Keivotos.';
    } finally {
      registryLoading = false;
    }
  }

  $: if (typeof document !== 'undefined') {
    document.documentElement.dataset.accent = $accentStyle;
    document.documentElement.dataset.settingsStyle = $settingsStyle;
    document.documentElement.style.setProperty('--accent', accents[$accentStyle].color);
    document.documentElement.style.setProperty('--accent-strong', accents[$accentStyle].strong);
    document.documentElement.dataset.motion = $motionPreference;
    document.documentElement.dataset.interfaceScale = $interfaceScale;
  }

  $: baseDescriptor = $suiteModules.find((module) => module.is_base);
  $: requestedDescriptor = $suiteModules.find((module) => module.slug === $activeModule);
  $: activeDescriptor = requestedDescriptor?.enabled ? requestedDescriptor : baseDescriptor;
  $: ActiveSurface = registryReady ? surfaceComponent(activeDescriptor?.slug ?? 'files') : null;
  $: if (registryReady && activeDescriptor && activeDescriptor.slug !== $activeModule) {
    activeModule.set(activeDescriptor.slug);
  }
  $: if (typeof document !== 'undefined') {
    document.title = activeDescriptor && !activeDescriptor.is_base
      ? `${SUITE_NAME} - ${activeDescriptor.name}`
      : SUITE_NAME;
  }

  onMount(() => { void initializeModules(); });
</script>

<div class="flex flex-col h-screen bg-[#0f0f14] text-gray-200">
  {#if ActiveSurface}
    <svelte:component this={ActiveSurface} />
  {:else if registryError}
    <main class="flex flex-1 items-center justify-center gap-3" role="alert">{registryError}<button type="button" class="rounded-md border border-[#303040] px-3 py-2" on:click={initializeModules}>Retry</button></main>
  {:else}
    <main class="flex flex-1 items-center justify-center text-gray-400" role="status">Opening Keivotos…</main>
  {/if}
</div>

{#if $settingsOpen && settingsModule}
  <svelte:component this={settingsModule.default} initialSection={$settingsInitialSection} on:close={() => settingsOpen.set(false)} />
{/if}
{#if settingsError}
  <div role="alert" class="fixed bottom-4 right-4 z-[200] rounded-lg bg-[#22222e] p-4 text-sm text-red-200">Could not open Settings: {settingsError}<button type="button" class="ml-3" on:click={() => settingsError = ''}>Dismiss</button></div>
{/if}
