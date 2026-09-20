<script lang="ts">
  import { onMount } from 'svelte';
  import { suiteApi, type SuiteModule, type ModuleStatus } from '../lib/suiteApi';
  import { suiteDataApi } from '../lib/suiteDataApi';
  import { suiteModules, enabledModules } from '../lib/suiteStores';
  import { settingsError } from '../lib/http';
  import SettingsSwitch from '../components/SettingsSwitch.svelte';
  let statuses: Record<string, ModuleStatus> = {};
  let planned: {id:string; name:string; experimental:boolean}[] = [];
  let showExperimental = false;
  let busy = '';
  let loading = true;
  let error = '';
  $: visibleModules = $suiteModules.filter(module => !module.experimental || showExperimental || module.enabled);

  async function refresh() {
    const modules = await suiteApi.listModules();
    suiteModules.set(modules);
    enabledModules.set(modules.filter(module => module.enabled).map(module => module.id));
    const results = await Promise.allSettled(modules.map(module => suiteApi.moduleStatus(module.id)));
    statuses = Object.fromEntries(results.flatMap(result => result.status === 'fulfilled' ? [[result.value.id, result.value]] : []));
    const failure = results.find(result => result.status === 'rejected');
    if (failure?.status === 'rejected') error = settingsError(failure.reason, 'Module status');
  }
  async function load() {
    loading = true; error = '';
    const results = await Promise.allSettled([
      refresh(),
      suiteDataApi.getDiagnostics().then(value => showExperimental = value.show_experimental_modules),
      suiteApi.plannedModules().then(value => planned = value),
    ]);
    const names = ['Modules', 'Experimental module preferences', 'Upcoming modules'];
    results.forEach((result, index) => {if (result.status === 'rejected') error ||= settingsError(result.reason, names[index]);});
    loading = false;
  }
  onMount(() => {void load();});
  async function change(module: SuiteModule, retry = false) {
    if (busy) return;
    busy = module.id; error = '';
    try {
      if (retry) await suiteApi.retryModule(module.id);
      else if (module.enabled) await suiteApi.disableModule(module.id);
      else await suiteApi.enableModule(module.id);
    } catch (e) { error = settingsError(e, module.name); }
    finally {try {await refresh();} catch(e){error ||= settingsError(e, 'Modules');} busy = '';}
  }
</script>

<div class="mx-auto max-w-3xl space-y-4" id="setting-modules">
  {#if error}<div role="alert" class="text-xs text-red-300">{error} <button class="ml-2 underline" disabled={loading || !!busy} on:click={load}>Retry</button></div>{/if}
  {#if loading}<p role="status" class="text-xs text-gray-500">Loading modules…</p>{/if}
  <section class="divide-y divide-[#22222e] overflow-hidden rounded-xl border border-[#292938] bg-[#111118]">
    {#each visibleModules as module (module.id)}
      <div class="flex min-h-[52px] items-center justify-between gap-4 px-4 py-3" data-module-id={module.id}>
        <span class="text-sm text-gray-200">{module.name}</span>
        <div class="flex items-center gap-3">
          {#if module.is_base}<span class="text-xs text-gray-500">Always on</span>{/if}
          {#if module.experimental}<span class="text-xs text-gray-500">Experimental</span>{/if}
          {#if statuses[module.id]?.state === 'failed'}<button class="text-xs text-red-300 underline" disabled={!!busy} on:click={() => change(module, true)}>Retry</button>{/if}
          <SettingsSwitch label={`${module.name} module`} checked={module.enabled} disabled={!module.disableable || !!busy || loading} on:click={() => change(module)} />
        </div>
      </div>
      {#if statuses[module.id]?.error}<p role="alert" class="px-4 py-2 text-xs text-red-300">{statuses[module.id].error}</p>{/if}
    {/each}
    {#each planned.filter(module => !module.experimental || showExperimental) as module (module.id)}
      <div class="flex min-h-[52px] items-center justify-between gap-4 px-4 py-3" data-module-id={module.id}>
        <span class="text-sm text-gray-200">{module.name}</span>
        <div class="flex items-center gap-3"><span class="text-xs text-gray-500">{module.experimental ? 'Experimental · Coming soon' : 'Coming soon'}</span><SettingsSwitch label={`${module.name} module`} disabled /></div>
      </div>
    {/each}
  </section>
</div>
