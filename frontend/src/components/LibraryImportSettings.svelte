<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { api, type AutomationStatus, type ImportPhase, type ImportPipelineStatus, type StorageConfiguration, type ToolFileResult } from '../lib/api';

  export let toolRunning = false;
  export let surface: 'storage' | 'metadata' = 'metadata';

  let storage: StorageConfiguration | null = null;
  let pipeline: ImportPipelineStatus | null = null;
  let automation: AutomationStatus | null = null;
  let intervalMinutes = 15;
  let metadataLimit = 0;
  let busy = false;
  let message = '';
  let error = '';
  let pollTimer: ReturnType<typeof setTimeout> | null = null;
  let pollRequestActive = false;

  type PhaseCountKey = 'discovered' | 'enriched' | 'metadata' | 'finalized';
  const phases: { id: Exclude<ImportPhase, 'all'>; counter: PhaseCountKey; number: number; label: string; description: string; network?: boolean }[] = [
    { id: 'discover', counter: 'discovered', number: 1, label: 'Discover', description: 'Inventory paths, sizes, and dates without opening image contents.' },
    { id: 'enrich', counter: 'enriched', number: 2, label: 'Enrich locally', description: 'Hash once and read dimensions with three bounded workers.' },
    { id: 'metadata', counter: 'metadata', number: 3, label: 'Match metadata', description: 'Use stored hashes for rate-limited Danbooru lookups.', network: true },
    { id: 'finalize', counter: 'finalized', number: 4, label: 'Finalize', description: 'Import sidecars, reconcile removals, and finish the incremental index.' },
  ];

  $: importRunning = pipeline?.task.status === 'running' || pipeline?.task.status === 'cancelling';
  $: recentResults = [...(pipeline?.task.file_results ?? [])].reverse();

  function pipelineTaskRunning() {
    return pipeline?.task.status === 'running' || pipeline?.task.status === 'cancelling';
  }

  function stopPipelinePolling() {
    if (pollTimer) clearTimeout(pollTimer);
    pollTimer = null;
  }

  function schedulePipelinePoll(delay = 1200) {
    if (surface !== 'metadata' || pollTimer || !pipelineTaskRunning()) return;
    pollTimer = setTimeout(() => {
      pollTimer = null;
      void pollPipelineTask();
    }, delay);
  }

  function resultLabel(result: ToolFileResult): string {
    if (result.status === 'matched') return 'Matched';
    if (result.status === 'no_match') return 'No match';
    return 'Failed';
  }

  function resultClass(status: ToolFileResult['status']): string {
    if (status === 'matched') return 'border-green-400/15 bg-green-500/[0.05] text-green-300';
    if (status === 'no_match') return 'border-amber-400/15 bg-amber-500/[0.05] text-amber-300';
    return 'border-red-400/15 bg-red-500/[0.05] text-red-300';
  }

  async function load() {
    try {
      if (surface === 'storage') {
        storage = await api.getStorageConfiguration();
      } else {
        [pipeline, automation] = await Promise.all([api.getImportPipeline(), api.getAutomation()]);
        intervalMinutes = automation.interval_minutes;
        schedulePipelinePoll();
      }
    } catch (caught) {
      error = caught instanceof Error ? caught.message : 'Could not load storage and import settings.';
    }
  }

  async function refreshPipeline() {
    if (surface !== 'metadata') return;
    try {
      pipeline = await api.getImportPipeline();
      if (pipelineTaskRunning()) schedulePipelinePoll();
    } catch {
      // Keep the last readable phase state while a restart is in progress.
    }
  }

  async function pollPipelineTask() {
    if (surface !== 'metadata' || pollRequestActive || !pipeline) return;
    pollRequestActive = true;
    try {
      const previousResults = pipeline.task.file_results ?? [];
      const afterIndex = previousResults.reduce((highest, result) => Math.max(highest, result.index ?? 0), 0);
      const task = await api.getImportTask(afterIndex || undefined);
      const fileResults = [...previousResults, ...(task.file_results ?? [])].slice(-250);
      pipeline = { ...pipeline, task: { ...task, file_results: fileResults } };
      if (task.status === 'running' || task.status === 'cancelling') {
        schedulePipelinePoll();
      } else {
        // Phase totals only need a full database recount when the job stops.
        await refreshPipeline();
      }
    } catch {
      // Keep the last readable state and retry only while the job was active.
      schedulePipelinePoll(1800);
    } finally {
      pollRequestActive = false;
    }
  }

  async function runPhase(phase: ImportPhase) {
    if (busy || importRunning || toolRunning) return;
    const needsNetwork = phase === 'metadata' || phase === 'all';
    if (needsNetwork && !confirm('Phase 3 sends rate-limited MD5 metadata requests to Danbooru. No images are downloaded. Continue?')) return;
    busy = true;
    error = '';
    message = '';
    try {
      await api.runImport(phase, undefined, metadataLimit || undefined, needsNetwork);
      await refreshPipeline();
      schedulePipelinePoll(250);
      message = phase === 'all' ? 'All four import phases started.' : `${phases.find(item => item.id === phase)?.label ?? phase} started.`;
    } catch (caught) {
      error = caught instanceof Error ? caught.message : 'Could not start the import phase.';
    } finally {
      busy = false;
    }
  }

  async function cancelImport() {
    error = '';
    try {
      await api.cancelImport();
      await refreshPipeline();
      schedulePipelinePoll(250);
      message = 'Import cancellation requested.';
    } catch (caught) {
      error = caught instanceof Error ? caught.message : 'Could not cancel the import.';
    }
  }

  async function saveAutomation(enabled = automation?.enabled ?? false) {
    if (busy) return;
    busy = true;
    error = '';
    try {
      automation = await api.setAutomation(enabled, intervalMinutes);
      message = enabled
        ? `Local watcher enabled every ${automation.interval_minutes} minutes. It will not contact Danbooru.`
        : 'Local watcher disabled.';
    } catch (caught) {
      error = caught instanceof Error ? caught.message : 'Could not update the watcher.';
    } finally {
      busy = false;
    }
  }

  onMount(() => {
    void load();
  });

  onDestroy(() => {
    stopPipelinePolling();
  });
</script>

{#if surface === 'storage'}
  <section id="setting-storage-location" class="overflow-hidden rounded-2xl border border-cyan-400/20 bg-[radial-gradient(circle_at_88%_0%,rgba(34,211,238,.14),transparent_42%),linear-gradient(135deg,#101b20,#101017_72%)] p-4">
    <div class="rounded-xl border border-cyan-300/10 bg-black/20 px-3 py-3">
      <div class="flex items-center justify-between gap-3"><span class="text-[11px] font-semibold uppercase tracking-wider text-gray-500">Generated files</span><span class="rounded-full bg-cyan-500/10 px-2 py-0.5 text-[10px] uppercase text-cyan-300">{storage?.mode ?? 'loading'}</span></div>
      <div class="mt-1 break-all font-mono text-xs text-cyan-100/80">{storage?.metadata_dir ?? 'Loading…'}</div>
    </div>
    <div class="mt-2 overflow-hidden rounded-xl border border-white/5 bg-black/10">
      <div class="border-b border-white/5 px-3 py-2.5">
        <div class="flex flex-wrap items-baseline justify-between gap-2">
          <div class="text-[10px] font-semibold uppercase tracking-wider text-gray-500">Runtime log</div>
          <div class="text-[10px] text-gray-600">Startup, changes, background work, warnings, errors</div>
        </div>
        <div class="mt-1 break-all font-mono text-[11px] text-gray-400">{storage?.runtime_log_file ?? 'Loading…'}</div>
      </div>
      <div class="px-3 py-2.5">
        <div class="flex flex-wrap items-baseline justify-between gap-2">
          <div class="text-[10px] font-semibold uppercase tracking-wider text-gray-500">HTTP access log</div>
          <div class="text-[10px] text-gray-600">Every local request: method, path, status</div>
        </div>
        <div class="mt-1 break-all font-mono text-[11px] text-gray-400">{storage?.access_log_file ?? 'Loading…'}</div>
      </div>
      <div class="border-t border-white/5 px-3 py-2 text-[10px] text-gray-600">
        Dated per launch · {storage?.log_retention_files ?? 30} recent files kept per type
      </div>
    </div>
  </section>
{:else}
  <section id="setting-import-pipeline" class="overflow-hidden rounded-xl border border-[#292938] bg-[#111118]">
    <div class="border-b border-[#242432] p-4">
      <div class="flex flex-wrap items-start justify-between gap-4">
        <h4 class="text-sm font-semibold text-gray-200">Four-phase import pipeline</h4>
        <button class="rounded-xl bg-purple-500/20 px-3.5 py-2 text-xs font-semibold text-purple-100 ring-1 ring-inset ring-purple-300/15 hover:bg-purple-500/30 disabled:opacity-40" type="button" disabled={busy || importRunning || toolRunning} on:click={() => runPhase('all')}>Run all four phases</button>
      </div>
    </div>

    {#if pipeline}
      <div class="grid gap-2 p-3 sm:grid-cols-2">
        {#each phases as phase}
          <div class="rounded-xl border border-white/5 bg-black/15 p-3">
            <div class="flex items-start gap-3"><span class="grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-purple-500/10 text-xs font-bold text-purple-300">{phase.number}</span><div class="min-w-0 flex-1"><div class="flex items-center gap-2 text-sm font-semibold text-gray-200">{phase.label}{#if phase.network}<span class="rounded-full bg-amber-500/10 px-1.5 py-0.5 text-[9px] text-amber-300">NETWORK</span>{/if}</div><p class="mt-0.5 text-xs leading-relaxed text-gray-500">{phase.description}</p></div></div>
            <div class="mt-3 flex items-center justify-between"><span class="text-[10px] text-gray-600">{pipeline.phases[phase.counter].toLocaleString()} complete</span><button class="rounded-lg border border-purple-400/15 px-2.5 py-1.5 text-[11px] text-purple-200 hover:bg-purple-500/10 disabled:opacity-40" type="button" disabled={busy || importRunning || toolRunning} on:click={() => runPhase(phase.id)}>Run phase</button></div>
          </div>
        {/each}
      </div>
      <div class="flex flex-wrap items-center justify-between gap-3 border-t border-[#242432] bg-black/10 px-4 py-3">
        <label class="flex items-center gap-2 text-xs text-gray-500"><span>Phase 3 limit</span><input class="w-24 rounded-lg border border-[#303040] bg-[#0d0d13] px-2 py-1.5 text-xs text-gray-200" type="number" min="0" max="1000000" title="0 means every missing sidecar" bind:value={metadataLimit} /></label>
        {#if importRunning}<button class="rounded-lg border border-red-400/20 px-3 py-2 text-xs text-red-300 hover:bg-red-500/10" type="button" on:click={cancelImport}>Cancel</button>{/if}
      </div>

      {#if pipeline.task.status !== 'idle'}
        <div class="border-t border-[#242432] bg-[#0d0d13] p-4">
          {#if pipeline.task.current_file}
            <div class="mb-3 rounded-xl border border-purple-300/10 bg-purple-500/[0.06] px-3 py-2.5">
              <div class="text-[9px] font-semibold uppercase tracking-[0.18em] text-purple-300/65">{pipeline.task.current_file_status === 'working' ? 'Current file' : 'Latest file'}</div>
              <div class="mt-1 truncate font-mono text-xs text-purple-100" title={pipeline.task.current_file_path ?? pipeline.task.current_file}>{pipeline.task.current_file}</div>
            </div>
          {/if}
          <div class="flex items-center justify-between gap-3 text-xs"><span class="font-semibold {pipeline.task.status === 'error' ? 'text-red-300' : pipeline.task.status === 'done' ? 'text-green-300' : pipeline.task.status === 'cancelled' ? 'text-amber-300' : 'text-purple-200'}">{pipeline.task.stage ?? 'Import'} · {pipeline.task.status}</span><span class="text-gray-500">{pipeline.task.progress ?? 0} / {pipeline.task.total ?? 0}</span></div>
          {#if pipeline.task.total}<div class="mt-2 h-1.5 overflow-hidden rounded-full bg-[#20202b]"><div class="h-full rounded-full bg-purple-400 transition-all" style="width: {Math.min(100, ((pipeline.task.progress ?? 0) / pipeline.task.total) * 100)}%"></div></div>{/if}
          <div class="mt-3 flex flex-wrap gap-2 text-[10px]"><span class="rounded-full bg-green-500/10 px-2 py-1 text-green-300">{pipeline.task.result_counts?.matched ?? 0} matched</span><span class="rounded-full bg-amber-500/10 px-2 py-1 text-amber-300">{pipeline.task.result_counts?.no_match ?? 0} no match</span><span class="rounded-full bg-red-500/10 px-2 py-1 text-red-300">{pipeline.task.result_counts?.error ?? 0} failed</span></div>
          {#if recentResults.length}
            <div class="mt-3 max-h-64 space-y-1.5 overflow-y-auto pr-1">
              {#each recentResults as result (`${result.path}:${result.index ?? ''}:${result.status}`)}
                <div class="flex items-start gap-2 rounded-lg border px-2.5 py-2 {resultClass(result.status)}"><span class="w-14 shrink-0 text-[10px] font-semibold uppercase">{resultLabel(result)}</span><div class="min-w-0 flex-1"><div class="truncate font-mono text-[11px] text-gray-200" title={result.path}>{result.filename}</div>{#if result.detail}<div class="mt-0.5 truncate text-[10px] opacity-65" title={result.detail}>{result.detail}</div>{/if}</div></div>
              {/each}
            </div>
          {/if}
          {#if pipeline.task.output}<details class="mt-3 border-t border-white/5 pt-2"><summary class="cursor-pointer text-[10px] text-gray-600 hover:text-gray-400">Console details</summary><pre class="mt-2 max-h-40 overflow-auto whitespace-pre-wrap font-mono text-[10px] leading-relaxed text-gray-600">{pipeline.task.output}</pre></details>{/if}
        </div>
      {/if}
    {:else}
      <div class="p-4 text-sm text-gray-500">Loading import pipeline…</div>
    {/if}
  </section>

  <section id="setting-automation" class="overflow-hidden rounded-xl border border-[#292938] bg-[#111118]">
    <div class="flex items-center justify-between gap-4 p-4"><h4 class="text-sm font-semibold text-gray-200">Local file watcher <span class="ml-1 text-xs font-normal text-cyan-300">No Danbooru</span></h4><button class="relative h-6 w-11 shrink-0 rounded-full transition-colors {automation?.enabled ? 'bg-cyan-500' : 'bg-[#2a2a3a]'}" type="button" role="switch" aria-label="Toggle local library watcher" aria-checked={automation?.enabled ?? false} disabled={busy || toolRunning} on:click={() => saveAutomation(!(automation?.enabled ?? false))}><span class="absolute left-0.5 top-0.5 h-5 w-5 rounded-full bg-white transition-transform {automation?.enabled ? 'translate-x-5' : ''}"></span></button></div>
    <div class="flex flex-wrap items-center justify-between gap-3 border-t border-[#242432] bg-black/10 px-4 py-3"><label class="flex items-center gap-2 text-xs text-gray-500"><span>Check every</span><select class="rounded-lg border border-[#303040] bg-[#0d0d13] px-2 py-1.5 text-xs text-gray-200" bind:value={intervalMinutes} on:change={() => saveAutomation()}>{#each [5, 15, 30, 60] as minutes}<option value={minutes}>{minutes} minutes</option>{/each}</select></label><span class="text-[11px] text-gray-600">Latest check: {automation?.candidate_count ?? 0} changed candidate{automation?.candidate_count === 1 ? '' : 's'}</span></div>
  </section>
{/if}

{#if message}<p class="rounded-xl border border-green-400/15 bg-green-500/[0.05] px-4 py-3 text-xs text-green-300">{message}</p>{/if}
{#if error}<p class="rounded-xl border border-red-400/15 bg-red-500/[0.05] px-4 py-3 text-xs text-red-300">{error}</p>{/if}
