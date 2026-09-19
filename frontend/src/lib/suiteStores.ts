import { writable } from 'svelte/store';
import { suiteDataApi as api } from './suiteDataApi';
import { DEFAULT_PROFILE_NAME, persistentStorageKey } from './product';
import type { SuiteModule } from './suiteApi';
import { persistedWritable, readStoredValue } from './persistedStore';

export type MotionPreference = 'system' | 'full' | 'reduced';
export type InterfaceScale = 'default' | 'comfortable';
// Which suite surface opens on launch. 'last' keeps the persisted activeModule
// (today's default); a module slug forces that module when it is enabled.
export type StartupModule = string;
const installedStartupModules = new Set(
  Object.keys(import.meta.glob('../modules/*/ui.ts')).map(path => path.split('/')[2]),
);

function normalizeMotionPreference(value: unknown): MotionPreference {
  return value === 'full' || value === 'reduced' ? value : 'system';
}

function normalizeInterfaceScale(value: unknown): InterfaceScale {
  return value === 'comfortable' ? 'comfortable' : 'default';
}

function normalizeStartupModule(value: unknown): StartupModule {
  return typeof value === 'string' && installedStartupModules.has(value) ? value : 'last';
}

export function normalizeProfileName(value: unknown): string {
  if (typeof value !== 'string') return DEFAULT_PROFILE_NAME;
  const trimmed = value.trim();
  return trimmed ? trimmed.slice(0, 40) : DEFAULT_PROFILE_NAME;
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
export const startupModule = persistedWritable<StartupModule>(persistentStorageKey('startup-module'), 'last', normalizeStartupModule);

// V1.1.0 suite shell. The persisted slug is resolved against the descriptor
// registry loaded from /api/suite/modules; unknown/disabled values fall back to
// the required base in App.svelte.
export type ActiveModule = string;
function normalizeActiveModule(value: unknown): ActiveModule {
  return typeof value === 'string' && value.trim() ? value : 'files';
}
export const activeModule = persistedWritable<ActiveModule>(
  persistentStorageKey('active-module'),
  'files',
  normalizeActiveModule,
);

// Ids of modules the user has enabled (fetched from /api/suite/modules on load).
// A module renders only when it is both the active surface AND enabled.
export const enabledModules = writable<string[]>([]);
export const suiteModules = writable<SuiteModule[]>([]);
export const motionPreference = persistedWritable<MotionPreference>(persistentStorageKey('motion-preference'), 'system', normalizeMotionPreference);
export const interfaceScale = persistedWritable<InterfaceScale>(persistentStorageKey('interface-scale'), 'default', normalizeInterfaceScale);
