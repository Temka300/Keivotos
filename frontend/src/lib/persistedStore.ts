import { writable } from 'svelte/store';


export function persistedWritable<T>(key: string, fallback: T, normalize: (value: unknown) => T) {
  let initial = fallback;
  if (typeof localStorage !== 'undefined') {
    const stored = localStorage.getItem(key);
    if (stored !== null) {
      try {
        initial = normalize(JSON.parse(stored));
      } catch {
        initial = fallback;
      }
    }
  }

  const store = writable<T>(initial);
  if (typeof localStorage !== 'undefined') {
    store.subscribe(value => localStorage.setItem(key, JSON.stringify(value)));
  }
  return store;
}

export function normalizeBoolean(value: unknown): boolean {
  return typeof value === 'boolean' ? value : true;
}

export function normalizeBooleanFalse(value: unknown): boolean {
  return typeof value === 'boolean' ? value : false;
}

export function readStoredValue(key: string): unknown {
  if (typeof localStorage === 'undefined') return null;
  const stored = localStorage.getItem(key);
  if (stored === null) return null;
  try {
    return JSON.parse(stored);
  } catch {
    return null;
  }
}
