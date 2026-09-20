<script lang="ts">
  import { getContext, onMount, tick } from 'svelte';
  import { suiteDataApi as api } from '../lib/suiteDataApi';
  import { type BackupOptions, type BackupComponents, type BackupConfiguration, type BackupEstimate, type BackupManifest, type LocalRecoveryStatus } from '../lib/suiteApiTypes';
  import { SUITE_NAME } from '../lib/product';
  import { suiteModules } from '../lib/suiteStores';

  import { SETTINGS_SESSION, type SettingsSession } from '../lib/settingsSession';
  const session = getContext<SettingsSession>(SETTINGS_SESSION);
  let dialog = '';
  let options: BackupOptions = {enabled:false, location:'default', custom_location:'', retention:3, frequency_minutes:60};

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
    { key: 'user_database', label: 'User data', description: 'Your registered folders, origin notes, favorites, collections, tags, follows and profile.', recommended: true },
    { key: 'library_database', label: 'Library index', description: 'Saved library information for a faster restore.', recommended: true },
    { key: 'sidecars', label: 'Tags and metadata', description: 'Saved tags and details for your images.', recommended: true },
    { key: 'sidecar_history', label: 'Metadata history', description: 'Archived metadata versions from manual refreshes.' },
    { key: 'artist_profile_archive', label: 'Artist profile archive', description: 'Locally preserved artist avatars and banners.' },
    { key: 'file_attachments', label: 'File attachments', description: 'Screenshots and clips you attached to files, so they survive a lost source folder.', recommended: true },
  ];

  function componentLabel(key: string) {
    return choices.find(choice => choice.key === key)?.label ?? key.replaceAll('_', ' ');
  }

  function ownerOrder(owner: string) {
    const index = $suiteModules.findIndex(module => module.slug === owner);
    return index < 0 ? Number.MAX_SAFE_INTEGER : index;
  }

  function ownerLabel(owner: string) {
    return owner === 'suite' ? SUITE_NAME : $suiteModules.find(module => module.slug === owner)?.name ?? owner;
  }

  $: availableChoices = Object.keys(configuration?.components ?? {}).map(key => ({
    key,
    label: componentLabel(key),
    description: choices.find(choice => choice.key === key)?.description ?? 'Preserved data contributed by this module.',
    recommended: choices.find(choice => choice.key === key)?.recommended ?? false,
    owner: configuration?.estimate.details[key]?.owner ?? 'suite',
  }));
  $: moduleOwners = [...new Set(availableChoices.filter(choice => choice.owner !== 'suite').map(choice => choice.owner))].sort((left, right) => ownerOrder(left) - ownerOrder(right));
  $: blocked = busy || saving || toolRunning || !!configuration?.automatic_status?.running;
  $: includedLabels = inspected ? Object.entries(inspected.components)
    .filter(([, included]) => included).map(([key]) => componentLabel(key)) : [];

  function applyConfiguration(value: BackupConfiguration) {
    configuration = value;
    destination = value.destination;
    options = value.options;
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
    if (blocked || !configuration) return;
    busy = true;
    error = '';
    message = '';
    try {
      const result = await api.createLocalRecoveryCheckpoint();
      localRecovery = result;
      message = result.created ? 'Recovery checkpoint saved.' : 'Your recovery checkpoint is already up to date.';
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
      applyConfiguration(await api.configureBackups(components, options));
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
    if (blocked || !configuration) return;
    busy = true;
    backupError = '';
    backupMessage = '';
    try {
      if (!(await saveConfiguration(false))) return;
      const result = await api.createMetadataBackup(components);
      backupMessage = `Backup saved ✓ ${result.display_size}.` + (result.omitted_components?.length ? ` Not included: ${result.omitted_components.map(componentLabel).join(', ')}.` : '');
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
        ? ' This replaces user data for Files and every module together, including origin notes, favorites and collections.'
        : '';
      if (!confirm(`Restore ${selectedBackup}? Included: ${includedLabels.join(', ')}.${wholeDatabase} ${SUITE_NAME} will preserve a recovery copy of the current data. Original media will not be changed. Browser preferences will not be restored.`)) return;
      const result = await api.restoreMetadataBackup(selectedBackup);
      message = `Restore complete. Restart ${SUITE_NAME} before continuing. Recovery copy: ${result.rollback_path}`;
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

  async function changeOption<K extends keyof BackupOptions>(key: K, value: BackupOptions[K]) {
    if (blocked) return;
    const previous = options;
    options = {...options, [key]: value};
    if (!await saveConfiguration(false)) options = previous;
  }

  async function chooseLocation() {
    if (blocked) return;
    busy = true;
    backupError = '';
    try {
      const initialPath = options.custom_location || (await api.getStorageConfiguration()).suite_home;
      const path = await session.pickDirectory(initialPath);
      if (!path) return;
      const previous = options;
      options = {...options, location:'custom', custom_location:path};
      if (!await saveConfiguration(false)) options = previous;
    } catch (caught) {
      backupError = caught instanceof Error ? caught.message : 'Could not choose a backup folder.';
    } finally { busy = false; }
  }

  async function finishSelection() {
    if (await saveConfiguration(false)) dialog = '';
  }

  async function userDataToggle() {
    const previous = {...components};
    await toggleComponent('user_database');
    if (!await saveConfiguration(false)) {components = previous; await refreshEstimate();}
  }

  async function openRestore() {
    dialog = 'restore';
    inspected = null;
    error = '';
    message = '';
    try {
      configuration = await api.getBackupConfiguration();
      if (!configuration.backups.some(backup => backup.name === selectedBackup)) selectedBackup = configuration.backups[0]?.name ?? '';
      await inspectSelected();
    } catch (caught) { error = String(caught); }
  }

  function focusDialog(node: HTMLElement) {
    const previous = document.activeElement as HTMLElement | null;
    void tick().then(() => node.querySelector<HTMLElement>('button, select')?.focus());
    const trap = (event: KeyboardEvent) => {
      if (event.key !== 'Tab') return;
      const targets = [...node.querySelectorAll<HTMLElement>('button:not(:disabled), select:not(:disabled), input:not(:disabled), summary')];
      const first = targets[0], last = targets[targets.length - 1];
      if (event.shiftKey && document.activeElement === first) {event.preventDefault(); last?.focus();}
      else if (!event.shiftKey && document.activeElement === last) {event.preventDefault(); first?.focus();}
    };
    node.addEventListener('keydown', trap);
    return {destroy() {node.removeEventListener('keydown', trap); if (previous?.isConnected) previous.focus();}};
  }

  function dismiss() {
    if (!dialog) return false;
    if (!blocked) {
      if (dialog !== 'restore' && configuration) {components = {...configuration.components}; void refreshEstimate();}
      dialog = '';
    }
    return true;
  }

  onMount(() => {
    void load();
    const unregister = session.register('suite-backups', {dismissOverlay:dismiss});
    let alive = true;
    let polling = false;
    const timer = setInterval(async () => {
      if (!options.enabled || !configuration || polling) return;
      polling = true;
      try {const status = await api.getAutomaticBackupStatus(); if (alive && configuration) configuration = {...configuration, automatic_status:status};}
      catch (caught) { if (alive) error = 'Could not refresh automatic backup status.'; }
      finally {polling = false;}
    }, 5000);
    return () => {alive = false; clearInterval(timer); unregister();};
  });
</script>

<section id="setting-backup" class="space-y-5">
  <section class="overflow-hidden rounded-xl border border-[#292938] bg-[#111118]">
    <div class="flex items-center justify-between gap-4 border-b border-[#22222e] px-4 py-4">
      <div><h3 class="text-sm font-semibold text-gray-200">Automatic backup</h3><p class="mt-1 text-xs text-gray-500">Runs while {SUITE_NAME} is open, using your selections below.</p></div>
      <button type="button" role="switch" aria-label="Automatic backup" aria-checked={options.enabled} disabled={blocked || !configuration} on:click={() => changeOption('enabled', !options.enabled)} class="rounded-lg border border-[#303040] px-4 py-2 text-xs {options.enabled ? 'bg-purple-500/20 text-purple-100' : 'text-gray-400'} disabled:opacity-50">{options.enabled ? 'On' : 'Off'}</button>
    </div>
    <div class="space-y-4 p-4">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <span class="text-sm text-gray-300">Location</span>
        <div class="flex gap-2">
          <button type="button" aria-pressed={options.location === 'default'} disabled={blocked || !configuration} on:click={() => changeOption('location', 'default')} class="rounded-lg border border-[#303040] px-3 py-2 text-xs {options.location === 'default' ? 'bg-[#242432] text-gray-100' : 'text-gray-400'}">Default</button>
          <button type="button" aria-pressed={options.location === 'custom'} disabled={blocked || !configuration} on:click={chooseLocation} class="rounded-lg border border-[#303040] px-3 py-2 text-xs {options.location === 'custom' ? 'bg-[#242432] text-gray-100' : 'text-gray-400'}">Custom…</button>
        </div>
      </div>
      <p class="break-all text-xs text-gray-500">{destination || 'Loading…'}</p>
      <div class="flex items-center justify-between gap-4">
        <label for="backup-retention" class="text-sm text-gray-300">Keep automatic backups</label>
        <select id="backup-retention" value={options.retention} disabled={blocked || !configuration} on:change={event => changeOption('retention', Number(event.currentTarget.value))} class="rounded-lg border border-[#303040] bg-[#0d0d13] px-3 py-2 text-xs text-gray-200">{#each [1,2,3,4,5] as count}<option value={count}>{count}</option>{/each}</select>
      </div>
      <div class="flex items-center justify-between gap-4">
        <label for="backup-frequency" class="text-sm text-gray-300">Frequency</label>
        <select id="backup-frequency" value={options.frequency_minutes} disabled={blocked || !configuration} on:change={event => changeOption('frequency_minutes', Number(event.currentTarget.value) as BackupOptions['frequency_minutes'])} class="rounded-lg border border-[#303040] bg-[#0d0d13] px-3 py-2 text-xs text-gray-200">{#each [15,30,45,60] as minutes}<option value={minutes}>{minutes === 60 ? 'One hour' : `${minutes} minutes`}</option>{/each}</select>
      </div>
      <p role="status" class="text-xs text-gray-400">{#if configuration?.automatic_status?.running}Backing up…{:else if configuration?.automatic_status?.last_result === 'failed'}Last backup failed ⚠ — details in Logs{:else if configuration?.automatic_status?.last_success_at}Last backup ✓ {new Date(configuration.automatic_status.last_success_at).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'})}{:else}No automatic backup yet{/if}</p>
    </div>
  </section>

  <section class="overflow-hidden rounded-xl border border-[#292938] bg-[#111118]">
    <h3 class="border-b border-[#22222e] px-4 py-4 text-sm font-semibold text-gray-200">Backups</h3>
    <div class="divide-y divide-[#22222e]">
      <button type="button" role="checkbox" aria-label="User data" aria-checked={components.user_database} disabled={blocked || !configuration} on:click={userDataToggle} class="flex w-full items-center justify-between px-4 py-4 text-sm text-gray-200 disabled:opacity-50"><span>User data</span><span aria-hidden="true" class="grid h-5 w-5 place-items-center rounded border border-[#444454]">{components.user_database ? '✓' : ''}</span></button>
      {#each moduleOwners as owner}
        <button type="button" disabled={blocked} on:click={() => dialog = owner} class="flex w-full items-center justify-between px-4 py-4 text-left text-sm text-gray-200 hover:bg-[#1a1a23] disabled:opacity-50"><span>{ownerLabel(owner)}</span><span class="text-gray-500" aria-hidden="true">›</span></button>
      {/each}
    </div>
  </section>

  <p class="text-sm text-gray-300">Estimated compressed size: {estimate?.estimated_compressed_display ?? 'Calculating…'}</p>
  <div class="flex flex-wrap gap-3">
    <button type="button" disabled={blocked || !configuration || !Object.values(components).some(Boolean)} on:click={createBackup} class="rounded-lg bg-purple-500/20 px-4 py-2.5 text-sm font-medium text-purple-100 disabled:opacity-50">{busy ? 'Working…' : 'Back up now'}</button>
    <button id="setting-restore" type="button" disabled={blocked || !configuration} on:click={openRestore} class="rounded-lg border border-[#303040] px-4 py-2.5 text-sm text-gray-200 disabled:opacity-50">Restore now</button>
  </div>
  {#if backupMessage}<p aria-live="polite" class="text-xs text-green-300">{backupMessage}</p>{/if}
  {#if backupError}<p role="alert" class="text-xs text-red-300">{backupError}</p>{/if}
  {#if message}<p role="status" class="break-all text-xs text-green-300">{message}</p>{/if}
  {#if error}<p role="alert" class="text-xs text-red-300">{error}</p>{/if}

  <details id="setting-local-recovery" class="rounded-xl border border-[#292938] bg-[#111118] p-4 text-xs text-gray-500">
    <summary class="cursor-pointer text-gray-400">Backup details and recovery</summary>
    <p class="mt-3">Manual backups are kept until you remove them. Automatic retention removes only unchanged automatic backups after a new backup is verified.</p>
    <p class="mt-2">Original media, thumbnails and credentials are excluded. Browser preferences such as grid size, motion and sidebar position stay in this browser. The saved configuration copy is for reference and is not applied during restore.</p>
    <p class="mt-2">Built-in user-data recovery remains active at startup and after successful sync. It is separate from automatic backups.</p>
    <p class="mt-2">{localRecovery?.count ?? 0} checkpoints · {localRecovery?.retention ?? 5} retained{#if localRecovery?.latest_at} · latest {new Date(localRecovery.latest_at).toLocaleString()}{/if}</p>
    {#if localRecovery?.preserved_count}<p class="mt-2 break-all">{localRecovery.preserved_count} legacy checkpoints · {localRecovery.preserved_directory}</p>{/if}
    <p class="mt-2 break-all">{localRecovery?.directory}</p>
    <button type="button" disabled={blocked || !configuration} on:click={createCheckpoint} class="mt-3 rounded-lg border border-[#303040] px-3 py-2 text-gray-300 disabled:opacity-50">Checkpoint now</button>
  </details>
</section>

{#if dialog}
  <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
  <div on:click|stopPropagation use:session.portal class="absolute inset-0 z-[5] flex items-center justify-center bg-black/65 p-5">
    <div role="dialog" aria-modal="true" aria-label={dialog === 'restore' ? 'Restore backup' : `${ownerLabel(dialog)} backups`} tabindex="-1" use:focusDialog class="max-h-full w-full max-w-lg overflow-y-auto rounded-xl border border-[#343444] bg-[#111118] p-5 shadow-2xl">
      <div class="mb-4 flex items-center justify-between gap-4"><h3 class="text-base font-semibold text-gray-200">{dialog === 'restore' ? 'Restore backup' : `${ownerLabel(dialog)} backups`}</h3><button type="button" aria-label="Close backup dialog" disabled={blocked} on:click={dismiss} class="rounded-lg px-2 py-1 text-gray-400">✕</button></div>
      {#if dialog === 'restore'}
        <select aria-label="Backup to restore" disabled={blocked} bind:value={selectedBackup} on:change={() => inspectSelected()} class="w-full rounded-lg border border-[#303040] bg-[#0d0d13] px-3 py-2 text-xs text-gray-200"><option value="">Choose a backup</option>{#each configuration?.backups ?? [] as backup}<option value={backup.name}>{new Date(backup.created_at).toLocaleString()} · {backup.display_size} · {backup.name}</option>{/each}</select>
        {#if configuration?.backups.length === 0}<p class="mt-3 text-sm text-gray-400">No backups in this location.</p>{/if}
        {#if inspected}
          <p class="mt-4 text-xs text-gray-400">Included: {includedLabels.join(', ') || 'None'}</p>
          {#if inspected.components.user_database}<p class="mt-3 text-sm text-gray-300">Replaces user data for Files and every module together.</p>{/if}
          {#if inspected.omitted_components?.length}<p class="mt-3 text-xs text-gray-500">Not included: {inspected.omitted_components.map(componentLabel).join(', ')}</p>{/if}
          <p class="mt-3 text-xs text-gray-500">A recovery copy of your current data will be preserved. Original media and browser preferences will stay unchanged.</p>
        {/if}
        {#if error}<p role="alert" class="mt-3 text-xs text-red-300">{error}</p>{/if}
        {#if message}<p role="status" class="mt-3 break-all text-xs text-green-300">{message}</p>{/if}
        <button type="button" disabled={blocked || !inspected} on:click={restoreSelected} class="mt-5 rounded-lg bg-purple-500/20 px-4 py-2 text-sm text-purple-100 disabled:opacity-50">Restore backup</button>
      {:else}
        <p class="mb-4 text-xs text-gray-500">Choose the data to include. Disabled modules remain eligible for backup.</p>
        <div class="space-y-2">{#each availableChoices.filter(choice => choice.owner === dialog) as choice}
          <button type="button" role="checkbox" aria-label={choice.label} aria-checked={components[choice.key]} disabled={blocked} on:click={() => toggleComponent(choice.key)} class="flex w-full items-start gap-3 rounded-lg border border-[#303040] p-3 text-left disabled:opacity-50"><span aria-hidden="true" class="grid h-5 w-5 shrink-0 place-items-center rounded border border-[#444454] text-gray-200">{components[choice.key] ? '✓' : ''}</span><span><span class="block text-sm text-gray-200">{choice.label}</span><span class="mt-1 block text-xs text-gray-500">{choice.description}</span>{#if configuration?.estimate.details[choice.key] && !configuration.estimate.details[choice.key].exists}<span class="mt-1 block text-xs text-gray-500">No data available</span>{/if}</span></button>
        {/each}</div>
        {#if backupError}<p role="alert" class="mt-3 text-xs text-red-300">{backupError}</p>{/if}
        <button type="button" disabled={blocked} on:click={finishSelection} class="mt-5 rounded-lg border border-[#303040] px-4 py-2 text-sm text-gray-200 disabled:opacity-50">Done</button>
      {/if}
    </div>
  </div>
{/if}
