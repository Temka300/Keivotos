<script lang="ts">
  import { onMount } from 'svelte';
  import { filesApi, type DuplicateGroup, type FileNode, type SourceInfo } from '../lib/filesApi';
  import { fileGlyph, hasThumbnail, type Subject } from '../lib/filePreview';
  import GridSizeMenu from './GridSizeMenu.svelte';
  import { filesGridSize, imageSizeByValue, thumbnailTierFor } from '../lib/stores';
  import { SUITE_NAME } from '../lib/product';
  import { suiteModules } from '../lib/stores';
  import {
    displayNameForPath,
    normalizedPath,
    suiteApi,
    type FolderBatchResult,
  } from '../lib/suiteApi';
  import { moduleUi } from '../modules/registry';
  import AppDrawer from './AppDrawer.svelte';
  import FileContextMenu from './FileContextMenu.svelte';
  import FileInfoPanel from './FileInfoPanel.svelte';
  import ManageFoldersDialog from './ManageFoldersDialog.svelte';

  let sources: SourceInfo[] = [];
  let selectedSourceId: string | null = null;
  let currentParent = '';
  let entries: FileNode[] = [];
  let searchQuery = '';
  let searchResults: FileNode[] | null = null;
  let showManager = false;
  let addingFolder = false;
  let loading = false;
  let busy = false;
  let error = '';
  let showAppMenu = false;
  let duplicateGroups: DuplicateGroup[] | null = null;
  let dedupBusy = false;
  let selectedEntry: FileNode | null = null;
  let annotatedPaths = new Set<string>();
  let showInfoModal = false;

  $: selectedSource = sources.find((s) => s.source_id === selectedSourceId) ?? null;
  $: sidebarSources = sources.filter((source) => source.visible);
  $: selectedRole = selectedSource?.role === 'base' ? 'files' : selectedSource?.role ?? 'files';
  $: breadcrumbSources = selectedSource
    ? sources
      .filter((source) => isSameOrAncestorPath(source.path, selectedSource?.path ?? ''))
      .sort((left, right) => pathDepth(left.path) - pathDepth(right.path))
    : [];
  $: crumbs = currentParent === '' ? [] : currentParent.split('/');
  $: displayed = searchResults ?? entries;
  $: subject = buildSubject(selectedEntry, selectedSource, currentParent, sources);
  $: subjectSourceName =
    sources.find((source) => source.source_id === subject?.sourceId)?.display_name ?? '';

  onMount(loadSources);

  function absolutePathFor(sourcePath: string, relativePath: string): string {
    return normalizedPath(relativePath ? `${sourcePath}/${relativePath}` : sourcePath);
  }

  function buildSubject(
    entry: FileNode | null,
    source: SourceInfo | null,
    parent: string,
    allSources: SourceInfo[],
  ): Subject | null {
    if (entry) {
      const owner = allSources.find((s) => s.source_id === entry.source_id) ?? source;
      const base = owner?.path ?? source?.path ?? '';
      return {
        sourceId: entry.source_id,
        path: entry.relative_path,
        name: entry.name,
        isDir: entry.is_dir,
        ext: entry.ext,
        size: entry.size,
        mtime: entry.mtime,
        absolutePath: absolutePathFor(base, entry.relative_path),
      };
    }
    if (!source) return null;
    const folderName = parent === '' ? source.display_name : parent.split('/').pop() ?? source.display_name;
    return {
      sourceId: source.source_id,
      path: parent,
      name: folderName,
      isDir: true,
      ext: null,
      size: null,
      mtime: null,
      absolutePath: absolutePathFor(source.path, parent),
    };
  }

  function isSelected(entry: FileNode): boolean {
    return (
      selectedEntry !== null &&
      selectedEntry.source_id === entry.source_id &&
      selectedEntry.relative_path === entry.relative_path
    );
  }

  async function loadAnnotatedPaths() {
    if (!selectedSourceId) {
      annotatedPaths = new Set();
      return;
    }
    try {
      annotatedPaths = new Set(await filesApi.listAnnotated(selectedSourceId));
      annotationRevision += 1;
      // A tile that 404'd before could have just been given an attachment, so
      // let every failure retry once the origin data has changed.
      thumbFailed = new Set();
    } catch {
      // Badges are non-essential; a failure just leaves them off.
    }
  }

  // Left-click selects (highlights) a file only; the info modal is opened
  // deliberately from the right-click menu's Show info, not on every click.
  function selectEntry(entry: FileNode): void {
    selectedEntry = entry;
  }

  // Right-click menu over one tile. It only exposes read-only actions that
  // already exist (info panel, Open, Reveal); nothing here writes to disk.
  let menuEntry: FileNode | null = null;
  let menuX = 0;
  let menuY = 0;

  function openMenu(event: MouseEvent, entry: FileNode): void {
    event.preventDefault();
    // Keep the browser's native menu suppressed and stop the window handler in
    // FileContextMenu from closing this the instant it opens.
    event.stopPropagation();
    menuEntry = entry;
    menuX = event.clientX;
    menuY = event.clientY;
  }

  function closeMenu(): void {
    menuEntry = null;
  }

  function menuShowInfo(): void {
    if (!menuEntry) return;
    selectedEntry = menuEntry;
    showInfoModal = true;
  }

  async function menuOpen(): Promise<void> {
    if (!menuEntry) return;
    error = '';
    try {
      await filesApi.openFile(menuEntry.source_id, menuEntry.relative_path);
    } catch (e) {
      error = (e as Error).message;
    }
  }

  async function menuReveal(): Promise<void> {
    if (!menuEntry) return;
    error = '';
    try {
      await filesApi.revealFile(menuEntry.source_id, menuEntry.relative_path);
    } catch (e) {
      error = (e as Error).message;
    }
  }

  // The modal's "Open" on a folder: browse into it inside Keivotos, then close.
  async function openInApp() {
    const entry = selectedEntry;
    showInfoModal = false;
    if (entry) await openEntry(entry);
  }

  async function loadSources() {
    error = '';
    try {
      const loadedSources = await filesApi.listSources();
      sources = loadedSources;
      const firstVisible = loadedSources.find((source) => source.visible);
      if (firstVisible && !selectedSourceId) {
        await selectSource(firstVisible.source_id);
      }
    } catch (e) {
      error = (e as Error).message;
    }
  }

  async function selectSource(sourceId: string, parent = '') {
    selectedSourceId = sourceId;
    currentParent = parent;
    selectedEntry = null;
    clearSearch();
    duplicateGroups = null;
    await loadEntries();
  }

  async function loadEntries() {
    if (!selectedSourceId) {
      entries = [];
      return;
    }
    loading = true;
    error = '';
    try {
      entries = await filesApi.browse(selectedSourceId, currentParent);
    } catch (e) {
      error = (e as Error).message;
      entries = [];
    } finally {
      loading = false;
    }
    void loadAnnotatedPaths();
  }

  async function navigate(parent: string) {
    currentParent = parent;
    selectedEntry = null;
    clearSearch();
    duplicateGroups = null;
    await loadEntries();
  }

  async function showDuplicates() {
    if (dedupBusy) return;
    dedupBusy = true;
    error = '';
    try {
      // Lazily hash size-colliding files in bounded batches until caught up.
      for (let round = 0; round < 50; round += 1) {
        const progress = await filesApi.computeHashes();
        if (progress.remaining === 0) break;
      }
      duplicateGroups = await filesApi.listDuplicates();
      selectedEntry = null;
      clearSearch();
    } catch (e) {
      error = (e as Error).message;
    } finally {
      dedupBusy = false;
    }
  }

  async function openEntry(entry: FileNode) {
    if (!entry.is_dir) {
      selectEntry(entry);
      return;
    }
    const owner = sources.find((source) => source.source_id === entry.source_id);
    if (owner && owner.source_id !== selectedSourceId) {
      await selectSource(owner.source_id, entry.relative_path);
      return;
    }
    const basePath = owner?.path ?? selectedSource?.path;
    if (basePath) {
      const absolutePath = normalizedPath(`${basePath}/${entry.relative_path}`);
      const nestedSource = sources.find(
        (source) => normalizedPath(source.path) === absolutePath
      );
      if (nestedSource && nestedSource.source_id !== selectedSourceId) {
        await selectSource(nestedSource.source_id);
        return;
      }
    }
    await navigate(entry.relative_path);
  }

  async function foldersSaved(event: CustomEvent<FolderBatchResult>) {
    sources = event.detail.sources;
    const selectedStillExists = sources.some((source) => source.source_id === selectedSourceId);
    if (!selectedStillExists) {
      selectedSourceId = null;
      entries = [];
      clearSearch();
      const next = sources.find((source) => source.visible);
      if (next) await selectSource(next.source_id);
    } else {
      await loadEntries();
    }
  }

  async function addRootFolder() {
    if (addingFolder) return;
    addingFolder = true;
    error = '';
    try {
      const picked = await filesApi.pickFolder();
      if (!picked.native) {
        throw new Error('The native Windows folder picker is unavailable.');
      }
      const pickedPath = picked.path;
      if (!pickedPath) return;
      // A one-item batch through the same path Manage folders uses, so quick-add
      // cannot accept a folder the dialog would reject.
      const applied = await suiteApi.applyFolderChanges([
        {
          source_id: null,
          path: pickedPath,
          display_name: displayNameForPath(pickedPath),
          role: 'files',
          visible: true,
          forget: false,
        },
      ]);
      sources = applied.sources;
      const added = applied.sources.find(
        (source) => normalizedPath(source.path) === normalizedPath(pickedPath),
      );
      if (added) await selectSource(added.source_id);
    } catch (e) {
      error = (e as Error).message;
    } finally {
      addingFolder = false;
    }
  }

  async function rescan() {
    if (!selectedSourceId) return;
    busy = true;
    error = '';
    try {
      await filesApi.scanSource(selectedSourceId);
      await loadEntries();
    } catch (e) {
      error = (e as Error).message;
    } finally {
      busy = false;
    }
  }

  async function runSearch() {
    const q = searchQuery.trim();
    if (!q) {
      clearSearch();
      return;
    }
    if (!selectedSourceId) return;
    loading = true;
    error = '';
    try {
      searchResults = await filesApi.search(q, selectedSourceId);
    } catch (e) {
      error = (e as Error).message;
    } finally {
      loading = false;
    }
  }

  function clearSearch() {
    searchQuery = '';
    searchResults = null;
  }

  function isSameOrAncestorPath(path: string, child: string): boolean {
    const candidate = normalizedPath(path);
    const descendant = normalizedPath(child);
    return candidate === descendant || descendant.startsWith(`${candidate}/`);
  }

  function pathDepth(path: string): number {
    return normalizedPath(path).split('/').filter(Boolean).length;
  }

  function iconFor(entry: FileNode): string {
    return fileGlyph(entry);
  }

  // Tiles whose thumbnail request failed fall back to the glyph for the rest of
  // the session, so a broken-image box never appears and the 404 is not retried.
  let thumbFailed = new Set<string>();

  function entryKey(entry: FileNode): string {
    return entry.source_id + '/' + entry.relative_path;
  }

  function markThumbFailed(entry: FileNode): void {
    thumbFailed.add(entryKey(entry));
    thumbFailed = thumbFailed;
  }

  // Bumped whenever the annotation set is re-read, i.e. after any origin edit.
  let annotationRevision = 0;

  // Files keeps its own size choice; the scale itself is shared with Danbooru.
  $: gridSize = imageSizeByValue[$filesGridSize];
  $: thumbTier = thumbnailTierFor(gridSize.gridMin);
  // Keeps the picture box proportional to the column so tiles stay square-ish
  // at every step instead of a fixed box floating in a huge tile.
  $: thumbBoxPx = Math.round(gridSize.gridMin * 0.62);

  // The thumbnail response is immutable, so this token is the only thing that
  // makes a tile refresh. mtime/size covers the file being replaced on disk.
  //
  // Annotated entries also fold in the revision: attaching a screenshot changes
  // which image the tile should show but touches neither the file's mtime nor
  // its size, so without this the browser would keep serving the pre-attachment
  // thumbnail and the attach would look like it did nothing. Unannotated
  // entries stay on the stable token and keep caching across edits.
  // ``revision`` is taken as an argument, not read from scope, so that Svelte
  // sees it in the template expression and actually recomputes ``src``.
  function thumbVersion(entry: FileNode, revision: number): string {
    const base = `${entry.mtime ?? 0}-${entry.size ?? 0}`;
    return annotatedPaths.has(entry.relative_path) ? `${base}-r${revision}` : base;
  }

  // Renderable types and folders always ask. An annotated entry also asks even
  // when its own type has no thumbnail, because the user may have attached a
  // screenshot to it - that is the only face a 3D model or archive can have.
  // Everything else stays silent, so a folder of subtitles issues no requests.
  function wantsThumbnail(entry: FileNode): boolean {
    return hasThumbnail(entry) || annotatedPaths.has(entry.relative_path);
  }

  function formatSize(bytes: number | null): string {
    if (bytes == null) return '';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let n = bytes;
    let i = 0;
    while (n >= 1024 && i < units.length - 1) {
      n /= 1024;
      i += 1;
    }
    return `${i === 0 ? n : n < 10 ? n.toFixed(1) : Math.round(n)} ${units[i]}`;
  }
</script>

<!-- Files owns one compact bar: drawer, breadcrumb, then the source tools. -->
<header class="flex shrink-0 items-center gap-3 border-b border-[#2a2a3a] bg-[#16161e] px-4 py-2">
  <button
    class="rounded p-1.5 transition-colors hover:bg-[#2a2a3a]"
    type="button"
    on:click={() => (showAppMenu = true)}
    title="Open {SUITE_NAME} menu"
    aria-label="Open {SUITE_NAME} menu"
  >
    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h16" />
    </svg>
  </button>

  <div class="flex w-[17rem] min-w-0 max-w-[38%] shrink-0 items-center gap-1 overflow-x-auto text-sm">
    {#if selectedSource}
      {#if moduleUi(selectedRole).iconSrc}
        <img src={moduleUi(selectedRole).iconSrc ?? ''} alt="" class="mr-1 h-7 w-7 shrink-0 rounded-md" />
      {:else}
        <span class="mr-1 grid h-7 w-7 shrink-0 place-items-center rounded-md bg-white/5 text-base">🗂️</span>
      {/if}
      {#each breadcrumbSources as source, i}
        {#if i > 0}<span class="shrink-0 text-gray-600">/</span>{/if}
        <button
          type="button"
          class="shrink-0 text-gray-300 hover:text-white"
          on:click={() => source.source_id === selectedSourceId ? navigate('') : selectSource(source.source_id)}
        >{source.display_name}</button>
      {/each}
      {#each crumbs as crumb, i}
        <span class="shrink-0 text-gray-600">/</span>
        <button
          type="button"
          class="shrink-0 text-gray-300 hover:text-white"
          on:click={() => navigate(crumbs.slice(0, i + 1).join('/'))}
        >{crumb}</button>
      {/each}
    {:else}
      <span class="text-gray-500">Select or add a folder</span>
    {/if}
  </div>

  <div class="relative ml-4 mr-2 min-w-64 flex-1 max-w-xl">
      <input
        class="w-full rounded-lg border border-[#2a2a3a] bg-[#1e1e2e] px-3 py-1.5 pr-8 text-sm text-gray-200 outline-none placeholder:text-gray-500 transition-colors focus:border-purple-500 disabled:opacity-40"
        placeholder="Search this folder…"
        bind:value={searchQuery}
        on:keydown={(event) => event.key === 'Enter' && runSearch()}
        disabled={!selectedSource}
      />
      {#if searchResults !== null}
        <button
          type="button"
          class="absolute right-2 top-1/2 -translate-y-1/2 text-sm text-gray-500 hover:text-white"
          on:click={() => navigate(currentParent)}
          title="Clear search"
          aria-label="Clear search"
        >✕</button>
      {/if}
  </div>
  <div class="flex shrink-0 items-center gap-2">
    <GridSizeMenu value={filesGridSize} />
    <button
      type="button"
      class="h-9 rounded-lg border border-[#2a2a3a] bg-[#1e1e2e] px-3 text-xs text-gray-300 transition-colors hover:border-purple-500/50 hover:text-white disabled:opacity-40"
      on:click={rescan}
      disabled={!selectedSource || busy}
    >Rescan</button>
    <button
      type="button"
      class="h-9 rounded-lg border px-3 text-xs transition-colors disabled:opacity-40 {duplicateGroups !== null ? 'border-purple-500/50 bg-purple-500/25 text-purple-100' : 'border-[#2a2a3a] bg-[#1e1e2e] text-gray-300 hover:border-purple-500/50 hover:text-white'}"
      on:click={() => (duplicateGroups !== null ? navigate(currentParent) : showDuplicates())}
      disabled={dedupBusy || sources.length === 0}
      title="Find files with identical content across every source"
    >{dedupBusy ? 'Hashing…' : duplicateGroups !== null ? 'Close duplicates' : 'Duplicates'}</button>
  </div>
</header>

<div class="flex flex-1 min-h-0 overflow-hidden">
  <!-- Sources panel -->
  <aside class="flex flex-col w-72 shrink-0 border-r border-white/5 bg-[#0b0b10]">
    <div class="flex items-center border-b border-white/5 px-4 py-3">
      <div class="flex-1 text-xs font-semibold uppercase tracking-wide text-gray-400">Your folders</div>
      <button
        type="button"
        class="grid h-7 w-7 place-items-center rounded-md text-gray-500 transition-colors hover:bg-white/5 hover:text-purple-100 disabled:opacity-40"
        title="Add folder"
        aria-label="Add folder"
        on:click={addRootFolder}
        disabled={addingFolder}
      >
        <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-width="1.8" d="M12 5v14M5 12h14" />
        </svg>
      </button>
      <button
        type="button"
        class="grid h-7 w-7 place-items-center rounded-md text-gray-500 transition-colors hover:bg-white/5 hover:text-purple-100"
        title="Manage folders"
        aria-label="Manage folders"
        on:click={() => (showManager = true)}
      >
        <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" d="M14.7 6.3a4 4 0 01-5 5L4 17v3h3l5.7-5.7a4 4 0 005-5l-2.4 2.4-3-3 2.4-2.4z" />
        </svg>
      </button>
    </div>
    <div class="flex-1 overflow-y-auto">
      {#each sidebarSources as source (source.source_id)}
        <button
          type="button"
          class="group flex w-full items-center gap-2 px-4 py-2.5 text-left text-sm transition-colors
                 {selectedSourceId === source.source_id ? 'bg-white/10 text-white' : 'text-gray-300 hover:bg-white/5'}"
          on:click={() => selectSource(source.source_id)}
        >
          {#if moduleUi(source.role === 'base' ? 'files' : source.role).iconSrc}
            <img src={moduleUi(source.role === 'base' ? 'files' : source.role).iconSrc ?? ''} alt="" class="h-5 w-5 rounded" />
          {:else}
            <span class="text-base">🗂️</span>
          {/if}
          <span class="flex-1 min-w-0 truncate" title={source.path}>{source.display_name}</span>
        </button>
      {/each}
      {#if sidebarSources.length === 0}
        <p class="px-4 py-4 text-xs leading-relaxed text-gray-500">
          {sources.length ? 'All registered folders are hidden from this sidebar.' : "You haven't added any folders yet."}
        </p>
      {/if}
    </div>
  </aside>

  <!-- Browse area.
       This row is deliberately uncapped. A cap was tried in V1.1.2 to pull the
       info panel away from the screen edge, but on a wide display it just left
       a dead band to the right of the panel. The resizable panel solves the
       same problem better: dragging it wider moves its left edge toward the
       grid without stranding any space. -->
  <section class="flex flex-col flex-1 min-w-0">
    {#if error}
      <div class="mx-4 mt-3 px-3 py-2 text-xs rounded bg-red-500/10 border border-red-500/30 text-red-300">{error}</div>
    {/if}

    <div class="flex-1 overflow-y-auto p-4">
      {#if duplicateGroups !== null}
        {#if duplicateGroups.length === 0}
          <p class="text-sm text-gray-500">No duplicate files found across your sources.</p>
        {:else}
          <div class="space-y-4">
            {#each duplicateGroups as group (group.content_hash)}
              <div class="rounded-lg border border-white/5 bg-white/[0.02]">
                <div class="flex items-center gap-2 border-b border-white/5 px-3 py-2">
                  <span class="text-xs font-semibold text-purple-200">{group.files.length}× identical</span>
                  <span class="text-[10px] text-gray-600 truncate" title={group.content_hash}>md5 {group.content_hash}</span>
                  <span class="ml-auto text-[10px] text-gray-500">{formatSize(group.files[0]?.size ?? null)} each</span>
                </div>
                {#each group.files as file (file.source_id + '/' + file.relative_path)}
                  <div class="flex items-center gap-2 px-3 py-1.5 text-xs text-gray-300">
                    <span>{iconFor(file)}</span>
                    <span class="truncate">{file.name}</span>
                    <span class="ml-auto truncate text-[10px] text-gray-500" title={file.relative_path}>
                      {sources.find((s) => s.source_id === file.source_id)?.display_name ?? file.source_id}{file.parent ? ` / ${file.parent}` : ''}
                    </span>
                  </div>
                {/each}
              </div>
            {/each}
          </div>
        {/if}
      {:else if loading}
        <p class="text-sm text-gray-500">Loading…</p>
      {:else if !selectedSource}
        <div class="grid h-full place-items-center text-center">
          <div class="max-w-sm">
            <div class="mb-3 text-5xl">🗂️</div>
            <h2 class="text-lg font-semibold text-gray-200">No folders yet</h2>
            <p class="mt-1 text-sm text-gray-500">
              Add a folder from your computer and Keivotos will index it in place — your files never move.
            </p>
            <button
              type="button"
              class="mt-4 rounded-lg bg-purple-500/25 px-4 py-2 text-sm font-medium text-purple-100 transition-colors hover:bg-purple-500/35"
              on:click={addRootFolder}
            >＋ Add a folder</button>
          </div>
        </div>
      {:else if searchResults !== null && searchResults.length === 0}
        <p class="text-sm text-gray-500">No matches for “{searchQuery}”.</p>
      {:else if displayed.length === 0}
        <p class="text-sm text-gray-500">This folder is empty.</p>
      {:else}
        <div class="grid gap-2" style="grid-template-columns: repeat(auto-fill, minmax({gridSize.gridMin}px, 1fr));">
          {#each displayed as entry (entry.source_id + '/' + entry.relative_path)}
            <button
              type="button"
              class="flex flex-col items-center gap-1 p-3 rounded-lg text-center transition-colors {isSelected(entry) ? 'border border-purple-500/60 bg-purple-500/15' : 'border border-white/5 bg-white/[0.03] hover:bg-white/[0.07]'}"
              on:click={() => openEntry(entry)}
              on:contextmenu={(event) => openMenu(event, entry)}
              title={entry.relative_path}
            >
              <span
                class="relative flex w-full items-center justify-center text-3xl leading-none"
                style="height: {thumbBoxPx}px;"
              >
                {#if wantsThumbnail(entry) && !thumbFailed.has(entryKey(entry))}
                  <img
                    src={filesApi.thumbnailUrl(entry.source_id, entry.relative_path, thumbTier, thumbVersion(entry, annotationRevision))}
                    alt=""
                    loading="lazy"
                    decoding="async"
                    class="max-w-full rounded object-contain"
                    style="max-height: {thumbBoxPx}px;"
                    on:error={() => markThumbFailed(entry)}
                  />
                {:else}
                  {iconFor(entry)}
                {/if}
                {#if annotatedPaths.has(entry.relative_path)}
                  <span class="absolute -right-1 -top-0.5 h-2 w-2 rounded-full bg-purple-400 ring-2 ring-[#0b0b10]" title="Has origin info"></span>
                {/if}
              </span>
              <span class="w-full truncate text-xs text-gray-200">{entry.name}</span>
              <span class="text-[10px] text-gray-500">
                {entry.is_dir ? 'Folder' : formatSize(entry.size)}
                {#if searchResults !== null && entry.parent}· {entry.parent}{/if}
              </span>
            </button>
          {/each}
        </div>
      {/if}
    </div>
  </section>
</div>

{#if showInfoModal && subject}
  <FileInfoPanel
    {subject}
    sourceName={subjectSourceName}
    on:close={() => (showInfoModal = false)}
    on:changed={loadAnnotatedPaths}
    on:browse={openInApp}
  />
{/if}

{#if menuEntry}
  <FileContextMenu
    x={menuX}
    y={menuY}
    entry={menuEntry}
    on:showinfo={menuShowInfo}
    on:open={menuOpen}
    on:reveal={menuReveal}
    on:close={closeMenu}
  />
{/if}

{#if showAppMenu}
  <AppDrawer on:close={() => (showAppMenu = false)} />
{/if}

{#if showManager}
  <ManageFoldersDialog
    {sources}
    modules={$suiteModules}
    on:saved={foldersSaved}
    on:close={() => (showManager = false)}
  />
{/if}
