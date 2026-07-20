export type SettingsModalModule = typeof import('../components/AppSettingsModal.svelte');

let settingsModalPromise: Promise<SettingsModalModule> | null = null;

export function loadSettingsModal(): Promise<SettingsModalModule> {
  settingsModalPromise ??= import('../components/AppSettingsModal.svelte');
  return settingsModalPromise;
}
