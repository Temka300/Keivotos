<script lang="ts">
  import { createEventDispatcher } from 'svelte';
  import type { SourceInfo } from '../lib/filesApi';
  import {
    displayNameForPath,
    normalizedPath,
    suiteApi,
    type FolderBatchResult,
    type FolderChange,
    type SuiteModule,
  } from '../lib/suiteApi';
  import { moduleUi } from '../modules/registry';
  import FolderPicker from './FolderPicker.svelte';

  export let sources: SourceInfo[] = [];
  export let modules: SuiteModule[] = [];

  interface FolderDraft extends FolderChange {
    key: string;
    original_role: string;
  }

  const dispatch = createEventDispatcher<{ saved: FolderBatchResult; close: void }>();
  let drafts: FolderDraft[] = sources.map(toDraft);
  let saving = false;
  let showPicker = false;
  let error = '';

  $: baseModule = modules.find((module) => module.is_base) ?? null;
  $: activeDrafts = drafts.filter((draft) => !draft.forget);
  $: registeredDrafts = activeDrafts.filter((draft) => draft.source_id);
  $: pickerRoots = registeredDrafts
    .filter((draft) => !registeredDrafts.some(
      (candidate) => candidate.key !== draft.key && isStrictDescendantPath(draft.path, candidate.path)
    ))
    .map((draft) => ({ name: draft.display_name, path: draft.path }));

  function toDraft(source: SourceInfo): FolderDraft {
    return {
      key: source.source_id,
      source_id: source.source_id,
      path: source.path,
      display_name: source.display_name,
      role: source.role === 'base' ? 'files' : source.role,
      original_role: source.role === 'base' ? 'files' : source.role,
      visible: source.visible,
      forget: false,
    };
  }

  function roleModules(draft: FolderDraft): SuiteModule[] {
    return modules.filter((module) => module.is_base || module.enabled || module.slug === draft.original_role);
  }

  function moduleName(slug: string): string {
    return modules.find((module) => module.slug === slug)?.name ?? slug;
  }

  function isStrictDescendantPath(path: string, parent: string): boolean {
    const candidate = normalizedPath(path);
    const boundary = normalizedPath(parent);
    return candidate !== boundary && candidate.startsWith(`${boundary}/`);
  }

  function stagePath(path: string) {
    showPicker = false;
    const cleanPath = path.trim();
    if (!cleanPath) return;
    if (drafts.some((draft) => !draft.forget && normalizedPath(draft.path) === normalizedPath(cleanPath))) {
      error = 'That folder is already in the registry.';
      return;
    }
    const role = baseModule?.slug ?? 'files';
    drafts = [
      ...drafts,
      {
        key: `new:${cleanPath}`,
        source_id: null,
        path: cleanPath,
        display_name: displayNameForPath(cleanPath),
        role,
        original_role: role,
        visible: true,
        forget: false,
      },
    ];
  }

  function beginAddFolder() {
    if (saving) return;
    error = '';
    showPicker = true;
  }

  function setVisible(key: string, visible: boolean) {
    drafts = drafts.map((draft) => draft.key === key ? { ...draft, visible } : draft);
  }

  async function markForgotten(draft: FolderDraft) {
    error = '';
    if (!draft.source_id) {
      drafts = drafts.filter((candidate) => candidate.key !== draft.key);
      return;
    }
    try {
      const preview = await suiteApi.previewFolderForget(draft.source_id);
      const indexed = preview.base_files + preview.module_files;
      const confirmed = window.confirm(
        `Forget “${preview.display_name}”?\n\n` +
        `${indexed} indexed entries will be removed from Keivotos. ` +
        `The original folder and ${preview.sidecars_preserved} sidecars stay on disk.\n\n` +
        'Nothing changes until you press Save.'
      );
      if (confirmed) {
        drafts = drafts.map((candidate) => candidate.key === draft.key ? { ...candidate, forget: true } : candidate);
      }
    } catch (e) {
      error = (e as Error).message;
    }
  }

  function undoForget(key: string) {
    drafts = drafts.map((draft) => draft.key === key ? { ...draft, forget: false } : draft);
  }

  async function save() {
    if (saving) return;
    if (activeDrafts.some((draft) => !draft.display_name.trim())) {
      error = 'Folder names cannot be blank.';
      return;
    }
    saving = true;
    error = '';
    try {
      const folders = drafts.map<FolderChange>((draft) => ({
        source_id: draft.source_id,
        path: draft.path,
        display_name: draft.display_name.trim(),
        role: draft.role,
        visible: draft.visible,
        forget: draft.forget,
      }));
      const result = await suiteApi.applyFolderChanges(folders);
      dispatch('saved', result);
      dispatch('close');
    } catch (e) {
      error = (e as Error).message;
    } finally {
      saving = false;
    }
  }

  function handleKeydown(event: KeyboardEvent) {
    if (event.key === 'Escape' && !saving && !showPicker) dispatch('close');
  }
</script>

<svelte:window on:keydown={handleKeydown} />

<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
<div class="fixed inset-0 z-[100] grid place-items-center bg-black/65 p-4" on:click={() => !saving && dispatch('close')}>
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div
    class="flex max-h-[82vh] w-[min(880px,96vw)] flex-col overflow-hidden rounded-xl border border-[#303041] bg-[#111118] shadow-2xl shadow-black/70"
    role="dialog"
    tabindex="-1"
    aria-modal="true"
    aria-labelledby="manage-folders-title"
    on:click|stopPropagation
  >
    <header class="flex items-start justify-between gap-4 border-b border-[#292937] px-5 py-4">
      <div>
        <h2 id="manage-folders-title" class="text-base font-semibold text-gray-100">Manage folders</h2>
        <p class="mt-1 text-xs text-gray-500">Rename, assign a module, or choose which folders appear in the sidebar. Changes apply together on Save.</p>
      </div>
      <button type="button" class="text-gray-500 hover:text-white disabled:opacity-40" on:click={() => dispatch('close')} disabled={saving} aria-label="Close">✕</button>
    </header>

    <div class="grid grid-cols-[minmax(180px,1.3fr)_minmax(140px,.8fr)_88px_36px] gap-3 border-b border-[#242432] px-5 py-2 text-[10px] font-semibold uppercase tracking-wide text-gray-600">
      <span>Folder name</span>
      <span>Role / module</span>
      <span class="text-center">Sidebar</span>
      <span></span>
    </div>

    <div class="min-h-[180px] flex-1 overflow-y-auto px-5 py-2">
      {#each drafts as draft (draft.key)}
        {#if draft.forget}
          <div class="my-2 flex items-center gap-3 rounded-lg border border-red-500/20 bg-red-500/[0.06] px-3 py-3 text-sm">
            <span class="min-w-0 flex-1 truncate text-gray-400"><span class="text-red-300">Will forget:</span> {draft.display_name}</span>
            <button type="button" class="text-xs text-purple-200 hover:text-purple-100" on:click={() => undoForget(draft.key)}>Undo</button>
          </div>
        {:else}
          <div class="grid grid-cols-[minmax(180px,1.3fr)_minmax(140px,.8fr)_88px_36px] items-start gap-3 border-b border-white/[0.04] py-3">
            <div class="min-w-0">
              <input
                class="h-8 w-full rounded-md border border-white/10 bg-black/30 px-2.5 text-sm text-gray-100 outline-none focus:border-purple-400/50"
                bind:value={draft.display_name}
                aria-label="Folder display name"
              />
              <div class="mt-1 truncate text-[10px] text-gray-600" title={draft.path}>{draft.path}</div>
            </div>

            <div class="min-w-0">
              <div class="flex h-8 items-center gap-2">
                {#if moduleUi(draft.role).iconSrc}
                  <img src={moduleUi(draft.role).iconSrc ?? ''} alt="" class="h-5 w-5 rounded" />
                {:else}
                  <span class="grid h-5 w-5 place-items-center text-sm">🗂️</span>
                {/if}
                <select
                  class="h-8 min-w-0 flex-1 rounded-md border border-white/10 bg-[#181821] px-2 text-xs text-gray-200 outline-none focus:border-purple-400/50"
                  bind:value={draft.role}
                  aria-label="Folder role"
                >
                  {#each roleModules(draft) as module (module.slug)}
                    <option value={module.slug}>{module.name}{module.is_base ? ' (base)' : ''}</option>
                  {/each}
                </select>
              </div>
              {#if draft.source_id && draft.role !== draft.original_role}
                <div class="mt-1 text-[10px] text-purple-300">
                  {draft.role === baseModule?.slug ? `Release to ${moduleName(draft.role)}` : `Adopt into ${moduleName(draft.role)}`}
                </div>
              {/if}
            </div>

            <div class="flex h-8 items-center justify-center">
              <button
                type="button"
                role="switch"
                aria-checked={draft.visible}
                aria-label={draft.visible ? 'Shown in sidebar' : 'Hidden from sidebar'}
                title={draft.visible ? 'Shown in sidebar' : 'Hidden from sidebar'}
                class="relative h-6 w-11 rounded-full transition-colors {draft.visible ? 'bg-purple-500/70' : 'bg-white/10'}"
                on:click={() => setVisible(draft.key, !draft.visible)}
              >
                <span class="absolute top-1 h-4 w-4 rounded-full bg-white shadow transition-all {draft.visible ? 'left-6' : 'left-1'}"></span>
              </button>
            </div>

            <button
              type="button"
              class="grid h-8 w-8 place-items-center rounded-md text-gray-600 transition-colors hover:bg-red-500/10 hover:text-red-300"
              title={draft.source_id ? 'Forget folder' : 'Remove staged folder'}
              aria-label={draft.source_id ? 'Forget folder' : 'Remove staged folder'}
              on:click={() => markForgotten(draft)}
            >✕</button>
          </div>
        {/if}
      {/each}

      {#if drafts.length === 0}
        <p class="py-8 text-center text-sm text-gray-600">No folders are registered yet.</p>
      {/if}
    </div>

    {#if error}
      <div class="mx-5 rounded-md border border-red-500/25 bg-red-500/10 px-3 py-2 text-xs text-red-300">{error}</div>
    {/if}

    <footer class="flex items-center gap-2 border-t border-[#292937] px-5 py-4">
      <button
        type="button"
        class="rounded-md border border-white/10 px-3 py-1.5 text-xs text-gray-300 transition-colors hover:bg-white/5 disabled:opacity-40"
        on:click={beginAddFolder}
        disabled={saving}
      >＋ Add folder</button>
      <span class="flex-1"></span>
      <button type="button" class="rounded-md px-3 py-1.5 text-xs text-gray-400 hover:text-white disabled:opacity-40" on:click={() => dispatch('close')} disabled={saving}>Cancel</button>
      <button
        type="button"
        class="rounded-md bg-purple-500/25 px-4 py-1.5 text-xs font-medium text-purple-100 transition-colors hover:bg-purple-500/35 disabled:opacity-40"
        on:click={save}
        disabled={saving}
      >{saving ? 'Saving…' : 'Save'}</button>
    </footer>
  </div>
</div>

{#if showPicker}
  <FolderPicker
    roots={pickerRoots}
    on:select={(event) => stagePath(event.detail)}
    on:close={() => (showPicker = false)}
  />
{/if}
