<script lang="ts">
  import { onMount } from 'svelte';
  import Sidebar from './Sidebar.svelte';
  import { sidebarHandlePosition, sidebarOpen } from '../lib/stores';

  const DRAG_THRESHOLD = 4;
  const MIN_HANDLE_POSITION = 10;
  const MAX_HANDLE_POSITION = 90;

  let dockRoot: HTMLDivElement;
  let dragPointerId: number | null = null;
  let dragStartY = 0;
  let dragging = false;
  let suppressNextClick = false;
  let gripRevealed = true;
  let revealTimer: ReturnType<typeof setTimeout> | null = null;
  let introReady = false;
  let introFrame: number | null = null;

  onMount(() => {
    revealGrip(1600);
    // Render one closed frame before applying is-open so the 280ms slide
    // plays on Browse/Tags entry. rAF is deferred in hidden tabs, so the
    // intro waits until the view is actually rendered.
    introFrame = requestAnimationFrame(() => {
      introFrame = requestAnimationFrame(() => {
        introReady = true;
        introFrame = null;
      });
    });
    return () => {
      if (revealTimer !== null) clearTimeout(revealTimer);
      if (introFrame !== null) cancelAnimationFrame(introFrame);
    };
  });

  function clampPosition(value: number) {
    return Math.min(MAX_HANDLE_POSITION, Math.max(MIN_HANDLE_POSITION, value));
  }

  function revealGrip(duration = 1000) {
    gripRevealed = true;
    if (revealTimer !== null) clearTimeout(revealTimer);
    revealTimer = setTimeout(() => {
      gripRevealed = false;
      revealTimer = null;
    }, duration);
  }

  function startGripDrag(event: PointerEvent) {
    if (event.button !== 0) return;
    revealGrip(1800);
    dragPointerId = event.pointerId;
    dragStartY = event.clientY;
    dragging = false;
    (event.currentTarget as HTMLButtonElement).setPointerCapture(event.pointerId);
  }

  function moveGrip(event: PointerEvent) {
    if (event.pointerId !== dragPointerId || !dockRoot) return;
    if (Math.abs(event.clientY - dragStartY) >= DRAG_THRESHOLD) dragging = true;
    if (!dragging) return;

    const bounds = dockRoot.getBoundingClientRect();
    if (bounds.height <= 0) return;
    const nextPosition = ((event.clientY - bounds.top) / bounds.height) * 100;
    sidebarHandlePosition.set(clampPosition(nextPosition));
  }

  function finishGripDrag(event: PointerEvent) {
    if (event.pointerId !== dragPointerId) return;
    const button = event.currentTarget as HTMLButtonElement;
    if (button.hasPointerCapture(event.pointerId)) button.releasePointerCapture(event.pointerId);

    if (dragging) {
      suppressNextClick = true;
      setTimeout(() => { suppressNextClick = false; }, 0);
    }
    revealGrip(900);
    dragPointerId = null;
    dragging = false;
  }

  function cancelGripDrag(event: PointerEvent) {
    if (event.pointerId !== dragPointerId) return;
    dragPointerId = null;
    dragging = false;
  }

  function toggleSidebar() {
    if (suppressNextClick) return;
    revealGrip(1100);
    sidebarOpen.update(open => !open);
  }

  function repositionWithKeyboard(event: KeyboardEvent) {
    if (event.key !== 'ArrowUp' && event.key !== 'ArrowDown') return;
    event.preventDefault();
    const direction = event.key === 'ArrowUp' ? -5 : 5;
    sidebarHandlePosition.update(position => clampPosition(position + direction));
  }
</script>

<div
  bind:this={dockRoot}
  class="sidebar-dock relative z-30 h-full shrink-0"
  class:is-open={$sidebarOpen && introReady}
>
  <div class="sidebar-panel flex h-full overflow-hidden" aria-hidden={!$sidebarOpen} inert={!$sidebarOpen}>
    <div class="h-full w-64 shrink-0">
      <Sidebar />
    </div>
  </div>

  <div
    class="pointer-events-none absolute left-full top-0 z-20 h-full w-10"
  >
    <button
      class="sidebar-grip-hotspot pointer-events-auto absolute left-0 h-16 w-10 -translate-y-1/2 cursor-grab border-0 bg-transparent p-0"
      class:is-dragging={dragging}
      class:is-revealed={gripRevealed}
      class:cursor-grabbing={dragging}
      style={`top: ${$sidebarHandlePosition}%;`}
      type="button"
      data-sidebar-grip-hotspot
      data-sidebar-grip
      title="Drag to reposition; click to {$sidebarOpen ? 'hide' : 'show'} the library sidebar"
      aria-label="{$sidebarOpen ? 'Hide' : 'Show'} library sidebar"
      on:pointerdown={startGripDrag}
      on:pointermove={moveGrip}
      on:pointerup={finishGripDrag}
      on:pointercancel={cancelGripDrag}
      on:keydown={repositionWithKeyboard}
      on:click={toggleSidebar}
    >
      <span
        class="sidebar-grip-visual pointer-events-none absolute left-0 top-1/2 flex h-12 w-7 touch-none select-none items-center justify-center gap-0.5 rounded-r-2xl border-y border-r border-white/10 bg-gradient-to-r from-[#111118] to-[#1d1d29] px-1 text-gray-500 shadow-[5px_0_16px_rgba(0,0,0,0.28)] group-hover:border-white/15"
        aria-hidden="true"
      >
        <span class="flex flex-col gap-0.5 text-current opacity-35" aria-hidden="true">
          <span class="h-0.5 w-0.5 rounded-full bg-current"></span>
          <span class="h-0.5 w-0.5 rounded-full bg-current"></span>
          <span class="h-0.5 w-0.5 rounded-full bg-current"></span>
        </span>
        <svg class="h-4 w-4 shrink-0 transition-transform duration-300 {$sidebarOpen ? '' : 'rotate-180'}" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
        </svg>
      </span>
    </button>
  </div>
</div>

<style>
  .sidebar-dock {
    width: 0;
    transition: width 280ms cubic-bezier(0.2, 0.8, 0.2, 1);
    will-change: width;
  }

  .sidebar-dock.is-open {
    width: 16rem;
  }

  .sidebar-panel {
    width: 16rem;
    transform: translate3d(-100%, 0, 0);
    transition: transform 280ms cubic-bezier(0.2, 0.8, 0.2, 1);
    will-change: transform;
  }

  .sidebar-dock.is-open .sidebar-panel {
    transform: translate3d(0, 0, 0);
  }

  .sidebar-dock:not(.is-open) .sidebar-panel {
    pointer-events: none;
  }

  .sidebar-grip-visual {
    opacity: 0;
    transform: translate3d(-8px, -50%, 0) scale(0.9);
    transform-origin: left center;
    transition:
      opacity 140ms ease-out,
      transform 180ms cubic-bezier(0.2, 0.8, 0.2, 1),
      background-color 140ms ease,
      border-color 140ms ease,
      color 140ms ease;
    will-change: opacity, transform;
  }

  .sidebar-grip-hotspot:hover .sidebar-grip-visual,
  .sidebar-grip-hotspot:focus-visible .sidebar-grip-visual,
  .sidebar-grip-hotspot.is-revealed .sidebar-grip-visual,
  .sidebar-grip-hotspot.is-dragging .sidebar-grip-visual {
    opacity: 1;
    transform: translate3d(0, -50%, 0) scale(1);
  }

  .sidebar-grip-hotspot:hover .sidebar-grip-visual,
  .sidebar-grip-hotspot:focus-visible .sidebar-grip-visual {
    border-color: rgb(255 255 255 / 0.15);
    color: rgb(233 213 255);
  }

  .sidebar-grip-hotspot.is-dragging .sidebar-grip-visual {
    border-color: rgb(192 132 252 / 0.35);
    color: rgb(233 213 255);
    transform: translate3d(0, -50%, 0) scale(1.05);
  }

  .sidebar-grip-hotspot:focus-visible {
    outline: none;
  }
</style>
