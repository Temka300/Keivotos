<script lang="ts">
  import { onMount } from 'svelte';
  import { api, type CollectionInfo } from '../lib/api';
  import { viewMode, activeCollectionId, collectionRefreshToken } from '../lib/stores';
  import CollectionPreviewGrid from './CollectionPreviewGrid.svelte';

  let collections: CollectionInfo[] = [];
  let newName = '';
  let newDesc = '';
  let showCreate = false;
  let pinBusy = new Set<number>();
  let editingId: number | null = null;
  let editName = '';
  let editDesc = '';
  let editSaving = false;
  let editError = '';
  let deletingIds = new Set<number>();

  onMount(async () => {
    collections = await api.getCollections();
  });

  async function createCollection() {
    if (!newName.trim()) return;
    const col = await api.createCollection(newName.trim(), newDesc.trim());
    collections = sortCollections([col, ...collections]);
    newName = '';
    newDesc = '';
    showCreate = false;
    collectionRefreshToken.update(n => n + 1);
  }

  function sortCollections(items: CollectionInfo[]) {
    return [...items].sort((a, b) => {
      if (a.pinned_at && !b.pinned_at) return -1;
      if (!a.pinned_at && b.pinned_at) return 1;
      if (a.pinned_at && b.pinned_at) return b.pinned_at.localeCompare(a.pinned_at);
      return b.created_at.localeCompare(a.created_at);
    });
  }

  async function toggleCollectionPin(col: CollectionInfo, event: MouseEvent) {
    event.stopPropagation();
    if (pinBusy.has(col.id)) return;
    pinBusy = new Set(pinBusy).add(col.id);
    try {
      const result = await api.toggleCollectionPin(col.id);
      collections = sortCollections(collections.map(item =>
        item.id === col.id ? { ...item, pinned_at: result.pinned_at } : item
      ));
      collectionRefreshToken.update(n => n + 1);
    } finally {
      const next = new Set(pinBusy);
      next.delete(col.id);
      pinBusy = next;
    }
  }

  function startEdit(col: CollectionInfo, event?: MouseEvent) {
    event?.stopPropagation();
    editingId = col.id;
    editName = col.name;
    editDesc = col.description ?? '';
    editError = '';
  }

  function cancelEdit() {
    editingId = null;
    editName = '';
    editDesc = '';
    editError = '';
  }

  async function saveCollection(col: CollectionInfo) {
    const name = editName.trim();
    if (!name || editSaving) return;
    editSaving = true;
    editError = '';
    try {
      const updated = await api.updateCollection(col.id, name, editDesc.trim());
      collections = sortCollections(collections.map(item => item.id === col.id ? updated : item));
      cancelEdit();
      collectionRefreshToken.update(n => n + 1);
    } catch (e) {
      console.error(e);
      editError = 'Failed to save collection';
    } finally {
      editSaving = false;
    }
  }

  function onEditKeydown(event: KeyboardEvent, col: CollectionInfo) {
    if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      saveCollection(col);
    } else if (event.key === 'Escape') {
      event.preventDefault();
      cancelEdit();
    }
  }

  async function deleteCollection(col: CollectionInfo, event?: MouseEvent) {
    event?.stopPropagation();
    if (deletingIds.has(col.id)) return;
    const confirmed = window.confirm(`Delete collection "${col.name}"? Images stay on disk.`);
    if (!confirmed) return;
    deletingIds = new Set(deletingIds).add(col.id);
    try {
      await api.deleteCollection(col.id);
      collections = collections.filter(c => c.id !== col.id);
      if ($activeCollectionId === col.id) {
        activeCollectionId.set(null);
        viewMode.set('collections');
      }
      if (editingId === col.id) cancelEdit();
      collectionRefreshToken.update(n => n + 1);
    } finally {
      const next = new Set(deletingIds);
      next.delete(col.id);
      deletingIds = next;
    }
  }

  function openCollection(id: number) {
    activeCollectionId.set(id);
    viewMode.set('collection-detail');
  }
</script>

<div class="h-full overflow-y-auto p-6">
  <div class="flex items-center justify-between mb-6">
    <h2 class="text-xl font-semibold">Collections</h2>
    <button
      class="px-4 py-2 bg-purple-600 hover:bg-purple-500 rounded-lg text-sm transition-colors"
      on:click={() => showCreate = !showCreate}
    >
      {showCreate ? 'Cancel' : 'New Collection'}
    </button>
  </div>

  {#if showCreate}
    <div class="bg-[#1a1a24] rounded-lg p-4 mb-6 border border-[#2a2a3a]">
      <input
        type="text"
        bind:value={newName}
        placeholder="Collection name"
        class="w-full bg-[#16161e] border border-[#2a2a3a] rounded-lg px-3 py-2 text-sm mb-2 outline-none focus:border-purple-500"
      />
      <input
        type="text"
        bind:value={newDesc}
        placeholder="Description (optional)"
        class="w-full bg-[#16161e] border border-[#2a2a3a] rounded-lg px-3 py-2 text-sm mb-3 outline-none focus:border-purple-500"
      />
      <button
        class="px-4 py-2 bg-purple-600 hover:bg-purple-500 rounded-lg text-sm transition-colors"
        on:click={createCollection}
      >Create</button>
    </div>
  {/if}

  {#if collections.length === 0}
    <div class="flex flex-col items-center justify-center py-20 text-gray-500">
      <svg class="w-16 h-16 mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10"/>
      </svg>
      <p class="text-lg">No collections yet</p>
      <p class="text-sm">Create one to organize your favorites</p>
    </div>
  {:else}
    <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
      {#each collections as col}
        <div class="relative bg-[#1a1a24] rounded-lg border border-[#2a2a3a] overflow-hidden hover:border-purple-500/30 transition-colors group">
          <button
            class="absolute left-2 top-2 z-10 flex h-7 w-7 items-center justify-center rounded-full border shadow transition-all {col.pinned_at ? 'border-amber-300/60 bg-amber-500/85 text-[#16110a]' : 'border-white/15 bg-black/55 text-gray-300 opacity-0 hover:border-amber-300/50 hover:text-amber-200 group-hover:opacity-100'} disabled:cursor-not-allowed disabled:opacity-50"
            disabled={pinBusy.has(col.id)}
            on:click={(event) => toggleCollectionPin(col, event)}
            title="{col.pinned_at ? 'Unpin collection' : 'Pin collection to front'}"
            aria-label="{col.pinned_at ? 'Unpin' : 'Pin'} {col.name}"
          >
            <svg class="h-4 w-4 {col.pinned_at ? 'fill-current' : ''}" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 4l5 5-4 1-4.5 4.5V18L9 20.5 3.5 15 6 12.5h3.5L14 8l1-4z"/>
            </svg>
          </button>
          <button
            class="w-full aspect-video cursor-pointer bg-[#1e1e2e]"
            on:click={() => openCollection(col.id)}
          >
            <CollectionPreviewGrid
              items={col.preview_items ?? []}
              previewIds={col.preview_ids}
              size={360}
            />
          </button>
          <div class="p-3">
            {#if editingId === col.id}
              <div class="space-y-2">
                {#if editError}
                  <div class="rounded border border-red-500/30 bg-red-500/10 px-2 py-1 text-xs text-red-300">{editError}</div>
                {/if}
                <input
                  type="text"
                  bind:value={editName}
                  class="w-full rounded border border-[#2a2a3a] bg-[#16161e] px-2 py-1.5 text-sm text-gray-100 outline-none focus:border-purple-500"
                  placeholder="Collection name"
                  on:keydown={(event) => onEditKeydown(event, col)}
                />
                <textarea
                  bind:value={editDesc}
                  rows="3"
                  class="w-full resize-none rounded border border-[#2a2a3a] bg-[#16161e] px-2 py-1.5 text-xs text-gray-300 outline-none focus:border-purple-500"
                  placeholder="Description"
                  on:keydown={(event) => onEditKeydown(event, col)}
                ></textarea>
                <div class="flex items-center justify-between gap-2">
                  <span class="text-xs text-gray-600">{col.image_count} images</span>
                  <div class="flex gap-1.5">
                    <button
                      class="rounded border border-[#2a2a3a] px-2 py-1 text-xs text-gray-400 transition-colors hover:bg-[#242436]"
                      disabled={editSaving}
                      on:click={cancelEdit}
                    >Cancel</button>
                    <button
                      class="rounded border border-purple-500/40 bg-purple-600/30 px-2 py-1 text-xs text-purple-200 transition-colors hover:bg-purple-600/40 disabled:cursor-not-allowed disabled:opacity-50"
                      disabled={editSaving || !editName.trim()}
                      on:click={() => saveCollection(col)}
                    >{editSaving ? 'Saving...' : 'Save'}</button>
                  </div>
                </div>
              </div>
            {:else}
              <div class="flex items-start justify-between gap-2">
                <button
                  class="min-w-0 flex-1 truncate text-left text-sm font-medium transition-colors hover:text-purple-300"
                  on:click={() => openCollection(col.id)}
                  title={col.name}
                >{col.name}</button>
                <div class="flex shrink-0 items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100">
                  <button
                    class="rounded p-1 text-gray-500 transition-colors hover:bg-[#242436] hover:text-purple-300"
                    on:click={() => openCollection(col.id)}
                    title="Open collection"
                  >
                    <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5h10v10M19 5L5 19"/>
                    </svg>
                  </button>
                  <button
                    class="rounded p-1 text-gray-500 transition-colors hover:bg-[#242436] hover:text-cyan-300"
                    on:click={(event) => startEdit(col, event)}
                    title="Edit collection"
                  >
                    <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 20h4L18.5 9.5a2.1 2.1 0 00-3-3L5 17v3z"/>
                    </svg>
                  </button>
                  <button
                    class="rounded p-1 text-gray-500 transition-colors hover:bg-red-500/10 hover:text-red-400 disabled:cursor-not-allowed disabled:opacity-50"
                    disabled={deletingIds.has(col.id)}
                    on:click={(event) => deleteCollection(col, event)}
                    title="Delete collection"
                  >
                    <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
                    </svg>
                  </button>
                </div>
              </div>
              {#if col.description}
                <p class="mt-1 line-clamp-2 text-xs leading-snug text-gray-500" title={col.description}>{col.description}</p>
              {:else}
                <p class="mt-1 text-xs text-gray-700">No description</p>
              {/if}
              <div class="mt-2 flex items-center justify-between text-xs text-gray-600">
                <span>{col.image_count} images</span>
                {#if col.pinned_at}
                  <span class="text-amber-300/80">Pinned</span>
                {/if}
              </div>
            {/if}
          </div>
        </div>
      {/each}
    </div>
  {/if}
</div>
