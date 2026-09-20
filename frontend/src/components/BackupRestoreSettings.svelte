<script lang="ts">
  import SettingsSwitch from './SettingsSwitch.svelte';
  import { settingsError } from '../lib/http';
  import { getContext, onMount, tick } from 'svelte';
  import { suiteDataApi as api } from '../lib/suiteDataApi';
  import { type BackupOptions, type BackupComponents, type BackupConfiguration, type BackupEstimate, type BackupManifest } from '../lib/suiteApiTypes';
  import { SUITE_NAME } from '../lib/product';
  import { suiteModules } from '../lib/suiteStores';

  import { SETTINGS_SESSION, type SettingsSession } from '../lib/settingsSession';
  const session = getContext<SettingsSession>(SETTINGS_SESSION);
  let dialog = '';
  let options: BackupOptions = {enabled:false, location:'default', custom_location:'', retention:3, frequency_minutes:60};

  export let toolRunning = false;

  let loading = true;
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
    if (!value.options || !value.automatic_status || !value.estimate?.details) {
      throw new Error(`The running backend does not support these backup settings. Close older ${SUITE_NAME} instances and restart the current build.`);
    }
    configuration = value;
    destination = value.destination;
    options = value.options;
    estimateRequest++;
    components = { ...value.components };
    estimate = value.estimate;
    if (!selectedBackup && value.backups.length) selectedBackup = value.backups[0].name;
  }

  async function load() {
    loading = true; error = '';
    try { applyConfiguration(await api.getBackupConfiguration()); }
    catch (caught) { error = settingsError(caught, 'Backup settings'); }
    loading = false;
  }

  async function openLocation() {
    busy = true; backupError = '';
    try {await api.openDiagnostics('backups');}
    catch (caught) {backupError = settingsError(caught, 'Backup folder');}
    finally {busy = false;}
  }

  function selectAll(selected: boolean) {
    components = {...components, ...Object.fromEntries(availableChoices.filter(choice => choice.owner === dialog).map(choice => [choice.key, selected]))};
    void refreshEstimate();
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

  function ownerState(owner: string, selection: BackupComponents): boolean | 'mixed' {
    const keys = availableChoices.filter(choice => choice.owner === owner);
    const count = keys.filter(choice => selection[choice.key]).length;
    return count === 0 ? false : count === keys.length ? true : 'mixed';
  }

  async function toggleOwner(owner: string) {
    if (blocked) return;
    const previous = {...components};
    const previousOptions = options;
    const keys = availableChoices.filter(choice => choice.owner === owner).map(choice => choice.key);
    const enabled = keys.some(key => components[key]);
    const remembered = {...options.remembered_components};
    if (enabled) keys.forEach(key => remembered[key] = !!components[key]);
    const hasMemory = keys.some(key => remembered[key]);
    components = {...components, ...Object.fromEntries(keys.map(key => [key, !enabled && (hasMemory ? !!remembered[key] : true)]))};
    options = {...options, remembered_components: remembered};
    if (!await saveConfiguration(false)) {components = previous; options = previousOptions; await refreshEstimate();}
  }

  async function finishSelection() {
    const keys = availableChoices.filter(choice => choice.owner === dialog).map(choice => choice.key);
    const source = keys.some(key => components[key]) ? components : configuration?.components;
    if (source && keys.some(key => source[key])) options = {...options, remembered_components: {...options.remembered_components, ...Object.fromEntries(keys.map(key => [key, !!source[key]]))}};
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

<div id="setting-backup" class="backup-page">
  {#if error}<div role="alert" class="backup-notice error">{error} <button on:click={load} disabled={loading || busy}>Retry</button></div>{/if}
  {#if loading && !configuration}<p role="status" class="backup-hint">Loading backup settings…</p>{/if}
  {#if configuration}
  <section class="backup-card">
    <div class="backup-row"><span>Automatic backup</span><div class="backup-controls"><span role="status" class="backup-hint">{#if configuration.automatic_status.running}Backing up…{:else if configuration.automatic_status.last_result === 'failed'}Last backup failed ⚠ — see Logs{:else if configuration.automatic_status.last_success_at}Last backup ✓ {new Date(configuration.automatic_status.last_success_at).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'})}{/if}</span><SettingsSwitch label="Automatic backup" checked={options.enabled} disabled={blocked} on:click={() => changeOption('enabled', !options.enabled)} /></div></div>
    <div class="backup-row"><span>Backup location</span><div class="backup-segments"><button class:chosen={options.location === 'default'} aria-pressed={options.location === 'default'} disabled={blocked} on:click={() => changeOption('location','default')}>Default</button><button class:chosen={options.location === 'custom'} aria-pressed={options.location === 'custom'} disabled={blocked} on:click={chooseLocation}>Custom</button></div></div>
    <div class="backup-row location-row"><span>Location</span><div class="backup-controls location-controls"><span class="backup-path" title={destination}>{destination}</span><button class="backup-button" disabled={blocked} on:click={options.location === 'custom' ? chooseLocation : openLocation}>{options.location === 'custom' ? 'Browse…' : 'Open folder'}</button></div></div>
    <div class="backup-row"><label for="backup-retention">Backups</label><select id="backup-retention" aria-label="Keep automatic backups" value={options.retention} disabled={blocked} on:change={event => changeOption('retention', Number(event.currentTarget.value))}>{#each [1,2,3,4,5] as count}<option value={count}>{count}</option>{/each}</select></div>
    <div class="backup-row"><label for="backup-frequency">Backup frequency</label><select id="backup-frequency" aria-label="Frequency" value={options.frequency_minutes} disabled={blocked} on:change={event => changeOption('frequency_minutes', Number(event.currentTarget.value) as BackupOptions['frequency_minutes'])}>{#each [15,30,45,60] as minutes}<option value={minutes}>{minutes === 60 ? '1 hour' : `${minutes} min`}</option>{/each}</select></div>
  </section>
  <section class="backup-card">
    <div class="backup-heading"><div><h3>Backups</h3></div><button class="backup-button primary" disabled={blocked || !Object.values(components).some(Boolean)} on:click={createBackup}>{busy ? 'Working…' : 'Back up now'}</button></div>
    <button class="backup-selection" role="checkbox" aria-label="User data" aria-checked={components.user_database} disabled={blocked} on:click={userDataToggle}><span class="backup-check" class:checked={components.user_database} aria-hidden="true"></span><span>User data</span><span class="backup-selection-summary">{components.user_database ? 'Included' : 'Not included'}</span></button>
    {#each moduleOwners as owner}
      <div class="backup-selection module-selection">
        <button class="module-checkbox" role="checkbox" aria-label={`${ownerLabel(owner)} backup inclusion`} aria-checked={ownerState(owner, components)} disabled={blocked} on:click={() => toggleOwner(owner)}><span class="backup-check" class:checked={ownerState(owner, components) !== false} class:mixed={ownerState(owner, components) === 'mixed'} aria-hidden="true"></span></button>
        <button class="module-options" aria-label={ownerLabel(owner)} disabled={blocked} on:click={() => dialog = owner}><span>{ownerLabel(owner)}</span><span class="backup-selection-summary">{availableChoices.filter(choice => choice.owner === owner && components[choice.key]).length} selected</span><span class="backup-chevron" aria-hidden="true">›</span></button>
      </div>
    {/each}
  </section>
  <section id="setting-restore" class="backup-card backup-heading"><div><h3>Restore</h3></div><button class="backup-button" disabled={blocked} on:click={openRestore}>Restore now</button></section>
  <div class="backup-footer"><span>Estimated compressed size: {estimate?.estimated_compressed_display ?? 'Calculating…'}</span></div>
  {#if backupMessage}<p aria-live="polite" class="backup-notice success">{backupMessage}</p>{/if}
  {#if backupError}<p role="alert" class="backup-notice error">{backupError}</p>{/if}
  {#if message}<p role="status" class="backup-notice success">{message}</p>{/if}

  {/if}
</div>

{#if dialog}
  <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
  <div on:click|stopPropagation use:session.portal class="backup-overlay">
    <div role="dialog" aria-modal="true" aria-label={dialog === 'restore' ? 'Restore backup' : `${ownerLabel(dialog)} backups`} tabindex="-1" use:focusDialog class="backup-dialog">
      <header><div><h3>{dialog === 'restore' ? 'Restore backup' : `${ownerLabel(dialog)} backup options`}</h3><p class="backup-hint">{dialog === 'restore' ? 'Review before restoring.' : `Choose what to include from ${ownerLabel(dialog)}.`}</p></div><button class="backup-close" aria-label="Close backup dialog" disabled={blocked} on:click={dismiss}>×</button></header>
      <div class="backup-dialog-content">
      {#if dialog === 'restore'}
        <select aria-label="Backup to restore" disabled={blocked} bind:value={selectedBackup} on:change={() => inspectSelected()}><option value="">Choose a backup</option>{#each configuration?.backups ?? [] as backup}<option value={backup.name}>{new Date(backup.created_at).toLocaleString()} · {backup.display_size} · {backup.name}</option>{/each}</select>
        {#if configuration?.backups.length === 0}<p class="backup-hint">No backups in this location.</p>{/if}
        {#if inspected}
          <div class="restore-summary"><h4>{SUITE_NAME} backup</h4><p class="backup-hint">{new Date(inspected.created_at).toLocaleString()} · {configuration?.backups.find(backup => backup.name === selectedBackup)?.display_size}</p><div class="restore-included"><p class="backup-hint">Included</p>{#each includedLabels as label}<p>✓ {label}</p>{/each}</div></div>
          {#if inspected.components.user_database}<p class="backup-hint">Replaces user data for Files and every module together.</p>{/if}
          {#if inspected.omitted_components?.length}<p class="backup-hint">Not included: {inspected.omitted_components.map(componentLabel).join(', ')}</p>{/if}
          <p class="backup-hint">A recovery copy of your current data will be preserved. Original media and browser preferences stay unchanged.</p>
        {/if}
        {#if error}<p role="alert" class="backup-notice error">{error}</p>{/if}
        {#if message}<p role="status" class="backup-notice success">{message}</p>{/if}
      {:else}
        <div class="backup-options">{#each availableChoices.filter(choice => choice.owner === dialog) as choice}
          <button role="checkbox" aria-label={choice.label} aria-checked={components[choice.key]} disabled={blocked} on:click={() => toggleComponent(choice.key)}><span class="backup-check" class:checked={components[choice.key]} aria-hidden="true"></span><span><span class="option-name">{choice.label}</span><span class="backup-hint">{choice.description}</span></span></button>
        {/each}</div>
        {#if backupError}<p role="alert" class="backup-notice error">{backupError}</p>{/if}
      {/if}
      </div>
      <footer>
        {#if dialog !== 'restore'}<div class="selection-actions"><button disabled={blocked} on:click={() => selectAll(true)}>Select all</button><button disabled={blocked} on:click={() => selectAll(false)}>Select none</button></div>{/if}
        <div class="backup-controls"><button class="backup-button" disabled={blocked} on:click={dismiss}>Cancel</button>{#if dialog === 'restore'}<button class="backup-button primary" disabled={blocked || !inspected} on:click={restoreSelected}>Restore</button>{:else}<button class="backup-button primary" disabled={blocked} on:click={finishSelection}>Done</button>{/if}</div>
      </footer>
    </div>
  </div>
{/if}

<style>
  .backup-page{max-width:816px;margin:auto;display:flex;flex-direction:column;gap:18px;color:#ececf3;font-size:14px}
  .backup-card{border:1px solid #2d2f3f;border-radius:12px;background:#0f1018;overflow:hidden}
  .backup-row{min-height:56px;padding:10px 17px;display:flex;align-items:center;justify-content:space-between;gap:16px}
  .backup-row+.backup-row{border-top:1px solid #232532}
  .backup-controls{display:flex;align-items:center;gap:12px;min-width:0}
  .backup-segments{display:flex;border:1px solid #343749;border-radius:8px;overflow:hidden;background:#0d0e15}
  .backup-segments button{width:98px;min-height:32px;font-size:12px;color:#8e91a3}
  .backup-segments button+button{border-left:1px solid #2d3040}
  .backup-segments .chosen{background:#351044;color:#f2e2ff;box-shadow:inset 0 0 0 1px #5f247e}
  .backup-button,select,.backup-close{border:1px solid #343749;border-radius:8px;background:#0d0e15;color:#ececf3;min-height:34px;padding:6px 14px;font-size:13px}
  .backup-button{white-space:nowrap;flex-shrink:0;min-width:110px}
  .primary{background:#7d2dc2;border-color:#7d2dc2;color:#f7edff;font-weight:500}
  select{min-width:112px}
  #backup-frequency{width:156px}
  .location-controls{flex:0 1 512px}
  .backup-path{min-width:0;flex:1;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;padding:8px 13px;font-size:12px;color:#a2a4b6;background:#0d0e15;border:1px solid #343749;border-radius:8px}
  .backup-heading{padding:16px 17px;display:flex;align-items:center;justify-content:space-between;gap:16px;min-height:72px}
  h3,h4{font-size:15px;font-weight:500;margin:0}
  .backup-hint{font-size:12px;color:#858899;line-height:1.5}
  h3+.backup-hint,h4+.backup-hint{margin-top:4px}
  .backup-selection{display:flex;align-items:center;gap:14px;min-height:54px;width:100%;text-align:left;padding:12px 17px;border-top:1px solid #232532}
  .module-selection{padding:0;gap:0}
  .module-checkbox{padding:18px 14px 18px 17px;display:flex;align-items:center}
  .module-options{display:flex;align-items:center;gap:14px;flex:1;align-self:stretch;text-align:left;padding:12px 17px 12px 0}
  .backup-check.checked::after{content:"";width:6px;height:10px;border:solid currentColor;border-width:0 2px 2px 0;transform:translateY(-1px) rotate(45deg)}
  .backup-check.mixed::after{width:10px;height:0;border-width:2px 0 0;transform:none}
  .backup-check{height:18px;width:18px;flex-shrink:0;border-radius:4px;background:#15151e;border:1px solid #444454;color:transparent;display:grid;place-items:center;font-size:0;position:relative}
  .backup-check.checked{background:#4b3908;border-color:#8f6e11;color:#f1d66a}
  .backup-selection-summary{margin-left:auto;font-size:12px;color:#a2a4b6}
  .backup-chevron{font-size:24px;line-height:18px;color:#a2a4b6}
  .backup-footer{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;font-size:11px;color:#858899}
  .backup-notice{font-size:12px;line-height:1.6;overflow-wrap:anywhere}
  .error{color:#fca5a5}.success{color:#86efac}.backup-notice button{text-decoration:underline;margin-left:8px}
  .backup-overlay{position:absolute;inset:0;z-index:5;display:flex;align-items:center;justify-content:center;padding:24px;background:#000a}
  .backup-dialog{width:560px;max-width:100%;max-height:100%;display:flex;flex-direction:column;border:1px solid #343447;border-radius:14px;background:#111119;box-shadow:0 24px 80px #0009;color:#ececf3}
  .backup-dialog header{display:flex;justify-content:space-between;align-items:center;gap:16px;padding:20px 22px;border-bottom:1px solid #292b39}
  .backup-dialog h3{font-size:18px;font-weight:600}
  .backup-close{font-size:22px;min-width:34px;padding:0 8px;color:#a2a4b6}
  .backup-dialog-content{padding:20px 22px;overflow-y:auto;display:flex;flex-direction:column;gap:14px}
  .backup-options{border:1px solid #303242;border-radius:10px;overflow:hidden}
  .backup-options button{display:flex;align-items:center;gap:14px;width:100%;padding:14px;text-align:left}
  .backup-options button+button{border-top:1px solid #292b39}
  .backup-options .backup-hint,.option-name{display:block}.option-name{font-size:14px;margin-bottom:3px}
  .backup-dialog footer{padding:16px 22px;border-top:1px solid #292b39;display:flex;align-items:center;justify-content:flex-end;gap:14px;flex-wrap:wrap}
  .selection-actions{display:flex;gap:14px;margin-right:auto;font-size:12px;color:#a2a4b6}
  .restore-summary{padding:16px;border:1px solid #303242;border-radius:10px;background:#0d0e15}.restore-included{margin-top:14px;display:grid;gap:7px;font-size:13px}
  button:disabled,select:disabled{opacity:.45;cursor:default}
  button:focus-visible,select:focus-visible{outline:2px solid #b66aff;outline-offset:2px}
  .backup-button:hover:not(:disabled),.backup-selection:hover:not(:disabled),.backup-options button:hover:not(:disabled){filter:brightness(1.15)}
  @media(max-width:650px){.location-row{align-items:flex-start;flex-direction:column}.location-controls{flex:auto;width:100%}.backup-heading{flex-wrap:wrap}.backup-controls>.backup-hint{display:none}.backup-dialog header,.backup-dialog footer,.backup-dialog-content{padding:16px}}
</style>
