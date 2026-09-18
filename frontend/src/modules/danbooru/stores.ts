import { writable, derived } from 'svelte/store';
import type { ArtistProfileAsset } from './apiTypes';
import { persistentStorageKey } from '../../lib/product';
import { persistedWritable, normalizeBoolean, normalizeBooleanFalse, readStoredValue } from '../../lib/persistedStore';
import { normalizeGridSize, type GridSize } from '../../lib/gridPreferences';


export type ViewMode = 'home' | 'profile' | 'gallery' | 'favorites' | 'collections' | 'collection-detail' | 'tags' | 'popularity' | 'timelapse' | 'challenges';
export type FitMode = 'fit' | 'contain';
export type ImagePageSize = 10 | 20 | 30 | 50 | 'all';
export type DuplicateScope = 'all' | 'same_folder' | 'different_folder';
export type MediaPlayback = 'never' | 'hover' | 'always';
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

export const imagePageSizeOptions: { value: ImagePageSize; label: string }[] = [
  { value: 10, label: '10' },
  { value: 20, label: '20' },
  { value: 30, label: '30' },
  { value: 50, label: '50' },
  { value: 'all', label: 'All' },
];

function normalizeImagePageSize(value: unknown): ImagePageSize {
  if (value === 'all') return 'all';
  if (value === 10 || value === 20 || value === 30 || value === 50) return value;
  return 10;
}

function normalizeFitMode(value: unknown): FitMode {
  return value === 'contain' ? 'contain' : 'fit';
}

function normalizeMediaPlayback(value: unknown): MediaPlayback {
  // Migrate the former boolean media-autoplay preference in place.
  if (value === true) return 'always';
  if (value === false) return 'hover';
  if (value === 'never' || value === 'hover' || value === 'always') return value;
  return 'always';
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
export const imageSize = persistedWritable<GridSize>(persistentStorageKey('image-size'), 'medium', normalizeGridSize);

export const imagePageSize = persistedWritable<ImagePageSize>(persistentStorageKey('image-page-size'), 10, normalizeImagePageSize);
export const mediaPlayback = persistedWritable<MediaPlayback>(persistentStorageKey('media-autoplay'), 'always', normalizeMediaPlayback);
export const heartSpamEnabled = persistedWritable<boolean>(persistentStorageKey('heart-spam-enabled'), false, normalizeBooleanFalse);
export const artistNotificationsEnabled = persistedWritable<boolean>(persistentStorageKey('artist-notifications-enabled'), true, normalizeBoolean);
export const artistNotificationIntervalMinutes = persistedWritable<ArtistNotificationIntervalMinutes>(persistentStorageKey('artist-notification-interval'), 15, normalizeArtistNotificationInterval);
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
