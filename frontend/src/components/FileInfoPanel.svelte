<script lang="ts">
  import { createEventDispatcher } from 'svelte';
  import { filesApi, type Annotation } from '../lib/filesApi';
  import { fileGlyph, linkKindLabel, previewMode, type Subject } from '../lib/filePreview';

  export let subject: Subject;

  const dispatch = createEventDispatcher<{ close: void }>();
  const TEXT_CAP = 1024 * 1024;

  let annotation: Annotation | null = null;
  let loading = false;
  let error = '';
  let actionError = '';
  let textPreview: string | null = null;
  let textTruncated = false;
  let loadedKey = '';

  $: key = `${subject.sourceId}::${subject.path}`;
  $: if (key !== loadedKey) {
    loadedKey = key;
    void load(subject);
  }
  $: mode = subject.isDir ? 'none' : previewMode(subject.ext);
  $: fileHref = filesApi.fileUrl(subject.sourceId, subject.path);
  $: hasOrigin =
    annotation !== null &&
    (annotation.description.trim() !== '' ||
      annotation.links.length > 0 ||
      annotation.attachments.length > 0);

  async function load(current: Subject) {
    loading = true;
    error = '';
    actionError = '';
    annotation = null;
    textPreview = null;
    textTruncated = false;
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

<aside class="flex w-[22rem] shrink-0 flex-col border-l border-white/5 bg-[#0b0b10]">
  <div class="flex items-center gap-2 border-b border-white/5 px-4 py-3">
    <span class="text-lg leading-none">{fileGlyph({ is_dir: subject.isDir, ext: subject.ext })}</span>
    <div class="min-w-0 flex-1">
      <div class="truncate text-sm font-medium text-gray-100" title={subject.name}>{subject.name}</div>
      <div class="text-[11px] text-gray-500">{subject.isDir ? 'Folder' : (subject.ext || 'file').toUpperCase()}</div>
    </div>
    <button
      type="button"
      class="grid h-7 w-7 place-items-center rounded-md text-gray-500 transition-colors hover:bg-white/5 hover:text-white"
      title="Close info"
      aria-label="Close info"
      on:click={() => dispatch('close')}
    >✕</button>
  </div>

  <div class="flex-1 overflow-y-auto">
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

    <!-- Facts -->
    <dl class="space-y-1.5 px-4 py-3 text-xs">
      <div class="flex justify-between gap-3">
        <dt class="text-gray-500">Size</dt>
        <dd class="text-gray-300">{subject.isDir ? '—' : formatSize(subject.size)}</dd>
      </div>
      <div class="flex justify-between gap-3">
        <dt class="text-gray-500">Modified</dt>
        <dd class="text-gray-300">{formatDate(subject.mtime)}</dd>
      </div>
      <div class="flex justify-between gap-3">
        <dt class="shrink-0 text-gray-500">MD5</dt>
        <dd class="truncate font-mono text-[10px] text-gray-400" title={annotation?.content_hash ?? ''}>
          {annotation?.content_hash ?? 'not computed'}
        </dd>
      </div>
      <div>
        <dt class="mb-0.5 text-gray-500">Path</dt>
        <dd>
          <button
            type="button"
            class="w-full break-all text-left font-mono text-[10px] text-gray-400 hover:text-gray-200"
            title="Click to copy"
            on:click={copyPath}
          >{subject.absolutePath}</button>
        </dd>
      </div>
    </dl>

    <!-- Actions -->
    <div class="flex gap-2 px-4 pb-3">
      <button
        type="button"
        class="flex-1 rounded-lg border border-[#2a2a3a] bg-[#1e1e2e] px-3 py-1.5 text-xs text-gray-300 transition-colors hover:border-purple-500/50 hover:text-white"
        on:click={openExternally}
      >Open</button>
      <button
        type="button"
        class="flex-1 rounded-lg border border-[#2a2a3a] bg-[#1e1e2e] px-3 py-1.5 text-xs text-gray-300 transition-colors hover:border-purple-500/50 hover:text-white"
        on:click={reveal}
      >Show in folder</button>
    </div>
    {#if actionError}
      <p class="px-4 pb-2 text-[11px] text-red-300">{actionError}</p>
    {/if}

    <!-- Origin -->
    <div class="border-t border-white/5 px-4 py-3">
      <h3 class="mb-2 text-[11px] font-semibold uppercase tracking-wide text-gray-400">Origin</h3>
      {#if loading}
        <p class="text-xs text-gray-600">Loading…</p>
      {:else if error}
        <p class="text-xs text-red-300">{error}</p>
      {:else if hasOrigin && annotation}
        {#if annotation.description}
          <p class="mb-3 whitespace-pre-wrap break-words text-xs leading-relaxed text-gray-300">{annotation.description}</p>
        {/if}
        {#if annotation.links.length}
          <ul class="mb-3 space-y-1.5">
            {#each annotation.links as link (link.url + link.kind)}
              <li class="flex items-start gap-2 text-xs">
                <span class="mt-0.5 shrink-0 rounded bg-white/5 px-1.5 py-0.5 text-[9px] uppercase tracking-wide text-gray-400">{linkKindLabel(link.kind)}</span>
                <a href={link.url} target="_blank" rel="noopener noreferrer" class="min-w-0 break-all text-purple-300 hover:text-purple-200">
                  {link.label || link.url}
                </a>
              </li>
            {/each}
          </ul>
        {/if}
        {#if annotation.attachments.length}
          <div class="flex flex-wrap gap-1.5">
            {#each annotation.attachments as attachment (attachment.id)}
              <span class="rounded bg-white/5 px-1.5 py-0.5 text-[10px] text-gray-400" title={attachment.file_name}>{attachment.file_name}</span>
            {/each}
          </div>
        {/if}
      {:else}
        <p class="text-xs text-gray-600">No origin info yet.</p>
      {/if}
    </div>
  </div>
</aside>
