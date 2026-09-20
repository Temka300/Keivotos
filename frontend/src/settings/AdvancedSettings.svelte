<script lang="ts">
  import SettingsSwitch from '../components/SettingsSwitch.svelte';
  import { settingsError } from '../lib/http';
  import { onMount } from 'svelte';
  import { suiteDataApi } from '../lib/suiteDataApi';
  import type { DiagnosticsPreferences } from '../lib/suiteApiTypes';
  let preferences: DiagnosticsPreferences | null = null;
  let busy = false;
  let error = '';
  let notice = '';
  let loading = false;
  async function load() {
    loading = true; error = '';
    try { preferences = await suiteDataApi.getDiagnostics(); }
    catch (caught) { error = settingsError(caught, 'Diagnostic preferences'); }
    loading = false;
  }
  onMount(() => {void load();});
  async function toggle(key: keyof DiagnosticsPreferences) {
    if (!preferences || busy) return;
    const previous = preferences;
    preferences = { ...preferences, [key]: !preferences[key] };
    busy = true; error = ''; notice = '';
    try { preferences = await suiteDataApi.configureDiagnostics(preferences); }
    catch (e) { preferences = previous; error = settingsError(e, 'Diagnostics'); }
    finally { busy = false; }
  }
  async function open(target: 'data' | 'logs' | 'runtime' | 'access') {
    busy = true; error = ''; notice = '';
    try { await suiteDataApi.openDiagnostics(target); notice = 'Opened with your desktop application.'; }
    catch (e) { error = settingsError(e, 'Diagnostics'); }
    finally { busy = false; }
  }
</script>

<div class="mx-auto max-w-3xl space-y-4" id="setting-diagnostics">
  {#if error}<p role="alert" class="text-sm text-red-300">{error} <button class="ml-2 underline" disabled={loading || busy} on:click={load}>Retry</button></p>{/if}
  {#if notice}<p role="status" class="text-sm text-gray-400">{notice}</p>{/if}
  <section class="space-y-4 rounded-xl border border-[#292938] bg-[#111118] p-4">
    <div class="flex flex-wrap gap-2">
      {#each [{ target: 'data' as const, label: 'Open data folder' }, { target: 'logs' as const, label: 'Open logs folder' }, { target: 'runtime' as const, label: 'Open application log' }, { target: 'access' as const, label: 'Open request log' }] as item}
        <button type="button" disabled={busy} on:click={() => open(item.target)} class="rounded-lg border border-[#303040] px-3 py-2 text-xs text-gray-200 hover:bg-[#1a1a23] disabled:opacity-50">{item.label}</button>
      {/each}
    </div>
  </section>
  {#if preferences}
    <section class="divide-y divide-[#22222e] overflow-hidden rounded-xl border border-[#292938] bg-[#111118]">
      {#each [{ key: 'verbose_logging' as const, label: 'Verbose logging', description: 'Also show successful read requests in the console and application log. Applies immediately.' }, { key: 'show_experimental_modules' as const, label: 'Show experimental modules', description: 'Show experimental choices in Modules. Enabled modules stay visible.' }] as option}
        <div class="flex items-center justify-between gap-5 px-4 py-3">
          <div><div class="text-sm font-medium text-gray-200">{option.label}</div><p class="mt-1 text-xs text-gray-500">{option.description}</p></div>
          <SettingsSwitch label={option.label} checked={preferences[option.key]} disabled={busy} on:click={() => toggle(option.key)} />
        </div>
      {/each}
    </section>
  {/if}
</div>
