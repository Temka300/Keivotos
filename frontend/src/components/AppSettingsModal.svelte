<script lang="ts">
  import { createEventDispatcher, onMount, tick } from 'svelte';
  import { get } from 'svelte/store';
  import {
    api,
    type DanbooruCredentialStatus,
    type FolderInfo,
    type FolderRemovalMode,
    type FolderRemovalPreview,
    type ToolInfo,
    type ToolStatus,
  } from '../lib/api';
  import { filesApi, type AttachmentStore, type SourceInfo } from '../lib/filesApi';
  import { suiteApi, type FolderBatchResult } from '../lib/suiteApi';
  import BackupRestoreSettings from './BackupRestoreSettings.svelte';
  import LibraryImportSettings from './LibraryImportSettings.svelte';
  import ManageFoldersDialog from './ManageFoldersDialog.svelte';
  import PathAutocomplete from './PathAutocomplete.svelte';
  import ThumbnailCacheSettings from './ThumbnailCacheSettings.svelte';
  import { SUITE_NAME } from '../lib/product';
  import { MODULE_NAME } from '../modules/danbooru/identity';
  import { prepareSettingsPresentation, restoreSettingsPresentation } from '../lib/settingsPresentation';
  import {
    activeRating,
    artistNotificationIntervalMinutes,
    artistNotificationsEnabled,
    duplicateScope,
    duplicatesOnly,
    enabledModules,
    fitMode,
    heartSpamEnabled,
    homeLayout,
    imagePageSize,
    imagePageSizeOptions,
    imageRefreshToken,
    imageSize,
    gridSizeOptions,
    interfaceScale,
    mediaPlayback,
    motionPreference,
    sidebarOpen,
    sortBy,
    sortOrder,
    startupModule,
    startupView,
    suiteModules,
    tagBannerHeight,
  } from '../lib/stores';
  import type { ArtistNotificationIntervalMinutes, DuplicateScope, FitMode, HomeLayout, ImagePageSize, GridSize, InterfaceScale, MediaPlayback, MotionPreference, StartupModule, StartupView } from '../lib/stores';

  const dispatch = createEventDispatcher<{ close: void }>();

  let selectedSection = 'appearance';
  let settingsSearch = '';

  // Settings are grouped by scope, not by function: General affects the whole
  // suite, Files is the always-on base, and each module (Danbooru) is its own
  // group that only appears while the module is enabled.
  const sectionGroups = [
    { id: 'general', label: 'General', module: null as string | null },
    { id: 'files', label: 'Files', module: null as string | null },
    { id: 'danbooru', label: MODULE_NAME, module: 'danbooru' as string | null },
  ];

  const sections = [
    { id: 'appearance', group: 'general', label: 'Appearance', icon: 'palette' },
    { id: 'startup', group: 'general', label: 'Startup', icon: 'window' },
    { id: 'storage', group: 'general', label: 'Storage', icon: 'folder' },
    { id: 'backup', group: 'general', label: 'Backup', icon: 'shield' },
    { id: 'roots', group: 'files', label: 'Folders', icon: 'folder' },
    { id: 'files', group: 'files', label: 'Attachments', icon: 'image' },
    { id: 'account', group: 'danbooru', label: 'Account', icon: 'database' },
    { id: 'browsing', group: 'danbooru', label: 'Browsing', icon: 'window' },
    { id: 'display', group: 'danbooru', label: 'Display', icon: 'palette' },
    { id: 'library', group: 'danbooru', label: 'Library', icon: 'folder' },
    { id: 'maintenance', group: 'danbooru', label: 'Advanced', icon: 'shield' },
  ];

  $: visibleGroups = sectionGroups.filter(
    (group) => !group.module || $enabledModules.includes(group.module),
  );
  $: visibleSections = sections.filter((section) =>
    visibleGroups.some((group) => group.id === section.group),
  );
  // If the selected section belongs to a module that just got disabled, fall
  // back to the first always-present section.
  $: if (!visibleSections.some((section) => section.id === selectedSection)) {
    selectedSection = 'appearance';
  }

  type SettingSearchItem = {
    id: string;
    section: string;
    label: string;
    description: string;
    keywords: string[];
  };

  const settingSearchItems: SettingSearchItem[] = [
    { id: 'motion', section: 'appearance', label: 'Interface motion', description: 'Follow the system or reduce interface animation.', keywords: ['animation', 'reduced motion', 'accessibility'] },
    { id: 'interface-scale', section: 'appearance', label: 'Interface scale', description: 'Use the default or a roomier readable scale.', keywords: ['density', 'comfortable', 'readability', 'text'] },
    { id: 'startup-module', section: 'startup', label: 'Startup destination', description: `Choose which surface ${SUITE_NAME} opens on launch.`, keywords: ['files', 'module', 'last used', 'launch', 'open'] },
    { id: 'folder-roles', section: 'roots', label: 'Folders', description: `Add, re-scan, relocate, or remove folders, and assign each to Files or ${MODULE_NAME}.`, keywords: ['role', 'module', 'adopt', 'release', 'sidebar', 'visible', 'assign', 'folders', 'sources', 'library', 'roots', 'rescan', 'relocate', 'remove', 'path', 'register'] },
    { id: 'thumbnail-cache', section: 'storage', label: 'Thumbnail cache', description: 'Manage the three derived thumbnail tiers and size limit.', keywords: ['300', '600', '1200', 'cleanup', 'cache'] },
    { id: 'backup', section: 'backup', label: 'Backup', description: `Choose protected components for the fixed ${SUITE_NAME} backup location.`, keywords: ['snapshot', 'database', 'sidecar', 'destination', 'size', 'metadata'] },
    { id: 'restore', section: 'backup', label: 'Restore', description: `Validate and restore a ${SUITE_NAME} backup bundle with rollback.`, keywords: ['recovery', 'rollback', 'backup'] },
    { id: 'local-recovery', section: 'backup', label: 'Automatic local recovery', description: 'Keep rotating user database checkpoints.', keywords: ['checkpoint', 'user sqlite', 'favorites', 'collections', 'automatic'] },
    { id: 'attachment-location', section: 'files', label: 'Attachment storage', description: 'Choose where origin-note images and videos are saved.', keywords: ['attachment', 'image', 'video', 'origin note', 'screenshot', 'storage', 'location', 'folder', 'path'] },
    { id: 'danbooru-access', section: 'account', label: 'Danbooru access', description: 'Manage encrypted credentials.', keywords: ['username', 'api key', 'credentials', 'connection'] },
    { id: 'startup-view', section: 'browsing', label: 'Startup view', description: `Choose which ${MODULE_NAME} page opens first.`, keywords: ['home', 'browse', 'last page', 'launch', 'gallery'] },
    { id: 'home-layout', section: 'browsing', label: 'Home layout', description: 'Use the new discovery dashboard or restore the preserved classic Home.', keywords: ['home', 'classic', 'legacy', 'old design', 'discovery', 'dashboard'] },
    { id: 'rating-filter', section: 'browsing', label: 'Default rating', description: 'Choose the rating used for normal browsing.', keywords: ['general', 'sensitive', 'questionable', 'explicit', 'unrated'] },
    { id: 'browse-sort', section: 'browsing', label: 'Browse sort', description: 'Choose the persisted image order.', keywords: ['date', 'downloaded', 'score', 'views', 'name', 'size'] },
    { id: 'page-size', section: 'browsing', label: 'Images per page', description: 'Choose the normal grid page size.', keywords: ['pagination', '10', '20', '30', '50', 'all'] },
    { id: 'sidebar', section: 'browsing', label: 'Sidebar recovery', description: 'Mirror the draggable Browse and Tags edge grip state.', keywords: ['folders', 'visible', 'navigation', 'grip', 'handle', 'draggable'] },
    { id: 'heart-spam', section: 'browsing', label: 'Heart Spam', description: 'Show the playful heart action in ImageDetail.', keywords: ['image detail', 'button'] },
    { id: 'artist-notifications', section: 'browsing', label: 'Artist notifications', description: 'Check followed artists while the app is open.', keywords: ['danbooru', 'followed', 'polling', 'bell', 'timer', 'interval', 'manual check'] },
    { id: 'duplicate-review', section: 'browsing', label: 'Duplicate review', description: 'Choose which duplicate groups to review.', keywords: ['same folder', 'different folders', 'review'] },
    { id: 'gallery-card-size', section: 'display', label: 'Gallery card size', description: 'Set the image-grid scale.', keywords: ['small', 'medium', 'large', 'huge', 'gigantic', 'absurd'] },
    { id: 'image-fit', section: 'display', label: 'Image fit', description: 'Crop cards or preserve the full image.', keywords: ['crop', 'contain', 'fill'] },
    { id: 'media-playback', section: 'display', label: 'Animated media', description: 'Control GIF and video playback.', keywords: ['autoplay', 'hover', 'never', 'always', 'gif', 'video'] },
    { id: 'tag-banner', section: 'display', label: 'Tag banner height', description: 'Set tag and artist banner height.', keywords: ['low', 'tall', 'huge', 'artist'] },
    { id: 'library-health', section: 'library', label: 'Library health', description: 'See indexed folders, images, and scan state.', keywords: ['status', 'count', 'index'] },
    { id: 'rescan', section: 'library', label: 'Re-scan library', description: 'Incrementally reconcile the local index.', keywords: ['sync', 'sqlite', 'changed', 'removed'] },
    { id: 'storage-location', section: 'library', label: 'Generated metadata location', description: 'See where databases, sidecars, and derived files live.', keywords: ['documents', 'portable', 'data', 'sidecars', 'sqlite'] },
    { id: 'import-pipeline', section: 'library', label: 'Import pipeline', description: 'Run the four resumable library import phases.', keywords: ['discover', 'enrich', 'metadata', 'finalize'] },
    { id: 'automation', section: 'library', label: 'Local library watcher', description: 'Detect new or changed files without contacting Danbooru.', keywords: ['automatic', 'watcher', 'sidecar', 'interval', 'local'] },
    { id: 'clean-sidecars', section: 'maintenance', label: 'Clean orphan sidecars', description: 'Remove metadata whose reachable media file is gone.', keywords: ['cleanup', 'orphan', 'metadata'] },
    { id: 'folder-sidecars', section: 'maintenance', label: 'Folder sidecars', description: 'Delete the central sidecar metadata for a registered folder.', keywords: ['sidecar', 'delete', 'remove', 'folder', 'metadata', 'un-index'] },
    { id: 'rebuild', section: 'maintenance', label: 'Rebuild database', description: 'Recover the regenerable SQLite index from sidecars.', keywords: ['recovery', 'sqlite', 'repair'] },
  ];

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
  let searchHighlightTimer: ReturnType<typeof setTimeout> | null = null;

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
      .catch(() => {
        credentials = null;
        credentialUsername = '';
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
    } else if (section === 'metadata') {
      await Promise.all([loadFolders(), loadTools(), loadCredentials()]);
    } else if (section === 'maintenance') {
      await Promise.all([loadTools(), loadFolders()]);
    } else if (section === 'roots') {
      await loadRoleSources();
    }
  }

  $: void ensureSectionData(selectedSection);

  let attachmentStore: AttachmentStore | null = null;
  let attachmentBusy = false;
  let attachmentError = '';
  let attachmentPathDraft = '';
  let attachmentModeView: 'managed' | 'folder' = 'managed';

  onMount(() => {
    prepareSettingsPresentation();
    void loadAttachmentStore();
    return () => {
      stopToolPolling();
      if (searchHighlightTimer) clearTimeout(searchHighlightTimer);
      restoreSettingsPresentation($mediaPlayback === 'always');
    };
  });

  async function loadAttachmentStore() {
    try {
      attachmentStore = await filesApi.getAttachmentStore();
      attachmentModeView = attachmentStore.mode;
      if (attachmentStore.mode === 'folder') attachmentPathDraft = attachmentStore.path;
    } catch (error) {
      attachmentError = error instanceof Error ? error.message : String(error);
    }
  }

  // Managed mode: attachments hidden with the suite data (deduped, backed up).
  async function useManagedAttachmentStore() {
    if (attachmentBusy) return;
    attachmentBusy = true;
    attachmentError = '';
    try {
      attachmentStore = await filesApi.setAttachmentStore(null);
      attachmentPathDraft = '';
      attachmentModeView = 'managed';
    } catch (error) {
      attachmentError = error instanceof Error ? error.message : String(error);
    } finally {
      attachmentBusy = false;
    }
  }

  // Folder mode: attachments stored visibly inside the chosen folder.
  async function saveAttachmentFolder(path?: string) {
    const target = (path ?? attachmentPathDraft).trim();
    if (!target || attachmentBusy) return;
    attachmentBusy = true;
    attachmentError = '';
    try {
      attachmentStore = await filesApi.setAttachmentStore(target);
      attachmentPathDraft = attachmentStore.path;
      attachmentModeView = 'folder';
    } catch (error) {
      attachmentError = error instanceof Error ? error.message : String(error);
    } finally {
      attachmentBusy = false;
    }
  }

  // Copy attachments made in managed mode into the chosen visible folder and
  // repoint them, so previously hidden ones become browsable in Files.
  let attachmentMigrateMessage = '';
  async function migrateAttachmentsToFolder() {
    if (attachmentBusy) return;
    attachmentBusy = true;
    attachmentError = '';
    attachmentMigrateMessage = '';
    try {
      const result = await filesApi.migrateAttachments();
      attachmentMigrateMessage = result.migrated
        ? `Moved ${result.migrated} attachment${result.migrated === 1 ? '' : 's'} into this folder${result.skipped ? ` (${result.skipped} already here)` : ''}. Re-scan the folder to see them in Files.`
        : 'Nothing to move — all attachments are already in this folder.';
    } catch (error) {
      attachmentError = error instanceof Error ? error.message : String(error);
    } finally {
      attachmentBusy = false;
    }
  }

  async function browseForAttachmentFolder() {
    if (attachmentBusy) return;
    attachmentBusy = true;
    attachmentError = '';
    try {
      const picked = await filesApi.pickFolder();
      if (!picked.native) throw new Error('The native folder picker is unavailable.');
      if (picked.path) attachmentPathDraft = picked.path;
    } catch (error) {
      attachmentError = error instanceof Error ? error.message : String(error);
    } finally {
      attachmentBusy = false;
    }
  }

  // Folder roles (FILES → Folders). Reuses the suite folder-role manager so each
  // root can be assigned to Files or a module (adopt/release) from Settings.
  let showRoleManager = false;
  let roleSources: SourceInfo[] = [];
  let roleSourcesLoaded = false;
  let rescanBusyId: string | null = null;
  let rescanError = '';
  let rescanMessage = '';

  async function loadRoleSources(force = false): Promise<void> {
    if (roleSourcesLoaded && !force) return;
    roleSources = await filesApi.listSources();
    roleSourcesLoaded = true;
    if (get(suiteModules).length === 0) {
      try {
        suiteModules.set(await suiteApi.listModules());
      } catch {
        // The role dropdown falls back to slugs if the registry is unavailable.
      }
    }
  }

  function moduleLabelForRole(role: string): string {
    if (role === 'base' || role === 'files') return 'Files';
    return get(suiteModules).find((module) => module.slug === role)?.name ?? role;
  }

  function openRoleManager() {
    void loadRoleSources(true);
    showRoleManager = true;
  }

  function roleFoldersSaved(event: CustomEvent<FolderBatchResult>) {
    roleSources = event.detail.sources;
    showRoleManager = false;
    void loadRoleSources(true); // refetch so per-folder counts are populated
    void loadFolders(true);
    imageRefreshToken.update((n) => n + 1);
  }

  // Re-scan one folder through its owning module (Files → base scan, a module →
  // its own sync). A module sync runs in the background as a tool, so hand it to
  // the existing tool poller; a base scan finishes synchronously.
  async function rescanRoleFolder(source: SourceInfo) {
    if (rescanBusyId) return;
    rescanBusyId = source.source_id;
    rescanError = '';
    rescanMessage = '';
    try {
      const result = await suiteApi.rescanFolder(source.source_id);
      const toolId = result.module?.active_tool_id;
      if (typeof toolId === 'string' && toolId) {
        startToolPolling(toolId);
        rescanMessage = `Re-scan started for ${source.display_name} — running in the background.`;
      } else {
        rescanMessage = `Re-scanned ${source.display_name}.`;
        imageRefreshToken.update((n) => n + 1);
      }
    } catch (error) {
      rescanError = error instanceof Error ? error.message : String(error);
    } finally {
      rescanBusyId = null;
    }
  }

  // Remove = the suite "forget": stop tracking the folder and drop its index
  // rows, but never touch the media or sidecars on disk. Works for any role.
  async function removeRoleFolder(source: SourceInfo) {
    if (rescanBusyId) return;
    rescanError = '';
    rescanMessage = '';
    try {
      const preview = await suiteApi.previewFolderForget(source.source_id);
      const indexed = preview.base_files + preview.module_files;
      const confirmed = window.confirm(
        `Remove “${preview.display_name}” from ${SUITE_NAME}?\n\n` +
        `${indexed} indexed entries will be dropped. The folder itself and ` +
        `${preview.sidecars_preserved} sidecars stay on disk — nothing is deleted.`
      );
      if (!confirmed) return;
      const result = await suiteApi.applyFolderChanges([
        {
          source_id: source.source_id,
          path: source.path,
          display_name: source.display_name,
          role: source.role === 'base' ? 'files' : source.role,
          visible: source.visible,
          forget: true,
        },
      ]);
      roleSources = result.sources;
      rescanMessage = `Removed ${source.display_name}. Your files were not touched.`;
      void loadRoleSources(true); // refetch so remaining counts are populated
      void loadFolders(true);
      imageRefreshToken.update((n) => n + 1);
    } catch (error) {
      rescanError = error instanceof Error ? error.message : String(error);
    }
  }

  // A module-owned folder keeps a stable identity, so it can be relocated (Files
  // folders are keyed by path — remove + re-add instead, so no Relocate is shown).
  function isModuleFolder(role: string): boolean {
    return role !== 'files' && role !== 'base';
  }

  // Relocate = the folder moved on disk; re-point its module index at the new
  // path without moving any files. Uses the native picker for the new location.
  async function relocateRoleFolder(source: SourceInfo) {
    if (rescanBusyId) return;
    rescanError = '';
    rescanMessage = '';
    try {
      const picked = await filesApi.pickFolder();
      if (!picked.native) throw new Error('The native folder picker is unavailable.');
      if (!picked.path) return;
      const result = await suiteApi.relocateFolder(source.source_id, picked.path);
      await Promise.all([loadRoleSources(true), loadFolders(true)]);
      rescanMessage = `Relocated ${source.display_name} — ${result.files_updated.toLocaleString()} indexed references updated. Files were not moved.`;
      imageRefreshToken.update((n) => n + 1);
    } catch (error) {
      rescanError = error instanceof Error ? error.message : String(error);
    }
  }

  async function saveDanbooruCredentials() {
    if (credentialBusy) return;
    credentialBusy = true;
    credentialError = '';
    credentialMessage = '';
    try {
      credentials = await api.saveDanbooruCredentials(credentialUsername.trim(), credentialApiKey.trim() || undefined);
      credentialUsername = credentials.username ?? '';
      credentialApiKey = '';
      credentialMessage = 'Credentials saved securely for this Windows user.';
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

  function formatByteCount(value: number) {
    if (value >= 1024 ** 3) return `${(value / 1024 ** 3).toFixed(2)} GB`;
    if (value >= 1024 ** 2) return `${(value / 1024 ** 2).toFixed(2)} MB`;
    if (value >= 1024) return `${(value / 1024).toFixed(1)} KB`;
    return `${value.toLocaleString()} B`;
  }

  const ratingOptions: { value: string | null; label: string; description: string }[] = [
    { value: null, label: 'All', description: 'Show every rating' },
    { value: 'g', label: 'General', description: 'Default safe browse' },
    { value: 's', label: 'Sensitive', description: 'Include sensitive posts' },
    { value: 'q', label: 'Questionable', description: 'Questionable only' },
    { value: 'e', label: 'Explicit', description: 'Explicit only' },
    { value: 'u', label: 'Unrated', description: 'Missing sidecar rating' },
  ];

  const artistNotificationIntervalOptions: ArtistNotificationIntervalMinutes[] = [5, 15, 30, 60];

  const fitModeOptions: { value: FitMode; label: string; description: string }[] = [
    { value: 'fit', label: 'Crop Fill', description: 'Dense grid with filled cards' },
    { value: 'contain', label: 'Contain', description: 'Show the full image shape' },
  ];

  const startupOptions: { value: StartupView; label: string }[] = [
    { value: 'home', label: 'Home' },
    { value: 'gallery', label: 'Browse' },
    { value: 'last', label: 'Last visited' },
  ];

  // Which surface opens on launch. Files is always offered; a module appears
  // only while it is enabled; 'Last used' keeps whatever was open last time.
  $: startupModuleOptions = [
    { value: 'files' as StartupModule, label: 'Files' },
    ...($enabledModules.includes('danbooru') ? [{ value: 'danbooru' as StartupModule, label: MODULE_NAME }] : []),
    { value: 'last' as StartupModule, label: 'Last used' },
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

  const motionOptions: { value: MotionPreference; label: string }[] = [
    { value: 'system', label: 'System' },
    { value: 'full', label: 'Full' },
    { value: 'reduced', label: 'Reduced' },
  ];

  const interfaceScaleOptions: { value: InterfaceScale; label: string }[] = [
    { value: 'default', label: 'Default' },
    { value: 'comfortable', label: 'Comfortable' },
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

  $: query = settingsSearch.trim().toLowerCase();
  $: searchResults = query
    ? settingSearchItems
        .filter(item => {
          const section = sections.find(candidate => candidate.id === item.section);
          return [item.label, item.description, section?.label ?? '', ...item.keywords]
            .some(value => value.toLowerCase().includes(query));
        })
        .sort((left, right) => settingSearchScore(left, query) - settingSearchScore(right, query)
          || left.label.localeCompare(right.label))
    : [];
  $: currentDuplicateMode = $duplicatesOnly ? $duplicateScope : 'off';
  $: selectedImageSize = gridSizeOptions.find(option => option.value === $imageSize) ?? gridSizeOptions[1];

  function close() {
    dispatch('close');
  }

  function handleKeydown(event: KeyboardEvent) {
    if (event.key === 'Escape') {
      if (folderRemovalFolder) closeFolderRemoval();
      else close();
    }
  }

  function setDuplicateMode(value: DuplicateScope | 'off') {
    if (value === 'off') {
      duplicatesOnly.set(false);
      return;
    }
    duplicateScope.set(value);
    duplicatesOnly.set(true);
  }

  function settingSearchScore(item: SettingSearchItem, needle: string) {
    const label = item.label.toLowerCase();
    const description = item.description.toLowerCase();
    const section = sections.find(candidate => candidate.id === item.section)?.label.toLowerCase() ?? '';
    const keywords = item.keywords.map(keyword => keyword.toLowerCase());
    if (label === needle) return 0;
    if (label.startsWith(needle)) return 1;
    if (label.includes(needle)) return 2;
    if (keywords.some(keyword => keyword === needle)) return 3;
    if (keywords.some(keyword => keyword.startsWith(needle))) return 4;
    if (section.includes(needle)) return 5;
    if (description.includes(needle)) return 6;
    return 7;
  }

  async function openSearchResult(item: SettingSearchItem) {
    selectedSection = item.section;
    settingsSearch = '';
    await tick();
    const target = document.getElementById(`setting-${item.id}`);
    if (!target) return;
    document.querySelector('.setting-flash')?.classList.remove('setting-flash');
    if (searchHighlightTimer) clearTimeout(searchHighlightTimer);
    target.scrollIntoView({
      block: 'center',
      behavior: $motionPreference === 'reduced' ? 'auto' : 'smooth',
    });
    await tick();
    target.classList.remove('setting-flash');
    void target.getBoundingClientRect();
    target.classList.add('setting-flash');
    searchHighlightTimer = window.setTimeout(() => {
      target.classList.remove('setting-flash');
      searchHighlightTimer = null;
    }, 1400);
  }

  function compactSegmentClass(active: boolean) {
    return `px-3 py-1.5 text-xs font-medium transition-colors ${
      active
        ? 'bg-purple-600/25 text-purple-100'
        : 'bg-[#0d0d13] text-gray-500 hover:bg-[#171720] hover:text-gray-200'
    }`;
  }

  function iconPath(icon: string) {
    if (icon === 'folder') {
      return 'M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2V7z';
    }
    if (icon === 'palette') {
      return 'M12 3a9 9 0 00-3 17.49c.6.2 1-.28.83-.87-.22-.76.27-1.54 1.06-1.54h1.33c4.18 0 7.56-3.05 7.56-6.82C19.78 6.7 16.3 3 12 3zm-4 8h.01M11 7h.01M15 8h.01M16 12h.01';
    }
    if (icon === 'database') {
      return 'M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3zm0 0v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6m-16 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6';
    }
    if (icon === 'shield') {
      return 'M12 3l7 3v5c0 4.6-2.8 8.2-7 10-4.2-1.8-7-5.4-7-10V6l7-3zm-3 9l2 2 4-4';
    }
    if (icon === 'image') {
      return 'M4 6a2 2 0 012-2h12a2 2 0 012 2v12a2 2 0 01-2 2H6a2 2 0 01-2-2V6zm2 10l4-4 3 3 4-5 3 4M9 10a1.5 1.5 0 100-3 1.5 1.5 0 000 3z';
    }
    return 'M4 5h16v14H4V5zm0 4h16M8 5v4';
  }
</script>

<svelte:window on:keydown={handleKeydown} />

<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
<div
  class="settings-layer fixed inset-0 z-[120] flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm"
  on:click={close}
>
  <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
  <div
    class="settings-shell grid h-[min(800px,calc(100vh-2rem))] w-[min(1120px,calc(100vw-2rem))] grid-cols-[252px_minmax(0,1fr)] grid-rows-[auto_minmax(0,1fr)] items-start overflow-hidden rounded-2xl border border-[#303042] bg-[#09090e] shadow-2xl shadow-black/70"
    role="dialog"
    aria-modal="true"
    aria-label="Settings"
    tabindex="-1"
    on:click|stopPropagation
  >
    <header class="col-span-2 flex h-16 items-center justify-between border-b border-[#272735] bg-[#111117]/95 px-5">
      <div class="flex min-w-0 items-center gap-3">
        <div class="grid h-9 w-9 shrink-0 place-items-center rounded-xl border border-purple-400/20 bg-purple-500/10 text-purple-200 shadow-inner shadow-purple-500/10">
          <svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" d="M10.3 4.3c.4-1.8 2.9-1.8 3.4 0a1.7 1.7 0 002.6 1.1c1.5-.9 3.3.8 2.4 2.4a1.7 1.7 0 001.1 2.6c1.8.4 1.8 2.9 0 3.4a1.7 1.7 0 00-1.1 2.6c.9 1.5-.8 3.3-2.4 2.4a1.7 1.7 0 00-2.6 1.1c-.4 1.8-2.9 1.8-3.4 0a1.7 1.7 0 00-2.6-1.1c-1.5.9-3.3-.8-2.4-2.4a1.7 1.7 0 00-1.1-2.6c-1.8-.4-1.8-2.9 0-3.4a1.7 1.7 0 001.1-2.6c-.9-1.5.8-3.3 2.4-2.4a1.7 1.7 0 002.6-1.1z" />
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
          </svg>
        </div>
        <h2 class="text-xl font-bold text-gray-100">Settings</h2>
      </div>
      <button
        class="grid h-9 w-9 place-items-center rounded-xl border border-[#303040] bg-[#17171f] text-gray-400 transition-colors hover:border-purple-400/40 hover:text-white"
        type="button"
        on:click={close}
        title="Close settings"
        aria-label="Close settings"
      >
        <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 6l12 12M18 6L6 18" />
        </svg>
      </button>
    </header>

    <aside class="flex h-full min-h-0 flex-col overflow-hidden border-r border-[#252532] bg-[#0d0d12] p-3.5">
      <label class="relative block shrink-0">
        <span class="sr-only">Search settings</span>
        <svg class="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-4.3-4.3m1.3-5.2a6.5 6.5 0 11-13 0 6.5 6.5 0 0113 0z" />
        </svg>
        <input
          class="w-full rounded-xl border border-[#2b2b3a] bg-[#15151d] py-2.5 pl-9 pr-8 text-sm text-gray-200 outline-none transition-colors placeholder:text-gray-600 focus:border-purple-500/60"
          type="search"
          placeholder="Find a setting"
          bind:value={settingsSearch}
        />
        {#if settingsSearch}
          <button class="absolute right-2 top-1/2 grid h-6 w-6 -translate-y-1/2 place-items-center rounded-md text-gray-600 hover:bg-white/5 hover:text-gray-300" type="button" title="Clear search" aria-label="Clear search" on:click={() => settingsSearch = ''}>×</button>
        {/if}
      </label>

      <nav class="settings-section-list mt-4 min-h-0 flex-1 space-y-4 overflow-y-auto pr-1" aria-label="Settings sections">
        {#each visibleGroups as group}
          <div>
            <div class="px-3 pb-1 text-[10px] font-semibold uppercase tracking-wider text-gray-600">{group.label}</div>
            <div class="space-y-0.5">
              {#each sections.filter((section) => section.group === group.id) as section}
                <button
                  class="settings-section-item w-full rounded-md px-3 py-2 text-left text-sm transition-colors {selectedSection === section.id && !query ? 'bg-[#1a1a23] text-gray-100' : 'text-gray-400 hover:bg-[#141419] hover:text-gray-200'}"
                  type="button"
                  aria-current={selectedSection === section.id && !query ? 'page' : undefined}
                  on:click={() => { selectedSection = section.id; settingsSearch = ''; }}
                >{section.label}</button>
              {/each}
            </div>
          </div>
        {/each}
      </nav>
    </aside>

    <main class="settings-scroll h-full min-h-0 overflow-y-auto bg-[#09090e] p-5">
      {#if query}
        <section class="mx-auto max-w-3xl">
          <div class="mb-4 flex items-end justify-between gap-4">
            <div>
              <div class="text-xs font-semibold uppercase tracking-[0.18em] text-purple-300">Search</div>
              <h3 class="mt-1 text-2xl font-bold text-gray-100">{searchResults.length} result{searchResults.length === 1 ? '' : 's'} for “{settingsSearch.trim()}”</h3>
            </div>
          </div>
          {#if searchResults.length}
            <div class="space-y-2">
              {#each searchResults as result}
                <button
                  class="group flex w-full items-center gap-4 rounded-xl border border-[#292938] bg-[#121219] px-4 py-3 text-left transition-all hover:-translate-y-0.5 hover:border-purple-400/35 hover:bg-[#171720]"
                  type="button"
                  on:click={() => openSearchResult(result)}
                >
                  <span class="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-purple-500/10 text-purple-200">
                    <svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" d={iconPath(sections.find(section => section.id === result.section)?.icon ?? 'window')} />
                    </svg>
                  </span>
                  <span class="min-w-0 flex-1">
                    <span class="block text-xs font-semibold uppercase tracking-wide text-gray-600">{sections.find(section => section.id === result.section)?.label}</span>
                    <span class="mt-0.5 block text-sm font-semibold text-gray-200">{result.label}</span>
                    <span class="mt-1 block text-xs leading-relaxed text-gray-500">{result.description}</span>
                  </span>
                  <svg class="h-4 w-4 shrink-0 text-gray-600 transition-transform group-hover:translate-x-0.5 group-hover:text-purple-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
                  </svg>
                </button>
              {/each}
            </div>
          {:else}
            <div class="rounded-2xl border border-dashed border-[#303040] bg-[#111117] px-6 py-14 text-center">
              <div class="mx-auto grid h-12 w-12 place-items-center rounded-2xl bg-white/[0.035] text-gray-600">
                <svg class="h-6 w-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" d="M21 21l-4.3-4.3m1.3-5.2a6.5 6.5 0 11-13 0 6.5 6.5 0 0113 0z" /></svg>
              </div>
              <h3 class="mt-4 text-base font-semibold text-gray-300">No matching setting</h3>
              <p class="mt-1 text-sm text-gray-600">Try a control name, task, or value such as “backup,” “hover,” or “folder.”</p>
            </div>
          {/if}
        </section>
      {:else}
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

        {#if selectedSection === 'appearance'}
          <div class="mx-auto max-w-3xl space-y-4">
            <section class="overflow-hidden rounded-xl border border-[#292938] bg-[#111118]">
              <div class="divide-y divide-[#22222e]">
                <div id="setting-motion" class="flex items-center justify-between gap-5 px-4 py-3">
                  <div class="text-sm font-medium text-gray-200">Interface motion</div>
                  <div class="flex divide-x divide-[#303040] overflow-hidden rounded-lg border border-[#303040]">{#each motionOptions as option}<button class={compactSegmentClass($motionPreference === option.value)} type="button" on:click={() => motionPreference.set(option.value)}>{option.label}</button>{/each}</div>
                </div>
                <div id="setting-interface-scale" class="flex items-center justify-between gap-5 px-4 py-3">
                  <div class="text-sm font-medium text-gray-200">Interface scale</div>
                  <div class="flex divide-x divide-[#303040] overflow-hidden rounded-lg border border-[#303040]">{#each interfaceScaleOptions as option}<button class={compactSegmentClass($interfaceScale === option.value)} type="button" on:click={() => interfaceScale.set(option.value)}>{option.label}</button>{/each}</div>
                </div>
              </div>
            </section>
          </div>
        {:else if selectedSection === 'startup'}
          <div class="mx-auto max-w-3xl space-y-4">
            <section class="overflow-hidden rounded-xl border border-[#292938] bg-[#111118]">
              <div class="divide-y divide-[#22222e]">
                <div id="setting-startup-module" class="flex items-center justify-between gap-5 px-4 py-3">
                  <div>
                    <div class="text-sm font-medium text-gray-200">Startup destination</div>
                    <div class="mt-0.5 text-xs text-gray-500">Which surface opens when {SUITE_NAME} launches.</div>
                  </div>
                  <select class="w-40 shrink-0 rounded-lg border border-[#303040] bg-[#0d0d13] px-3 py-2 text-xs text-gray-200 outline-none focus:border-purple-400/60" value={$startupModule} on:change={(event) => startupModule.set((event.currentTarget as HTMLSelectElement).value as StartupModule)}>
                    {#each startupModuleOptions as option}<option value={option.value}>{option.label}</option>{/each}
                  </select>
                </div>
              </div>
            </section>
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
        {:else if selectedSection === 'storage'}
          <div class="mx-auto max-w-3xl space-y-4">
            <ThumbnailCacheSettings />
          </div>
        {:else if selectedSection === 'roots'}
          <div class="mx-auto max-w-3xl space-y-4">
            <section id="setting-folder-roles" class="overflow-visible rounded-xl border border-[#292938] bg-[#111118]">
              <div class="border-b border-[#242432] p-4">
                <div class="flex items-center justify-between gap-4">
                  <div class="flex items-center gap-2"><h4 class="text-sm font-semibold text-gray-200">Folders</h4><span class="rounded-full bg-cyan-500/10 px-2.5 py-1 text-[11px] text-cyan-300">{roleSources.length}</span></div>
                  <button class="rounded-lg border border-[#2a2a3a] bg-[#1e1e2e] px-3 py-1.5 text-xs text-gray-300 transition-colors hover:border-cyan-500/50 hover:text-white" type="button" on:click={openRoleManager}>Manage folders…</button>
                </div>
                <p class="mt-1 text-xs leading-relaxed text-gray-500">Folders registered with Files. Each is owned by Files or handed to a module ({MODULE_NAME}); use <span class="text-gray-400">Manage folders…</span> to add, assign a role, rename, or hide one.</p>
                {#if rescanMessage}<p class="mt-2 text-xs text-green-400">{rescanMessage}</p>{/if}
                {#if rescanError}<p class="mt-2 text-xs text-red-400">{rescanError}</p>{/if}
              </div>
              <div class="space-y-2 p-3">
                {#if !roleSourcesLoaded}<div class="rounded-xl border border-dashed border-[#303040] px-4 py-8 text-center text-sm text-gray-500">Loading folders…</div>{:else if roleSources.length === 0}<div class="rounded-xl border border-dashed border-[#303040] px-4 py-8 text-center text-sm text-gray-500">No folders registered yet. Use Manage folders to add one.</div>{/if}
                {#each roleSources as source (source.source_id)}
                  <div class="flex items-center gap-3 rounded-xl border border-white/5 bg-[#0d0d13] px-3 py-2.5 transition-colors hover:border-cyan-300/15">
                    <span class="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-cyan-500/10 text-cyan-300"><svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" d={iconPath('folder')} /></svg></span>
                    <div class="min-w-0 flex-1"><div class="flex items-baseline gap-2"><span class="truncate text-sm font-semibold text-gray-200">{source.display_name}</span><span class="shrink-0 rounded-full bg-cyan-500/10 px-2 py-0.5 text-[10px] text-cyan-300">{moduleLabelForRole(source.role)}</span><span class="shrink-0 rounded-full bg-white/[0.04] px-2 py-0.5 text-[10px] text-gray-500">{(source.entry_count ?? 0).toLocaleString()} items</span>{#if !source.visible}<span class="shrink-0 text-[10px] text-gray-600">hidden</span>{/if}</div><div class="mt-0.5 truncate text-xs text-gray-600" title={source.path}>{source.path}</div></div>
                    <button class="shrink-0 rounded-lg border border-[#2a2a3a] px-3 py-1.5 text-xs text-gray-300 transition-colors hover:border-cyan-500/50 hover:text-white disabled:opacity-40" type="button" title="Re-index this folder" disabled={rescanBusyId !== null || toolRunning} on:click={() => rescanRoleFolder(source)}>{rescanBusyId === source.source_id ? 'Re-scanning…' : 'Re-scan'}</button>
                    <details class="group relative shrink-0">
                      <summary class="grid h-8 w-8 cursor-pointer list-none place-items-center rounded-lg text-gray-500 hover:bg-white/5 hover:text-gray-200" title="Folder actions" aria-label="Folder actions">•••</summary>
                      <div class="absolute right-0 top-9 z-20 w-40 overflow-hidden rounded-lg border border-[#303040] bg-[#191920] p-1 shadow-xl shadow-black/50">
                        {#if isModuleFolder(source.role)}<button class="w-full rounded-md px-3 py-2 text-left text-xs text-cyan-200 hover:bg-cyan-500/10" type="button" disabled={toolRunning} on:click={() => relocateRoleFolder(source)}>Relocate…</button>{/if}
                        <button class="w-full rounded-md px-3 py-2 text-left text-xs text-red-300 hover:bg-red-500/10" type="button" on:click={() => removeRoleFolder(source)}>Remove…</button>
                      </div>
                    </details>
                  </div>
                {/each}
              </div>
            </section>
          </div>
        {:else if selectedSection === 'files'}
          <div class="mx-auto max-w-3xl space-y-4">
            <section id="setting-attachment-location" class="rounded-xl border border-[#292938] bg-[#111118] p-4">
              <div class="flex items-start gap-3">
                <span class="mt-0.5 grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-purple-500/10 text-purple-300"><svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" d={iconPath('image')} /></svg></span>
                <div class="min-w-0 flex-1">
                  <h3 class="text-sm font-semibold text-gray-100">Attachment storage</h3>
                  <p class="mt-0.5 text-xs leading-relaxed text-gray-500">Where images and videos you attach to a file's origin note are saved. Existing attachments stay where they are — this changes only where new ones go.</p>
                  {#if attachmentStore}
                    <div class="mt-3 flex divide-x divide-[#303040] overflow-hidden rounded-lg border border-[#303040]">
                      <button class={compactSegmentClass(attachmentModeView === 'managed')} type="button" on:click={() => (attachmentModeView = 'managed')} disabled={attachmentBusy}>Managed</button>
                      <button class={compactSegmentClass(attachmentModeView === 'folder')} type="button" on:click={() => (attachmentModeView = 'folder')} disabled={attachmentBusy}>Choose a folder</button>
                    </div>

                    {#if attachmentModeView === 'managed'}
                      <div class="mt-3 rounded-lg border border-[#2a2a3a] bg-[#0d0d14] px-3 py-2.5">
                        <p class="text-xs leading-relaxed text-gray-400">Stored with {SUITE_NAME}'s own data — hidden from browsing, de-duplicated, and covered by the app backup. Recommended.</p>
                        <div class="mt-1.5 break-all font-mono text-[11px] text-gray-600">{attachmentStore.default}\.keivotos\attachments</div>
                      </div>
                      {#if attachmentStore.mode !== 'managed'}
                        <div class="mt-3 flex items-center gap-2">
                          <button type="button" class="rounded-lg bg-purple-500/20 px-3 py-1.5 text-xs font-semibold text-purple-100 transition-colors hover:bg-purple-500/30 disabled:opacity-40" on:click={useManagedAttachmentStore} disabled={attachmentBusy}>Use managed storage</button>
                          <span class="text-[11px] text-gray-500">Currently saving to a folder.</span>
                        </div>
                      {:else}
                        <p class="mt-2 text-[11px] text-green-400">Managed storage is active.</p>
                      {/if}
                    {:else}
                      <p class="mt-3 text-xs leading-relaxed text-gray-500">Pick a folder inside your library. New attachments are saved there as browsable files (under an <span class="font-mono text-gray-400">Attachments</span> subfolder), so they show up in Files.</p>
                      <div class="mt-2">
                        <PathAutocomplete bind:value={attachmentPathDraft} disabled={attachmentBusy} on:submit={(event) => saveAttachmentFolder(event.detail)} />
                      </div>
                      <div class="mt-2 flex flex-wrap items-center gap-2">
                        <button type="button" class="rounded-lg bg-purple-500/20 px-3 py-1.5 text-xs font-semibold text-purple-100 transition-colors hover:bg-purple-500/30 disabled:opacity-40" on:click={() => saveAttachmentFolder()} disabled={attachmentBusy || !attachmentPathDraft.trim()}>Save folder</button>
                        <button type="button" class="rounded-lg border border-[#2a2a3a] px-3 py-1.5 text-xs text-gray-400 transition-colors hover:text-white disabled:opacity-40" on:click={browseForAttachmentFolder} disabled={attachmentBusy}>Browse…</button>
                        {#if attachmentStore.mode === 'folder'}<span class="text-[11px] text-green-400">Saving to this folder now.</span>{/if}
                      </div>
                      {#if attachmentStore.mode === 'folder'}
                        <div class="mt-3 rounded-lg border border-[#2a2a3a] bg-[#0d0d14] px-3 py-2.5">
                          <p class="text-xs leading-relaxed text-gray-500">Attachments you added while on <span class="text-gray-400">Managed</span> stay hidden. Move them into this folder so they show up in Files too.</p>
                          <div class="mt-2 flex flex-wrap items-center gap-2">
                            <button type="button" class="rounded-lg border border-[#2a2a3a] bg-[#1e1e2e] px-3 py-1.5 text-xs text-gray-300 transition-colors hover:border-purple-500/50 hover:text-white disabled:opacity-40" on:click={migrateAttachmentsToFolder} disabled={attachmentBusy}>Move existing attachments here</button>
                          </div>
                          {#if attachmentMigrateMessage}<p class="mt-2 text-[11px] text-green-400">{attachmentMigrateMessage}</p>{/if}
                        </div>
                      {/if}
                    {/if}
                  {:else}
                    <p class="mt-3 text-xs text-gray-600">Loading…</p>
                  {/if}
                  {#if attachmentError}<p class="mt-2 text-[11px] text-red-300">{attachmentError}</p>{/if}
                </div>
              </div>
            </section>
          </div>
        {:else if selectedSection === 'account'}
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
        {:else if selectedSection === 'backup'}
          <div class="mx-auto max-w-3xl space-y-4">
            <BackupRestoreSettings {toolRunning} />
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

    </main>
  </div>

  {#if showRoleManager}
    <ManageFoldersDialog
      sources={roleSources}
      modules={$suiteModules}
      on:saved={roleFoldersSaved}
      on:close={() => (showRoleManager = false)}
    />
  {/if}

  {#if folderRemovalFolder}
    <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
    <div class="fixed inset-0 z-[140] grid place-items-center bg-black/80 p-4 backdrop-blur-sm" on:click={closeFolderRemoval}>
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
</div>

<style>
  .settings-scroll {
    scrollbar-gutter: stable;
    contain: layout paint;
    overscroll-behavior: contain;
  }

  .settings-layer {
    contain: paint;
    isolation: isolate;
  }

  .settings-shell {
    contain: layout paint style;
  }

  .settings-section-list {
    scrollbar-gutter: stable;
    overscroll-behavior: contain;
  }

  .settings-section-marker {
    animation: settings-section-marker-in 180ms ease-out;
  }

  :global(.setting-flash) {
    position: relative;
    z-index: 1;
    animation: setting-highlight 1.35s ease-out;
  }

  @keyframes settings-section-marker-in {
    from {
      opacity: 0;
      transform: translateX(-4px) scaleY(0.45);
    }
    to {
      opacity: 1;
      transform: translateX(0) scaleY(1);
    }
  }

  @keyframes setting-highlight {
    0%, 20% {
      box-shadow: 0 0 0 2px rgba(216, 180, 254, 0.78), 0 0 28px rgba(168, 85, 247, 0.22);
      background-color: rgba(168, 85, 247, 0.11);
    }
    100% {
      box-shadow: 0 0 0 0 transparent;
      background-color: transparent;
    }
  }

  @media (max-width: 780px) {
    .settings-shell {
      grid-template-columns: 205px minmax(0, 1fr);
    }
  }
</style>
