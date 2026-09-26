import { persistedWritable } from './persistedStore';
import { persistentStorageKey } from './product';

export function normalizeHideControlsSeconds(value: unknown): number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 1 && value <= 10 ? value : 5;
}

export const hideControlsSeconds = persistedWritable(
  persistentStorageKey('player-hide-controls-seconds'),
  5,
  normalizeHideControlsSeconds,
);
