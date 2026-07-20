type CacheEntry<T> = {
  value: T;
  expiresAt: number;
};

const entries = new Map<string, CacheEntry<unknown>>();

export function getCachedView<T>(key: string): T | null {
  const entry = entries.get(key);
  if (!entry) return null;
  if (entry.expiresAt <= Date.now()) {
    entries.delete(key);
    return null;
  }
  return entry.value as T;
}

export function cacheView<T>(key: string, value: T, ttlMs = 45_000) {
  entries.set(key, { value, expiresAt: Date.now() + ttlMs });
}

export function invalidateViewCache(prefix: string) {
  for (const key of entries.keys()) {
    if (key.startsWith(prefix)) entries.delete(key);
  }
}
