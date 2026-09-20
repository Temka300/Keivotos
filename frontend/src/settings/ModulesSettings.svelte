<script lang="ts">
  import { onMount } from 'svelte';
  import { suiteApi, type SuiteModule, type ModuleStatus } from '../lib/suiteApi';
  import { suiteDataApi } from '../lib/suiteDataApi';
  import { suiteModules, enabledModules } from '../lib/suiteStores';
  let statuses: Record<string, ModuleStatus> = {};
  let showExperimental = false;
  let busy = '';
  let loading = true;
  let error = '';
  $: visibleModules = $suiteModules.filter(module => !module.experimental || showExperimental || module.enabled);

  async function refresh() {
    const modules = await suiteApi.listModules();
    suiteModules.set(modules);
    enabledModules.set(modules.filter(module => module.enabled).map(module => module.id));
    const results = await Promise.all(modules.map(module => suiteApi.moduleStatus(module.id)));
    statuses = Object.fromEntries(results.map(status => [status.id, status]));
  }
  onMount(() => {
    void (async () => {
      try {
        const preferences = await suiteDataApi.getDiagnostics();
        showExperimental = preferences.show_experimental_modules;
        await refresh();
      } catch (e) { error = String(e); }
      finally { loading = false; }
    })();
  });

  async function change(module: SuiteModule, retry = false) {
    if (busy) return;
    busy = module.id;
    error = '';
    try {
      if (retry) await suiteApi.retryModule(module.id);
      else if (module.enabled) await suiteApi.disableModule(module.id);
      else await suiteApi.enableModule(module.id);
    } catch (e) { error = String(e); }
    finally {
      try { await refresh(); } catch (e) { error ||= String(e); }
      busy = '';
    }
  }
</script>

<div class="mx-auto max-w-3xl space-y-4" id="setting-modules">
  <p class="text-sm text-gray-400">Choose which modules appear in Keivotos. Turning a module off keeps its data.</p>
  {#if error}<p role="alert" class="text-sm text-red-300">{error}</p>{/if}
  {#if loading}<p role="status" class="text-sm text-gray-400">Loading modules…</p>{/if}
  <section class="divide-y divide-[#22222e] overflow-hidden rounded-xl border border-[#292938] bg-[#111118]">
    {#each visibleModules as module (module.id)}
      <div class="flex items-center justify-between gap-5 px-4 py-4" data-module-id={module.id}>
        <div class="min-w-0">
          <div class="text-sm font-medium text-gray-200">{module.name}{#if module.experimental}<span class="ml-2 text-xs text-gray-400">Experimental</span>{/if}</div>
          <p class="mt-1 text-xs text-gray-500">{module.description}</p>
          <p class="mt-1 text-xs text-gray-400" role="status">{busy === module.id ? 'Updating…' : module.is_base ? 'Always on' : statuses[module.id]?.state ?? (module.enabled ? 'Enabled' : 'Disabled')}</p>
          {#if statuses[module.id]?.error}<p class="mt-1 text-xs text-red-300">{statuses[module.id].error}</p>{/if}
        </div>
        <div class="flex shrink-0 items-center gap-3">
          {#if module.enabled && statuses[module.id]?.state === 'failed'}
            <button type="button" class="rounded-lg border border-[#303040] px-3 py-2 text-xs text-gray-200" disabled={!!busy} on:click={() => change(module, true)}>Retry</button>
          {/if}
          <button type="button" role="switch" aria-label={`${module.name} module`} aria-checked={module.enabled} disabled={!module.disableable || !!busy || loading} on:click={() => change(module)} class="min-w-[56px] rounded-lg border border-[#303040] px-3 py-2 text-xs font-medium disabled:opacity-50 {module.enabled ? 'bg-purple-500/20 text-purple-100' : 'text-gray-400'}">{module.enabled ? 'On' : 'Off'}</button>
        </div>
      </div>
    {/each}
  </section>
  <p class="text-xs text-gray-500">Experimental modules can be shown in General → Advanced.</p>
</div>
