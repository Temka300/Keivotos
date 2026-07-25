<script lang="ts">
  // The Small…Absurd size picker, sharing Danbooru's scale so "Large" means the
  // same thing everywhere. The *value* is a prop, so each surface keeps its own
  // choice; see `filesGridSize` vs `imageSize` in stores.ts.
  //
  // ``open`` is bindable so a parent that runs several mutually-exclusive menus
  // can close this one. TopBar does exactly that: its filter and page-size
  // menus clear the others when they open, which only works if it can reach
  // this flag. Left unbound (as in Files) the component just manages itself.
  import type { Writable } from 'svelte/store';
  import { imageSizeOptions, type ImageSize } from '../lib/stores';

  export let value: Writable<ImageSize>;
  export let open = false;

  function toggle(): void {
    open = !open;
  }

  function close(): void {
    open = false;
  }

  function choose(size: ImageSize): void {
    value.set(size);
    close();
  }

  $: selected = imageSizeOptions.find((option) => option.value === $value) ?? imageSizeOptions[1];
</script>

<svelte:window on:click={close} />

<div class="relative">
  <button
    type="button"
    class="grid h-9 w-9 place-items-center rounded-lg border border-[#2a2a3a] bg-[#1e1e2e] text-gray-300 transition-colors hover:border-purple-500/50 hover:text-white"
    on:click|stopPropagation={toggle}
    aria-label="Size"
    title="Size: {selected.label}"
  >
    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h6v6H4V6zm10 0h6v6h-6V6zM4 16h6v2H4v-2zm10 0h6v2h-6v-2z" />
    </svg>
  </button>

  {#if open}
    <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
    <div
      class="absolute right-0 top-full mt-1 w-40 overflow-hidden rounded-lg border border-[#2a2a3a] bg-[#1e1e2e] shadow-xl z-50"
      on:click|stopPropagation
    >
      {#each imageSizeOptions as option}
        <button
          type="button"
          class="w-full flex items-center justify-between px-3 py-1.5 text-sm transition-colors {$value === option.value ? 'text-purple-300 bg-purple-600/10' : 'text-gray-400 hover:bg-[#2a2a3a]'}"
          on:click={() => choose(option.value)}
        >
          <span>{option.label}</span>
          {#if $value === option.value}
            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
            </svg>
          {/if}
        </button>
      {/each}
    </div>
  {/if}
</div>
