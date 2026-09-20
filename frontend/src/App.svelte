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
  $: ActiveSurface = surfaceComponent(activeDescriptor?.slug ?? 'files');
  $: if (activeDescriptor && activeDescriptor.slug !== $activeModule) {
    activeModule.set(activeDescriptor.slug);
  }
  $: if (typeof document !== 'undefined') {
    document.title = activeDescriptor && !activeDescriptor.is_base
      ? `${SUITE_NAME} - ${activeDescriptor.name}`
      : SUITE_NAME;
  }

  onMount(async () => {
    try {
      const modules = await suiteApi.listModules();
      suiteModules.set(modules);
      enabledModules.set(modules.filter((m) => m.enabled).map((m) => m.id));
      // Apply the startup-destination preference now that the registry is known.
      // 'last' keeps the persisted activeModule; an explicit choice wins, and an
      // unavailable module quietly falls back to the always-on base.
      const startup = get(startupModule);
      if (startup !== 'last') {
        const target = modules.find((m) => m.slug === startup && m.enabled);
        activeModule.set(target ? target.slug : 'files');
      }
    } catch (e) {
      console.error('Failed to load modules:', e);
    }
  });
</script>

<div class="flex flex-col h-screen bg-[#0f0f14] text-gray-200">
  <svelte:component this={ActiveSurface} />
</div>

{#if $settingsOpen && settingsModule}
  <svelte:component this={settingsModule.default} initialSection={$settingsInitialSection} on:close={() => settingsOpen.set(false)} />
{/if}
{#if settingsError}
  <div role="alert" class="fixed bottom-4 right-4 z-[200] rounded-lg bg-[#22222e] p-4 text-sm text-red-200">Could not open Settings: {settingsError}<button type="button" class="ml-3" on:click={() => settingsError = ''}>Dismiss</button></div>
{/if}
