import { persistedWritable } from './persistedStore';
import { persistentStorageKey } from './product';

export const accents = {
  purple: { name: 'Purple', color: '#a855f7', strong: '#7e22ce' },
  pink: { name: 'Pink', color: '#ec4899', strong: '#be185d' },
  cyan: { name: 'Cyan', color: '#22d3ee', strong: '#0e7490' },
  yellow: { name: 'Yellow', color: '#eab308', strong: '#854d0e' },
  blue: { name: 'Blue', color: '#3b82f6', strong: '#1d4ed8' },
  green: { name: 'Green', color: '#22c55e', strong: '#15803d' },
  orange: { name: 'Orange', color: '#f97316', strong: '#c2410c' },
} as const;
export type AccentStyle = keyof typeof accents;
export type SettingsStyle = 'modern' | 'legacy';
export const accentStyle = persistedWritable<AccentStyle>(persistentStorageKey('accent-style'), 'purple',
  value => typeof value === 'string' && Object.hasOwn(accents, value) ? value as AccentStyle : 'purple');
export const settingsStyle = persistedWritable<SettingsStyle>(persistentStorageKey('settings-style'), 'modern',
  value => value === 'legacy' ? 'legacy' : 'modern');
