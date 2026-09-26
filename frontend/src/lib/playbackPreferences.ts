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

export type PlaybackOwner = 'video' | 'youtube';
export type LoopMode = 'off' | 'all' | 'one';
export function normalizeLoopMode(value: unknown): LoopMode {
  return value === 'all' || value === 'one' ? value : 'off';
}

const loopModes = {
  video: persistedWritable(persistentStorageKey('video-loop-mode'), 'off' as LoopMode, normalizeLoopMode),
  youtube: persistedWritable(persistentStorageKey('youtube-loop-mode'), 'off' as LoopMode, normalizeLoopMode),
};
export function loopModeFor(owner: PlaybackOwner) { return loopModes[owner]; }

function normalizeAutoNext(value: unknown): boolean { return value === true; }
const autoNextModes = {
  video: persistedWritable(persistentStorageKey('video-auto-next'), false, normalizeAutoNext),
  youtube: persistedWritable(persistentStorageKey('youtube-auto-next'), false, normalizeAutoNext),
};
export function autoNextFor(owner: PlaybackOwner) { return autoNextModes[owner]; }
