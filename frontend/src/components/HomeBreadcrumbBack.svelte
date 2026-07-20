<script lang="ts">
  import { createEventDispatcher } from 'svelte';

  export let current: string;

  const dispatch = createEventDispatcher<{ back: void }>();
</script>

<button
  class="group inline-flex max-w-full items-center gap-2 rounded-full bg-black/35 px-3 py-1.5 text-sm text-gray-200 shadow-lg shadow-black/20 backdrop-blur-md transition-colors hover:bg-black/60 hover:text-white"
  type="button"
  aria-label="Back to Home"
  title="Back to Home"
  on:click={() => dispatch('back')}
>
  <svg class="h-4 w-4 shrink-0 text-purple-200 transition-transform group-hover:-translate-x-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7" />
  </svg>
  <span class="font-medium">Home</span>
  <span class="text-gray-500">/</span>
  <span class="truncate text-gray-400">{current}</span>
</button>
