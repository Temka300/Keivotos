import { writable } from 'svelte/store';

export const SETTINGS_SESSION = Symbol('settings-session');

interface SettingsHooks {
  reloadFolders?: () => Promise<void>;
  refreshImages?: () => void;
  startToolPolling?: (toolId: string) => void;
  resumeMedia?: () => boolean;
  dismissOverlay?: () => boolean;
}

// One session per open dialog. Owners retain their state while the user moves
// between sections; the shell knows only these cross-section coordination hooks.
export function createSettingsSession(pickDirectory: (path: string) => Promise<string | null>) {
  const owners = new Map<string, SettingsHooks>();
  // Child cleanup can run before the shell restores paused media. Preserve the
  // final owner decision until this dialog session itself is discarded.
  let resumeAfterUnmount = false;
  const busyOwners = writable(new Set<string>());
  const setBusy = (owner: string, busy: boolean) => busyOwners.update(current => {
    if (current.has(owner) === busy) return current;
    const next = new Set(current);
    if (busy) next.add(owner); else next.delete(owner);
    return next;
  });
  return {
    pickDirectory,
    busyOwners,
    setBusy,
    register(owner: string, hooks: SettingsHooks) {
      owners.set(owner, hooks);
      return () => {
        resumeAfterUnmount ||= Boolean(hooks.resumeMedia?.());
        owners.delete(owner);
        setBusy(owner, false);
      };
    },
    async reloadFolders() { await Promise.all([...owners.values()].map(owner => owner.reloadFolders?.())); },
    refreshImages() { for (const owner of owners.values()) owner.refreshImages?.(); },
    startToolPolling(owner: string, toolId: string) { owners.get(owner)?.startToolPolling?.(toolId); },
    resumeMedia() { return resumeAfterUnmount || [...owners.values()].some(owner => owner.resumeMedia?.()); },
    dismissOverlay() { return [...owners.values()].some(owner => owner.dismissOverlay?.()); },
    // Preserve the old overlay parent outside the scrolling/contained content.
    // The action keeps Svelte ownership and cleanup while relocating the DOM node.
    portal(node: HTMLElement) {
      const layer = node.closest('.settings-layer');
      if (!layer) throw new Error('Settings overlays require a settings layer');
      layer.appendChild(node);
      return { destroy() { node.remove(); } };
    },
  };
}
export type SettingsSession = ReturnType<typeof createSettingsSession>;
