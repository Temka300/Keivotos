import { persistentStorageKey } from './product';
import { persistedWritable } from './persistedStore';
import { normalizeGridSize, type GridSize } from './gridPreferences';

// Files keeps its own chosen size while sharing Danbooru's scale. The two are
// different browsing jobs - a uniform image wall versus a mixed folder of
// models, archives and documents - so one value would be wrong for one of them.
// Danbooru's existing `image-size` key is deliberately left alone: renaming it
// would silently reset the user's saved preference.
export const filesGridSize = persistedWritable<GridSize>(persistentStorageKey('files-grid-size'), 'medium', normalizeGridSize);
