<script lang="ts">
  import { onMount } from 'svelte';
  import {
    api,
    thumbnailUrl,
    type DailyChallenge,
    type DailyChallengeOption,
    type TagInfo,
  } from '../lib/api';
  import { persistentStorageKey } from '../lib/product';
  import { activeRating, activeTags, selectedImageId, viewMode } from '../lib/stores';
  import HomeBreadcrumbBack from './HomeBreadcrumbBack.svelte';

  type ChallengeState = {
    guesses: string[];
    solved: boolean;
    revealed: boolean;
    showChoices: boolean;
  };

  type ClueBlock = {
    title: string;
    values: string[];
    unlockAt: number;
  };

  const MAX_GUESSES = 4;
  const quadrantClasses = [
    'left-0 top-0',
    'left-1/2 top-0',
    'left-0 top-1/2',
    'left-1/2 top-1/2',
  ];

  let challenge: DailyChallenge | null = null;
  let loading = false;
  let error = '';
  let guess = '';
  let guesses: string[] = [];
  let solved = false;
  let revealed = false;
  let showChoices = false;
  let suggestions: TagInfo[] = [];
  let suggestionsLoading = false;
  let message = '';
  let mounted = false;
  let loadedRatingKey: string | null = null;
  let requestSerial = 0;
  let suggestSerial = 0;
  let suggestTimer: number | null = null;

  onMount(() => {
    mounted = true;
    void loadChallenge();
  });

  function displayTag(name: string) {
    return name.replace(/_/g, ' ');
  }

  function normalizeGuess(value: string) {
    return value.trim().toLowerCase().replace(/\s+/g, '_');
  }

  function looseKey(value: string) {
    return value.toLowerCase().replace(/[^a-z0-9]+/g, '');
  }

  function storageKey(item: DailyChallenge) {
    return persistentStorageKey(`daily-challenge-v2:${item.challenge_id}`);
  }

  function loadSavedState(item: DailyChallenge) {
    guesses = [];
    solved = false;
    revealed = false;
    showChoices = false;
    if (typeof localStorage === 'undefined') return;
    const raw = localStorage.getItem(storageKey(item));
    if (!raw) return;
    try {
      const parsed = JSON.parse(raw) as Partial<ChallengeState>;
      guesses = Array.isArray(parsed.guesses) ? parsed.guesses.map(String).filter(Boolean) : [];
      solved = parsed.solved === true;
      revealed = parsed.revealed === true;
      showChoices = parsed.showChoices === true;
    } catch {
      guesses = [];
      solved = false;
      revealed = false;
      showChoices = false;
    }
  }

  function saveState() {
    if (!challenge || typeof localStorage === 'undefined') return;
    const state: ChallengeState = { guesses, solved, revealed, showChoices };
    localStorage.setItem(storageKey(challenge), JSON.stringify(state));
  }

  async function loadChallenge() {
    const requestId = ++requestSerial;
    loadedRatingKey = $activeRating ?? '';
    loading = true;
    error = '';
    message = '';
    guess = '';
    suggestions = [];
    try {
      const result = await api.getDailyChallenge({ rating: $activeRating || undefined });
      if (requestId !== requestSerial) return;
      challenge = result;
      loadSavedState(result);
    } catch (e) {
      console.error('Failed to load daily challenge:', e);
      if (requestId === requestSerial) error = 'Daily challenge is unavailable';
    } finally {
      if (requestId === requestSerial) loading = false;
    }
  }

  function queueSuggestions() {
    message = '';
    if (suggestTimer !== null) window.clearTimeout(suggestTimer);
    suggestTimer = window.setTimeout(() => void loadSuggestions(guess), 140);
  }

  async function loadSuggestions(value: string) {
    const query = value.trim();
    const requestId = ++suggestSerial;
    if (!query || query.length < 2 || finished) {
      suggestions = [];
      suggestionsLoading = false;
      return [];
    }
    suggestionsLoading = true;
    try {
      const results = await api.suggestChallengeCharacters({
        q: query,
        rating: $activeRating || undefined,
        limit: 8,
      });
      if (requestId === suggestSerial) suggestions = results;
      return results;
    } catch (e) {
      console.error('Failed to load challenge suggestions:', e);
      if (requestId === suggestSerial) suggestions = [];
      return [];
    } finally {
      if (requestId === suggestSerial) suggestionsLoading = false;
    }
  }

  async function resolveGuess(value: string) {
    if (!challenge) return null;
    const query = value.trim();
    if (!query) return null;
    const normalized = normalizeGuess(query);
    const loose = looseKey(query);
    if (normalized === challenge.answer_tag || loose === looseKey(challenge.answer_tag)) {
      return challenge.answer_tag;
    }

    const results = await api.suggestChallengeCharacters({
      q: query,
      rating: $activeRating || undefined,
      limit: 8,
    });
    suggestions = results;
    const exact = results.find(item => item.name === normalized || looseKey(item.name) === loose);
    if (exact) return exact.name;
    if (results.length === 1) return results[0].name;
    message = results.length
      ? 'Pick the exact character from the suggestions.'
      : 'No local character tag matches that guess.';
    return null;
  }

  async function submitGuess(value = guess) {
    if (!challenge || finished) return;
    const resolved = await resolveGuess(value);
    if (!resolved) return;
    if (guesses.includes(resolved)) {
      message = 'Already guessed.';
      guess = '';
      suggestions = [];
      return;
    }

    guesses = [...guesses, resolved];
    solved = resolved === challenge.answer_tag;
    guess = '';
    suggestions = [];
    message = solved ? 'Correct.' : 'Nope. Another quadrant and clue unlocked.';
    saveState();
  }

  function revealAnswer() {
    if (!challenge) return;
    revealed = true;
    message = 'Answer revealed.';
    saveState();
  }

  function toggleChoices() {
    showChoices = !showChoices;
    saveState();
  }

  function openImage() {
    if (challenge && finished) selectedImageId.set(challenge.image.id);
  }

  function browseAnswer() {
    if (!challenge) return;
    activeTags.set([challenge.answer_tag]);
    viewMode.set('gallery');
  }

  function goHome() {
    viewMode.set('home');
  }

  function optionGuessed(option: DailyChallengeOption) {
    return guesses.includes(option.name);
  }

  function optionClass(option: DailyChallengeOption) {
    const isAnswer = option.name === challenge?.answer_tag;
    if ((solved || revealed) && isAnswer) return 'border-emerald-500/45 bg-emerald-500/15 text-emerald-100';
    if (optionGuessed(option)) return 'border-red-500/35 bg-red-500/10 text-red-200';
    return 'border-[#343447] bg-[#171721] text-gray-300 hover:border-pink-500/40 hover:text-pink-100';
  }

  function ratingLabel(value: string | null) {
    if (value === 'g') return 'General';
    if (value === 's') return 'Sensitive';
    if (value === 'q') return 'Questionable';
    if (value === 'e') return 'Explicit';
    return value ?? 'Unknown';
  }

  $: wrongGuesses = challenge ? guesses.filter(item => item !== challenge?.answer_tag).length : 0;
  $: remaining = Math.max(0, MAX_GUESSES - guesses.length);
  $: finished = solved || revealed || wrongGuesses >= MAX_GUESSES;
  $: visibleQuadrants = finished ? 4 : Math.min(4, wrongGuesses + 1);
  $: resultText = solved ? 'Solved' : revealed ? 'Revealed' : `${remaining} ${remaining === 1 ? 'try' : 'tries'} left`;
  $: clueBlocks = challenge
    ? [
        { title: 'Series', values: challenge.clues.copyrights.map(displayTag), unlockAt: 1 },
        { title: 'Artist', values: challenge.clues.artists.map(displayTag), unlockAt: 2 },
        { title: 'Visual Tags', values: challenge.clues.general.slice(0, 6).map(displayTag), unlockAt: 3 },
        {
          title: 'Post Info',
          values: [
            challenge.clues.year ? `Created ${challenge.clues.year}` : '',
            challenge.clues.rating ? ratingLabel(challenge.clues.rating) : '',
            challenge.clues.score !== null ? `Score ${challenge.clues.score}` : '',
          ].filter(Boolean),
          unlockAt: 4,
        },
      ] satisfies ClueBlock[]
    : [];
  $: if (challenge && wrongGuesses >= MAX_GUESSES && !solved && !revealed) {
    revealed = true;
    saveState();
  }
  $: if (mounted && loadedRatingKey !== ($activeRating ?? '')) void loadChallenge();
</script>

<div class="h-full overflow-y-auto bg-[#0b0b10]">
  <div class="mx-auto flex min-h-full max-w-7xl flex-col gap-3 px-4 py-3">
    <div class="flex"><HomeBreadcrumbBack current="Challenge" on:back={goHome} /></div>
    <header class="flex flex-wrap items-center justify-between gap-3">
      <div class="flex items-center gap-3">
        <div class="grid h-10 w-10 place-items-center rounded-xl border border-pink-500/25 bg-pink-500/10 text-pink-200 shadow-[0_0_30px_rgba(236,72,153,0.08)]">
          <svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" d="M12 3l2.2 4.8 5.2.6-3.8 3.5 1 5.1L12 14.4 7.4 17l1-5.1-3.8-3.5 5.2-.6L12 3z" /></svg>
        </div>
        <div>
          <div class="text-[10px] font-semibold uppercase tracking-[0.24em] text-pink-300/75">Daily Danbooru Challenge</div>
          <h2 class="text-2xl font-semibold leading-tight text-gray-100">Guess the Character</h2>
        </div>
      </div>
      <div class="flex items-center gap-3 rounded-xl border border-[#282838] bg-[#13131a] px-3 py-2">
        <span class="text-xs text-gray-500">{challenge?.date ?? 'Today'}</span>
        <span class="h-4 w-px bg-[#303040]"></span>
        <span class="text-sm font-semibold text-gray-200">{resultText}</span>
      </div>
    </header>

    {#if error}
      <div class="rounded-xl border border-red-500/30 bg-red-600/10 px-4 py-3 text-sm text-red-200">{error}</div>
    {:else if loading || !challenge}
      <div class="grid flex-1 gap-3 xl:grid-cols-[minmax(0,1fr)_390px]">
        <div class="min-h-[420px] animate-pulse rounded-2xl bg-[#171721]"></div>
        <div class="min-h-[420px] animate-pulse rounded-2xl bg-[#171721]"></div>
      </div>
    {:else}
      <div class="grid flex-1 items-start gap-3 xl:grid-cols-[minmax(0,1fr)_390px]">
        <section class="relative min-w-0 overflow-hidden rounded-2xl border border-[#2b2b3d] bg-black shadow-2xl shadow-black/30">
          <button
            class="relative flex aspect-[16/10] max-h-[calc(100vh-132px)] min-h-[420px] w-full items-center justify-center overflow-hidden bg-black focus:outline-none"
            type="button"
            on:click={openImage}
            disabled={!finished}
            title={finished ? 'Open image detail' : 'Finish the challenge to open the image'}
          >
            <img
              src={thumbnailUrl(challenge.image.file_id, 1200, challenge.image.thumbnail_token)}
              alt="Daily challenge"
              class="h-full w-full object-contain"
              decoding="async"
            />

            {#each quadrantClasses as position, index}
              <div
                class="absolute h-1/2 w-1/2 origin-center overflow-hidden border-black/60 bg-[#08080d] transition-all duration-500 ease-out {position} {index < visibleQuadrants ? 'pointer-events-none scale-[0.98] opacity-0' : 'scale-100 opacity-100'}"
              >
                <div class="absolute inset-0 bg-[radial-gradient(circle_at_30%_25%,rgba(236,72,153,.09),transparent_35%),linear-gradient(135deg,rgba(255,255,255,.025),transparent_45%)]"></div>
                <div class="absolute inset-3 rounded-xl border border-dashed border-white/[0.035]"></div>
              </div>
            {/each}

            <div class="pointer-events-none absolute inset-x-0 top-0 flex items-start justify-between bg-gradient-to-b from-black/70 to-transparent p-3">
              <div class="flex gap-1.5">
                {#each Array(MAX_GUESSES) as _, index}
                  <span class="h-2 w-8 rounded-full {index < guesses.length ? (guesses[index] === challenge.answer_tag ? 'bg-emerald-400' : 'bg-pink-500') : 'bg-white/15'}"></span>
                {/each}
              </div>
              <span class="rounded-full border border-white/10 bg-black/45 px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-gray-300 backdrop-blur">
                {visibleQuadrants}/4 visible
              </span>
            </div>

            {#if finished}
              <div class="pointer-events-none absolute bottom-3 left-3 rounded-xl border border-emerald-500/20 bg-black/70 px-4 py-3 text-left shadow-xl backdrop-blur">
                <div class="text-[10px] uppercase tracking-[0.2em] text-emerald-300/75">Answer</div>
                <div class="mt-1 text-xl font-semibold text-white">{displayTag(challenge.answer_tag)}</div>
              </div>
            {/if}
          </button>
        </section>

        <section class="relative min-w-0 overflow-visible rounded-2xl border border-[#2b2b3d] bg-[linear-gradient(155deg,#171721_0%,#111118_52%,#18131c_100%)] p-4 shadow-xl shadow-black/20">
          <div class="mb-3 flex items-center justify-between gap-3">
            <div>
              <h3 class="text-sm font-semibold text-gray-100">Your Guess</h3>
              <div class="text-[11px] text-gray-500">{challenge.total_candidates.toLocaleString()} local characters</div>
            </div>
            <span class="rounded-full border border-[#343447] px-2.5 py-1 text-xs tabular-nums text-gray-400">{guesses.length}/{MAX_GUESSES}</span>
          </div>

          <form class="relative z-20" on:submit|preventDefault={() => submitGuess()}>
            <div class="flex gap-2">
              <input
                bind:value={guess}
                on:input={queueSuggestions}
                class="min-w-0 flex-1 rounded-xl border border-[#343447] bg-[#0d0d13] px-3 py-2.5 text-sm text-gray-100 outline-none placeholder:text-gray-600 focus:border-pink-500/60"
                placeholder="Character name..."
                autocomplete="off"
                disabled={finished}
              />
              <button class="rounded-xl border border-pink-500/35 bg-pink-600/20 px-4 text-sm font-semibold text-pink-100 transition-colors hover:bg-pink-600/30 disabled:opacity-40" type="submit" disabled={finished || !guess.trim()}>Guess</button>
            </div>

            {#if !finished && guess.trim().length >= 2 && (suggestionsLoading || suggestions.length || message)}
              <div class="absolute left-0 right-0 top-[calc(100%+6px)] overflow-hidden rounded-xl border border-[#343447] bg-[#101017] shadow-2xl">
                {#if suggestionsLoading}
                  <div class="px-3 py-2 text-sm text-gray-500">Searching...</div>
                {:else if suggestions.length}
                  {#each suggestions as item}
                    <button class="flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm text-gray-200 hover:bg-pink-500/10 hover:text-pink-100" type="button" on:click={() => submitGuess(item.name)}>
                      <span class="min-w-0 truncate">{displayTag(item.name)}</span><span class="text-xs text-gray-600">{item.count.toLocaleString()}</span>
                    </button>
                  {/each}
                {:else}
                  <div class="px-3 py-2 text-sm text-gray-500">No matching character tags</div>
                {/if}
              </div>
            {/if}
          </form>

          <div class="mt-2 flex flex-wrap items-center gap-2">
            <button class="rounded-lg border border-[#343447] px-2.5 py-1.5 text-xs text-gray-300 hover:border-pink-500/45 hover:text-pink-100 disabled:opacity-40" type="button" on:click={toggleChoices} disabled={finished}>{showChoices ? 'Hide choices' : 'Show choices'}</button>
            <button class="rounded-lg border border-[#343447] px-2.5 py-1.5 text-xs text-gray-300 hover:border-red-500/45 hover:text-red-100 disabled:opacity-40" type="button" on:click={revealAnswer} disabled={solved || revealed}>Reveal</button>
            {#if message}<span class="min-w-0 flex-1 truncate text-right text-xs {solved ? 'text-emerald-300' : 'text-gray-500'}" title={message}>{message}</span>{/if}
          </div>

          {#if showChoices && !finished}
            <div class="mt-3 grid grid-cols-2 gap-1.5">
              {#each challenge.options as option}
                <button class="min-w-0 truncate rounded-lg border px-2.5 py-1.5 text-left text-xs transition-colors {optionClass(option)}" type="button" on:click={() => submitGuess(option.name)} disabled={finished || optionGuessed(option)} title={displayTag(option.name)}>{displayTag(option.name)}</button>
              {/each}
            </div>
          {/if}

          <div class="my-4 h-px bg-gradient-to-r from-transparent via-[#343447] to-transparent"></div>

          <div class="mb-2 flex items-center justify-between">
            <h3 class="text-xs font-semibold uppercase tracking-[0.18em] text-gray-400">Clue trail</h3>
            <span class="text-[10px] text-pink-300/60">wrong guesses unlock</span>
          </div>
          <div class="grid grid-cols-2 gap-2">
            {#each clueBlocks as clue}
              {@const unlocked = finished || wrongGuesses >= clue.unlockAt}
              <div class="min-h-[74px] rounded-xl border px-3 py-2.5 {unlocked ? 'border-cyan-500/20 bg-cyan-500/[0.055]' : 'border-[#303041] bg-[#0e0e14]'}">
                <div class="flex items-center justify-between gap-2">
                  <span class="text-[10px] uppercase tracking-[0.15em] {unlocked ? 'text-cyan-200/70' : 'text-gray-600'}">{clue.title}</span>
                  {#if !unlocked}<span class="text-[9px] text-gray-700">after {clue.unlockAt}</span>{/if}
                </div>
                {#if unlocked}
                  <div class="mt-1.5 flex max-h-12 flex-wrap gap-1 overflow-hidden">
                    {#if clue.values.length}
                      {#each clue.values as value}<span class="max-w-full truncate rounded bg-cyan-500/10 px-1.5 py-0.5 text-[10px] text-cyan-100">{value}</span>{/each}
                    {:else}<span class="text-[10px] text-gray-600">No clue data</span>{/if}
                  </div>
                {:else}
                  <div class="mt-2 h-5 rounded-md bg-white/[0.025]"></div>
                {/if}
              </div>
            {/each}
          </div>

          <div class="mt-4 flex flex-wrap items-center gap-1.5">
            <span class="mr-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-gray-600">Guesses</span>
            {#if guesses.length === 0}
              <span class="text-xs text-gray-700">none yet</span>
            {:else}
              {#each guesses as item}
                <span class="max-w-40 truncate rounded-full border px-2 py-1 text-[10px] {item === challenge.answer_tag ? 'border-emerald-500/35 bg-emerald-500/10 text-emerald-100' : 'border-red-500/25 bg-red-500/[0.07] text-red-200'}" title={displayTag(item)}>{displayTag(item)}</span>
              {/each}
            {/if}
          </div>

          {#if finished}
            <div class="mt-4 flex items-center gap-2 rounded-xl border border-emerald-500/20 bg-emerald-500/[0.07] p-2">
              <div class="min-w-0 flex-1 px-1">
                <div class="text-[9px] uppercase tracking-[0.18em] text-emerald-300/70">Answer</div>
                <div class="truncate text-sm font-semibold text-emerald-100">{displayTag(challenge.answer_tag)}</div>
              </div>
              <button class="rounded-lg border border-emerald-500/20 px-2.5 py-1.5 text-xs text-emerald-100 hover:bg-emerald-500/10" type="button" on:click={openImage}>Open image</button>
              <button class="rounded-lg border border-emerald-500/20 px-2.5 py-1.5 text-xs text-emerald-100 hover:bg-emerald-500/10" type="button" on:click={browseAnswer}>Browse tag</button>
            </div>
          {/if}
        </section>
      </div>
    {/if}
  </div>
</div>
