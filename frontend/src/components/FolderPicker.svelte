<script lang="ts">
  import { createEventDispatcher } from 'svelte';
  import { filesApi, type FsListing } from '../lib/filesApi';

  export let roots: Array<{ name: string; path: string }> = [];

  const dispatch = createEventDispatcher<{ select: string; close: void }>();

  let listing: FsListing | null = null;
  let activeRoot: { name: string; path: string } | null = null;
  let showingRoots = true;
  let loading = false;
  let error = '';

  $: canChoose = Boolean(
    activeRoot
    && listing
    && normalizedPath(listing.path) !== normalizedPath(activeRoot.path)
  );

  function normalizedPath(path: string): string {
    return path.replace(/[\\/]+/g, '/').replace(/\/+$/, '').toLocaleLowerCase();
  }

  function isInsideRoot(path: string, root: string): boolean {
    const candidate = normalizedPath(path);
    const boundary = normalizedPath(root);
    return candidate === boundary || candidate.startsWith(`${boundary}/`);
  }

  async function load(path: string) {
    if (!activeRoot || !isInsideRoot(path, activeRoot.path)) {
      error = 'Choose a folder inside one of the added folders.';
      return;
    }
    loading = true;
    showingRoots = false;
    error = '';
    try {
      const next = await filesApi.browseFs(path);
      if (!isInsideRoot(next.path, activeRoot.path)) {
        throw new Error('Folder navigation cannot leave the added folder.');
      }
      listing = {
        ...next,
        entries: next.entries.filter((entry) => isInsideRoot(entry.path, activeRoot?.path ?? '')),
      };
      showingRoots = false;
    } catch (e) {
      error = (e as Error).message;
    } finally {
      loading = false;
    }
  }

  async function openRoot(root: { name: string; path: string }) {
    activeRoot = root;
    await load(root.path);
  }

  function showRootList() {
    showingRoots = true;
    activeRoot = null;
    listing = null;
    error = '';
  }

  async function goUp() {
    if (!activeRoot || !listing) return;
    if (normalizedPath(listing.path) === normalizedPath(activeRoot.path)) {
      showRootList();
      return;
    }
    if (!listing.parent || !isInsideRoot(listing.parent, activeRoot.path)) {
      showRootList();
      return;
    }
    await load(listing.parent);
  }

  function choose() {
    if (canChoose && listing?.path) dispatch('select', listing.path);
  }
</script>

<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
<div class="fixed inset-0 z-[110] grid place-items-center bg-black/60 p-4" on:click={() => dispatch('close')}>
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div
    class="flex h-[70vh] w-[min(560px,92vw)] flex-col overflow-hidden rounded-xl border border-[#2a2a3a] bg-[#14141c] shadow-2xl shadow-black/70"
    role="dialog"
    tabindex="-1"
    aria-modal="true"
    aria-labelledby="folder-picker-title"
    on:click|stopPropagation
  >
    <header class="flex items-center justify-between border-b border-[#242432] px-4 py-3">
      <span id="folder-picker-title" class="text-sm font-semibold text-gray-200">Choose a folder inside an added folder</span>
      <button class="text-gray-500 hover:text-white" on:click={() => dispatch('close')} aria-label="Close">✕</button>
    </header>

    <div class="flex items-center gap-2 border-b border-[#242432] px-4 py-2">
      <button
        class="rounded px-2 py-1 text-xs text-gray-300 hover:bg-white/10 disabled:opacity-30"
        on:click={goUp}
        disabled={loading || showingRoots}
        title="Up one level"
      >↑ Up</button>
      <span class="min-w-0 flex-1 truncate text-xs text-gray-400" title={listing?.path ?? ''}>
        {showingRoots ? 'Added folders' : listing?.path ?? activeRoot?.path}
      </span>
    </div>

    <div class="flex-1 overflow-y-auto p-2">
      {#if showingRoots}
        {#if roots.length === 0}
          <p class="px-2 py-3 text-sm leading-relaxed text-gray-500">
            Add a top-level folder with the sidebar + button first.
          </p>
        {:else}
          {#each roots as root (root.path)}
            <button
              class="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm text-gray-200 hover:bg-white/10"
              on:click={() => openRoot(root)}
            >
              <span>📁</span>
              <span class="min-w-0 flex-1 truncate">{root.name}</span>
              <span class="text-gray-600">›</span>
            </button>
          {/each}
        {/if}
      {:else if loading}
        <p class="px-2 py-3 text-sm text-gray-500">Loading…</p>
      {:else if error}
        <p class="px-2 py-3 text-sm text-red-300">{error}</p>
      {:else if listing && listing.entries.length === 0}
        <p class="px-2 py-3 text-sm text-gray-500">No subfolders here.</p>
      {:else if listing}
        {#each listing.entries as entry (entry.path)}
          <button
            class="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm text-gray-200 hover:bg-white/10"
            on:click={() => load(entry.path)}
          >
            <span>📁</span>
            <span class="min-w-0 flex-1 truncate">{entry.name}</span>
            <span class="text-gray-600">›</span>
          </button>
        {/each}
      {/if}
    </div>

    <footer class="flex items-center justify-end gap-2 border-t border-[#242432] px-4 py-3">
      <button class="rounded px-3 py-1.5 text-xs text-gray-400 hover:text-white" on:click={() => dispatch('close')}>Cancel</button>
      <button
        class="rounded bg-purple-500/25 px-3 py-1.5 text-xs font-medium text-purple-100 hover:bg-purple-500/35 disabled:opacity-40"
        on:click={choose}
        disabled={!canChoose}
      >Add this folder</button>
    </footer>
  </div>
</div>
