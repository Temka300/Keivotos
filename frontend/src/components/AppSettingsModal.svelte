<script lang="ts">
  import { createEventDispatcher, onMount, setContext, tick } from 'svelte';
  import { enabledModules, motionPreference } from '../lib/suiteStores';
  import { prepareSettingsPresentation, restoreSettingsPresentation } from '../lib/settingsPresentation';
  import { SETTINGS_SESSION, createSettingsSession } from '../lib/settingsSession';
  import { iconPath } from '../lib/settingsControls';
  import type { SettingSearchItem } from '../lib/settingsTypes';
  import { settingsContributions } from '../modules/settings';
  import DirectoryPicker from './DirectoryPicker.svelte';
  let directoryPicker: DirectoryPicker;
  const session = createSettingsSession(path => directoryPicker.pick(path));
  setContext(SETTINGS_SESSION, session);
  const dispatch = createEventDispatcher<{ close: void }>();
  export let initialSection = 'appearance';
  let selectedSection = initialSection;
  let settingsSearch = '';
  let searchHighlightTimer: ReturnType<typeof setTimeout> | null = null;
  const sectionGroups = settingsContributions.map(owner => owner.group);
  const sections = settingsContributions.flatMap(owner => owner.sections);
  const settingSearchItems = settingsContributions.flatMap(owner => owner.searchItems);
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
  function close() {
    dispatch('close');
  }

  function handleKeydown(event: KeyboardEvent) {
    if (event.key === 'Escape') {
      if (!session.dismissOverlay()) close();
    }
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

  onMount(() => {
    prepareSettingsPresentation();
    return () => {
      if (searchHighlightTimer) clearTimeout(searchHighlightTimer);
      restoreSettingsPresentation(session.resumeMedia());
    };
  });
</script>

<DirectoryPicker bind:this={directoryPicker} />

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
      {/if}
      {#each settingsContributions as owner (owner.group.id)}
        <svelte:component this={owner.component} {selectedSection} {query} />
      {/each}

    </main>
  </div>


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

  :global(.settings-layer .settings-section-marker) {
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
      box-shadow: 0 0 0 2px color-mix(in srgb, var(--interface-accent) 78%, transparent), 0 0 28px var(--accent-glow);
      background-color: color-mix(in srgb, var(--interface-accent) 11%, transparent);
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
