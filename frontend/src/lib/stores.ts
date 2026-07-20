import { writable, derived } from 'svelte/store';
import { api, type ArtistProfileAsset } from './api';
import { DEFAULT_PROFILE_NAME, persistentStorageKey } from './product';

export type ViewMode = 'home' | 'profile' | 'gallery' | 'favorites' | 'collections' | 'collection-detail' | 'tags' | 'popularity' | 'timelapse' | 'challenges';
export type FitMode = 'fit' | 'contain';
export type ImageSize = 'small' | 'medium' | 'large' | 'huge' | 'gigantic' | 'absurd';
export type ImagePageSize = 10 | 20 | 30 | 50 | 'all';
export type DuplicateScope = 'all' | 'same_folder' | 'different_folder';
export type MediaPlayback = 'never' | 'hover' | 'always';
export type MotionPreference = 'system' | 'full' | 'reduced';
export type InterfaceScale = 'default' | 'comfortable';
export type StartupView = 'home' | 'gallery' | 'last';
export type HomeLayout = 'discovery' | 'classic';
export type ArtistNotificationIntervalMinutes = 5 | 15 | 30 | 60;

export const ratingOrder = ['g', 's', 'q', 'e', 'u'] as const;

export interface BrowseTagSelection {
  name: string;
  category: string;
  count: number;
  source: 'danbooru' | 'user';
}

export interface ImageSizeOption {
  value: ImageSize;
  label: string;
  cardWidth: number;
  maxHeight: number;
  gridMin: number;
  previewSize: number;
}

export const imageSizeOptions: ImageSizeOption[] = [
  { value: 'small', label: 'Small', cardWidth: 128, maxHeight: 192, gridMin: 128, previewSize: 360 },
  { value: 'medium', label: 'Medium', cardWidth: 192, maxHeight: 288, gridMin: 176, previewSize: 420 },
  { value: 'large', label: 'Large', cardWidth: 256, maxHeight: 384, gridMin: 240, previewSize: 520 },
  { value: 'huge', label: 'Huge', cardWidth: 340, maxHeight: 510, gridMin: 320, previewSize: 640 },
  { value: 'gigantic', label: 'Gigantic', cardWidth: 460, maxHeight: 690, gridMin: 440, previewSize: 860 },
  { value: 'absurd', label: 'Absurd', cardWidth: 640, maxHeight: 960, gridMin: 600, previewSize: 1120 },
];

export const imageSizeByValue = Object.fromEntries(
  imageSizeOptions.map(option => [option.value, option])
) as Record<ImageSize, ImageSizeOption>;

export const imagePageSizeOptions: { value: ImagePageSize; label: string }[] = [
  { value: 10, label: '10' },
  { value: 20, label: '20' },
  { value: 30, label: '30' },
  { value: 50, label: '50' },
  { value: 'all', label: 'All' },
];

function persistedWritable<T>(key: string, fallback: T, normalize: (value: unknown) => T) {
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

function normalizeImagePageSize(value: unknown): ImagePageSize {
  if (value === 'all') return 'all';
  if (value === 10 || value === 20 || value === 30 || value === 50) return value;
  return 10;
}

function normalizeFitMode(value: unknown): FitMode {
  return value === 'contain' ? 'contain' : 'fit';
}

function normalizeImageSize(value: unknown): ImageSize {
  return imageSizeOptions.some(option => option.value === value) ? value as ImageSize : 'medium';
}

function normalizeBoolean(value: unknown): boolean {
  return typeof value === 'boolean' ? value : true;
}

function normalizeBooleanFalse(value: unknown): boolean {
  return typeof value === 'boolean' ? value : false;
}

function normalizeMediaPlayback(value: unknown): MediaPlayback {
  // Migrate the former boolean media-autoplay preference in place.
  if (value === true) return 'always';
  if (value === false) return 'hover';
  if (value === 'never' || value === 'hover' || value === 'always') return value;
  return 'always';
}

function normalizeMotionPreference(value: unknown): MotionPreference {
  return value === 'full' || value === 'reduced' ? value : 'system';
}

function normalizeInterfaceScale(value: unknown): InterfaceScale {
  return value === 'comfortable' ? 'comfortable' : 'default';
}

function normalizeStartupView(value: unknown): StartupView {
  return value === 'gallery' || value === 'last' ? value : 'home';
}

function normalizeHomeLayout(value: unknown): HomeLayout {
  return value === 'classic' ? 'classic' : 'discovery';
}

function normalizeSortBy(value: unknown): string {
  return ['date', 'downloaded', 'score', 'views', 'tags', 'random', 'name', 'size'].includes(String(value))
    ? String(value)
    : 'date';
}

function normalizeSortOrder(value: unknown): string {
  return value === 'asc' ? 'asc' : 'desc';
}

function normalizeTagBannerHeight(value: unknown): number {
  if (typeof value !== 'number' || Number.isNaN(value)) return 520;
  return Math.min(720, Math.max(280, Math.round(value / 20) * 20));
}

function normalizeSidebarHandlePosition(value: unknown): number {
  if (typeof value !== 'number' || Number.isNaN(value)) return 50;
  return Math.min(90, Math.max(10, Math.round(value * 10) / 10));
}

export function ratingSelectionValues(value: string | null): string[] {
  if (!value) return [];
  const rawValues = value.includes(',') ? value.split(',') : value.split('');
  return ratingOrder.filter(rating => rawValues.includes(rating));
}

export function toggleRatingSelection(value: string | null, rating: string): string | null {
  if (!ratingOrder.includes(rating as (typeof ratingOrder)[number])) return value;
  const selected = new Set(ratingSelectionValues(value));
  if (selected.has(rating)) selected.delete(rating);
  else selected.add(rating);
  const next = ratingOrder.filter(item => selected.has(item));
  return next.length > 0 ? next.join(',') : null;
}

function normalizeRating(value: unknown): string | null {
  if (value === null) return null;
  const candidates = Array.isArray(value)
    ? value.map(String)
    : String(value).toLowerCase().split(/[,+|\s]+/).flatMap(part => part.length > 1 ? part.split('') : [part]);
  const selected = ratingOrder.filter(rating => candidates.includes(rating));
  if (selected.length > 0) return selected.join(',');
  return 'g';
}

function normalizeArtistNotificationInterval(value: unknown): ArtistNotificationIntervalMinutes {
  return value === 5 || value === 30 || value === 60 ? value : 15;
}

export function normalizeProfileName(value: unknown): string {
  if (typeof value !== 'string') return DEFAULT_PROFILE_NAME;
  const trimmed = value.trim();
  return trimmed ? trimmed.slice(0, 40) : DEFAULT_PROFILE_NAME;
}

function readStoredValue(key: string): unknown {
  if (typeof localStorage === 'undefined') return null;
  const stored = localStorage.getItem(key);
  if (stored === null) return null;
  try {
    return JSON.parse(stored);
  } catch {
    return null;
  }
}

const legacyProfileNameStorageKey = persistentStorageKey('profile-name');
const legacyProfileName = normalizeProfileName(readStoredValue(legacyProfileNameStorageKey));
const profileNameWritable = writable<string>(legacyProfileName);
let currentProfileName = legacyProfileName;
let profileNameLoad: Promise<string> | null = null;

function setCurrentProfileName(value: string) {
  currentProfileName = normalizeProfileName(value);
  profileNameWritable.set(currentProfileName);
}

async function loadProfileName(): Promise<string> {
  if (!profileNameLoad) {
    profileNameLoad = (async () => {
      const setting = await api.getUserSetting('profile_name');
      let value = normalizeProfileName(setting.value);
      if (value === DEFAULT_PROFILE_NAME && legacyProfileName !== DEFAULT_PROFILE_NAME) {
        value = normalizeProfileName((await api.putUserSetting('profile_name', legacyProfileName)).value);
      }
      setCurrentProfileName(value);
      if (typeof localStorage !== 'undefined') localStorage.removeItem(legacyProfileNameStorageKey);
      return currentProfileName;
    })().catch(error => {
      profileNameLoad = null;
      throw error;
    });
  }
  return profileNameLoad;
}

async function saveProfileName(value: string): Promise<string> {
  const previous = currentProfileName;
  const normalized = normalizeProfileName(value);
  setCurrentProfileName(normalized);
  try {
    const saved = await api.putUserSetting('profile_name', normalized);
    setCurrentProfileName(saved.value);
    if (typeof localStorage !== 'undefined') localStorage.removeItem(legacyProfileNameStorageKey);
    return currentProfileName;
  } catch (error) {
    setCurrentProfileName(previous);
    throw error;
  }
}

export const profileName = {
  subscribe: profileNameWritable.subscribe,
  load: loadProfileName,
  set: saveProfileName,
};

export const startupView = persistedWritable<StartupView>(persistentStorageKey('startup-view'), 'home', normalizeStartupView);
export const homeLayout = persistedWritable<HomeLayout>(persistentStorageKey('home-layout'), 'discovery', normalizeHomeLayout);

function initialViewMode(): ViewMode {
  const startup = normalizeStartupView(readStoredValue(persistentStorageKey('startup-view')));
  if (startup === 'gallery') return 'gallery';
  if (startup === 'last') {
    const last = readStoredValue(persistentStorageKey('last-view'));
    const safeViews: ViewMode[] = ['home', 'profile', 'gallery', 'favorites', 'collections', 'tags', 'popularity', 'timelapse', 'challenges'];
    if (safeViews.includes(last as ViewMode)) return last as ViewMode;
  }
  return 'home';
}

export const viewMode = writable<ViewMode>(initialViewMode());
if (typeof localStorage !== 'undefined') {
  viewMode.subscribe(value => {
    const safeValue = value === 'collection-detail' ? 'collections' : value;
    localStorage.setItem(persistentStorageKey('last-view'), JSON.stringify(safeValue));
  });
}
export const activeFolder = writable<string | null>(null);
export const activeFolderLabel = writable<string | null>(null);
export const activeRating = persistedWritable<string | null>(persistentStorageKey('active-rating'), 'g', normalizeRating);
export const sortBy = persistedWritable<string>(persistentStorageKey('browse-sort'), 'date', normalizeSortBy);
export const sortOrder = persistedWritable<string>(persistentStorageKey('browse-sort-order'), 'desc', normalizeSortOrder);
export const selectedImageId = writable<number | null>(null);
export const selectedArtistProfileAsset = writable<ArtistProfileAsset | null>(null);
export const visibleImageIds = writable<number[]>([]);
export const imageRefreshToken = writable(0);
export const collectionRefreshToken = writable(0);
export const tagRefreshToken = writable(0);
export const artistFollowRefreshToken = writable(0);
export const artistFocusRequest = writable<string | null>(null);
export const activeCollectionId = writable<number | null>(null);
export const sidebarOpen = persistedWritable<boolean>(persistentStorageKey('sidebar-open'), true, normalizeBoolean);
export const sidebarHandlePosition = persistedWritable<number>(persistentStorageKey('sidebar-handle-position'), 50, normalizeSidebarHandlePosition);
export const fitMode = persistedWritable<FitMode>(persistentStorageKey('fit-mode'), 'fit', normalizeFitMode);
export const imageSize = persistedWritable<ImageSize>(persistentStorageKey('image-size'), 'medium', normalizeImageSize);
export const imagePageSize = persistedWritable<ImagePageSize>(persistentStorageKey('image-page-size'), 10, normalizeImagePageSize);
export const mediaPlayback = persistedWritable<MediaPlayback>(persistentStorageKey('media-autoplay'), 'always', normalizeMediaPlayback);
export const heartSpamEnabled = persistedWritable<boolean>(persistentStorageKey('heart-spam-enabled'), false, normalizeBooleanFalse);
export const artistNotificationsEnabled = persistedWritable<boolean>(persistentStorageKey('artist-notifications-enabled'), true, normalizeBoolean);
export const artistNotificationIntervalMinutes = persistedWritable<ArtistNotificationIntervalMinutes>(persistentStorageKey('artist-notification-interval'), 15, normalizeArtistNotificationInterval);
export const motionPreference = persistedWritable<MotionPreference>(persistentStorageKey('motion-preference'), 'system', normalizeMotionPreference);
export const interfaceScale = persistedWritable<InterfaceScale>(persistentStorageKey('interface-scale'), 'default', normalizeInterfaceScale);
export const tagBannerHeight = persistedWritable<number>(persistentStorageKey('tag-banner-height'), 520, normalizeTagBannerHeight);
export const duplicatesOnly = writable(false);
export const duplicateScope = writable<DuplicateScope>('all');

export const activeTags = writable<string[]>([]);
export const blacklistedTagNames = writable<string[]>([]);
export const browseTagSelection = writable<BrowseTagSelection | null>(null);

export const searchString = derived(
  activeTags,
  ($tags) => $tags.join(' ')
);
