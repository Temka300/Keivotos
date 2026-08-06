<script lang="ts">
  // The "File information" modal, opened from the browse tile's right-click
  // Show info. It replaced the docked, resizable side panel in Phase 1: a
  // centered dialog with two tabs — Properties (system facts) and Origin (the
  // user-authored note, links, attachments, and in-app preview). The Origin
  // logic is carried over unchanged; only the container and layout changed.
  import { createEventDispatcher } from 'svelte';
  import { filesApi, type Annotation, type AnnotationLink, type ApiError } from '../lib/filesApi';
  import {
    fileGlyph,
    isListableArchive,
    linkKindLabel,
    previewMode,
    type Subject,
  } from '../lib/filePreview';

  export let subject: Subject;
  // The owning source's display name, resolved by the parent from the registry.
  export let sourceName = '';

  const dispatch = createEventDispatcher<{ close: void; changed: void }>();
  const TEXT_CAP = 1024 * 1024;
  const LINK_KINDS = ['source', 'discussion', 'mirror', 'author', 'other'];

  let activeTab: 'properties' | 'origin' = 'properties';

  let annotation: Annotation | null = null;
  let loading = false;
  let error = '';
  let actionError = '';
  let textPreview: string | null = null;
  let textTruncated = false;
  let loadedKey = '';

  let editing = false;
  let saving = false;
  let draftDescription = '';
  let draftLinks: AnnotationLink[] = [];
  let uploading = false;
  let fileInput: HTMLInputElement;

  $: key = `${subject.sourceId}::${subject.path}`;
  $: if (key !== loadedKey) {
    loadedKey = key;
    void load(subject);
  }
  $: mode = subject.isDir ? 'none' : previewMode(subject.ext);
  $: fileHref = filesApi.fileUrl(subject.sourceId, subject.path);
  $: typeLabel = subject.isDir ? 'Folder' : subject.ext ? `${subject.ext.toUpperCase()} file` : 'File';
  $: hasOrigin =
    annotation !== null &&
    (annotation.description.trim() !== '' ||
      annotation.links.length > 0 ||
      annotation.attachments.length > 0);

  function onKey(event: KeyboardEvent) {
    if (event.key !== 'Escape') return;
    // While editing origin, Escape stays out of the way so a draft is never lost
    // to a stray keypress; the Cancel button is the deliberate exit there.
    if (editing) return;
    dispatch('close');
  }

  async function load(current: Subject) {
    loading = true;
    error = '';
    actionError = '';
    annotation = null;
    editing = false;
    textPreview = null;
    textTruncated = false;
    archive = null;
    archiveError = '';
    picking = false;
    try {
      annotation = await filesApi.getInfo(current.sourceId, current.path);
    } catch (e) {
      error = (e as Error).message;
    } finally {
      loading = false;
    }
    if (!current.isDir && previewMode(current.ext) === 'text') {
      await loadText(current);
    }
  }

  function startEditing() {
    draftDescription = annotation?.description ?? '';
    draftLinks = (annotation?.links ?? []).map((link) => ({ ...link }));
    if (draftLinks.length === 0) addLink();
    actionError = '';
    editing = true;
  }

  function cancelEditing() {
    editing = false;
    actionError = '';
  }

  function addLink() {
    draftLinks = [...draftLinks, { url: '', label: '', kind: 'source' }];
  }

  function removeLink(index: number) {
    draftLinks = draftLinks.filter((_, i) => i !== index);
  }

  // --- Archive contents --------------------------------------------------
  // Fetched on demand rather than whenever an archive is selected: clicking
  // through a folder of zips should not fire a listing per click.
  let archive: import('../lib/filesApi').ArchiveListing | null = null;
  let archiveError = '';
  let archiveLoading = false;

  $: canListArchive = !subject.isDir && isListableArchive(subject.ext);

  async function loadArchive() {
    archiveLoading = true;
    archiveError = '';
    try {
      archive = await filesApi.listArchive(subject.sourceId, subject.path);
    } catch (e) {
      archiveError = (e as Error).message;
    } finally {
      archiveLoading = false;
    }
  }

  // --- Copy origin from another subject ---------------------------------
  // The unzip workflow: extract an archive, then carry the archive's Booth link
  // and description onto the folder that came out of it.
  let picking = false;
  let pickerPaths: string[] = [];
  let pickerFilter = '';
  let copying = false;

  $: pickerMatches = pickerPaths
    .filter((candidate) => candidate !== subject.path)
    .filter((candidate) => candidate.toLowerCase().includes(pickerFilter.toLowerCase()))
    .slice(0, 50);

  async function openPicker() {
    actionError = '';
    picking = true;
    pickerFilter = '';
    try {
      pickerPaths = await filesApi.listAnnotated(subject.sourceId);
    } catch (e) {
      actionError = (e as Error).message;
      pickerPaths = [];
    }
  }

  async function copyFrom(fromPath: string, overwrite = false) {
    copying = true;
    actionError = '';
    try {
      annotation = await filesApi.copyInfo(
        subject.sourceId,
        fromPath,
        subject.sourceId,
        subject.path,
        overwrite,
      );
      picking = false;
      dispatch('changed');
    } catch (e) {
      const error = e as ApiError;
      // 409 is the server refusing to replace text the user wrote by hand.
      if (error.status === 409 && !overwrite) {
        copying = false;
        if (confirm(`${error.message}.\n\nReplace this description?`)) {
          await copyFrom(fromPath, true);
        }
        return;
      }
      actionError = error.message;
    } finally {
      copying = false;
    }
  }

  async function save() {
    const links = draftLinks
      .map((link) => ({ url: link.url.trim(), label: link.label.trim(), kind: link.kind }))
      .filter((link) => link.url !== '');
    for (const link of links) {
      if (!/^https?:\/\//i.test(link.url)) {
        actionError = `Links must start with http:// or https:// — check: ${link.url}`;
        return;
      }
    }
    saving = true;
    actionError = '';
    try {
      // Local-state-first: adopt the server's normalized note, then fan out.
      annotation = await filesApi.saveInfo({
        source_id: subject.sourceId,
        path: subject.path,
        description: draftDescription.trim(),
        links,
      });
      editing = false;
      dispatch('changed');
    } catch (e) {
      actionError = (e as Error).message;
    } finally {
      saving = false;
    }
  }

  async function deleteInfo() {
    saving = true;
    actionError = '';
    try {
      await filesApi.deleteInfo(subject.sourceId, subject.path);
      annotation = null;
      editing = false;
      dispatch('changed');
    } catch (e) {
      actionError = (e as Error).message;
    } finally {
      saving = false;
    }
  }

  async function onUploadChange(event: Event) {
    const input = event.currentTarget as HTMLInputElement;
    const file = input.files?.[0];
    input.value = '';
    if (!file) return;
    uploading = true;
    actionError = '';
    try {
      annotation = await filesApi.uploadAttachment(subject.sourceId, subject.path, file);
      dispatch('changed');
    } catch (e) {
      actionError = (e as Error).message;
    } finally {
      uploading = false;
    }
  }

  async function removeAttachment(attachmentId: number) {
    actionError = '';
    try {
      await filesApi.deleteAttachment(attachmentId);
      annotation = await filesApi.getInfo(subject.sourceId, subject.path);
      dispatch('changed');
    } catch (e) {
      actionError = (e as Error).message;
    }
  }

  async function loadText(current: Subject) {
    try {
      const res = await fetch(filesApi.fileUrl(current.sourceId, current.path), {
        headers: { Range: `bytes=0-${TEXT_CAP - 1}` },
      });
      if (!res.ok && res.status !== 206) return;
      textPreview = await res.text();
      textTruncated = (current.size ?? 0) > TEXT_CAP;
    } catch {
      // Preview is best-effort; the facts and Open action still work.
    }
  }

  async function openExternally() {
    actionError = '';
    try {
      await filesApi.openFile(subject.sourceId, subject.path);
    } catch (e) {
      actionError = (e as Error).message;
    }
  }

  async function reveal() {
    actionError = '';
    try {
      await filesApi.revealFile(subject.sourceId, subject.path);
    } catch (e) {
      actionError = (e as Error).message;
    }
  }

  async function copyPath() {
    try {
      await navigator.clipboard.writeText(subject.absolutePath);
    } catch {
      // Clipboard can be unavailable; the path is still shown in full.
    }
  }

  function formatSize(bytes: number | null): string {
    if (bytes == null) return '—';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let n = bytes;
    let i = 0;
    while (n >= 1024 && i < units.length - 1) {
      n /= 1024;
      i += 1;
    }
    return `${i === 0 ? n : n < 10 ? n.toFixed(1) : Math.round(n)} ${units[i]}`;
  }

  function formatDate(mtime: number | null): string {
    if (!mtime) return '—';
    return new Date(mtime * 1000).toLocaleString();
  }
</script>

<svelte:window on:keydown={onKey} />

<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
<div
  class="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4"
  role="presentation"
  on:click={() => dispatch('close')}
>
  <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
  <div
    class="flex max-h-[85vh] w-full max-w-2xl flex-col overflow-hidden rounded-xl border border-[#2a2a3a] bg-[#12121a] shadow-2xl"
    role="dialog"
    aria-modal="true"
    aria-label="File information"
    tabindex="-1"
    on:click|stopPropagation
  >
    <!-- Header -->
    <div class="flex items-center gap-2 border-b border-white/5 px-4 py-3">
      <span class="text-lg leading-none">{fileGlyph({ is_dir: subject.isDir, ext: subject.ext })}</span>
      <div class="min-w-0 flex-1">
        <div class="truncate text-sm font-medium text-gray-100" title={subject.name}>{subject.name}</div>
        <div class="text-[11px] text-gray-500">{typeLabel}</div>
      </div>
      <button
        type="button"
        class="grid h-7 w-7 place-items-center rounded-md text-gray-500 transition-colors hover:bg-white/5 hover:text-white"
        title="Close"
        aria-label="Close"
        on:click={() => dispatch('close')}
      >✕</button>
    </div>

    <!-- Tabs -->
    <div class="flex shrink-0 gap-4 border-b border-white/5 px-4">
      <button
        type="button"
        class="-mb-px border-b-2 py-2 text-sm transition-colors {activeTab === 'properties' ? 'border-purple-500 text-white' : 'border-transparent text-gray-400 hover:text-gray-200'}"
        on:click={() => (activeTab = 'properties')}
      >Properties</button>
      <button
        type="button"
        class="-mb-px border-b-2 py-2 text-sm transition-colors {activeTab === 'origin' ? 'border-purple-500 text-white' : 'border-transparent text-gray-400 hover:text-gray-200'}"
        on:click={() => (activeTab = 'origin')}
      >Origin</button>
    </div>

    <!-- Body -->
    <div class="flex-1 overflow-y-auto">
      {#if activeTab === 'properties'}
        <dl class="space-y-3 px-5 py-4 text-sm">
          <div class="flex justify-between gap-4">
            <dt class="shrink-0 font-medium text-gray-400">Name</dt>
            <dd class="min-w-0 break-words text-right text-gray-200">{subject.name}</dd>
          </div>
          <div class="flex justify-between gap-4">
            <dt class="shrink-0 font-medium text-gray-400">Type</dt>
            <dd class="text-gray-200">{typeLabel}</dd>
          </div>
          <div class="flex justify-between gap-4">
            <dt class="shrink-0 font-medium text-gray-400">Size</dt>
            <dd class="text-gray-200">{subject.isDir ? '—' : formatSize(subject.size)}</dd>
          </div>
          <div class="flex justify-between gap-4">
            <dt class="shrink-0 font-medium text-gray-400">Modified</dt>
            <dd class="text-gray-200">{formatDate(subject.mtime)}</dd>
          </div>
          <div class="flex justify-between gap-4">
            <dt class="shrink-0 font-medium text-gray-400">MD5</dt>
            <dd class="min-w-0 truncate font-mono text-xs text-gray-400" title={annotation?.content_hash ?? ''}>
              {annotation?.content_hash ?? 'not computed'}
            </dd>
          </div>
          <div class="flex justify-between gap-4">
            <dt class="shrink-0 font-medium text-gray-400">Source</dt>
            <dd class="min-w-0 truncate text-gray-200" title={sourceName}>{sourceName || '—'}</dd>
          </div>
          <div>
            <dt class="mb-0.5 font-medium text-gray-400">Path</dt>
            <dd>
              <button
                type="button"
                class="w-full break-words text-left font-mono text-xs leading-relaxed text-gray-400 hover:text-gray-200"
                title="Click to copy"
                on:click={copyPath}
              >{subject.absolutePath}</button>
            </dd>
          </div>
        </dl>
      {:else}
        <!-- Preview -->
        <div class="border-b border-white/5 bg-black/20 p-3">
          {#if mode === 'image'}
            <img src={fileHref} alt={subject.name} class="mx-auto max-h-72 max-w-full rounded object-contain" />
          {:else if mode === 'video'}
            <!-- svelte-ignore a11y-media-has-caption -->
            <video src={fileHref} controls class="mx-auto max-h-72 max-w-full rounded"></video>
          {:else if mode === 'audio'}
            <audio src={fileHref} controls class="w-full"></audio>
          {:else if mode === 'pdf'}
            <embed src={fileHref} type="application/pdf" class="h-80 w-full rounded" />
          {:else if mode === 'text'}
            {#if textPreview !== null}
              <pre class="max-h-72 overflow-auto whitespace-pre-wrap break-words rounded bg-black/30 p-2 text-[11px] leading-snug text-gray-300">{textPreview}</pre>
              {#if textTruncated}
                <p class="mt-1 text-[10px] text-gray-500">Preview truncated — open externally for the full file.</p>
              {/if}
            {:else}
              <p class="py-6 text-center text-xs text-gray-600">Loading preview…</p>
            {/if}
          {:else}
            <div class="grid place-items-center py-8 text-center">
              <div class="text-5xl">{fileGlyph({ is_dir: subject.isDir, ext: subject.ext })}</div>
              <p class="mt-2 text-xs text-gray-500">No in-app preview for this type.</p>
            </div>
          {/if}
        </div>

        <!-- Origin -->
        <div class="border-b border-white/5 px-4 py-3">
          <div class="mb-2 flex items-center justify-between">
            <h3 class="text-xs font-semibold uppercase tracking-wide text-gray-400">Origin</h3>
            {#if !editing && !loading}
              <div class="flex items-center gap-3">
                <button
                  type="button"
                  class="text-xs text-gray-400 hover:text-purple-200"
                  title="Carry another file's origin note onto this one"
                  on:click={openPicker}
                >Copy from…</button>
                <button
                  type="button"
                  class="text-xs text-purple-300 hover:text-purple-200"
                  on:click={startEditing}
                >{hasOrigin ? 'Edit' : 'Add info'}</button>
              </div>
            {/if}
          </div>

          {#if picking}
            <div class="mb-3 rounded-lg border border-[#2a2a3a] bg-[#12121a] p-2">
              <div class="mb-2 flex items-center gap-2">
                <input
                  class="min-w-0 flex-1 rounded border border-[#2a2a3a] bg-[#1e1e2e] px-2 py-1 text-xs text-gray-200 outline-none placeholder:text-gray-600 focus:border-purple-500"
                  placeholder="Filter files with origin info…"
                  bind:value={pickerFilter}
                />
                <button
                  type="button"
                  class="shrink-0 text-xs text-gray-500 hover:text-gray-300"
                  on:click={() => (picking = false)}
                >Cancel</button>
              </div>
              {#if pickerMatches.length === 0}
                <p class="px-1 py-2 text-xs text-gray-600">
                  {pickerPaths.length === 0
                    ? 'Nothing in this folder has origin info yet.'
                    : 'No match.'}
                </p>
              {:else}
                <ul class="max-h-52 overflow-y-auto">
                  {#each pickerMatches as candidate (candidate)}
                    <li>
                      <button
                        type="button"
                        class="w-full truncate rounded px-2 py-1 text-left text-xs text-gray-300 hover:bg-white/5 hover:text-white disabled:opacity-40"
                        title={candidate}
                        disabled={copying}
                        on:click={() => copyFrom(candidate)}
                      >{candidate || '(this folder)'}</button>
                    </li>
                  {/each}
                </ul>
              {/if}
              <p class="mt-1 px-1 text-[10px] text-gray-600">
                Adds to this note — links and screenshots merge, nothing is removed.
              </p>
            </div>
          {/if}
          {#if loading}
            <p class="text-sm text-gray-500">Loading…</p>
          {:else if error}
            <p class="text-xs text-red-300">{error}</p>
          {:else if editing}
            <div class="space-y-3">
              <div>
                <label class="mb-1 block text-[10px] uppercase tracking-wide text-gray-500" for="origin-desc">Description</label>
                <textarea
                  id="origin-desc"
                  rows="4"
                  bind:value={draftDescription}
                  placeholder="Where is this from? What is it?"
                  class="w-full resize-y rounded-lg border border-[#2a2a3a] bg-[#1e1e2e] px-2 py-1.5 text-xs text-gray-200 outline-none placeholder:text-gray-600 focus:border-purple-500"
                ></textarea>
              </div>

              <div class="space-y-2">
                <span class="block text-[10px] uppercase tracking-wide text-gray-500">Links</span>
                {#each draftLinks as link, index (index)}
                  <div class="space-y-1 rounded-lg border border-white/5 bg-black/20 p-2">
                    <div class="flex gap-1.5">
                      <select
                        bind:value={link.kind}
                        class="shrink-0 rounded border border-[#2a2a3a] bg-[#1e1e2e] px-1 py-1 text-[11px] text-gray-300 outline-none focus:border-purple-500"
                      >
                        {#each LINK_KINDS as kind}
                          <option value={kind}>{linkKindLabel(kind)}</option>
                        {/each}
                      </select>
                      <input
                        bind:value={link.label}
                        placeholder="Label (optional)"
                        class="min-w-0 flex-1 rounded border border-[#2a2a3a] bg-[#1e1e2e] px-2 py-1 text-[11px] text-gray-200 outline-none placeholder:text-gray-600 focus:border-purple-500"
                      />
                      <button
                        type="button"
                        class="shrink-0 rounded px-1.5 text-gray-500 hover:text-red-300"
                        title="Remove link"
                        aria-label="Remove link"
                        on:click={() => removeLink(index)}
                      >✕</button>
                    </div>
                    <input
                      bind:value={link.url}
                      placeholder="https://…"
                      class="w-full rounded border border-[#2a2a3a] bg-[#1e1e2e] px-2 py-1 text-[11px] text-gray-200 outline-none placeholder:text-gray-600 focus:border-purple-500"
                    />
                  </div>
                {/each}
                <button
                  type="button"
                  class="text-[11px] text-purple-300 hover:text-purple-200"
                  on:click={addLink}
                >＋ Add link</button>
              </div>

              {#if actionError}
                <p class="text-[11px] text-red-300">{actionError}</p>
              {/if}

              <div class="flex items-center gap-2 pt-1">
                <button
                  type="button"
                  class="rounded-lg bg-purple-500/30 px-3 py-1.5 text-xs font-medium text-purple-100 transition-colors hover:bg-purple-500/40 disabled:opacity-40"
                  on:click={save}
                  disabled={saving}
                >{saving ? 'Saving…' : 'Save'}</button>
                <button
                  type="button"
                  class="rounded-lg border border-[#2a2a3a] px-3 py-1.5 text-xs text-gray-300 transition-colors hover:text-white disabled:opacity-40"
                  on:click={cancelEditing}
                  disabled={saving}
                >Cancel</button>
                {#if hasOrigin}
                  <button
                    type="button"
                    class="ml-auto text-[11px] text-red-300/80 hover:text-red-300 disabled:opacity-40"
                    on:click={deleteInfo}
                    disabled={saving}
                  >Remove all</button>
                {/if}
              </div>
            </div>
          {:else if hasOrigin && annotation}
            {#if annotation.description}
              <p class="mb-3 whitespace-pre-wrap break-words text-sm leading-relaxed text-gray-200">{annotation.description}</p>
            {/if}
            {#if annotation.links.length}
              <ul class="mb-3 space-y-1.5">
                {#each annotation.links as link (link.url + link.kind)}
                  <li class="flex items-start gap-2 text-sm">
                    <span class="mt-0.5 shrink-0 rounded bg-white/5 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-gray-400">{linkKindLabel(link.kind)}</span>
                    <a href={link.url} target="_blank" rel="noopener noreferrer" class="min-w-0 break-words text-purple-300 hover:text-purple-200">
                      {link.label || link.url}
                    </a>
                  </li>
                {/each}
              </ul>
            {/if}
          {:else}
            <p class="text-sm text-gray-500">No origin info yet.</p>
          {/if}

          {#if !editing && !loading && !error}
            <div class="mt-3">
              {#if annotation && annotation.attachments.length}
                <div class="mb-2 grid grid-cols-3 gap-1.5">
                  {#each annotation.attachments as attachment (attachment.id)}
                    <div class="group relative overflow-hidden rounded border border-white/5 bg-black/30">
                      {#if attachment.media_type.startsWith('video/')}
                        <!-- svelte-ignore a11y-media-has-caption -->
                        <video src={filesApi.attachmentUrl(attachment.id)} class="h-16 w-full object-cover" muted></video>
                      {:else}
                        <img src={filesApi.attachmentUrl(attachment.id)} alt={attachment.caption || attachment.file_name} class="h-16 w-full object-cover" />
                      {/if}
                      <button
                        type="button"
                        class="absolute right-0.5 top-0.5 hidden h-5 w-5 place-items-center rounded bg-black/70 text-[10px] text-gray-200 group-hover:grid hover:text-red-300"
                        title="Remove attachment"
                        aria-label="Remove attachment"
                        on:click={() => removeAttachment(attachment.id)}
                      >✕</button>
                    </div>
                  {/each}
                </div>
              {/if}
              <input
                bind:this={fileInput}
                type="file"
                accept="image/*,video/*"
                class="hidden"
                on:change={onUploadChange}
              />
              <button
                type="button"
                class="text-[11px] text-purple-300 hover:text-purple-200 disabled:opacity-40"
                on:click={() => fileInput.click()}
                disabled={uploading}
              >{uploading ? 'Uploading…' : '＋ Image / video'}</button>
            </div>
          {/if}
        </div>

        <!-- Archive contents — read-only; the server never extracts anything. -->
        {#if canListArchive}
          <div class="px-4 py-3">
            <div class="mb-2 flex items-center justify-between">
              <h3 class="text-xs font-semibold uppercase tracking-wide text-gray-400">Contents</h3>
              {#if archive === null && !archiveLoading}
                <button
                  type="button"
                  class="text-xs text-purple-300 hover:text-purple-200"
                  on:click={loadArchive}
                >Show contents</button>
              {/if}
            </div>

            {#if archiveLoading}
              <p class="text-sm text-gray-500">Reading…</p>
            {:else if archiveError}
              <p class="text-sm text-red-300">{archiveError}</p>
            {:else if archive}
              <p class="mb-2 text-xs text-gray-500">
                {archive.total_entries} item{archive.total_entries === 1 ? '' : 's'} ·
                {formatSize(archive.total_size)} unpacked · {formatSize(archive.compressed_size)} stored
              </p>
              <ul class="max-h-64 overflow-y-auto rounded bg-black/20 p-1">
                {#each archive.entries as entry (entry.name)}
                  <li class="flex items-baseline gap-2 px-1 py-0.5 text-xs">
                    <span class="min-w-0 flex-1 truncate font-mono text-gray-300" title={entry.name}>
                      {entry.is_dir ? '📁' : ''}{entry.name}
                    </span>
                    {#if !entry.is_dir}
                      <span class="shrink-0 text-[10px] text-gray-500">{formatSize(entry.size)}</span>
                    {/if}
                  </li>
                {/each}
              </ul>
              {#if archive.truncated}
                <p class="mt-1 text-[10px] text-gray-500">
                  Showing the first {archive.entries.length} of {archive.total_entries}.
                </p>
              {/if}
            {/if}
          </div>
        {/if}
      {/if}
    </div>

    <!-- Actions — always available regardless of tab. -->
    <div class="shrink-0 border-t border-white/5 px-4 py-3">
      <div class="flex gap-2">
        <button
          type="button"
          class="flex-1 rounded-lg border border-[#2a2a3a] bg-[#1e1e2e] px-3 py-1.5 text-sm text-gray-300 transition-colors hover:border-purple-500/50 hover:text-white"
          on:click={openExternally}
        >Open</button>
        <button
          type="button"
          class="flex-1 rounded-lg border border-[#2a2a3a] bg-[#1e1e2e] px-3 py-1.5 text-sm text-gray-300 transition-colors hover:border-purple-500/50 hover:text-white"
          on:click={reveal}
        >Show in folder</button>
      </div>
      {#if actionError}
        <p class="mt-2 text-[11px] text-red-300">{actionError}</p>
      {/if}
    </div>
  </div>
</div>
