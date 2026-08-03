<script lang="ts">
  // A cursor-positioned right-click menu for one Files tile. It surfaces only
  // read-only actions that already exist elsewhere (the info panel's Open and
  // Reveal, plus opening the info panel itself), so it authors nothing and never
  // touches the file on disk — matching the Files base's read-only contract.
  //
  // The parent owns the target and the handlers; this component only positions
  // itself, keeps itself on-screen, and closes on the usual dismiss gestures.
  import { createEventDispatcher, onMount, tick } from 'svelte';
  import type { FileNode } from '../lib/filesApi';

  export let x: number;
  export let y: number;
  export let entry: FileNode;

  const dispatch = createEventDispatcher<{
    showinfo: void;
    open: void;
    reveal: void;
    close: void;
  }>();

  let menuEl: HTMLDivElement;
  let left = x;
  let top = y;

  onMount(async () => {
    // Measure after render so a menu opened near the right/bottom edge flips
    // back toward the cursor instead of spilling off-screen.
    await tick();
    const rect = menuEl.getBoundingClientRect();
    const margin = 8;
    if (x + rect.width + margin > window.innerWidth) left = Math.max(margin, x - rect.width);
    if (y + rect.height + margin > window.innerHeight) top = Math.max(margin, y - rect.height);
  });

  function close(): void {
    dispatch('close');
  }

  function onKey(event: KeyboardEvent): void {
    if (event.key === 'Escape') close();
  }

  function choose(action: 'showinfo' | 'open' | 'reveal'): void {
    dispatch(action);
    close();
  }
</script>

<!-- Any click, another right-click, Escape, resize, or a scroll anywhere (the
     grid scrolls inside its own container, so capture catches it) dismisses. -->
<svelte:window
  on:click={close}
  on:contextmenu={close}
  on:keydown={onKey}
  on:resize={close}
  on:scroll|capture={close}
/>

<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
<div
  bind:this={menuEl}
  class="fixed z-[60] min-w-44 overflow-hidden rounded-lg border border-[#2a2a3a] bg-[#1e1e2e] py-1 shadow-xl"
  style="left: {left}px; top: {top}px;"
  role="menu"
  tabindex="-1"
  on:click|stopPropagation
  on:contextmenu|stopPropagation|preventDefault
>
  <div class="truncate px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wide text-gray-500" title={entry.name}>
    {entry.name}
  </div>
  <button
    type="button"
    role="menuitem"
    class="flex w-full items-center gap-2.5 px-3 py-1.5 text-sm text-gray-300 transition-colors hover:bg-[#2a2a3a] hover:text-white"
    on:click={() => choose('showinfo')}
  >
    <svg class="h-4 w-4 shrink-0 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" d="M12 8h.01M11 12h1v4h1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
    </svg>
    Show info
  </button>
  <button
    type="button"
    role="menuitem"
    class="flex w-full items-center gap-2.5 px-3 py-1.5 text-sm text-gray-300 transition-colors hover:bg-[#2a2a3a] hover:text-white"
    on:click={() => choose('open')}
  >
    <svg class="h-4 w-4 shrink-0 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" d="M14 4h6m0 0v6m0-6L10 14M10 4H6a2 2 0 00-2 2v12a2 2 0 002 2h12a2 2 0 002-2v-4" />
    </svg>
    Open
  </button>
  <button
    type="button"
    role="menuitem"
    class="flex w-full items-center gap-2.5 px-3 py-1.5 text-sm text-gray-300 transition-colors hover:bg-[#2a2a3a] hover:text-white"
    on:click={() => choose('reveal')}
  >
    <svg class="h-4 w-4 shrink-0 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" d="M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v7a2 2 0 01-2 2H5a2 2 0 01-2-2V7z" />
    </svg>
    Open in Explorer
  </button>
</div>
