<script lang="ts">
  import { onMount } from 'svelte';
  import { api, type BackupComponents, type BackupConfiguration, type BackupEstimate, type BackupManifest, type LocalRecoveryStatus } from '../lib/api';
  import { SUITE_NAME } from '../lib/product';
  import { suiteModules } from '../lib/stores';

  export let toolRunning = false;

  let configuration: BackupConfiguration | null = null;
  let destination = '';
  let components: BackupComponents = {
    user_database: true,
    library_database: true,
    sidecars: true,
    sidecar_history: false,
    artist_profile_archive: false,
    file_attachments: true,
  };
  let estimate: BackupEstimate | null = null;
  let selectedBackup = '';
  let inspected: BackupManifest | null = null;
  let localRecovery: LocalRecoveryStatus | null = null;
  let busy = false;
  let saving = false;
  let estimateRequest = 0;
  let inspectionRequest = 0;
  let message = '';
  let error = '';
  let backupMessage = '';
  let backupError = '';

  const choices: { key: keyof BackupComponents; label: string; description: string; recommended?: boolean }[] = [
    { key: 'user_database', label: 'User database', description: 'Suite settings, registered folders, Files origin notes, and module data such as favorites, collections, tags and follows.', recommended: true },
    { key: 'library_database', label: 'Library database', description: 'Immediate searchable index for a fast restore.', recommended: true },
    { key: 'sidecars', label: 'Current sidecars', description: 'Durable metadata used to rebuild the library database.', recommended: true },
    { key: 'sidecar_history', label: 'Sidecar history', description: 'Archived metadata versions from manual refreshes.' },
    { key: 'artist_profile_archive', label: 'Artist profile archive', description: 'Locally preserved artist avatars and banners.' },
    { key: 'file_attachments', label: 'File attachments', description: 'Screenshots and clips you attached to files, so they survive a lost source folder.', recommended: true },
  ];

  function componentLabel(key: string) {
    return choices.find(choice => choice.key === key)?.label ?? key.replaceAll('_', ' ');
  }

  function ownerLabel(owner: string) {
    return owner === 'suite' ? SUITE_NAME : $suiteModules.find(module => module.slug === owner)?.name ?? owner;
  }

  $: availableChoices = Object.keys(configuration?.components ?? {}).map(key => ({
    key,
    label: componentLabel(key),
    description: choices.find(choice => choice.key === key)?.description ?? 'Preserved data contributed by this module.',
    recommended: choices.find(choice => choice.key === key)?.recommended ?? false,
    owner: ownerLabel(configuration?.estimate.details[key]?.owner ?? 'suite'),
  }));
  $: includedLabels = inspected ? Object.entries(inspected.components)
    .filter(([, included]) => included).map(([key]) => componentLabel(key)) : [];

  function applyConfiguration(value: BackupConfiguration) {
    configuration = value;
    destination = value.destination;
    estimateRequest++;
    components = { ...value.components };
    estimate = value.estimate;
    if (!selectedBackup && value.backups.length) selectedBackup = value.backups[0].name;
  }

  async function load() {
    try {
      const [backup, recovery] = await Promise.all([
        api.getBackupConfiguration(),
        api.getLocalRecovery(),
      ]);
      applyConfiguration(backup);
      localRecovery = recovery;
    } catch (caught) {
      error = caught instanceof Error ? caught.message : 'Could not load backup settings.';
    }
  }

  async function createCheckpoint() {
    if (busy || saving || toolRunning || !configuration) return;
    busy = true;
    error = '';
    message = '';
    try {
      const result = await api.createLocalRecoveryCheckpoint();
      localRecovery = result;
      message = result.message;
    } catch (caught) {
      error = caught instanceof Error ? caught.message : 'Could not create a local recovery checkpoint.';
    } finally {
      busy = false;
    }
  }

  async function refreshEstimate() {
    const request = ++estimateRequest;
    try {
      const result = await api.estimateBackup({ ...components });
      if (request === estimateRequest) estimate = result;
    } catch (caught) {
      if (request === estimateRequest) backupError = caught instanceof Error ? caught.message : 'Could not estimate backup size.';
    }
  }

  async function toggleComponent(key: keyof BackupComponents) {
    if (busy || saving || toolRunning) return;
    backupMessage = '';
    backupError = '';
    components = { ...components, [key]: !components[key] };
    await refreshEstimate();
  }

  async function saveConfiguration(showMessage = true): Promise<boolean> {
    if (saving || (showMessage && (busy || toolRunning))) return false;
    saving = true;
    backupError = '';
    if (showMessage) backupMessage = '';
    try {
      applyConfiguration(await api.configureBackups(components));
      if (showMessage) backupMessage = 'Backup contents saved.';
      return true;
    } catch (caught) {
      backupError = caught instanceof Error ? caught.message : 'Could not save backup settings.';
      return false;
    } finally {
      saving = false;
    }
  }

  async function createBackup() {
    if (busy || saving || toolRunning || !configuration) return;
    busy = true;
    backupError = '';
    backupMessage = '';
    try {
      if (!(await saveConfiguration(false))) return;
      const result = await api.createMetadataBackup(components);
      backupMessage = `Created ${result.name} (${result.display_size}) in ${destination}. ${result.message}`;
      await load();
      selectedBackup = result.name;
    } catch (caught) {
      backupError = caught instanceof Error ? caught.message : 'Backup failed.';
    } finally {
      busy = false;
    }
  }

  async function inspectSelected(): Promise<boolean> {
    const name = selectedBackup;
    const request = ++inspectionRequest;
    inspected = null;
    error = '';
    try {
      const result = name ? await api.inspectMetadataBackup(name) : null;
      if (request !== inspectionRequest || name !== selectedBackup) return false;
      inspected = result;
      return result !== null;
    } catch (caught) {
      if (request === inspectionRequest) error = caught instanceof Error ? caught.message : 'Could not inspect this backup.';
      return false;
    }
  }

  async function restoreSelected() {
    if (!selectedBackup || busy || saving || toolRunning) return;
    busy = true;
    error = '';
    message = '';
    try {
      if (!(await inspectSelected()) || !inspected) return;
      const wholeDatabase = inspected.components.user_database
        ? ' This replaces the whole shared user database, including suite settings, Files origin notes and every module’s user data. It cannot restore one module’s tables separately.'
        : '';
      if (!confirm(`Restore ${selectedBackup}? Included: ${includedLabels.join(', ')}.${wholeDatabase} ${SUITE_NAME} will preserve current metadata in a rollback folder. Original media will not be changed. Browser preferences will not be restored.`)) return;
      const result = await api.restoreMetadataBackup(selectedBackup);
      message = `${result.message} Rollback: ${result.rollback_path}`;
      if (result.attachments) {
        const a = result.attachments;
        message += ` Attachments: ${a.restored} restored, ${a.existing} already present, ${a.missing} missing, ${a.failed} failed.`;
      }
    } catch (caught) {
      error = caught instanceof Error ? caught.message : 'Restore failed.';
    } finally {
      busy = false;
    }
  }

  onMount(() => {
    void load();
  });
</script>

<section id="setting-local-recovery" class="overflow-hidden rounded-xl border border-green-400/15 bg-[linear-gradient(135deg,rgba(34,197,94,.07),#111118_55%)]">
  <div class="flex flex-wrap items-start justify-between gap-4 p-4">
    <div class="flex min-w-0 flex-1 flex-wrap items-center gap-2"><h4 class="text-sm font-semibold text-gray-200">Automatic user-data recovery</h4><span class="rounded-full bg-green-500/10 px-2 py-0.5 text-[9px] font-semibold uppercase text-green-300">On</span><span class="rounded-full bg-black/15 px-2 py-0.5 text-[10px] text-gray-500">{localRecovery?.retention ?? 5} retained</span><span class="rounded-full bg-black/15 px-2 py-0.5 text-[10px] text-gray-500">Startup + successful sync</span></div>
    <button class="shrink-0 rounded-lg border border-green-400/20 px-3 py-2 text-xs font-semibold text-green-200 hover:bg-green-500/10 disabled:opacity-40" type="button" disabled={busy || saving || toolRunning || !configuration} on:click={createCheckpoint}>Checkpoint now</button>
  </div>
  <div class="grid gap-2 border-t border-[#242432] bg-black/10 px-4 py-3 text-[11px] sm:grid-cols-[auto_1fr]">
    <span class="text-gray-600">Saved</span><span class="text-gray-400">{localRecovery?.count ?? 0} checkpoint{localRecovery?.count === 1 ? '' : 's'}{#if localRecovery?.latest_at} · latest {new Date(localRecovery.latest_at).toLocaleString()}{/if}</span>
    {#if localRecovery?.preserved_count}
      <span class="text-gray-600">Preserved history</span><span class="break-all text-gray-400">{localRecovery.preserved_count} legacy checkpoints · {localRecovery.preserved_directory}</span>
    {/if}
    <span class="text-gray-600">Location</span><span class="break-all font-mono text-gray-500">{localRecovery?.directory ?? 'Loading…'}</span>
  </div>
</section>

<section id="setting-backup" class="overflow-hidden rounded-2xl border border-amber-400/20 bg-[radial-gradient(circle_at_82%_0%,rgba(245,158,11,.16),transparent_38%),linear-gradient(135deg,#1d1810,#101017_72%)] p-5">
  <div class="flex flex-wrap items-center justify-between gap-4"><div><h3 class="text-base font-bold text-amber-100">Manual metadata backup</h3><div class="mt-2 flex flex-wrap gap-2 text-[10px]"><span class="rounded-full bg-black/20 px-2.5 py-1 text-amber-100/65">No original images</span><span class="rounded-full bg-black/20 px-2.5 py-1 text-amber-100/65">No thumbnails</span><span class="rounded-full bg-black/20 px-2.5 py-1 text-amber-100/65">No credentials</span></div></div><button class="rounded-xl bg-amber-500/15 px-4 py-2 text-xs font-semibold text-amber-100 ring-1 ring-inset ring-amber-300/15 hover:bg-amber-500/25 disabled:opacity-40" type="button" disabled={busy || saving || toolRunning || !configuration} on:click={createBackup}>{busy ? 'Working…' : backupMessage ? 'Create another backup' : 'Create backup'}</button></div>
  <div class="mt-4 rounded-xl border border-amber-300/10 bg-black/15 px-3 py-2.5"><div class="text-[10px] uppercase tracking-[0.14em] text-amber-100/45">Backup location</div><div class="mt-1 break-all font-mono text-xs text-amber-50/70">{destination || 'Loading…'}</div></div>
  {#if backupMessage}<p aria-live="polite" class="mt-3 rounded-xl border border-green-400/20 bg-green-500/[0.08] px-4 py-3 text-xs leading-relaxed text-green-300">{backupMessage}</p>{/if}
  {#if backupError}<p role="alert" class="mt-3 rounded-xl border border-red-400/20 bg-red-500/[0.08] px-4 py-3 text-xs leading-relaxed text-red-300">{backupError}</p>{/if}
  <p class="mt-3 text-xs leading-relaxed text-gray-400">Disabled modules keep their backup eligibility. Unavailable data is omitted and reported after creation. Files origin notes are in the shared user database; their attachment bytes are a separate selection.</p>
  <p class="mt-2 text-xs leading-relaxed text-gray-500">Original media, thumbnails, credentials and the rebuildable Files index are excluded. Browser preferences such as grid size, motion and sidebar position stay in this browser and are not backed up or restored. The configuration copy in a bundle is reference-only and is not applied during restore.</p>
  <div class="mt-4 grid gap-2 sm:grid-cols-2">
    {#each availableChoices as choice}
      <button class="flex items-start gap-3 rounded-xl border p-3 text-left transition-colors {components[choice.key] ? 'border-amber-300/20 bg-amber-500/[0.07]' : 'border-white/5 bg-black/15'}" type="button" role="checkbox" disabled={busy || saving || toolRunning} aria-checked={components[choice.key]} on:click={() => toggleComponent(choice.key)}><span class="mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded border {components[choice.key] ? 'border-amber-300/40 bg-amber-400/20 text-amber-100' : 'border-gray-700 text-transparent'}">✓</span><span><span class="text-sm font-semibold text-gray-200">{choice.label}<span class="ml-2 text-[10px] text-gray-400">{choice.owner}</span>{#if choice.recommended}<span class="ml-2 text-[9px] uppercase text-amber-300">recommended</span>{/if}</span><span class="mt-0.5 block text-xs leading-relaxed text-gray-500">{choice.description}</span><span class="mt-1 block text-[10px] text-gray-600">{estimate?.details[choice.key]?.display_size ?? 'Calculating…'} · {estimate?.details[choice.key]?.files ?? 0} files{#if estimate?.details[choice.key] && !estimate.details[choice.key].exists} · No data available{/if}</span></span></button>
    {/each}
  </div>
  <div class="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-amber-300/10 bg-black/15 px-3 py-2.5"><div><div class="text-xs font-semibold text-amber-100/80">Estimated compressed size: {estimate?.estimated_compressed_display ?? 'Calculating…'}</div><div class="mt-0.5 text-[10px] text-amber-100/45">Raw selection {estimate?.display_size ?? '-'} · exact size is verified after creation</div></div><button class="rounded-lg border border-amber-300/15 px-3 py-2 text-xs text-amber-100/80 hover:bg-amber-500/10 disabled:opacity-40" type="button" disabled={busy || saving || toolRunning || !configuration} on:click={() => saveConfiguration()}>Save selection</button></div>
</section>

<section id="setting-restore" class="overflow-hidden rounded-xl border border-purple-400/15 bg-[#111118]">
  <div class="border-b border-[#242432] p-4"><h4 class="text-sm font-semibold text-gray-200">Restore metadata backup</h4></div>
  <div class="flex flex-wrap gap-2 p-4"><select class="min-w-0 flex-1 rounded-xl border border-[#303040] bg-[#0d0d13] px-3 py-2 text-xs text-gray-200" aria-label="Backup to restore" disabled={busy || saving || toolRunning} bind:value={selectedBackup} on:change={() => inspectSelected()}><option value="">Choose a backup</option>{#each configuration?.backups ?? [] as backup}<option value={backup.name}>{backup.name} · {backup.display_size}</option>{/each}</select><button class="rounded-xl border border-purple-400/20 px-3 py-2 text-xs text-purple-200 hover:bg-purple-500/10 disabled:opacity-40" type="button" disabled={!selectedBackup || busy || saving || toolRunning} on:click={restoreSelected}>Restore</button></div>
  {#if inspected}<div class="border-t border-[#242432] bg-black/10 px-4 py-3 text-[11px] text-gray-500">Created {new Date(inspected.created_at).toLocaleString()} · format {inspected.format_version} · originals excluded · thumbnails excluded
    <p class="mt-2">Included: {includedLabels.join(', ') || 'None'}</p>
    {#if inspected.components.user_database}<p class="mt-2 text-amber-200">Restores the whole shared user database, including Files and every module’s user data.</p>{/if}
    {#if inspected.omitted_components?.length}<p class="mt-2">Omitted when created: {inspected.omitted_components.map(componentLabel).join(', ')}</p>{/if}
  </div>{/if}
</section>

{#if message}<p class="rounded-xl border border-green-400/15 bg-green-500/[0.05] px-4 py-3 text-xs leading-relaxed text-green-300">{message}</p>{/if}
{#if error}<p class="rounded-xl border border-red-400/15 bg-red-500/[0.05] px-4 py-3 text-xs text-red-300">{error}</p>{/if}
