import { SUITE_NAME } from '../lib/product';
import component from './GeneralSettings.svelte';
import type { SettingsContribution } from '../lib/settingsTypes';

const contribution: SettingsContribution = {
  group: { id: 'general', label: 'General', module: null },
  order: 0,
  component,
  sections: [
    { id: 'appearance', group: 'general', label: 'Appearance', icon: 'palette' },
    { id: 'startup', group: 'general', label: 'Startup', icon: 'window' },
    { id: 'storage', group: 'general', label: 'Storage', icon: 'folder' },
    { id: 'backup', group: 'general', label: 'Backup', icon: 'shield' },
  ],
  searchItems: [
    { id: 'motion', section: 'appearance', label: 'Interface motion', description: 'Follow the system or reduce interface animation.', keywords: ['animation', 'reduced motion', 'accessibility'] },
    { id: 'interface-scale', section: 'appearance', label: 'Interface scale', description: 'Use the default or a roomier readable scale.', keywords: ['density', 'comfortable', 'readability', 'text'] },
    { id: 'startup-module', section: 'startup', label: 'Startup destination', description: `Choose which surface ${SUITE_NAME} opens on launch.`, keywords: ['files', 'module', 'last used', 'launch', 'open'] },
    { id: 'thumbnail-cache', section: 'storage', label: 'Thumbnail cache', description: 'Manage the three derived thumbnail tiers and size limit.', keywords: ['300', '600', '1200', 'cleanup', 'cache'] },
    { id: 'backup', section: 'backup', label: 'Backup', description: `Choose protected components for the fixed ${SUITE_NAME} backup location.`, keywords: ['snapshot', 'database', 'sidecar', 'destination', 'size', 'metadata'] },
    { id: 'restore', section: 'backup', label: 'Restore', description: `Validate and restore a ${SUITE_NAME} backup bundle with rollback.`, keywords: ['recovery', 'rollback', 'backup'] },
    { id: 'local-recovery', section: 'backup', label: 'Automatic local recovery', description: 'Keep rotating user database checkpoints.', keywords: ['checkpoint', 'user sqlite', 'favorites', 'collections', 'automatic'] },
  ],
};

export default contribution;
