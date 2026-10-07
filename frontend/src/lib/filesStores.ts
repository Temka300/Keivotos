import { persistentStorageKey } from './product';
import { persistedWritable } from './persistedStore';
import { normalizeGridSize, type GridSize } from './gridPreferences';
import { writable } from 'svelte/store';

export interface FilesLocationRequest {
  sourceId: string;
  relativePath: string;
}

// A one-use navigation request. This is view state, not a persisted preference.
export const filesLocationRequest = writable<FilesLocationRequest | null>(null);

// Files keeps its own chosen size while sharing Danbooru's scale. The two are
// different browsing jobs - a uniform image wall versus a mixed folder of
// models, archives and documents - so one value would be wrong for one of them.
// Danbooru's existing `image-size` key is deliberately left alone: renaming it
// would silently reset the user's saved preference.
export const filesGridSize = persistedWritable<GridSize>(persistentStorageKey('files-grid-size'), 'medium', normalizeGridSize);
