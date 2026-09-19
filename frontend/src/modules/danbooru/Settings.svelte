<script lang="ts">
  import { getContext, onDestroy } from 'svelte';
  import { SETTINGS_SESSION, type SettingsSession } from '../../lib/settingsSession';
  import { compactSegmentClass, iconPath, formatByteCount } from '../../lib/settingsControls';
  import { danbooruApi as api } from './api';
  import type { DanbooruCredentialStatus, FolderInfo, FolderRemovalMode, FolderRemovalPreview, ToolInfo, ToolStatus } from './apiTypes';
  import { MODULE_NAME } from './identity';
  import { activeRating, artistNotificationIntervalMinutes, artistNotificationsEnabled, duplicateScope, duplicatesOnly, fitMode, heartSpamEnabled, homeLayout, imagePageSize, imagePageSizeOptions, imageRefreshToken, imageSize, mediaPlayback, sidebarOpen, sortBy, sortOrder, startupView, tagBannerHeight } from './stores';
  import type { ArtistNotificationIntervalMinutes, DuplicateScope, FitMode, HomeLayout, ImagePageSize, MediaPlayback, StartupView } from './stores';
  import { gridSizeOptions, type GridSize } from '../../lib/gridPreferences';
  import LibraryImportSettings from './components/LibraryImportSettings.svelte';
  export let selectedSection: string;
  export let query = '';
  const session = getContext<SettingsSession>(SETTINGS_SESSION);
  let folders: FolderInfo[] = [];
  let folderMessage = '';
  let folderRemovalFolder: FolderInfo | null = null;
  let folderRemovalPreview: FolderRemovalPreview | null = null;
  let folderRemovalBusy = false;
  let folderRemovalError = '';
  let syncStatus: { status: string; output?: string; progress?: number; total?: number } | null = null;
  let tools: ToolInfo[] = [];
  let activeToolId = '';
  let activeToolStatus: ToolStatus | null = null;
  let toolPoller: ReturnType<typeof setTimeout> | null = null;
  let toolError = '';
  let credentials: DanbooruCredentialStatus | null = null;
  let credentialUsername = '';
  let credentialApiKey = '';
  let credentialBusy = false;
  let credentialMessage = '';
  let credentialError = '';
  let foldersLoaded = false;
  let toolsLoaded = false;
  let credentialsLoaded = false;
  let foldersRequest: Promise<void> | null = null;
  let toolsRequest: Promise<void> | null = null;
  let credentialsRequest: Promise<void> | null = null;

  // Registered folders plus top-level indexed folders (subfolder labels like
  // "Danbooru\x" stay out of the management list; the sidebar still shows them).
  $: libraryFolders = folders.filter(
    folder => folder.registered || (!folder.name.includes('\\') && !folder.name.includes('/'))
  );
  $: syncRunning = syncStatus?.status === 'running';
  $: toolRunning = activeToolStatus?.status === 'running' || activeToolStatus?.status === 'cancelling';
  $: syncTool = tools.find(tool => tool.id === 'sync');
  $: safetyTools = tools.filter(tool => ['clean-sidecars', 'sqlite'].includes(tool.id));
  $: totalIndexedImages = libraryFolders.reduce((total, folder) => total + folder.count, 0);

  async function loadFolders(force = false): Promise<void> {
    if (foldersRequest) return foldersRequest;
    if (foldersLoaded && !force) return;
    foldersRequest = api.getFolders()
      .then(value => {
        folders = value;
        foldersLoaded = true;
      })
      .finally(() => {
        foldersRequest = null;
      });
    return foldersRequest;
  }

  function stopToolPolling() {
    if (toolPoller) {
      clearTimeout(toolPoller);
      toolPoller = null;
    }
  }

  function scheduleToolPolling(delay = 1500) {
    if (!activeToolId || toolPoller) return;
    toolPoller = setTimeout(() => {
      toolPoller = null;
      void pollActiveTool();
    }, delay);
  }

  async function pollActiveTool() {
    if (!activeToolId) return;
    try {
      activeToolStatus = await api.getToolStatus(activeToolId);
    } catch (error) {
      toolError = error instanceof Error ? error.message : String(error);
      scheduleToolPolling(2200);
      return;
    }
    if (activeToolId === 'sync') syncStatus = activeToolStatus;
    if (!['running', 'cancelling'].includes(activeToolStatus.status)) {
      stopToolPolling();
      tools = await api.getTools();
      toolsLoaded = true;
      await loadFolders(true);
      imageRefreshToken.update(n => n + 1);
    } else {
      scheduleToolPolling();
    }
  }

  function startToolPolling(toolId: string) {
    activeToolId = toolId;
    activeToolStatus = { status: 'running', output: '', progress: 0, total: 0 };
    if (toolId === 'sync') syncStatus = activeToolStatus;
    stopToolPolling();
    scheduleToolPolling(0);
  }

  async function loadTools(): Promise<void> {
    if (toolsRequest) return toolsRequest;
    if (toolsLoaded) return;
    toolsRequest = api.getTools()
      .then(value => {
        tools = value;
        toolsLoaded = true;
        const sync = value.find(tool => tool.id === 'sync');
        syncStatus = sync ?? null;
        const active = value.find(tool => tool.status === 'running' || tool.status === 'cancelling');
        if (active) startToolPolling(active.id);
      })
      .finally(() => {
        toolsRequest = null;
      });
    return toolsRequest;
  }

  async function loadCredentials(): Promise<void> {
    if (credentialsRequest) return credentialsRequest;
    if (credentialsLoaded) return;
    credentialsRequest = api.getDanbooruCredentials()
      .then(value => {
        credentials = value;
        credentialUsername = value.username ?? '';
      })
      .catch(error => {
        credentials = null;
        credentialUsername = '';
        credentialError = error instanceof Error ? error.message : String(error);
      })
      .finally(() => {
        credentialsLoaded = true;
        credentialsRequest = null;
      });
    return credentialsRequest;
  }

  async function ensureSectionData(section: string): Promise<void> {
    if (section === 'library') {
      await Promise.all([loadFolders(), loadTools()]);
    } else if (section === 'account') {
      await loadCredentials();
    } else if (section === 'maintenance') {
      await Promise.all([loadTools(), loadFolders()]);

    }
  }

  $: void ensureSectionData(selectedSection);

  async function saveDanbooruCredentials() {
    if (credentialBusy) return;
    credentialBusy = true;
    credentialError = '';
    credentialMessage = '';
    try {
      credentials = await api.saveDanbooruCredentials(credentialUsername.trim(), credentialApiKey.trim() || undefined);
      credentialUsername = credentials.username ?? '';
      credentialApiKey = '';
      credentialMessage = 'Credentials saved securely for this operating-system user.';
    } catch (error) {
      credentialError = error instanceof Error ? error.message : String(error);
    } finally {
      credentialBusy = false;
    }
  }

  async function checkCredentials() {
    if (credentialBusy) return;
    credentialBusy = true;
    credentialError = '';
    credentialMessage = '';
    try {
      const result = await api.checkDanbooruCredentials();
      credentialMessage = `Connected as ${result.username}${result.user_id ? ` (user ${result.user_id})` : ''}.`;
    } catch (error) {
      credentialError = error instanceof Error ? error.message : String(error);
    } finally {
      credentialBusy = false;
    }
  }

  async function clearDanbooruCredentials() {
    if (!confirm('Remove the saved Danbooru username and API key from this computer?')) return;
    credentialBusy = true;
    credentialError = '';
    try {
      credentials = await api.clearDanbooruCredentials();
      credentialUsername = credentials.username ?? '';
      credentialApiKey = '';
      credentialMessage = credentials.source === 'environment'
        ? 'Saved credentials removed. Environment credentials are still active.'
        : 'Saved credentials removed.';
    } catch (error) {
      credentialError = error instanceof Error ? error.message : String(error);
    } finally {
      credentialBusy = false;
    }
  }

  async function beginTool(toolId: string, runner: () => Promise<{ status: string; active_tool_id?: string }>) {
    if (toolRunning) return;
    toolError = '';
    try {
      const result = await runner();
      const runningId = result.active_tool_id ?? toolId;
      if (result.status === 'started' || result.status === 'already_running' || result.status === 'busy') {
        startToolPolling(runningId);
      }
    } catch (error) {
      toolError = error instanceof Error ? error.message : String(error);
    }
  }

  function maintenanceDisplayName(tool: ToolInfo) {
    if (tool.id === 'clean-sidecars') return 'Clean orphan sidecars';
    if (tool.id === 'sqlite') return 'Rebuild database (recovery)';
    return tool.name;
  }

  async function runMaintenanceTool(tool: ToolInfo) {
    if (tool.id === 'clean-sidecars' && !confirm('Clean sidecars whose media files are missing? This removes orphan metadata files.')) return;
    if (tool.id === 'sqlite' && !confirm('Rebuild the regenerable image database from sidecars? User data is kept separately.')) return;
    await beginTool(tool.id, () => api.runTool(tool.id));
  }

  async function cancelActiveTool() {
    if (!activeToolId || !toolRunning) return;
    try {
      activeToolStatus = { ...(activeToolStatus ?? { output: '' }), status: 'cancelling', cancellable: false };
      await api.cancelTool(activeToolId);
    } catch (error) {
      toolError = error instanceof Error ? error.message : String(error);
    }
  }

  async function openFolderRemoval(folder: FolderInfo) {
    if (folderRemovalBusy) return;
    folderRemovalFolder = folder;
    folderRemovalPreview = null;
    folderRemovalError = '';
    folderRemovalBusy = true;
    try {
      folderRemovalPreview = await api.getFolderRemovalPreview(folder.root_id ?? folder.selector);
    } catch (error) {
      folderRemovalError = error instanceof Error ? error.message : String(error);
    } finally {
      folderRemovalBusy = false;
    }
  }

  function closeFolderRemoval() {
    if (folderRemovalBusy) return;
    folderRemovalFolder = null;
    folderRemovalPreview = null;
    folderRemovalError = '';
  }

  async function confirmFolderRemoval(mode: FolderRemovalMode) {
    if (!folderRemovalFolder || !folderRemovalPreview || folderRemovalBusy) return;
    const folder = folderRemovalFolder;
    folderRemovalBusy = true;
    folderRemovalError = '';
    folderMessage = '';
    try {
      const result = await api.removeFolder(folder.root_id ?? folder.selector, mode);
      folders = folders.filter(item => item.selector !== folder.selector);
      imageRefreshToken.update(n => n + 1);
      folderMessage = mode === 'delete_sidecars'
        ? `Removed ${result.files_removed.toLocaleString()} indexed images and ${result.sidecar_files_removed.toLocaleString()} current sidecar files. External images and sidecar history were preserved.`
        : `Removed ${result.files_removed.toLocaleString()} indexed images from SQLite. Sidecars and external images were preserved.`;
      folderRemovalFolder = null;
      folderRemovalPreview = null;
    } catch (error) {
      folderRemovalError = error instanceof Error ? error.message : String(error);
    } finally {
      folderRemovalBusy = false;
    }
  }

  const ratingOptions: { value: string | null; label: string; description: string }[] = [
    { value: null, label: 'All', description: 'Show every rating' },
    { value: 'g', label: 'General', description: 'Default safe browse' },
    { value: 's', label: 'Sensitive', description: 'Include sensitive posts' },
    { value: 'q', label: 'Questionable', description: 'Questionable only' },
    { value: 'e', label: 'Explicit', description: 'Explicit only' },
    { value: 'u', label: 'Unrated', description: 'Missing sidecar rating' },
  ];

  const fitModeOptions: { value: FitMode; label: string; description: string }[] = [
    { value: 'fit', label: 'Crop Fill', description: 'Dense grid with filled cards' },
    { value: 'contain', label: 'Contain', description: 'Show the full image shape' },
  ];

  const startupOptions: { value: StartupView; label: string }[] = [
    { value: 'home', label: 'Home' },
    { value: 'gallery', label: 'Browse' },
    { value: 'last', label: 'Last visited' },
  ];

  const homeLayoutOptions: { value: HomeLayout; label: string }[] = [
    { value: 'discovery', label: 'Discovery' },
    { value: 'classic', label: 'Classic' },
  ];

  const sortOptions = [
    { value: 'date', label: 'Date' },
    { value: 'downloaded', label: 'Downloaded' },
    { value: 'score', label: 'Score' },
    { value: 'views', label: 'Viewed' },
    { value: 'tags', label: 'Most tagged' },
    { value: 'random', label: 'Random' },
    { value: 'name', label: 'Name' },
    { value: 'size', label: 'File size' },
  ];

  const playbackOptions: { value: MediaPlayback; label: string; description: string }[] = [
    { value: 'never', label: 'Never', description: 'Keep GIFs and videos still until explicitly played.' },
    { value: 'hover', label: 'On hover', description: 'Animate while the pointer is over the media.' },
    { value: 'always', label: 'Always', description: 'Automatically animate visible media.' },
  ];

  const duplicateOptions: { value: DuplicateScope | 'off'; label: string; description: string }[] = [
    { value: 'off', label: 'Off', description: 'Normal browsing' },
    { value: 'all', label: 'All', description: 'Every duplicate group' },
    { value: 'same_folder', label: 'Same Folder', description: 'Duplicates inside one folder' },
    { value: 'different_folder', label: 'Different Folders', description: 'Duplicates split across folders' },
  ];

  const bannerPresets = [
    { label: 'Low', value: 360 },
    { label: 'Tall', value: 520 },
    { label: 'Huge', value: 660 },
  ];

  const artistNotificationIntervalOptions: ArtistNotificationIntervalMinutes[] = [5, 15, 30, 60];
  function setDuplicateMode(value: DuplicateScope | 'off') {
    if (value === 'off') {
      duplicatesOnly.set(false);
      return;
    }
    duplicateScope.set(value);
    duplicatesOnly.set(true);
  }

  $: currentDuplicateMode = $duplicatesOnly ? $duplicateScope : 'off';
  $: selectedImageSize = gridSizeOptions.find(option => option.value === $imageSize) ?? gridSizeOptions[1];
  $: session.setBusy('danbooru', toolRunning);
  const unregister = session.register('danbooru', {
    reloadFolders: () => loadFolders(true),
    refreshImages: () => imageRefreshToken.update(n => n + 1),
    startToolPolling,
    resumeMedia: () => $mediaPlayback === 'always',
    dismissOverlay: () => {
      if (!folderRemovalFolder) return false;
      closeFolderRemoval();
      return true;
    },
  });
  onDestroy(() => { stopToolPolling(); unregister(); });
</script>

{#if !query}
        {#if activeToolStatus && ['library', 'maintenance'].includes(selectedSection)}
          <section class="mb-4 rounded-xl border border-purple-400/20 bg-purple-500/[0.055] p-3.5">
            <div class="flex items-center justify-between gap-4">
              <div>
                <div class="text-xs font-semibold uppercase tracking-wider {activeToolStatus.status === 'error' ? 'text-red-300' : activeToolStatus.status === 'done' ? 'text-green-300' : 'text-purple-200'}">
                  {activeToolStatus.status === 'running' ? (activeToolStatus.stage ?? ('Running ' + activeToolId)) : activeToolStatus.status}
                </div>
                {#if activeToolStatus.stage_total && activeToolStatus.stage_total > 1}
                  <div class="mt-0.5 text-[10px] text-gray-600">Stage {activeToolStatus.stage_index ?? 1} of {activeToolStatus.stage_total}</div>
                {/if}
              </div>
              {#if toolRunning && activeToolStatus.cancellable !== false}
                <button class="rounded-lg border border-red-400/20 px-2.5 py-1.5 text-xs text-red-300 hover:bg-red-500/10" type="button" on:click={cancelActiveTool}>Cancel</button>
              {/if}
            </div>
            {#if activeToolStatus.total && activeToolStatus.total > 0}
              <div class="mt-3">
                <div class="mb-1 flex justify-between text-[10px] text-gray-500"><span>{activeToolStatus.progress ?? 0} / {activeToolStatus.total}</span><span>{Math.round(((activeToolStatus.progress ?? 0) / activeToolStatus.total) * 100)}%</span></div>
                <div class="h-1.5 overflow-hidden rounded-full bg-[#1a1a24]"><div class="h-full rounded-full bg-purple-400 transition-all" style="width: {((activeToolStatus.progress ?? 0) / activeToolStatus.total) * 100}%"></div></div>
              </div>
            {/if}
            {#if activeToolStatus.output}<pre class="mt-3 max-h-28 overflow-auto whitespace-pre-wrap rounded-lg bg-black/25 p-2.5 text-[10px] leading-relaxed text-gray-500">{activeToolStatus.output}</pre>{/if}
          </section>
        {/if}

{/if}
{#if !query}
{#if selectedSection === 'account'}
          <div class="mx-auto max-w-3xl space-y-4">
            <details id="setting-danbooru-access" class="group overflow-hidden rounded-xl border border-[#292938] bg-[#111118]">
              <summary class="flex cursor-pointer list-none items-center justify-between gap-4 px-4 py-3.5">
                <div class="flex items-center gap-3"><span class="grid h-9 w-9 place-items-center rounded-xl bg-amber-500/10 text-amber-300"><svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4" /></svg></span><div class="text-sm font-semibold text-gray-200">Danbooru credentials</div></div>
                <div class="flex items-center gap-3"><span class="rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase {credentials?.configured ? 'border-green-400/20 bg-green-500/10 text-green-300' : 'border-amber-400/20 bg-amber-500/10 text-amber-300'}">{!credentialsLoaded ? 'Loading…' : credentials?.configured ? (credentials.source === 'environment' ? 'Environment' : 'Configured') : 'Not configured'}</span><svg class="h-4 w-4 text-gray-600 transition-transform group-open:rotate-180" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 9l6 6 6-6" /></svg></div>
              </summary>
              <div class="border-t border-[#242432] bg-black/10 p-4">
                {#if credentials?.source === 'environment'}<p class="mb-3 rounded-lg border border-cyan-400/15 bg-cyan-500/[0.06] px-3 py-2 text-xs text-cyan-200">Environment credentials are active and override saved values.</p>{/if}
                <div class="grid gap-3 sm:grid-cols-2">
                  <label><span class="mb-1 block text-[11px] font-medium text-gray-500">Username</span><input class="w-full rounded-lg border border-[#303040] bg-[#0d0d13] px-3 py-2 text-sm text-gray-200 outline-none focus:border-purple-400/60" type="text" autocomplete="username" bind:value={credentialUsername} /></label>
                  <label><span class="mb-1 block text-[11px] font-medium text-gray-500">API key {credentials?.has_api_key ? '(leave blank to keep)' : ''}</span><input class="w-full rounded-lg border border-[#303040] bg-[#0d0d13] px-3 py-2 text-sm text-gray-200 outline-none focus:border-purple-400/60" type="password" autocomplete="off" bind:value={credentialApiKey} /></label>
                </div>
                <div class="mt-3 flex flex-wrap gap-2"><button class="rounded-lg bg-purple-500/20 px-3 py-2 text-xs font-semibold text-purple-100 hover:bg-purple-500/30 disabled:opacity-50" type="button" disabled={credentialBusy || !credentialUsername.trim()} on:click={saveDanbooruCredentials}>Save securely</button><button class="rounded-lg border border-[#303040] px-3 py-2 text-xs text-gray-300 hover:bg-white/5 disabled:opacity-50" type="button" disabled={credentialBusy || !credentials?.configured} on:click={checkCredentials}>Test connection</button>{#if credentials?.source === 'saved'}<button class="rounded-lg px-3 py-2 text-xs text-red-300 hover:bg-red-500/10 disabled:opacity-50" type="button" disabled={credentialBusy} on:click={clearDanbooruCredentials}>Remove saved</button>{/if}</div>
                {#if credentialMessage}<p class="mt-2 text-xs text-green-400">{credentialMessage}</p>{/if}{#if credentialError}<p class="mt-2 text-xs text-red-400">{credentialError}</p>{/if}
              </div>
            </details>
          </div>
{:else if selectedSection === 'browsing'}
          <div class="mx-auto max-w-3xl space-y-4">
            <section class="overflow-hidden rounded-xl border border-[#292938] bg-[#111118]">
              <div class="divide-y divide-[#22222e]">
                <div id="setting-startup-view" class="flex items-center justify-between gap-5 px-4 py-3">
                  <div class="text-sm font-medium text-gray-200">Startup view</div>
                  <div class="flex shrink-0 divide-x divide-[#303040] overflow-hidden rounded-lg border border-[#303040]">
                    {#each startupOptions as option}
                      <button class={compactSegmentClass($startupView === option.value)} type="button" on:click={() => startupView.set(option.value)}>{option.label}</button>
                    {/each}
                  </div>
                </div>
                <div id="setting-home-layout" class="flex items-center justify-between gap-5 px-4 py-3">
                  <div class="text-sm font-medium text-gray-200">Home layout</div>
                  <div class="flex shrink-0 divide-x divide-[#303040] overflow-hidden rounded-lg border border-[#303040]">
                    {#each homeLayoutOptions as option}
                      <button class={compactSegmentClass($homeLayout === option.value)} type="button" on:click={() => homeLayout.set(option.value)}>{option.label}</button>
                    {/each}
                  </div>
                </div>
                <div id="setting-rating-filter" class="flex items-center justify-between gap-5 px-4 py-3">
                  <div class="text-sm font-medium text-gray-200">Default rating</div>
                  <select class="w-44 rounded-lg border border-[#303040] bg-[#0d0d13] px-3 py-2 text-xs text-gray-200 outline-none focus:border-purple-400/60" value={$activeRating ?? ''} on:change={(event) => activeRating.set((event.currentTarget as HTMLSelectElement).value || null)}>
                    {#if $activeRating?.includes(',')}<option value={$activeRating}>Multiple ratings</option>{/if}
                    {#each ratingOptions as option}<option value={option.value ?? ''}>{option.label}</option>{/each}
                  </select>
                </div>
                <div id="setting-browse-sort" class="flex items-center justify-between gap-5 px-4 py-3">
                  <div class="text-sm font-medium text-gray-200">Browse sort</div>
                  <div class="flex shrink-0 items-center gap-2">
                    <select class="w-36 rounded-lg border border-[#303040] bg-[#0d0d13] px-3 py-2 text-xs text-gray-200 outline-none focus:border-purple-400/60" value={$sortBy} on:change={(event) => sortBy.set((event.currentTarget as HTMLSelectElement).value)}>
                      {#each sortOptions as option}<option value={option.value}>{option.label}</option>{/each}
                    </select>
                    <button
                      class="grid h-8 w-8 place-items-center rounded-lg border border-[#303040] bg-[#0d0d13] text-gray-300 transition-colors hover:border-purple-400/50 hover:bg-purple-500/10 hover:text-purple-100"
                      type="button"
                      title="Sort order: {$sortOrder === 'desc' ? 'Descending' : 'Ascending'}"
                      aria-label="Toggle sort order; currently {$sortOrder === 'desc' ? 'descending' : 'ascending'}"
                      on:click={() => sortOrder.update(order => order === 'desc' ? 'asc' : 'desc')}
                    >
                      <svg class="h-3.5 w-3.5 transition-transform {$sortOrder === 'asc' ? 'rotate-180' : ''}" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
                      </svg>
                    </button>
                  </div>
                </div>
                <div id="setting-page-size" class="flex items-center justify-between gap-5 px-4 py-3">
                  <div class="text-sm font-medium text-gray-200">Images per page</div>
                  <select class="w-32 rounded-lg border border-[#303040] bg-[#0d0d13] px-3 py-2 text-xs text-gray-200 outline-none focus:border-purple-400/60" value={$imagePageSize} on:change={(event) => imagePageSize.set(((event.currentTarget as HTMLSelectElement).value === 'all' ? 'all' : Number((event.currentTarget as HTMLSelectElement).value)) as ImagePageSize)}>
                    {#each imagePageSizeOptions as option}<option value={option.value}>{option.value === 'all' ? 'All images' : option.label}</option>{/each}
                  </select>
                </div>
              </div>
            </section>

            <section class="overflow-hidden rounded-xl border border-[#292938] bg-[#111118]">
              <div class="divide-y divide-[#22222e]">
                <div id="setting-sidebar" class="flex items-center justify-between gap-5 px-4 py-3">
                  <div class="text-sm font-medium text-gray-200">Sidebar default</div>
                  <button class="relative h-6 w-11 shrink-0 rounded-full transition-colors {$sidebarOpen ? 'bg-purple-500' : 'bg-[#2a2a3a]'}" type="button" role="switch" aria-label="Toggle library sidebar" aria-checked={$sidebarOpen} on:click={() => sidebarOpen.update(value => !value)}><span class="absolute left-0.5 top-0.5 h-5 w-5 rounded-full bg-white transition-transform {$sidebarOpen ? 'translate-x-5' : ''}"></span></button>
                </div>
                <div id="setting-heart-spam" class="flex items-center justify-between gap-5 px-4 py-3">
                  <div class="text-sm font-medium text-gray-200">Heart Spam button</div>
                  <button class="relative h-6 w-11 shrink-0 rounded-full transition-colors {$heartSpamEnabled ? 'bg-pink-500' : 'bg-[#2a2a3a]'}" type="button" role="switch" aria-label="Toggle Heart Spam" aria-checked={$heartSpamEnabled} on:click={() => heartSpamEnabled.update(value => !value)}><span class="absolute left-0.5 top-0.5 h-5 w-5 rounded-full bg-white transition-transform {$heartSpamEnabled ? 'translate-x-5' : ''}"></span></button>
                </div>
                <div id="setting-artist-notifications" class="flex items-center justify-between gap-5 px-4 py-3">
                  <div class="text-sm font-medium text-gray-200">Artist checks</div>
                  <div class="flex shrink-0 items-center gap-2">
                    <select
                      class="w-24 rounded-lg border border-[#303040] bg-[#0d0d13] px-2.5 py-2 text-xs text-gray-200 outline-none focus:border-cyan-400/60 disabled:opacity-50"
                      value={$artistNotificationIntervalMinutes}
                      disabled={!$artistNotificationsEnabled}
                      aria-label="Artist notification check interval"
                      on:change={(event) => artistNotificationIntervalMinutes.set(Number((event.currentTarget as HTMLSelectElement).value) as ArtistNotificationIntervalMinutes)}
                    >
                      {#each artistNotificationIntervalOptions as minutes}<option value={minutes}>{minutes} min</option>{/each}
                    </select>
                    <button class="relative h-6 w-11 shrink-0 rounded-full transition-colors {$artistNotificationsEnabled ? 'bg-cyan-500' : 'bg-[#2a2a3a]'}" type="button" role="switch" aria-label="Toggle artist notifications" aria-checked={$artistNotificationsEnabled} on:click={() => artistNotificationsEnabled.update(value => !value)}><span class="absolute left-0.5 top-0.5 h-5 w-5 rounded-full bg-white transition-transform {$artistNotificationsEnabled ? 'translate-x-5' : ''}"></span></button>
                  </div>
                </div>
              </div>
            </section>

            <section id="setting-duplicate-review" class="rounded-xl border border-[#292938] bg-[#111118] p-4">
              <div class="flex flex-wrap items-center justify-between gap-4">
                <div class="text-sm font-semibold text-gray-200">Duplicate review filter</div>
                <div class="flex divide-x divide-[#303040] overflow-hidden rounded-lg border border-[#303040]">
                  {#each duplicateOptions as option}<button class={compactSegmentClass(currentDuplicateMode === option.value)} type="button" title={option.description} on:click={() => setDuplicateMode(option.value)}>{option.label}</button>{/each}
                </div>
              </div>
            </section>
          </div>
{:else if selectedSection === 'display'}
          <div class="mx-auto max-w-3xl space-y-4">

            <section class="overflow-hidden rounded-xl border border-[#292938] bg-[#111118]">
              <div class="divide-y divide-[#22222e]">
                <div id="setting-gallery-card-size" class="flex items-center justify-between gap-5 px-4 py-3">
                  <div class="flex items-center gap-2 text-sm font-medium text-gray-200">Gallery card size <span class="rounded-full bg-pink-500/10 px-2 py-0.5 text-[10px] text-pink-200">{selectedImageSize.cardWidth}px</span></div>
                  <select class="w-40 rounded-lg border border-[#303040] bg-[#0d0d13] px-3 py-2 text-xs text-gray-200 outline-none focus:border-pink-400/60" value={$imageSize} on:change={(event) => imageSize.set((event.currentTarget as HTMLSelectElement).value as GridSize)}>
                    {#each gridSizeOptions as option}<option value={option.value}>{option.label}</option>{/each}
                  </select>
                </div>
                <div id="setting-image-fit" class="flex items-center justify-between gap-5 px-4 py-3">
                  <div class="text-sm font-medium text-gray-200">Image fit</div>
                  <div class="flex divide-x divide-[#303040] overflow-hidden rounded-lg border border-[#303040]">{#each fitModeOptions as option}<button class={compactSegmentClass($fitMode === option.value)} type="button" title={option.description} on:click={() => fitMode.set(option.value)}>{option.label}</button>{/each}</div>
                </div>
              </div>
            </section>

            <section class="overflow-hidden rounded-xl border border-[#292938] bg-[#111118]">
              <div class="divide-y divide-[#22222e]">
                <div id="setting-media-playback" class="flex items-center justify-between gap-5 px-4 py-3">
                  <div class="text-sm font-medium text-gray-200">Animated media</div>
                  <div class="flex shrink-0 divide-x divide-[#303040] overflow-hidden rounded-lg border border-[#303040]">{#each playbackOptions as option}<button class={compactSegmentClass($mediaPlayback === option.value)} type="button" on:click={() => mediaPlayback.set(option.value)}>{option.label}</button>{/each}</div>
                </div>
              </div>
            </section>

            <section id="setting-tag-banner" class="rounded-xl border border-[#292938] bg-[#111118] p-4">
              <div class="flex items-start justify-between gap-6">
                <div class="text-sm font-semibold text-gray-200">Tag banner height</div>
                <div class="w-[360px] max-w-[58%]">
                  <div class="flex items-center gap-3"><input class="min-w-0 flex-1 accent-pink-500" type="range" min="280" max="720" step="20" value={$tagBannerHeight} on:input={(event) => tagBannerHeight.set(Number((event.currentTarget as HTMLInputElement).value))} /><span class="w-14 text-right text-xs font-semibold text-pink-200">{$tagBannerHeight}px</span></div>
                  <div class="mt-2 flex justify-end divide-x divide-[#303040] overflow-hidden rounded-lg border border-[#303040]">{#each bannerPresets as preset}<button class={compactSegmentClass($tagBannerHeight === preset.value) + ' flex-1'} type="button" on:click={() => tagBannerHeight.set(preset.value)}>{preset.label}</button>{/each}</div>
                </div>
              </div>
            </section>
          </div>
{:else if selectedSection === 'library'}
          <div class="mx-auto max-w-3xl space-y-4">
            <LibraryImportSettings {toolRunning} surface="storage" />

            <section id="setting-library-health" class="overflow-hidden rounded-2xl border border-cyan-400/20 bg-[radial-gradient(circle_at_82%_0%,rgba(34,211,238,.14),transparent_38%),linear-gradient(135deg,#101a20,#101017_72%)] p-4">
              <div class="flex flex-wrap items-center justify-between gap-4">
                <div class="flex flex-wrap items-center gap-3">
                  <div class="flex items-center gap-2 text-sm font-semibold text-cyan-100"><span class="h-2 w-2 rounded-full {syncRunning ? 'animate-pulse bg-cyan-300' : 'bg-green-400'}"></span>Library: {!foldersLoaded || !toolsLoaded ? 'Loading' : syncRunning ? 'Indexing' : 'Ready'}</div>
                  <div class="flex flex-wrap gap-2">
                    <span class="rounded-full border border-cyan-300/10 bg-cyan-500/[0.07] px-2.5 py-1 text-[11px] text-cyan-100">{foldersLoaded ? `${libraryFolders.length} root${libraryFolders.length === 1 ? '' : 's'}` : 'Loading roots…'}</span>
                    <span class="rounded-full border border-white/5 bg-black/15 px-2.5 py-1 text-[11px] text-gray-300">{foldersLoaded ? `${totalIndexedImages.toLocaleString()} indexed images` : 'Loading image count…'}</span>
                  </div>
                </div>
                {#if syncTool}
                  <button id="setting-rescan" class="shrink-0 rounded-xl bg-cyan-500/15 px-4 py-2 text-xs font-semibold text-cyan-100 ring-1 ring-inset ring-cyan-300/15 hover:bg-cyan-500/25 disabled:opacity-50" type="button" disabled={toolRunning} on:click={() => runMaintenanceTool(syncTool)}>{syncTool.status === 'running' ? 'Re-scanning…' : 'Re-scan library'}</button>
                {/if}
              </div>
              {#if syncStatus && syncStatus.status !== 'idle'}
                <div class="mt-4 rounded-xl border border-white/5 bg-black/15 px-3 py-2.5">
                  <div class="flex items-center justify-between text-xs"><span class="{syncRunning ? 'text-cyan-200' : syncStatus.status === 'error' ? 'text-red-300' : 'text-green-300'}">{syncRunning ? ('Syncing' + (syncStatus.total ? (' - ' + (syncStatus.progress ?? 0) + ' / ' + syncStatus.total) : '…')) : syncStatus.status === 'error' ? 'Sync failed' : 'Sync complete'}</span>{#if syncRunning}<span class="h-3.5 w-3.5 animate-spin rounded-full border-2 border-cyan-300 border-t-transparent"></span>{/if}</div>
                  {#if syncRunning && syncStatus.total}<div class="mt-2 h-1.5 overflow-hidden rounded-full bg-[#15151d]"><div class="h-full rounded-full bg-cyan-400 transition-all" style="width: {((syncStatus.progress ?? 0) / syncStatus.total) * 100}%"></div></div>{/if}
                </div>
              {/if}
            </section>

            <LibraryImportSettings {toolRunning} surface="metadata" />
          </div>
{:else if selectedSection === 'maintenance'}
          <div class="mx-auto max-w-3xl space-y-4">
            <section class="overflow-hidden rounded-xl border border-[#292938] bg-[#111118]">
              <div class="border-b border-[#242432] px-4 py-3"><h4 class="text-sm font-semibold text-gray-200">Recovery maintenance</h4></div>
              <div class="divide-y divide-[#22222e]">
                {#each safetyTools as tool (tool.id)}
                  <div id={tool.id === 'sqlite' ? 'setting-rebuild' : 'setting-clean-sidecars'} class="flex items-start justify-between gap-4 px-4 py-3.5">
                    <div class="flex items-start gap-3"><span class="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-lg {tool.id === 'sqlite' ? 'bg-red-500/10 text-red-300' : 'bg-amber-500/10 text-amber-300'}"><svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">{#if tool.id === 'sqlite'}<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" d={iconPath('database')} />{:else}<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" d="M4 7h16M9 7V4h6v3m-8 0 1 13h8l1-13M10 11v5m4-5v5" />{/if}</svg></span><div><h4 class="text-sm font-semibold text-gray-200">{maintenanceDisplayName(tool)}</h4><p class="mt-0.5 text-xs leading-relaxed text-gray-500">{tool.description}</p>{#if tool.id === 'sqlite'}<p class="mt-1 text-[11px] text-red-200/60">Recovery only. The user database is kept separately.</p>{/if}</div></div>
                    <button class="shrink-0 rounded-lg border px-3 py-2 text-xs font-semibold disabled:opacity-50 {tool.id === 'sqlite' ? 'border-red-400/20 text-red-300 hover:bg-red-500/10' : 'border-amber-400/20 text-amber-300 hover:bg-amber-500/10'}" type="button" disabled={toolRunning} on:click={() => runMaintenanceTool(tool)}>{tool.status === 'running' ? 'Running…' : 'Run'}</button>
                  </div>
                {/each}
              </div>
            </section>

            <section id="setting-folder-sidecars" class="overflow-hidden rounded-xl border border-[#292938] bg-[#111118]">
              <div class="border-b border-[#242432] p-4">
                <h4 class="text-sm font-semibold text-gray-200">Folder sidecars</h4>
                <p class="mt-1 text-xs leading-relaxed text-gray-500">Permanently delete the central sidecar metadata for a registered {MODULE_NAME} folder. Your media files and the archived sidecar history are always kept.</p>
                {#if folderMessage}<p class="mt-2 text-xs text-green-400">{folderMessage}</p>{/if}
              </div>
              <div class="space-y-2 p-3">
                {#each libraryFolders.filter((folder) => folder.registered) as folder (folder.selector)}
                  <div class="flex items-center gap-3 rounded-xl border border-white/5 bg-[#0d0d13] px-3 py-2.5">
                    <span class="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-amber-500/10 text-amber-300"><svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" d={iconPath('folder')} /></svg></span>
                    <div class="min-w-0 flex-1"><div class="truncate text-sm font-semibold text-gray-200">{folder.name}</div><div class="mt-0.5 truncate text-xs text-gray-600" title={folder.path ?? ''}>{folder.path ?? ''}</div></div>
                    <button class="shrink-0 rounded-lg border border-red-400/20 px-3 py-1.5 text-xs text-red-300 transition-colors hover:bg-red-500/10 disabled:opacity-40" type="button" disabled={folderRemovalBusy} on:click={() => openFolderRemoval(folder)}>Delete sidecars…</button>
                  </div>
                {:else}
                  <div class="rounded-xl border border-dashed border-[#303040] px-4 py-8 text-center text-sm text-gray-500">No registered {MODULE_NAME} folders.</div>
                {/each}
              </div>
            </section>

            {#if toolError}<p class="rounded-xl border border-red-400/15 bg-red-500/[0.06] px-4 py-3 text-xs text-red-300">{toolError}</p>{/if}
          </div>
{/if}
{/if}

  {#if folderRemovalFolder}
    <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
    <div use:session.portal class="fixed inset-0 z-[140] grid place-items-center bg-black/80 p-4 backdrop-blur-sm" on:click={closeFolderRemoval}>
      <!-- svelte-ignore a11y_click_events_have_key_events -->
      <div
        class="w-full max-w-xl overflow-hidden rounded-2xl border border-red-300/20 bg-[#111117] shadow-2xl shadow-black/80"
        role="dialog"
        aria-modal="true"
        aria-labelledby="folder-removal-title"
        tabindex="-1"
        on:click|stopPropagation
      >
        <header class="flex items-start justify-between gap-4 border-b border-[#292936] bg-[radial-gradient(circle_at_85%_-30%,rgba(239,68,68,.16),transparent_52%)] px-5 py-4">
          <div>
            <div class="text-[10px] font-semibold uppercase tracking-[0.2em] text-red-300">Library root removal</div>
            <h3 id="folder-removal-title" class="mt-1 text-xl font-bold text-gray-100">What should be removed?</h3>
            <p class="mt-1 break-all text-xs text-gray-500">{folderRemovalFolder.path ?? folderRemovalFolder.name}</p>
          </div>
          <button class="grid h-8 w-8 shrink-0 place-items-center rounded-lg border border-[#303040] text-gray-500 hover:bg-white/5 hover:text-gray-200 disabled:opacity-40" type="button" disabled={folderRemovalBusy} aria-label="Cancel folder removal" on:click={closeFolderRemoval}>×</button>
        </header>

        <div class="space-y-4 p-5">
          <div class="flex items-center gap-3 rounded-xl border border-green-400/15 bg-green-500/[0.055] px-3.5 py-3">
            <span class="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-green-500/10 text-green-300">✓</span>
            <div><div class="text-xs font-semibold text-green-100">External images affected: 0</div><p class="mt-0.5 text-[11px] text-green-100/55">Neither choice moves, edits, or deletes your original media folder.</p></div>
          </div>

          {#if folderRemovalBusy && !folderRemovalPreview}
            <div class="flex items-center justify-center gap-3 rounded-xl border border-[#292938] bg-black/15 px-4 py-10 text-sm text-gray-400"><span class="h-4 w-4 animate-spin rounded-full border-2 border-cyan-300 border-t-transparent"></span>Calculating exact impact…</div>
          {:else if folderRemovalPreview}
            <div class="grid grid-cols-2 gap-3">
              <div class="rounded-xl border border-[#292938] bg-black/15 p-3"><div class="text-[10px] uppercase tracking-wider text-gray-600">SQLite records</div><div class="mt-1 text-lg font-bold text-gray-200">{folderRemovalPreview.indexed_files.toLocaleString()}</div><div class="text-[11px] text-gray-600">indexed images</div></div>
              <div class="rounded-xl border border-[#292938] bg-black/15 p-3"><div class="text-[10px] uppercase tracking-wider text-gray-600">Current sidecars</div><div class="mt-1 text-lg font-bold text-gray-200">{folderRemovalPreview.sidecar_files.toLocaleString()}</div><div class="text-[11px] text-gray-600">{formatByteCount(folderRemovalPreview.sidecar_bytes)}</div></div>
            </div>

            <div class="space-y-2.5">
              <button class="group flex w-full items-start gap-3 rounded-xl border border-cyan-400/15 bg-cyan-500/[0.045] px-4 py-3.5 text-left transition-colors hover:border-cyan-300/35 hover:bg-cyan-500/[0.09] disabled:opacity-45" type="button" disabled={folderRemovalBusy} on:click={() => confirmFolderRemoval('unindex_only')}>
                <span class="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-cyan-500/10 text-cyan-300"><svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" d={iconPath('database')} /></svg></span>
                <span class="min-w-0 flex-1"><span class="block text-sm font-semibold text-cyan-100">Un-index only</span><span class="mt-1 block text-xs leading-relaxed text-gray-500">Remove the folder registration and {folderRemovalPreview.indexed_files.toLocaleString()} image records from SQLite. Keep all sidecars.</span></span>
                <span class="mt-1 text-cyan-300 transition-transform group-hover:translate-x-0.5">→</span>
              </button>

              <button class="group flex w-full items-start gap-3 rounded-xl border border-red-400/20 bg-red-500/[0.045] px-4 py-3.5 text-left transition-colors hover:border-red-300/40 hover:bg-red-500/[0.09] disabled:opacity-45" type="button" disabled={folderRemovalBusy} on:click={() => confirmFolderRemoval('delete_sidecars')}>
                <span class="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-red-500/10 text-red-300"><svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" d="M4 7h16M9 7V4h6v3m-8 0 1 13h8l1-13M10 11v5m4-5v5" /></svg></span>
                <span class="min-w-0 flex-1"><span class="block text-sm font-semibold text-red-100">Delete sidecars &amp; un-index</span><span class="mt-1 block text-xs leading-relaxed text-gray-500">Permanently delete {folderRemovalPreview.sidecar_files.toLocaleString()} current central sidecars ({formatByteCount(folderRemovalPreview.sidecar_bytes)}), then remove the SQLite records.</span></span>
                <span class="mt-1 text-red-300 transition-transform group-hover:translate-x-0.5">→</span>
              </button>
            </div>

            <p class="text-center text-[11px] text-gray-600">Archived sidecar history is preserved by both choices.</p>
          {/if}

          {#if folderRemovalError}<p class="rounded-lg border border-red-400/15 bg-red-500/[0.06] px-3 py-2 text-xs text-red-300">{folderRemovalError}</p>{/if}
          <div class="flex justify-end"><button class="rounded-lg border border-[#303040] px-3 py-2 text-xs text-gray-300 hover:bg-white/5 disabled:opacity-40" type="button" disabled={folderRemovalBusy} on:click={closeFolderRemoval}>Cancel</button></div>
        </div>
      </div>
    </div>
  {/if}
