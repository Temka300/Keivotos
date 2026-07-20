export const SUITE_NAME = 'Keivotos';
export const MODULE_NAME = 'Danbooru';
export const MODULE_DISPLAY_NAME = MODULE_NAME.replace('-', ' ');
export const DISPLAY_NAME = `${SUITE_NAME} - ${MODULE_NAME}`;
export const DEFAULT_PROFILE_NAME = SUITE_NAME;

export const STORAGE_PREFIX = 'danbooru:';

const persistedSuffixes = new Set([
  'profile-name',
  'startup-view',
  'home-layout',
  'last-view',
  'active-rating',
  'browse-sort',
  'browse-sort-order',
  'sidebar-open',
  'sidebar-handle-position',
  'fit-mode',
  'image-size',
  'image-page-size',
  'media-autoplay',
  'heart-spam-enabled',
  'artist-notifications-enabled',
  'artist-notification-interval',
  'motion-preference',
  'interface-scale',
  'tag-banner-height',
]);
const persistedSuffixFamilies = ['daily-challenge-v2:', 'home:', 'tag-cover:'];

function migratePersistedStorage(): void {
  if (typeof localStorage === 'undefined') return;
  try {
    const keys = Array.from({ length: localStorage.length }, (_, index) => localStorage.key(index))
      .filter((key): key is string => key !== null);
    for (const key of keys) {
      if (key.startsWith(STORAGE_PREFIX)) continue;
      const separator = key.indexOf(':');
      if (separator < 0) continue;
      const suffix = key.slice(separator + 1);
      if (!persistedSuffixes.has(suffix) && !persistedSuffixFamilies.some(prefix => suffix.startsWith(prefix))) continue;
      const currentKey = `${STORAGE_PREFIX}${suffix}`;
      if (localStorage.getItem(currentKey) === null) {
        const value = localStorage.getItem(key);
        if (value !== null) localStorage.setItem(currentKey, value);
      }
    }
  } catch {
    // Storage can be unavailable in hardened browser contexts; defaults remain safe.
  }
}

migratePersistedStorage();

export function persistentStorageKey(suffix: string): string {
  return `${STORAGE_PREFIX}${suffix}`;
}
