<script lang="ts">
  import { onMount } from 'svelte';
  import { api, type ThumbnailCacheStatus } from '../lib/api';

  let status: ThumbnailCacheStatus | null = null;
  let limitGb = 10;
  let busy = false;
  let message = '';
  let error = '';

  const formatBytes = (value: number) => value >= 1024 ** 3 ? `${(value / 1024 ** 3).toFixed(2)} GB` : value >= 1024 ** 2 ? `${(value / 1024 ** 2).toFixed(1)} MB` : `${Math.round(value / 1024)} KB`;

  async function load() {
    status = await api.getThumbnailCache();
    limitGb = Math.max(1, Math.round(status.limit_bytes / 1024 ** 3));
  }

  async function run(action: 'cleanup' | 'clear') {
    if (busy || (action === 'clear' && !confirm('Clear every derived thumbnail? Originals, sidecars, and databases will not be touched.'))) return;
    busy = true;
    error = '';
    try {
      const result = action === 'cleanup' ? await api.cleanupThumbnailCache() : await api.clearThumbnailCache();
      status = result;
      message = action === 'cleanup' ? `Removed ${result.removed} stale thumbnail files.` : `Cleared ${result.removed} thumbnail files.`;
    } catch (caught) {
      error = caught instanceof Error ? caught.message : 'Thumbnail cleanup failed.';
    } finally {
      busy = false;
    }
  }

  async function saveLimit() {
    if (busy) return;
    busy = true;
    error = '';
    try {
      status = await api.setThumbnailCacheLimit(limitGb);
      message = `Thumbnail cache limit set to ${limitGb} GB.`;
    } catch (caught) {
      error = caught instanceof Error ? caught.message : 'Could not save the thumbnail cache limit.';
    } finally {
      busy = false;
    }
  }

  onMount(() => {
    void load().catch(caught => error = caught instanceof Error ? caught.message : 'Could not load thumbnail cache.');
  });
</script>

<section id="setting-thumbnail-cache" class="overflow-hidden rounded-xl border border-[#292938] bg-[#111118]">
  <div class="flex flex-wrap items-start justify-between gap-4 border-b border-[#242432] p-4"><h4 class="text-sm font-semibold text-gray-200">Thumbnail cache · 300 / 600 / 1200px</h4><div class="text-right"><div class="text-sm font-semibold text-cyan-200">{formatBytes(status?.bytes ?? 0)}</div><div class="text-[10px] text-gray-600">{status?.files ?? 0} files · {status?.legacy_files ?? 0} stale</div></div></div>
  <div class="grid grid-cols-3 divide-x divide-[#242432] border-b border-[#242432] bg-black/10 text-center">{#each ['300', '600', '1200'] as tier}<div class="px-3 py-3"><div class="text-xs font-semibold text-gray-300">{tier}px</div><div class="mt-0.5 text-[10px] text-gray-600">{status?.tiers[tier] ?? 0} cached</div></div>{/each}</div>
  <div class="flex flex-wrap items-center justify-between gap-3 p-4"><label class="flex items-center gap-2 text-xs text-gray-500"><span>Maximum</span><select class="rounded-lg border border-[#303040] bg-[#0d0d13] px-2 py-1.5 text-xs text-gray-200" bind:value={limitGb} on:change={saveLimit}>{#each [2, 5, 10, 20, 50] as value}<option value={value}>{value} GB</option>{/each}</select></label><div class="flex gap-2"><button class="rounded-lg border border-cyan-400/15 px-3 py-2 text-xs text-cyan-200 hover:bg-cyan-500/10 disabled:opacity-40" type="button" disabled={busy} on:click={() => run('cleanup')}>Remove stale</button><button class="rounded-lg border border-red-400/15 px-3 py-2 text-xs text-red-300 hover:bg-red-500/10 disabled:opacity-40" type="button" disabled={busy} on:click={() => run('clear')}>Clear all</button></div></div>
</section>
{#if message}<p class="rounded-xl border border-green-400/15 bg-green-500/[0.05] px-4 py-3 text-xs text-green-300">{message}</p>{/if}
{#if error}<p class="rounded-xl border border-red-400/15 bg-red-500/[0.05] px-4 py-3 text-xs text-red-300">{error}</p>{/if}
