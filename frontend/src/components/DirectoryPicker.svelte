<script lang="ts">
  import { onDestroy } from 'svelte';
  import { filesApi, type FsListing } from '../lib/filesApi';

  let dialog: HTMLDialogElement;
  let pathInput: HTMLInputElement;
  let listing: FsListing | null = null;
  let pathDraft = '';
  let loading = false;
  let error = '';
  let request = 0;
  let destroyed = false;
  let returnFocus: HTMLElement | null = null;
  let pending: Promise<string | null> | null = null;
  let resolveSelection: ((path: string | null) => void) | null = null;

  $: canChoose = Boolean(listing?.path && !loading && !error && pathDraft === listing.path);

  // Native cancellation stays cancellation. Only an unavailable native picker
  // opens the in-app dialog, shared by Files and suite Settings.
  export function pick(initialPath = ''): Promise<string | null> {
    if (pending) return pending;
    returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    pending = begin(initialPath).finally(() => { pending = null; });
    return pending;
  }

  async function begin(initialPath: string): Promise<string | null> {
    const native = await filesApi.pickFolder();
    if (destroyed) return null;
    if (native.native) return native.path;
    listing = null;
    pathDraft = initialPath;
    error = '';
    const result = new Promise<string | null>((resolve) => { resolveSelection = resolve; });
    dialog.showModal();
    pathInput.focus();
    void load(initialPath);
    return result;
  }

  async function load(path: string) {
    const current = ++request;
    loading = true;
    error = '';
    try {
      const next = await filesApi.browseFs(path.trim());
      if (current !== request || destroyed) return;
      listing = next;
      pathDraft = next.path;
    } catch (e) {
      if (current === request && !destroyed) error = (e as Error).message;
    } finally {
      if (current === request && !destroyed) loading = false;
    }
  }

  function finish(path: string | null) {
    const closedRequest = ++request;
    loading = false;
    dialog?.close();
    const resolve = resolveSelection;
    resolveSelection = null;
    resolve?.(path);
    // Callers may keep the opening button disabled until pick() resolves.
    // Restore focus after their pending state and Svelte updates have settled.
    setTimeout(() => {
      if (!destroyed && request === closedRequest && !dialog.open && returnFocus?.isConnected) {
        returnFocus.focus();
      }
    }, 0);
  }

  function handleKeydown(event: KeyboardEvent) {
    event.stopPropagation();
    if (event.key === 'Escape') {
      event.preventDefault();
      finish(null);
    } else if (event.key === 'Tab') {
      const controls = Array.from(dialog.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled])'));
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    }
  }

  function backdropClick(event: MouseEvent) {
    event.stopPropagation();
    if (event.target !== dialog) return;
    const bounds = dialog.getBoundingClientRect();
    if (event.clientX < bounds.left || event.clientX > bounds.right
      || event.clientY < bounds.top || event.clientY > bounds.bottom) finish(null);
  }

  onDestroy(() => {
    destroyed = true;
    finish(null);
  });
</script>

<dialog
  bind:this={dialog}
  aria-label="Choose a folder"
  class="m-auto w-[min(560px,92vw)] rounded-xl border border-[#2a2a3a] bg-[#14141c] p-0 text-gray-200 shadow-2xl"
  on:cancel={(event) => { event.preventDefault(); finish(null); }}
  on:keydown={handleKeydown}
  on:click={backdropClick}
>
  <div class="flex h-[min(580px,80vh)] flex-col">
    <header class="flex items-center justify-between border-b border-[#242432] px-4 py-3">
      <h2 class="text-sm font-semibold">Choose a folder</h2>
      <button type="button" class="text-gray-400 hover:text-white" aria-label="Close folder picker" on:click={() => finish(null)}>✕</button>
    </header>
    <form class="flex gap-2 border-b border-[#242432] p-3" on:submit|preventDefault={() => load(pathDraft)}>
      <input bind:this={pathInput} bind:value={pathDraft} aria-label="Folder path" placeholder="Enter an absolute folder path" autocomplete="off" spellcheck="false"
        on:input={() => { ++request; loading = false; }}
        class="min-w-0 flex-1 rounded border border-[#303040] bg-[#0d0d13] px-3 py-2 text-xs outline-none focus:border-purple-400" />
      <button type="submit" class="rounded px-3 py-2 text-xs hover:bg-white/10">Go</button>
    </form>
    <div class="flex items-center gap-2 border-b border-[#242432] px-3 py-2">
      <button type="button" class="rounded px-2 py-1 text-xs hover:bg-white/10 disabled:opacity-30" disabled={loading || listing?.parent == null}
        on:click={() => load(listing?.parent ?? '')}>↑ Up</button>
      <span class="truncate text-xs text-gray-400" title={listing?.path ?? ''}>{listing?.path || 'Locations'}</span>
    </div>
    <div class="min-h-0 flex-1 overflow-y-auto p-2" aria-busy={loading}>
      {#if loading}
        <p class="p-3 text-sm text-gray-400">Loading…</p>
      {:else if error}
        <p role="alert" class="p-3 text-sm text-red-300">{error}</p>
      {:else if listing?.entries.length === 0}
        <p class="p-3 text-sm text-gray-400">No visible subfolders. The folder may be empty or unavailable.</p>
      {:else if listing}
        {#each listing.entries as entry (entry.path)}
          <button type="button" class="flex w-full items-center gap-2 rounded px-3 py-2 text-left text-sm hover:bg-white/10" on:click={() => load(entry.path)}>
            <span aria-hidden="true">📁</span><span class="min-w-0 flex-1 truncate">{entry.name}</span><span aria-hidden="true">›</span>
          </button>
        {/each}
      {/if}
    </div>
    <footer class="flex justify-end gap-2 border-t border-[#242432] p-3">
      <button type="button" class="rounded px-3 py-2 text-xs text-gray-400 hover:text-white" on:click={() => finish(null)}>Cancel</button>
      <button type="button" class="rounded bg-purple-500/25 px-3 py-2 text-xs text-purple-100 hover:bg-purple-500/35 disabled:opacity-40"
        disabled={!canChoose} on:click={() => finish(listing?.path ?? null)}>Choose this folder</button>
    </footer>
  </div>
</dialog>

<style>
  dialog::backdrop { background: rgb(0 0 0 / 65%); }
</style>
