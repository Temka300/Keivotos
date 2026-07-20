<script lang="ts">
  import { api } from '../lib/api';
  import {
    activeFolder,
    activeRating,
    activeTags,
    blacklistedTagNames,
    searchString,
    sortBy,
    sortOrder,
    viewMode,
  } from '../lib/stores';
  import HomeBreadcrumbBack from './HomeBreadcrumbBack.svelte';
  import ImageGrid from './ImageGrid.svelte';

  type PeriodMode = 'day' | 'month' | 'year';

  const modes: { value: PeriodMode; label: string }[] = [
    { value: 'day', label: 'Date' },
    { value: 'month', label: 'Month' },
    { value: 'year', label: 'Year' },
  ];
  const dateFilterPrefixes = [
    'created:',
    'created_at:',
    'created_date:',
    'uploaded:',
    'uploaded_at:',
    'upload_date:',
  ];

  let mode: PeriodMode = 'day';
  let selectedDate = '';
  let loadingDefault = false;
  let defaultLoadKey = '';
  let appliedFilterKey = '';
  let initializedFromTags = false;
  let currentBaseTags: string[] = [];
  let currentPeriodFilter = '';

  function isDateFilter(tag: string) {
    const normalized = tag.startsWith('-') ? tag.slice(1) : tag;
    return dateFilterPrefixes.some(prefix => normalized.startsWith(prefix));
  }

  function dateFilterValue(tag: string) {
    const normalized = tag.startsWith('-') ? tag.slice(1) : tag;
    const prefix = dateFilterPrefixes.find(value => normalized.startsWith(value));
    return prefix ? normalized.slice(prefix.length) : '';
  }

  function dateFromFilter(tags: string[]) {
    const tag = tags.find(isDateFilter);
    const match = tag ? dateFilterValue(tag).match(/\d{4}-\d{2}-\d{2}/) : null;
    return match ? match[0] : '';
  }

  function parseDate(value: string) {
    const match = value.match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (!match) return null;
    return new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
  }

  function isoDate(date: Date) {
    return date.toISOString().slice(0, 10);
  }

  function addPeriod(delta: number) {
    const date = parseDate(selectedDate);
    if (!date) return;
    if (mode === 'day') {
      date.setUTCDate(date.getUTCDate() + delta);
    } else if (mode === 'month') {
      date.setUTCDate(1);
      date.setUTCMonth(date.getUTCMonth() + delta);
    } else {
      date.setUTCMonth(0, 1);
      date.setUTCFullYear(date.getUTCFullYear() + delta);
    }
    selectedDate = isoDate(date);
  }

  function monthEnd(date: Date) {
    return new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth() + 1, 0));
  }

  function periodBounds(dateValue = selectedDate, periodMode = mode) {
    const date = parseDate(dateValue);
    if (!date) return null;
    if (periodMode === 'year') {
      const year = date.getUTCFullYear();
      return { start: `${year}-01-01`, end: `${year}-12-31` };
    }
    if (periodMode === 'month') {
      const start = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), 1));
      return { start: isoDate(start), end: isoDate(monthEnd(start)) };
    }
    return { start: dateValue, end: dateValue };
  }

  function periodFilter(dateValue: string, periodMode: PeriodMode) {
    const bounds = periodBounds(dateValue, periodMode);
    if (!bounds) return '';
    if (periodMode === 'day') return `created:${bounds.start}`;
    return `created:${bounds.start}..${bounds.end}`;
  }

  function baseSearchTags(tags: string[]) {
    return tags.filter(tag => !isDateFilter(tag));
  }

  function applyPeriodFilter(filter: string, baseTags: string[]) {
    if (!filter) return;
    const nextKey = `${mode}|${filter}|${baseTags.join('\n')}`;
    if (nextKey === appliedFilterKey) return;
    appliedFilterKey = nextKey;
    activeTags.set([...baseTags, filter]);
    sortBy.set('score');
    sortOrder.set('desc');
  }

  function blacklistParam(tags: string[]) {
    return tags.length ? tags.join(',') : undefined;
  }

  async function loadDefaultPeriod() {
    const requestKey = JSON.stringify([
      mode,
      baseSearchTags($activeTags).join(' '),
      $activeFolder,
      $activeRating,
      $blacklistedTagNames,
    ]);
    if (requestKey === defaultLoadKey || loadingDefault) return;
    defaultLoadKey = requestKey;
    loadingDefault = true;
    try {
      const result = await api.getPopularityPeriods({
        period: mode,
        q: baseSearchTags($activeTags).join(' ') || undefined,
        folder: $activeFolder || undefined,
        rating: $activeRating || undefined,
        blacklist: blacklistParam($blacklistedTagNames),
        limit: 1,
      });
      selectedDate = result[0]?.start_date ?? '';
    } catch (e) {
      console.error('Failed to load popularity period:', e);
      selectedDate = '';
    } finally {
      loadingDefault = false;
    }
  }

  function setMode(nextMode: PeriodMode) {
    if (mode === nextMode) return;
    mode = nextMode;
    if (!selectedDate) {
      defaultLoadKey = '';
      loadDefaultPeriod();
    }
  }

  function goHome() {
    viewMode.set('home');
  }

  function formatMainLabel(dateValue: string, periodMode: PeriodMode) {
    const date = parseDate(dateValue);
    if (!date) return 'No created date';
    if (periodMode === 'year') {
      return String(date.getUTCFullYear());
    }
    if (periodMode === 'month') {
      return date.toLocaleDateString(undefined, { month: 'long', year: 'numeric', timeZone: 'UTC' });
    }
    return date.toLocaleDateString(undefined, {
      day: '2-digit',
      month: 'short',
      year: 'numeric',
      timeZone: 'UTC',
    });
  }

  function formatRangeLabel(dateValue: string, periodMode: PeriodMode) {
    const bounds = periodBounds(dateValue, periodMode);
    if (!bounds) return 'No created date range';
    if (bounds.start === bounds.end) return bounds.start;
    return `${bounds.start} .. ${bounds.end}`;
  }

  $: if (!initializedFromTags) {
    selectedDate = dateFromFilter($activeTags);
    initializedFromTags = true;
  }
  $: currentBaseTags = baseSearchTags($activeTags);
  $: currentPeriodFilter = periodFilter(selectedDate, mode);
  $: if (!selectedDate) {
    loadDefaultPeriod();
  }
  $: if (currentPeriodFilter) {
    applyPeriodFilter(currentPeriodFilter, currentBaseTags);
  }
</script>

<div class="flex h-full min-h-0 flex-col overflow-hidden">
  <div class="border-b border-[#2a2a3a] bg-[#13131b] px-4 py-3">
    <div class="mx-auto mb-2 flex max-w-3xl"><HomeBreadcrumbBack current="Popularity" on:back={goHome} /></div>
    <div class="mx-auto flex max-w-3xl flex-col items-center gap-2">
      <div class="flex items-center gap-1.5">
        {#each modes as opt}
          <button
            class="min-w-20 rounded-lg border px-3 py-1.5 text-sm transition-colors {mode === opt.value ? 'border-cyan-500/40 bg-cyan-600/20 text-cyan-200' : 'border-[#2a2a3a] text-gray-400 hover:bg-[#1e1e2e]'}"
            on:click={() => setMode(opt.value)}
          >{opt.label}</button>
        {/each}
      </div>

      <div class="flex w-full items-center justify-center gap-2">
        <button
          class="flex h-9 w-9 items-center justify-center rounded-lg border border-[#2a2a3a] text-gray-400 transition-colors hover:bg-[#1e1e2e] hover:text-cyan-200 disabled:cursor-not-allowed disabled:opacity-40"
          disabled={!selectedDate}
          on:click={() => addPeriod(-1)}
          title="Previous {mode === 'day' ? 'date' : mode}"
        >
          <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7"/>
          </svg>
        </button>

        <div class="min-w-0 flex-1 rounded-lg border border-[#2a2a3a] bg-[#1a1a24] px-4 py-2 text-center">
          <div class="truncate text-sm font-medium text-gray-200">
            {loadingDefault ? 'Loading...' : formatMainLabel(selectedDate, mode)}
          </div>
          <div class="truncate text-xs text-gray-500">{formatRangeLabel(selectedDate, mode)}</div>
        </div>

        <button
          class="flex h-9 w-9 items-center justify-center rounded-lg border border-[#2a2a3a] text-gray-400 transition-colors hover:bg-[#1e1e2e] hover:text-cyan-200 disabled:cursor-not-allowed disabled:opacity-40"
          disabled={!selectedDate}
          on:click={() => addPeriod(1)}
          title="Next {mode === 'day' ? 'date' : mode}"
        >
          <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/>
          </svg>
        </button>
      </div>
    </div>
  </div>

  <div class="min-h-0 flex-1">
    <ImageGrid />
  </div>
</div>
