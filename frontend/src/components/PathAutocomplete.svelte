<script lang="ts">
  import { createEventDispatcher, onDestroy } from 'svelte';
  import { filesApi, type FsEntry } from '../lib/filesApi';

  export let value = '';
  export let placeholder = 'D:\\Pictures\\Attachments';
  export let disabled = false;

  // Obsidian-style: the user types a path and picks from folder suggestions that
  // match the trailing segment. Suggestions render in-flow (not an absolute
  // dropdown) so they never clip against the settings modal's scroll area.
  const dispatch = createEventDispatcher<{ submit: string }>();

  let entries: FsEntry[] = [];
  let open = false;
  let loading = false;
  let error = '';
  let debounce: ReturnType<typeof setTimeout> | null = null;

  function endsWithSeparator(path: string): boolean {
    return /[\\/]$/.test(path);
  }

  function directoryOf(path: string): string {
    const index = Math.max(path.lastIndexOf('\\'), path.lastIndexOf('/'));
    return index < 0 ? '' : path.slice(0, index + 1);
  }

  function trailingTerm(path: string): string {
    const index = Math.max(path.lastIndexOf('\\'), path.lastIndexOf('/'));
    return index < 0 ? path : path.slice(index + 1);
  }

  async function refresh() {
    error = '';
    loading = true;
    try {
      const listDir = endsWithSeparator(value) ? value : directoryOf(value);
      const term = endsWithSeparator(value) ? '' : trailingTerm(value).toLowerCase();
      const listing = await filesApi.browseFs(listDir);
      entries = term
        ? listing.entries.filter((entry) => entry.name.toLowerCase().includes(term))
        : listing.entries;
      open = true;
    } catch (e) {
      error = (e as Error).message;
      entries = [];
      open = true;
    } finally {
      loading = false;
    }
  }

  function onInput() {
    if (debounce) clearTimeout(debounce);
    debounce = setTimeout(refresh, 200);
  }

  function onFocus() {
    if (!open && !disabled) void refresh();
  }

  function pick(entry: FsEntry) {
    // Drill into the folder: append a separator so the next keystroke lists it.
    value = entry.path.replace(/[\\/]*$/, '') + '\\';
    void refresh();
  }

  function onKeydown(event: KeyboardEvent) {
    if (event.key === 'Enter') {
      event.preventDefault();
      dispatch('submit', value.trim());
      open = false;
    } else if (event.key === 'Escape') {
      open = false;
    }
  }

  onDestroy(() => {
    if (debounce) clearTimeout(debounce);
  });
</script>

<div class="relative">
  <input
    class="w-full rounded-lg border border-[#303040] bg-[#0d0d13] px-3 py-2 font-mono text-xs text-gray-200 outline-none placeholder:text-gray-650 focus:border-purple-400/60 disabled:opacity-50"
    type="text"
    autocomplete="off"
    spellcheck="false"
    {placeholder}
    {disabled}
    bind:value
    on:input={onInput}
    on:focus={onFocus}
    on:keydown={onKeydown}
    aria-label="Attachment folder path"
  />

  {#if open && !disabled}
    <div class="mt-1.5 max-h-52 overflow-y-auto rounded-lg border border-[#2a2a3a] bg-[#14141c] p-1">
      {#if loading}
        <p class="px-2 py-2 text-xs text-gray-500">Loading…</p>
      {:else if error}
        <p class="px-2 py-2 text-xs text-red-300">{error}</p>
      {:else if entries.length === 0}
        <p class="px-2 py-2 text-xs text-gray-500">No matching folders.</p>
      {:else}
        {#each entries as entry (entry.path)}
          <button
            type="button"
            class="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-xs text-gray-200 hover:bg-white/10"
            on:click={() => pick(entry)}
          >
            <span class="text-gray-500">📁</span>
            <span class="min-w-0 flex-1 truncate">{entry.name}</span>
            <span class="text-gray-600">›</span>
          </button>
        {/each}
      {/if}
    </div>
  {/if}
</div>
