<script lang="ts">
  import { onMount } from 'svelte';
  import './app.css';
  import { SUITE_NAME } from './lib/product';
  import { suiteApi } from './lib/suiteApi';
  import { activeModule, enabledModules, interfaceScale, motionPreference, suiteModules } from './lib/stores';
  import { surfaceComponent } from './modules/surfaces';

  $: if (typeof document !== 'undefined') {
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
    } catch (e) {
      console.error('Failed to load modules:', e);
    }
  });
</script>

<div class="flex flex-col h-screen bg-[#0f0f14] text-gray-200">
  <svelte:component this={ActiveSurface} />
</div>
