import general from '../settings/settings';
import type { SettingsContribution } from '../lib/settingsTypes';

const contributions = import.meta.glob<SettingsContribution>('./*/settings.ts', {
  eager: true,
  import: 'default',
});
export const settingsContributions = [general, ...Object.values(contributions)]
  .sort((left, right) => left.order - right.order || left.group.id.localeCompare(right.group.id));
