<script lang="ts">
  import { activeTags } from '../lib/stores';
  import { api, type TagInfo } from '../lib/api';

  let inputValue = '';
  let searchInput: HTMLInputElement;
  let suggestions: TagInfo[] = [];
  let showSuggestions = false;
  let highlightedSuggestionIndex = -1;
  let debounceTimer: ReturnType<typeof setTimeout>;

  const tagPrefixes = new Set(['artist', 'character', 'copyright', 'general', 'meta', 'unknown']);
  const idPrefixes = new Set(['id', 'post', 'post_id', 'danbooru', 'danbooru_id', 'danbooru_post_id']);
  const filenamePrefixes = new Set(['filename', 'file', 'name']);
  const shapePrefixes = new Set(['shape', 'aspect', 'aspect_ratio', 'preset']);
  const shapeTerms = new Set([
    'vertical', 'portrait', 'horizontal', 'landscape', 'wide',
    'phone', 'phones', 'phone_sized', 'phone_size', 'phone_wallpaper', 'phone_wallpapers',
    'mobile', 'mobile_sized', 'mobile_wallpaper',
    'banner', 'banners', 'banner_sized', 'banner_size', 'wide_banner', 'header', 'headers',
    'logo', 'logos', 'logo_sized', 'logo_size', 'icon', 'icons', 'avatar', 'avatars', 'square',
  ]);

  function normalizeDimensionTerms(value: string): string {
    return value.replace(/(\d+)\s*[xX\u00d7]\s*(\d+)/g, '$1x$2');
  }

  function normalizeSearchTerms(value: string): string {
    return normalizeDimensionTerms(value)
      .replace(/\b(phone|mobile|banner|logo)\s+(sized?|wallpapers?)\b/gi, '$1_$2')
      .replace(/\bwide\s+banner\b/gi, 'wide_banner');
  }

  function normalizeShapeTerm(value: string): string {
    return value.trim().toLowerCase().replace(/[\s-]+/g, '_');
  }

  function pendingSuggestionQuery(term: string): string | null {
    let value = term.trim();
    if (value.startsWith('-')) value = value.slice(1);
    if (!value) return null;
    if (/^#\d*$/.test(value)) return null;
    if (/.+\.(?:jpe?g|png|webp|gif|jfif|mp4|webm)$/i.test(value)) return null;
    if (shapeTerms.has(normalizeShapeTerm(value))) return null;
    if (/^(>=|<=|>|<|=)?\d+[xX\u00d7]\d+$/.test(normalizeDimensionTerms(value))) return null;

    if (value.includes(':')) {
      const [prefix, rest] = value.split(':', 2);
      if (idPrefixes.has(prefix.toLowerCase())) return null;
      if (filenamePrefixes.has(prefix.toLowerCase())) return null;
      if (shapePrefixes.has(prefix.toLowerCase())) return null;
      if (!tagPrefixes.has(prefix.toLowerCase())) return null;
      value = rest;
    }

    return value.length >= 1 ? value : null;
  }

  function termForSuggestion(rawTerm: string, tagName: string): string {
    let value = rawTerm.trim();
    const isExclude = value.startsWith('-');
    if (isExclude) value = value.slice(1);

    if (value.includes(':')) {
      const [prefix] = value.split(':', 1);
      if (tagPrefixes.has(prefix.toLowerCase())) {
        return `${isExclude ? '-' : ''}${prefix.toLowerCase()}:${tagName}`;
      }
    }

    return `${isExclude ? '-' : ''}${tagName}`;
  }

  function onInput() {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(async () => {
      const words = normalizeSearchTerms(inputValue).trim().split(/\s+/);
      const last = words[words.length - 1] || '';
      const query = pendingSuggestionQuery(last);
      if (query) {
        try {
          suggestions = await api.suggestTags(query);
          showSuggestions = suggestions.length > 0;
          highlightedSuggestionIndex = suggestions.length > 0 ? 0 : -1;
        } catch {
          suggestions = [];
          highlightedSuggestionIndex = -1;
        }
      } else {
        suggestions = [];
        showSuggestions = false;
        highlightedSuggestionIndex = -1;
      }
    }, 250);
  }

  function commitTerms(text: string) {
    const terms = normalizeSearchTerms(text).trim().split(/\s+/).filter(Boolean);
    if (terms.length === 0) return;
    activeTags.update(existing => {
      const combined = [...existing];
      for (const t of terms) {
        if (!combined.includes(t)) combined.push(t);
      }
      return combined;
    });
    inputValue = '';
    suggestions = [];
    showSuggestions = false;
    highlightedSuggestionIndex = -1;
  }

  function selectSuggestion(tag: TagInfo) {
    const words = inputValue.trim().split(/\s+/);
    const last = words.pop() || '';
    const pending = words.join(' ');
    if (pending) commitTerms(pending);
    activeTags.update(existing =>
      existing.includes(termForSuggestion(last, tag.name)) ? existing : [...existing, termForSuggestion(last, tag.name)]
    );
    inputValue = '';
    suggestions = [];
    showSuggestions = false;
    highlightedSuggestionIndex = -1;
  }

  function onKeydown(e: KeyboardEvent) {
    if (showSuggestions && suggestions.length > 0 && e.key === 'ArrowDown') {
      e.preventDefault();
      highlightedSuggestionIndex = (highlightedSuggestionIndex + 1) % suggestions.length;
      return;
    }

    if (showSuggestions && suggestions.length > 0 && e.key === 'ArrowUp') {
      e.preventDefault();
      highlightedSuggestionIndex = highlightedSuggestionIndex <= 0
        ? suggestions.length - 1
        : highlightedSuggestionIndex - 1;
      return;
    }

    if (e.key === 'Enter') {
      if (showSuggestions && highlightedSuggestionIndex >= 0 && suggestions[highlightedSuggestionIndex]) {
        e.preventDefault();
        selectSuggestion(suggestions[highlightedSuggestionIndex]);
        return;
      }
      commitTerms(inputValue);
    }
    if (e.key === 'Escape') {
      showSuggestions = false;
      highlightedSuggestionIndex = -1;
    }
  }

  function isTextEntryTarget(target: EventTarget | null): boolean {
    if (!(target instanceof HTMLElement)) return false;
    const tagName = target.tagName.toLowerCase();
    return tagName === 'input' || tagName === 'textarea' || tagName === 'select' || target.isContentEditable;
  }

  function onWindowKeydown(e: KeyboardEvent) {
    if (isTextEntryTarget(e.target) || e.ctrlKey || e.altKey || e.metaKey) return;
    if (e.key.length !== 1) return;

    e.preventDefault();
    inputValue += e.key;
    searchInput?.focus();
    requestAnimationFrame(() => {
      const end = searchInput.value.length;
      searchInput.setSelectionRange(end, end);
    });
    onInput();
  }

  function onBlur() {
    setTimeout(() => { showSuggestions = false; }, 200);
  }

  const categoryColors: Record<string, string> = {
    artist: 'text-red-400',
    character: 'text-green-400',
    copyright: 'text-purple-400',
    general: 'text-blue-400',
    meta: 'text-yellow-400',
  };
</script>

<svelte:window on:keydown={onWindowKeydown} />

<div class="relative">
  <input
    bind:this={searchInput}
    type="text"
    bind:value={inputValue}
    on:input={onInput}
    on:keydown={onKeydown}
    on:blur={onBlur}
    on:focus={onInput}
    placeholder="Search tags, filenames, IDs, size, or shape..."
    class="w-full bg-[#1e1e2e] border border-[#2a2a3a] rounded-lg px-3 py-1.5 text-sm text-gray-200 placeholder-gray-500 outline-none focus:border-purple-500 transition-colors"
  />

  {#if showSuggestions}
    <div class="absolute z-50 top-full left-0 right-0 mt-1 bg-[#1e1e2e] border border-[#2a2a3a] rounded-lg shadow-xl max-h-64 overflow-y-auto">
      {#each suggestions as tag, i}
        <button
          class="w-full px-3 py-1.5 text-left text-sm flex justify-between items-center transition-colors {i === highlightedSuggestionIndex ? 'bg-purple-600/20' : 'hover:bg-[#2a2a3a]'}"
          on:mousedown|preventDefault={() => selectSuggestion(tag)}
          on:mouseenter={() => highlightedSuggestionIndex = i}
        >
          <span class={categoryColors[tag.category] || 'text-gray-300'}>{tag.name}</span>
          <span class="text-xs text-gray-500">{tag.category} ({tag.count})</span>
        </button>
      {/each}
    </div>
  {/if}
</div>
