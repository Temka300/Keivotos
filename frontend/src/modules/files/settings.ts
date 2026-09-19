import component from './Settings.svelte';
import type { SettingsContribution } from '../../lib/settingsTypes';

const contribution: SettingsContribution = {
  group: { id: 'files', label: 'Files', module: null },
  order: 1,
  component,
  sections: [
    { id: 'roots', group: 'files', label: 'Folders', icon: 'folder' },
    { id: 'files', group: 'files', label: 'Attachments', icon: 'image' },
  ],
  searchItems: [
    { id: 'folder-roles', section: 'roots', label: 'Folders', description: `Add, re-scan, relocate, or remove folders, and assign each to Files or a module.`, keywords: ['role', 'module', 'adopt', 'release', 'sidebar', 'visible', 'assign', 'folders', 'sources', 'library', 'roots', 'rescan', 'relocate', 'remove', 'path', 'register'] },
    { id: 'attachment-location', section: 'files', label: 'Attachment storage', description: 'Choose where origin-note images and videos are saved.', keywords: ['attachment', 'image', 'video', 'origin note', 'screenshot', 'storage', 'location', 'folder', 'path'] },
  ],
};

export default contribution;
